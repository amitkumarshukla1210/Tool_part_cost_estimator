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


def _ray_top(shape, x: float, y: float, z0: float):
    """Lowest point of the part above z0 on the vertical line through (x, y), else None."""
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    it = IntCurvesFace_ShapeIntersector()
    it.Load(shape.wrapped, 1e-4)
    it.Perform(gp_Lin(gp_Pnt(x, y, z0), gp_Dir(0, 0, 1)), 0, 1e5)
    zs = [it.Pnt(i).Z() for i in range(1, it.NbPnt() + 1)]
    return min(zs) if zs else None


def mould_design(part: dict, shape, tr: dict, part_type: str, axis: str = "z") -> dict:
    rules = Rules(part_type)
    lines = tr["lines"]
    nodes = tr["nodes"]
    val = lambda k, d=0.0: float(nodes[k]["value"]) if k in nodes else d
    b = tr["base"]
    if not b.get("length_mm"):
        raise DesignError("The tool cost has no mould base: a detailed mould needs one (Mould & die database → Mould bases).")
    shrink = rules("shrinkage_pct") / 100
    s = _orient(shape, axis).scale(1 + shrink)
    bb = s.BoundingBox()
    s = s.translate(cq.Vector(-bb.center.x, -bb.center.y, -bb.zmin))       # centred, bottom at z = 0
    bb = s.BoundingBox()
    H = bb.zlen
    notes = [f"Cavity and core = part × {1 + shrink:g} (shrinkage {rules('shrinkage_pct'):g} %).",
             "Gate, runner, vents, slides and lifters: to be added by the mould designer (see the concept analysis)."]
    # parting plane
    if part_type == "blow":
        pl = H / 2
        notes.append("Blow mould: parting plane through the middle; neck and base inserts to be added.")
    else:
        lo, hi = _section_area(s, H * 0.02), _section_area(s, H * 0.98)
        if hi < lo:                     # open side at the top: turn the part over so the open side is down
            s = s.rotate((0, 0, 0), (1, 0, 0), 180).translate(cq.Vector(0, 0, H))
            bb = s.BoundingBox()
        pl = 0.0
    rows, cols = int(val("v:layout_rows", 1)), int(val("v:layout_cols", 1))
    il, iw = val("v:insert_each_l", bb.xlen + 50), val("v:insert_each_w", bb.ylen + 50)
    gapc = val("v:insert_gap_mm", 10)
    backing = val("v:insert_backing_mm", rules("cavity_wall_mm"))
    ha = (bb.zmax - pl) + backing                     # cavity insert height (above the parting plane)
    hb = backing + max(0.0, pl - bb.zmin)             # core insert height (below the parting plane)
    # cavity centres
    cells = [((c - (cols - 1) / 2) * (il + gapc), (r - (rows - 1) / 2) * (iw + gapc)) for r in range(rows) for c in range(cols)]
    # ----- core and cavity of one cavity -----
    upper = cq.Solid.makeBox(il, iw, ha, cq.Vector(-il / 2, -iw / 2, pl))
    lower = cq.Solid.makeBox(il, iw, hb, cq.Vector(-il / 2, -iw / 2, pl - hb))
    cut = upper.cut(s)
    pieces = sorted(cut.Solids(), key=lambda x: -x.Volume())
    cavity = pieces[0]
    core = lower.cut(s)
    if len(pieces) > 1:
        core = core.fuse(*pieces[1:]).clean()
        notes.append("Core formed by the region the part encloses (inside of the part).")
    elif part_type != "blow" and _section_area(s, H * 0.02) < 0.6 * _section_area(s, H * 0.5):
        notes.append("Core and cavity could not be separated cleanly (holes through the part link inside and outside): "
                     "the designer splits the shut-offs.")
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
    sprue = part_type in ("plastic", "die_casting") and bool(tc)
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
    if part_type == "eps":
        notes.append("EPS: steam chest, fill injectors and steam vents (slots / vent plugs in the cavity and core) to be added by the designer.")
    if part_type == "blow":
        notes.append("Blow mould: no ejection; neck and base inserts, blow pin and venting to be added by the designer.")
    if part_type == "die_casting":
        notes.append("Die casting: shot sleeve / biscuit, runner, overflows and vacuum vents to be added by the designer.")
    # the moulded part (reference)
    comps.append(Comp("Moulded part (reference)", s, [(x, y, 0.0) for x, y in cells], kind="ref", size=(bb.xlen, bb.ylen, bb.zlen),
                      color="ref", drawing="none"))
    return _finish(comps, notes, chans, cd, depth, z_tc + (tc or 0) - z_bc if tc else (pl + ta) - (pl - tb), cells, H, b, L, W, rules, part_type)


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
