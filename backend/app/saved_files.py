"""Saved files with revisions (roadmap stage 47).

Every file the software makes for a part - drawings, the tool design (picture, 3D viewer, STEP, STL, drawing set, release
pack), cost sheets (RM, part, tool, country comparison), simulation reports and videos, PO pack, production data … - is
saved in the database (projects_db.saved_files, the bytes in the storage folder, so a backup holds them) the first time it
is made. Asked for again, the saved file is handed out at once, also after the app was closed and opened again, as long as
the data it was made from has not changed. After a change the file is marked out of date; the next revision is made when it
is asked for and saved next to the earlier ones (they stay downloadable: part panel -> Saved files).

"The data it was made from" is the state of the part (part_state): the part row and its project, every table that belongs
to the part (revisions, tool costs, inserts, drawing data, reviews, machine, cavities, mould systems, simulation runs …),
the linked insert parts, the master data and rates files, the drawing settings (company, logo, checked / approved by) and
the software version. Each group is hashed on its own, so a new revision says what changed.

Applies to every part type (plastic, die casting, foundry, sheet metal, EPS, blow moulding, machined): it works on the
download path, not on the process.

The slow calculations behind the panels (3D tool design, simulation) are kept on disk too (disk_get / disk_put), so the
panel of a part opens without calculating again after a restart.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import re
import threading
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select

from . import projects_db as db

PART_PATH = re.compile(r"^/api/parts/(\d+)/(.+)$")
FILE_SUFFIX = re.compile(r"\.(pdf|xlsx|zip|dxf|step|stp|stl|png|html|mp4|gif|csv)$")
FILE_PATHS = ("simulation/video",)                      # files without a file suffix in the path
NOT_SAVED = (re.compile(r"^fea/\d+\.png$"), re.compile(r"^sim-runs/"), re.compile(r"^saved-files"),
             re.compile(r"^files/"))                    # already saved runs and uploads, and the saved files themselves
OWN_TABLES_SKIPPED = {"saved_files"}
CACHE_BUSTERS = ("t", "_")                              # query parameters a page adds only to get a fresh picture
GROUP_LABELS = {"part": "part data", "project": "project", "inserts": "insert parts", "master": "master data / rates",
                "brand": "drawing settings (logo, company)", "software": "software version", "revisions": "part revision (3D)",
                "tool_costs": "tool cost", "part_inserts": "inserts", "tool_drawing_data": "drawing data",
                "tool_reviews": "toolmaker review", "tool_fea_runs": "FEA run", "sim_runs": "simulation run",
                "history": "part history"}


def is_saved_path(rest: str) -> bool:
    if any(r.search(rest) for r in NOT_SAVED):
        return False
    path = rest.split("?", 1)[0]
    return bool(FILE_SUFFIX.search(path)) or path in FILE_PATHS


# ---------- state of a part ----------

@lru_cache(maxsize=1)
def software_stamp() -> str:
    """Hash of the program code (backend): a software update makes new revisions (a fix shows in the files)."""
    h = hashlib.sha1()
    root = Path(__file__).resolve().parent
    for p in sorted(root.rglob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _file_stamp(path) -> list:
    try:
        st = Path(path).stat()
        return [str(path), st.st_size, st.st_mtime_ns]
    except OSError:
        return [str(path), None, None]


def _part_tables():
    for t in db.meta.sorted_tables:
        if "part_id" in t.c and t.name not in OWN_TABLES_SKIPPED:
            yield t


def _h(obj) -> str:
    return hashlib.sha1(json.dumps(obj, default=str, sort_keys=True).encode()).hexdigest()[:16]


def part_state(part_id: int, conn=None) -> dict:
    """{group: hash} of everything a file of the part can depend on."""
    from . import costing_db, drawing_style, master_data
    own = conn is None
    conn = conn or db.engine().connect()
    try:
        part = conn.execute(select(db.parts).where(db.parts.c.id == part_id)).mappings().first()
        if not part:
            return {}
        out = {"part": _h(dict(part))}
        if "project_id" in part and part["project_id"] is not None:
            out["project"] = _h(dict(conn.execute(select(db.projects).where(db.projects.c.id == part["project_id"])).mappings().first() or {}))
        for t in _part_tables():
            cols = [func.count(), func.max(t.c.id)] if "id" in t.c else [func.count()]
            cols += [func.max(c) for c in t.c if str(c.type).upper().startswith(("DATETIME", "TIMESTAMP"))]
            out[t.name] = _h(list(conn.execute(select(*cols).where(t.c.part_id == part_id)).first()))
        if "part_inserts" in db.meta.tables:
            ids = [r[0] for r in conn.execute(select(db.part_inserts.c.insert_part_id).where(db.part_inserts.c.part_id == part_id))]
            if ids:
                out["inserts"] = _h([dict(r) for r in conn.execute(select(db.parts).where(db.parts.c.id.in_(ids))).mappings()])
        hist = db.history
        out["history"] = _h(list(conn.execute(select(func.count(), func.max(hist.c.id)).where(
            (hist.c.entity == "part") & (hist.c.entity_id == part_id))).first()))
    finally:
        if own:
            conn.close()
    s = drawing_style.settings()
    out["master"] = _h([_file_stamp(costing_db.path()), _file_stamp(master_data.path())])
    out["brand"] = _h([{k: v for k, v in s.items() if k != "drawn"}, _file_stamp(drawing_style.logo_path())])
    out["software"] = software_stamp()[:16]
    return out


def state_hash(state: dict) -> str:
    return _h(state)


def what_changed(old: dict | None, new: dict) -> str:
    if not old:
        return "first issue"
    keys = [k for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
    return ", ".join(GROUP_LABELS.get(k, k.replace("_", " ")) for k in keys) or "made again"


# ---------- saved files ----------

def file_key(rest: str, query: str) -> str:
    q = "&".join(sorted(p for p in (query or "").split("&") if p and p.split("=", 1)[0] not in CACHE_BUSTERS))
    return rest + (f"?{q}" if q else "")


def latest(part_id: int, key: str, conn) -> dict | None:
    r = conn.execute(select(db.saved_files).where((db.saved_files.c.part_id == part_id) & (db.saved_files.c.file_key == key))
                     .order_by(db.saved_files.c.rev_no.desc()).limit(1)).mappings().first()
    return dict(r) if r else None


def read(row: dict, conn) -> bytes | None:
    from . import file_store
    f = conn.execute(select(db.files).where(db.files.c.id == row["file_id"])).mappings().first()
    if not f:
        return None
    try:
        return file_store.path_of(dict(f)).read_bytes()
    except OSError:
        return None


def find(part_id: int, key: str) -> tuple[dict, bytes] | None:
    """The saved file of the current state, else None."""
    with db.engine().connect() as conn:
        row = latest(part_id, key, conn)
        if not row:
            return None
        if row["state_hash"] != state_hash(part_state(part_id, conn)):
            return None
        data = read(row, conn)
    return (row, data) if data is not None else None


_SAVE_LOCK = threading.Lock()


def save(part_id: int, key: str, data: bytes, media_type: str, filename: str, disposition: str, user: str) -> dict:
    """Save as the next revision (nothing new when the latest revision is of the same state and content)."""
    from . import file_store
    with _SAVE_LOCK, db.engine().begin() as conn:
        if not conn.execute(select(db.parts.c.id).where(db.parts.c.id == part_id)).first():
            return {}
        state = part_state(part_id, conn)
        h = state_hash(state)
        last = latest(part_id, key, conn)
        f = file_store.put(data, filename or key.rsplit("/", 1)[-1].split("?")[0], "saved", conn)
        if last and last["state_hash"] == h and last["file_id"] == f["id"]:
            return last
        vals = dict(part_id=part_id, file_key=key, rev_no=(last["rev_no"] + 1) if last else 1, filename=filename,
                    media_type=media_type, disposition=disposition, file_id=f["id"], size_bytes=len(data), state_hash=h,
                    state=state, changed=what_changed(last["state"] if last else None, state), created_by=user or "")
        rid = conn.execute(db.saved_files.insert().values(**vals)).inserted_primary_key[0]
        return vals | {"id": rid}


LABELS = [(r"^tool-design\.pdf", "Tool design: drawing set (PDF)"), (r"^tool-design\.zip", "Tool design: release pack (ZIP)"),
          (r"^tool-design\.png", "Tool design: picture"), (r"^tool-design\.html", "Tool design: 3D viewer"),
          (r"^tool-design\.step", "Tool design: assembly STEP"), (r"^tool-design\.stl", "Tool design: assembly STL"),
          (r"^tool-design/parts/", "Tool design: part file"), (r"^piece-cost/export", "Part cost sheet"),
          (r"^tool-cost/export", "Tool cost sheet"), (r"^rm-cost/export", "RM cost sheet"),
          (r"^country-comparison/export", "Country comparison"), (r"^drawing\.", "Part drawing"),
          (r"^tool-drawing\.", "Tool concept drawing"), (r"^po-pack", "PO pack"), (r"^forming-simulation", "Forming simulation"),
          (r"^simulation/", "Simulation report / video"), (r"^correction", "3D correction"), (r"^production-data", "Production data"),
          (r"^process-parameters", "Process parameters"), (r"^drawing-data", "Drawing data"), (r"^sheet-layout", "Blank / strip layout")]


def label(key: str) -> str:
    for pat, text in LABELS:
        if re.search(pat, key):
            q = key.split("?", 1)[1] if "?" in key else ""
            return text + (f" ({q.replace('die=', '').replace('&', ', ')})" if q else "")
    return key


def listing(part_id: int) -> dict:
    """Every saved file of the part, newest revision first, with 'current' = made from the data as it is now."""
    with db.engine().connect() as conn:
        now = state_hash(part_state(part_id, conn))
        rows = [dict(r) for r in conn.execute(select(db.saved_files).where(db.saved_files.c.part_id == part_id)
                                              .order_by(db.saved_files.c.file_key, db.saved_files.c.rev_no.desc())).mappings()]
    files: dict = {}
    for r in rows:
        f = files.setdefault(r["file_key"], {"key": r["file_key"], "label": label(r["file_key"]), "revisions": []})
        f["revisions"].append({"id": r["id"], "rev_no": r["rev_no"], "filename": r["filename"], "size_bytes": r["size_bytes"],
                               "changed": r["changed"], "created_by": r["created_by"], "created_at": r["created_at"],
                               "current": not f["revisions"] and r["state_hash"] == now})
    out = sorted(files.values(), key=lambda f: f["label"])
    for f in out:
        f["up_to_date"] = f["revisions"][0]["current"]
    return {"part_id": part_id, "files": out, "total_bytes": sum(r["size_bytes"] or 0 for r in rows)}


def revision(part_id: int, rid: int) -> tuple[dict, bytes] | None:
    with db.engine().connect() as conn:
        r = conn.execute(select(db.saved_files).where((db.saved_files.c.id == rid) & (db.saved_files.c.part_id == part_id))).mappings().first()
        if not r:
            return None
        data = read(dict(r), conn)
    return (dict(r), data) if data is not None else None


# ---------- slow calculations kept on disk ----------

DISK_KEEP = 200                     # files kept per kind (the oldest go first)


def _disk_dir(kind: str) -> Path:
    from . import register_setup
    return register_setup.storage_root() / "kept" / kind


def _disk_path(kind: str, key) -> Path:
    return _disk_dir(kind) / (hashlib.sha1(repr((key, software_stamp())).encode()).hexdigest() + ".pkl")


def disk_get(kind: str, key):
    """The object kept for key (None if not kept, or kept by another software version, or unreadable)."""
    if os.environ.get("DTC_NO_DISK_KEEP"):
        return None
    p = _disk_path(kind, key)
    try:
        with p.open("rb") as fh:
            obj = pickle.load(fh)
        os.utime(p)
        return obj
    except Exception:
        return None


def disk_put(kind: str, key, obj) -> None:
    if os.environ.get("DTC_NO_DISK_KEEP"):
        return
    p = _disk_path(kind, key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.{threading.get_ident()}.part")
        with tmp.open("wb") as fh:
            pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(p)
        old = sorted(p.parent.glob("*.pkl"), key=lambda x: x.stat().st_mtime)
        for x in old[:-DISK_KEEP]:
            x.unlink(missing_ok=True)
    except Exception:                    # keeping is a speed-up only: never fail the calculation for it
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
