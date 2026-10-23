"""Production tool designs of a part (roadmap stage 21): generate, view, correct by STEP upload, check, release.

    generate     3D tool design (moulds: plates, pillars, bushes, inserts cut from the corrected part; sheet metal: every stage
                 or the progressive die) split into components with part numbers, class, steel, features, raw stock,
                 machining operations and costs; one STEP file per component (stored by checksum), bought-out standard parts
                 and assembly steps in the bill of materials
    correct      download a component STEP, edit it in any CAD (radius, thickness, …), upload it: the solid is validated, size /
                 stock / weight / machining are recalculated, every identical part follows, and the whole design is checked
    check        valid solids and interference between components, listed with the volume
    release      freezes the design as a drawing revision (A, B, …) for the purchase orders; a released design is never edited, a new
                 revision is started from it instead
"""

from __future__ import annotations

import base64
import io
import math
import os
import tempfile
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import cadquery as cq
import numpy as np
from sqlalchemy import func, select, update

from . import (corrections, design_pack, file_store, geometry, master_data, mould_db, outputs3d, rates, register, register_setup,
               tool_components, tool_design)
from . import projects_db as db
from .register import RegisterError, ToolNotApplicable

_SHAPES: OrderedDict = OrderedDict()
SHAPE_CACHE = 160
REVS = "ABCDEFGHJKLMNPRSTUVWXYZ"


def _user() -> str:
    return register.user()


def _safe(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in s)


def _next_rev(rev: str) -> str:
    i = REVS.index(rev) if rev in REVS else 0
    return REVS[min(i + 1, len(REVS) - 1)]


# ------------------------------------------------------------ files and shapes

def _shape_of(file_row: dict) -> cq.Shape:
    key = file_row["sha256"]
    if key in _SHAPES:
        _SHAPES.move_to_end(key)
        return _SHAPES[key]
    shape = geometry.load_step(str(file_store.path_of(file_row)))
    _SHAPES[key] = shape
    while len(_SHAPES) > SHAPE_CACHE:
        _SHAPES.popitem(last=False)
    return shape


def _file_row(conn, file_id: int) -> dict:
    return dict(conn.execute(select(db.files).where(db.files.c.id == file_id)).mappings().one())


def _store_step(conn, shape: cq.Shape, name: str, color) -> dict:
    return file_store.put(outputs3d.solid_step_bytes(shape), f"{name}.step", "tool_step", conn)


# ------------------------------------------------------------ generate

def _tool_group(part_type: str) -> str:
    if part_type == "sheet_metal":
        return "sheet_metal"
    if part_type in ("plastic", "die_casting", "eps", "blow"):
        return "mould"
    raise ToolNotApplicable("Production tool drawings cover moulds, dies (plastic, die casting, EPS, blow) and sheet-metal tools. "
                            "Foundry patterns come with their own tool-design stage.")


def _signature(shape: cq.Shape, cls: str) -> tuple:
    bb = shape.BoundingBox()
    return (cls, tuple(sorted(round(x, 1) for x in (bb.xlen, bb.ylen, bb.zlen))), round(shape.Volume(), -1))


