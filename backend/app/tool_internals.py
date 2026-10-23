"""Details inside the tool in 3D (roadmap stage 22): ejector and return pins, cooling channels and connectors, cap screws and dowels,
stripper springs and bolts. Sizes and counts come from the master-data table *Tool detail rules*; the 3D work only finds places for them.

Every detail is both a component (a screw, a pin, a channel connector) and a feature of the parts it passes through: the plates and inserts
get the clearance holes, counterbores, tapped holes and channels cut in, so the manufacturing drawings show them and the overlap check
proves that they fit.
"""

from __future__ import annotations

import math

import cadquery as cq
import numpy as np

from . import formula, master_data, mould_db

TAP_DRILL = {6: 5.0, 8: 6.8, 10: 8.5, 12: 10.2, 14: 12.0, 16: 14.0, 20: 17.5, 24: 21.0}   # ISO 261 coarse thread tap drills (mm)
EXAMPLE = "EXAMPLE rule - replace with your toolroom practice"
MOULD_ENV = ("base_l_mm", "base_w_mm", "plate_a_mm", "plate_b_mm", "clamp_mm", "support_mm", "spacer_mm", "ejector_mm", "pocket_l_mm", "pocket_w_mm",
             "cavities", "part_h_mm", "projected_area_cm2", "pillar_dia_mm", "bush_od_mm", "bom_ejector_pins", "bom_return_pins", "bom_cooling_connectors",
             "hot_runner", "slides", "lifters")
SEED = [
    ("mould", "ejector_pin_dia_mm", "4 if part_h_mm < 40 else 6 if part_h_mm < 100 else 8", "mm", "Ejector pin diameter"),
    ("mould", "ejector_head_dia_mm", "ejector_pin_dia_mm + 4", "mm", "Ejector pin head diameter"),
    ("mould", "ejector_head_t_mm", "4", "mm", "Ejector pin head thickness (seated in a counterbore of the ejector plate)"),
    ("mould", "ejector_pins", "bom_ejector_pins", "pcs", "Ejector pins wanted (the tool-cost BOM quantity); fewer are placed if the part has no room"),
    ("mould", "return_pin_dia_mm", "round(max(12, 0.6 * pillar_dia_mm))", "mm", "Return pin diameter"),
    ("mould", "return_pins", "4", "pcs", "Return pins"),
    ("mould", "cool_dia_mm", "8 if min(base_l_mm, base_w_mm) < 450 else 10 if min(base_l_mm, base_w_mm) < 700 else 12", "mm", "Cooling channel diameter"),
    ("mould", "cool_min_wall_mm", "max(4, 0.6 * cool_dia_mm)", "mm", "Smallest steel wall between a channel and a cavity, pin or insert edge"),
    ("mould", "cool_channels", "min(8, max(2, 2 * ceil(pocket_w_mm / (8 * cool_dia_mm))))", "pcs", "Cooling channels wanted in each insert"),
    ("mould", "connector_len_mm", "12", "mm", "Length of a cooling connector outside the plate"),
    ("mould", "screw_dia_mm", "max(8, round(min(base_l_mm, base_w_mm) / 30))", "mm", "Socket head cap screw size"),
    ("mould", "screws_a", "4 * max(1, ceil(base_l_mm / 250))", "pcs", "Screws holding the A plate to the top clamp plate"),
    ("mould", "screws_b", "4", "pcs", "Screws holding the B plate, support plate, spacer blocks and bottom clamp plate together"),
    ("mould", "dowel_dia_mm", "max(8, screw_dia_mm)", "mm", "Dowel pin diameter"),
    ("mould", "dowels_per_interface", "2", "pcs", "Dowel pins at each plate interface"),
    ("mould", "manifold_plate_t_mm", "max(40, 0.6 * plate_a_mm)", "mm", "Hot runner manifold plate thickness"),
    ("mould", "hr_nozzle_dia_mm", "22", "mm", "Hot runner nozzle diameter"),
    ("mould", "hr_manifold_w_mm", "40", "mm", "Hot runner manifold bar width"),
    ("mould", "slide_wall_mm", "8", "mm", "Steel around the undercut in a slide"),
    ("mould", "slide_guide_mm", "40", "mm", "Length of slide guided behind the undercut at the end of its stroke"),
    ("mould", "slide_stroke_extra_mm", "3", "mm", "Stroke beyond the undercut depth"),
    ("mould", "angle_pin_dia_mm", "max(12, round(0.6 * pillar_dia_mm))", "mm", "Angle pin diameter"),
    ("mould", "angle_pin_deg", "18", "°", "Angle pin inclination from the opening direction"),
    ("mould", "min_void_mm3", "30", "mm³", "Smallest void between the envelopes that gets a slide or lifter"),
    ("mould", "min_void_thickness_mm", "1", "mm", "Thinner voids are mould-making slivers, not undercuts"),
    ("sheet_metal", "spring_od_mm", "max(20, round(16 + 0.04 * spring_rating_kgf))", "mm", "Stripper spring outside diameter (grows with the rating)"),
    ("sheet_metal", "spring_pocket_mm", "30", "mm", "Depth of the spring pocket in the punch plate"),
    ("sheet_metal", "stripper_bolts", "4", "pcs", "Shoulder bolts holding the stripper plate"),
    ("sheet_metal", "wiper_thickness_mm", "max(10, 4 * t)", "mm", "Thickness of a wiper steel beside a flange"),
]


def seed() -> int:
    db = mould_db.tables()
    migrated = False
    for r in db["detail_rules"]:
        if r["name"] == "spring_od_mm" and r["formula"] == "max(20, round(0.4 * spring_rating_kgf))":
            r["formula"] = "max(20, round(16 + 0.04 * spring_rating_kgf))"
            migrated = True
    have = {(r["tool_group"], r["name"]) for r in db["detail_rules"]}
    top = max((r["step"] for r in db["detail_rules"]), default=0)
    n = 0
    for g, name, f, unit, label in SEED:
        if (g, name) not in have:
            n += 1
            db["detail_rules"].append({"tool_group": g, "step": top + n, "name": name, "formula": f, "unit": unit, "label": label,
                                       "is_example": 1, "notes": EXAMPLE})
    if n or migrated:
        mould_db.write(db)
    return n


