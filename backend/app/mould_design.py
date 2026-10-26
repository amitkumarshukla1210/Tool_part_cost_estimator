"""Detailed 3D mould design (roadmap stage 27): two-plate mould with core and cavity cut from the part.

    part            the 3D model scaled by the shrinkage (Design rules → shrinkage_pct of the part type), turned so the
                    opening direction (concept analysis) is +Z
    parting plane   injection, die casting, EPS: at the end of the part with the smaller cross-section (the open side of
                    a cover); blow moulding: through the middle (largest cross-section), the two halves are cavities
    core / cavity   a steel block per half (insert size per cavity from the tool cost, height = part + insert backing):
                    cavity insert = upper block − part; whatever the part encloses above the parting plane (the inside of
                    a cover) is added to the core insert = lower block + that region − part
    mould base      the plates of the mould base from the tool cost (clamp plates, A / B plates with insert pockets,
                    support plate, spacer blocks, ejector retainer and ejector plate), guide pillars and bushes, return
                    pins, ejector pins under the part (pitch rule, length to the moulding face), sprue bush and locating
                    ring at the centre, cooling channels drilled in the inserts (depth rule, kept clear of the part),
                    socket head screws
Every size comes from the tool cost (mould base, layout, inserts) and Mould & die database → Design rules. A first-cut
design for the mould designer to check: gates, runners, slides, lifters and vents are left to the designer (notes).
"""

from __future__ import annotations

import cadquery as cq

from .tool_design import Comp, DesignError, Plate, Rules, _line, _mat, _pillar_d, _round_up


def _orient(shape, axis: str):
    """Turn the part so that its opening direction is +Z."""
    if axis == "x":
        return shape.rotate((0, 0, 0), (0, 1, 0), -90)
    if axis == "y":
        return shape.rotate((0, 0, 0), (1, 0, 0), 90)
    return shape


def _section_area(shape, z: float) -> float:
    bb = shape.BoundingBox()
    big = 4 * max(bb.xlen, bb.ylen) + 10
    slab = cq.Solid.makeBox(big, big, 0.2, cq.Vector(bb.center.x - big / 2, bb.center.y - big / 2, z - 0.1))
    try:
        return shape.intersect(slab).Volume() / 0.2
    except Exception:
        return 0.0


def _section_area_axis(shape, axis: str, frac: float) -> float:
    """Cross-section area of the shape square to an axis (x / y / z) at a fraction of its length."""
    bb = shape.BoundingBox()
    big = 4 * max(bb.xlen, bb.ylen, bb.zlen) + 10
    if axis == "x":
        x = bb.xmin + frac * bb.xlen
        slab = cq.Solid.makeBox(0.2, big, big, cq.Vector(x - 0.1, bb.center.y - big / 2, bb.center.z - big / 2))
    elif axis == "y":
        y = bb.ymin + frac * bb.ylen
        slab = cq.Solid.makeBox(big, 0.2, big, cq.Vector(bb.center.x - big / 2, y - 0.1, bb.center.z - big / 2))
    else:
        return _section_area(shape, bb.zmin + frac * bb.zlen)
    try:
        return shape.intersect(slab).Volume() / 0.2
    except Exception:
        return 0.0


def _ray_top(shape, x: float, y: float, z0: float):
    """Lowest point of the part above z0 on the vertical line through (x, y), else None."""
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    it = IntCurvesFace_ShapeIntersector()
    it.Load(shape.wrapped, 1e-4)
    it.Perform(gp_Lin(gp_Pnt(x, y, z0), gp_Dir(0, 0, 1)), 0, 1e5)
    zs = [it.Pnt(i).Z() for i in range(1, it.NbPnt() + 1)]
    return min(zs) if zs else None