def _prepare(part_id: int) -> dict:
    d = register.part_detail(part_id, with_rm=False)
    proc = register_setup.processes().get(d["process"])
    if not proc:
        raise ToolNotApplicable("Set the part's process first.")
    group = _tool_group(proc["part_type"])
    code = _safe(d["part_code"])
    comps, std, steps, summary, stage_of = [], [], [], {}, {}
    if group == "mould":
        P = design_pack.mould_prepare(part_id, production=True)
        m3d, tool = P["m3d"], P["tool"]
        country, month = tool["country"], tool["as_of"]
        base = m3d["base_mm"]
        env = {"cavities": float(m3d["cavities_total"]), "base_l_mm": base[0], "base_w_mm": base[1], "plate_a_mm": m3d["plate_a_mm"],
               "plate_b_mm": m3d["plate_b_mm"], "pillar_dia_mm": m3d["pillar_dia_mm"], "pillars": 4.0,
               "part_h_mm": tool.get("part_h", 0) or 0, "screw_dia_mm": float(max(8, round(min(base) / 30))),
               "dowel_dia_mm": float(max(8, round(min(base) / 30)))}
        std = tool_components.bom_standard_lines(tool) + tool_components.standard_lines("mould", env)
        steps = tool_components.assembly_steps("mould", env)
        for c in m3d["components"]:
            comps.append(dict(c, prefix="M-", stage=None))
        base_line = next((l for l in tool.get("lines", []) if l.get("is_base")), None)
        summary = {"mould_base": m3d["base"], "cavities": m3d["cavities_total"], "notes": m3d["note"], "parting_z_mm": m3d["parting_z_mm"],
                   "opening_axis": P["axis"], "tool_cost": round(tool["value"]), "tool_cost_inr": round(tool["value_inr"]),
                   "currency": tool["currency"], "catalogue_base": ({"item": base_line["element"], "price": round(base_line["total"])} if base_line else None),
                   "draft": ({"before_cm2": P["corr"]["before"]["low_draft_cm2"], "after_cm2": P["corr"]["after"]["low_draft_cm2"]} if P["corr"] else None),
                   "example": bool(tool.get("example", {}).get("any"))}
        part_h = P["rev"]["geometry"]["bbox_axes_mm"][P["axis"]] if P["axis"] in P["rev"]["geometry"]["bbox_axes_mm"] else 0
        stage_of = {}
    else:
        P = design_pack.sheet_prepare(part_id)
        design, fp, shape = P["design"], P["fp"], P["shape"]
        country, month = P["country"], design["month"]
        progressive = design["mode"] == "progressive"
        if progressive:
            sol = tool_design.progressive_solids(design, fp, shape, open_state=False)
            for c in sol:
                comps.append(dict(c, prefix="P-", stage=None))
            env = _stage_env(design["stages"][0])
            std = tool_components.standard_lines("sheet_metal", env)
            steps = tool_components.assembly_steps("sheet_metal", env)
        else:
            agg, x0 = {}, 0.0
            for s in design["stages"]:
                width = s["values"]["die_set_l_mm"]
                # the stage dies stand side by side (one after the other along X) so that they can be viewed and checked together
                for c in tool_design.stage_solids(design, s, fp, shape, open_state=False):
                    shifted = c["shape"].translate(cq.Vector(x0 + width / 2, 0, 0))
                    comps.append(dict(c, shape=shifted, prefix=f"S{s['n']}-", stage=s["n"]))
                x0 += width + 150
                env = _stage_env(s)
                for l in tool_components.standard_lines("sheet_metal", env):
                    key = (l["item"], l["spec"])
                    if key in agg:
                        agg[key]["quantity"] += l["quantity"]
                        agg[key]["amount_inr"] += l["amount_inr"]
                    else:
                        agg[key] = dict(l, item=f"{l['item']}")
                    agg[key].setdefault("stages", []).append(s["n"])
            std = list(agg.values())
            steps = []
            for s in design["stages"]:
                env = _stage_env(s)
                for st in tool_components.assembly_steps("sheet_metal", env):
                    steps.append(dict(st, text=f"Stage {s['n']} ({s['name']}): {st['text']}"))
            steps = [dict(st, step=i) for i, st in enumerate(steps, start=1)]
        summary = {"mode": design["mode"], "stages": len(design["stages"]), "total_force_t": design["total_force_t"],
                   "presses": [s["press"].get("name") for s in design["stages"]], "notes": " ".join(design["warnings"]),
                   "corrections": [c for c in P["corr"]["changes"] if c.get("count")], "steel_cost": design["steel_cost"],
                   "currency": design["currency"], "example": design["is_example"], "thickness_mm": design["thickness_mm"]}
    return {"d": d, "group": group, "part_type": proc["part_type"], "code": code, "comps": comps, "std": std, "steps": steps,
            "summary": summary, "country": country, "month": month, "P": P}


def _stage_env(stage: dict) -> dict:
    env = {k: float(v) for k, v in stage["values"].items()}
    env |= {k: float(v) for k, v in master_data.parameters("sheet_metal").items() if isinstance(v, (int, float))}
    env["force_t"] = stage["force_t"]
    return env


