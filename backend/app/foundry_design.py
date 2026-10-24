"""Foundry tooling in 3D (roadmap stage 22): pattern halves, match plate, gating and riser patterns, core boxes.

    pattern     the corrected casting (draft added with the alloy's minimum draft) grown by the machining allowance and scaled by the alloy's
                shrinkage, split at the parting plane into a drag half and a cope half
    match plate holds both halves, with the gating on it; sized from the pattern and the flask margin
    cores       every undercut void between the part's envelopes along the draw direction (side holes, bosses) becomes a core with core prints;
                the prints are added to the pattern. Open hollows (a cup) need no core: the sand rammed into the pattern is the core
    gating      sprue, runner, ingate and riser from the *Tool detail rules* (foundry): riser size from the casting modulus (volume ÷ surface)
All values come from master data (Foundry materials, Tool detail rules, Component classes). Concept level: your foundry confirms the layout.
"""

from __future__ import annotations

import math

import cadquery as cq
import numpy as np

from . import corrections, master_data, mould_db, tool_design, tool_internals

EXAMPLE = "EXAMPLE - replace with your foundry's data"
SEED_MATERIALS = [("Grey cast iron FG260", 1.0, 3.0, 1.5, 25, 1.2), ("SG / ductile iron", 1.2, 4.0, 1.5, 25, 1.3), ("Cast steel", 2.0, 5.0, 2.0, 40, 1.2),
                  ("Aluminium LM6 / A356", 1.3, 2.5, 1.0, 12, 1.2), ("Bronze", 1.5, 3.0, 1.5, 20, 1.2)]
SEED_RULES = [
    ("foundry", "poured_weight_kg", "part_weight_kg * 1.5", "kg", "Metal poured per mould (casting plus gating and riser)"),
    ("foundry", "riser_dia_mm", "max(30, round(riser_modulus_factor * part_modulus_mm / 0.214))", "mm", "Riser diameter (height 1.5 × diameter has a modulus of 0.214 × D)"),
    ("foundry", "riser_h_mm", "1.5 * riser_dia_mm", "mm", "Riser height"),
    ("foundry", "riser_neck_mm", "round(0.5 * riser_dia_mm)", "mm", "Riser neck diameter"),
    ("foundry", "sprue_dia_mm", "max(16, round(7 * sqrt(poured_weight_kg)))", "mm", "Sprue diameter at the bottom"),
    ("foundry", "sprue_h_mm", "part_h_mm + 60", "mm", "Sprue height"),
    ("foundry", "runner_w_mm", "round(0.8 * sprue_dia_mm)", "mm", "Runner width"),
    ("foundry", "runner_h_mm", "round(0.6 * sprue_dia_mm)", "mm", "Runner height"),
    ("foundry", "ingate_w_mm", "round(1.2 * runner_w_mm)", "mm", "Ingate width"),
    ("foundry", "ingate_h_mm", "round(0.5 * runner_h_mm)", "mm", "Ingate height"),
    ("foundry", "core_print_len_mm", "25", "mm", "Length of a core print"),
    ("foundry", "flask_margin_mm", "60", "mm", "Sand wall between the pattern and the flask"),
    ("foundry", "plate_margin_mm", "40", "mm", "Match plate margin around the pattern and the gating"),
    ("foundry", "match_plate_t_mm", "max(20, round(0.06 * max(part_l_mm, part_w_mm)))", "mm", "Match plate thickness"),
    ("foundry", "screw_dia_mm", "10", "mm", "Socket head cap screw size"),
    ("foundry", "dowel_dia_mm", "10", "mm", "Dowel pin diameter"),
]
FOUNDRY_ENV = ("part_weight_kg", "part_volume_cm3", "part_surface_cm2", "part_modulus_mm", "riser_modulus_factor", "part_l_mm", "part_w_mm", "part_h_mm", "flask_l_mm", "flask_w_mm")