def env_names(group: str, clean: dict) -> dict:
    from . import tool_design
    if group == "foundry":
        from . import foundry_design
        env = {k: 1.0 for k in foundry_design.FOUNDRY_ENV}
    else:
        env = {k: 1.0 for k in MOULD_ENV} if group == "mould" else {k: 1.0 for k in tool_design.STAGE_VARS}
    if group == "sheet_metal":
        env |= {r["name"]: 1.0 for r in clean.get("stage_rules", [])}
        env |= {k: 1.0 for k in ("springback_deg", "draw_ratio", "progressive_ok")}
    env |= {k: float(v) for k, v in master_data.parameters({"mould": "plastic"}.get(group, group)).items() if isinstance(v, (int, float))}
    return env


def validate(clean: dict) -> None:
    for group in ("mould", "sheet_metal", "foundry"):
        env = env_names(group, clean)
        for r in sorted((r for r in clean.get("detail_rules", []) if r["tool_group"] == group), key=lambda r: r["step"]):
            if not r["name"].isidentifier():
                raise mould_db.MouldDbError(f"Tool detail rules '{r['name']}' must be one word (letters, digits and _).")
            try:
                env[r["name"]] = float(formula.evaluate(r["formula"], env))
            except formula.FormulaError as exc:
                raise mould_db.MouldDbError(f"Tool detail rules ({r['name']}): {exc}") from None
            except (ArithmeticError, ValueError):
                env[r["name"]] = 1.0


def values(group: str, env: dict) -> dict:
    """Rule values of a tool group for a design (rules run in order; each can use the ones before it)."""
    out = dict(env)
    for r in sorted((r for r in mould_db.tables()["detail_rules"] if r["tool_group"] == group), key=lambda r: r["step"]):
        try:
            out[r["name"]] = float(formula.evaluate(r["formula"], out))
        except (formula.FormulaError, ArithmeticError, ValueError) as exc:
            raise ValueError(f"Tool detail rule '{r['name']}' ({r['formula']}): {exc}") from None
    return out


# ------------------------------------------------------------ small geometry helpers

def cyl(r: float, h: float, x: float, y: float, z0: float, axis=(0, 0, 1)) -> cq.Shape:
    return cq.Solid.makeCylinder(r, h, cq.Vector(x, y, z0), cq.Vector(*axis))


def find(comps: list[dict], name: str) -> dict | None:
    return next((c for c in comps if c["name"] == name), None)


def add(comps, name, group, shape, color, cls, standard=True):
    comps.append({"name": name, "group": group, "shape": shape, "color": color, "cls": cls, "standard": standard})


def cut(comp: dict, solid) -> None:
    comp["shape"] = comp["shape"].cut(solid)


def _inside(shape: cq.Shape, x, y, z) -> bool:
    return shape.isInside(cq.Vector(x, y, z), 1e-3)


def farthest(points: np.ndarray, n: int) -> list[int]:
    """Indices of n points spread out as far as possible (farthest-point sampling from the point nearest the centre)."""
    if len(points) <= n:
        return list(range(len(points)))
    first = int(np.argmin(((points - points.mean(0)) ** 2).sum(1)))
    chosen = [first]
    d = ((points - points[first]) ** 2).sum(1)
    while len(chosen) < n:
        k = int(np.argmax(d))
        chosen.append(k)
        d = np.minimum(d, ((points - points[k]) ** 2).sum(1))
    return chosen


def ring_positions(L: float, W: float, inset: float, n: int, circles=(), rects=(), spacing: float = 0.0, cx: float = 0.0, cy: float = 0.0) -> list[tuple]:
    """Up to n positions on a rectangle `inset` inside the L × W outline, spread evenly, keeping clear of circles (x, y, r) and rects (x0, y0, x1, y1)."""
    pts = []
    for ins in (inset if isinstance(inset, (list, tuple)) else [inset]):
        step = max(ins, 8.0)
        xs = np.arange(-L / 2 + ins, L / 2 - ins + 1e-6, step)
        ys = np.arange(-W / 2 + ins, W / 2 - ins + 1e-6, step)
        for x in xs:
            pts += [(cx + x, cy - W / 2 + ins), (cx + x, cy + W / 2 - ins)]
        for y in ys[1:-1]:
            pts += [(cx - L / 2 + ins, cy + y), (cx + L / 2 - ins, cy + y)]

    def ok(p):
        if any(math.hypot(p[0] - c[0], p[1] - c[1]) < c[2] for c in circles):
            return False
        return not any(r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3] for r in rects)
    pts = [p for p in dict.fromkeys(pts) if ok(p)]
    if not pts or n <= 0:
        return []
    arr = np.array(pts)
    pick = farthest(arr, min(n, len(arr)))
    return [pts[i] for i in pick]


# ------------------------------------------------------------ fasteners