def generate(part_id: int, note: str = "") -> dict:
    """Build a new draft design version of the part's tool. Returns the design (see get_design)."""
    pre = _prepare(part_id)
    code, part_type, country, month = pre["code"], pre["part_type"], pre["country"], pre["month"]
    # part numbers: identical parts share one, per prefix
    counters, numbers, infos = {}, {}, {}
    rows = []
    comps = sorted(pre["comps"], key=lambda c: (c["stage"] or 0, {"lower": 0, "upper": 1}.get(c["group"], 2), c["name"]))
    for c in comps:
        cls = c["cls"]
        if cls in tool_components.NON_TOOL:
            kind = cls
        else:
            row = tool_components.class_row(cls, part_type)
            kind = row["kind"] if row else "made"
        c["kind"] = kind
        if kind == "made":
            sig = (c["prefix"],) + _signature(c["shape"], cls)
            if sig not in numbers:
                counters[c["prefix"]] = counters.get(c["prefix"], 0) + 1
                numbers[sig] = f"{code}-{c['prefix']}{counters[c['prefix']]:02d}"
                infos[sig] = tool_components.component_info(c["shape"], cls, part_type, country, month)
            c["part_no"], c["info"] = numbers[sig], infos[sig]
            c["instance"] = sum(1 for r in rows if r["part_no"] == c["part_no"]) + 1
        else:
            tag = {"standard": "STD", "work": "WRK", "part": "PRT", "proposal": "PRP"}[kind]
            counters[tag] = counters.get(tag, 0) + 1
            c["part_no"], c["instance"] = f"{code}-{tag}{counters[tag]:02d}", 1
            bb = c["shape"].BoundingBox()
            c["info"] = {"class": cls, "bbox_mm": [round(bb.xlen, 2), round(bb.ylen, 2), round(bb.zlen, 2)],
                         "bbox_min": [round(bb.xmin, 2), round(bb.ymin, 2), round(bb.zmin, 2)],
                         "volume_cm3": round(c["shape"].Volume() / 1000, 2)}
        rows.append(c)
    with db.engine().begin() as conn:
        version = (conn.execute(select(func.max(db.tool_designs.c.version)).where(db.tool_designs.c.part_id == part_id)).scalar() or 0) + 1
        summary = pre["summary"] | {"part_code": pre["d"]["part_code"], "part_rev": pre["d"]["revisions"][0]["rev"] if pre["d"]["revisions"] else ""}
        did = conn.execute(db.tool_designs.insert().values(
            part_id=part_id, version=version, rev_label="A", status="draft", kind=pre["group"], part_type=part_type, country=country,
            as_of=month, summary=summary, bom={"standard": pre["std"], "assembly": pre["steps"]}, note=note, created_by=_user())).inserted_primary_key[0]
        for c in rows:
            f = _store_step(conn, c["shape"], c["part_no"] + (f"_{c['instance']}" if c["instance"] > 1 else ""), c["color"])
            cid = conn.execute(db.tool_components.insert().values(
                design_id=did, part_no=c["part_no"], instance=c["instance"], name=c["name"], group=c["group"], stage_no=c["stage"],
                cls=c["cls"], kind=c["kind"], color=list(c["color"]), file_id=f["id"], rev="A", info=c["info"], edited=0)).inserted_primary_key[0]
            conn.execute(db.tool_component_revs.insert().values(component_id=cid, rev="A", file_id=f["id"], note="generated", info=c["info"],
                                                                created_by=_user()))
        register._log(conn, "part", part_id, "tool_design_generated", {"version": version, "components": len(rows)})
    check_design(did)
    return get_design(did)


# ------------------------------------------------------------ read

def _design_row(conn, design_id: int) -> dict:
    r = conn.execute(select(db.tool_designs).where(db.tool_designs.c.id == design_id)).mappings().first()
    if not r:
        raise RegisterError("Tool design not found.")
    return dict(r)


def _comp_rows(conn, design_id: int) -> list[dict]:
    rows = conn.execute(select(db.tool_components).where(db.tool_components.c.design_id == design_id)
                        .order_by(db.tool_components.c.id)).mappings().all()
    return [dict(r) for r in rows]