def seed() -> dict:
    d = mould_db.tables()
    n_m = 0
    have = {r["material"] for r in d["foundry_materials"]}
    for m, shr, allow, draft, core, rmf in SEED_MATERIALS:
        if m not in have:
            d["foundry_materials"].append({"material": m, "shrinkage_pct": shr, "machining_allowance_mm": allow, "min_draft_deg": draft,
                                           "min_cored_dia_mm": core, "riser_modulus_factor": rmf, "is_example": 1, "notes": EXAMPLE})
            n_m += 1
    have = {(r["tool_group"], r["name"]) for r in d["detail_rules"]}
    top = max((r["step"] for r in d["detail_rules"]), default=0)
    n_r = 0
    for g, name, f, unit, label in SEED_RULES:
        if (g, name) not in have:
            n_r += 1
            d["detail_rules"].append({"tool_group": g, "step": top + n_r, "name": name, "formula": f, "unit": unit, "label": label, "is_example": 1, "notes": EXAMPLE})
    if n_m or n_r:
        mould_db.write(d)
    return {"materials": n_m, "rules": n_r}


def material_row(name: str) -> dict:
    row = next((r for r in mould_db.tables()["foundry_materials"] if r["material"] == name), None)
    if not row:
        raise ValueError(f"Mould & die database → Foundry materials has no row for '{name or '(no material)'}'. Add it (shrinkage, allowance, draft) or set the part's material.")
    return row


def _grow(shape: cq.Shape, mm: float) -> tuple[cq.Shape, bool]:
    """Offset a solid outwards by mm (holes get smaller). Falls back to the unchanged shape when the kernel cannot offset it."""
    from OCP.BRepOffset import BRepOffset_Skin
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
    from OCP.GeomAbs import GeomAbs_Intersection
    try:
        mk = BRepOffsetAPI_MakeOffsetShape()
        mk.PerformByJoin(shape.wrapped, mm, 1e-3, BRepOffset_Skin, False, False, GeomAbs_Intersection)
        if mk.IsDone():
            out = cq.Shape.cast(mk.Shape())
            if out.ShapeType() == "Shell":
                out = cq.Solid.makeSolid(out)
            elif out.ShapeType() != "Solid" and out.Solids():
                out = out.Solids()[0]
            if out.ShapeType() == "Solid" and out.isValid() and out.Volume() > shape.Volume():
                return out, True
    except Exception:
        pass
    return shape, False


