"""Output packs (roadmap stage 66): every output of a part in one ZIP, made in the background, saved with revisions.

One click on a part (part panel → Output packs, or the Output packs page) makes pack Rev.00: the simulation and FEA jobs of
the part's tool type, then every download of the part (tool design pack, 2D drawings, 3D, strip layout, simulation reports
and videos, FEA, tool / RM / part cost of all countries, BOM, PO pack …), each saved in the database (files + output_packs),
and one ZIP of all of them with an index. It runs in the app, not in the browser: close the part window or the page and it
goes on; open the part again and the progress (0-100 %) is there. Stop ends it after the output being made.

After the first pack, every saved change of the part starts the next revision by itself (Rev.01, Rev.02 …) once the part
has not changed for AUTO_DELAY_S seconds (auto, switch off per part). Every revision stays downloadable (each file and
the ZIP). A pack that was running when the app stopped is started again when the app starts.

The pack makes its files through the app's own download addresses, logged in as the user who started it (a short service
session), so permissions and tool groups apply as everywhere; a download that does not apply to the part (e.g. a strip
layout for a mould) is listed as "not applicable" with the reason.
"""

from __future__ import annotations

import io
import json
import os
import re
import threading
import time
import zipfile
from datetime import datetime
from urllib.parse import unquote

from sqlalchemy import select

from . import projects_db as db

AUTO_DELAY_S = float(os.environ.get("DTC_PACK_DELAY_S", "120"))     # auto: start after the part has not changed this long
WATCH_S = float(os.environ.get("DTC_PACK_WATCH_S", "30"))           # how often the auto watcher looks
JOB_TIMEOUT_S = 3600
# Tables the pack's own jobs write (simulation and FEA runs): not a change of the part for the auto start.
JOB_TABLES = {"sim_runs", "tool_fea_runs", "fin_fea_part_runs", "fin_fea_runs"}
MOULDS = {"plastic", "die_casting", "foundry", "eps", "blow"}

# Columns of the output table (and folders of the ZIP), in order
GROUPS = [("design", "Tool design pack"), ("2d", "2D drawings (PDF, DXF)"), ("3d", "3D (STEP, STL, viewer)"),
          ("strip", "Strip layout"), ("sim", "Simulation"), ("fea", "FEA"), ("tool_cost", "Tool cost – all countries"),
          ("rm", "Tool breakdown & raw material"), ("part_cost", "Part cost – all countries"), ("po", "PO pack & production")]
GROUP_LABEL = dict(GROUPS)


def _get(group, path, label, weight=1.0):
    return {"group": group, "kind": "get", "path": path, "label": label, "weight": weight}


def _job(group, path, label, body=None, weight=8.0):
    return {"group": group, "kind": "job", "path": path, "label": label, "body": body or {}, "weight": weight}


COSTS = [_get("tool_cost", "tool-cost/export.xlsx", "Tool cost (Excel)"), _get("tool_cost", "tool-cost/export.pdf", "Tool cost (PDF)"),
         _get("tool_cost", "country-comparison/export.xlsx", "All countries: part and tool landed (Excel)"),
         _get("tool_cost", "country-comparison/export.pdf", "All countries: part and tool landed (PDF)"),
         _get("rm", "rm-cost/export.xlsx", "RM cost (Excel)"), _get("rm", "rm-cost/export.pdf", "RM cost (PDF)"),
         _get("part_cost", "piece-cost/export.xlsx", "Part cost (Excel)"), _get("part_cost", "piece-cost/export.pdf", "Part cost (PDF)"),
         _get("part_cost", "vs-country/export.xlsx", "Part / tool / RM cost by country, line by line (Excel)"),
         _get("part_cost", "vs-country/export.pdf", "Part / tool / RM cost by country, line by line (PDF)")]
PART_2D = [_get("2d", "drawing.pdf", "Part drawing (PDF)"), _get("2d", "drawing.dxf", "Part drawing (DXF)")]