def list_designs(part_id: int) -> list[dict]:
    with db.engine().connect() as conn:
        rows = conn.execute(select(db.tool_designs).where(db.tool_designs.c.part_id == part_id)
                            .order_by(db.tool_designs.c.version.desc())).mappings().all()
    out = []
    for r in rows:
        r = dict(r)
        r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
        r["released_at"] = r["released_at"].isoformat() if r["released_at"] else None
        s = r.pop("summary") or {}
        r.pop("bom")
        r["summary"] = {k: s.get(k) for k in ("mould_base", "cavities", "mode", "stages", "total_force_t", "tool_cost_inr", "steel_cost", "checks")}
        out.append(r)
    return out


def get_design(design_id: int) -> dict:
    with db.engine().connect() as conn:
        d = _design_row(conn, design_id)
        comps = _comp_rows(conn, design_id)
    d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
    d["released_at"] = d["released_at"].isoformat() if d["released_at"] else None
    d["components"] = [{k: c[k] for k in ("id", "part_no", "instance", "name", "group", "stage_no", "cls", "kind", "rev", "edited", "color")}
                       | {"info": c["info"]} for c in comps]
    d["bill"] = bill(design_id)
    return d


def bill(design_id: int) -> dict:
    """Made parts grouped by part number (quantity = instances), bought-out parts, assembly steps, totals."""
    with db.engine().connect() as conn:
        d = _design_row(conn, design_id)
        comps = _comp_rows(conn, design_id)
    made = {}
    for c in comps:
        if c["kind"] != "made":
            continue
        m = made.setdefault(c["part_no"], {"part_no": c["part_no"], "name": c["name"].split(":")[0] if c["instance"] > 1 else c["name"],
                                           "cls": c["cls"], "stage_no": c["stage_no"], "rev": c["rev"], "qty": 0, "info": c["info"], "ids": []})
        m["qty"] += 1
        m["ids"].append(c["id"])
        m["rev"] = max(m["rev"], c["rev"])
    for m in made.values():
        if m["qty"] > 1:
            m["name"] = m["name"].rstrip("0123456789 ").rstrip() or m["name"]
    std3d = [c for c in comps if c["kind"] == "standard"]
    lines = list(d["bom"]["standard"])
    totals = {"made_parts": len(made), "made_qty": sum(m["qty"] for m in made.values()),
              "steel_kg": round(sum(m["info"]["stock"]["weight_kg"] * m["qty"] for m in made.values()), 1),
              "material_cost": sum((m["info"]["material_cost"] or 0) * m["qty"] for m in made.values()),
              "machining_cost": sum(m["info"]["machining_cost"] * m["qty"] for m in made.values()),
              "standard_cost_inr": sum(l["amount_inr"] for l in lines),
              "assembly_hours": round(sum(a["hours"] for a in d["bom"]["assembly"]), 1)}
    return {"made": sorted(made.values(), key=lambda m: m["part_no"]), "standard": lines, "standard_3d": [c["name"] for c in std3d],
            "assembly": d["bom"]["assembly"], "totals": totals, "currency": d["summary"].get("currency", ""), "country": d["country"]}


# ------------------------------------------------------------ files, mesh, assembly

def component_step(design_id: int, comp_id: int) -> tuple[bytes, str]:
    with db.engine().connect() as conn:
        c = conn.execute(select(db.tool_components).where((db.tool_components.c.id == comp_id) & (db.tool_components.c.design_id == design_id))).mappings().first()
        if not c:
            raise RegisterError("Component not found.")
        f = _file_row(conn, c["file_id"])
    return file_store.path_of(f).read_bytes(), f"{c['part_no']}_rev{c['rev']}" + (f"_{c['instance']}" if c["instance"] > 1 else "") + ".step"


def _live(design_id: int, kinds=("made", "standard")) -> list[dict]:
    with db.engine().connect() as conn:
        comps = _comp_rows(conn, design_id)
        out = []
        for c in comps:
            if c["kind"] in kinds:
                out.append(dict(c, shape=_shape_of(_file_row(conn, c["file_id"]))))
    return out


def assembly_step(design_id: int, include_reference: bool = False) -> bytes:
    kinds = ("made", "standard") + (("work", "part") if include_reference else ())
    items = _live(design_id, kinds)
    return outputs3d.step_bytes([{"name": f"{c['part_no']}_{c['instance']}", "shape": c["shape"], "color": tuple(c["color"] or (0.7, 0.7, 0.7))}
                                 for c in items], f"tool_design_{design_id}")


