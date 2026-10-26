"""Process features of a mould design (roadmap stage 28), added to the assembly made by mould_design.py.

    plastic, cold runner  one cavity: direct sprue gate to the top of the part; several: runner on the parting plane from
                          the sprue to an edge gate on the side of each cavity facing the sprue
    plastic, hot runner   manifold plate between the A plate and the top clamp plate, manifold, a nozzle per cavity to the
                          top of the part (Tool features → hot runner)
    die casting           shot sleeve and biscuit beside the cavities, runner and gate to each cavity, overflows on the far
                          side of each cavity with a vacuum vent to the insert edge
    slides                (Tool features → slides per cavity) slide block in the B side next to the part, heel (wedge) block
                          and angle pin in the A side; the undercut shape of the slide face is left to the designer
    lifters               (lifters per cavity) inclined lifter rods from the ejector retainer plate to the part
    EPS                   steam chambers with back plates behind the cavity and the core, fill injectors to the cavity,
                          steam vents on the moulding faces (count and pitch from the tool BOM and the Design rules)
    blow moulding         neck insert and base (push-up) insert cut from the two halves at the ends of the bottle, blow pin
Every tool cuts the components it crosses (plates and inserts); an insert used for several cavities becomes one item per
cavity when the cut differs. Sizes come from Mould & die database → Design rules.
"""

from __future__ import annotations

import copy
import math

import cadquery as cq

from .tool_design import Comp, _line


def _hits(shape, x, y):
    """z of every crossing of the vertical line through (x, y) with the shape."""
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    it = IntCurvesFace_ShapeIntersector()
    it.Load(shape.wrapped, 1e-4)
    it.Perform(gp_Lin(gp_Pnt(x, y, -1e5), gp_Dir(0, 0, 1)), 0, 2e5)
    return sorted(it.Pnt(i).Z() for i in range(1, it.NbPnt() + 1))


def cut(comps: list, names, tool, label: str = "") -> int:
    """Cut a tool solid (world coordinates) from every component whose name starts with one of `names`."""
    names = (names,) if isinstance(names, str) else names
    tb = tool.BoundingBox()
    n = 0
    for c in list(comps):
        if c.kind == "ref" or not any(c.name.startswith(x) for x in names):
            continue
        hit = []
        cb = c.shape.BoundingBox()
        for i, (x, y, z) in enumerate(c.locs):
            if not (cb.xmax + x < tb.xmin or tb.xmax < cb.xmin + x or cb.ymax + y < tb.ymin or tb.ymax < cb.ymin + y
                    or cb.zmax + z < tb.zmin or tb.zmax < cb.zmin + z):
                hit.append(i)
        if not hit:
            continue
        if c.qty > 1:      # one item per cavity: the cut differs from one cavity to the next
            k = comps.index(c)
            comps.remove(c)
            for j, loc in enumerate(c.locs, start=1):
                d = copy.copy(c)
                d.name, d.locs, d.notes = f"{c.name} {j}", [loc], list(c.notes)
                comps.insert(k + j - 1, d)
            return cut(comps, names, tool, label)
        x, y, z = c.locs[0]
        c.shape = c.shape.cut(tool.translate(cq.Vector(-x, -y, -z)))
        if label and label not in c.notes:
            c.notes.append(label)
        n += 1
    return n


def _shift(comps, z_from: float, dz: float):
    for c in comps:
        if c.kind != "ref" and min(z for _, _, z in c.locs) >= z_from - 1e-6:
            c.locs = [(x, y, z + dz) for x, y, z in c.locs]


def _bar(p0, p1, d):
    """Cylinder of diameter d from p0 to p1."""
    v = cq.Vector(*p1) - cq.Vector(*p0)
    return cq.Solid.makeCylinder(d / 2, v.Length, cq.Vector(*p0), v.normalized())


def _box(x0, y0, z0, x1, y1, z1):
    return cq.Solid.makeBox(abs(x1 - x0), abs(y1 - y0), abs(z1 - z0), cq.Vector(min(x0, x1), min(y0, y1), min(z0, z1)))