CATALOGUE = {
    "mould": [_job("sim", "flow-simulation", "Flow simulation", {"gate_from": "design", "video": True}),
              _job("sim", "simulation/video-job", "Simulation & analysis video"),
              _job("fea", "fea", "FEA of the tool parts", weight=10.0),
              _get("design", "tool-design.zip", "Tool design release pack (ZIP)", 3),
              _get("design", "tool-design.pdf", "Tool design drawing set (PDF)", 2), _get("design", "tool-design.png", "Tool picture (PNG)"),
              _get("2d", "tool-drawing.pdf", "Tool drawing (PDF)"), _get("2d", "tool-drawing.dxf", "Tool drawing (DXF)"), *PART_2D,
              _get("3d", "tool-design.step", "3D tool (STEP)", 2), _get("3d", "tool-design.stl", "3D tool (STL)", 2),
              _get("3d", "tool-design.html", "3D viewer (HTML)", 2),
              _get("sim", "simulation/report.pdf", "Simulation report (PDF)", 2), _get("sim", "simulation/video", "Simulation video", 2),
              _get("sim", "process-parameters.pdf", "Process parameters, first trial (PDF)"),
              _get("sim", "process-parameters.xlsx", "Process parameters, first trial (Excel)"),
              {"group": "sim", "kind": "runs", "label": "Saved simulation runs (PDF, video)", "weight": 1.0},
              {"group": "fea", "kind": "fea", "path": "fea", "label": "FEA results (Excel, pictures)", "weight": 1.0},
              *COSTS, _get("po", "po-pack.zip", "PO pack (ZIP)", 2), _get("po", "production-data.xlsx", "Production data (Excel)"),
              _get("po", "drawing-data.xlsx", "Drawing data (Excel)")],
    "sheet_metal": [_job("fea", "fea", "FEA of the die parts", weight=10.0),
                    _get("design", "sheet-layout/tool-pack.pdf", "Die design pack (PDF)", 2),
                    _get("design", "tool-design.zip", "Tool design release pack (ZIP)", 3), _get("design", "tool-design.pdf", "Die drawing set (PDF)", 2),
                    _get("2d", "tool-drawing.pdf", "Tool drawing (PDF)"), _get("2d", "tool-drawing.dxf", "Tool drawing (DXF)"), *PART_2D,
                    _get("3d", "tool-design.step", "3D die (STEP)", 2), _get("3d", "tool-design.stl", "3D die (STL)", 2),
                    _get("3d", "tool-design.html", "3D viewer (HTML)", 2),
                    _get("strip", "sheet-layout/strip.dxf", "Strip layout (DXF)"), _get("strip", "sheet-layout/blank.dxf", "Developed blank (DXF)"),
                    _get("sim", "forming-simulation.pdf", "Forming simulation (PDF)", 2), _get("sim", "forming-simulation.video", "Forming simulation video", 2),
                    {"group": "fea", "kind": "fea", "path": "fea", "label": "FEA results (Excel, pictures)", "weight": 1.0},
                    *COSTS, _get("po", "po-pack.zip", "PO pack (ZIP)", 2), _get("po", "production-data.xlsx", "Production data (Excel)"),
                    _get("po", "drawing-data.xlsx", "Drawing data (Excel)")],
    "fin": [_job("fea", "fin-fea", "FEA of the fin die at the full press capacity", weight=10.0),
            _job("sim", "fin-sim", "Fin simulation (collar forming FEA, strip video)", weight=10.0),
            _get("design", "fin-design/all.zip", "Fin die release pack (ZIP)", 3), _get("design", "fin-design/po-pack.pdf", "Fin die PO pack (PDF)", 2),
            _get("2d", "fin-design/drawings.pdf", "All die part drawings (PDF)", 2), _get("2d", "fin-design/drawings-dxf.zip", "Die part drawings (DXF, ZIP)", 2),
            _get("2d", "fin-design/fin.pdf", "Fin drawing (PDF)"), _get("2d", "fin-design/fin.dxf", "Fin drawing (DXF)"),
            _get("3d", "fin-design/die.step", "3D fin die (STEP)", 2), _get("3d", "fin-design/die.stl", "3D fin die (STL)", 2),
            _get("3d", "fin-design/viewer.html", "3D viewer (HTML)", 2), _get("3d", "fin-design/fin.step", "Fin (STEP)"),
            _get("strip", "fin-design/strip.pdf", "Strip layout (PDF)"), _get("strip", "fin-design/strip.dxf", "Strip layout (DXF)"),
            {"group": "sim", "kind": "runs", "label": "Saved simulation runs (PDF, video)", "weight": 1.0},
            {"group": "fea", "kind": "fea", "path": "fin-fea", "label": "FEA results (Excel)", "weight": 1.0},
            _get("rm", "fin-design/bom.xlsx", "Fin die BOM (Excel)"), *COSTS],
    "machined": [*PART_2D, _get("design", "tool-design.zip", "Fixture release pack (ZIP)", 2),
                 _get("3d", "tool-design.step", "3D fixture (STEP)", 2), *COSTS,
                 _get("po", "production-data.xlsx", "Production data (Excel)"), _get("po", "drawing-data.xlsx", "Drawing data (Excel)")],
}

_LOCK = threading.Lock()
_QUEUE: list[int] = []                 # pack ids waiting, first = next
_STOP: set[int] = set()
_WORKER: threading.Thread | None = None
_WATCHER: threading.Thread | None = None
_PENDING: dict[int, tuple[str, float]] = {}   # auto: part id → (state seen, since)
_WAKE = threading.Event()