def mesh_payload(design_id: int) -> dict:
    """Meshes of every component for the 3D viewer (base64 float32 vertices, uint32 triangles) and the features to mark."""
    items = _live(design_id, ("made", "standard", "work", "part", "proposal"))
    allbb = None
    for c in items:
        bb = c["shape"].BoundingBox()
        allbb = bb if allbb is None else allbb.add(bb)
    size = max(allbb.xlen, allbb.ylen, allbb.zlen) if allbb else 100.0
    tol = max(0.15, size / 900)
    out = []
    for c in items:
        v, f = outputs3d.mesh(c["shape"], tol)
        if not len(f):
            continue
        out.append({"id": c["id"], "part_no": c["part_no"], "instance": c["instance"], "name": c["name"], "group": c["group"], "kind": c["kind"],
                    "stage": c["stage_no"], "rev": c["rev"], "edited": bool(c["edited"]),
                    "color": [float(x) for x in (c["color"] or (0.7, 0.7, 0.7))],
                    "v": base64.b64encode(v.astype("<f4").tobytes()).decode(), "f": base64.b64encode(f.astype("<u4").tobytes()).decode(),
                    "info": {k: (c["info"] or {}).get(k) for k in ("bbox_mm", "bbox_min", "volume_cm3", "steel", "hardness", "stock", "class_name")}
                            | {"features": ((c["info"] or {}).get("features") or {})}})
    return {"design_id": design_id, "components": out, "span_mm": round(size * 0.25, 1)}


# ------------------------------------------------------------ check

def check_design(design_id: int) -> dict:
    items = _live(design_id, ("made", "standard"))
    issues = []
    for c in items:
        if not c["shape"].isValid():
            issues.append({"level": "error", "component": c["part_no"], "text": f"{c['name']}: the solid is not valid."})
    for x in tool_components.interference([{"id": c["id"], "name": f"{c['part_no']} {c['name']}", "shape": c["shape"]} for c in items]):
        issues.append({"level": "error" if x["volume_mm3"] > 100 else "warning", "component": x["a_name"].split(" ")[0],
                       "text": f"{x['a_name']} and {x['b_name']} overlap by {x['volume_mm3']:g} mm³.", "volume_mm3": x["volume_mm3"]})
    with db.engine().begin() as conn:
        d = _design_row(conn, design_id)
        s = dict(d["summary"] or {})
        s["checks"] = {"issues": issues, "errors": sum(i["level"] == "error" for i in issues), "warnings": sum(i["level"] == "warning" for i in issues),
                       "at": datetime.utcnow().isoformat(timespec="seconds"), "components_checked": len(items)}
        conn.execute(update(db.tool_designs).where(db.tool_designs.c.id == design_id).values(summary=s))
    return s["checks"]


# ------------------------------------------------------------ correct by STEP upload

def _require_draft(conn, design_id: int) -> dict:
    d = _design_row(conn, design_id)
    if d["status"] != "draft":
        raise RegisterError(f"This design is {d['status']}: start a new revision to change it.")
    return d