def fasten(comps: list[dict], chain: list[str], positions: list[tuple], sd: float, down: bool, name: str, cls: str = "screw",
           color=(0.62, 0.64, 0.68)) -> int:
    """Socket head cap screws through a stack of components. chain = names from the head side to the tapped end; down = head on top
    of chain[0] and the screw goes down, else head under chain[0] and it goes up. Cuts the counterbore, clearance and tapped holes,
    adds the screws as standard components. Returns the number placed."""
    plates = [find(comps, n) for n in chain]
    if any(p is None for p in plates):
        return 0
    tap = TAP_DRILL.get(int(round(sd)), sd * 0.85)
    placed = 0
    for (x, y) in positions:
        bbs = [p["shape"].BoundingBox() for p in plates]
        if any(not (b.xmin < x < b.xmax and b.ymin < y < b.ymax) for b in bbs):
            continue
        sign = -1 if down else 1
        face0 = bbs[0].zmax if down else bbs[0].zmin
        head_h, head_d = sd, 1.5 * sd
        cb_depth = head_h + 1
        # counterbore and clearance hole in the head plate
        z0 = face0 - cb_depth if down else face0
        cut(plates[0], cyl(head_d / 2 + 0.5, cb_depth, x, y, z0))
        for p, b in zip(plates[:-1], bbs[:-1]):
            cut(p, cyl((sd + 1) / 2, b.zlen + 2, x, y, b.zmin - 1))
        last, lb = plates[-1], bbs[-1]
        depth = min(1.5 * sd, lb.zlen - 3)
        top = lb.zmax if down else lb.zmin
        z_t = top - depth if down else top
        cut(last, cyl(tap / 2, depth, x, y, z_t))
        # the screw: head in the counterbore, shank through the clearance holes, thread (minor diameter) in the tapped hole
        z_head_bottom = face0 - head_h if down else face0 + head_h
        z_end = (lb.zmax - depth) if down else (lb.zmin + depth)
        head = cyl(head_d / 2, head_h, x, y, face0 - head_h if down else face0)
        if down:
            body = cyl(sd / 2, z_head_bottom - lb.zmax, x, y, lb.zmax)
            thread = cyl(tap / 2, depth, x, y, z_end)
        else:
            body = cyl(sd / 2, lb.zmin - z_head_bottom, x, y, z_head_bottom)
            thread = cyl(tap / 2, depth, x, y, lb.zmin)
        screw = head.fuse(body).fuse(thread)
        add(comps, name, "lower" if (plates[0]["group"] == "lower") else "upper", screw, color, cls)
        placed += 1
    return placed


def dowels(comps: list[dict], upper: str, lower: str, positions: list[tuple], d: float, name: str, color=(0.85, 0.85, 0.5)) -> int:
    """Dowel pins across the interface of two components (upper plate sits on the lower plate)."""
    a, b = find(comps, upper), find(comps, lower)
    if a is None or b is None:
        return 0
    ba, bb = a["shape"].BoundingBox(), b["shape"].BoundingBox()
    z_if = (ba.zmin + bb.zmax) / 2
    half = 1.5 * d
    n = 0
    for (x, y) in positions:
        if not (ba.xmin < x < ba.xmax and ba.ymin < y < ba.ymax and bb.xmin < x < bb.xmax and bb.ymin < y < bb.ymax):
            continue
        pin = cyl(d / 2, 2 * half, x, y, z_if - half)
        cut(a, pin)
        cut(b, pin)
        add(comps, name, a["group"], pin, color, "dowel")
        n += 1
    return n


# ------------------------------------------------------------ mould: pins, cooling, screws, dowels

def _part_vertices(placed: cq.Shape) -> np.ndarray:
    v, _ = placed.tessellate(0.5, 0.3)
    return np.array([[p.x, p.y, p.z] for p in v]) if v else np.zeros((0, 3))


def _lowest_hit(placed: cq.Shape, x: float, y: float, z_from: float) -> float | None:
    """Z of the lowest point of the part on the vertical line (x, y), or None when the line misses it."""
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    hit = IntCurvesFace_ShapeIntersector()
    hit.Load(placed.wrapped, 1e-6)
    hit.Perform(gp_Lin(gp_Pnt(x, y, z_from), gp_Dir(0, 0, 1)), 0.0, 1e6)
    if hit.NbPnt() == 0:
        return None
    return min(hit.Pnt(i + 1).Z() for i in range(hit.NbPnt()))


def ejector_pins(comps: list[dict], ctx: dict, v: dict) -> int:
    ins, eplate, support = find(comps, "B side insert"), find(comps, "Ejector plate"), find(comps, "Support plate")
    placed = ctx.get("placed")
    if ins is None or eplate is None or placed is None:
        return 0
    pd, hd, ht = v["ejector_pin_dia_mm"], v["ejector_head_dia_mm"], v["ejector_head_t_mm"]
    want = int(v["ejector_pins"])
    bb = ins["shape"].BoundingBox()
    pb = placed.BoundingBox()
    step = max(2.5 * pd, (pb.xlen + pb.ylen) / 30)
    cand = []
    for x in np.arange(pb.xmin + pd, pb.xmax - pd, step):
        for y in np.arange(pb.ymin + pd, pb.ymax - pd, step):
            z0 = _lowest_hit(placed, float(x), float(y), bb.zmin - 1)
            if z0 is None or z0 < bb.zmin + 3 or z0 > bb.zmax:
                continue
            ring = [(x + pd / 2 * math.cos(a), y + pd / 2 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 5)[:-1]]
            zs = np.linspace(z0 - 1.5, bb.zmin + 1.5, 6)
            if all(_inside(ins["shape"], px, py, float(z)) for px, py in ring + [(x, y)] for z in zs):
                cand.append((float(x), float(y), z0))
    if not cand:
        return 0
    idx = farthest(np.array([(c[0], c[1]) for c in cand]), want)
    eb = eplate["shape"].BoundingBox()
    z_e1 = eb.zmax
    n = 0
    for i in idx:
        x, y, z0 = cand[i]
        if not (eb.xmin + hd < x < eb.xmax - hd and eb.ymin + hd < y < eb.ymax - hd):
            continue
        shaft = cyl(pd / 2, z0 - z_e1, x, y, z_e1)
        head = cyl(hd / 2, ht, x, y, z_e1 - ht)
        pin = shaft.fuse(head)
        cut(ins, cyl(pd / 2, z0 - bb.zmin + 1, x, y, bb.zmin - 1))
        if support is not None:
            sb = support["shape"].BoundingBox()
            cut(support, cyl((pd + 1) / 2, sb.zlen + 2, x, y, sb.zmin - 1))
        cut(eplate, cyl((hd + 1) / 2, ht, x, y, z_e1 - ht))
        add(comps, "Ejector pin", "lower", pin, (0.78, 0.30, 0.30), "ejector_pin")
        n += 1
    return n