def split_core_cavity(shape, axis: str, shrink: float, il: float, iw: float, backing: float, middle: bool = False) -> dict:
    """Core and cavity of one cavity (also the punch and die of a drawing die).

    The part (× 1 + shrink) is turned so its opening direction is +Z and its open side is down; the parting plane is the
    bottom of the part (middle = through the middle, blow moulds). cavity = upper block − part; core = lower block − part
    + whatever the part encloses above the parting plane."""
    s = _orient(shape, axis)
    if shrink:
        s = s.scale(1 + shrink)
    bb = s.BoundingBox()
    s = s.translate(cq.Vector(-bb.center.x, -bb.center.y, -bb.zmin))       # centred, bottom at z = 0
    bb = s.BoundingBox()
    H = bb.zlen
    notes = []
    if middle:
        pl = H / 2
    else:
        lo, hi = _section_area(s, H * 0.02), _section_area(s, H * 0.98)
        if hi < lo:                     # open side at the top: turn the part over so the open side is down
            s = s.rotate((0, 0, 0), (1, 0, 0), 180).translate(cq.Vector(0, 0, H))
            bb = s.BoundingBox()
            lo = hi
        pl = 0.0
    ha = (bb.zmax - pl) + backing                     # cavity insert height (above the parting plane)
    hb = backing + max(0.0, pl - bb.zmin)             # core insert height (below the parting plane)
    upper = cq.Solid.makeBox(il, iw, ha, cq.Vector(-il / 2, -iw / 2, pl))
    lower = cq.Solid.makeBox(il, iw, hb, cq.Vector(-il / 2, -iw / 2, pl - hb))
    pieces = sorted(upper.cut(s).Solids(), key=lambda x: -x.Volume())
    if not middle and len(pieces) == 1:
        # nothing enclosed: maybe the open side is the other end (ribs or bosses made the section test pick it): try it
        f = s.rotate((0, 0, 0), (1, 0, 0), 180).translate(cq.Vector(0, 0, H))
        fp = sorted(upper.cut(f).Solids(), key=lambda x: -x.Volume())
        if len(fp) > 1:
            s, pieces, bb = f, fp, f.BoundingBox()
    cavity = pieces[0]
    core = lower.cut(s) if middle or pl > bb.zmin + 1e-6 else lower
    enclosed = None
    if len(pieces) > 1:
        enclosed = pieces[1] if len(pieces) == 2 else cq.Compound.makeCompound(pieces[1:])
        core = core.fuse(*pieces[1:]).clean()
        notes.append("Core formed by the region the part encloses (inside of the part).")
    elif not middle and lo < 0.6 * _section_area(s, H * 0.5):
        notes.append("Core and cavity could not be separated cleanly (holes through the part link inside and outside): "
                     "the designer splits the shut-offs.")
    return {"part": s, "bb": bb, "H": H, "pl": pl, "cavity": cavity, "core": core, "enclosed": enclosed, "ha": ha, "hb": hb,
            "notes": notes}