def upload_component(design_id: int, comp_id: int, content: bytes, filename: str, note: str) -> dict:
    """Replace a component by a corrected STEP file (coordinates as downloaded). Identical parts follow; the design is re-checked."""
    if not note.strip():
        raise RegisterError("Say what you changed (for the drawing revision).")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "upload.step")
        path.write_bytes(content)
        try:
            new = geometry.load_step(str(path))
        except Exception as exc:
            raise RegisterError(f"The STEP file could not be read as a solid: {exc}") from None
    if not new.isValid() or new.Volume() <= 0:
        raise RegisterError("The uploaded solid is not valid (or has no volume). Repair it in your CAD and upload again.")
    with db.engine().begin() as conn:
        d = _require_draft(conn, design_id)
        comp = conn.execute(select(db.tool_components).where((db.tool_components.c.id == comp_id) & (db.tool_components.c.design_id == design_id))).mappings().first()
        if not comp:
            raise RegisterError("Component not found.")
        if comp["kind"] not in ("made", "standard"):
            raise RegisterError("Only tool parts can be replaced.")
        peers = [dict(r) for r in conn.execute(select(db.tool_components).where((db.tool_components.c.design_id == design_id)
                                               & (db.tool_components.c.part_no == comp["part_no"]))).mappings()]
        old_ref = _shape_of(_file_row(conn, comp["file_id"])).BoundingBox()
        old_vol = comp["info"]["volume_cm3"]
        rev = _next_rev(comp["rev"])
        changed = []
        for peer in peers:
            pb = _shape_of(_file_row(conn, peer["file_id"])).BoundingBox()
            shape = new if peer["id"] == comp_id else new.translate(cq.Vector(pb.xmin - old_ref.xmin, pb.ymin - old_ref.ymin, pb.zmin - old_ref.zmin))
            info = (tool_components.component_info(shape, comp["cls"], d["part_type"], d["country"], d["as_of"]) if comp["kind"] == "made"
                    else {**comp["info"], "bbox_mm": [round(x, 2) for x in (shape.BoundingBox().xlen, shape.BoundingBox().ylen, shape.BoundingBox().zlen)],
                          "volume_cm3": round(shape.Volume() / 1000, 2)})
            f = _store_step(conn, shape, f"{peer['part_no']}_rev{rev}" + (f"_{peer['instance']}" if peer["instance"] > 1 else ""), peer["color"])
            conn.execute(update(db.tool_components).where(db.tool_components.c.id == peer["id"]).values(file_id=f["id"], rev=rev, info=info, edited=1))
            conn.execute(db.tool_component_revs.insert().values(component_id=peer["id"], rev=rev, file_id=f["id"], note=note.strip(),
                                                                info=info, created_by=_user()))
            changed.append(peer["id"])
        new_info = info
    checks = check_design(design_id)
    mine = [i for i in checks["issues"] if comp["part_no"] in i["text"]]
    nb = new.BoundingBox()
    return {"component": comp["part_no"], "rev": rev, "applied_to": len(changed), "volume_cm3": {"before": old_vol, "after": new_info["volume_cm3"]},
            "size_mm": {"before": comp["info"]["bbox_mm"], "after": new_info["bbox_mm"]},
            "stock": new_info.get("stock"), "material_cost": new_info.get("material_cost"), "machining_cost": new_info.get("machining_cost"),
            "issues_for_this_part": mine, "checks": {k: checks[k] for k in ("errors", "warnings")}}


def revert_component(design_id: int, comp_id: int, rev: str) -> dict:
    with db.engine().begin() as conn:
        d = _require_draft(conn, design_id)
        comp = conn.execute(select(db.tool_components).where((db.tool_components.c.id == comp_id) & (db.tool_components.c.design_id == design_id))).mappings().first()
        old = conn.execute(select(db.tool_component_revs).where((db.tool_component_revs.c.component_id == comp_id)
                           & (db.tool_component_revs.c.rev == rev))).mappings().first()
        if not comp or not old:
            raise RegisterError("Revision not found.")
        conn.execute(update(db.tool_components).where(db.tool_components.c.id == comp_id).values(file_id=old["file_id"], info=old["info"],
                     rev=old["rev"], edited=0 if old["rev"] == "A" else 1))
    check_design(design_id)
    return {"component": comp["part_no"], "rev": rev}


def component_revisions(design_id: int, comp_id: int) -> list[dict]:
    with db.engine().connect() as conn:
        rows = conn.execute(select(db.tool_component_revs).where(db.tool_component_revs.c.component_id == comp_id)
                            .order_by(db.tool_component_revs.c.id)).mappings().all()
    return [{"rev": r["rev"], "note": r["note"], "by": r["created_by"], "at": r["created_at"].isoformat() if r["created_at"] else None,
             "size_mm": (r["info"] or {}).get("bbox_mm"), "volume_cm3": (r["info"] or {}).get("volume_cm3")} for r in rows]


# ------------------------------------------------------------ release and revisions