def apply(ctx: dict) -> None:
    """Add the process features to ctx['comps'] and ctx['notes'] (in place)."""
    pt = ctx["part_type"]
    if pt in ("plastic", "die_casting"):
        _gating(ctx)
        _slides(ctx)
        _lifters(ctx)
    elif pt == "eps":
        _eps(ctx)
    elif pt == "blow":
        _blow(ctx)


# ---------- gates, runners, hot runner, shot sleeve, overflows ----------

def _gate_side(cx, cy, hx, hy):
    dx, dy = hx - cx, hy - cy
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return (0.0, -1.0)
    return (math.copysign(1, dx), 0.0) if abs(dx) >= abs(dy) else (0.0, math.copysign(1, dy))


def _gating(ctx):
    R, comps, notes, bb, pl, cells = ctx["rules"], ctx["comps"], ctx["notes"], ctx["bb"], ctx["pl"], ctx["cells"]
    pt, s = ctx["part_type"], ctx["part"]
    hot = pt == "plastic" and ctx["val"]("v:hot_runner", 0) > 0
    if hot:
        mp = R("hot_manifold_plate_mm", 80)
        nd = R("hot_nozzle_d_mm", 30)
        z_tc = ctx["z_tc"]
        _shift(comps, z_tc, mp)
        ctx["z_tc"] = z_tc + mp
        ctx["stack"] += mp
        L, W = ctx["L"], ctx["W"]
        frame = _box(-L / 2, -W / 2, z_tc, L / 2, W / 2, z_tc + mp)
        xs = [cx for cx, _ in cells]
        ys = [cy for _, cy in cells]
        ml, mw = max(xs) - min(xs) + 2 * nd + 80, max(ys) - min(ys) + 2 * nd + 80
        hole = _box(-ml / 2 - 10, -mw / 2 - 10, z_tc, ml / 2 + 10, mw / 2 + 10, z_tc + mp - 20)
        comps.append(Comp("Manifold plate", frame.cut(hole).translate(cq.Vector(L / 2, W / 2, -z_tc)), [(-L / 2, -W / 2, z_tc)],
                          material=ctx["base_mat"], make=ctx["base_make"], color="plate", size=(L, W, mp), drawing="solid",
                          notes=["Frame round the hot-runner manifold"]))
        ml_line = _line(ctx["lines"], "Hot runner manifold")
        comps.append(Comp("Hot runner manifold", _box(-ml / 2, -mw / 2, 0, ml / 2, mw / 2, mp - 30), [(0.0, 0.0, z_tc + 5)], kind="std",
                          make=ml_line.get("make") or "", std=" ".join(v for v in (ml_line.get("std_part") or "", ml_line.get("part_number") or "") if v)
                          or "Hot runner manifold (heated)", size=(ml, mw, mp - 30), color="std", drawing="none"))
        nz_line = _line(ctx["lines"], "Hot runner nozzle")
        locs = []
        for cx, cy in cells:
            zs = _hits(s, 0, 0)
            ztop = max(zs) if zs else bb.zmax
            locs.append((cx, cy, ztop))
            tool = _bar((cx, cy, ztop - 0.01), (cx, cy, z_tc + 5), nd + 2)
            cut(comps, ("A plate", "Cavity insert"), tool, "Hot-runner nozzle bore")
        nl = z_tc + 5 - min(z for _, _, z in locs)
        comps.append(Comp(f"Hot runner nozzle Ø{nd:g}", cq.Solid.makeCylinder(nd / 2, nl), locs, kind="std", make=nz_line.get("make") or "",
                          std=" ".join(v for v in (nz_line.get("std_part") or "", nz_line.get("part_number") or "") if v) or
                          f"Hot runner nozzle Ø{nd:g} × {nl:.0f}", size=(nd, nd, nl), color="std", drawing="none"))
        notes.append(f"Hot runner: manifold plate {mp:g} mm, {len(cells)} nozzle(s) gating on the top of the part.")
        return
    rd = R("runner_d_mm", 6)
    gw, gh = R("gate_w_mm", 3), R("gate_h_mm", 1.2)
    if pt == "die_casting":
        ssd = R("shot_sleeve_d_mm", 80)
        hx, hy = 0.0, -(ctx["pocket_w"] / 2 + ssd * 0.75)
        if abs(hy) + ssd / 2 > ctx["W"] / 2 - 20:
            hy = -(ctx["W"] / 2 - ssd / 2 - 25)
        sleeve = _bar((hx, hy, pl), (hx, hy, ctx["z_tc"] + ctx["tc"] + 1), ssd)
        cut(comps, ("A plate", "Top clamp plate", "Cavity insert"), sleeve, "Shot sleeve bore")
        biscuit = _bar((hx, hy, pl - R("biscuit_mm", 25)), (hx, hy, pl + 0.01), ssd)
        cut(comps, ("B plate", "Core insert"), biscuit, "Biscuit pocket")
        ss_line = _line(ctx["lines"], "Shot sleeve")
        sl = ctx["z_tc"] + ctx["tc"] + R("shot_sleeve_out_mm", 60) - pl
        comps.append(Comp(f"Shot sleeve Ø{ssd:g}", cq.Solid.makeCylinder(ssd / 2 + 15, sl).cut(cq.Solid.makeCylinder(ssd / 2, sl)),
                          [(hx, hy, pl)], kind="std", make=ss_line.get("make") or "", std=f"Shot sleeve ID {ssd:g} × {sl:.0f} (H13, nitrided)",
                          size=(ssd + 30, ssd + 30, sl), color="std", drawing="none"))
    else:
        hx, hy = 0.0, 0.0
        if len(cells) == 1:
            zs = _hits(s, 0, 0)
            if zs:
                gd = R("sprue_bush_d_mm") * 0.375
                cut(comps, ("Cavity insert",), _bar((0, 0, max(zs) - 0.01), (0, 0, pl + ctx["ha"] + 1), gd), "Direct sprue gate")
                notes.append(f"Gate: direct sprue gate Ø{gd:g} on the top of the part.")
                return
    for cx, cy in cells:
        ux, uy = _gate_side(cx, cy, hx, hy)
        ex = cx + ux * (bb.xlen / 2)
        ey = cy + uy * (bb.ylen / 2)
        out = (ex + ux * 3, ey + uy * 3)
        runner = _bar((hx, hy, pl), (out[0], out[1], pl), rd)
        cut(comps, ("A plate", "B plate", "Cavity insert", "Core insert"), runner, f"Runner Ø{rd:g} on the parting plane")
        gx0, gx1 = sorted((ex - ux * 0.5, out[0]))
        gy0, gy1 = sorted((ey - uy * 0.5, out[1]))
        if ux:
            gate = _box(gx0, cy - gw / 2, pl, gx1, cy + gw / 2, pl + gh)
        else:
            gate = _box(cx - gw / 2, gy0, pl, cx + gw / 2, gy1, pl + gh)
        cut(comps, ("Cavity insert", "Core insert"), gate, f"Edge gate {gw:g} × {gh:g}")
        if pt == "die_casting":
            n = int(R("overflows", 3))
            ow, olen, oh = R("overflow_w_mm", 12), R("overflow_l_mm", 20), R("overflow_h_mm", 6)
            for k in range(n):
                f = (k + 1) / (n + 1) - 0.5
                if ux:
                    px = cx - ux * (bb.xlen / 2 + 2 + olen / 2)
                    py = cy + f * bb.ylen
                    ov = _box(px - olen / 2, py - ow / 2, pl - oh, px + olen / 2, py + ow / 2, pl + 0.01)
                    link = _box(min(px + ux * olen / 2, cx - ux * bb.xlen / 2), py - 2, pl - 1, max(px + ux * olen / 2, cx - ux * bb.xlen / 2),
                                py + 2, pl + 0.01)
                    vent = _box(min(px, cx - ux * ctx["il"] / 2), py - 4, pl - 0.3, max(px, cx - ux * ctx["il"] / 2), py + 4, pl + 0.01)
                else:
                    px = cx + f * bb.xlen
                    py = cy - uy * (bb.ylen / 2 + 2 + olen / 2)
                    ov = _box(px - ow / 2, py - olen / 2, pl - oh, px + ow / 2, py + olen / 2, pl + 0.01)
                    link = _box(px - 2, min(py + uy * olen / 2, cy - uy * bb.ylen / 2), pl - 1, px + 2,
                                max(py + uy * olen / 2, cy - uy * bb.ylen / 2), pl + 0.01)
                    vent = _box(px - 4, min(py, cy - uy * ctx["iw"] / 2), pl - 0.3, px + 4, max(py, cy - uy * ctx["iw"] / 2), pl + 0.01)
                cut(comps, ("Core insert",), ov.fuse(link).fuse(vent), "Overflows with vacuum vents")
    if pt == "die_casting":
        notes.append(f"Shot sleeve Ø{R('shot_sleeve_d_mm', 80):g} with biscuit beside the cavities, runner Ø{rd:g} and gate "
                     f"{gw:g} × {gh:g} to each cavity, {int(R('overflows', 3))} overflows with vacuum vents per cavity.")
    else:
        notes.append(f"Cold runner Ø{rd:g} on the parting plane from the sprue, edge gate {gw:g} × {gh:g} to each cavity.")