def mould_design(part: dict, shape, tr: dict, part_type: str, axis: str = "z") -> dict:
    rules = Rules(part_type)
    lines = tr["lines"]
    nodes = tr["nodes"]
    val = lambda k, d=0.0: float(nodes[k]["value"]) if k in nodes else d
    b = tr["base"]
    if not b.get("length_mm"):
        raise DesignError("The tool cost has no mould base: a detailed mould needs one (Mould & die database → Mould bases).")
    shrink = rules("shrinkage_pct") / 100
    rows, cols = int(val("v:layout_rows", 1)), int(val("v:layout_cols", 1))
    bb0 = _orient(shape, axis).BoundingBox()
    il, iw = val("v:insert_each_l", bb0.xlen + 50), val("v:insert_each_w", bb0.ylen + 50)
    gapc = val("v:insert_gap_mm", 10)
    backing = val("v:insert_backing_mm", rules("cavity_wall_mm"))
    sp = split_core_cavity(shape, axis, shrink, il, iw, backing, middle=part_type == "blow")
    s, bb, H, pl, cavity, core, ha, hb = (sp[k] for k in ("part", "bb", "H", "pl", "cavity", "core", "ha", "hb"))
    notes = [f"Cavity and core = part × {1 + shrink:g} (shrinkage {rules('shrinkage_pct'):g} %)."] + sp["notes"] + \
        ["Vents at the parting line, polish and texture as the part drawing: by the mould designer."]
    if part_type == "blow":
        notes.append("Blow mould: parting plane through the middle.")
    # cavity centres
    cells = [((c - (cols - 1) / 2) * (il + gapc), (r - (rows - 1) / 2) * (iw + gapc)) for r in range(rows) for c in range(cols)]
    # cooling channels in the inserts, kept clear of the part
    cd = rules("cooling_d_mm")
    depth = rules("cooling_depth_factor") * cd
    chans = []
    for z, half in ((bb.zmax + depth, "cavity"), (pl - depth if pl - depth > pl - hb + cd else pl - hb / 2, "core")):
        for y in (-iw / 4, iw / 4):
            cyl = cq.Solid.makeCylinder(cd / 2, il + 2, cq.Vector(-il / 2 - 1, y, z), cq.Vector(1, 0, 0))
            if cyl.intersect(s).Volume() > 1e-6:
                continue
            chans.append((half, y, z, cyl))
            if half == "cavity" and z + cd / 2 < pl + ha:
                cavity = cavity.cut(cyl)
            elif half == "core" and z - cd / 2 > pl - hb:
                core = core.cut(cyl)
    cav_line, core_line = _line(lines, "Cavity insert"), _line(lines, "Core insert")
    cm, ch = _mat(rules, cav_line, "")
    km, kh = _mat(rules, core_line, cm)
    finish = rules.text("finish_cavity", "")
    comps = []
    cav_local = cavity.translate(cq.Vector(il / 2, iw / 2, -pl))
    core_local = core.translate(cq.Vector(il / 2, iw / 2, -(pl - hb)))
    cav_holes = [{"x": round(il / 2, 2), "y": round(iw / 2 + y, 2), "d": cd, "kind": "cooling",
                  "label": f"Cooling Ø{cd:g} along X at height {z - pl:.1f}", "depth": None, "top": True} for h_, y, z, _ in chans if h_ == "cavity"]
    comps.append(Comp("Cavity insert", cav_local, [(x - il / 2, y - iw / 2, pl) for x, y in cells], material=cm, hardness=ch,
                      color="hard", size=(il, iw, ha), drawing="solid", holes=cav_holes,
                      notes=[f"Moulding faces {finish}", f"Insert in pocket {rules.text('fit_insert', '')}", rules.text("heat_treat_note"),
                             "Cavity = part × (1 + shrinkage); dimensions from the 3D model of this insert"]))
    comps.append(Comp("Core insert", core_local, [(x - il / 2, y - iw / 2, pl - hb) for x, y in cells], material=km, hardness=kh,
                      color="hard", size=(il, iw, core_local.BoundingBox().zlen), drawing="solid",
                      notes=[f"Moulding faces {finish}", f"Insert in pocket {rules.text('fit_insert', '')}", rules.text("heat_treat_note")]))
    # ----- mould base plates -----
    L, W = float(b["length_mm"]), float(b["width_mm"])
    ta, tb = float(b.get("a_plate_mm") or ha), float(b.get("b_plate_mm") or hb)
    tc, ts = float(b.get("clamp_plates_mm") or 0), float(b.get("support_plate_mm") or 0)
    tsp, tej = float(b.get("spacer_block_mm") or 0), float(b.get("ejector_plates_mm") or 0)
    pocket_l, pocket_w = val("v:pocket_l", il), val("v:pocket_w", iw)
    da = min(ha, ta)
    dbk = min(hb, tb)
    if ha > ta + 0.5:
        notes.append(f"Cavity insert {ha:.1f} mm is higher than the A plate ({ta:g} mm): pocket of {ha - ta:.1f} mm in the top clamp plate.")
    if hb > tb + ts:
        notes.append(f"Core insert {hb:.0f} mm is higher than B plate + support plate: choose a thicker B plate.")
    z_b = pl - tb
    z_sup = z_b - ts
    z_sp = z_sup - tsp
    z_bc = z_sp - tc
    z_a = pl
    z_tc = pl + ta
    base_mat, base_make = b.get("material") or "", b.get("make") or ""
    pd = _pillar_d(rules, W)
    pe = rules("pillar_edge_factor") * pd
    pillars = [(-L / 2 + pe, -W / 2 + pe), (L / 2 - pe, -W / 2 + pe), (-L / 2 + pe, W / 2 - pe), (L / 2 - pe, W / 2 - pe)]
    bush_od = rules("bush_od_factor") * pd
    sd, se = rules("screw_d_mm"), rules("screw_edge_mm")
    plate_notes = [f"Thickness {rules.text('plate_thk_tol')} mm", f"Flatness {rules.text('plate_flatness')}, parallelism "
                   f"{rules.text('plate_parallelism')}", f"Ground faces {rules.text('finish_general')}"]
    A = Plate(L, W, ta)
    B = Plate(L, W, tb)
    pocket = lambda P, depth, top: P.wp.cut(cq.Workplane("XY").workplane(offset=(P.H - depth) if top else 0)
                                           .center(L / 2, W / 2).rect(pocket_l, pocket_w).extrude(depth))
    A.wp = pocket(A, da, False)
    A.openings.append({"pts": [[L / 2 - pocket_l / 2, W / 2 - pocket_w / 2], [L / 2 + pocket_l / 2, W / 2 - pocket_w / 2],
                                [L / 2 + pocket_l / 2, W / 2 + pocket_w / 2], [L / 2 - pocket_l / 2, W / 2 + pocket_w / 2],
                                [L / 2 - pocket_l / 2, W / 2 - pocket_w / 2]],
                       "label": f"Insert pocket {pocket_l:g} × {pocket_w:g}, depth {da:g} from the parting face", "tol": rules.text("fit_insert")})
    B.wp = pocket(B, dbk, True)
    B.openings.append({"pts": A.openings[0]["pts"], "label": f"Insert pocket {pocket_l:g} × {pocket_w:g}, depth {dbk:g} from the parting face",
                       "tol": rules.text("fit_insert")})
    for (x, y) in pillars:
        A.hole(x + L / 2, y + W / 2, bush_od, "fit", f"Ø{bush_od:g} {rules.text('fit_bush')} guide bush seat")
        B.hole(x + L / 2, y + W / 2, pd, "fit", f"Ø{pd:g} {rules.text('fit_bush')} guide pillar seat")
    # ejector system
    epd = rules("ejector_pin_d_mm")
    pitch = rules("ejector_pitch_mm")
    pins = []
    max_pins = rules("ejector_max_pins", 48)
    pitch = max(pitch, (bb.xlen * bb.ylen / max_pins) ** 0.5)          # large parts: fewer, bigger-spaced pins
    nx, ny = max(2, int(bb.xlen // pitch)), max(1, int(bb.ylen // pitch))
    for i in range(nx):
        for j in range(ny):
            x = bb.xmin + bb.xlen * (i + 0.5) / nx
            y = bb.ymin + bb.ylen * (j + 0.5) / ny
            ztop = _ray_top(s, x, y, pl - hb - 1)
            if ztop is not None and ztop > pl - hb:
                pins.append((x, y, ztop))
    if len(pins) < 2:
        notes.append("Ejector pins: fewer than 2 found under the part - place them by hand.")
    ej_ret_h, ej_h = tej / 2, tej / 2
    z_ej = z_bc + tc                             # ejector plate rests on the bottom clamp plate
    z_ret = z_ej + ej_h
    rails_w = max(30.0, (W - pocket_w) / 2 - 10) if tsp else 0
    comps_plates = []
    ejection = bool(tej) and part_type in ("plastic", "die_casting")
    sprue = part_type == "plastic" and bool(tc)        # die casting: shot sleeve instead (mould_features)
    if not ejection:
        pins = []
    TC = Plate(L, W, tc or 1)
    sprue_d = rules("sprue_bush_d_mm")
    ring_d = rules("locating_ring_d_mm")
    if ha > ta + 1e-6 and tc:
        TC.wp = TC.wp.cut(cq.Workplane("XY").center(L / 2, W / 2).rect(pocket_l, pocket_w).extrude(ha - ta))
        TC.openings.append({"pts": A.openings[0]["pts"], "label": f"Insert pocket {pocket_l:g} × {pocket_w:g}, depth {ha - ta:.1f} "
                            "from the A-plate face", "tol": rules.text("fit_insert")})
    if sprue:
        TC.hole(L / 2, W / 2, sprue_d, "fit", f"Ø{sprue_d:g} sprue bush seat")
        A.hole(L / 2, W / 2, sprue_d * 0.75, "thru", f"Ø{sprue_d * 0.75:g} sprue bush body")
    if tc:
        for (x, y) in ((se, se), (L - se, se), (se, W - se), (L - se, W - se)):
            TC.hole(x, y, sd + 1, "cbore", f"M{sd:g}", cb_d=1.6 * sd + 1, cb_h=sd + 1)
            A.hole(x, y, sd * 0.85, "tap", f"M{sd:g} tapped", depth=2 * sd)
        comps_plates.append(TC.comp("Top clamp plate", [(-L / 2, -W / 2, z_tc)], material=base_mat, make=base_make, color="shoe",
                                    notes=plate_notes))
    comps_plates.append(A.comp("A plate (cavity side)", [(-L / 2, -W / 2, z_a)], material=base_mat, make=base_make, color="plate",
                               notes=plate_notes))
    pin_holes_B = []
    for (x, y, _) in pins:
        for cx_, cy_ in cells:
            pin_holes_B.append((x + cx_, y + cy_))
    for (x, y) in pin_holes_B:
        B.hole(x + L / 2, y + W / 2, epd + 1, "thru", f"Ø{epd + 1:g} ejector pin clearance")
    rpd = rules("return_pin_d_mm")
    rp = [(-pocket_l / 2 - rpd, -pocket_w / 2 + rpd), (pocket_l / 2 + rpd, -pocket_w / 2 + rpd),
          (-pocket_l / 2 - rpd, pocket_w / 2 - rpd), (pocket_l / 2 + rpd, pocket_w / 2 - rpd)] if ejection else []
    for (x, y) in rp:
        B.hole(x + L / 2, y + W / 2, rpd + 1, "thru", f"Ø{rpd + 1:g} return pin clearance")
    comps_plates.append(B.comp("B plate (core side)", [(-L / 2, -W / 2, z_b)], material=base_mat, make=base_make, color="plate",
                               notes=plate_notes))
    if ts:
        SPt = Plate(L, W, ts)
        for (x, y) in pin_holes_B:
            SPt.hole(x + L / 2, y + W / 2, epd + 1, "thru", f"Ø{epd + 1:g} ejector pin clearance")
        for (x, y) in rp:
            SPt.hole(x + L / 2, y + W / 2, rpd + 1, "thru", f"Ø{rpd + 1:g} return pin clearance")
        comps_plates.append(SPt.comp("Support plate", [(-L / 2, -W / 2, z_sup)], material=base_mat, make=base_make, color="plate",
                                     notes=plate_notes))
    if tsp:
        SB = Plate(L, rails_w, tsp)
        comps_plates.append(SB.comp("Spacer block", [(-L / 2, -W / 2, z_sp), (-L / 2, W / 2 - rails_w, z_sp)], material=base_mat,
                                    make=base_make, color="shoe", notes=plate_notes))
    ej_w = W - 2 * rails_w - 4
    ej_l = L - 2 * (pd + 10)
    if ejection:
        ER = Plate(ej_l, ej_w, ej_ret_h)
        EP = Plate(ej_l, ej_w, ej_h)
        for (x, y) in pin_holes_B:
            ER.hole(x + ej_l / 2, y + ej_w / 2, epd, "cbore", "ejector pin", cb_d=epd + 4, cb_h=3, from_top=False)
        for (x, y) in rp:
            ER.hole(x + ej_l / 2, y + ej_w / 2, rpd, "cbore", "return pin", cb_d=rpd + 6, cb_h=5, from_top=False)
        comps_plates.append(ER.comp("Ejector retainer plate", [(-ej_l / 2, -ej_w / 2, z_ret)], material=base_mat, make=base_make,
                                    color="plate", notes=plate_notes))
        comps_plates.append(EP.comp("Ejector plate", [(-ej_l / 2, -ej_w / 2, z_ej)], material=base_mat, make=base_make, color="plate",
                                    notes=plate_notes))
    if tc:
        BC = Plate(L, W, tc)
        if ejection:
            BC.hole(L / 2, W / 2, 40, "thru", "Ø40 ejector rod hole")
        comps_plates.append(BC.comp("Bottom clamp plate", [(-L / 2, -W / 2, z_bc)], material=base_mat, make=base_make, color="shoe",
                                    notes=plate_notes))
    comps = comps_plates + comps
    # standard parts
    gp_line, gb_line = _line(lines, "Guide pillar"), _line(lines, "Guide bush")
    plen = (pl - z_sup) + ta - 5
    comps.append(Comp(f"Guide pillar Ø{pd:g}", cq.Workplane("XY").circle(pd / 2).extrude(plen).val(), [(x, y, z_sup) for x, y in pillars],
                      kind="std", make=gp_line.get("make") or base_make,
                      std=" ".join(v for v in (gp_line.get("std_part") or "", gp_line.get("part_number") or "") if v)
                      or f"Guide pillar Ø{pd:g} {rules.text('fit_pillar')} × {_round_up(plen, 5):g}",
                      size=(pd, pd, plen), color="std", drawing="none"))
    blen = min(ta, rules("bush_len_factor") * pd)
    comps.append(Comp(f"Guide bush Ø{pd:g}", cq.Workplane("XY").circle(bush_od / 2).circle(pd / 2).extrude(blen).val(),
                      [(x, y, pl) for x, y in pillars], kind="std", make=gb_line.get("make") or base_make,
                      std=f"Guide bush Ø{pd:g} {rules.text('fit_bush')} × OD {bush_od:g} × {blen:g}", size=(bush_od, bush_od, blen),
                      color="std", drawing="none"))
    ep_line = _line(lines, "Ejector pin")
    for (x, y, ztop) in pins:
        L_ = ztop - (z_ret + ej_ret_h - 3)
        nm = f"Ejector pin Ø{epd:g} × {_round_up(L_, 5):g}"
        body = cq.Workplane("XY").circle(epd / 2).extrude(L_).union(cq.Workplane("XY").circle((epd + 4) / 2).extrude(3))
        locs = [(x + cx_, y + cy_, z_ret) for cx_, cy_ in cells]
        same = next((c for c in comps if c.name == nm), None)
        if same:
            same.locs += locs
            continue
        comps.append(Comp(nm, body.val(), locs, kind="std", make=ep_line.get("make") or "",
                          std=(" ".join(v for v in (ep_line.get("std_part") or "", ep_line.get("part_number") or "") if v)
                               + f" - cut to {L_:.2f} (fitted to the core surface)").strip(" -"),
                          size=(epd + 4, epd + 4, L_), color="std", drawing="none"))
    rp_line = _line(lines, "Return pin")
    rl = pl - z_ret - 3
    if ejection:
        comps.append(Comp(f"Return pin Ø{rpd:g} × {_round_up(rl, 5):g}",
                          cq.Workplane("XY").circle(rpd / 2).extrude(rl).union(cq.Workplane("XY").circle((rpd + 6) / 2).extrude(5)).val(),
                          [(x, y, z_ret) for x, y in rp], kind="std", make=rp_line.get("make") or "",
                          std=f"Return pin Ø{rpd:g} × {_round_up(rl, 5):g}", size=(rpd + 6, rpd + 6, rl), color="std", drawing="none"))
    if sprue:
        _sprue_parts(comps, lines, sprue_d, ring_d, ta, tc, ha, z_tc)
    if tc:
        _clamp_screws(comps, sd, se, tc, L, W, z_tc)
    # process features: gates / runners / hot runner / shot sleeve / overflows, slides, lifters, EPS chambers, blow inserts
    from . import mould_features
    ctx = {"part_type": part_type, "rules": rules, "lines": lines, "val": val, "comps": comps, "notes": notes, "part": s, "bb": bb,
           "pl": pl, "ha": ha, "hb": hb, "cells": cells, "il": il, "iw": iw, "L": L, "W": W, "ta": ta, "tb": tb, "tc": tc,
           "z_tc": z_tc, "z_ret": z_ret, "ej_ret_h": ej_ret_h, "ejection": ejection, "pocket_w": pocket_w, "base_mat": base_mat,
           "base_make": base_make, "core_mat": km, "stack": z_tc + (tc or 0) - z_bc if tc else (pl + ta) - (pl - tb)}
    mould_features.apply(ctx)
    # the moulded part (reference)
    comps.append(Comp("Moulded part (reference)", s, [(x, y, 0.0) for x, y in cells], kind="ref", size=(bb.xlen, bb.ylen, bb.zlen),
                      color="ref", drawing="none"))
    return _finish(comps, notes, chans, cd, depth, ctx["stack"], cells, H, b, L, W, rules, part_type)


def _sprue_parts(comps, lines, sprue_d, ring_d, ta, tc, ha, z_tc):
    sb_line = _line(lines, "Sprue bush")
    sb_len = ta + tc - ha if ha < ta else tc
    sb = cq.Workplane("XY").circle(sprue_d * 0.375).extrude(max(sb_len, 10)).union(
        cq.Workplane("XY").workplane(offset=max(sb_len, 10) - 10).circle(sprue_d / 2).extrude(10))
    comps.append(Comp(f"Sprue bush Ø{sprue_d:g}", sb.val(), [(0.0, 0.0, z_tc + tc - max(sb_len, 10))], kind="std",
                      make=sb_line.get("make") or "", std=f"Sprue bush Ø{sprue_d:g} × {max(sb_len, 10):g}", size=(sprue_d, sprue_d, sb_len),
                      color="std", drawing="none"))
    lr_line = _line(lines, "Locating ring")
    comps.append(Comp(f"Locating ring Ø{ring_d:g}", cq.Workplane("XY").circle(ring_d / 2).circle(sprue_d / 2 + 2).extrude(10).val(),
                      [(0.0, 0.0, z_tc + tc)], kind="std", make=lr_line.get("make") or "", std=f"Locating ring Ø{ring_d:g} × 10",
                      size=(ring_d, ring_d, 10), color="std", drawing="none"))


def _clamp_screws(comps, sd, se, tc, L, W, z_tc):
    def screw(d, Ls):
        return cq.Workplane("XY").circle(d / 2).extrude(Ls).union(cq.Workplane("XY").workplane(offset=Ls).circle(0.75 * d).extrude(d)).val()
    Ls = _round_up(tc - (sd + 1) + 1.5 * sd, 5)
    comps.append(Comp(f"Socket head cap screw M{sd:g} × {Ls:g}", screw(sd, Ls).rotate((0, 0, 0), (1, 0, 0), 180),
                      [(x - L / 2, y - W / 2, z_tc + tc - (sd + 1)) for x, y in ((se, se), (L - se, se), (se, W - se), (L - se, W - se))],
                      kind="std", std=f"ISO 4762 M{sd:g} × {Ls:g} - 12.9", size=(1.5 * sd, 1.5 * sd, Ls + sd), color="screw", drawing="none"))


def _finish(comps, notes, chans, cd, depth, stack, cells, H, b, L, W, rules, part_type):
    order = [c for c in comps if c.kind == "made"] + [c for c in comps if c.kind == "std"] + [c for c in comps if c.kind == "ref"]
    for i, c in enumerate(order, start=1):
        c.no = f"{i:02d}" if c.kind != "ref" else "REF"
    if chans:
        notes.append(f"Cooling: {len(chans)} channel(s) Ø{cd:g} per cavity in the inserts, {depth:g} mm from the moulding faces.")
    notes.append(f"Mould height {stack:.0f} mm, {len(cells)} cavit{'y' if len(cells) == 1 else 'ies'}, opening stroke ≥ {2 * H + 20:.0f} mm.")
    return {"name": f"Mould · {len(cells)} cavit{'y' if len(cells) == 1 else 'ies'}", "key": "mould", "components": order,
            "notes": notes, "shut_height": round(stack, 1), "die_set": f"{b.get('series', '')} {b.get('size_code', '')} {L:.0f} × {W:.0f}",
            "rules_are_examples": rules.is_example, "part_type": part_type}


# ---------- foundry: pattern equipment for a sand mould ----------

def foundry_design(part: dict, shape, tr: dict, axis: str = "z") -> dict:
    """Match plate with the cope and drag patterns (the part × shrinkage, split at its largest section), gating (sprue,
    runner bar, ingate) and riser patterns, a core box when the casting encloses a region (inside of a cover / housing),
    cope and drag flasks with pins and bushes."""
    from .mould_features import _box
    rules = Rules("foundry")
    lines, nodes = tr["lines"], tr["nodes"]
    val = lambda k, d=0.0: float(nodes[k]["value"]) if k in nodes else d
    b = tr["base"]
    shrink = rules("shrinkage_pct") / 100
    s = _orient(shape, axis).scale(1 + shrink)
    bb = s.BoundingBox()
    s = s.translate(cq.Vector(-bb.center.x, -bb.center.y, -bb.zmin))
    bb = s.BoundingBox()
    H = bb.zlen
    zs = [H * f for f in (0.1, 0.3, 0.5, 0.7, 0.9)]
    pl = max(zs, key=lambda z: _section_area(s, z))           # parting plane at the largest cross-section
    rows, cols = int(val("v:layout_rows", 1)), int(val("v:layout_cols", 1))
    il, iw = val("v:insert_each_l", bb.xlen + 120), val("v:insert_each_w", bb.ylen + 120)
    gapc = val("v:insert_gap_mm", 60)
    cells = [((c - (cols - 1) / 2) * (il + gapc), (r - (rows - 1) / 2) * (iw + gapc)) for r in range(rows) for c in range(cols)]
    L, W = float(b["length_mm"]), float(b["width_mm"])
    hc, hd, tp = float(b.get("a_plate_mm") or 200), float(b.get("b_plate_mm") or 200), float(b.get("clamp_plates_mm") or rules("pattern_plate_mm"))
    big = 10 * max(bb.xlen, bb.ylen, bb.zlen)
    upper = cq.Solid.makeBox(big, big, big, cq.Vector(-big / 2, -big / 2, pl))
    cope = s.intersect(upper)
    drag = s.cut(upper)
    notes = [f"Patterns = casting × {1 + shrink:g} (shrinkage {rules('shrinkage_pct'):g} %); machining allowance "
             f"{rules('machining_allowance_mm'):g} mm and draft {rules('pattern_draft_deg'):g}° to be added on the pattern where the "
             "casting drawing asks.", f"Parting plane at the largest cross-section ({pl:.1f} mm from the bottom)."]
    pm = _line(lines, "Cope pattern").get("grade") or "Aluminium 6061-T6"
    comps = []
    # match plate between the flasks; cope pattern on top, drag pattern below (mould closed: patterns shown in place)
    mp = Plate(L, W, tp)
    sd, se = rules("screw_d_mm"), rules("screw_edge_mm")
    for cx, cy in cells:
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            mp.hole(cx + dx * (bb.xlen / 2 - se) + L / 2, cy + dy * (bb.ylen / 2 - se) + W / 2, sd + 1, "thru", f"Ø{sd + 1:g} pattern screw")
    pd = _pillar_d(rules, W)
    pe = rules("pillar_edge_factor") * pd
    pins = [(-L / 2 + pe, 0.0), (L / 2 - pe, 0.0)]
    for (x, y) in pins:
        mp.hole(x + L / 2, y + W / 2, pd, "fit", f"Ø{pd:g} {rules.text('fit_bush')} flask pin bush seat")
    comps.append(mp.comp("Match plate", [(-L / 2, -W / 2, pl - tp / 2)], material=b.get("material") or pm, make=b.get("make") or "",
                         color="plate", notes=[f"Thickness {rules.text('plate_thk_tol')} mm, flatness {rules.text('plate_flatness')}"]))
    cb, db_ = cope.BoundingBox(), drag.BoundingBox()
    cope_s = cope.translate(cq.Vector(-cb.xmin, -cb.ymin, -cb.zmin))
    drag_s = drag.translate(cq.Vector(-db_.xmin, -db_.ymin, -db_.zmin))
    comps.append(Comp("Cope pattern", cope_s, [(cx + cb.xmin, cy + cb.ymin, cb.zmin + tp / 2) for cx, cy in cells], material=pm,
                      color="hard", size=(cb.xlen, cb.ylen, cb.zlen), drawing="solid",
                      notes=[f"Upper half of the casting above the parting plane, finish {rules.text('finish_pattern')}"]))
    comps.append(Comp("Drag pattern", drag_s, [(cx + db_.xmin, cy + db_.ymin, db_.zmin - tp / 2) for cx, cy in cells], material=pm,
                      color="hard", size=(db_.xlen, db_.ylen, db_.zlen), drawing="solid",
                      notes=["Lower half of the casting below the parting plane", f"Finish {rules.text('finish_pattern')}"]))
    # gating: sprue (cope), runner bar and ingate on the parting plane, riser on the top of the casting
    spd, rw, igw = rules("sprue_d_mm"), rules("runner_w_mm"), rules("ingate_w_mm")
    wall = max(float(part.get("wall_mm") or 0), 4.0)
    rd = max(40.0, rules("riser_d_factor") * wall)
    sx = -(il / 2) + spd + 10
    gating = []
    for cx, cy in cells:
        gx = cx + sx
        sprue = cq.Solid.makeCylinder(spd / 2, hc - 10, cq.Vector(gx, cy, pl + tp / 2), cq.Vector(0, 0, 1))
        runner = _box(gx, cy - rw / 2, pl + tp / 2, cx - bb.xlen / 2 - igw * 0.2, cy + rw / 2, pl + tp / 2 + rw)
        ingate = _box(cx - bb.xlen / 2 - igw * 0.2, cy - igw / 2, pl + tp / 2, cx - bb.xlen / 2 + 3, cy + igw / 2, pl + tp / 2 + rw * 0.4)
        riser = cq.Solid.makeCylinder(rd / 2, max(rd * 1.5, 40), cq.Vector(cx, cy, cb.zmax + tp / 2 - 2), cq.Vector(0, 0, 1))
        gating.append(sprue.fuse(runner).fuse(ingate).fuse(riser).clean())
    gl = _line(lines, "Gating & riser patterns")
    for k, g in enumerate(gating, start=1):
        gb = g.BoundingBox()
        comps.append(Comp(f"Gating & riser pattern {k}" if len(gating) > 1 else "Gating & riser pattern", g.translate(cq.Vector(-gb.xmin, -gb.ymin, -gb.zmin)),
                          [(gb.xmin, gb.ymin, gb.zmin)], material=gl.get("grade") or pm, color="std", size=(gb.xlen, gb.ylen, gb.zlen),
                          drawing="solid", notes=[f"Sprue Ø{spd:g}, runner {rw:g} × {rw:g}, ingate {igw:g}, riser Ø{rd:.0f} (= {rules('riser_d_factor'):g} × wall)"]))
    # core box: the region the casting encloses (open side down), when there is one
    core_line = _line(lines, "Core box")
    if (core_line.get("quantity") or 0) > 0:
        sp = split_core_cavity(shape, axis, shrink, bb.xlen + 60, bb.ylen + 60, 30)
        if sp["enclosed"] is not None:
            enc = sp["enclosed"]
            eb = enc.BoundingBox()
            box = cq.Solid.makeBox(eb.xlen + 60, eb.ylen + 60, eb.zlen + 30, cq.Vector(eb.xmin - 30, eb.ymin - 30, eb.zmin - 0.01))
            cbox = box.cut(enc)
            kb = cbox.BoundingBox()
            comps.append(Comp("Core box", cbox.translate(cq.Vector(-kb.xmin, -kb.ymin, -kb.zmin)), [(L / 2 + 80, -kb.ylen / 2, pl - hd)],
                              material=core_line.get("grade") or pm, color="hard", size=(kb.xlen, kb.ylen, kb.zlen), drawing="solid",
                              notes=["Forms the sand core of the region the casting encloses; split and vent by the pattern maker",
                                     "Shown beside the flasks"]))
            notes.append("Core box for the sand core of the inside of the casting (shown beside the flasks).")
        else:
            notes.append("No enclosed region found: the core box line of the tool BOM can be set to 0.")
    # flasks
    fw = rules("flask_wall_mm")
    for name, z, h in (("Cope flask", pl + tp / 2, hc), ("Drag flask", pl - tp / 2 - hd, hd)):
        frame = _box(0, 0, 0, L, W, h).cut(_box(fw, fw, -1, L - fw, W - fw, h + 1))
        comps.append(Comp(name, frame, [(-L / 2, -W / 2, z)], material="Steel (fabricated)", make=b.get("make") or "", color="shoe",
                          size=(L, W, h), drawing="solid", notes=[f"Wall {fw:g} mm; pin lugs at the ends"]))
    comps.append(Comp(f"Flask pin Ø{pd:g}", cq.Solid.makeCylinder(pd / 2, hc + hd + tp), [(x, y, pl - tp / 2 - hd) for x, y in pins], kind="std",
                      std=f"Flask pin Ø{pd:g} {rules.text('fit_pillar')}", size=(pd, pd, hc + hd + tp), color="std", drawing="none"))
    comps.append(Comp("Casting (reference)", s, [(cx, cy, 0.0) for cx, cy in cells], kind="ref", size=(bb.xlen, bb.ylen, bb.zlen),
                      color="ref", drawing="none"))
    order = [c for c in comps if c.kind == "made"] + [c for c in comps if c.kind == "std"] + [c for c in comps if c.kind == "ref"]
    for i, c in enumerate(order, start=1):
        c.no = f"{i:02d}" if c.kind != "ref" else "REF"
    notes.append(f"Flasks {L:.0f} × {W:.0f} mm, cope {hc:g} / drag {hd:g} mm, {len(cells)} pattern(s) on the match plate.")
    return {"name": f"Pattern equipment · {len(cells)} pattern{'s' if len(cells) > 1 else ''}", "key": "pattern", "components": order,
            "notes": notes, "shut_height": round(hc + hd + tp, 1), "die_set": f"{b.get('series', '')} {b.get('size_code', '')} {L:.0f} × {W:.0f}",
            "rules_are_examples": rules.is_example, "part_type": "foundry"}