class PackError(Exception):
    pass


def rev_label(n: int) -> str:
    return f"Rev.{n:02d}"


def part_type(part_id: int) -> str:
    from . import register, register_setup
    d = register.part_detail(part_id, with_rm=False)
    proc = register_setup.processes().get(d.get("process") or "")
    return (proc or {}).get("part_type") or ""


def catalogue(pt: str) -> list[dict]:
    key = "mould" if pt in MOULDS else pt
    return [dict(x) for x in CATALOGUE.get(key, [*PART_2D, *COSTS])]


def columns(pt: str | None = None) -> list[dict]:
    used = {x["group"] for x in catalogue(pt)} if pt else {g for g, _ in GROUPS}
    return [{"key": g, "label": lab} for g, lab in GROUPS if g in used]


# ---------------------------------------------------------------- state ----------

def _states(part_id: int) -> tuple[dict, str, str]:
    """(state groups, full hash, auto hash without the pack's own job tables)."""
    from . import saved_files
    st = saved_files.part_state(part_id)
    return st, saved_files.state_hash(st), saved_files.state_hash({k: v for k, v in st.items() if k not in JOB_TABLES})


def _row(r) -> dict:
    d = dict(r)
    for k in ("created_at", "started_at", "finished_at"):
        if d.get(k):
            d[k] = d[k].isoformat(timespec="seconds")
    d["rev"] = rev_label(d["rev_no"])
    d["items"] = d.get("items") or []
    return d


def _public(d: dict) -> dict:
    out = {k: v for k, v in d.items() if k not in ("state",)}
    by = {}
    for i, it in enumerate(out["items"]):
        it = dict(it)
        it["n"] = i
        it.pop("body", None)
        by.setdefault(it["group"], []).append(it)
    out["groups"] = by
    return out


def packs(part_id: int) -> list[dict]:
    with db.engine().connect() as conn:
        rows = conn.execute(select(db.output_packs).where(db.output_packs.c.part_id == part_id)
                            .order_by(db.output_packs.c.rev_no.desc())).mappings().all()
    return [_row(r) for r in rows]


def get_pack(part_id: int, pack_id: int) -> dict:
    with db.engine().connect() as conn:
        r = conn.execute(select(db.output_packs).where((db.output_packs.c.id == pack_id) & (db.output_packs.c.part_id == part_id))).mappings().first()
    if not r:
        raise PackError("No such output pack.")
    return _row(r)


def auto_on(part_id: int) -> bool:
    with db.engine().connect() as conn:
        r = conn.execute(select(db.output_pack_auto.c.enabled).where(db.output_pack_auto.c.part_id == part_id)).first()
    return bool(r and r[0])


def set_auto(part_id: int, enabled: bool) -> dict:
    with db.engine().begin() as conn:
        conn.execute(db.output_pack_auto.delete().where(db.output_pack_auto.c.part_id == part_id))
        conn.execute(db.output_pack_auto.insert().values(part_id=part_id, enabled=bool(enabled)))
    _PENDING.pop(part_id, None)
    return overview(part_id)


def overview(part_id: int) -> dict:
    """What the part panel shows: the columns, every revision (newest first), auto on / off, out of date."""
    pt = part_type(part_id)
    ps = packs(part_id)
    _st, _full, auto_h = _states(part_id)
    latest = ps[0] if ps else None
    out_of_date = bool(latest and latest["status"] in ("done", "failed", "stopped") and latest["auto_hash"] != auto_h)
    waiting = _PENDING.get(part_id)
    return {"part_id": part_id, "part_type": pt, "columns": columns(pt), "auto": auto_on(part_id), "out_of_date": out_of_date,
            "auto_in_s": max(0, round(AUTO_DELAY_S - (time.time() - waiting[1]))) if waiting and auto_on(part_id) else None,
            "packs": [_public(p) for p in ps]}


# ---------------------------------------------------------------- start / stop ----------