# ---------- slides and lifters ----------

def _slides(ctx):
    n = int(round(ctx["val"]("v:slides_per_cavity", 0)))
    if n <= 0:
        return
    R, comps, bb, pl, cells = ctx["rules"], ctx["comps"], ctx["bb"], ctx["pl"], ctx["cells"]
    depth, ang, apd = R("slide_depth_mm", 60), math.radians(R("slide_angle_deg", 18)), R("angle_pin_d_mm", 16)
    sides = [(1, 0), (-1, 0), (0, 1), (0, -1)][:min(n, 4)]
    sh = min(ctx["hb"] * 0.8, R("slide_h_mm", 60))
    slide_shapes, wedge_shapes, pin_locs = [], [], []
    for cx, cy in cells:
        for ux, uy in sides:
            span = 0.6 * (bb.ylen if ux else bb.xlen)
            e0 = (bb.xlen if ux else bb.ylen) / 2 + 0.5
            e1 = (ctx["il"] if ux else ctx["iw"]) / 2 + depth
            if ux:
                sl = _box(cx + ux * e0, cy - span / 2, pl - sh, cx + ux * e1, cy + span / 2, pl)
                wd = _box(cx + ux * (e1 - depth * 0.3), cy - span / 2, pl, cx + ux * (e1 + 30), cy + span / 2, pl + min(ctx["ta"] * 0.6, 60))
                px, py = cx + ux * (e0 + e1) / 2, cy
            else:
                sl = _box(cx - span / 2, cy + uy * e0, pl - sh, cx + span / 2, cy + uy * e1, pl)
                wd = _box(cx - span / 2, cy + uy * (e1 - depth * 0.3), pl, cx + span / 2, cy + uy * (e1 + 30), pl + min(ctx["ta"] * 0.6, 60))
                px, py = cx, cy + uy * (e0 + e1) / 2
            cut(comps, ("Core insert", "B plate", "Cavity insert"), sl.translate(cq.Vector(0, 0, 0)), "Slide pocket")
            cut(comps, ("A plate",), wd, "Heel block pocket")
            slide_shapes.append(sl)
            wedge_shapes.append(wd)
            top = (px - ux * math.tan(ang) * ctx["ta"], py - uy * math.tan(ang) * ctx["ta"], pl + ctx["ta"])
            pin = _bar((px + ux * math.tan(ang) * sh * 0.8, py + uy * math.tan(ang) * sh * 0.8, pl - sh * 0.8), top, apd)
            cut(comps, ("A plate",), _bar((px + ux * math.tan(ang) * sh * 0.8, py + uy * math.tan(ang) * sh * 0.8, pl - sh * 0.8), top, apd + 1),
                "Angle pin bore")
            pin_locs.append(pin)
    sm = _line(ctx["lines"], "Slide block")
    for k, (sl, wd) in enumerate(zip(slide_shapes, wedge_shapes), start=1):
        b = sl.BoundingBox()
        comps.append(Comp(f"Slide {k}", sl.translate(cq.Vector(-b.xmin, -b.ymin, -b.zmin)), [(b.xmin, b.ymin, b.zmin)],
                          material=sm.get("grade") or ctx["core_mat"], hardness="", color="hard", size=(b.xlen, b.ylen, b.zlen), drawing="solid",
                          notes=["Moulding face of the slide (the undercut shape) to be cut by the designer from the part",
                                 f"Angle pin {math.degrees(ang):g}°, wear plates and lock as Slide mechanism"]))
        w = wd.BoundingBox()
        comps.append(Comp(f"Heel block {k}", wd.translate(cq.Vector(-w.xmin, -w.ymin, -w.zmin)), [(w.xmin, w.ymin, w.zmin)],
                          material=ctx["core_mat"], color="hard", size=(w.xlen, w.ylen, w.zlen), drawing="solid",
                          notes=["Locks the slide when the mould is closed"]))
    am = _line(ctx["lines"], "Slide mechanism")
    for k, pin in enumerate(pin_locs, start=1):
        b = pin.BoundingBox()
        comps.append(Comp(f"Angle pin {k}", pin.translate(cq.Vector(-b.xmin, -b.ymin, -b.zmin)), [(b.xmin, b.ymin, b.zmin)], kind="std",
                          make=am.get("make") or "", std=f"Angle pin Ø{apd:g} at {math.degrees(ang):g}°", size=(b.xlen, b.ylen, b.zlen),
                          color="std", drawing="none"))
    ctx["notes"].append(f"Slides: {len(slide_shapes)} slide(s) with heel blocks and {math.degrees(ang):g}° angle pins "
                        "(the undercut shape of each slide face is cut by the designer).")