def release(design_id: int, accept_warnings: bool = False) -> dict:
    checks = check_design(design_id)
    with db.engine().begin() as conn:
        d = _require_draft(conn, design_id)
        if checks["errors"]:
            raise RegisterError(f"{checks['errors']} error(s) in the check (solid not valid or parts overlapping): correct them first.")
        if checks["warnings"] and not accept_warnings:
            raise RegisterError(f"{checks['warnings']} warning(s) in the check: look at them, then release with 'accept warnings'.")
        conn.execute(update(db.tool_designs).where((db.tool_designs.c.part_id == d["part_id"]) & (db.tool_designs.c.status == "released"))
                     .values(status="superseded"))
        conn.execute(update(db.tool_designs).where(db.tool_designs.c.id == design_id)
                     .values(status="released", released_by=_user(), released_at=datetime.utcnow()))
        register._log(conn, "part", d["part_id"], "tool_design_released", {"version": d["version"], "rev": d["rev_label"]})
    return get_design(design_id)


def new_revision(design_id: int, note: str = "") -> dict:
    """A new draft design (next drawing revision) starting from the components of this one."""
    with db.engine().begin() as conn:
        d = _design_row(conn, design_id)
        comps = _comp_rows(conn, design_id)
        version = conn.execute(select(func.max(db.tool_designs.c.version)).where(db.tool_designs.c.part_id == d["part_id"])).scalar() + 1
        nid = conn.execute(db.tool_designs.insert().values(
            part_id=d["part_id"], version=version, rev_label=_next_rev(d["rev_label"]), status="draft", kind=d["kind"], part_type=d["part_type"],
            country=d["country"], as_of=d["as_of"], summary=d["summary"], bom=d["bom"], note=note or f"revision of version {d['version']}",
            created_by=_user())).inserted_primary_key[0]
        for c in comps:
            cid = conn.execute(db.tool_components.insert().values(
                design_id=nid, part_no=c["part_no"], instance=c["instance"], name=c["name"], group=c["group"], stage_no=c["stage_no"],
                cls=c["cls"], kind=c["kind"], color=c["color"], file_id=c["file_id"], rev=c["rev"], info=c["info"], edited=0)).inserted_primary_key[0]
            conn.execute(db.tool_component_revs.insert().values(component_id=cid, rev=c["rev"], file_id=c["file_id"], note=f"carried from version {d['version']}",
                                                                info=c["info"], created_by=_user()))
    check_design(nid)
    return get_design(nid)


# ------------------------------------------------------------ drawings

def _head(conn, d: dict, part_row) -> dict:
    proj = conn.execute(select(db.projects).where(db.projects.c.id == part_row["project_id"])).mappings().first()
    tool = ("Mould" if d["kind"] == "mould" else "Sheet-metal die") + f" · {d['part_type'].replace('_', ' ')}"
    return {"part_code": part_row["part_code"], "part_name": part_row["name"], "tool": tool, "revision_label": d["rev_label"],
            "status": d["status"], "country": d["country"], "project": (proj["code"] if proj else ""), "date": datetime.utcnow().date().isoformat()}


def _part_row(conn, part_id: int):
    return conn.execute(select(db.parts).where(db.parts.c.id == part_id)).mappings().one()


def component_drawing(design_id: int, comp_id: int, fmt: str = "pdf") -> tuple[bytes, str]:
    from . import tool_drawings
    with db.engine().connect() as conn:
        d = _design_row(conn, design_id)
        c = conn.execute(select(db.tool_components).where((db.tool_components.c.id == comp_id) & (db.tool_components.c.design_id == design_id))).mappings().first()
        if not c:
            raise RegisterError("Component not found.")
        if c["kind"] != "made":
            raise RegisterError("Only made parts have a manufacturing drawing: bought-out parts are ordered from the catalogue.")
        shape = _shape_of(_file_row(conn, c["file_id"]))
        head = _head(conn, d, _part_row(conn, d["part_id"]))
        qty = conn.execute(select(func.count()).select_from(db.tool_components).where((db.tool_components.c.design_id == design_id)
                                                                                      & (db.tool_components.c.part_no == c["part_no"]))).scalar()
    comp = {"part_no": c["part_no"], "name": c["name"].split(":")[0], "rev": c["rev"], "qty": qty, "stage": c["stage_no"]}
    if fmt == "dxf":
        return tool_drawings.component_dxf(comp, c["info"], shape, head), f"{c['part_no']}_rev{c['rev']}.dxf"
    return tool_drawings.component_pdf(comp, c["info"], shape, head), f"{c['part_no']}_rev{c['rev']}.pdf"