def start(part_id: int, user: dict | None, auto: bool = False, force: bool = False) -> dict:
    """Queue the next revision of the part's output pack (the latest one is returned when it is still running or queued,
    or already done on the same data, unless force)."""
    from . import saved_files
    pt = part_type(part_id)
    st, full, auto_h = _states(part_id)
    ps = packs(part_id)
    latest = ps[0] if ps else None
    if latest and latest["status"] in ("queued", "running"):
        return _public(latest)
    if latest and not force and latest["status"] == "done" and latest["auto_hash"] == auto_h:
        return _public(latest)
    items = [dict(x, status="waiting") for x in catalogue(pt)]
    d = _detail(part_id)
    with db.engine().begin() as conn:
        res = conn.execute(db.output_packs.insert().values(
            part_id=part_id, rev_no=(latest["rev_no"] + 1) if latest else 0, status="queued", progress=0.0, step="Waiting to start",
            items=items, state=st, state_hash=full, auto_hash=auto_h, design_stage=d.get("status") or "",
            changed=saved_files.what_changed(latest.get("state") if latest else None, st) if latest else "first pack",
            auto=bool(auto), part_type=pt, user_id=(user or {}).get("id"),
            created_by=(user or {}).get("username") or (user or {}).get("name") or "local user"))
        pid = res.inserted_primary_key[0]
        if not auto:                            # your click switches auto on for this part (switch it off on the panel)
            conn.execute(db.output_pack_auto.delete().where(db.output_pack_auto.c.part_id == part_id))
            conn.execute(db.output_pack_auto.insert().values(part_id=part_id, enabled=True))
    _PENDING.pop(part_id, None)
    with _LOCK:
        _QUEUE.append(pid)
    _ensure_threads()
    _WAKE.set()
    return _public(get_pack(part_id, pid))


def stop(part_id: int, pack_id: int) -> dict:
    p = get_pack(part_id, pack_id)
    if p["status"] in ("queued", "running"):
        with _LOCK:
            if pack_id in _QUEUE:
                _QUEUE.remove(pack_id)
                _update(pack_id, status="stopped", step="Stopped before it started", finished_at=datetime.utcnow())
            else:
                _STOP.add(pack_id)
    return _public(get_pack(part_id, pack_id))


def _detail(part_id: int) -> dict:
    from . import register
    return register.part_detail(part_id, with_rm=False)


def _update(pack_id: int, **values) -> None:
    with db.engine().begin() as conn:
        conn.execute(db.output_packs.update().where(db.output_packs.c.id == pack_id).values(**values))


# ---------------------------------------------------------------- the worker ----------

def _ensure_threads() -> None:
    global _WORKER, _WATCHER
    with _LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_work_loop, name="output-packs", daemon=True)
            _WORKER.start()
        if _WATCHER is None or not _WATCHER.is_alive():
            _WATCHER = threading.Thread(target=_watch_loop, name="output-pack-auto", daemon=True)
            _WATCHER.start()


def _work_loop() -> None:
    while True:
        with _LOCK:
            pid = _QUEUE.pop(0) if _QUEUE else None
        if pid is None:
            _WAKE.wait(5)
            _WAKE.clear()
            continue
        try:
            _run(pid)
        except Exception as exc:  # noqa: BLE001 - a pack never stops the worker
            _update(pid, status="failed", error=str(exc)[:500], finished_at=datetime.utcnow())


def _service_cookie(user_id: int | None) -> dict:
    """A short login of the user who started the pack (server mode), so the downloads see that user's permissions."""
    from . import auth
    if not auth.server_mode() or not user_id:
        return {}
    import secrets
    from datetime import timedelta
    token = secrets.token_urlsafe(32)
    with db.engine().begin() as conn:
        conn.execute(db.sessions.insert().values(token_hash=auth._hash(token), user_id=user_id,
                                                 expires_at=datetime.utcnow() + timedelta(hours=6)))
    return {auth.COOKIE: token}


def _end_session(cookies: dict) -> None:
    from . import auth
    tok = cookies.get(auth.COOKIE)
    if tok:
        with db.engine().begin() as conn:
            conn.execute(db.sessions.delete().where(db.sessions.c.token_hash == auth._hash(tok)))


def _filename(resp, path: str) -> str:
    cd = resp.headers.get("content-disposition") or ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
    if m:
        return unquote(m.group(1)).strip()
    tail = path.rsplit("/", 1)[-1]
    ext = {"video/mp4": ".mp4", "image/gif": ".gif", "application/pdf": ".pdf"}.get((resp.headers.get("content-type") or "").split(";")[0], "")
    return tail + ("" if "." in tail else ext)


def _detail_text(resp) -> str:
    try:
        d = resp.json().get("detail")
    except Exception:  # noqa: BLE001
        d = None
    return str(d or resp.text[:200] or f"HTTP {resp.status_code}")[:300]


def _store(content: bytes, name: str) -> int:
    from . import file_store
    with db.engine().begin() as conn:
        return file_store.put(content, name, "output_pack", conn)["id"]


