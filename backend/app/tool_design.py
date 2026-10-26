"""Detailed 3D tool design (roadmap stage 27): every die stage as an assembly with every part modelled.

    inputs      the flat pattern of the part (unfold.py: real outline, holes, bend lines), the die of the stage from the
                tool cost (die set, die plate size, force, press, BOM lines with grade / make / standard part), the
                Design rules and Sizing rules of Mould & die database (clearances, fits, plate, pillar, screw sizes)
    blanking    die plate with the blank outline as the opening (die = part size), punch = outline − clearance,
                stock guides for the strip, fixed stripper, backing plates, punch holder, shoes, pillars, bushes
    piercing    die plate with every hole + clearance, a punch per hole (round holes: standard punches with a head),
                nest plate locating the blank, fixed stripper
    bending     V-die block (opening, angle with overbend) and punch blade with the part's inside radius, gauge pins
    progressive one die plate with the piercing and blanking stations at the strip pitch (forming stations: to be
                added by the die designer, listed in the notes)
    every part  a solid with its local origin at its lower-left-bottom corner (the datum of its detail drawing),
                its holes (kind, size, fit) for the hole table, material and hardness, quantity and positions

The result is a first-cut design made by rules for the die designer to check and complete; every number comes
from master data, nothing is fixed here.
"""

from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass, field

import cadquery as cq
from shapely.geometry import Polygon

COLORS = {"shoe": (0.55, 0.6, 0.66), "plate": (0.35, 0.55, 0.8), "hard": (0.85, 0.45, 0.2), "std": (0.85, 0.75, 0.2),
          "ref": (0.2, 0.75, 0.35), "screw": (0.25, 0.25, 0.25)}


class DesignError(ValueError):
    pass


@dataclass
class Comp:
    name: str
    shape: cq.Shape
    locs: list
    kind: str = "made"                 # made | std | ref (workpiece, not in the BOM)
    material: str = ""
    hardness: str = ""
    make: str = ""
    std: str = ""                      # standard part description / catalogue number
    notes: list = field(default_factory=list)
    holes: list = field(default_factory=list)      # {x, y, d, kind, label, depth}
    openings: list = field(default_factory=list)   # {pts, label, tol}
    size: tuple = (0, 0, 0)
    color: str = "plate"
    drawing: str = "plate"             # plate | solid | none
    no: str = ""

    @property
    def qty(self) -> int:
        return len(self.locs)


# ---------- geometry helpers ----------

def _box(L, W, H):
    return cq.Workplane("XY").box(L, W, H, centered=False)


def _circle_of(pts):
    """(cx, cy, r) when a closed polyline is a circle (within 1 %), else None."""
    p = Polygon(pts)
    if p.area <= 0 or len(pts) < 12:        # a rectangle's corners are also all at one distance from its centre
        return None
    c = p.centroid
    rs = [math.hypot(x - c.x, y - c.y) for x, y in pts]
    r = sum(rs) / len(rs)
    return (c.x, c.y, r) if r > 0 and max(abs(x - r) for x in rs) < 0.01 * r + 0.01 else None


def _prism(pts, z0, h):
    circ = _circle_of(pts)
    if circ:
        cx, cy, r = circ
        return cq.Workplane("XY").workplane(offset=z0).center(cx, cy).circle(r).extrude(h)
    q = [tuple(map(float, p)) for p in pts]
    if q[0] == q[-1]:
        q = q[:-1]
    return cq.Workplane("XY").workplane(offset=z0).polyline(q).close().extrude(h)


def _offset(pts, d):
    """Polygon grown (d > 0) or shrunk (d < 0) by d with sharp corners kept."""
    p = Polygon(pts).buffer(d, join_style=2, mitre_limit=5)
    if p.geom_type != "Polygon":
        p = max(p.geoms, key=lambda g: g.area)
    return [list(c) for c in p.exterior.coords]


def _move(pts, dx, dy):
    return [[x + dx, y + dy] for x, y in pts]


class Plate:
    """A plate with its holes and openings, origin at its lower-left-bottom corner. Holes and openings are collected and
    cut in one go (one boolean for all of them: fast on large plates with many holes)."""

    def __init__(self, L, W, H):
        self.L, self.W, self.H = L, W, H
        self._wp = _box(L, W, H)
        self._pending = []
        self.holes, self.openings = [], []

    @property
    def wp(self):
        if self._pending:
            tools = [t.val() if hasattr(t, "val") else t for t in self._pending]
            self._wp = cq.Workplane("XY").newObject([self._wp.val().cut(*tools)])     # one boolean, tools may overlap
            self._pending = []
        return self._wp

    @wp.setter
    def wp(self, value):
        self._pending = []
        self._wp = value

    def _cut(self, tool):
        self._pending.append(tool)

    def hole(self, x, y, d, kind="thru", label="", depth=None, from_top=True, cb_d=None, cb_h=None):
        h = depth or self.H
        z0 = self.H - h if from_top else 0
        self._cut(cq.Workplane("XY").workplane(offset=z0 - 0.01).center(x, y).circle(d / 2).extrude(h + 0.02))
        if cb_d:
            z1 = self.H - cb_h if from_top else 0
            self._cut(cq.Workplane("XY").workplane(offset=z1 - 0.01).center(x, y).circle(cb_d / 2).extrude(cb_h + 0.02))
            label = f"{label}: Ø{d:g} thru, counterbore Ø{cb_d:g} × {cb_h:g}" + ("" if from_top else " from below")
        self.holes.append({"x": round(x, 3), "y": round(y, 3), "d": round(d, 3), "kind": kind, "label": label,
                           "depth": None if depth is None else round(depth, 2), "top": from_top, "cb_d": cb_d, "cb_h": cb_h})

    def opening(self, pts, label, tol=""):
        self._cut(_prism(pts, -0.01, self.H + 0.02))
        self.openings.append({"pts": [[round(x, 3), round(y, 3)] for x, y in pts], "label": label, "tol": tol})

    def comp(self, name, locs, **k) -> Comp:
        return Comp(name, self.wp.val(), locs, holes=self.holes, openings=self.openings, size=(self.L, self.W, self.H), **k)


# ---------- rules ----------

class Rules:
    def __init__(self, part_type: str):
        from . import mould_db
        self.design = mould_db.design_rules(part_type)
        self.sizing = mould_db.sizing_rules(part_type)
        self.steels = {r["code"]: r for r in mould_db.tables()["tool_materials"]}
        self.is_example = any(r["is_example"] for r in self.design.values())

    def __call__(self, name, default=None):
        r = self.design.get(name) or self.sizing.get(name)
        if r is None or r.get("value") in (None, ""):
            if default is None:
                raise DesignError(f"Mould & die database → Design rules has no '{name}'.")
            return default
        return float(r["value"])

    def text(self, name, default=""):
        r = self.design.get(name)
        return (r or {}).get("text") or default

    def hardness(self, grade):
        return (self.steels.get(grade) or {}).get("hardness") or ""