def assembly_drawing(design_id: int) -> tuple[bytes, str]:
    from . import tool_drawings
    items = _live(design_id, ("made", "standard"))
    b = bill(design_id)
    numbers = {m["part_no"]: i for i, m in enumerate(b["made"], start=1)}
    parts = [{"shape": c["shape"], "group": c["group"], "color": c["color"] or (0.7, 0.7, 0.7), "item": numbers.get(c["part_no"]) if c["instance"] == 1 else None}
             for c in items]
    with db.engine().connect() as conn:
        d = _design_row(conn, design_id)
        head = _head(conn, d, _part_row(conn, d["part_id"]))
    return tool_drawings.assembly_pdf(d, b, parts, head), f"{head['part_code']}_assembly_{d['status']}_{d['rev_label']}.pdf"


# ------------------------------------------------------------ purchase-order pack

def po_file(design_id: int, kind: str) -> tuple[bytes, str]:
    """kind: xlsx, po-material, po-machining, po-bought-out, assembly-pdf, assembly-step."""
    from . import tool_po
    d = get_design(design_id)
    code = _safe(d["summary"].get("part_code", f"design{design_id}"))
    tag = f"{code}_v{d['version']}_rev{d['rev_label']}_{d['status']}"
    if kind == "xlsx":
        return tool_po.workbook(d), f"{tag}_purchase_pack.xlsx"
    if kind == "po-material":
        return tool_po.po_pdf(d, "material"), f"{tag}_PO_raw_material.pdf"
    if kind == "po-machining":
        return tool_po.po_pdf(d, "machining"), f"{tag}_PO_machining.pdf"
    if kind == "po-bought-out":
        return tool_po.po_pdf(d, "bought_out"), f"{tag}_PO_bought_out.pdf"
    if kind == "assembly-pdf":
        return assembly_drawing(design_id)
    if kind == "assembly-step":
        return assembly_step(design_id), f"{tag}_assembly.step"
    raise RegisterError("Unknown file.")


def supplier_package(design_id: int) -> tuple[bytes, str]:
    """ZIP for the supplier: STEP, PDF and DXF of every made part, the assembly, the Excel pack and the three order documents."""
    import zipfile
    d = get_design(design_id)
    code = _safe(d["summary"].get("part_code", f"design{design_id}"))
    buf = io.BytesIO()
    seen = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for c in d["components"]:
            if c["kind"] != "made" or c["part_no"] in seen:
                continue
            seen.add(c["part_no"])
            z.writestr(f"step/{c['part_no']}_rev{c['rev']}.step", component_step(design_id, c["id"])[0])
            z.writestr(f"drawings/{c['part_no']}_rev{c['rev']}.pdf", component_drawing(design_id, c["id"], "pdf")[0])
            z.writestr(f"dxf/{c['part_no']}_rev{c['rev']}.dxf", component_drawing(design_id, c["id"], "dxf")[0])
        for kind in ("xlsx", "po-material", "po-machining", "po-bought-out", "assembly-pdf", "assembly-step"):
            content, name = po_file(design_id, kind)
            z.writestr((f"assembly/{name}" if kind.startswith("assembly") else f"po/{name}"), content)
        z.writestr("README.txt", (
            f"Tool purchase pack: {d['summary'].get('part_code', '')}\nDesign version {d['version']}, drawing revision {d['rev_label']}, status {d['status']}.\n\n"
            "step/        one STEP file per made part (edit in any CAD; send the corrected file back for the next revision)\n"
            "drawings/    manufacturing drawing (PDF) per made part\n"
            "dxf/         the same views and features as DXF\n"
            "assembly/    assembly STEP and the assembly sheet with the bill of materials\n"
            "po/          Excel purchase pack and the three order documents (raw material, machining, bought-out)\n\n"
            "The 3D (STEP) file governs where it differs from a drawing. Concept-level tool design generated by Design to Cost: check before cutting steel.\n"
            + ("\nDRAFT: this design is not released. Do not order from it.\n" if d["status"] != "released" else "")))
    return buf.getvalue(), f"{code}_tool_v{d['version']}_rev{d['rev_label']}_{d['status']}_supplier_package.zip"