def _lifters(ctx):
    n = int(round(ctx["val"]("v:lifters_per_cavity", 0)))
    if n <= 0 or not ctx.get("ejection"):
        return
    R, comps, bb, cells, s = ctx["rules"], ctx["comps"], ctx["bb"], ctx["cells"], ctx["part"]
    lw, ang = R("lifter_w_mm", 12), math.radians(R("lifter_angle_deg", 8))
    z0 = ctx["z_ret"] + ctx["ej_ret_h"]
    made = []
    for cx, cy in cells:
        for k in range(min(n, 4)):
            ux, uy = [(1, 0), (-1, 0), (0, 1), (0, -1)][k]
            lx, ly = ux * (bb.xlen / 2 - lw * 1.5), uy * (bb.ylen / 2 - lw * 1.5)
            zs = [z for z in _hits(s, lx, ly) if z > ctx["pl"] - 1]
            if not zs:
                continue
            ztop = min(zs)
            h = ztop - z0
            off = math.tan(ang) * h
            bot = (cx + lx - ux * off, cy + ly - uy * off, z0)
            top = (cx + lx, cy + ly, ztop)
            rod = _bar(bot, top, lw)
            cut(comps, ("Core insert", "B plate", "Support plate"), _bar(bot, top, lw + 1), "Lifter bore")
            made.append(rod)
    lm = _line(ctx["lines"], "Lifter")
    for k, rod in enumerate(made, start=1):
        b = rod.BoundingBox()
        comps.append(Comp(f"Lifter {k}", rod.translate(cq.Vector(-b.xmin, -b.ymin, -b.zmin)), [(b.xmin, b.ymin, b.zmin)],
                          material=lm.get("grade") or ctx["core_mat"], color="hard", size=(b.xlen, b.ylen, b.zlen), drawing="solid",
                          notes=[f"Inclined {math.degrees(ang):g}°: moves inwards while ejecting; head shaped by the designer to the undercut"]))
    if made:
        ctx["notes"].append(f"Lifters: {len(made)} inclined lifter(s) {math.degrees(ang):g}° from the ejector retainer plate.")