def _forming_station(dp, hp, fp, t, rules, lines, x_st, DL, DW, z_die, DH, z_holder, holder_h, die_mat):
    """V-forming insert (pocketed in the die plate, flush with its top) and forming punch (in the punch holder) for the first
    bend of the part, at station x_st of a progressive die."""
    b = fp["bends"][0]
    (x1, y1), (x2, y2) = b["line"]
    blen = math.hypot(x2 - x1, y2 - y1)
    horiz = abs(x2 - x1) > abs(y2 - y1)
    v_open = rules("v_die_open_factor") * t
    inc = math.radians(180 - b["angle_deg"] - rules("overbend_deg"))
    depth_v = (v_open / 2) / math.tan(inc / 2)
    vw = v_open * rules("v_die_w_factor")
    il, iw = (blen + 10, vw) if horiz else (vw, blen + 10)
    ih = DH
    cx = (x1 + x2) / 2 - fp["length_mm"] / 2 + x_st
    cy = (y1 + y2) / 2 - fp["width_mm"] / 2
    blk = cq.Workplane("XY").box(il, iw, ih, centered=False)
    if horiz:
        prof = cq.Workplane("YZ").polyline([(iw / 2 - v_open / 2, ih + 0.01), (iw / 2, ih - depth_v), (iw / 2 + v_open / 2, ih + 0.01)]).close().extrude(il)
    else:
        prof = cq.Workplane("XZ").polyline([(il / 2 - v_open / 2, ih + 0.01), (il / 2, ih - depth_v), (il / 2 + v_open / 2, ih + 0.01)]).close().extrude(-iw)
    blk = blk.cut(prof)
    pocket = [[cx - il / 2 + DL / 2, cy - iw / 2 + DW / 2], [cx + il / 2 + DL / 2, cy - iw / 2 + DW / 2],
              [cx + il / 2 + DL / 2, cy + iw / 2 + DW / 2], [cx - il / 2 + DL / 2, cy + iw / 2 + DW / 2],
              [cx - il / 2 + DL / 2, cy - iw / 2 + DW / 2]]
    dp.opening(pocket, "Pocket for the forming insert", rules.text("fit_insert", "H7"))
    vm, vh = _mat(rules, _line(lines, "Bending die", "Die plate"), die_mat)
    out = [Comp("Forming insert (V)", blk.val(), [(cx - il / 2, cy - iw / 2, z_die)], material=vm, hardness=vh, color="hard",
                size=(il, iw, ih), drawing="solid", notes=[f"V opening {v_open:g} mm, included angle {math.degrees(inc):.1f}°",
                                                           rules.text("heat_treat_note")])]
    r_tip = max(b["inner_radius_mm"], 0.2)
    ph = z_holder + holder_h - (z_die + DH - depth_v + t)
    tw = max(2 * ph * math.tan(inc / 2) * 0.5, 2 * r_tip + 4)
    pts = [(-r_tip, 0.0), (-tw / 2, ph), (tw / 2, ph), (r_tip, 0.0)]
    blade = (cq.Workplane("YZ").polyline(pts).close().extrude(blen) if horiz else cq.Workplane("XZ").polyline(pts).close().extrude(-blen))
    loc = (cx - blen / 2, cy, z_die + DH - depth_v + t) if horiz else (cx, cy - blen / 2, z_die + DH - depth_v + t)
    sl = [[cx - blen / 2 + DL / 2, cy - tw / 2 + DW / 2], [cx + blen / 2 + DL / 2, cy - tw / 2 + DW / 2],
          [cx + blen / 2 + DL / 2, cy + tw / 2 + DW / 2], [cx - blen / 2 + DL / 2, cy + tw / 2 + DW / 2],
          [cx - blen / 2 + DL / 2, cy - tw / 2 + DW / 2]] if horiz else \
         [[cx - tw / 2 + DL / 2, cy - blen / 2 + DW / 2], [cx + tw / 2 + DL / 2, cy - blen / 2 + DW / 2],
          [cx + tw / 2 + DL / 2, cy + blen / 2 + DW / 2], [cx - tw / 2 + DL / 2, cy + blen / 2 + DW / 2],
          [cx - tw / 2 + DL / 2, cy - blen / 2 + DW / 2]]
    hp.opening(sl, "Forming punch seat", rules.text("fit_punch"))
    bm, bh = _mat(rules, _line(lines, "Bending punch"), die_mat)
    bb = blade.val().BoundingBox()
    out.append(Comp("Forming punch (V)", blade.val(), [loc], material=bm, hardness=bh, color="hard", size=(bb.xlen, bb.ylen, bb.zlen),
                    drawing="solid", notes=[f"Tip radius R{r_tip:g}", rules.text("heat_treat_note")]))
    return out


def _round_up(x, step):
    return math.ceil(x / step - 1e-9) * step


def _pillar_d(rules, width):
    return _round_up(max(rules("pillar_d_min_mm"), width * rules("pillar_d_width_factor")), rules("pillar_d_step_mm"))


def _line(lines, *names):
    for n in names:
        for l in lines:
            if l["element"].lower().startswith(n.lower()):
                return l
    return {}


def _mat(rules, line, fallback=""):
    g = line.get("grade") or fallback
    return g, rules.hardness(g)


def _screw_len(grip, d):
    return _round_up(grip + 1.5 * d, 5)


# ---------- the die of one stage ----------

