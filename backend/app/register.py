"""Part register: projects, variants, parts, revisions, BOM, history, search, dashboard.

Rules
- A part code is unique. A blank code is generated from the pattern in master
  data (Part register setup → Register settings → part_code_pattern).
- A new file for an existing part code is a NEW revision; old revisions, files
  and history are kept.
- Every change writes a history record: what changed (old → new), who, when.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from sqlalchemy import and_, func, or_, select

from . import cad_import, file_store, formula, master_data, rates, register_setup
from . import projects_db as db
from .table_set import EXAMPLE_FILL, HEADER_FILL


class RegisterError(ValueError):
    pass


def user() -> str:
    return rates.settings().get("approver_name") or "local user"


def _log(conn, entity, entity_id, action, detail=None):
    conn.execute(db.history.insert().values(entity=entity, entity_id=entity_id, action=action,
                                            detail=detail or {}, user=user()))


def _plain(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat(timespec="seconds")
    return d


def _num(v, where, kind=float, required=False):
    if v is None or str(v).strip() == "":
        if required:
            raise RegisterError(f"{where}: is empty.")
        return None
    try:
        n = kind(float(str(v).replace(",", "").strip()))
    except ValueError:
        raise RegisterError(f"{where}: '{v}' is not a number.") from None
    if n < 0:
        raise RegisterError(f"{where}: must not be negative.")
    return n


# ---------- projects & variants ----------

PROJECT_FIELDS = ("code", "name", "customer", "description", "capex_budget_inr")
VARIANT_FIELDS = ("code", "name", "target_bom_cost_inr", "annual_volume", "notes")


def _project_values(data, where="Project"):
    out = {}
    for k in PROJECT_FIELDS:
        if k in data:
            out[k] = _num(data[k], f"{where}: CAPEX budget") if k == "capex_budget_inr" else str(data[k] or "").strip()
    if "code" in out:
        out["code"] = out["code"].upper()
        if not out["code"]:
            raise RegisterError(f"{where}: code must not be empty.")
    if "name" in out and not out["name"]:
        raise RegisterError(f"{where}: name must not be empty.")
    return out


def create_project(data: dict) -> dict:
    vals = _project_values(data)
    for k in ("code", "name"):
        if k not in vals:
            raise RegisterError(f"Project: {k} must not be empty.")
    with db.engine().begin() as conn:
        if conn.execute(select(db.projects.c.id).where(db.projects.c.code == vals["code"])).first():
            raise RegisterError(f"Project code '{vals['code']}' already exists.")
        pid = conn.execute(db.projects.insert().values(**vals, created_by=user())).inserted_primary_key[0]
        _log(conn, "project", pid, "created", {"code": vals["code"]})
    return get_project(pid)


def update_project(pid: int, data: dict) -> dict:
    vals = _project_values(data)
    with db.engine().begin() as conn:
        old = conn.execute(select(db.projects).where(db.projects.c.id == pid)).mappings().first()
        if not old:
            raise RegisterError(f"Project {pid} does not exist.")
        changes = {k: {"old": old[k], "new": v} for k, v in vals.items() if old[k] != v}
        if changes:
            conn.execute(db.projects.update().where(db.projects.c.id == pid).values(**vals))
            _log(conn, "project", pid, "updated", changes)
    return get_project(pid)


def list_projects() -> list[dict]:
    with db.engine().connect() as conn:
        counts = dict(conn.execute(select(db.parts.c.project_id, func.count()).group_by(db.parts.c.project_id)).all())
        rows = conn.execute(select(db.projects).order_by(db.projects.c.code)).mappings().all()
        return [_plain(r) | {"part_count": counts.get(r["id"], 0)} for r in rows]


def get_project(pid: int) -> dict:
    with db.engine().connect() as conn:
        p = conn.execute(select(db.projects).where(db.projects.c.id == pid)).mappings().first()
        if not p:
            raise RegisterError(f"Project {pid} does not exist.")
        vs = conn.execute(select(db.variants).where(db.variants.c.project_id == pid).order_by(db.variants.c.code)).mappings().all()
        return _plain(p) | {"variants": [_plain(v) for v in vs]}


def _variant_values(data, where="Variant"):
    out = {}
    for k in VARIANT_FIELDS:
        if k in data:
            if k == "target_bom_cost_inr":
                out[k] = _num(data[k], f"{where}: target BOM cost")
            elif k == "annual_volume":
                out[k] = _num(data[k], f"{where}: annual volume", int)
            else:
                out[k] = str(data[k] or "").strip()
    if "code" in out:
        out["code"] = out["code"].upper()
        if not out["code"]:
            raise RegisterError(f"{where}: code must not be empty.")
    return out


def create_variant(pid: int, data: dict) -> dict:
    vals = _variant_values(data)
    if not vals.get("code") or not vals.get("name"):
        raise RegisterError("Variant: code and name must not be empty.")
    with db.engine().begin() as conn:
        if conn.execute(select(db.variants.c.id).where(and_(db.variants.c.project_id == pid,
                                                             db.variants.c.code == vals["code"]))).first():
            raise RegisterError(f"Variant '{vals['code']}' already exists in this project.")
        vid = conn.execute(db.variants.insert().values(project_id=pid, **vals)).inserted_primary_key[0]
        _log(conn, "variant", vid, "created", {"code": vals["code"], "project_id": pid})
    return get_project(pid)


def update_variant(vid: int, data: dict) -> dict:
    vals = _variant_values(data)
    with db.engine().begin() as conn:
        old = conn.execute(select(db.variants).where(db.variants.c.id == vid)).mappings().first()
        if not old:
            raise RegisterError(f"Variant {vid} does not exist.")
        changes = {k: {"old": old[k], "new": v} for k, v in vals.items() if old[k] != v}
        if changes:
            conn.execute(db.variants.update().where(db.variants.c.id == vid).values(**vals))
            _log(conn, "variant", vid, "updated", changes)
    return get_project(old["project_id"])


# ---------- parts & revisions ----------

PART_FIELDS = ("name", "material", "process", "sourcing", "status", "annual_volume", "programme_life_years",
               "target_piece_cost_inr", "notes")


def next_part_code(conn, project_code: str) -> str:
    pattern = register_setup.settings()["part_code_pattern"]
    seq = conn.execute(select(func.count()).select_from(db.parts).join(db.projects)
                       .where(db.projects.c.code == project_code)).scalar() + 1
    while True:
        code = pattern.format(project=project_code, seq=seq)
        if not conn.execute(select(db.parts.c.id).where(db.parts.c.part_code == code)).first():
            return code
        seq += 1


def suggest_process(metrics: dict | None) -> dict:
    """Score every process with its rule from master data; the highest wins."""
    if not metrics:
        return {"process": "", "scores": {}}
    if metrics.get("assembly"):
        return {"process": register_setup.assembly_process(), "scores": {}}
    env = {k: metrics[k] for k in register_setup.SUGGEST_VARIABLES}
    env["volume_cm3"] = metrics["volume_cm3"]
    scores = {}
    for code, p in register_setup.processes().items():
        try:
            scores[code] = formula.evaluate(p["suggest_rule"] or "0", env)
        except formula.FormulaError:
            scores[code] = 0
    best = max(scores, key=scores.get) if scores and max(scores.values()) > 0 else ""
    return {"process": best, "scores": scores, "inputs": env}


def _part_values(data, where="Part"):
    out = {}
    procs, srcs = register_setup.processes(), register_setup.sourcing()
    statuses = {s["code"] for s in register_setup.statuses()}
    for k in PART_FIELDS:
        if k not in data:
            continue
        v = data[k]
        if k == "annual_volume":
            out[k] = _num(v, f"{where}: annual volume", int)
        elif k in ("programme_life_years", "target_piece_cost_inr"):
            out[k] = _num(v, f"{where}: {k.replace('_', ' ')}")
        else:
            out[k] = str(v or "").strip()
    if out.get("process") and out["process"] not in procs:
        raise RegisterError(f"{where}: process '{out['process']}' is not in Master data → Part register setup → "
                            f"Processes ({', '.join(procs)}).")
    if out.get("sourcing") and out["sourcing"] not in srcs:
        raise RegisterError(f"{where}: sourcing '{out['sourcing']}' must be one of {', '.join(srcs)}.")
    if out.get("status") and out["status"] not in statuses:
        raise RegisterError(f"{where}: status '{out['status']}' is not in Part statuses.")
    if "name" in out and not out["name"]:
        raise RegisterError(f"{where}: name must not be empty.")
    return out


def _project_by_id(conn, pid):
    p = conn.execute(select(db.projects).where(db.projects.c.id == pid)).mappings().first()
    if not p:
        raise RegisterError(f"Project {pid} does not exist.")
    return p


def upsert_part(conn, project_id: int, code: str, values: dict, is_assembly=False) -> tuple[int, bool]:
    """Create the part, or return the existing one with that code. -> (part_id, created)."""
    project = _project_by_id(conn, project_id)
    code = (code or "").strip() or next_part_code(conn, project["code"])
    row = conn.execute(select(db.parts).where(db.parts.c.part_code == code)).mappings().first()
    if row:
        return row["id"], False
    vals = {"sourcing": next(iter(register_setup.sourcing())), "status": register_setup.initial_status()} | values
    if is_assembly:
        vals["process"] = vals.get("process") or register_setup.assembly_process()
    pid = conn.execute(db.parts.insert().values(part_code=code, project_id=project_id, is_assembly=is_assembly,
                                                created_by=user(), **vals)).inserted_primary_key[0]
    _log(conn, "part", pid, "created", {"part_code": code, **{k: v for k, v in vals.items() if v not in (None, "")}})
    return pid, True


def add_revision(conn, part_id: int, rev: str, *, step: bytes | None = None, file_name: str = "",
                 thumbnail: bytes | None = None, geometry: dict | None = None, change_note: str = "",
                 source: str = "") -> int:
    rev = (rev or "").strip()
    existing = [r for (r,) in conn.execute(select(db.revisions.c.rev).where(db.revisions.c.part_id == part_id))]
    if not rev:
        rev = _next_rev(existing)
    if rev in existing:
        code = conn.execute(select(db.parts.c.part_code).where(db.parts.c.id == part_id)).scalar()
        raise RegisterError(f"Part {code} already has revision '{rev}'. Use a new revision number.")
    file_row = file_store.put(step, file_name or "part.step", "step", conn) if step else None
    thumb_row = file_store.put(thumbnail, "thumbnail.png", "thumbnail", conn) if thumbnail else None
    rid = conn.execute(db.revisions.insert().values(
        part_id=part_id, rev=rev, file_id=file_row and file_row["id"], thumbnail_file_id=thumb_row and thumb_row["id"],
        change_note=change_note, geometry=geometry, source=source, created_by=user())).inserted_primary_key[0]
    conn.execute(db.parts.update().where(db.parts.c.id == part_id).values(current_revision_id=rid))
    _log(conn, "part", part_id, "revision_added", {"rev": rev, "file": file_name if step else "(file missing)",
                                                     "change_note": change_note, "source": source})
    return rid


def _next_rev(existing: list[str]) -> str:
    if not existing:
        return "A"
    last = sorted(existing)[-1]
    if last.isdigit():
        return str(int(last) + 1).zfill(len(last))
    if len(last) == 1 and last.isalpha() and last.upper() != "Z":
        return chr(ord(last.upper()) + 1)
    return f"{last}.1"


def update_part(part_id: int, data: dict) -> dict:
    vals = _part_values(data)
    with db.engine().begin() as conn:
        old = conn.execute(select(db.parts).where(db.parts.c.id == part_id)).mappings().first()
        if not old:
            raise RegisterError(f"Part {part_id} does not exist.")
        changes = {k: {"old": old[k], "new": v} for k, v in vals.items() if old[k] != v}
        if changes:
            conn.execute(db.parts.update().where(db.parts.c.id == part_id).values(**vals))
            _log(conn, "part", part_id, "updated", changes)
    return part_detail(part_id)


def new_revision_from_upload(part_id: int, content: bytes, file_name: str, rev: str, change_note: str) -> dict:
    tmp = file_store.scratch_dir(uuid.uuid4().hex)
    try:
        path = tmp / "upload.step"
        path.write_bytes(content)
        tree = cad_import.analyse_file(str(path), file_name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    root = tree["defs"][tree["root"]]
    geometry = root["metrics"]
    with db.engine().begin() as conn:
        add_revision(conn, part_id, rev, step=content, file_name=file_name, thumbnail=root.get("thumbnail"),
                     geometry=geometry, change_note=change_note, source=f"upload {file_name}")
    return part_detail(part_id)


# ---------- reading ----------

def _part_query():
    r = db.revisions.alias("cur")
    return (select(db.parts, db.projects.c.code.label("project_code"), r.c.rev, r.c.file_id, r.c.thumbnail_file_id,
                   r.c.geometry, r.c.created_at.label("revision_date"))
            .join(db.projects, db.projects.c.id == db.parts.c.project_id)
            .outerjoin(r, r.c.id == db.parts.c.current_revision_id)), r


def search(q="", project_id=None, process="", status="", sourcing="", rev="", file_missing=None,
           target_min=None, target_max=None, sort="part_code", limit=50, offset=0) -> dict:
    query, r = _part_query()
    conds = []
    if q:
        like = f"%{q.strip()}%"
        conds.append(or_(db.parts.c.part_code.ilike(like), db.parts.c.name.ilike(like), db.parts.c.material.ilike(like)))
    if project_id:
        conds.append(db.parts.c.project_id == project_id)
    for col, val in ((db.parts.c.process, process), (db.parts.c.status, status), (db.parts.c.sourcing, sourcing)):
        if val:
            conds.append(col == val)
    if rev:
        conds.append(r.c.rev == rev)
    if file_missing is True:
        conds.append(r.c.file_id.is_(None))
    if file_missing is False:
        conds.append(r.c.file_id.is_not(None))
    if target_min is not None:
        conds.append(db.parts.c.target_piece_cost_inr >= target_min)
    if target_max is not None:
        conds.append(db.parts.c.target_piece_cost_inr <= target_max)
    if conds:
        query = query.where(and_(*conds))
    sort_cols = {"part_code": db.parts.c.part_code, "name": db.parts.c.name, "updated": db.parts.c.updated_at.desc(),
                 "status": db.parts.c.status, "process": db.parts.c.process}
    with db.engine().connect() as conn:
        total = conn.execute(select(func.count()).select_from(query.subquery())).scalar()
        rows = conn.execute(query.order_by(sort_cols.get(sort, db.parts.c.part_code))
                            .limit(min(int(limit), 500)).offset(int(offset))).mappings().all()
    return {"total": total, "rows": [_plain(x) for x in rows]}


def part_detail(part_id: int) -> dict:
    query, _ = _part_query()
    with db.engine().connect() as conn:
        p = conn.execute(query.where(db.parts.c.id == part_id)).mappings().first()
        if not p:
            raise RegisterError(f"Part {part_id} does not exist.")
        revs = conn.execute(select(db.revisions, db.files.c.original_name, db.files.c.size_bytes, db.files.c.sha256)
                            .outerjoin(db.files, db.files.c.id == db.revisions.c.file_id)
                            .where(db.revisions.c.part_id == part_id).order_by(db.revisions.c.id.desc())).mappings().all()
        hist = conn.execute(select(db.history).where(and_(db.history.c.entity == "part", db.history.c.entity_id == part_id))
                            .order_by(db.history.c.id.desc())).mappings().all()
        parent = db.parts.alias("parent")
        used = conn.execute(select(db.bom_lines.c.quantity, db.variants.c.code.label("variant"),
                                   parent.c.part_code.label("parent_code"), parent.c.name.label("parent_name"))
                            .join(db.variants, db.variants.c.id == db.bom_lines.c.variant_id)
                            .outerjoin(parent, parent.c.id == db.bom_lines.c.parent_part_id)
                            .where(db.bom_lines.c.child_part_id == part_id)).mappings().all()
        children = conn.execute(select(db.bom_lines.c.quantity, db.variants.c.code.label("variant"),
                                       db.parts.c.id, db.parts.c.part_code, db.parts.c.name)
                                .join(db.parts, db.parts.c.id == db.bom_lines.c.child_part_id)
                                .join(db.variants, db.variants.c.id == db.bom_lines.c.variant_id)
                                .where(db.bom_lines.c.parent_part_id == part_id)).mappings().all()
    return _plain(p) | {"revisions": [_plain(x) for x in revs], "history": [_plain(x) for x in hist],
                        "where_used": [_plain(x) for x in used], "children": [_plain(x) for x in children]}


def revision_trace(part_id: int, rev_id: int | None = None) -> dict:
    """Traceable geometry of a revision: volume from the CAD file, weight = volume × material density."""
    from .trace import Trace
    d = part_detail(part_id)
    rev = next((r for r in d["revisions"] if rev_id in (None, r["id"])), None)
    if not rev or not rev["geometry"]:
        raise RegisterError("This revision has no 3D file yet, so there is no geometry to trace.")
    g = rev["geometry"]
    cad = {"type": "cad", "file": rev["original_name"], "rev": rev["rev"], "sha256": rev["sha256"],
           "note": "Measured from the STEP file with OpenCascade (CadQuery)"}
    t = Trace()
    t.add_input("volume", "Volume", g["volume_cm3"], "cm³", cad)
    t.add_input("surface", "Surface area", g["surface_area_mm2"] / 100, "cm²", cad)
    t.add_input("proj", f"Projected area (along {g['pull_direction'].upper()})",
                g["projected_area_mm2"][g["pull_direction"]] / 100, "cm²", cad)
    nodes = ["volume", "surface", "proj"]
    mat = next((m for m in master_data.tables()["Materials"] if m["material"] == d["material"]), None)
    if mat:
        t.add_input("density", f"Density of {mat['material']}", mat["density_g_cm3"], "g/cm³",
                    {"type": "master", "sheet": "Materials", "row": mat["material"], "part_type": mat["part_type"]})
        t.compute("weight", "Net weight", "volume * density", "g", names={"volume": "volume", "density": "density"},
                  description="Volume from the CAD file × material density from master data")
        nodes.insert(0, "weight")
    out = t.to_dict(nodes[0])
    out["components"] = nodes
    return out


# ---------- BOM ----------

def set_bom_line(conn, variant_id: int, parent_id: int | None, child_id: int, qty: float) -> None:
    cond = and_(db.bom_lines.c.variant_id == variant_id, db.bom_lines.c.child_part_id == child_id,
                db.bom_lines.c.parent_part_id.is_(None) if parent_id is None else db.bom_lines.c.parent_part_id == parent_id)
    old = conn.execute(select(db.bom_lines).where(cond)).mappings().first()
    if old:
        if old["quantity"] != qty:
            conn.execute(db.bom_lines.update().where(db.bom_lines.c.id == old["id"]).values(quantity=qty))
            _log(conn, "bom", old["id"], "updated", {"quantity": {"old": old["quantity"], "new": qty}})
        return
    bid = conn.execute(db.bom_lines.insert().values(variant_id=variant_id, parent_part_id=parent_id,
                                                    child_part_id=child_id, quantity=qty)).inserted_primary_key[0]
    _log(conn, "bom", bid, "created", {"variant_id": variant_id, "parent": parent_id, "child": child_id, "quantity": qty})


def variant_bom(variant_id: int) -> list[dict]:
    with db.engine().connect() as conn:
        rows = conn.execute(select(db.bom_lines, db.parts.c.part_code, db.parts.c.name, db.parts.c.is_assembly,
                                   db.parts.c.sourcing, db.parts.c.status)
                            .join(db.parts, db.parts.c.id == db.bom_lines.c.child_part_id)
                            .where(db.bom_lines.c.variant_id == variant_id)).mappings().all()
    by_parent: dict = {}
    for r in rows:
        by_parent.setdefault(r["parent_part_id"], []).append(dict(r))

    def tree(parent, depth, mult):
        out = []
        for r in sorted(by_parent.get(parent, []), key=lambda x: x["part_code"]):
            total = r["quantity"] * mult
            out.append(r | {"depth": depth, "total_quantity": total})
            out += tree(r["child_part_id"], depth + 1, total)
        return out

    return tree(None, 0, 1)


# ---------- assembly / single-part import (preview, then commit) ----------

def import_preview(content: bytes, file_name: str) -> dict:
    token = uuid.uuid4().hex
    folder = file_store.scratch_dir(token)
    src = folder / "source.step"
    src.write_bytes(content)
    try:
        tree = cad_import.analyse_file(str(src), file_name)
    except cad_import.ImportError_ as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise RegisterError(str(exc)) from None
    for key, d in tree["defs"].items():
        if d["is_assembly"]:
            # an assembly revision records its structure (child names and quantities)
            d["metrics"] = {"assembly": True, "children": sorted(
                [tree["defs"][c]["name"], q] for c, q in d["children"].items())}
        if d.get("step"):
            (folder / f"{key}.step").write_bytes(d.pop("step"))
        else:
            d.pop("step", None)
        if d.get("thumbnail"):
            (folder / f"{key}.png").write_bytes(d.pop("thumbnail"))
        d["suggestion"] = suggest_process(d["metrics"])
    manifest = {"token": token, "file_name": file_name, "root": tree["root"], "defs": tree["defs"]}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def import_thumbnail(token: str, key: str) -> Path:
    p = file_store.scratch_dir(token) / f"{Path(key).name}.png"
    if not p.exists():
        raise RegisterError("Thumbnail not found.")
    return p


def import_commit(token: str, project_id: int, variant_id: int | None, items: dict, rev: str = "",
                  change_note: str = "") -> dict:
    """items: {def_key: {part_code, name, material, process, sourcing, register(bool)}}"""
    folder = file_store.scratch_dir(Path(token).name)
    mf = folder / "manifest.json"
    if not mf.exists():
        raise RegisterError("This import has expired. Please upload the file again.")
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    defs = manifest["defs"]
    created, revised, ids = [], [], {}
    with db.engine().begin() as conn:
        if variant_id is not None:
            v = conn.execute(select(db.variants).where(db.variants.c.id == variant_id)).mappings().first()
            if not v or v["project_id"] != project_id:
                raise RegisterError("The chosen variant does not belong to the chosen project.")

        def make(key):
            if key in ids:
                return ids[key]
            d, choice = defs[key], items.get(key, {})
            if not choice.get("register", True):
                ids[key] = None
                return None
            vals = _part_values({k: choice[k] for k in ("material", "process", "sourcing") if choice.get(k)}
                                | {"name": choice.get("name") or d["name"]}, f"Part '{d['name']}'")
            pid, is_new = upsert_part(conn, project_id, choice.get("part_code", ""), vals, d["is_assembly"])
            is_root = key == manifest["root"]
            step_path = folder / ("source.step" if is_root else f"{key}.step")
            step = step_path.read_bytes() if step_path.exists() else None
            thumb_path = folder / f"{key}.png"
            if not is_new and _same_as_current(conn, pid, d["metrics"], step):
                unchanged.append(pid)  # same geometry / structure as the current revision: just link it
            else:
                add_revision(conn, pid, rev, step=step,
                             file_name=manifest["file_name"] if is_root else f"{d['name']}.step",
                             thumbnail=thumb_path.read_bytes() if thumb_path.exists() else None,
                             geometry=d["metrics"], change_note=change_note,
                             source=f"{manifest['file_name']} / {d['name']}")
                (created if is_new else revised).append(pid)
            ids[key] = pid
            return pid

        def link(key, parent_pid, qty):
            pid = make(key)
            if pid is not None and variant_id is not None:
                set_bom_line(conn, variant_id, parent_pid, pid, float(qty))
            # An unticked assembly passes its children (and its quantity) on to the next ticked level up.
            for child, child_qty in defs[key]["children"].items():
                if pid is None:
                    link(child, parent_pid, child_qty * qty)
                else:
                    link(child, pid, child_qty)

        unchanged: list = []
        link(manifest["root"], None, 1)
    shutil.rmtree(folder, ignore_errors=True)
    return {"created": len(created), "new_revisions": len(revised), "unchanged": len(set(unchanged)),
            "part_ids": [i for i in ids.values() if i]}


def _same_as_current(conn, part_id, metrics, step) -> bool:
    """Exported STEP files carry a timestamp, so compare geometry (or the file checksum when it is the original)."""
    cur = conn.execute(select(db.revisions.c.geometry, db.files.c.sha256).select_from(
        db.parts.join(db.revisions, db.revisions.c.id == db.parts.c.current_revision_id)
        .outerjoin(db.files, db.files.c.id == db.revisions.c.file_id)).where(db.parts.c.id == part_id)).first()
    if not cur:
        return False
    geometry, sha = cur
    if step is not None and sha == hashlib.sha256(step).hexdigest():
        return True
    if not geometry or not metrics:
        return False
    if metrics.get("assembly"):
        return geometry.get("children") == metrics["children"]
    return "volume_mm3" in geometry and cad_import.signature(geometry) == cad_import.signature(metrics)


# ---------- Excel bulk upload ----------

TEMPLATE_COLUMNS = [
    ("part_code", "Your part code; leave blank to generate one"),
    ("part_name", "Required"),
    ("rev", "Drawing revision, e.g. A or 01; blank = next revision"),
    ("file_name", "STEP file name, matched to the uploaded files / ZIP"),
    ("material", "Material name as in Master data → Materials"),
    ("process", "Process code (see Part register setup → Processes); blank = suggested from the 3D file"),
    ("sourcing", "make, bought_out, existing or not_required"),
    ("annual_volume", "Parts per year"),
    ("programme_life_years", "Years"),
    ("target_piece_cost_inr", "Optional target cost per piece (INR)"),
    ("variant", "Variant code; adds the part to that variant's BOM"),
    ("parent_part_code", "Assembly it belongs to (blank = top level of the variant)"),
    ("quantity", "Quantity in the parent (default 1)"),
    ("change_note", "What changed (for a new revision)"),
]


def excel_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Parts"
    wb.properties.title = "Design to Cost — Part register bulk upload"
    wb.properties.creator = "Design to Cost"
    ws.append([c for c, _ in TEMPLATE_COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
    ws.append(["", "Example bracket", "A", "sheet_metal_bracket.step", "Mild steel CRCA / HR", "", "make", 200000, 5,
               "", "STD", "", 2, "first upload"])
    for cell in ws[2]:
        cell.fill = EXAMPLE_FILL
    for i, (c, _) in enumerate(TEMPLATE_COLUMNS, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = max(14, len(c) + 4)
    help_ws = wb.create_sheet("Help")
    help_ws.append(["column", "meaning"])
    for cell in help_ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
    for c, h in TEMPLATE_COLUMNS:
        help_ws.append([c, h])
    help_ws.append([])
    help_ws.append(["note", "Row 2 is an example (yellow); replace or delete it. Same part_code again = new revision."])
    help_ws.column_dimensions["A"].width = 24
    help_ws.column_dimensions["B"].width = 90
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _collect_files(uploads: list[tuple[str, bytes]]) -> dict[str, bytes]:
    """{lower-case file name: bytes} from STEP uploads and ZIPs."""
    out = {}
    for name, content in uploads:
        if name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    for info in z.infolist():
                        if not info.is_dir() and Path(info.filename).suffix.lower() in (".step", ".stp"):
                            out[Path(info.filename).name.lower()] = z.read(info)
            except zipfile.BadZipFile:
                raise RegisterError(f"{name} is not a valid ZIP file.") from None
        elif Path(name).suffix.lower() in (".step", ".stp"):
            out[Path(name).name.lower()] = content
    return out


def bulk_upload(project_id: int, excel: bytes, uploads: list[tuple[str, bytes]]) -> dict:
    try:
        wb = load_workbook(io.BytesIO(excel), read_only=True, data_only=True)
    except Exception as exc:
        raise RegisterError(f"Could not read the Excel file: {exc}") from None
    ws = wb["Parts"] if "Parts" in wb.sheetnames else wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        raise RegisterError("The Excel file is empty.")
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    if "part_name" not in header:
        raise RegisterError("The Parts sheet needs the template columns (download the template).")
    files = _collect_files(uploads)
    project = get_project(project_id)
    variants = {v["code"]: v["id"] for v in project["variants"]}

    # 1. check every row first; nothing is saved if any row is wrong
    records, errors = [], []
    codes_in_sheet = set()
    for i, raw in enumerate(rows[1:], start=2):
        if not any(v not in (None, "") for v in raw):
            continue
        r = {h: raw[j] if j < len(raw) else None for j, h in enumerate(header) if h}
        where = f"Parts row {i}"
        try:
            vals = _part_values({"name": r.get("part_name"), "material": r.get("material"), "process": r.get("process"),
                                 "sourcing": r.get("sourcing"), "annual_volume": r.get("annual_volume"),
                                 "programme_life_years": r.get("programme_life_years"),
                                 "target_piece_cost_inr": r.get("target_piece_cost_inr")}, where)
            vals = {k: v for k, v in vals.items() if v not in (None, "")}
            variant = str(r.get("variant") or "").strip().upper()
            if variant and variant not in variants:
                raise RegisterError(f"{where}: variant '{variant}' is not in project {project['code']}. Add it first.")
            qty = _num(r.get("quantity"), f"{where}: quantity") or 1
            fname = str(r.get("file_name") or "").strip()
            code = str(r.get("part_code") or "").strip()
            if code:
                if code in codes_in_sheet:
                    raise RegisterError(f"{where}: part_code '{code}' appears twice in the sheet.")
                codes_in_sheet.add(code)
            records.append({"row": i, "code": code, "values": vals, "rev": str(r.get("rev") or "").strip(),
                            "file_name": fname, "content": files.get(fname.lower()) if fname else None,
                            "variant": variant, "parent": str(r.get("parent_part_code") or "").strip(),
                            "quantity": qty, "change_note": str(r.get("change_note") or "").strip()})
        except RegisterError as exc:
            errors.append(str(exc))
    for rec in records:
        if rec["parent"] and rec["parent"] not in codes_in_sheet:
            with db.engine().connect() as conn:
                if not conn.execute(select(db.parts.c.id).where(db.parts.c.part_code == rec["parent"])).first():
                    errors.append(f"Parts row {rec['row']}: parent_part_code '{rec['parent']}' is not in the sheet or the register.")
        if rec["parent"] and not rec["variant"]:
            errors.append(f"Parts row {rec['row']}: a parent_part_code needs a variant.")
    if errors:
        raise RegisterError("Nothing was saved. Please fix: " + " | ".join(errors[:20]) +
                            (f" | … and {len(errors) - 20} more" if len(errors) > 20 else ""))

    # 2. measure the files (outside the transaction)
    for rec in records:
        rec["geometry"] = rec["thumbnail"] = None
        if rec["content"]:
            tmp = file_store.scratch_dir(uuid.uuid4().hex)
            try:
                (tmp / "f.step").write_bytes(rec["content"])
                tree = cad_import.analyse_file(str(tmp / "f.step"), rec["file_name"])
                root = tree["defs"][tree["root"]]
                rec["geometry"], rec["thumbnail"] = root["metrics"], root.get("thumbnail")
            except cad_import.ImportError_ as exc:
                raise RegisterError(f"Nothing was saved. Parts row {rec['row']}: {rec['file_name']}: {exc}") from None
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            if not rec["values"].get("process"):
                rec["values"]["process"] = suggest_process(rec["geometry"])["process"]

    # 3. save everything in one transaction
    report = []
    with db.engine().begin() as conn:
        ids = {}
        for rec in records:
            pid, is_new = upsert_part(conn, project_id, rec["code"], rec["values"])
            if not is_new and rec["values"]:
                old = conn.execute(select(db.parts).where(db.parts.c.id == pid)).mappings().one()
                changes = {k: {"old": old[k], "new": v} for k, v in rec["values"].items() if old[k] != v}
                if changes:
                    conn.execute(db.parts.update().where(db.parts.c.id == pid).values(**rec["values"]))
                    _log(conn, "part", pid, "updated", changes | {"source": f"Excel row {rec['row']}"})
            add_revision(conn, pid, rec["rev"], step=rec["content"], file_name=rec["file_name"],
                         thumbnail=rec["thumbnail"], geometry=rec["geometry"], change_note=rec["change_note"],
                         source=f"Excel row {rec['row']}")
            code = conn.execute(select(db.parts.c.part_code).where(db.parts.c.id == pid)).scalar()
            ids[code] = rec["pid"] = pid
            report.append({"row": rec["row"], "part_code": code, "result": "created" if is_new else "new revision",
                           "file": rec["file_name"] if rec["content"] else "File missing"})
        for rec in records:
            if rec["variant"]:
                parent = None
                if rec["parent"]:
                    parent = ids.get(rec["parent"]) or conn.execute(
                        select(db.parts.c.id).where(db.parts.c.part_code == rec["parent"])).scalar()
                set_bom_line(conn, variants[rec["variant"]], parent, rec["pid"], rec["quantity"])
    return {"rows": report, "created": sum(r["result"] == "created" for r in report),
            "new_revisions": sum(r["result"] == "new revision" for r in report),
            "file_missing": sum(r["file"] == "File missing" for r in report)}


# ---------- dashboard ----------

def dashboard(project_id: int) -> dict:
    project = get_project(project_id)
    statuses = register_setup.statuses()
    with db.engine().connect() as conn:
        by = lambda col: dict(conn.execute(select(col, func.count()).where(db.parts.c.project_id == project_id)
                                           .group_by(col)).all())
        by_status, by_process, by_sourcing = by(db.parts.c.status), by(db.parts.c.process), by(db.parts.c.sourcing)
        r = db.revisions.alias("cur")
        missing = conn.execute(select(func.count()).select_from(db.parts.outerjoin(r, r.c.id == db.parts.c.current_revision_id))
                               .where(and_(db.parts.c.project_id == project_id, r.c.file_id.is_(None)))).scalar()
        total = sum(by_status.values())
        targets = conn.execute(select(func.count(), func.sum(db.parts.c.target_piece_cost_inr))
                               .where(and_(db.parts.c.project_id == project_id,
                                           db.parts.c.target_piece_cost_inr.is_not(None)))).one()
    variants = []
    for v in project["variants"]:
        bom = variant_bom(v["id"])
        variants.append(v | {"bom_lines": len(bom), "unique_parts": len({b["child_part_id"] for b in bom}),
                             "bom_cost_inr": None})
    procs, srcs = register_setup.processes(), register_setup.sourcing()
    corrections = sum(by_status.get(s["code"], 0) for s in statuses if s.get("is_open_correction"))
    return {
        "project": project,
        "parts_total": total,
        "file_missing": missing,
        "status": [{"code": s["code"], "name": s["name"], "count": by_status.get(s["code"], 0)} for s in statuses],
        "process": [{"code": c, "name": procs[c]["name"] if c in procs else c or "—", "count": n} for c, n in by_process.items()],
        "sourcing": [{"code": c, "name": srcs[c]["name"] if c in srcs else c or "—", "count": n} for c, n in by_sourcing.items()],
        "variants": variants,
        "parts_with_target": targets[0], "target_piece_cost_sum_inr": targets[1],
        "capex": {"budget_inr": project["capex_budget_inr"], "tool_cost_inr": None, "machine_cost_inr": None},
        "open_corrections": corrections,
        "not_costed_note": "Costs appear here from the part-costing and tool-costing stages (roadmap stages 4 and 8).",
    }


# ---------- exports ----------

def export_parts_excel(**filters) -> bytes:
    res = search(**filters, limit=500, offset=0)
    rows = res["rows"]
    offset = 500
    while offset < res["total"]:
        rows += search(**filters, limit=500, offset=offset)["rows"]
        offset += 500
    wb = Workbook()
    ws = wb.active
    ws.title = "Part register"
    wb.properties.title = "Design to Cost — Part register"
    wb.properties.creator = "Design to Cost"
    cols = ["part_code", "name", "project_code", "rev", "material", "process", "sourcing", "status", "annual_volume",
            "programme_life_years", "target_piece_cost_inr", "volume_cm3", "bbox_mm", "file", "updated_at"]
    ws.append(cols)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
    for r in rows:
        g = r.get("geometry") or {}
        b = g.get("bbox_mm") or {}
        ws.append([r["part_code"], r["name"], r["project_code"], r["rev"], r["material"], r["process"], r["sourcing"],
                   r["status"], r["annual_volume"], r["programme_life_years"], r["target_piece_cost_inr"],
                   g.get("volume_cm3"), f"{b.get('length')} x {b.get('width')} x {b.get('height')}" if b else "",
                   "yes" if r["file_id"] else "File missing", r["updated_at"]])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_dashboard_pdf(project_id: int) -> bytes:
    from .pdf_report import dashboard_pdf
    return dashboard_pdf(dashboard(project_id))