def return_pins(comps: list[dict], ctx: dict, v: dict) -> int:
    eplate, support, bplate = find(comps, "Ejector plate"), find(comps, "Support plate"), find(comps, "B plate (core plate)")
    if eplate is None or support is None or bplate is None:
        return 0
    rd = v["return_pin_dia_mm"]
    eb = eplate["shape"].BoundingBox()
    pl, pw = ctx["pocket_l"], ctx["pocket_w"]
    y_band = (pw / 2 + rd / 2 + 3, eb.ymax - rd / 2 - 3)
    if y_band[1] <= y_band[0]:
        return 0
    x = min(0.25 * ctx["L"], eb.xmax - rd - 3)
    y = (y_band[0] + y_band[1]) / 2
    z_e1 = eb.zmax
    z_top = 0.0
    n = 0
    ctx["return_xy"] = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            if n >= int(v["return_pins"]):
                break
            px, py = sx * x, sy * y
            pin = cyl(rd / 2, z_top - z_e1, px, py, z_e1)
            sb, bb_ = support["shape"].BoundingBox(), bplate["shape"].BoundingBox()
            cut(support, cyl((rd + 1) / 2, sb.zlen + 2, px, py, sb.zmin - 1))
            cut(bplate, cyl(rd / 2, bb_.zlen + 1, px, py, bb_.zmin))
            cut(eplate, cyl(rd / 2, 8, px, py, z_e1 - 8))
            add(comps, "Return pin", "lower", pin, (0.78, 0.45, 0.30), "return_pin")
            ctx["return_xy"].append((px, py, rd))
            n += 1
    return n


def cooling(comps: list[dict], ctx: dict, v: dict, side: str) -> dict:
    """Straight drilled channels through the insert and its plate, in the steel under / behind the forming surface."""
    iname, pname = (("B side insert", "B plate (core plate)") if side == "B" else ("A side insert", "A plate (cavity plate)"))
    ins, plate = find(comps, iname), find(comps, pname)
    placed = ctx.get("placed")
    if ins is None or plate is None or placed is None:
        return {"channels": 0, "connectors": 0, "wanted": 0}
    d, wall, want = v["cool_dia_mm"], v["cool_min_wall_mm"], int(v["cool_channels"])
    r = d / 2
    bb = ins["shape"].BoundingBox()
    ax = 0 if bb.xlen >= bb.ylen else 1                    # channels run along the longer side
    length = bb.xlen if ax == 0 else bb.ylen
    lo, hi = (bb.xmin, bb.xmax) if ax == 0 else (bb.ymin, bb.ymax)
    lat_lo, lat_hi = (bb.ymin, bb.ymax) if ax == 0 else (bb.xmin, bb.xmax)
    verts = _part_vertices(placed)
    keep_out = [(c[0], c[1], ctx["bush_od"] / 2 + wall) for c in ctx["pil_xy"]]
    cands = []
    stations = np.linspace(lo + 1, hi - 1, 6)
    for lat in np.arange(lat_lo + r + wall, lat_hi - r - wall + 1e-6, d):
        for z in np.arange(bb.zmin + r + wall, bb.zmax - r - wall + 1e-6, d):
            pbox = plate["shape"].BoundingBox()
            if pbox.zmin < z < pbox.zmax and any(abs(lat - (c[1] if ax == 0 else c[0])) < c[2] + r for c in keep_out):
                continue
            pts = []
            for s in stations:
                for a in np.linspace(0, 2 * math.pi, 9)[:-1]:
                    off = (r + wall) * math.cos(a), (r + wall) * math.sin(a)
                    pts.append((s, lat + off[0], z + off[1]) if ax == 0 else (lat + off[0], s, z + off[1]))
                pts.append((s, lat, z) if ax == 0 else (lat, s, z))
            if all(_inside(ins["shape"], *p) for p in pts):
                centre = np.array([(lo + hi) / 2, lat, z] if ax == 0 else [lat, (lo + hi) / 2, z])
                dist = float(np.sqrt(((verts - centre) ** 2).sum(1)).min()) if len(verts) else 0.0
                cands.append((abs(dist - 2.5 * d), lat, z, dist))
    cands.sort()
    chosen = []
    for score, lat, z, dist in cands:
        if all(math.hypot(lat - c[0], z - c[1]) >= 3 * d for c in chosen):
            chosen.append((lat, z))
        if len(chosen) >= want:
            break
    pb = plate["shape"].BoundingBox()
    p_lo, p_hi = (pb.xmin, pb.xmax) if ax == 0 else (pb.ymin, pb.ymax)
    conn = 0
    for lat, z in chosen:
        axis = (1, 0, 0) if ax == 0 else (0, 1, 0)
        origin = (p_lo - 1, lat, z) if ax == 0 else (lat, p_lo - 1, z)
        bore = cq.Solid.makeCylinder(r, (p_hi - p_lo) + 2, cq.Vector(*origin), cq.Vector(*axis))
        cut(ins, bore)
        cut(plate, bore)
        for end, sgn in ((p_lo, -1), (p_hi, 1)):
            base = (end if sgn > 0 else end - v["connector_len_mm"], lat, z) if ax == 0 else (lat, end if sgn > 0 else end - v["connector_len_mm"], z)
            fit = cq.Solid.makeCylinder(r + 4, v["connector_len_mm"], cq.Vector(*base), cq.Vector(*axis))
            fit = fit.cut(cq.Solid.makeCylinder(r, v["connector_len_mm"] + 2, cq.Vector(*(base[0] - (1 if ax == 0 else 0), base[1] - (0 if ax == 0 else 1), base[2])), cq.Vector(*axis)))
            add(comps, "Cooling connector", plate["group"], fit, (0.35, 0.55, 0.85), "cooling_connector")
            conn += 1
    return {"channels": len(chosen), "connectors": conn, "dia": d, "axis": "xy"[ax], "wanted": want}