def die_design(part: dict, fp: dict, t: float, die: dict, lines: list, strip: dict | None = None) -> dict:
    """3D design of one die stage: {components, name, notes, stack, rules_are_examples}."""
    rules = Rules("sheet_metal")
    ops = set(die["ops"])
    base = die["base"]
    SL, SW = float(base["length_mm"]), float(base["width_mm"])
    if die.get("base_turned"):
        SL, SW = SW, SL
    shoe_h = float(base.get("clamp_plates_mm") or rules("die_plate_min_mm"))
    DL, DW, DH = (float(die["die_plate"][k]) for k in ("die_l", "die_w", "die_h"))
    c = rules("cut_clearance_pct") / 100 * t
    pd = _pillar_d(rules, SW)
    pe = rules("pillar_edge_factor") * pd
    sd, se, dd = rules("screw_d_mm"), rules("screw_edge_mm"), rules("dowel_d_mm")
    back_h, holder_h, strip_h = rules("backing_h_mm"), rules("punch_plate_h_mm"), rules("stripper_h_mm")
    pback_h = rules("punch_backing_h_mm")
    guide_h = max(6.0, rules("stock_guide_h_factor") * t)
    entry = rules("punch_entry_mm")
    gap = rules("nest_gap_mm")
    tol = {k: rules.text(k) for k in ("plate_thk_tol", "plate_flatness", "plate_parallelism", "position_tol", "fit_pillar",
                                      "fit_bush", "fit_dowel", "fit_punch", "punch_tol", "die_opening_tol", "finish_working",
                                      "finish_general", "heat_treat_note")}
    plate_notes = [f"Thickness {tol['plate_thk_tol']} mm", f"Flatness {tol['plate_flatness']}, parallelism {tol['plate_parallelism']}",
                   f"Ground faces {tol['finish_general']}"]
    hard_notes = [tol["heat_treat_note"], f"Working faces {tol['finish_working']}"]
    comps: list[Comp] = []
    notes = []
    # flat pattern placed with its centre at the die centre
    ox, oy = -fp["length_mm"] / 2, -fp["width_mm"] / 2
    outline = _move(fp["outline"], ox, oy)
    holes = [_move(h, ox, oy) for h in fp["holes"]]
    bending = bool(ops & {"bend"}) and not ops & {"blank", "pierce", "trim"}
    if ops & {"draw"}:
        notes.append("Drawing operation: punch, die ring and blank holder are sized in the tool cost only - model them from the part.")

    # ----- die set: shoes, pillars, bushes -----
    pillars = [(-SL / 2 + pe, -SW / 2 + pe), (SL / 2 - pe, -SW / 2 + pe), (-SL / 2 + pe, SW / 2 - pe), (SL / 2 - pe, SW / 2 - pe)]
    px_, py_ = pillars[3]
    if px_ - pd / 2 < DL / 2 and py_ - pd / 2 < DW / 2:
        notes.append("Die plate runs into the guide pillars: choose a bigger die set.")
    bush_od, bush_len = rules("bush_od_factor") * pd, rules("bush_len_factor") * pd
    die_mat, die_hard = _mat(rules, _line(lines, "Die plate", "Bending die"), "")
    base_mat = base.get("material") or ""

    # stack heights (closed position, bottom of stroke)
    z_bshoe = 0.0
    if bending:
        v_open = rules("v_die_open_factor") * t
        v_h = rules("v_die_h_mm")
        z_die = shoe_h
        die_top = z_die + v_h
    else:
        z_back = shoe_h
        z_die = z_back + back_h
        die_top = z_die + DH
    # ----- lower half -----
    bshoe = Plate(SL, SW, shoe_h)
    for (x, y) in pillars:
        bshoe.hole(x + SL / 2, y + SW / 2, pd, "fit", f"Ø{pd:g} {rules.text('fit_bush', 'H7')} pillar seat")
    lower_screws = []
    if not bending:
        # die plate + backing screwed and doweled to the bottom shoe
        dp = Plate(DL, DW, DH)
        bp = Plate(DL, DW, back_h)
        corners = [(se, se), (DL - se, se), (se, DW - se), (DL - se, DW - se)]
        dowels = [(se, DW / 2), (DL - se, DW / 2)]
        for (x, y) in corners:
            dp.hole(x, y, sd + 1, "cbore", f"M{sd:g}", cb_d=1.6 * sd + 1, cb_h=sd + 1)
            bp.hole(x, y, sd + 1, "thru", f"Ø{sd + 1:g} screw clearance")
            bshoe.hole(x - DL / 2 + SL / 2, y - DW / 2 + SW / 2, sd * 0.85, "tap", f"M{sd:g} tapped", depth=2 * sd)
            lower_screws.append((x - DL / 2, y - DW / 2))
        for (x, y) in dowels:
            for p in (dp, bp):
                p.hole(x, y, dd, "fit", f"Ø{dd:g} {tol['fit_dowel']} dowel")
            bshoe.hole(x - DL / 2 + SL / 2, y - DW / 2 + SW / 2, dd, "fit", f"Ø{dd:g} {tol['fit_dowel']} dowel", depth=1.5 * dd)
        # stripper (fixed) screws into the die plate: tapped holes in the die plate between the corner screws
        sx = [(DL / 2, se), (DL / 2, DW - se)]
        for (x, y) in sx:
            dp.hole(x, y, sd * 0.85, "tap", f"M{sd:g} tapped (stripper)", depth=2 * sd)
        relief = rules("slug_relief_mm")
        cut_open, punch_pts = [], []
        # stations: one (multi-stage) or along the strip at the pitch (progressive: piercing first, cut-off last)
        if die.get("progressive"):
            n_st = max(int(die.get("stations") or 1), 1)
            pitch = float(die.get("pitch") or fp["length_mm"])
            xs = [-(n_st - 1) * pitch / 2 + i * pitch for i in range(n_st)]
            st_pierce, st_blank = xs[0], xs[-1]
            forming = ops - {"blank", "pierce", "trim"}
            st_form = xs[len(xs) // 2] if len(xs) >= 3 else None
            if forming - {"bend"} or ("bend" in forming and (st_form is None or not fp.get("bends"))):
                notes.append(f"Progressive die: forming stations ({', '.join(sorted(forming))}) need a station between piercing and "
                             "cut-off: the die designer adds them.")
        else:
            st_pierce = st_blank = 0.0
        if ops & {"blank", "trim"}:
            o = _move(outline, st_blank, 0)
            dp.opening(_move(o, DL / 2, DW / 2), "Die opening = blank outline (wire cut)", tol["die_opening_tol"])
            cut_open.append(o)
            punch_pts.append(("blank", _offset(o, -c)))
        if "pierce" in ops:
            for h in holes:
                h = _move(h, st_pierce, 0)
                dp.opening(_move(_offset(h, c), DL / 2, DW / 2), "Piercing die opening = hole + clearance", tol["die_opening_tol"])
                cut_open.append(_offset(h, c))
                punch_pts.append(("pierce", h))
        for o in cut_open:
            bp.opening(_move(_offset(o, relief), DL / 2, DW / 2), "Slug relief")
            bshoe.opening(_move(_offset(o, 2 * relief), SL / 2, SW / 2), "Slug escape")
        comps.append(dp.comp("Die plate", [(-DL / 2, -DW / 2, z_die)], material=die_mat, hardness=die_hard, color="hard",
                             notes=plate_notes + hard_notes + [f"Die opening {tol['die_opening_tol']} mm, land "
                                                               f"{rules('die_land_mm'):g} mm then {rules('die_relief_deg'):g}° relief",
                                                               f"Cutting clearance {c:.3f} mm per side ({rules('cut_clearance_pct'):g} % of t)"]))
        g, hd = _mat(rules, _line(lines, "Backing plate"), die_mat)
        comps.append(bp.comp("Backing plate (die)", [(-DL / 2, -DW / 2, z_back)], material=g, hardness=hd, color="hard",
                             notes=plate_notes + [tol["heat_treat_note"]]))
        # strip / blank location
        guide_line = _line(lines, "Stock guides")
        gm, gh = _mat(rules, guide_line, base_mat)
        if ops & {"blank", "trim"}:
            edge = (strip or {}).get("edge_mm") or max(2.0, 1.5 * t)
            sw = float(die.get("strip_w")) if die.get("progressive") and die.get("strip_w") else fp["width_mm"] + 2 * edge
            gw = min(rules("stock_guide_w_mm"), max(5.0, (DW - sw) / 2 - gap))
            gp = Plate(DL, gw, guide_h)
            for x in (se, DL - se):
                gp.hole(x, gw / 2, sd + 1, "thru", f"Ø{sd + 1:g} screw clearance")
            comps.append(gp.comp("Stock guide", [(-DL / 2, sw / 2 + gap, die_top), (-DL / 2, -(sw / 2 + gap) - gw, die_top)],
                                 material=gm, hardness=gh, color="plate",
                                 notes=plate_notes + [f"Strip width {sw:.2f} mm + {gap:g} mm gap per side"]))
            loc_note = f"strip {sw:.1f} mm wide between the stock guides"
            # stop pin: the web of the strip comes against it after each stroke (sets the pitch)
            spd = rules("gauge_pin_d_mm")
            bridge = (strip or {}).get("bridge_mm") or max(1.5, 1.2 * t)
            xs_ = max(q[0] for q in outline) + (st_blank if die.get("progressive") else 0) + bridge + spd / 2
            if xs_ + spd / 2 < DL / 2 - 2:
                dp.hole(xs_ + DL / 2, DW / 2, spd, "fit", f"Ø{spd:g} {tol['fit_dowel']} stop pin", depth=1.5 * spd)
                comps.append(Comp(f"Stop pin Ø{spd:g}", cq.Workplane("XY").circle(spd / 2).extrude(1.5 * spd + guide_h - 0.5).val(),
                                  [(xs_, 0.0, die_top - 1.5 * spd)], kind="std",
                                  std=f"Stop pin ISO 8734 Ø{spd:g} m6 × {_round_up(1.5 * spd + guide_h - 0.5, 1):g}",
                                  size=(spd, spd, 1.5 * spd + guide_h), color="std", drawing="none",
                                  notes=["The strip web stops against it: sets the pitch"]))
            else:
                notes.append("No room for a stop pin on the die plate: use a finger stop or a pitch notch.")
        else:
            nest = Plate(DL, DW, guide_h)
            nest.opening(_move(_offset(outline, gap), DL / 2, DW / 2), "Nest pocket = blank + gap", f"+{gap:g} per side")
            for (x, y) in sx:
                nest.hole(x, y, sd + 1, "thru", f"Ø{sd + 1:g} screw clearance")
            comps.append(nest.comp("Nest plate", [(-DL / 2, -DW / 2, die_top)], material=gm, hardness=gh, color="plate",
                                   notes=plate_notes))
            loc_note = "blank located in the nest plate"
        # fixed stripper on the guides / nest
        z_str = die_top + guide_h
        st = Plate(DL, DW, strip_h)
        for kind, pts in punch_pts:
            st.opening(_move(_offset(pts, rules("stripper_opening_mm")), DL / 2, DW / 2), "Punch opening + gap")
        for (x, y) in sx:
            st.hole(x, y, sd + 1, "cbore", f"M{sd:g}", cb_d=1.6 * sd + 1, cb_h=sd + 1)
        sm, shd = _mat(rules, _line(lines, "Stripper plate"), base_mat)
        comps.append(st.comp("Stripper plate (fixed)", [(-DL / 2, -DW / 2, z_str)], material=sm, hardness=shd, color="plate",
                             notes=plate_notes + [f"Punch openings + {rules('stripper_opening_mm'):g} mm per side"]))
        # ----- upper half: punch holder, punch backing, top shoe -----
        plen = rules("punch_len_mm")
        need = holder_h + rules("closed_gap_min_mm") + strip_h + guide_h + entry
        if plen < need:
            notes.append(f"Punch length {plen:g} mm (Sizing rules) is short for this stack: made {need:g} mm.")
            plen = need
        z_ptip = die_top - entry
        z_holder = z_ptip + plen - holder_h
        z_pback = z_holder + holder_h
        z_tshoe = z_pback + pback_h
        hp = Plate(DL, DW, holder_h)
        pb = Plate(DL, DW, pback_h)
        ts = Plate(SL, SW, shoe_h)
        punches = []
        ph_extra = rules("punch_head_extra_mm")
        pm, phd = _mat(rules, _line(lines, "Blanking", "Piercing punch"), die_mat)
        for kind, pts in punch_pts:
            circ = _circle_of(pts)
            hp.opening(_move(pts, DL / 2, DW / 2), "Punch seat", tol["fit_punch"])
            if circ and kind == "pierce":
                cx, cy, r = circ
                hd = 2 * r + ph_extra
                hp.hole(cx + DL / 2, cy + DW / 2, 2 * r, "cbore", "punch head", cb_d=hd, cb_h=ph_extra * 1.5)
                punches.append(("round", cx, cy, r))
            else:
                punches.append(("profile", pts, None, None))
        for (x, y) in corners:
            ts.hole(x - DL / 2 + SL / 2, y - DW / 2 + SW / 2, sd + 1, "cbore", f"M{sd:g}", cb_d=1.6 * sd + 1, cb_h=sd + 1)
            pb.hole(x, y, sd + 1, "thru", f"Ø{sd + 1:g} screw clearance")
            hp.hole(x, y, sd * 0.85, "tap", f"M{sd:g} tapped", depth=2 * sd, from_top=True)
        for (x, y) in dowels:
            for p in (hp, pb):
                p.hole(x, y, dd, "fit", f"Ø{dd:g} {tol['fit_dowel']} dowel")
        for (x, y) in pillars:
            ts.hole(x + SL / 2, y + SW / 2, bush_od, "fit", f"Ø{bush_od:g} {rules.text('fit_bush', 'H7')} bush seat")
        hm, hhd = _mat(rules, _line(lines, "Punch holder"), base_mat)
        comps.append(hp.comp("Punch holder plate", [(-DL / 2, -DW / 2, z_holder)], material=hm, hardness=hhd, color="plate",
                             notes=plate_notes + [f"Punch seats {tol['fit_punch']}"]))
        g, hd = _mat(rules, _line(lines, "Backing plate"), die_mat)
        comps.append(pb.comp("Backing plate (punch)", [(-DL / 2, -DW / 2, z_pback)], material=g, hardness=hd, color="hard",
                             notes=plate_notes + [tol["heat_treat_note"]]))
        # punches
        pline = _line(lines, "Piercing punch")
        for p in punches:
            if p[0] == "round":
                _, cx, cy, r = p
                hd = 2 * r + ph_extra
                body = cq.Workplane("XY").circle(r).extrude(plen).union(
                    cq.Workplane("XY").workplane(offset=plen - ph_extra * 1.5).circle(hd / 2).extrude(ph_extra * 1.5))
                std = " ".join(x for x in (pline.get("std_part") or "", pline.get("part_number") or "") if x)
                name = f"Piercing punch Ø{2 * r:.2f}"
                same = next((k for k in comps if k.name == name), None)
                if same:
                    same.locs.append((cx, cy, z_ptip))
                    continue
                comps.append(Comp(name, body.val(), [(cx, cy, z_ptip)], kind="std" if std else "made",
                                  material=pline.get("grade") or pm, hardness=rules.hardness(pline.get("grade") or pm),
                                  make=pline.get("make") or "", std=(std + f" - order Ø{2 * r:.2f} × {plen:g}") if std else "",
                                  size=(hd, hd, plen), color="hard", drawing="solid",
                                  notes=[f"Ø{2 * r:.3f} {tol['punch_tol']} (piercing: punch = hole size)", tol["heat_treat_note"]]))
            else:
                pts = p[1]
                x0, y0 = min(q[0] for q in pts), min(q[1] for q in pts)
                local = _move(pts, -x0, -y0)
                comps.append(Comp("Blanking punch", _prism(local, 0, plen).val(), [(x0, y0, z_ptip)], material=pm, hardness=phd,
                                  size=(max(q[0] for q in local), max(q[1] for q in local), plen), color="hard", drawing="solid",
                                  openings=[{"pts": local, "label": "Punch profile = blank − clearance", "tol": tol["punch_tol"]}],
                                  notes=[f"Profile = blank outline − {c:.3f} mm per side, {tol['punch_tol']} mm", tol["heat_treat_note"],
                                         f"Working faces {tol['finish_working']}"]))
        if die.get("progressive") and "bend" in ops and fp.get("bends") and st_form is not None:
            comps += _forming_station(dp, hp, fp, t, rules, lines, st_form, DL, DW, z_die, DH, z_holder, holder_h, die_mat)
            notes.append(f"Progressive die: forming station at {st_form:+.1f} mm (V-forming insert in the die plate, forming punch "
                         "in the punch holder); check carrier, pilots and lifters with the strip layout.")
        top_screws = [(x - DL / 2, y - DW / 2) for x, y in corners]
    else:
        # ----- bending: V-die block and punch blade -----
        bend = (fp.get("bends") or [None])[0]
        if not bend:
            raise DesignError("The flat pattern has no bend line for the bending die.")
        ang = bend["angle_deg"]
        inc = math.radians(180 - ang - rules("overbend_deg"))
        half = inc / 2
        (x1, y1), (x2, y2) = bend["line"]
        blen = math.hypot(x2 - x1, y2 - y1)
        horizontal = abs(x2 - x1) > abs(y2 - y1)
        vl = blen + 20
        vw = v_open * rules("v_die_w_factor")
        depth_v = (v_open / 2) / math.tan(half)
        if depth_v > v_h - 10:
            notes.append("V-die is shallow for this opening: check v_die_h_mm.")
        # V block: length along the bend line (Y if the bend line runs along Y)
        VX, VY = (vl, vw) if horizontal else (vw, vl)
        vb = cq.Workplane("XY").box(VX, VY, v_h, centered=False)
        if horizontal:
            prof = cq.Workplane("YZ").polyline([(vw / 2 - v_open / 2, v_h + 0.01), (vw / 2, v_h - depth_v), (vw / 2 + v_open / 2, v_h + 0.01)]).close().extrude(VX)
        else:
            prof = cq.Workplane("XZ").polyline([(vw / 2 - v_open / 2, v_h + 0.01), (vw / 2, v_h - depth_v), (vw / 2 + v_open / 2, v_h + 0.01)]).close().extrude(-VY)
        vb = vb.cut(prof)
        vmat, vhard = _mat(rules, _line(lines, "Bending die"), die_mat)
        vholes = []
        for (x, y) in ((10, 10), (VX - 10, VY - 10)) if horizontal else ((10, 10), (VX - 10, VY - 10)):
            vb = vb.cut(cq.Workplane("XY").center(x, y).circle(sd * 0.425).extrude(2 * sd))
            vholes.append({"x": x, "y": y, "d": sd * 0.85, "kind": "tap", "label": f"M{sd:g} tapped from below", "depth": 2 * sd, "top": False})
        cxv = (x1 + x2) / 2 + ox
        cyv = (y1 + y2) / 2 + oy
        comps.append(Comp("V-die block", vb.val(), [(cxv - VX / 2, cyv - VY / 2, z_die)], material=vmat, hardness=vhard, color="hard",
                          size=(VX, VY, v_h), holes=vholes, drawing="solid",
                          notes=[f"V opening {v_open:g} mm ({rules('v_die_open_factor'):g} × t), included angle "
                                 f"{math.degrees(inc):.1f}° (bend {ang:g}° with {rules('overbend_deg'):g}° overbend)",
                                 tol["heat_treat_note"], f"V faces {tol['finish_working']}"]))
        # gauge pins at the end of the far leg: locate the blank
        gpd = rules("gauge_pin_d_mm")
        fx, fy = bend["far_side"]
        gx = fp["length_mm"] + gap + gpd / 2 if fx > (x1 + x2) / 2 else -gap - gpd / 2
        pins = [(gx + ox, fp["width_mm"] * 0.25 + oy), (gx + ox, fp["width_mm"] * 0.75 + oy)] if horizontal is False else \
               [(fp["length_mm"] * 0.25 + ox, (fp["width_mm"] + gap + gpd / 2 if fy > (y1 + y2) / 2 else -gap - gpd / 2) + oy),
                (fp["length_mm"] * 0.75 + ox, (fp["width_mm"] + gap + gpd / 2 if fy > (y1 + y2) / 2 else -gap - gpd / 2) + oy)]
        pin_len = die_top - shoe_h + 3 * t
        for (x, y) in pins:
            bshoe.hole(x + SL / 2, y + SW / 2, gpd, "fit", f"Ø{gpd:g} {tol['fit_dowel']} gauge pin", depth=gpd * 1.5)
        comps.append(Comp(f"Gauge pin Ø{gpd:g}", cq.Workplane("XY").circle(gpd / 2).extrude(pin_len + gpd * 1.5).val(),
                          [(x, y, shoe_h - gpd * 1.5) for x, y in pins], kind="std", material="", make="",
                          std=f"Dowel / gauge pin ISO 8734 Ø{gpd:g} m6 × {_round_up(pin_len + gpd * 1.5, 5):g}", size=(gpd, gpd, pin_len),
                          color="std", drawing="none", notes=["Locates the blank end (far leg) before bending"]))
        # punch blade: tip radius = inside radius of the part
        r_tip = max(bend["inner_radius_mm"], 0.2)
        bh = rules("bend_punch_h_mm")
        z_ptip = die_top - depth_v + t / math.sin(half)
        bw = max(20.0, 2 * (bh * math.tan(half)) * 0.5)
        tipw = 2 * r_tip * math.cos(half) + 2 * (bh * math.tan(half))
        pts2d = [(-r_tip * math.cos(half), r_tip * (1 - math.sin(half))), (-min(bw, tipw) / 2, bh), (min(bw, tipw) / 2, bh),
                 (r_tip * math.cos(half), r_tip * (1 - math.sin(half)))]
        if horizontal:
            blade = cq.Workplane("YZ").polyline(pts2d).close().extrude(vl)
            blade = blade.union(cq.Workplane("YZ").center(0, r_tip).circle(r_tip).extrude(vl))
            bloc = (cxv - vl / 2, cyv, z_ptip)
        else:
            blade = cq.Workplane("XZ").polyline(pts2d).close().extrude(-vl)
            blade = blade.union(cq.Workplane("XZ").center(0, r_tip).circle(r_tip).extrude(-vl))
            bloc = (cxv, cyv - vl / 2, z_ptip)
        bm, bhd = _mat(rules, _line(lines, "Bending punch"), die_mat)
        bb = blade.val().BoundingBox()
        comps.append(Comp("Bending punch", blade.val(), [bloc], material=bm, hardness=bhd, color="hard",
                          size=(bb.xlen, bb.ylen, bb.zlen), drawing="solid",
                          notes=[f"Tip radius R{r_tip:g} = inside bend radius of the part", f"Included angle {math.degrees(inc):.1f}°",
                                 tol["heat_treat_note"], f"Tip {tol['finish_working']}"]))
        # punch holder (clamps the blade) and top shoe
        hp = Plate(DL, DW, holder_h)
        slot_w = min(bw, tipw)
        if horizontal:
            hp.opening([[DL / 2 - vl / 2, DW / 2 - slot_w / 2], [DL / 2 + vl / 2, DW / 2 - slot_w / 2],
                        [DL / 2 + vl / 2, DW / 2 + slot_w / 2], [DL / 2 - vl / 2, DW / 2 + slot_w / 2]], "Blade slot", tol["fit_punch"])
        else:
            hp.opening([[DL / 2 - slot_w / 2, DW / 2 - vl / 2], [DL / 2 + slot_w / 2, DW / 2 - vl / 2],
                        [DL / 2 + slot_w / 2, DW / 2 + vl / 2], [DL / 2 - slot_w / 2, DW / 2 + vl / 2]], "Blade slot", tol["fit_punch"])
        corners = [(se, se), (DL - se, se), (se, DW - se), (DL - se, DW - se)]
        ts = Plate(SL, SW, shoe_h)
        for (x, y) in corners:
            hp.hole(x, y, sd * 0.85, "tap", f"M{sd:g} tapped", depth=2 * sd)
            ts.hole(x - DL / 2 + SL / 2, y - DW / 2 + SW / 2, sd + 1, "cbore", f"M{sd:g}", cb_d=1.6 * sd + 1, cb_h=sd + 1)
        for (x, y) in pillars:
            ts.hole(x + SL / 2, y + SW / 2, bush_od, "fit", f"Ø{bush_od:g} {rules.text('fit_bush', 'H7')} bush seat")
        hm, hhd = _mat(rules, _line(lines, "Punch holder"), base_mat)
        z_hold = z_ptip + bh - holder_h
        comps.append(hp.comp("Punch holder plate", [(-DL / 2, -DW / 2, z_hold)], material=hm, hardness=hhd, color="plate",
                             notes=plate_notes + [f"Blade slot {tol['fit_punch']}"]))
        z_tshoe = z_hold + holder_h
        top_screws = [(x - DL / 2, y - DW / 2) for x, y in corners]
        # V block screws from below through the bottom shoe
        for h in vholes:
            bshoe.hole(cxv - VX / 2 + h["x"] + SL / 2, cyv - VY / 2 + h["y"] + SW / 2, sd + 1, "cbore", f"M{sd:g}",
                       cb_d=1.6 * sd + 1, cb_h=sd + 1, from_top=False)
        lower_screws = []
        loc_note = "blank located by gauge pins at the end of the far leg"
        plen = bh
    # ----- shoes, pillars, bushes -----
    comps.insert(0, bshoe.comp("Bottom shoe (die set)", [(-SL / 2, -SW / 2, z_bshoe)], material=base_mat, kind="made",
                               make=base.get("make") or "", color="shoe",
                               notes=plate_notes + [f"Part of die set {base.get('series', '')} {base.get('size_code', '')}"]))
    comps.insert(1, ts.comp("Top shoe (die set)", [(-SL / 2, -SW / 2, z_tshoe)], material=base_mat, make=base.get("make") or "",
                            color="shoe", notes=plate_notes + [f"Part of die set {base.get('series', '')} {base.get('size_code', '')}"]))
    plen_p = z_tshoe + shoe_h - 5
    comps.append(Comp(f"Guide pillar Ø{pd:g}", cq.Workplane("XY").circle(pd / 2).extrude(plen_p).val(),
                      [(x, y, 0.0) for x, y in pillars], kind="std", make=base.get("make") or "",
                      std=f"Guide pillar Ø{pd:g} {tol['fit_pillar']} × {_round_up(plen_p, 5):g} (die set {base.get('series', '')} {base.get('size_code', '')})",
                      size=(pd, pd, plen_p), color="std", drawing="none", notes=[f"Ø{pd:g} {tol['fit_pillar']}"]))
    bush = cq.Workplane("XY").circle(bush_od / 2).circle(pd / 2).extrude(bush_len)
    comps.append(Comp(f"Guide bush Ø{pd:g}", bush.val(), [(x, y, z_tshoe + shoe_h - bush_len) for x, y in pillars], kind="std",
                      make=base.get("make") or "", std=f"Guide bush Ø{pd:g} {tol['fit_bush']} × OD {bush_od:g} × {bush_len:g}",
                      size=(bush_od, bush_od, bush_len), color="std", drawing="none"))
    # ----- screws and dowels (ISO 4762 / ISO 8734) -----
    def screw(d, L):
        hd, hh = 1.5 * d, d
        return cq.Workplane("XY").circle(d / 2).extrude(L).union(cq.Workplane("XY").workplane(offset=L).circle(hd / 2).extrude(hh)).val()
    sline = _line(lines, "Screws")
    if lower_screws:
        grip = DH - (sd + 1) + back_h
        L = _screw_len(grip, sd)
        comps.append(Comp(f"Socket head cap screw M{sd:g} × {L:g}", screw(sd, L),
                          [(x, y, z_die + DH - (sd + 1) - L) for x, y in lower_screws], kind="std", make=sline.get("make") or "",
                          std=f"ISO 4762 M{sd:g} × {L:g} - 12.9", size=(1.5 * sd, 1.5 * sd, L + sd), color="screw", drawing="none"))
        dl = _round_up(DH + back_h + 1.5 * dd - 2, 5)
        comps.append(Comp(f"Dowel pin Ø{dd:g} × {dl:g}", cq.Workplane("XY").circle(dd / 2).extrude(dl).val(),
                          [(x - DL / 2, y - DW / 2, shoe_h - 1.5 * dd) for x, y in dowels], kind="std", make=sline.get("make") or "",
                          std=f"ISO 8734 Ø{dd:g} m6 × {dl:g}", size=(dd, dd, dl), color="screw", drawing="none"))
    if top_screws:
        grip = shoe_h - (sd + 1) + (pback_h if not bending else 0)
        L = _screw_len(grip, sd)
        comps.append(Comp(f"Socket head cap screw M{sd:g} × {L:g} (top)", screw(sd, L).rotate((0, 0, 0), (1, 0, 0), 180),
                          [(x, y, z_tshoe + shoe_h - (sd + 1)) for x, y in top_screws], kind="std", make=sline.get("make") or "",
                          std=f"ISO 4762 M{sd:g} × {L:g} - 12.9", size=(1.5 * sd, 1.5 * sd, L + sd), color="screw", drawing="none"))
    # workpiece (reference)
    z_sheet = die_top
    if not bending and die.get("progressive"):
        sw_ = float(die.get("strip_w") or fp["width_mm"])
        comps.append(Comp("Workpiece (reference: strip)", _box(DL, sw_, t).val(), [(-DL / 2, -sw_ / 2, die_top)], kind="ref",
                          size=(DL, sw_, t), color="ref", drawing="none"))
    elif not bending:
        wp = _prism(outline, 0, t)
        for h in (holes if "pierce" not in ops else []):
            wp = wp.cut(_prism(h, -0.1, t + 0.2))
        comps.append(Comp("Workpiece (reference: blank)", wp.val(), [(0.0, 0.0, die_top)], kind="ref", size=(fp["length_mm"], fp["width_mm"], t),
                          color="ref", drawing="none"))
    else:
        flat = _prism(outline, 0, t)
        for h in holes:
            flat = flat.cut(_prism(h, -0.1, t + 0.2))
        comps.append(Comp("Workpiece (reference: blank before bending)", flat.val(), [(0.0, 0.0, z_sheet)], kind="ref",
                          size=(fp["length_mm"], fp["width_mm"], t), color="ref", drawing="none"))
    # item numbers: made parts first, then standard parts
    order = [c for c in comps if c.kind == "made"] + [c for c in comps if c.kind == "std"] + [c for c in comps if c.kind == "ref"]
    for i, c in enumerate(order, start=1):
        c.no = f"{i:02d}" if c.kind != "ref" else "REF"
    shut = z_tshoe + shoe_h
    notes += [f"Closed (bottom of stroke): shut height {shut:.1f} mm; {loc_note}.",
              f"Press {((die.get('press') or {}).get('machine_id')) or '-'} for {die.get('force_t') or 0:.1f} t."]
    return {"name": die["name"], "key": die["key"], "components": order, "notes": notes, "shut_height": round(shut, 1),
            "die_set": f"{base.get('series', '')} {base.get('size_code', '')} {SL:.0f} × {SW:.0f}",
            "rules_are_examples": rules.is_example, "punch_len": plen}


# ---------- assembly output ----------

def assembly(design: dict, name: str):
    asm = cq.Assembly(name=name)
    for c in design["components"]:
        col = cq.Color(*COLORS.get(c.color, COLORS["plate"]))
        for k, (x, y, z) in enumerate(c.locs, start=1):
            label = f"{c.no}_{c.name}" + (f"_{k}" if c.qty > 1 else "")
            label = "".join(ch if ch.isalnum() or ch in "_-." else "_" for ch in label)
            asm.add(c.shape, name=label, color=col, loc=cq.Location(cq.Vector(x, y, z)))
    return asm


def step_bytes(obj) -> bytes:
    fd, path = tempfile.mkstemp(suffix=".step")
    os.close(fd)
    try:
        if isinstance(obj, cq.Assembly):
            obj.export(path, "STEP")
        else:
            cq.exporters.export(cq.Workplane("XY").add(obj), path, "STEP")
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        os.remove(path)


# ---------- drawing die (deep drawing of trays, cups, panels) ----------

def _outline_at(solid, z: float):
    """Outer outline (list of x, y) of a solid's cross-section just above z, or None."""
    from shapely.geometry import MultiPolygon
    from shapely.ops import unary_union
    bb = solid.BoundingBox()
    slab = cq.Solid.makeBox(bb.xlen + 20, bb.ylen + 20, 0.2, cq.Vector(bb.xmin - 10, bb.ymin - 10, z + 0.5))
    sec = solid.intersect(slab)
    polys = []
    for f in sec.Faces():
        if abs(f.normalAt().z) > 0.99:
            from .unfold import _wire_pts
            pts = [(p[0], p[1]) for p in _wire_pts(f.outerWire())]
            if len(pts) >= 3:
                polys.append(Polygon(pts).buffer(0))
    if not polys:
        return None
    u = unary_union(polys)
    if isinstance(u, MultiPolygon):
        u = max(u.geoms, key=lambda g: g.area)
    return [list(c) for c in u.exterior.coords]


def draw_die_design(part: dict, shape, t: float, die: dict, lines: list, trim: bool = False) -> dict:
    """Drawing die: punch (inside of the part) on the bottom shoe, blank holder round it on cushion pins, die (outside of
    the part) on the top shoe, guide pillars and bushes. Closed position.
    trim=True: trimming die of the drawn part - trim post (the punch shape) holds the part, the upper trim steel cuts the rim
    (opening = outside of the part + cutting clearance), pressure pad in the trim steel; scrap cutters noted."""
    from .mould_design import split_core_cavity
    rules = Rules("sheet_metal")
    base = die["base"]
    SL, SW = float(base["length_mm"]), float(base["width_mm"])
    if die.get("base_turned"):
        SL, SW = SW, SL
    shoe_h = float(base.get("clamp_plates_mm") or rules("die_plate_min_mm"))
    DL, DW = float(die["die_plate"]["die_l"]), float(die["die_plate"]["die_w"])
    back = rules("draw_die_backing_mm", 60)
    sp = split_core_cavity(shape, "z", 0.0, DL, DW, back)
    s, bb, pl, cavity, ha = sp["part"], sp["bb"], sp["pl"], sp["cavity"], sp["ha"]
    notes = list(sp["notes"])
    if sp["enclosed"] is None:
        raise DesignError("The drawn shape encloses no punch region (is the part open on one side?).")
    outline = _outline_at(sp["enclosed"], pl)
    if not outline:
        raise DesignError("Could not find the punch outline at the parting plane.")
    hb = rules("draw_holder_h_mm", 50)
    clear = t * (1 + rules("draw_clearance_pct", 10) / 100)
    punch_base = cq.Workplane("XY").workplane(offset=pl - hb).polyline([tuple(p) for p in outline[:-1]]).close().extrude(hb).val()
    punch = sp["enclosed"].fuse(punch_base).clean()
    holder = Plate(DL, DW, hb)
    holder.opening(_move(_offset(outline, clear), DL / 2, DW / 2), f"Blank holder opening = punch + {clear:.2f} mm per side", "")
    pd = _pillar_d(rules, SW)
    pe = rules("pillar_edge_factor") * pd
    pillars = [(-SL / 2 + pe, -SW / 2 + pe), (SL / 2 - pe, -SW / 2 + pe), (-SL / 2 + pe, SW / 2 - pe), (SL / 2 - pe, SW / 2 - pe)]
    bush_od, bush_len = rules("bush_od_factor") * pd, rules("bush_len_factor") * pd
    z_shoe_top = pl - hb
    bshoe, tshoe = Plate(SL, SW, shoe_h), Plate(SL, SW, shoe_h)
    for (x, y) in pillars:
        bshoe.hole(x + SL / 2, y + SW / 2, pd, "fit", f"Ø{pd:g} {rules.text('fit_bush', 'H7')} pillar seat")
        tshoe.hole(x + SL / 2, y + SW / 2, bush_od, "fit", f"Ø{bush_od:g} {rules.text('fit_bush', 'H7')} bush seat")
    cpd = rules("cushion_pin_d_mm", 20)
    ob = Polygon(outline).bounds
    cush = [(x, y) for x in (ob[0] - clear - 1.5 * cpd, ob[2] + clear + 1.5 * cpd) for y in (ob[1] / 2, ob[3] / 2)]
    cush = [(x, y) for x, y in cush if abs(x) + cpd < DL / 2 and abs(y) + cpd < DW / 2]
    for (x, y) in cush:
        bshoe.hole(x + SL / 2, y + SW / 2, cpd + 1, "thru", f"Ø{cpd + 1:g} cushion pin")
    dm, dh = _mat(rules, _line(lines, "Draw die ring", "Die plate"), "")
    pm, ph = _mat(rules, _line(lines, "Draw punch"), dm)
    hm, hh = _mat(rules, _line(lines, "Blank holder"), dm)
    tol_ = {k: rules.text(k) for k in ("finish_working", "heat_treat_note", "plate_thk_tol", "plate_flatness", "fit_pillar", "fit_bush")}
    pnotes = [f"Thickness {tol_['plate_thk_tol']} mm", f"Flatness {tol_['plate_flatness']}"]
    if trim:
        c_cut = rules("cut_clearance_pct") / 100 * t
        steel = Plate(DL, DW, hb)
        steel.opening(_move(_offset(outline, t + c_cut), DL / 2, DW / 2), f"Trim steel opening = outside of the part + {c_cut:.3f}", "")
        pad_ = punch.translate(cq.Vector(0, 0, 0))
        comps = [
            bshoe.comp("Bottom shoe (die set)", [(-SL / 2, -SW / 2, z_shoe_top - shoe_h)], material=base.get("material") or "",
                       make=base.get("make") or "", color="shoe", notes=pnotes),
            tshoe.comp("Top shoe (die set)", [(-SL / 2, -SW / 2, pl + bb.zlen + hb)], material=base.get("material") or "",
                       make=base.get("make") or "", color="shoe", notes=pnotes),
            Comp("Trim post", pad_.translate(cq.Vector(DL / 2, DW / 2, -(pl - hb))), [(-DL / 2, -DW / 2, pl - hb)], material=pm, hardness=ph,
                 color="hard", size=(Polygon(outline).bounds[2] - Polygon(outline).bounds[0],
                                     Polygon(outline).bounds[3] - Polygon(outline).bounds[1], bb.zlen + hb), drawing="solid",
                 notes=["Holds the drawn part (inside shape); cutting edge at the trim line", tol_["heat_treat_note"]]),
            steel.comp("Trim steel (upper)", [(-DL / 2, -DW / 2, pl + bb.zlen)], material=dm, hardness=dh, color="hard",
                       notes=pnotes + [f"Cutting edge {tol_['finish_working']}", tol_["heat_treat_note"]]),
        ]
        notes.append("Trimming of the drawn part: trim line at the rim; scrap cutters and a pressure pad in the trim steel to be "
                     "detailed by the die designer.")
        shut0 = (pl + bb.zlen + hb + shoe_h) - (z_shoe_top - shoe_h)
        ha = bb.zlen + hb                      # top shoe above the trim steel
        cush = []
    else:
        shut0 = None
    if not trim:
        comps = [
            bshoe.comp("Bottom shoe (die set)", [(-SL / 2, -SW / 2, z_shoe_top - shoe_h)], material=base.get("material") or "",
                       make=base.get("make") or "", color="shoe", notes=pnotes + ["Cushion pin holes for the blank holder"]),
            tshoe.comp("Top shoe (die set)", [(-SL / 2, -SW / 2, pl + ha)], material=base.get("material") or "", make=base.get("make") or "",
                       color="shoe", notes=pnotes),
            Comp("Draw die (cavity)", cavity.translate(cq.Vector(DL / 2, DW / 2, -pl)), [(-DL / 2, -DW / 2, pl)], material=dm, hardness=dh,
                 color="hard", size=(DL, DW, ha), drawing="solid",
                 notes=["Cavity = outside of the part; draw radius as the part", tol_["heat_treat_note"], f"Drawing faces {tol_['finish_working']} (polish)"]),
            Comp("Draw punch", punch.translate(cq.Vector(DL / 2, DW / 2, -(pl - hb))), [(-DL / 2, -DW / 2, pl - hb)], material=pm, hardness=ph,
                 color="hard", size=(Polygon(outline).bounds[2] - Polygon(outline).bounds[0], Polygon(outline).bounds[3] - Polygon(outline).bounds[1],
                                     bb.zlen + hb), drawing="solid",
                 notes=["Punch = inside of the part", tol_["heat_treat_note"], f"Drawing faces {tol_['finish_working']}"]),
            holder.comp("Blank holder (binder)", [(-DL / 2, -DW / 2, pl - hb)], material=hm, hardness=hh, color="plate",
                        notes=pnotes + ["Rides on the press cushion through the cushion pins", tol_["heat_treat_note"]]),
        ]
    plen = (pl + ha + shoe_h) - (z_shoe_top - shoe_h) - 5
    comps.append(Comp(f"Guide pillar Ø{pd:g}", cq.Workplane("XY").circle(pd / 2).extrude(plen).val(),
                      [(x, y, z_shoe_top - shoe_h) for x, y in pillars], kind="std", make=base.get("make") or "",
                      std=f"Guide pillar Ø{pd:g} {tol_['fit_pillar']} × {_round_up(plen, 5):g}", size=(pd, pd, plen), color="std", drawing="none"))
    comps.append(Comp(f"Guide bush Ø{pd:g}", cq.Workplane("XY").circle(bush_od / 2).circle(pd / 2).extrude(bush_len).val(),
                      [(x, y, pl + ha + shoe_h - bush_len) for x, y in pillars], kind="std", make=base.get("make") or "",
                      std=f"Guide bush Ø{pd:g} {tol_['fit_bush']} × OD {bush_od:g} × {bush_len:g}", size=(bush_od, bush_od, bush_len),
                      color="std", drawing="none"))
    if cush:
        cl = shoe_h + rules("cushion_stroke_mm", 50)
        comps.append(Comp(f"Cushion pin Ø{cpd:g} × {cl:g}", cq.Workplane("XY").circle(cpd / 2).extrude(cl).val(),
                          [(x, y, z_shoe_top - cl) for x, y in cush], kind="std", std=f"Cushion pin Ø{cpd:g} × {cl:g}",
                          size=(cpd, cpd, cl), color="std", drawing="none"))
    comps.append(Comp("Drawn part (reference)", s, [(0.0, 0.0, 0.0)], kind="ref", size=(bb.xlen, bb.ylen, bb.zlen), color="ref", drawing="none"))
    order = [c for c in comps if c.kind == "made"] + [c for c in comps if c.kind == "std"] + [c for c in comps if c.kind == "ref"]
    for i, c in enumerate(order, start=1):
        c.no = f"{i:02d}" if c.kind != "ref" else "REF"
    shut = shut0 or (pl + ha + shoe_h) - (z_shoe_top - shoe_h)
    notes += ([f"Closed: shut height {shut:.1f} mm."] if trim else
              [f"Draw depth {bb.zlen:.1f} mm; punch–die clearance {clear:.2f} mm per side (t + {rules('draw_clearance_pct', 10):g} %).",
               f"Closed: shut height {shut:.1f} mm; blank holder on the press cushion ({len(cush)} cushion pins)."]) + [
        f"Press {((die.get('press') or {}).get('machine_id')) or '-'} for {die.get('force_t') or 0:.1f} t."]
    return {"name": die["name"], "key": die["key"], "components": order, "notes": notes, "shut_height": round(shut, 1),
            "die_set": f"{base.get('series', '')} {base.get('size_code', '')} {SL:.0f} × {SW:.0f}",
            "rules_are_examples": rules.is_example, "punch_len": bb.zlen + hb}


# ---------- U-bending die (channels: two parallel bends the same way, one hit) ----------

def u_shape(fp: dict):
    """The U of a channel: two parallel bends turning the same way with the base between them, else None."""
    bs = fp.get("bends") or []
    if len(bs) != 2:
        return None
    (a1, a2), (b1, _) = bs[0]["line"], bs[1]["line"]
    horiz = abs(a2[0] - a1[0]) > abs(a2[1] - a1[1])
    k = 1 if horiz else 0                       # coordinate across the bend lines
    ca, cb = a1[k], b1[k]
    if bs[0]["up"] != bs[1]["up"] or abs(bs[0]["angle_deg"] - 90) > 15 or abs(bs[1]["angle_deg"] - 90) > 15:
        return None
    fa, fb = bs[0]["far_side"][k], bs[1]["far_side"][k]
    if not ((fa - ca) * (cb - ca) < 0 and (fb - cb) * (ca - cb) < 0):
        return None                             # the far sides must point away from the base (flanges outside)
    r = max(bs[0]["inner_radius_mm"], bs[1]["inner_radius_mm"])
    dev = bs[0]["developed_mm"]
    lo, hi = min(ca, cb), max(ca, cb)
    flat_across = fp["width_mm"] if horiz else fp["length_mm"]
    flange_flat = min(lo, flat_across - hi) - dev / 2
    length = fp["length_mm"] if horiz else fp["width_mm"]
    return {"horizontal": horiz, "base_flat": hi - lo - dev, "flange_flat": flange_flat, "r": r, "length": length,
            "centre": (lo + hi) / 2}


def u_die_design(part: dict, fp: dict, t: float, die: dict, lines: list) -> dict:
    u = u_shape(fp)
    if not u:
        raise DesignError("Not a U channel.")
    rules = Rules("sheet_metal")
    base = die["base"]
    SL, SW = float(base["length_mm"]), float(base["width_mm"])
    if die.get("base_turned"):
        SL, SW = SW, SL
    shoe_h = float(base.get("clamp_plates_mm") or rules("die_plate_min_mm"))
    r = u["r"]
    w_out = u["base_flat"] + 2 * (r + t)
    h_out = u["flange_flat"] + r + t
    w_in = w_out - 2 * t
    gap = t * rules("draw_clearance_pct", 10) / 100            # slot = outside width + small clearance per side
    slot = w_out + 2 * gap
    blen = u["length"] + 40
    wall = rules("die_wall_mm", 35)
    pad_h = rules("u_die_pad_h_mm", 40)
    spring_l = rules("spring_len_mm")
    floor = 25.0
    Hb = floor + spring_l * 0.6 + pad_h + h_out
    Wb = slot + 2 * max(wall, 0.6 * h_out)
    z_die = shoe_h
    z_top = z_die + Hb
    z_pad = z_top - h_out - pad_h
    # die block with the slot
    die_blk = cq.Workplane("XY").box(blen, Wb, Hb, centered=False).cut(
        cq.Workplane("XY").workplane(offset=floor).center(blen / 2, Wb / 2).rect(blen + 2, slot).extrude(Hb))
    die_blk = die_blk.edges("|X and >Z").fillet(min(r + t, wall / 3)) if r + t > 0.5 else die_blk
    dm, dh = _mat(rules, _line(lines, "Bending die", "Die plate"), "")
    comps = []
    comps.append(Comp("U-bending die", die_blk.val(), [(-blen / 2, -Wb / 2, z_die)], material=dm, hardness=dh, color="hard",
                      size=(blen, Wb, Hb), drawing="solid",
                      notes=[f"Slot {slot:.2f} mm = outside width {w_out:.2f} + {gap:.2f} per side; entry radius R{r + t:g}",
                             rules.text("heat_treat_note"), f"Working faces {rules.text('finish_working')}"]))
    pad = Plate(blen, slot - 1.0, pad_h)
    pm, ph = _mat(rules, _line(lines, "Pressure pad"), dm)
    comps.append(pad.comp("Pressure pad (ejector)", [(-blen / 2, -(slot - 1) / 2, z_pad)], material=pm, hardness=ph, color="plate",
                          notes=["Holds the base flat and lifts the part out", f"Springs below: {rules('pad_springs', 4):g}"]))
    punch_h = h_out + 30
    pnch = cq.Workplane("XY").box(u["length"], w_in, punch_h, centered=False)
    if r > 0.3:
        pnch = pnch.edges("|X and <Z").fillet(min(r, w_in / 2 - 0.1))
    bm, bh = _mat(rules, _line(lines, "Bending punch"), dm)
    comps.append(Comp("U-bending punch", pnch.val(), [(-u["length"] / 2, -w_in / 2, z_pad + pad_h + t)], material=bm, hardness=bh,
                      color="hard", size=(u["length"], w_in, punch_h), drawing="solid",
                      notes=[f"Width {w_in:.2f} = inside width of the channel; nose radius R{r:g}", rules.text("heat_treat_note")]))
    z_holder = z_pad + pad_h + t + punch_h - 15
    hold_h = rules("punch_plate_h_mm")
    DL, DW = max(float(die["die_plate"]["die_l"]), blen + 2 * wall), max(float(die["die_plate"]["die_w"]), Wb)
    hp = Plate(DL, DW, hold_h)
    hp.opening([[DL / 2 - u["length"] / 2, DW / 2 - w_in / 2], [DL / 2 + u["length"] / 2, DW / 2 - w_in / 2],
                [DL / 2 + u["length"] / 2, DW / 2 + w_in / 2], [DL / 2 - u["length"] / 2, DW / 2 + w_in / 2],
                [DL / 2 - u["length"] / 2, DW / 2 - w_in / 2]], "Punch seat", rules.text("fit_punch"))
    hm, hhd = _mat(rules, _line(lines, "Punch holder"), base.get("material") or "")
    comps.append(hp.comp("Punch holder plate", [(-DL / 2, -DW / 2, z_holder)], material=hm, hardness=hhd, color="plate"))
    z_tshoe = z_holder + hold_h
    pd = _pillar_d(rules, SW)
    pe = rules("pillar_edge_factor") * pd
    pillars = [(-SL / 2 + pe, -SW / 2 + pe), (SL / 2 - pe, -SW / 2 + pe), (-SL / 2 + pe, SW / 2 - pe), (SL / 2 - pe, SW / 2 - pe)]
    bush_od, bush_len = rules("bush_od_factor") * pd, rules("bush_len_factor") * pd
    bshoe, tshoe = Plate(SL, SW, shoe_h), Plate(SL, SW, shoe_h)
    for (x, y) in pillars:
        bshoe.hole(x + SL / 2, y + SW / 2, pd, "fit", f"Ø{pd:g} {rules.text('fit_bush', 'H7')} pillar seat")
        tshoe.hole(x + SL / 2, y + SW / 2, bush_od, "fit", f"Ø{bush_od:g} {rules.text('fit_bush', 'H7')} bush seat")
    sod = rules("spring_od_mm")
    springs = [(x, 0.0) for x in (-blen / 3, blen / 3)] + [(x, 0.0) for x in (-blen / 8, blen / 8)]
    springs = springs[:int(rules("pad_springs", 4))]
    comps = [bshoe.comp("Bottom shoe (die set)", [(-SL / 2, -SW / 2, 0.0)], material=base.get("material") or "", make=base.get("make") or "",
                        color="shoe"),
             tshoe.comp("Top shoe (die set)", [(-SL / 2, -SW / 2, z_tshoe)], material=base.get("material") or "", make=base.get("make") or "",
                        color="shoe")] + comps
    comps.append(Comp(f"Die spring Ø{sod:g} × {spring_l:g}", cq.Workplane("XY").circle(sod / 2).circle(sod / 2 - 4).extrude(z_pad - z_die - floor).val(),
                      [(x, y, z_die + floor) for x, y in springs], kind="std",
                      std=f"Die spring ISO 10243 Ø{sod:g} × {spring_l:g}", size=(sod, sod, spring_l), color="std", drawing="none"))
    plen = z_tshoe + shoe_h - 5
    comps.append(Comp(f"Guide pillar Ø{pd:g}", cq.Workplane("XY").circle(pd / 2).extrude(plen).val(), [(x, y, 0.0) for x, y in pillars],
                      kind="std", make=base.get("make") or "", std=f"Guide pillar Ø{pd:g} {rules.text('fit_pillar')} × {_round_up(plen, 5):g}",
                      size=(pd, pd, plen), color="std", drawing="none"))
    comps.append(Comp(f"Guide bush Ø{pd:g}", cq.Workplane("XY").circle(bush_od / 2).circle(pd / 2).extrude(bush_len).val(),
                      [(x, y, z_tshoe + shoe_h - bush_len) for x, y in pillars], kind="std", make=base.get("make") or "",
                      std=f"Guide bush Ø{pd:g} {rules.text('fit_bush')} × OD {bush_od:g} × {bush_len:g}", size=(bush_od, bush_od, bush_len),
                      color="std", drawing="none"))
    gpd = rules("gauge_pin_d_mm")
    flat_w = u["base_flat"] + 2 * u["flange_flat"] + 2 * fp["bends"][0]["developed_mm"]
    pins = [(x, s_ * (flat_w / 2 + rules("nest_gap_mm") + gpd / 2)) for x in (-blen / 4, blen / 4) for s_ in (-1, 1)]
    pins = [(x, y) for x, y in pins if abs(y) < Wb / 2 - gpd]
    if pins:
        comps.append(Comp(f"Gauge pin Ø{gpd:g}", cq.Workplane("XY").circle(gpd / 2).extrude(1.5 * gpd + 3 * t).val(),
                          [(x, y, z_top - 1.5 * gpd) for x, y in pins], kind="std", std=f"Dowel / gauge pin ISO 8734 Ø{gpd:g} m6",
                          size=(gpd, gpd, 1.5 * gpd + 3 * t), color="std", drawing="none", notes=["Locate the flat blank across the slot"]))

    prof = [(-w_out / 2, 0), (w_out / 2, 0), (w_out / 2, h_out), (w_out / 2 - t, h_out), (w_out / 2 - t, t), (-w_out / 2 + t, t),
            (-w_out / 2 + t, h_out), (-w_out / 2, h_out)]
    ref = cq.Workplane("YZ").polyline(prof).close().extrude(u["length"]).translate((-u["length"] / 2, 0, z_pad + pad_h)).val()
    comps.append(Comp("Bent channel (reference)", ref, [(0.0, 0.0, 0.0)], kind="ref", size=(u["length"], w_out, h_out), color="ref",
                      drawing="none"))
    order = [c for c in comps if c.kind == "made"] + [c for c in comps if c.kind == "std"] + [c for c in comps if c.kind == "ref"]
    for i, c in enumerate(order, start=1):
        c.no = f"{i:02d}" if c.kind != "ref" else "REF"
    shut = z_tshoe + shoe_h
    notes = [f"U channel in one hit: outside width {w_out:.1f} mm, flange height {h_out:.1f} mm, inside radius R{r:g}.",
             f"Closed: shut height {shut:.1f} mm; pressure pad on {len(springs)} die springs ejects the part.",
             f"Press {((die.get('press') or {}).get('machine_id')) or '-'} for {die.get('force_t') or 0:.1f} t + pad force."]
    if not pins:
        notes.append("Blank wider than the die block: locate it with gauge plates on the die set.")
    return {"name": die["name"].replace("Bending (V)", "Bending (U)"), "key": die["key"], "components": order, "notes": notes,
            "shut_height": round(shut, 1), "die_set": f"{base.get('series', '')} {base.get('size_code', '')} {SL:.0f} × {SW:.0f}",
            "rules_are_examples": rules.is_example, "punch_len": punch_h}