def build(shape: cq.Shape, axis: str, material: str, facts: dict) -> dict:
    """Pattern equipment of a casting. facts: part_weight_kg, part_volume_cm3, part_surface_cm2 (of the casting)."""
    mat = material_row(material)
    notes, counts = [], {}
    corr = corrections.apply_draft(shape, axis, mat["min_draft_deg"])
    fixed = corr["shape"]
    z = corrections.to_z(fixed, axis)
    pz = corr["parting_z_mm"]
    bb0 = z.BoundingBox()
    cx, cy = (bb0.xmin + bb0.xmax) / 2, (bb0.ymin + bb0.ymax) / 2
    placed = z.translate(cq.Vector(-cx, -cy, -pz))
    allowance = mat["machining_allowance_mm"]
    grown, ok = _grow(placed, allowance)
    if not ok and allowance:
        notes.append(f"The {allowance:g} mm machining allowance could not be added by offsetting this shape: the pattern has the casting's size with the shrinkage only. Add the allowance on the machined faces in your CAD.")
    scale = 1 + mat["shrinkage_pct"] / 100
    pattern = grown.scale(scale)
    pb = pattern.BoundingBox()
    part_h = pb.zlen
    modulus = facts["part_volume_cm3"] * 1000 / max(facts["part_surface_cm2"] * 100, 1.0)
    env = {"part_weight_kg": facts["part_weight_kg"], "part_volume_cm3": facts["part_volume_cm3"], "part_surface_cm2": facts["part_surface_cm2"],
           "part_modulus_mm": modulus, "riser_modulus_factor": mat["riser_modulus_factor"], "part_l_mm": pb.xlen, "part_w_mm": pb.ylen, "part_h_mm": part_h, "flask_l_mm": 0.0, "flask_w_mm": 0.0}
    v = tool_internals.values("foundry", env)
    big = max(pb.xlen, pb.ylen, pb.zlen) * 3 + 200
    comps = []

    def add(name, group, shp, color, cls, standard=False):
        comps.append({"name": name, "group": group, "shape": shp.val() if hasattr(shp, "val") else shp, "color": color, "cls": cls, "standard": standard})

    cope_box = tool_design._box(big, big, big, z=0).val()
    drag_box = tool_design._box(big, big, big, z=-big).val()
    cope = pattern.intersect(cope_box)
    drag = pattern.intersect(drag_box)
    has_cope, has_drag = cope.Volume() > 1.0, drag.Volume() > 1.0
    # cores: undercut voids along the draw direction of the casting at its own size
    cores = []
    try:
        up, dn = tool_design.sweep(placed, big), tool_design.sweep(placed, -big)
        if up is not None and dn is not None:
            sil = up.fuse(dn)
            full = tool_design._box(pb.xlen + 40, pb.ylen + 40, 2 * big, x=0, y=0, z=-big).val()
            fs = full.intersect(sil)
            voids = fs.cut(fs.cut(dn)).cut(fs.cut(up)).cut(placed)
            cores = [g for g in voids.Solids() if g.Volume() > 30 and sorted((g.BoundingBox().xlen, g.BoundingBox().ylen, g.BoundingBox().zlen))[1] >= mat["min_cored_dia_mm"] * 0.5]
    except Exception as exc:
        notes.append(f"Cores could not be derived from the shape ({str(exc)[:70]}): the foundry decides them.")
    plen = v["core_print_len_mm"]
    core_solids = []
    for g in cores:
        gb = g.BoundingBox()
        c = ((gb.xmin + gb.xmax) / 2, (gb.ymin + gb.ymax) / 2)
        dx, dy = c[0], c[1]
        u = (1.0 if dx >= 0 else -1.0, 0.0, 0.0) if abs(dx) >= abs(dy) else (0.0, 1.0 if dy >= 0 else -1.0, 0.0)
        body = tool_design.sweep_vec(g, tuple(p * plen for p in u))
        core = (g if body is None else g.fuse(body)).scale(scale)
        core_solids.append(core)
        # the print on the pattern: the swept part outside the casting
        if body is not None:
            stub = body.scale(scale).cut(placed.scale(scale))
            pat_half = drag if gb.zmin < 0 else cope
            if gb.zmin < 0:
                drag = drag.fuse(stub)
            else:
                cope = cope.fuse(stub)
    counts["cores"] = len(core_solids)
    # match plate: sized from the pattern and the gating
    sprue_x = pb.xmax + v["plate_margin_mm"] + v["sprue_dia_mm"]
    L = (sprue_x + v["sprue_dia_mm"] + v["plate_margin_mm"]) - (pb.xmin - v["plate_margin_mm"])
    W = pb.ylen + 2 * v["plate_margin_mm"]
    pt = v["match_plate_t_mm"]
    x_lo = pb.xmin - v["plate_margin_mm"]
    plate = tool_design._box(L, W, pt, x=x_lo + L / 2, y=0, z=-pt / 2).val()
    # patterns stand on the plate: cope half up by pt/2, drag half down by pt/2
    if has_cope:
        add("Pattern: cope half", "upper", cope.translate(cq.Vector(0, 0, pt / 2)), (0.78, 0.60, 0.30), "pattern_half")
    if has_drag:
        add("Pattern: drag half", "lower", drag.translate(cq.Vector(0, 0, -pt / 2)), (0.78, 0.60, 0.30), "pattern_half")
    if not has_cope:
        notes.append("The casting lies entirely in the drag: the cope is flat (no cope pattern).")
    # gating: riser over the thickest part of the casting, sprue beside it, runner and ingate in the drag
    rd, rh, rn = v["riser_dia_mm"], v["riser_h_mm"], v["riser_neck_mm"]
    centroid = np.array([0.0, 0.0])
    try:
        verts, tris = pattern.tessellate(1.0, 0.4)
        pts = np.array([[p.x, p.y] for p in verts])
        centroid = pts.mean(axis=0)
    except Exception:
        pass
    riser_z0 = pb.zmax - rn
    riser = cq.Solid.makeCylinder(rd / 2, rh, cq.Vector(centroid[0], centroid[1], riser_z0 + pt / 2)).fuse(
        cq.Solid.makeCylinder(rn / 2, rn + 4, cq.Vector(centroid[0], centroid[1], riser_z0 + pt / 2 - rn)))
    riser = riser.cut(placed.scale(scale).translate(cq.Vector(0, 0, pt / 2)))
    sp_d = v["sprue_dia_mm"]
    sprue = cq.Solid.makeCone(sp_d / 2, sp_d / 2 * 1.4, v["sprue_h_mm"], cq.Vector(sprue_x, 0, -pt / 2 - v["runner_h_mm"]), cq.Vector(0, 0, 1))
    rw, rh2 = v["runner_w_mm"], v["runner_h_mm"]
    runner = tool_design._box(sprue_x - pb.xmax + sp_d / 2, rw, rh2, x=(pb.xmax + sprue_x) / 2 - sp_d / 4, y=0, z=-pt / 2 - rh2).val()
    ig = tool_design._box(v["plate_margin_mm"], v["ingate_w_mm"], v["ingate_h_mm"], x=pb.xmax + v["plate_margin_mm"] / 2, y=0, z=-pt / 2 - v["ingate_h_mm"]).val()
    gating_ok = True
    add("Riser pattern", "upper", riser, (0.80, 0.45, 0.25), "gating_pattern")
    add("Sprue pattern", "upper", sprue, (0.80, 0.45, 0.25), "gating_pattern")
    add("Runner and ingate pattern", "lower", runner.fuse(ig), (0.80, 0.45, 0.25), "gating_pattern")
    add("Match plate", "lower", plate, (0.55, 0.57, 0.60), "match_plate")
    plate_c = tool_internals.find(comps, "Match plate")
    halves = [c["shape"] for c in comps if c["cls"] == "pattern_half"]
    for nm in ("Riser pattern", "Sprue pattern", "Runner and ingate pattern"):
        gc = tool_internals.find(comps, nm)
        gc["shape"] = gc["shape"].cut(plate_c["shape"])
        for h in halves:
            gc["shape"] = gc["shape"].cut(h)
        if nm == "Runner and ingate pattern":
            gc["shape"] = gc["shape"].cut(tool_internals.find(comps, "Sprue pattern")["shape"])
    # fix the patterns: cap screws and dowels where the pattern is solid at the parting face
    sd, dd = v["screw_dia_mm"], v["dowel_dia_mm"]
    n_s = n_d = 0
    for name, sign in (("Pattern: cope half", 1), ("Pattern: drag half", -1)):
        pc = tool_internals.find(comps, name)
        if pc is None:
            continue
        pbb = pc["shape"].BoundingBox()
        cand = []
        for x in np.arange(pbb.xmin + 2 * sd, pbb.xmax - 2 * sd, 2.2 * sd):
            for y in np.arange(pbb.ymin + 2 * sd, pbb.ymax - 2 * sd, 2.2 * sd):
                zs = [pt / 2 * sign + sign * k for k in (0.5, 1.5 * sd * 0.5, 1.5 * sd - 0.5)]
                if all(pc["shape"].isInside(cq.Vector(float(x), float(y), float(zz)), 1e-3) for zz in zs):
                    cand.append((float(x), float(y)))
        if len(cand) >= 3:
            idx = tool_internals.farthest(np.array(cand), min(6, len(cand)))
            pos = [cand[i] for i in idx]
            n_dw = 2 if len(pos) >= 4 else 0
            screw_pos = pos[:len(pos) - n_dw]
            # the screw goes from the far side of the plate into the pattern: chain plate (head side) then pattern
            n_s += tool_internals.fasten(comps, ["Match plate", name] if sign > 0 else ["Match plate", name], screw_pos, sd, down=(sign < 0),
                                         name=f"Screw M{sd:g} (pattern)", cls="screw")
            if n_dw:
                up, lo = ("Match plate", name) if sign < 0 else (name, "Match plate")
                n_d += tool_internals.dowels(comps, up, lo, pos[-n_dw:], dd, f"Dowel pin Ø{dd:g} (pattern)")
        else:
            notes.append(f"{name} is too thin at the parting face for screws: fix it to the plate by bonding or through ribs your pattern maker adds.")
    counts["screws"], counts["dowels"] = n_s, n_d
    # core boxes: laid out in a row beside the match plate, each centred on the centre line
    run = 0.0
    for i, core in enumerate(core_solids, start=1):
        cb = core.BoundingBox()
        m = 20.0
        T = cq.Vector(x_lo + L + 60 + 2 * m - cb.xmin + run, -(cb.ymin + cb.ymax) / 2, -cb.zmin - 2 * m)
        run += cb.xlen + 6 * m + 40
        block = cq.Workplane("XY").box(cb.xlen + 2 * m, cb.ylen + 2 * m, cb.zlen + 2 * m, centered=False).translate((cb.xmin - m, cb.ymin - m, cb.zmin - m)).val()
        box = block.cut(core)
        mid = (cb.ymin + cb.ymax) / 2
        h1 = box.intersect(cq.Workplane("XY").box(cb.xlen + 4 * m, (cb.ymax - cb.ymin) / 2 + 2 * m, cb.zlen + 4 * m, centered=False).translate(
            (cb.xmin - 2 * m, cb.ymin - 2 * m, cb.zmin - 2 * m)).val())
        h2 = box.cut(h1)
        for k, half in enumerate((h1, h2), start=1):
            if half.Volume() > 1:
                add(f"Core box {i}, half {k}", "lower", half.translate(T), (0.45, 0.65, 0.80), "core_box")
        add(f"Core {i} (sand, reference)", "part", core.translate(T), (0.9, 0.85, 0.6), "part")
    # the casting and the flask for reference
    add("Casting (reference)", "part", placed.scale(1.0), (0.95, 0.80, 0.25), "part")
    fl = v["flask_margin_mm"]
    flask = tool_design._box(L + 2 * fl, W + 2 * fl, 2 * (part_h / 2 + fl), x=x_lo + L / 2, y=0, z=-(part_h / 2 + fl)).val()
    add("Flask (reference)", "part", flask.cut(tool_design._box(L, W, 2 * (part_h / 2 + fl) + 2, x=x_lo + L / 2, y=0, z=-(part_h / 2 + fl) - 1).val()), (0.6, 0.6, 0.6), "part")
    notes.append(f"Pattern: shrinkage {mat['shrinkage_pct']:g} %, machining allowance {allowance:g} mm, minimum draft {mat['min_draft_deg']:g}° (draft added to {len(corr['faces_drafted'])} faces). "
                 f"Riser Ø{rd:g} × {rh:g} mm, sprue Ø{sp_d:g} mm; flask at least {L + 2 * fl:.0f} × {W + 2 * fl:.0f} mm.")
    v = tool_internals.values("foundry", env | {"flask_l_mm": L + 2 * fl, "flask_w_mm": W + 2 * fl})      # again, now that the flask is known (machine recommendation)
    return {"components": comps, "notes": notes, "counts": counts, "rules": {k: round(x, 3) for k, x in v.items()}, "draft": {"before_cm2": corr["before"]["low_draft_cm2"],
            "after_cm2": corr["after"]["low_draft_cm2"]}, "pattern_ok": 1 if (ok or not allowance) else 0, "gating_ok": 1 if gating_ok else 0,
            "shrinkage_pct": mat["shrinkage_pct"], "allowance_mm": allowance, "flask_mm": [round(L + 2 * fl), round(W + 2 * fl)], "cores": len(core_solids)}