def _fea_excel(data: dict, title: str) -> bytes:
    """The FEA results of the part (JSON of …/fea or …/fin-fea) as an Excel table: one row per stored run."""
    from openpyxl import Workbook
    rows: list[dict] = []

    def walk(x, path=""):
        if isinstance(x, dict):
            if ("ok" in x or "max_stress_mpa" in x or "result" in x) and any(k in x for k in ("name", "item", "key", "kind")):
                flat = {k: v for k, v in x.items() if not isinstance(v, (dict, list))}
                res = x.get("result") if isinstance(x.get("result"), dict) else {}
                flat |= {f"result {k}": v for k, v in res.items() if not isinstance(v, (dict, list))}
                rows.append({"where": path} | flat)
                return
            for k, v in x.items():
                walk(v, f"{path}/{k}" if path else str(k))
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}[{i}]")
    walk(data)
    wb = Workbook()
    ws = wb.active
    ws.title = "FEA results"
    ws.append([title])
    if not rows:
        ws.append(["No FEA run stored for this part yet (FEA programs missing, or nothing to check)."])
    else:
        keys = []
        for r in rows:
            keys += [k for k in r if k not in keys]
        ws.append(keys)
        for r in rows:
            ws.append([json.dumps(r.get(k)) if isinstance(r.get(k), (dict, list)) else r.get(k) for k in keys])
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _run(pack_id: int) -> None:
    from fastapi.testclient import TestClient
    from .main import app
    with db.engine().connect() as conn:
        p = conn.execute(select(db.output_packs).where(db.output_packs.c.id == pack_id)).mappings().first()
    if not p or p["status"] not in ("queued", "running"):
        return
    part_id = p["part_id"]
    items = [dict(x) for x in (p["items"] or [])]
    total = sum(float(x.get("weight") or 1) for x in items) or 1.0
    done_w = 0.0
    _update(pack_id, status="running", started_at=datetime.utcnow(), step="Starting")
    cookies = _service_cookie(p["user_id"])
    client = TestClient(app, cookies=cookies)
    base = f"/api/parts/{part_id}/"
    t_start = time.time()

    def progress(extra=0.0, step=None):
        pct = min(99.0, 100.0 * (done_w + extra) / total)
        vals = {"progress": round(pct, 1), "items": items}
        if step:
            vals["step"] = step
        _update(pack_id, **vals)

    def stopped() -> bool:
        return pack_id in _STOP

    key_box: dict = {}

    def design_key():
        if "k" not in key_box:
            key_box["k"] = job_key(part_id, p["part_type"] or "")
        return key_box["k"]

    def do(it):
        nonlocal done_w
        w = float(it.get("weight") or 1)
        if it.get("status") == "done":              # a pack started again after a restart: what is made stays
            done_w += w
            return
        it["status"] = "running"
        progress(step=it["label"])
        t0 = time.time()
        try:
            if it["kind"] == "job":
                prev = _reusable(part_id, pack_id, it, design_key())
                if prev:                            # stage 66b: the tool design has not changed since that run
                    it |= {"status": "done", "reused": prev["rev"], "design_key": design_key(),
                           "note": f"tool design unchanged since {prev['rev']}: its result is used", "run_id": prev.get("run_id")}
                else:
                    _do_job(client, base, it, lambda f: progress(w * f, it["label"]), stopped)
                    if it.get("status") == "done":
                        it["design_key"] = design_key()
            elif it["kind"] == "get":
                r = client.get(base + it["path"])
                if r.status_code == 200 and r.content:
                    name = _filename(r, it["path"])
                    it |= {"status": "done", "file_id": _store(r.content, name), "filename": name, "size": len(r.content)}
                else:
                    it |= {"status": "n/a", "reason": _detail_text(r)}
            elif it["kind"] == "runs":
                _do_runs(client, base, it, p["started_at"] or p["created_at"])
            elif it["kind"] == "fea":
                r = client.get(base + it["path"])
                if r.status_code == 200:
                    content = _fea_excel(r.json(), f"{it['label']} · part {part_id}")
                    it |= {"status": "done", "file_id": _store(content, "FEA_results.xlsx"), "filename": "FEA_results.xlsx",
                           "size": len(content)}
                else:
                    it |= {"status": "n/a", "reason": _detail_text(r)}
        except Exception as exc:  # noqa: BLE001 - one output failing never stops the pack
            it |= {"status": "failed", "reason": str(exc)[:300]}
        it["seconds"] = round(time.time() - t0, 1)
        done_w += w
        progress()

    try:
        # 1) the files (drawings, 3D, costs, PO pack …): quick, then a first ZIP to download at once
        files = [x for x in items if x["kind"] == "get"]
        later = [x for x in items if x["kind"] != "get"]     # simulation / FEA jobs, then their results
        for it in files:
            if stopped():
                break
            do(it)
        jobs_left = [x for x in later if x["kind"] == "job" and x.get("status") != "done"]
        if not stopped() and jobs_left and not p["zip_file_id"]:
            progress(step="Making the first ZIP (files)")
            zid, zname, zsize = _zip(part_id, pack_id, items, quick=True)
            _update(pack_id, zip_file_id=zid, zip_name=zname, zip_size=zsize, zip_stage="quick",
                    step="ZIP of the files ready; simulation and FEA running")
        # 2) simulation and FEA (reused when the tool design has not changed), then their results
        for it in sorted(later, key=lambda x: x["kind"] != "job"):
            if stopped():
                break
            do(it)
        if stopped():
            _STOP.discard(pack_id)
            _update(pack_id, status="stopped", step="Stopped by you", items=items, finished_at=datetime.utcnow())
            return
        progress(step="Making the ZIP")
        zid, zname, zsize = _zip(part_id, pack_id, items)
        _st, full, auto_h = _states(part_id)
        n_ok = sum(1 for x in items if (x.get("status") == "done" and x["kind"] != "job") or x.get("files"))
        reused = sorted({x["reused"] for x in items if x.get("reused")})
        _update(pack_id, status="done", progress=100.0, zip_stage="full",
                step=f"Ready: {n_ok} outputs in {round(time.time() - t_start)} s"
                     + (f" (simulation / FEA of {', '.join(reused)} used: design unchanged)" if reused else ""),
                items=items, zip_file_id=zid, zip_name=zname, zip_size=zsize, finished_at=datetime.utcnow(),
                end_hash=full, auto_hash=auto_h)
    finally:
        _end_session(cookies)