# ---------- EPS ----------

def _eps(ctx):
    R, comps, bb, pl, cells, s = ctx["rules"], ctx["comps"], ctx["bb"], ctx["pl"], ctx["cells"], ctx["part"]
    L, W = ctx["L"], ctx["W"]
    ch, wall, back = R("steam_chamber_mm", 120), R("steam_chamber_wall_mm", 20), R("steam_back_plate_mm", 15)
    z_top = pl + ctx["ta"]
    z_bot = pl - ctx["tb"]
    for name, z in (("Steam chamber frame (cavity side)", z_top), ("Steam chamber frame (core side)", z_bot - ch)):
        frame = _box(-L / 2, -W / 2, 0, L / 2, W / 2, ch).cut(_box(-L / 2 + wall, -W / 2 + wall, -1, L / 2 - wall, W / 2 - wall, ch + 1))
        comps.append(Comp(name, frame.translate(cq.Vector(L / 2, W / 2, 0)), [(-L / 2, -W / 2, z)], material=ctx["base_mat"],
                          color="plate", size=(L, W, ch), drawing="solid", notes=["Steam chamber; steam, drain and cooling valves on its sides"]))
    for name, z in (("Steam chamber back plate (cavity side)", z_top + ch), ("Steam chamber back plate (core side)", z_bot - ch - back)):
        comps.append(Comp(name, _box(0, 0, 0, L, W, back), [(-L / 2, -W / 2, z)], material=ctx["base_mat"], color="shoe",
                          size=(L, W, back), drawing="solid"))
    nfill = int(_line(ctx["lines"], "Fill gun").get("quantity") or len(cells))
    per = max(1, round(nfill / max(len(cells), 1)))
    idd = R("injector_d_mm", 20)
    locs = []
    for cx, cy in cells:
        cols_ = max(1, int(math.ceil(math.sqrt(per))))
        for k in range(per):
            fx = ((k % cols_) + 0.5) / cols_ - 0.5
            fy = ((k // cols_) + 0.5) / max(1, math.ceil(per / cols_)) - 0.5
            x, y = cx + fx * bb.xlen * 0.6, cy + fy * bb.ylen * 0.6
            zs = _hits(s, x - cx, y - cy)
            if not zs:
                continue
            zt = max(zs)
            cut(comps, ("Cavity insert", "A plate"), _bar((x, y, zt - 0.01), (x, y, z_top + 0.01), idd + 1), "Fill injector bore")
            locs.append((x, y, zt))
    fl = _line(ctx["lines"], "Fill gun")
    if locs:
        h = z_top + ch - min(z for _, _, z in locs)
        comps.append(Comp(f"Fill injector Ø{idd:g}", cq.Solid.makeCylinder(idd / 2, h), locs, kind="std", make=fl.get("make") or "",
                          std=f"EPS fill injector (fill gun) Ø{idd:g}", size=(idd, idd, h), color="std", drawing="none"))
    vd, vp = R("vent_d_mm", 8), R("vent_pitch_mm", 25)
    vlocs = []
    for cx, cy in cells:
        nx, ny = max(1, int(bb.xlen // vp)), max(1, int(bb.ylen // vp))
        for i in range(nx):
            for j in range(ny):
                x = bb.xmin + (i + 0.5) * bb.xlen / nx
                y = bb.ymin + (j + 0.5) * bb.ylen / ny
                zs = _hits(s, x, y)
                if zs:
                    vlocs.append((cx + x, cy + y, max(zs)))
                    vlocs.append((cx + x, cy + y, min(zs) - 6))
    vl = _line(ctx["lines"], "Steam vent")
    if vlocs:
        comps.append(Comp(f"Steam vent Ø{vd:g}", cq.Solid.makeCylinder(vd / 2, 6), vlocs, kind="std", make=vl.get("make") or "",
                          std=f"Steam vent plug Ø{vd:g} (slotted, stainless), pitch {vp:g} mm on the cavity and core faces",
                          size=(vd, vd, 6), color="std", drawing="none"))
    ctx["stack"] += 2 * (ch + back)
    ctx["notes"].append(f"EPS: steam chambers {ch:g} mm with back plates on both halves, {len(locs)} fill injector(s), "
                        f"{len(vlocs)} steam vents at {vp:g} mm pitch.")


# ---------- blow moulding ----------

def _blow(ctx):
    R, comps, bb, s, cells, pl = ctx["rules"], ctx["comps"], ctx["bb"], ctx["part"], ctx["cells"], ctx["pl"]
    along_x = bb.xlen >= bb.ylen
    from .mould_design import _section_area_axis
    a0 = _section_area_axis(s, "x" if along_x else "y", 0.03)
    a1 = _section_area_axis(s, "x" if along_x else "y", 0.97)
    neck_low = a0 <= a1
    nl, bl = R("neck_insert_mm", 30), R("base_insert_mm", 25)
    zl, zh = pl - ctx["hb"], pl + ctx["ha"]
    made = []
    for cx, cy in cells:
        lo = (bb.xmin if along_x else bb.ymin)
        hi = (bb.xmax if along_x else bb.ymax)
        for name, at_lo, length in (("Neck insert", neck_low, nl), ("Base (push-up) insert", not neck_low, bl)):
            if along_x:
                x0 = (cx - ctx["il"] / 2) if at_lo else (cx + hi - length)
                x1 = (cx + lo + length) if at_lo else (cx + ctx["il"] / 2)
                box = _box(x0, cy - ctx["iw"] / 2, zl, x1, cy + ctx["iw"] / 2, zh)
            else:
                y0 = (cy - ctx["iw"] / 2) if at_lo else (cy + hi - length)
                y1 = (cy + lo + length) if at_lo else (cy + ctx["iw"] / 2)
                box = _box(cx - ctx["il"] / 2, y0, zl, cx + ctx["il"] / 2, y1, zh)
            cut(comps, ("Cavity insert", "Core insert"), box, f"{name} seat")
            ins = box.cut(s.translate(cq.Vector(cx, cy, 0)))
            made.append((name, ins))
    for k, (name, ins) in enumerate(made, start=1):
        b = ins.BoundingBox()
        comps.append(Comp(f"{name} {k}" if len(cells) > 1 else name, ins.translate(cq.Vector(-b.xmin, -b.ymin, -b.zmin)),
                          [(b.xmin, b.ymin, b.zmin)], material=ctx["core_mat"], color="hard", size=(b.xlen, b.ylen, b.zlen),
                          drawing="solid", notes=["Split in two halves at the parting plane by the designer", "Cooled; vents at the parting line"]))
    bp = R("blow_pin_d_mm", 20)
    end = (bb.xmin - 60 if neck_low else bb.xmax + 60) if along_x else (bb.ymin - 60 if neck_low else bb.ymax + 60)
    comps.append(Comp(f"Blow pin / stretch rod Ø{bp:g}", cq.Solid.makeCylinder(bp / 2, 60 + 5, cq.Vector(0, 0, 0),
                                                                             cq.Vector(1 if neck_low else -1, 0, 0) if along_x else
                                                                             cq.Vector(0, 1 if neck_low else -1, 0)),
                      [((end if along_x else 0) + cells[0][0], (0 if along_x else end) + cells[0][1], pl)], kind="std",
                      std="Blow nozzle with stretch rod", size=(bp, bp, 65), color="std", drawing="none"))
    ctx["notes"].append(f"Blow mould: neck insert ({nl:g} mm) and base push-up insert ({bl:g} mm) per cavity, blow nozzle / stretch rod at the neck.")