def mould_details(comps: list[dict], ctx: dict, v: dict) -> dict:
    """Pins, cooling channels, screws and dowels of a mould. Returns what was placed, for the bill of materials and the notes."""
    out, notes = {}, []
    sp_ = special(comps, ctx, v)
    out.update(sp_["counts"])
    notes += sp_["notes"]
    out["ejector_pins"] = ejector_pins(comps, ctx, v)
    if find(comps, "Ejector plate") is not None and out["ejector_pins"] < int(v["ejector_pins"]):
        notes.append(f"{out['ejector_pins']} of {int(v['ejector_pins'])} ejector pins fit under the part: the rest go on the ribs and bosses the toolmaker chooses.")
    out["return_pins"] = return_pins(comps, ctx, v)
    cb, ca = cooling(comps, ctx, v, "B"), cooling(comps, ctx, v, "A")
    out["cooling_channels"], out["cooling_connectors"] = cb["channels"] + ca["channels"], cb["connectors"] + ca["connectors"]
    if cb["channels"] < cb["wanted"] or ca["channels"] < ca["wanted"]:
        notes.append(f"Cooling channels placed: B side {cb['channels']}, A side {ca['channels']} (wanted {cb['wanted']} each): the rest need baffles, bubblers or conformal cooling.")
    sd, dd = v["screw_dia_mm"], v["dowel_dia_mm"]
    L, W = ctx["L"], ctx["W"]
    bush_r = ctx["bush_od"] / 2 + sd
    circles = [(c[0], c[1], bush_r) for c in ctx["pil_xy"]]
    pocket = (-ctx["pocket_l"] / 2 - sd, -ctx["pocket_w"] / 2 - sd, ctx["pocket_l"] / 2 + sd, ctx["pocket_w"] / 2 + sd)
    inset = 1.5 * sd + 6
    ps = ring_positions(L, W, inset, int(v["screws_a"]), circles, [pocket])
    a_chain = ["Top clamp plate"] + (["Manifold plate"] if find(comps, "Manifold plate") else []) + ["A plate (cavity plate)"]
    out["screws"] = fasten(comps, a_chain, ps, sd, True, f"Screw M{sd:g} (A side)")
    sp = []
    # B side: from under the bottom clamp plate up through the spacer blocks and the support plate into the B plate
    spacers_x = [find(comps, n)["shape"].BoundingBox() for n in ("Spacer block 1", "Spacer block 2") if find(comps, n)]
    for bx in spacers_x:
        xc = (bx.xmin + bx.xmax) / 2
        ys = np.linspace(-W / 2 + inset + 10, W / 2 - inset - 10, 5)
        okys = [float(y) for y in ys if all(math.hypot(xc - c[0], y - c[1]) > bush_r + 4 for c in circles) and not (abs(xc) < ctx["pocket_l"] / 2 + sd and abs(y) < ctx["pocket_w"] / 2 + sd)]
        for y in okys[::max(1, len(okys) // max(1, int(v["screws_b"]) // 2))][:max(1, int(v["screws_b"]) // 2)]:
            sp.append((xc, y))
    # the spacer block is the 2nd link of the chain: one chain per spacer
    for spacer in ("Spacer block 1", "Spacer block 2"):
        sb = find(comps, spacer)
        if sb is None:
            continue
        bx = sb["shape"].BoundingBox()
        pos = [p for p in sp if bx.xmin < p[0] < bx.xmax]
        out["screws"] += fasten(comps, ["Bottom clamp plate", spacer, "Support plate", "B plate (core plate)"], pos, sd, False, f"Screw M{sd:g} (B side)")
    if find(comps, "Top clamp plate") is not None and out["screws"] < int(v["screws_a"]) + int(v["screws_b"]):
        notes.append(f"{out['screws']} of {int(v['screws_a']) + int(v['screws_b'])} cap screws placed: the plate frame is too narrow for the rest, use a larger base.")
    k = int(v["dowels_per_interface"])
    rp = [(x, y, r + dd) for x, y, r in ctx.get("return_xy", [])]
    dpos_a = ring_positions(L, W, inset + 2 * sd, k, circles + [(p[0], p[1], 2.5 * sd) for p in ps], [pocket])
    dpos_b = ring_positions(L, W, inset + 2 * sd, k, circles + rp + [(p[0], p[1], 2.5 * sd) for p in sp], [pocket])
    out["dowels"] = dowels(comps, a_chain[-2], "A plate (cavity plate)", dpos_a, dd, f"Dowel pin Ø{dd:g} (A side)")
    out["dowels"] += dowels(comps, "B plate (core plate)", "Support plate", dpos_b, dd, f"Dowel pin Ø{dd:g} (B side)")
    return {"counts": out, "notes": notes, "cooling": {"B": cb, "A": ca}}


# ------------------------------------------------------------ mould: hot runner, slides, lifters

def _bar(x0, y0, x1, y1, w, z0, h):
    lo_x, hi_x = min(x0, x1) - w / 2, max(x0, x1) + w / 2
    lo_y, hi_y = min(y0, y1) - w / 2, max(y0, y1) + w / 2
    return cq.Workplane("XY").box(hi_x - lo_x, hi_y - lo_y, h, centered=False).translate((lo_x, lo_y, z0)).val()


def hot_runner(comps: list[dict], ctx: dict, v: dict) -> dict:
    """Manifold plate, manifold bar, nozzle drops down to a gate on the part at each cavity centre, inlet bushing."""
    clamp_pl, ring, a_ins, aplate = find(comps, "Top clamp plate"), find(comps, "Locating ring"), find(comps, "A side insert"), find(comps, "A plate (cavity plate)")
    placed = ctx.get("placed")
    if clamp_pl is None or a_ins is None or aplate is None or placed is None:
        return {"nozzles": 0}
    a, mp = ctx["a"], v["manifold_plate_t_mm"]
    nd, mw = v["hr_nozzle_dia_mm"], v["hr_manifold_w_mm"]
    L, W = ctx["L"], ctx["W"]
    # shift the clamp plate and locating ring up by the manifold plate
    for c in (clamp_pl, ring):
        if c is not None:
            c["shape"] = c["shape"].translate(cq.Vector(0, 0, mp))
    drops = []
    pb = placed.BoundingBox()
    for (px, py) in ctx["pos"]:
        hit_top = None
        from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
        from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
        h = IntCurvesFace_ShapeIntersector()
        h.Load(placed.wrapped, 1e-6)
        h.Perform(gp_Lin(gp_Pnt(px, py, pb.zmax + 50), gp_Dir(0, 0, -1)), 0.0, 1e6)
        if h.NbPnt():
            hit_top = max(h.Pnt(i + 1).Z() for i in range(h.NbPnt()))
        else:
            hit_top = (pb.zmin + pb.zmax) / 2
        drops.append((px, py, hit_top))
    z_man0, z_man1 = a + 4, a + mp - 4
    bar = None
    for (x, y, _) in drops:
        seg = _bar(0, 0, x, 0, mw, z_man0, z_man1 - z_man0).fuse(_bar(x, 0, x, y, mw, z_man0, z_man1 - z_man0))
        bar = seg if bar is None else bar.fuse(seg)
    if bar is None:
        return {"nozzles": 0}
    plate = cq.Workplane("XY").box(L, W, mp, centered=(True, True, False)).translate((0, 0, a)).val()
    plate = plate.cut(_bar(0, 0, max(abs(d[0]) for d in drops) * (1 if drops[0][0] >= 0 else -1), 0, mw + 8, a, mp).fuse(
        *[_bar(x, 0, x, y, mw + 8, a, mp) for x, y, _ in drops]))
    add(comps, "Manifold plate", "upper", plate, (0.30, 0.45, 0.80), "manifold_plate", False)
    add(comps, "Hot runner manifold", "upper", bar, (0.85, 0.40, 0.15), "hr_manifold")
    for i, (x, y, zg) in enumerate(drops, start=1):
        noz = cyl(nd / 2, z_man0 - zg, x, y, zg)
        cut(a_ins, cyl(nd / 2, a - zg + 1, x, y, zg))
        add(comps, f"Hot runner nozzle {i}", "upper", noz, (0.85, 0.55, 0.20), "hr_nozzle")
    add(comps, "Hot runner inlet bushing", "upper", cq.Solid.makeCylinder(ctx["sprue_d"] / 2, mp - 8 + ctx["clamp"], cq.Vector(0, 0, z_man1)), (0.8, 0.2, 0.2), "sprue_bush")
    return {"nozzles": len(drops), "manifold_plate_t": mp}


def _lateral_dir(centre, part_centre) -> tuple:
    dx, dy = centre[0] - part_centre[0], centre[1] - part_centre[1]
    if abs(dx) >= abs(dy):
        return (1.0 if dx >= 0 else -1.0, 0.0, 0.0)
    return (0.0, 1.0 if dy >= 0 else -1.0, 0.0)


def slides_and_lifters(comps: list[dict], ctx: dict, v: dict) -> dict:
    """A slide for every undercut void on the outside of the part, a lifter for every one on the inside. The void IS the forming steel:
    the slide / lifter is that void extended along its path (outward / down to the ejector plate); the path is cut out of the inserts and
    plates, an angle pin drives each slide."""
    from . import tool_design
    gaps = ctx.get("gaps") or []
    placed = ctx.get("placed")
    notes, counts = [], {"slides": 0, "lifters": 0, "angle_pins": 0}
    if not gaps or placed is None:
        return {"counts": counts, "notes": notes}
    pb = placed.BoundingBox()
    pc = ((pb.xmin + pb.xmax) / 2, (pb.ymin + pb.ymax) / 2)
    a_pl, b_pl = find(comps, "A plate (cavity plate)"), find(comps, "B plate (core plate)")
    a_ins, b_ins = find(comps, "A side insert"), find(comps, "B side insert")
    support, eplate = find(comps, "Support plate"), find(comps, "Ejector plate")
    wall, guide, extra = v["slide_wall_mm"], v["slide_guide_mm"], v["slide_stroke_extra_mm"]
    ap_d, ap_deg = v["angle_pin_dia_mm"], math.radians(v["angle_pin_deg"])
    L, W = ctx["L"], ctx["W"]
    todo = []
    for g in gaps:
        gb = g.BoundingBox()
        dims = sorted((gb.xlen, gb.ylen, gb.zlen))
        if g.Volume() < v["min_void_mm3"] or dims[0] < v["min_void_thickness_mm"]:
            continue
        todo.append((g, gb))
    counts["unresolved"] = 0
    ignored = len(gaps) - len(todo)
    if ignored:
        notes.append(f"{ignored} small void(s) between the envelopes are slivers (under {v['min_void_mm3']:g} mm³ or {v['min_void_thickness_mm']:g} mm thick): ignored.")
    n_s = n_l = 0
    for g, gb in todo:
        centre = ((gb.xmin + gb.xmax) / 2, (gb.ymin + gb.ymax) / 2, (gb.zmin + gb.zmax) / 2)
        u = _lateral_dir(centre, pc)
        along = lambda b: (b.xmin, b.xmax) if u[0] else (b.ymin, b.ymax)
        g_lo, g_hi = along(gb)
        p_lo, p_hi = along(pb)
        outer = (u[0] + u[1]) > 0
        # a slide needs a free path outward: the void swept along u must not meet the part
        try:
            probe = tool_design.sweep_vec(g, tuple(c * 60.0 for c in u))
            free = probe is None or probe.intersect(placed).Volume() < 1.0
        except Exception:                 # the kernel cannot decide (revolved surfaces): leave the void to the toolmaker
            notes.append(f"Void at ({centre[0]:.0f}, {centre[1]:.0f}) could not be checked for a slide path: the toolmaker decides slide or lifter.")
            counts["unresolved"] += 1
            continue
        if free:
            # slide: moves outward along u
            depth = gb.xlen if u[0] else gb.ylen
            stroke = depth + extra
            plate_edge = (L / 2 if u[0] else W / 2) * (1 if outer else -1)
            start = g_hi if outer else g_lo
            room = abs(plate_edge) - 5 - abs(start) - stroke
            carrier = min(guide + stroke, room)
            if carrier < 20:
                notes.append(f"Slide at ({centre[0]:.0f}, {centre[1]:.0f}) has no room for its stroke ({stroke:.0f} mm) in the base: use a larger base.")
                counts["unresolved"] += 1
                continue
            body = tool_design.sweep_vec(g, tuple(c * carrier for c in u))
            slide = g if body is None else g.fuse(body)
            sb = slide.BoundingBox()
            # steel around: grow the cross-section by the wall (perpendicular to u and in z), keep clear of the part
            blk = cq.Workplane("XY").box(sb.xlen + (0 if u[0] else 2 * wall), sb.ylen + (2 * wall if u[0] else 0), sb.zlen + 2 * wall, centered=False).translate(
                (sb.xmin - (0 if u[0] else wall), sb.ymin - (wall if u[0] else 0), sb.zmin - wall)).val()
            slide = blk.cut(placed)
            n_s += 1
            add(comps, f"Slide {n_s}", "lower", slide, (0.62, 0.30, 0.75), "slide", False)
            for c in (a_pl, b_pl, a_ins, b_ins, support):
                if c is not None:
                    cut(c, slide)
            counts["slides"] += 1
            # angle pin through the slide, inclined so that closing pushes the slide in
            sbb = slide.BoundingBox()
            cx_, cy_, cz_ = (sbb.xmin + sbb.xmax) / 2, (sbb.ymin + sbb.ymax) / 2, (sbb.zmin + sbb.zmax) / 2
            a_top = ctx["a"]
            t_len = (a_top - cz_) / math.cos(ap_deg)
            top = (cx_ + u[0] * math.sin(ap_deg) * t_len, cy_ + u[1] * math.sin(ap_deg) * t_len, a_top)
            d = (-u[0] * math.sin(ap_deg), -u[1] * math.sin(ap_deg), -math.cos(ap_deg))
            plen = t_len + sbb.zlen / 2 / math.cos(ap_deg)
            if abs(top[0]) < L / 2 - ap_d and abs(top[1]) < W / 2 - ap_d and a_pl is not None:
                pin = cq.Solid.makeCylinder(ap_d / 2, plen, cq.Vector(*top), cq.Vector(*d))
                pin = pin.intersect(cq.Workplane("XY").box(4 * L, 4 * W, 2000, centered=(True, True, False)).translate((0, 0, a_top - 2000)).val())
                cut(comps[-1], pin)
                for c in comps:
                    if c["cls"] in ("base_plate", "insert_a", "insert_b", "support_plate") and c["shape"].BoundingBox().zmax > pin.BoundingBox().zmin \
                            and c["shape"].BoundingBox().zmin < pin.BoundingBox().zmax:
                        cut(c, pin)
                add(comps, f"Angle pin {n_s}", "upper", pin, (0.4, 0.42, 0.45), "angle_pin")
                counts["angle_pins"] += 1
            else:
                notes.append(f"Angle pin of slide {n_s} falls outside the A plate: use a steeper pin or a larger base.")
        else:
            # lifter: the void plus a rod down to the ejector plate
            z_e = eplate["shape"].BoundingBox().zmax if eplate is not None else gb.zmin - 40
            drop = gb.zmin - z_e
            body = tool_design.sweep_vec(g, (0, 0, -drop)) if drop > 1 else None
            lifter = (g if body is None else g.fuse(body)).cut(placed)
            n_l += 1
            add(comps, f"Lifter {n_l}", "lower", lifter, (0.75, 0.30, 0.60), "lifter", False)
            for c in (b_ins, support):
                if c is not None:
                    cut(c, lifter)
            counts["lifters"] += 1
    if n_l:
        notes.append("Lifters are straight rods here: set the lifter angle and the foot on the ejector plate when you detail them.")
    return {"counts": counts, "notes": notes}


def special(comps: list[dict], ctx: dict, v: dict) -> dict:
    counts, notes = {}, []
    if ctx.get("hot"):
        hr = hot_runner(comps, ctx, v)
        counts["nozzles"] = hr["nozzles"]
    sl = slides_and_lifters(comps, ctx, v)
    counts.update(sl["counts"])
    notes += sl["notes"]
    return {"counts": counts, "notes": notes}


# ------------------------------------------------------------ sheet-metal die: screws, dowels, springs, stripper bolts

def _plate_rects(shape: cq.Shape, margin: float) -> list[tuple]:
    """Rectangles (x0, y0, x1, y1) of the openings of a plate seen from the top, grown by margin: places where no screw may go."""
    bb = shape.BoundingBox()
    out = []
    for f in shape.Faces():
        if f.geomType() == "PLANE" and f.normalAt().z > 0.999 and abs(f.Center().z - bb.zmax) < 1e-3:
            for w in f.innerWires():
                b = w.BoundingBox()
                out.append((b.xmin - margin, b.ymin - margin, b.xmax + margin, b.ymax + margin))
    return out


def die_details(comps: list[dict], ctx: dict, v: dict) -> dict:
    """Screws, dowels, stripper bolts and springs of a die set; the plates get their holes, the pockets for the springs."""
    notes, out = [], {}
    sd, dd = v["screw_dia_mm"], v["dowel_dia_mm"]
    L, W = ctx["sl"], ctx["sw"]
    pil_c = [(x, y, ctx["bush_od"] / 2 + sd) for x, y in ctx["pillars"]]
    die, lower, upper = find(comps, "Die block"), find(comps, "Lower shoe"), find(comps, "Upper shoe")
    ppl, back, strip = find(comps, "Punch plate"), find(comps, "Backing plate"), find(comps, "Stripper plate")
    if die is None or lower is None or upper is None or ppl is None:
        return {"counts": out, "notes": notes}
    db_ = die["shape"].BoundingBox()
    inset = 1.5 * sd + 6
    rects_d = _plate_rects(die["shape"], sd)
    n_screw = int(v["screws"])
    ps = ring_positions(db_.xlen, db_.ylen, inset, n_screw, pil_c, rects_d, 0, (db_.xmin + db_.xmax) / 2, (db_.ymin + db_.ymax) / 2)
    out["screws"] = fasten(comps, ["Die block", "Lower shoe"], ps, sd, True, f"Screw M{sd:g} (die block)")
    # punch plate stack: the punches and openings of the stripper are no-go areas
    pb = ppl["shape"].BoundingBox()
    punch_rects = []
    for c in comps:
        if c["cls"] == "punch":
            b = c["shape"].BoundingBox()
            punch_rects.append((b.xmin - 2 * sd, b.ymin - 2 * sd, b.xmax + 2 * sd, b.ymax + 2 * sd))
    if strip is not None:
        punch_rects += _plate_rects(strip["shape"], sd)
    chain = ["Upper shoe"] + (["Backing plate"] if back is not None else []) + ["Punch plate"]
    pu = ring_positions(pb.xlen, pb.ylen, inset, n_screw, pil_c, punch_rects, 0, (pb.xmin + pb.xmax) / 2, (pb.ymin + pb.ymax) / 2)
    out["screws"] += fasten(comps, chain, pu, sd, True, f"Screw M{sd:g} (punch plate)")
    used = [(x, y, 2.5 * sd) for x, y in ps + pu]
    # stripper bolts: through the upper stack into the stripper plate
    nb = int(v["stripper_bolts"])
    out["stripper_bolts"] = 0
    if strip is not None and nb:
        bolts = ring_positions(pb.xlen, pb.ylen, inset + 2 * sd, nb, pil_c + used, punch_rects, 0, (pb.xmin + pb.xmax) / 2, (pb.ymin + pb.ymax) / 2)
        out["stripper_bolts"] = fasten(comps, chain + ["Stripper plate"], bolts, sd, True, f"Stripper bolt M{sd:g}", "stripper_bolt")
        used += [(x, y, 2.5 * sd) for x, y in bolts]
    # stripper springs: pockets in the punch plate, springs compressed in them
    od, depth = v["spring_od_mm"], v["spring_pocket_mm"]
    n_spring = int(v["springs"])
    out["springs"] = 0
    if strip is not None and n_spring:
        pos = ring_positions(pb.xlen, pb.ylen, [od / 2 + 4, od * 1.5 + 8], n_spring * 3, pil_c + used, punch_rects, 0, (pb.xmin + pb.xmax) / 2, (pb.ymin + pb.ymax) / 2)
        pos = _spread(pos, n_spring, od * 1.1)
        depth = min(depth, 0.7 * pb.zlen)
        z0 = pb.zmin
        for (x, y) in pos:
            cut(ppl, cyl((od + 2) / 2, depth, x, y, z0))
            add(comps, "Stripper spring", "upper", cyl(od / 2, depth, x, y, z0), (0.2, 0.55, 0.3), "spring")
            used.append((x, y, od / 2 + dd + 2))
            out["springs"] += 1
        if out["springs"] < n_spring:
            notes.append(f"{out['springs']} of {n_spring} stripper springs fit in the punch plate: use stronger springs (Stage tool rules → spring_rating_kgf) or a larger die set.")
    k = int(v["dowels"] // 2) or 2
    rp = [(x, y, max(r, 2.5 * dd)) for x, y, r in used]
    out["dowels"] = dowels(comps, "Die block", "Lower shoe", ring_positions(db_.xlen, db_.ylen, inset + 2 * sd, k, pil_c + rp, rects_d, 0,
                                                                             (db_.xmin + db_.xmax) / 2, (db_.ymin + db_.ymax) / 2), dd, f"Dowel pin Ø{dd:g} (die block)")
    if back is not None:
        out["dowels"] += dowels(comps, "Backing plate", "Punch plate", ring_positions(pb.xlen, pb.ylen, inset + 2 * sd, k, pil_c + rp, punch_rects, 0,
                                                                                       (pb.xmin + pb.xmax) / 2, (pb.ymin + pb.ymax) / 2), dd, f"Dowel pin Ø{dd:g} (punch plate)")
    if out["screws"] < 2 * n_screw:
        notes.append(f"{out['screws']} of {2 * n_screw} cap screws placed: the plates are too crowded for the rest.")
    return {"counts": out, "notes": notes}


def _spread(points: list[tuple], n: int, min_gap: float) -> list[tuple]:
    """n of the points, none closer to another than min_gap, picked evenly."""
    if not points:
        return []
    arr = np.array(points)
    order = farthest(arr, min(len(points), n * 2))
    chosen = []
    for i in order:
        p = points[i]
        if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= min_gap for q in chosen):
            chosen.append(p)
        if len(chosen) >= n:
            break
    return chosen