def _rounded(x, nd=2):
    if isinstance(x, float):
        return round(x, nd)
    if isinstance(x, (list, tuple)):
        return [_rounded(v, nd) for v in x]
    if isinstance(x, dict):
        return {str(k): _rounded(v, nd) for k, v in x.items()}
    return x


def job_key(part_id: int, pt: str) -> str | None:
    """What the simulation and FEA of the part depend on: the designed tool itself (parts, sizes, places, materials, gates,
    cooling, die set), the part's 3D revision, material, process and machine, the flow / FEA rules of master data and the
    software. A change of volume, rates or costs that leaves the tool as it was keeps the key: the results are reused."""
    import hashlib
    from . import fin_part, mould_db, register, saved_files
    try:
        d = register.part_detail(part_id, with_rm=False)
        part = {k: d.get(k) for k in ("material", "process", "current_revision_id", "fin_inputs")}
        part |= {k: v for k, v in d.items() if "machine" in k or k in ("cavity_check", "mould_typed")}
        db_ = mould_db.tables()
        mat = d.get("material")
        rules = {"design_rules": [r for r in db_.get("design_rules", []) if r.get("part_type") == pt],
                 "flow_rules": [r for r in db_.get("flow_rules", []) if r.get("part_type") == pt],
                 "flow_materials": [r for r in db_.get("flow_materials", []) if r.get("material") == mat],
                 "process_windows": [r for r in db_.get("process_windows", []) if r.get("material") == mat]}
        if pt == "fin":
            design = {"spec": fin_part.spec_for(part_id)["spec"],
                      "sizing": [r for r in db_.get("sizing_rules", []) if r.get("part_type") == pt]}
        else:
            _d, rev, designs = register.tool_designs(part_id)
            design = {"rev": rev.get("rev")}
            for k, des in designs:
                comps = []
                for c in des.get("components", []):
                    try:
                        bb = c.shape.BoundingBox()
                        size = [bb.xlen, bb.ylen, bb.zlen]
                    except Exception:  # noqa: BLE001
                        size = []
                    comps.append([c.name, getattr(c, "kind", ""), getattr(c, "material", ""), _rounded(list(getattr(c, "locs", []) or [])),
                                  _rounded(size)])
                design[k] = {"comps": comps, **{f: _rounded(des.get(f)) for f in
                                               ("die_set", "shut_height", "gates", "cooling", "internals", "motion", "systems", "name")}}
        blob = json.dumps(_rounded([part, rules, design, saved_files.software_stamp()]), default=str, sort_keys=True)
        return hashlib.sha1(blob.encode()).hexdigest()
    except Exception:  # noqa: BLE001 - no key = no reuse, the job simply runs
        return None


def _reusable(part_id: int, pack_id: int, it: dict, key: str | None) -> dict | None:
    """An earlier finished pack of the part whose same job ran (not reused from even earlier) on the same design key."""
    if not key:
        return None
    for p in packs(part_id):
        if p["id"] == pack_id or p["status"] != "done":
            continue
        for x in p["items"]:
            if x.get("kind") == "job" and x.get("path") == it.get("path") and x.get("status") == "done" and x.get("design_key") == key:
                return {"rev": x.get("reused") or p["rev"], "run_id": x.get("run_id")}
    return None


