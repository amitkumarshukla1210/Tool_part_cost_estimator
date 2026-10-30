"""Long simulation work (flow simulation, videos) runs in the background with a progress bar (roadmap stage 39).

The browser starts a job and asks for its progress every 2 s, so a large part never leaves the page waiting without a word
(before: "Analysing the 3D model…" for half an hour). One job runs at a time (they use every core); the others wait their turn
and say so. The finished result is saved as a simulation run (projects_db.sim_runs) with its PDF and video, so it can be
downloaded again later without calculating again. Jobs live in the server process: a restart forgets the running ones,
never the saved runs.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dtc-sim")
_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
KEEP_S = 6 * 3600


def _public(job: dict) -> dict:
    out = {k: v for k, v in job.items() if not k.startswith("_")}
    out["elapsed_s"] = round((job["finished"] or time.time()) - job["started"], 1)
    with _LOCK:
        ahead = sum(1 for j in _JOBS.values() if j["status"] in ("queued", "running") and j["created"] < job["created"])
    if job["status"] == "queued":
        out["text"] = f"Waiting for {ahead} other simulation(s) to finish" if ahead else "Starting"
    return out


def start(part_id: int, kind: str, fn, user: str = "") -> dict:
    """Run fn(progress) in the background; progress(pct, text). fn returns the saved run's id. The same part and kind
    already queued or running: that job is returned instead of starting a second one."""
    with _LOCK:
        now = time.time()
        for k in [k for k, j in _JOBS.items() if j["finished"] and now - j["finished"] > KEEP_S]:
            del _JOBS[k]
        for j in _JOBS.values():
            if j["part_id"] == part_id and j["kind"] == kind and j["status"] in ("queued", "running"):
                return _public(j)
        job = {"id": uuid.uuid4().hex[:12], "part_id": part_id, "kind": kind, "status": "queued", "pct": 0, "text": "Starting",
               "run_id": None, "error": None, "user": user, "created": now, "started": now, "finished": None}
        _JOBS[job["id"]] = job

    def progress(pct: float, text: str) -> None:
        job["pct"] = max(job["pct"], min(99, int(pct)))
        job["text"] = text

    def work():
        from . import auth
        job["status"], job["started"] = "running", time.time()
        token = auth.set_current(job["_user"]) if job.get("_user") else None
        try:
            job["run_id"] = fn(progress)
            job["status"], job["pct"], job["text"] = "done", 100, "Done"
        except Exception as exc:  # shown to the user on the page
            job["status"], job["error"] = "failed", str(exc) or exc.__class__.__name__
            job["_trace"] = traceback.format_exc()
        finally:
            job["finished"] = time.time()
            if token is not None:
                auth.reset(token)
    from . import auth
    job["_user"] = auth.current()
    _POOL.submit(work)
    return _public(job)


def get(job_id: str, part_id: int | None = None) -> dict | None:
    j = _JOBS.get(job_id)
    if not j or (part_id is not None and j["part_id"] != part_id):
        return None
    return _public(j)


def wait(job_id: str, timeout: float = 600) -> dict | None:
    """Wait until the job ends (tests, scripts)."""
    end = time.time() + timeout
    while time.time() < end:
        j = _JOBS.get(job_id)
        if not j or j["status"] in ("done", "failed"):
            return _public(j) if j else None
        time.sleep(0.2)
    return get(job_id)