def _do_job(client, base, it, progress, stopped) -> None:
    r = client.post(base + it["path"], json=it.get("body") or {})
    if r.status_code != 200:
        it |= {"status": "n/a", "reason": _detail_text(r)}
        return
    job = r.json()
    jid = job.get("id") or job.get("job_id")
    if not jid:
        it |= {"status": "done", "note": "finished at once"}
        return
    t0 = time.time()
    while time.time() - t0 < JOB_TIMEOUT_S:
        j = client.get(f"{base}sim-jobs/{jid}")
        if j.status_code != 200:
            it |= {"status": "failed", "reason": _detail_text(j)}
            return
        j = j.json()
        progress(float(j.get("pct") or 0) / 100.0)
        if j.get("status") == "done":
            it |= {"status": "done", "note": j.get("text") or "", "run_id": j.get("run_id")}
            return
        if j.get("status") in ("failed", "error"):
            it |= {"status": "failed", "reason": str(j.get("error") or j.get("text") or "job failed")[:300]}
            return
        if stopped():
            it |= {"status": "stopped"}
            return
        time.sleep(1.0)
    it |= {"status": "failed", "reason": f"no answer within {JOB_TIMEOUT_S // 60} min"}


def _do_runs(client, base, it, since) -> None:
    """The saved simulation runs of the part: the newest of each kind (PDF and video)."""
    r = client.get(base + "sim-runs")
    if r.status_code != 200:
        it |= {"status": "n/a", "reason": _detail_text(r)}
        return
    seen, files = set(), []
    for run in r.json():
        if run["kind"] in seen or run["kind"] == "external":
            continue
        seen.add(run["kind"])
        for what in ("pdf", "video"):
            if not run.get(what):
                continue
            f = client.get(f"{base}sim-runs/{run['id']}/{what}")
            if f.status_code == 200 and f.content:
                name = _filename(f, f"{run['kind']}_{what}")
                files.append({"file_id": _store(f.content, name), "filename": name, "size": len(f.content),
                              "label": f"{run['title'] or run['kind']} ({what})"})
    if files:
        it |= {"status": "done", "files": files}
    else:
        it |= {"status": "n/a", "reason": "No saved simulation run with a report or video."}


def _bytes(file_id: int) -> bytes:
    from . import file_store
    with db.engine().connect() as conn:
        row = conn.execute(select(db.files).where(db.files.c.id == file_id)).mappings().first()
    return file_store.path_of(dict(row)).read_bytes()


def _safe(text: str) -> str:
    """A file or folder name every PC and ZIP program takes (only the characters Windows forbids are replaced)."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text).replace("–", "-").strip(" .") or "file"


STORED = (".zip", ".mp4", ".gif", ".png", ".jpg", ".jpeg", ".xlsx", ".docx")   # already compressed: stored as they are


def _zip(part_id: int, pack_id: int, items: list[dict], quick: bool = False) -> tuple[int, str, int]:
    d = _detail(part_id)
    p = get_pack(part_id, pack_id)
    root = _safe(f"{d['part_code']}_{p['rev']}_output_pack")
    bio = io.BytesIO()
    lines = [f"Output pack {p['rev']} of {d['part_code']} · {d['name']}", f"Made {datetime.now():%Y-%m-%d %H:%M} by {p['created_by']}",
             f"Design stage: {p['design_stage']}; changed: {p['changed']}",
             *(["FIRST ZIP: the files only; simulation and FEA are still running (the full ZIP replaces this one)."] if quick else []), ""]
    used: set = set()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        for gi, (g, glab) in enumerate(GROUPS, 1):
            members = [x for x in items if x["group"] == g]
            if not members:
                continue
            folder = f"{root}/{gi:02d} {_safe(glab)}"
            lines.append(f"{gi:02d} {glab}")
            for it in members:
                files = it.get("files") or ([it] if it.get("file_id") else [])
                if not files:
                    why = it.get("note") if it.get("reused") else it.get("reason", "")
                    lines.append(f"   - {it['label']}: {it.get('status')} {('(' + why + ')') if why else ''}".rstrip())
                for f in files:
                    name = _safe(f["filename"])
                    arc = f"{folder}/{name}"
                    k = 1
                    while arc in used:
                        k += 1
                        stem, dot, ext = name.rpartition(".")
                        arc = f"{folder}/{stem or name}_{k}{dot}{ext if stem else ''}"
                    used.add(arc)
                    z.writestr(arc, _bytes(f["file_id"]),
                               compress_type=zipfile.ZIP_STORED if name.lower().endswith(STORED) else zipfile.ZIP_DEFLATED)
                    lines.append(f"   ✓ {f.get('label') or it['label']}: {arc.split('/', 1)[1]}")
        z.writestr(f"{root}/00 Index.txt", "\n".join(lines) + "\n")
    content = bio.getvalue()
    name = f"{root}.zip"
    return _store(content, name), name, len(content)


# ---------------------------------------------------------------- downloads ----------

def item_file(part_id: int, pack_id: int, n: int, k: int = 0) -> tuple[bytes, str]:
    p = get_pack(part_id, pack_id)
    if not 0 <= n < len(p["items"]):
        raise PackError("No such output in this pack.")
    it = p["items"][n]
    files = it.get("files") or ([it] if it.get("file_id") else [])
    if not 0 <= k < len(files):
        raise PackError(f"{it['label']}: {it.get('reason') or 'not made'}.")
    return _bytes(files[k]["file_id"]), files[k]["filename"]


def zip_file(part_id: int, pack_id: int) -> tuple[bytes, str]:
    p = get_pack(part_id, pack_id)
    if not p.get("zip_file_id"):
        raise PackError(f"The ZIP of {p['rev']} is not ready yet ({p['progress']:.0f} %).")
    return _bytes(p["zip_file_id"]), p["zip_name"]


def listing(project_id: int | None = None, group: str = "") -> dict:
    """Output packs page: every part (of the user's tool groups) with its newest pack and all revisions."""
    from . import register_setup, scope
    g = scope.groups()
    procs = register_setup.processes()
    with db.engine().connect() as conn:
        q = select(db.parts.c.id, db.parts.c.part_code, db.parts.c.name, db.parts.c.process, db.parts.c.project_id,
                   db.parts.c.status, db.projects.c.code.label("project")).join(db.projects, db.projects.c.id == db.parts.c.project_id)
        if project_id:
            q = q.where(db.parts.c.project_id == project_id)
        parts = [dict(r) for r in conn.execute(q.order_by(db.projects.c.code, db.parts.c.part_code)).mappings()]
        rows = conn.execute(select(db.output_packs).order_by(db.output_packs.c.rev_no.desc())).mappings().all()
        allowed = {p["id"] for p in parts if scope.part_ok(conn, p["id"], g)}
    by: dict[int, list] = {}
    for r in rows:
        by.setdefault(r["part_id"], []).append(_public(_row(r)))
    out = []
    for p in parts:
        if p["id"] not in allowed:
            continue
        pt = (procs.get(p["process"] or "") or {}).get("part_type") or ""
        if group and pt != group:
            continue
        if (procs.get(p["process"] or "") or {}).get("is_assembly"):
            continue
        out.append(p | {"part_type": pt, "packs": by.get(p["id"], [])})
    return {"columns": columns(), "parts": out}


# ---------------------------------------------------------------- auto + restart ----------

def _watch_loop() -> None:
    while True:
        time.sleep(WATCH_S)
        try:
            watch_once()
        except Exception:  # noqa: BLE001 - the watcher keeps going
            pass


def watch_once(now: float | None = None) -> list[int]:
    """Auto: parts whose data changed since their newest pack and stayed unchanged for AUTO_DELAY_S get the next revision."""
    now = now or time.time()
    started = []
    with db.engine().connect() as conn:
        on = [r[0] for r in conn.execute(select(db.output_pack_auto.c.part_id).where(db.output_pack_auto.c.enabled.is_(True)))]
    for part_id in on:
        ps = packs(part_id)
        if not ps or ps[0]["status"] in ("queued", "running"):
            _PENDING.pop(part_id, None)
            continue
        try:
            _st, _full, auto_h = _states(part_id)
        except Exception:  # noqa: BLE001 - a deleted part
            continue
        if auto_h == ps[0]["auto_hash"]:
            _PENDING.pop(part_id, None)
            continue
        seen = _PENDING.get(part_id)
        if not seen or seen[0] != auto_h:
            _PENDING[part_id] = (auto_h, now)
            continue
        if now - seen[1] >= AUTO_DELAY_S:
            owner = {"id": ps[0].get("user_id"), "username": ps[0].get("created_by")}
            start(part_id, owner, auto=True, force=True)
            started.append(part_id)
    return started


def resume() -> int:
    """App start: packs that were queued or running when the app stopped run again (what was made stays)."""
    with db.engine().begin() as conn:
        rows = conn.execute(select(db.output_packs.c.id).where(db.output_packs.c.status.in_(("queued", "running")))
                            .order_by(db.output_packs.c.id)).all()
        for (pid,) in rows:
            conn.execute(db.output_packs.update().where(db.output_packs.c.id == pid).values(status="queued", step="Started again after the app restarted"))
    with _LOCK:
        for (pid,) in rows:
            if pid not in _QUEUE:
                _QUEUE.append(pid)
    _ensure_threads()
    _WAKE.set()
    return len(rows)


def wait(part_id: int, pack_id: int, timeout: float = 1800) -> dict:
    """Tests / scripts: wait until the pack is no longer queued or running."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        p = get_pack(part_id, pack_id)
        if p["status"] not in ("queued", "running"):
            return p
        time.sleep(0.5)
    return get_pack(part_id, pack_id)
