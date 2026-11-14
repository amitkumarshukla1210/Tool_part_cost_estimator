"""Fin die design outputs (roadmap stage 58): strip layout, 3D die, detail drawings of every die part, fin drawing, BOM,
PO pack and CAD files - all from one design built on the fin die cost (stage 57) of the confirmed fin spec.

    stations      draw steps, pierce & burr, ironing, louver, slit, wave, reflare, edge trim, pilot, row slit, feed, cut-off
                  (Fin patterns + fin_fixed_stations), each max(feed, station_min_mm) long along the die
    die parts     die set plates (Mould bases fin), per station: sub-die / button plate, stripper plate, punch holder; punches
                  (draw, pierce & burr, ironing, reflare), louver / slit sets, wave dies, edge trim, row slit blades, cut-off
                  punch & die, pilots, guide posts; sizes from the Sizing rules fin, grades from the die BOM (stage 57),
                  hardness from Tool materials, tolerances from the Design rules fin
    outputs       strip layout PDF + DXF, 3D viewer (HTML), die STEP + STL, detail drawings PDF + DXF (ZIP), fin drawing
                  PDF + DXF + STEP, BOM Excel, PO pack PDF (spec, BOM, accessories, guarantee, documents, all drawings), ZIP

Drawing numbers: FD-<fin die id>-<nn>. Every size is a rule in master data (EXAMPLE until you replace it): this is a design
proposal for your die maker to check, as every tool design of the software.
"""

from __future__ import annotations

import io
import json
import math
import zipfile
from datetime import date

from . import fin_design, fin_die, mould_db

STRIP_GAP_MM = "strip_gap_mm"


# ---------------------------------------------------------------- the design ----------

def stations(pattern: dict) -> list[dict]:
    out = [{"code": f"draw{i + 1}", "name": f"Draw {i + 1}", "kind": "draw"} for i in range(int(pattern["draw_steps"]))]
    out.append({"code": "pierce", "name": "Pierce & burr", "kind": "pierce"})
    for col, kind, name in (("iron_stations", "iron", "Ironing"), ("louver_stations", "louver", "Louver"),
                            ("slit_stations", "slit", "Slit / lance"), ("wave_stations", "wave", "Wave")):
        out += [{"code": f"{kind}{i + 1}", "name": name + (f" {i + 1}" if int(pattern[col]) > 1 else ""), "kind": kind}
                for i in range(int(pattern[col]))]
    out += [{"code": "reflare", "name": "Reflare", "kind": "reflare"}, {"code": "trim", "name": "Edge trim", "kind": "trim"},
            {"code": "pilot", "name": "Pilot", "kind": "pilot"}, {"code": "rowslit", "name": "Row slit", "kind": "rowslit"},
            {"code": "feed", "name": "Feed (hitch finger)", "kind": "feed"},
            {"code": "cutoff", "name": "Cut-off" + (" (rippled)" if int(pattern["rippled_cutoff"]) else ""), "kind": "cutoff"}]
    return out


def _hardness() -> dict:
    return {r["code"]: r.get("hardness") or "" for r in mould_db.tables()["tool_materials"]}


def build(spec: dict, fid: int | None = None, name: str = "Fin die") -> dict:
    """The fin die design of a spec: geometry, stations, die parts (with drawing numbers), BOM and the cost behind it."""
    s = fin_die.normalise(spec)
    die = fin_die.die_cost(s)
    rules = mould_db.sizing_rules(fin_die.PART_TYPE)
    R = lambda k: float(rules[k]["value"])
    g = die["die"]
    b = die["base"]
    st_len = max(g["feed_mm"], R("station_min_mm"))
    trim = float(fin_die._param("fin_edge_trim_mm")["value"])
    foil_w = g["foil_width_mm"]
    die_l, die_w = g["length_mm"], g["width_mm"]
    sts = stations(die["pattern"])
    for i, st in enumerate(sts):
        st["x0"] = R("die_end_mm") + i * st_len
        st["no"] = i + 1
    ph, sub_h, hold_h, strip_h, punch_l = b["clamp_plates_mm"], R("subdie_h_mm"), R("holder_h_mm"), R("stripper_h_mm"), R("punch_len_mm")
    hard = _hardness()
    grade = {l["element"]: l["grade"] for l in die["lines"]}
    qty = {l["element"]: l["quantity"] for l in die["lines"]}
    prefix = f"FD-{fid or 'NEW'}"
    parts: list[dict] = []

    def part(name, bom_el, shape, dims, q, notes=(), holes=None, std=""):
        mat = grade.get(bom_el) or (b.get("material") or "" if bom_el.startswith("Fin die set") else "")
        parts.append({"no": f"{len(parts) + 1:02d}", "drawing": f"{prefix}-{len(parts) + 1:02d}", "name": name, "bom": bom_el,
                      "shape": shape, "dims": dims, "qty": q, "material": mat, "hardness": hard.get(mat, ""), "notes": list(notes),
                      "holes": holes or [], "std": std})

    tol = fin_design.rule
    hole_note = f"{int(g['holes_per_stroke'])} holes = {s['die_rows']} rows × {s['progressions']} progressions, pitch {s['hole_pitch_mm']:g} {tol('pitch_tol', '±0.05')} × " \
                f"{s['row_pitch_mm']:g} {tol('pitch_tol', '±0.05')}" + (", staggered" if s["staggered"] else "")

    def grid(d):
        """Hole pattern of one stroke on a station plate (origin = plate lower-left), d = hole Ø."""
        pts = []
        x_off = (st_len - g["feed_mm"]) / 2
        for r in range(s["die_rows"]):
            st_off = s["hole_pitch_mm"] / 2 if s["staggered"] and r % 2 else 0
            y = (die_w - foil_w) / 2 + trim + (r + 0.5) * s["row_pitch_mm"]
            for p in range(s["progressions"]):
                pts.append((x_off + (p + 0.25) * s["hole_pitch_mm"] + st_off, y, d))
        return pts

    corners = lambda d: [(x, y, d) for x in (50, b["length_mm"] - 50) for y in (50, b["width_mm"] - 50)]
    part("Lower die plate (die set)", f"Fin die set {b['size_code']}", "plate", (b["length_mm"], b["width_mm"], ph), 1,
         ["Guide post bores Ø40 H7 at the 4 corners, 50 mm from the edges", "Grind both faces parallel " + str(tol("plate_flatness", "0.005"))],
         corners(40))
    part("Upper die plate (die set)", f"Fin die set {b['size_code']}", "plate", (b["length_mm"], b["width_mm"], ph), 1,
         ["Guide bush bores Ø52 H7 at the 4 corners, 50 mm from the edges"], corners(52))
    punch_kinds = {"draw": ("Draw punch", "Draw sub-die plate", s["hole_d_mm"] * 0.8), "pierce": ("Pierce & burring punch", "Pierce die button", fin_die._param("fin_pierce_factor")["value"] * s["hole_d_mm"]),
                   "iron": ("Ironing punch", "Pierce die button", s["hole_d_mm"]), "reflare": ("Reflare punch", "Draw sub-die plate", s["hole_d_mm"])}
    for st in sts:
        k = st["kind"]
        bom_sub = {"draw": "Draw sub-die plate", "pierce": "Pierce holder", "louver": "Louver punch & die set", "slit": "Slit (lance) punch & die set",
                   "wave": "Wave forming die (upper + lower)", "iron": "Pierce holder", "reflare": "Draw sub-die plate",
                   "trim": "Edge trim punch & die", "rowslit": "Row slit blade (upper + lower)", "cutoff": "Cut-off punch & die"}.get(k, "Stripper plate")
        holes = grid(punch_kinds[k][2] + 0.01) if k in punch_kinds else []
        part(f"Sub-die plate · station {st['no']} {st['name']}", bom_sub, "plate", (st_len, die_w, sub_h), 1,
             [hole_note + f", button holes Ø{punch_kinds[k][2]:.2f} {tol('die_opening_tol', '+0.005 / 0')}"] if holes else [], holes)
        st["subdie"] = parts[-1]["no"]
    part("Stripper plate (one per station)", "Stripper plate", "plate", (st_len, die_w, strip_h), len(sts),
         ["Punch clearance holes Ø(punch + 0.02)", hole_note])
    part("Punch holder plate (one per station)", "Drawing holder", "plate", (st_len, die_w, hold_h), len(sts),
         [f"Punch holes {tol('fit_punch', 'm5 / H6')}, position {tol('position_tol', '±0.005')}, jig ground", hole_note])
    for k, (pname, _btn, d) in punch_kinds.items():
        n = sum(1 for st in sts if st["kind"] == k)
        if n:
            part(pname, pname, "round", (d, punch_l), int(n * g["holes_per_stroke"]),
                 [f"Working Ø{d:.2f} {tol('punch_tol', '0 / −0.005')}", f"Finish {tol('finish_working', 'Ra 0.2')}", "Head Ø + 3 mm × 4 mm"])
    if any(st["kind"] == "pierce" for st in sts):
        d = punch_kinds["pierce"][2]
        part("Pierce die button", "Pierce die button", "round", (d + 8, sub_h), int(g["holes_per_stroke"]),
             [f"Opening Ø{d:.2f} {tol('die_opening_tol', '+0.005 / 0')}, land 2 mm, relief 1°", "Outside Ø press fit m5 in the sub-die plate"])
    for k, pname in (("louver", "Louver punch & die set"), ("slit", "Slit (lance) punch & die set")):
        if any(st["kind"] == k for st in sts):
            part(pname, pname, "plate", (s["hole_pitch_mm"], s["row_pitch_mm"], sub_h), int(qty.get(pname, 0)),
                 [f"Profile per the fin drawing ({k}s between the holes), wire cut and profile ground"])
    if any(st["kind"] == "wave" for st in sts):
        part("Wave forming die (upper / lower)", "Wave forming die (upper + lower)", "plate", (g["feed_mm"], die_w, sub_h), 2,
             ["Herringbone wave profile per the fin drawing"])
    part("Edge trim punch & die", "Edge trim punch & die", "blade", (st_len, 30, sub_h), 4, [f"Cuts {trim:g} mm each side of the strip"])
    part("Row slit blade (upper / lower)", "Row slit blade (upper + lower)", "blade", (st_len, 3, 40), int(2 * (s["die_rows"] - 1)),
         [f"Pitch {s['row_pitch_mm']:g} {tol('pitch_tol', '±0.05')}; adjustable 1 - {s['die_rows']} rows"])
    part("Cut-off punch & die", "Cut-off punch & die", "blade", (foil_w + 20, 40, 30), 2,
         ["Rippled edge per the wave" if int(die["pattern"]["rippled_cutoff"]) else "Straight blade, cuts at any length"])
    part("Pilot", "Pilots", "round", (s["hole_d_mm"] - 0.02, 40), int(2 * s["die_rows"]), ["Bought-out (Misumi / Punch)"], std="Misumi / Punch")
    part("Guide post Ø40 and bush (set)", "Springs, guide posts, bushes, screws (set)", "round", (40, 250), 4, ["Ball-bearing guide set, Japan make"], std="Japan make")
    return {"spec": s, "die": die, "stations": sts, "parts": parts, "name": name, "id": fid,
            "dims": {"die_l": die_l, "die_w": die_w, "station_len": st_len, "foil_w": foil_w, "trim": trim, "plate_h": ph,
                     "subdie_h": sub_h, "holder_h": hold_h, "stripper_h": strip_h, "punch_len": punch_l,
                     "base_l": b["length_mm"], "base_w": b["width_mm"], "shut_h": b["stack_height_mm"]},
            "grid": grid, "prefix": prefix}


# ---------------------------------------------------------------- 3D ----------

def solids(des: dict) -> list[dict]:
    """3D die parts at their places: [{name, no, kind, color, shape (placed), material, hardness, qty}]."""
    import cadquery as cq
    dd, s, g = des["dims"], des["spec"], des["die"]["die"]
    out = []
    pn = {p["name"]: p for p in des["parts"]}

    def add(name, shape, color, part_name=None, kind="made"):
        p = pn.get(part_name or name, {})
        out.append({"name": name, "no": p.get("no", ""), "kind": kind, "color": color, "shape": shape,
                    "material": p.get("material", ""), "hardness": p.get("hardness", ""), "qty": p.get("qty", 1)})
    box = lambda L, W, H, x, y, z: cq.Workplane("XY").box(L, W, H, centered=False).translate((x, y, z)).val()
    bx0, by0 = (dd["die_l"] - dd["base_l"]) / 2, (dd["die_w"] - dd["base_w"]) / 2
    z = 0.0
    add("Lower die plate (die set)", box(dd["base_l"], dd["base_w"], dd["plate_h"], bx0, by0, z), "shoe")
    z += dd["plate_h"]
    strip_z = z + dd["subdie_h"]
    top = strip_z + 2 + dd["stripper_h"] + dd["punch_len"] * 0.6 + dd["holder_h"]
    for st in des["stations"]:
        add(f"Sub-die plate · station {st['no']} {st['name']}", box(dd["station_len"] - 1, dd["die_w"], dd["subdie_h"], st["x0"], 0, z), "plate",
            next(p["name"] for p in des["parts"] if p["no"] == st["subdie"]))
        add(f"Stripper · station {st['no']}", box(dd["station_len"] - 1, dd["die_w"], dd["stripper_h"], st["x0"], 0, strip_z + 2), "hard",
            "Stripper plate (one per station)")
        add(f"Punch holder · station {st['no']}", box(dd["station_len"] - 1, dd["die_w"], dd["holder_h"], st["x0"], 0, top - dd["holder_h"]),
            "plate", "Punch holder plate (one per station)")
        pname = {"draw": "Draw punch", "pierce": "Pierce & burring punch", "iron": "Ironing punch", "reflare": "Reflare punch"}.get(st["kind"])
        if pname:
            d = pn[pname]["dims"][0]
            pts = [(st["x0"] + x, y) for x, y, _ in des["grid"](d)]
            punches = cq.Workplane("XY").workplane(offset=strip_z + 0.5).pushPoints(pts).circle(d / 2).extrude(top - strip_z - 0.5 - dd["holder_h"] / 2)
            add(f"{pname}s · station {st['no']}", punches.val(), "hard", pname)
        if st["kind"] == "rowslit":
            y0 = (dd["die_w"] - dd["foil_w"]) / 2 + dd["trim"]
            blades = cq.Workplane("XY").pushPoints([(st["x0"] + dd["station_len"] / 2, y0 + r * s["row_pitch_mm"]) for r in range(1, s["die_rows"])]) \
                .rect(dd["station_len"] * 0.7, 3).extrude(40).translate((0, 0, strip_z - 20))
            add(f"Row slit blades · station {st['no']}", blades.val(), "hard", "Row slit blade (upper / lower)")
        if st["kind"] == "cutoff":
            add("Cut-off punch", box(10, dd["foil_w"] + 20, 40, st["x0"] + dd["station_len"] / 2 - 5, (dd["die_w"] - dd["foil_w"]) / 2 - 10, strip_z + 1),
                "hard", "Cut-off punch & die")
    add("Upper die plate (die set)", box(dd["base_l"], dd["base_w"], dd["plate_h"], bx0, by0, top), "shoe")
    for cx, cy in ((bx0 + 50, by0 + 50), (bx0 + dd["base_l"] - 50, by0 + 50), (bx0 + 50, by0 + dd["base_w"] - 50),
                   (bx0 + dd["base_l"] - 50, by0 + dd["base_w"] - 50)):
        add("Guide post", cq.Workplane("XY").circle(20).extrude(top + dd["plate_h"]).translate((cx, cy, 0)).val(), "std",
            "Guide post Ø40 and bush (set)", "std")
    add("Fin strip (foil)", box(dd["die_l"], dd["foil_w"], max(g and s["foil_t_mm"], 0.3), 0, (dd["die_w"] - dd["foil_w"]) / 2, strip_z), "ref", kind="ref")
    return out


def _mesh(shape, size):
    from . import render3d
    return render3d.mesh(shape, tol=max(0.3, size / 150))


def step_bytes(des: dict) -> bytes:
    import cadquery as cq
    from .tool_design import step_bytes as sb
    asm = cq.Assembly(name=des["name"][:40] or "fin_die")
    for i, x in enumerate(solids(des)):
        asm.add(x["shape"], name=f"{i:03d}_{x['name'][:40]}".replace(" ", "_").replace("·", "-"))
    return sb(asm)


def stl_bytes(des: dict) -> bytes:
    from .outputs3d import stl_bytes as sb
    meshes = []
    for x in solids(des):
        bb = x["shape"].BoundingBox()
        meshes.append(_mesh(x["shape"], max(bb.xlen, bb.ylen, bb.zlen)))
    return sb(meshes, des["name"])


def viewer_html(des: dict) -> str:
    from .outputs3d import viewer_html as vh
    from .tool_design import COLORS
    parts = []
    for x in solids(des):
        bb = x["shape"].BoundingBox()
        v, t = _mesh(x["shape"], max(bb.xlen, bb.ylen, bb.zlen))
        parts.append({"item": x["no"] or "REF", "name": x["name"], "kind": x["kind"], "qty": x["qty"], "material": x["material"],
                      "hardness": x["hardness"], "std": "", "size": [round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1)],
                      "stock": None, "kg": None, "inr": None, "inr_note": "", "rgb": list(COLORS.get(x["color"], (0.6, 0.6, 0.6))),
                      "locs": [[0.0, 0.0, 0.0]], "moves": [""], "v": [round(float(a), 2) for a in v.reshape(-1)], "t": [int(a) for a in t.reshape(-1)]})
    data = {"title": f"{des['name']} · fin die {des['prefix']}", "part_code": des["prefix"], "rev": "-", "tool": des["name"],
            "tool_cost_inr": des["die"]["value_inr"], "parts": parts, "motion": None}
    return vh(data)


# ---------------------------------------------------------------- 2D drawings ----------

A3 = (420.0, 297.0)


def _title_rows(des: dict, p: dict | None) -> list[tuple[str, str]]:
    s = des["spec"]
    rows = [("Fin die", f"Ø{s['tube_od_mm']:g} × {s['die_rows']}R × {s['progressions']}P · {s['pattern']}"), ("Fin foil", f"{s['material']} {s['foil_t_mm']:g} mm")]
    if p:
        rows += [("Part", p["name"]), ("Qty", f"{p['qty']:g}"), ("Material", p["material"] or "-"), ("Hardness", p["hardness"] or "-")]
    return rows


class _Sheet:
    """One A3 landscape drawing on a reportlab canvas: frame, title block, a drawing area in model mm at a scale."""

    def __init__(self, c, des, title, drawing_no, p=None, sheet="1 / 1", notes=()):
        from reportlab.lib.units import mm
        from . import drawing_style
        self.c, self.mm = c, mm
        W, H = A3[0] * mm, A3[1] * mm
        c.setPageSize((W, H))
        c.setLineWidth(0.8)
        c.rect(8 * mm, 8 * mm, W - 16 * mm, H - 16 * mm)
        tb = drawing_style.pdf_title_block(W - 16 * mm, _title_rows(des, p), part_type=fin_die.PART_TYPE, sheet=sheet,
                                           drawing_no=drawing_no, rev="A", extra_notes=list(notes),
                                           general_tolerance=fin_design.rule("general_tolerance", "ISO 2768-mK"))
        _w, h = tb.wrapOn(c, W - 16 * mm, H)
        tb.drawOn(c, 8 * mm, 8 * mm)
        self.area = (14 * mm, 8 * mm + h + 8 * mm, W - 14 * mm, H - 16 * mm)         # x0, y0, x1, y1 in points
        c.setFont("Helvetica-Bold", 12)
        c.drawString(14 * mm, H - 14 * mm, title)
        c.setFont("Helvetica", 8)

    def fit(self, w, h, x0=None, y0=None, x1=None, y1=None):
        ax0, ay0, ax1, ay1 = (x0 or self.area[0], y0 or self.area[1], x1 or self.area[2], y1 or self.area[3])
        k = min((ax1 - ax0) / max(w, 1e-6), (ay1 - ay0) / max(h, 1e-6)) * 0.88
        ox = ax0 + ((ax1 - ax0) - w * k) / 2
        oy = ay0 + ((ay1 - ay0) - h * k) / 2
        return lambda x, y: (ox + x * k, oy + y * k), k

    def dim_h(self, P, x0, x1, y, text, off=10):
        c = self.c
        (a, b), (e, _f) = P(x0, y), P(x1, y)
        yy = b - off
        c.setLineWidth(0.3)
        c.line(a, b, a, yy - 2)
        c.line(e, b, e, yy - 2)
        c.line(a, yy, e, yy)
        c.drawCentredString((a + e) / 2, yy + 2, text)

    def dim_v(self, P, x, y0, y1, text, off=10):
        c = self.c
        (a, b), (_e, f) = P(x, y0), P(x, y1)
        xx = a - off
        c.setLineWidth(0.3)
        c.line(a, b, xx - 2, b)
        c.line(a, f, xx - 2, f)
        c.line(xx, b, xx, f)
        c.saveState()
        c.translate(xx - 2, (b + f) / 2)
        c.rotate(90)
        c.drawCentredString(0, 0, text)
        c.restoreState()


def _part_page(c, des, p, sheet):
    s = des["spec"]
    tol = fin_design.rule
    hardened = p["material"] in (fin_die.HAP, fin_die.SKH, fin_die.SK3)
    notes = p["notes"] + [f"Material {p['material'] or '-'} {p['hardness']}".strip()] + ([str(tol("heat_treat_note", ""))] if hardened else [])
    if p["std"]:
        notes = [f"Bought-out: {p['std']}"] + p["notes"]
    sh = _Sheet(c, des, f"{p['drawing']} · {p['name']}", p["drawing"], p, sheet, notes)
    x0, y0, x1, y1 = sh.area
    mid = x0 + (x1 - x0) * 0.62
    c.setLineWidth(0.6)
    if p["shape"] in ("plate", "blade"):
        L, W, H = p["dims"]
        P, k = sh.fit(L + H + 40, W + H + 40, x0, y0, x1 - 60, y1)        # top view + side view (right) + front view (below), one scale
        a, b = P(0, H + 30)
        c.rect(a, b, L * k, W * k)
        Pt = lambda x, y: P(x, y + H + 30)
        holes = p["holes"]
        if holes:
            for hx, hy, d in holes:
                cx, cy = Pt(hx, hy)
                c.circle(cx, cy, max(d * k / 2, 0.25), stroke=1, fill=0)
            hx, hy, d = holes[0]
            cx, cy = Pt(hx, hy)
            c.setFont("Helvetica", 7)
            c.drawString(cx + 4, cy - 10, f"{len(holes)} × Ø{d:.2f} {tol('die_opening_tol', '+0.005 / 0')}")
        c.setFont("Helvetica", 8)
        c.drawString(a, b + W * k + 4, "Top view")
        sh.dim_v(Pt, 0, 0, W, f"{W:g}")
        fa, fb = P(0, 0)                                                 # front view under the top view
        c.rect(fa, fb, L * k, H * k)
        sh.dim_h(P, 0, L, 0, f"{L:g}", off=8)
        sh.dim_v(P, 0, 0, H, f"{H:g} {tol('plate_thk_tol', '±0.01')}", off=8)
        sa, sb_ = P(L + 30, H + 30)                                      # side view right of the top view
        c.rect(sa, sb_, H * k, W * k)
        c.drawString(sa, sb_ + W * k + 4, "Side view")
    else:
        d, L = p["dims"]
        P, k = sh.fit(L + 8 + 3 * d, 3 * d, x0, y0, x1 - 60, y1)        # side view + end view, one scale
        a, b = P(0, d)
        c.rect(a, b, (L - 4) * k, d * k)
        ha, hb = P(L - 4, d - 1.5)
        c.rect(ha, hb, 4 * k, (d + 3) * k)
        c.drawString(a, b + (d + 3) * k + 6, "Side view")
        sh.dim_h(P, 0, L, d, f"{L:g}")
        sh.dim_v(P, 0, d, 2 * d, f"Ø{d:.2f} {tol('punch_tol', '0 / −0.005')}")
        cx, cy = P(L + 8 + 1.5 * d, 1.5 * d)
        c.circle(cx, cy, d * k / 2)
        c.circle(cx, cy, (d + 3) * k / 2)
        c.drawString(cx - 15, cy + (d + 3) * k / 2 + 6, "End view")
    c.setFont("Helvetica", 8)
    yy = y1 - 6
    for line in [f"Qty: {p['qty']:g}", f"Fin: Ø{s['tube_od_mm']:g}, collar Ø{s['hole_d_mm']:g} {tol('hole_tol', '±0.03')}",
                 f"Pitch {s['hole_pitch_mm']:g} × {s['row_pitch_mm']:g} {tol('pitch_tol', '±0.05')}"]:
        c.drawRightString(x1, yy, line)
        yy -= 11
    c.showPage()


def _strip_page(c, des, sheet="1 / 1"):
    s, dd = des["spec"], des["dims"]
    sts = des["stations"]
    sh = _Sheet(c, des, f"{des['prefix']}-00 · Strip / station layout", f"{des['prefix']}-00", None, sheet,
                [f"Feed {des['die']['die']['feed_mm']:g} mm per stroke; {len(sts)} stations of {dd['station_len']:g} mm",
                 f"Foil {dd['foil_w']:g} mm, edge trim {dd['trim']:g} mm each side"])
    c = sh.c
    L, W = dd["die_l"], dd["die_w"]
    P, k = sh.fit(L, W + 60)
    fy0 = (W - dd["foil_w"]) / 2
    a, b = P(0, fy0)
    c.setLineWidth(0.6)
    c.rect(a, b, L * k, dd["foil_w"] * k)
    for st in sts:
        xa, ya = P(st["x0"], 0)
        c.setLineWidth(0.3)
        c.setDash(2, 2)
        c.line(xa, ya, xa, ya + W * k)
        c.setDash()
        c.setFont("Helvetica-Bold", 6.5)
        c.saveState()
        c.translate(xa + dd["station_len"] * k / 2, ya + W * k + 4)
        c.rotate(30)
        c.drawString(0, 0, f"{st['no']} {st['name']}")
        c.restoreState()
        kind = st["kind"]
        pts = des["grid"](s["hole_d_mm"])
        for hx, hy, d in pts:
            cx, cy = P(st["x0"] + hx, hy)
            r = max(d * k / 2, 0.3)
            if kind == "draw":
                c.circle(cx, cy, r * (0.5 + 0.15 * int(st["code"][-1])), stroke=1, fill=0)
            elif kind in ("pierce", "iron", "reflare", "pilot"):
                c.circle(cx, cy, r, stroke=1, fill=1 if kind == "pierce" else 0)
            elif kind == "louver":
                c.line(cx - r, cy + r * 1.6, cx + r, cy + r * 1.6)
            elif kind == "slit":
                c.line(cx - r, cy + r * 1.6, cx + r, cy + r * 1.6)
                c.line(cx - r, cy + r * 1.9, cx + r, cy + r * 1.9)
        if kind == "trim":
            for yy in (fy0, fy0 + dd["foil_w"]):
                p1, p2 = P(st["x0"], yy), P(st["x0"] + dd["station_len"], yy)
                c.setLineWidth(1.2)
                c.line(*p1, *p2)
        if kind in ("rowslit", "feed", "cutoff"):
            for r in range(1, s["die_rows"]):
                yy = fy0 + dd["trim"] + r * s["row_pitch_mm"]
                p1, p2 = P(st["x0"], yy), P(L, yy)
                c.setLineWidth(0.15)
                c.line(*p1, *p2)
        if kind == "cutoff":
            p1, p2 = P(st["x0"] + dd["station_len"] / 2, fy0), P(st["x0"] + dd["station_len"] / 2, fy0 + dd["foil_w"])
            c.setLineWidth(1.4)
            c.line(*p1, *p2)
    c.setFont("Helvetica", 8)
    sh.dim_h(P, 0, L, 0, f"Die length {L:g}")
    sh.dim_v(P, 0, fy0, fy0 + dd["foil_w"], f"Foil {dd['foil_w']:g}")
    c.showPage()


def _fin_page(c, des, sheet="1 / 1"):
    s = des["spec"]
    tol = fin_design.rule
    L, W = s["fin_holes"] * s["hole_pitch_mm"], s["fin_rows"] * s["row_pitch_mm"]
    sh = _Sheet(c, des, f"{des['prefix']}-F · Fin (part)", f"{des['prefix']}-F", None, sheet,
                [f"Collar Ø{s['hole_d_mm']:g} {tol('hole_tol', '±0.03')} for tube Ø{s['tube_od_mm']:g}; collar height = fin pitch {25.4 / s['fpi']:.3f} mm ({s['fpi']:g} FPI)",
                 f"Foil {s['material']} {s['foil_t_mm']:g} mm; pattern {s['pattern']}"])
    c = sh.c
    P, k = sh.fit(L, W * 3)
    a, b = P(0, W)
    c.rect(a, b, L * k, W * k)
    for x, y in fin_design.fin_holes(s):
        cx, cy = P(x, W + y)
        c.circle(cx, cy, s["hole_d_mm"] * k / 2)
        c.circle(cx, cy, (s["hole_d_mm"] / 2 + s["foil_t_mm"]) * k + 0.3)
    sh.dim_h(P, 0, L, W, f"{L:g} ({s['fin_holes']} × {s['hole_pitch_mm']:g} {tol('pitch_tol', '±0.05')})")
    sh.dim_v(P, 0, W, 2 * W, f"{W:g} ({s['fin_rows']} × {s['row_pitch_mm']:g})")
    c.showPage()


def drawings_pdf(des: dict, which: str = "all") -> bytes:
    """which = all (strip, fin, every die part), strip, fin or parts."""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(A3[0] * 2.8346, A3[1] * 2.8346))
    c.setTitle(f"Design to Cost — fin die {des['name']} drawings")
    pages = (["strip"] if which in ("all", "strip") else []) + (["fin"] if which in ("all", "fin") else []) \
        + ([p for p in des["parts"]] if which in ("all", "parts") else [])
    n = len(pages)
    for i, pg in enumerate(pages, start=1):
        sheet = f"{i} / {n}"
        if pg == "strip":
            _strip_page(c, des, sheet)
        elif pg == "fin":
            _fin_page(c, des, sheet)
        else:
            _part_page(c, des, pg, sheet)
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------- DXF ----------

def _dxf_doc():
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.units = 4                                  # mm
    for name, col in (("OUTLINE", 7), ("HOLES", 1), ("CENTER", 3), ("DIM", 2), ("TEXT", 7)):
        doc.layers.add(name, color=col)
    return doc


def _dxf_out(doc) -> bytes:
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()


def part_dxf(des: dict, p: dict) -> bytes:
    from . import drawing_style
    doc = _dxf_doc()
    msp = doc.modelspace()
    if p["shape"] in ("plate", "blade"):
        L, W, H = p["dims"]
        msp.add_lwpolyline([(0, 0), (L, 0), (L, W), (0, W)], close=True, dxfattribs={"layer": "OUTLINE"})
        for hx, hy, d in p["holes"]:
            msp.add_circle((hx, hy), d / 2, dxfattribs={"layer": "HOLES"})
        msp.add_lwpolyline([(0, -H - 30), (L, -H - 30), (L, -30), (0, -30)], close=True, dxfattribs={"layer": "OUTLINE"})
        dims = [(f"{L:g}", (L / 2, W + 8)), (f"{W:g}", (-25, W / 2)), (f"T {H:g}", (L + 8, -H / 2 - 30))]
        w, h = L + 60, W + H + 80
    else:
        d, L = p["dims"]
        msp.add_lwpolyline([(0, 0), (L, 0), (L, d), (0, d)], close=True, dxfattribs={"layer": "OUTLINE"})
        msp.add_circle((L + 3 * d, d / 2), d / 2, dxfattribs={"layer": "OUTLINE"})
        dims = [(f"{L:g}", (L / 2, d + 5)), (f"Ø{d:.2f}", (L + 3 * d, d + 5))]
        w, h = L + 5 * d + 40, d + 40
    for text, (x, y) in dims:
        msp.add_text(text, dxfattribs={"layer": "DIM", "height": 3.5}).set_placement((x, y))
    for i, note in enumerate(p["notes"][:6]):
        msp.add_text(f"{i + 1}. {note}"[:120], dxfattribs={"layer": "TEXT", "height": 3}).set_placement((0, -(p["dims"][2] if len(p["dims"]) == 3 else 0) - 50 - i * 6))
    drawing_style.dxf_frame(doc, msp, max(w, 420), max(h, 297), p["name"], _title_rows(des, p), part_type=fin_die.PART_TYPE,
                            drawing_no=p["drawing"], rev="A", margin=40)
    return _dxf_out(doc)


def strip_dxf(des: dict) -> bytes:
    from . import drawing_style
    s, dd = des["spec"], des["dims"]
    doc = _dxf_doc()
    msp = doc.modelspace()
    L, W = dd["die_l"], dd["die_w"]
    fy0 = (W - dd["foil_w"]) / 2
    msp.add_lwpolyline([(0, fy0), (L, fy0), (L, fy0 + dd["foil_w"]), (0, fy0 + dd["foil_w"])], close=True, dxfattribs={"layer": "OUTLINE"})
    for st in des["stations"]:
        msp.add_line((st["x0"], 0), (st["x0"], W), dxfattribs={"layer": "CENTER"})
        msp.add_text(f"{st['no']} {st['name']}", dxfattribs={"layer": "TEXT", "height": 5}).set_placement((st["x0"] + 2, W + 8))
        if st["kind"] in ("draw", "pierce", "iron", "reflare", "pilot"):
            for hx, hy, d in des["grid"](s["hole_d_mm"]):
                msp.add_circle((st["x0"] + hx, hy), d / 2, dxfattribs={"layer": "HOLES"})
    drawing_style.dxf_frame(doc, msp, L, W + 40, "Strip / station layout", _title_rows(des, None), part_type=fin_die.PART_TYPE,
                            drawing_no=f"{des['prefix']}-00", rev="A", margin=40)
    return _dxf_out(doc)


def dxf_zip(des: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{des['prefix']}-00_strip_layout.dxf", strip_dxf(des))
        z.writestr(f"{des['prefix']}-F_fin.dxf", fin_design.fin_dxf(des["spec"]))
        for p in des["parts"]:
            z.writestr(f"{p['drawing']}_{_safe(p['name'])}.dxf", part_dxf(des, p))
    return buf.getvalue()


def _safe(text: str) -> str:
    return "".join(ch if (ch.isascii() and ch.isalnum()) or ch in "-_" else "_" for ch in text).strip("_")[:50]


# ---------------------------------------------------------------- BOM and PO pack ----------

def bom_rows(des: dict) -> list[dict]:
    d = des["die"]
    by_bom = {}
    for p in des["parts"]:
        by_bom.setdefault(p["bom"], []).append(p["drawing"])
    rows = []
    for i, line in enumerate(d["lines"], start=1):
        rows.append({"pos": i, "element": line["element"], "qty": line["quantity"], "grade": line["grade"], "make": line["make"],
                     "hardness": _hardness().get(line["grade"], ""), "drawings": ", ".join(by_bom.get(line["element"], [])),
                     "weight_kg": line["weight_each_kg"], "total": line["total"], "category": line["category"]})
    return rows


def bom_xlsx(des: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from .table_set import HEADER_FILL
    wb = Workbook()
    ws = wb.active
    ws.title = "Die BOM"
    head = ["Pos", "Element", "Category", "Qty", "Grade", "Hardness", "Make", "Drawings", "Weight each kg", f"Total ({des['die']['currency']})"]
    ws.append(head)
    for r in bom_rows(des):
        ws.append([r["pos"], r["element"], r["category"], r["qty"], r["grade"], r["hardness"], r["make"], r["drawings"], r["weight_kg"], r["total"]])
    ws2 = wb.create_sheet("Drawings")
    ws2.append(["Drawing", "Part", "Qty", "Material", "Hardness", "Size (mm)", "Notes"])
    ws2.append([f"{des['prefix']}-00", "Strip / station layout", 1, "", "", "", ""])
    ws2.append([f"{des['prefix']}-F", "Fin (part)", "", des["spec"]["material"], "", "", ""])
    for p in des["parts"]:
        ws2.append([p["drawing"], p["name"], p["qty"], p["material"], p["hardness"], " × ".join(f"{x:g}" for x in p["dims"]), "; ".join(p["notes"])])
    ws3 = wb.create_sheet("Stations")
    ws3.append(["Station", "Name", "From die entry (mm)"])
    for st in des["stations"]:
        ws3.append([st["no"], st["name"], st["x0"]])
    for w in (ws, ws2, ws3):
        for c in w[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
        w.column_dimensions["B"].width = 44
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def po_pack_pdf(des: dict) -> bytes:
    """Purchase order pack: technical specification, BOM, accessories, guarantee, documents; then every drawing."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
    from . import drawing_style
    from .pdf_report import _example_banner, _table, _theme
    theme, ss = _theme(), getSampleStyleSheet()
    st = {"k": ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8),
          "h1": ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=16, alignment=0)}
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=11, spaceBefore=8, spaceAfter=4)
    cell = ParagraphStyle("c", parent=ss["Normal"], fontSize=8, leading=10)
    P = lambda x: Paragraph(str(x).replace("&", "&amp;").replace("<", "&lt;"), cell)
    s, d, dd = des["spec"], des["die"], des["dims"]
    prm = lambda k: fin_die._param(k)["value"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Design to Cost — fin die PO pack {des['name']}")
    W = A4[0] - 30 * mm
    press = d["trial"]["machine"]
    story = [drawing_style.pdf_header(st, "PURCHASE ORDER PACK · FIN DIE", f"Ø{s['tube_od_mm']:g} × {s['die_rows']}R × {s['progressions']}P "
                                      f"({s['row_pitch_mm']:g} × {s['hole_pitch_mm']:g} mm) {s['pattern']} fin die"),
             Paragraph(f"{des['name']} · drawing set {des['prefix']} · {date.today().isoformat()}", cell)]
    if d["example"]["any"]:
        story += [Spacer(1, 2 * mm), _example_banner(ss, "Sizes and rules are EXAMPLE master data: the die maker confirms them.")]
    spec_rows = [["Item", "Specification"], ["1. Object", f"Fin die for the fin press {press['machine_id'] if press else '-'} ({press['name'] if press else ''})"],
                 ["2. Fin pattern", f"{s['pattern']}; hole (collar) Ø{s['hole_d_mm']:g} {fin_design.rule('hole_tol', '±0.03')}; "
                                     f"{'staggered' if s['staggered'] else 'in line'}; hole pitch {s['hole_pitch_mm']:g}, row pitch {s['row_pitch_mm']:g} "
                                     f"{fin_design.rule('pitch_tol', '±0.05')}; fin pitch {s['fpi']:g} FPI"],
                 ["3. Material", f"{s['material']}, thickness {s['foil_t_mm']:g} mm, width {dd['foil_w']:g} mm"],
                 ["4. Die structure", "Progressive draw type: " + " → ".join(x["name"] for x in des["stations"])],
                 ["   Die size", f"{dd['die_l']:g} × {dd['die_w']:g} mm, die set {d['base']['size_code']} ({dd['base_l']:g} × {dd['base_w']:g} mm), "
                                f"shut height ≈ {dd['shut_h']:g} mm; feed {d['die']['feed_mm']:g} mm; {int(d['die']['holes_per_stroke'])} holes per stroke"],
                 ["   Cutting parts", "; ".join(sorted({f"{p['name']}: {p['material']} {p['hardness']}".strip() for p in des["parts"]
                                                        if p["material"] and p["shape"] != "plate" and not p["std"]}))],
                 ["5. Trial material", f"{prm('trials'):g} try-outs × {prm('trial_shots_each'):,.0f} strokes, foil supplied by the buyer"],
                 ["6. Fin oil", "YBL evaporative fin oil, supplied by the buyer"],
                 ["7. Guarantee", f"{prm('fin_die_life_strokes'):,.0f} strokes after the trial; cutting parts {prm('fin_regrind_strokes'):,.0f} strokes per regrind"],
                 ["8. Documents", "Operating manual; detail drawings of the consumable parts (punches, buttons, slit blades, edge trim, cut-off); this drawing set"],
                 ["9. Accessories", "; ".join(f"{l['element']} × {l['quantity']:g}" for l in d["lines"] if l["element"].startswith("Spare"))],
                 ["10. Standard parts", "Springs, guide posts, bushes, screws: Japan make (or equal, to be agreed)"]]
    story += [Paragraph("Technical specification", h2), _table([[P(a), P(b)] for a, b in spec_rows], theme, [38 * mm, W - 38 * mm]),
              PageBreak(), Paragraph("Bill of materials", h2),
              _table([["Pos", "Element", "Qty", "Grade", "Hardness", "Drawing"]] +
                     [[r["pos"], P(r["element"]), f"{r['qty']:g}", P(r["grade"]), P(r["hardness"]), P(r["drawings"])] for r in bom_rows(des)],
                     theme, [10 * mm, 62 * mm, 14 * mm, 40 * mm, 26 * mm, W - 152 * mm]),
              Paragraph("Drawings in this pack", h2),
              _table([["Drawing", "Title"], [f"{des['prefix']}-00", "Strip / station layout"], [f"{des['prefix']}-F", "Fin (part)"]] +
                     [[p["drawing"], P(p["name"])] for p in des["parts"]], theme, [30 * mm, W - 30 * mm]),
              Spacer(1, 6 * mm),
              _table([[P("Buyer: for and on behalf of"), P("Die maker: for and on behalf of")], [P("Date / signature / stamp"), P("Date / signature / stamp")]],
                     theme, [W / 2, W / 2])]
    doc.build(story)
    out = PdfWriter()
    for blob in (buf.getvalue(), drawings_pdf(des)):
        for page in PdfReader(io.BytesIO(blob)).pages:
            out.add_page(page)
    res = io.BytesIO()
    out.write(res)
    return res.getvalue()


def all_zip(des: dict) -> bytes:
    buf = io.BytesIO()
    n = _safe(des["name"]) or des["prefix"]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{n}_PO_pack.pdf", po_pack_pdf(des))
        z.writestr(f"{n}_drawings.pdf", drawings_pdf(des))
        z.writestr(f"{n}_BOM.xlsx", bom_xlsx(des))
        z.writestr(f"{n}_die.step", step_bytes(des))
        z.writestr(f"{n}_die.stl", stl_bytes(des))
        z.writestr(f"{n}_3D_viewer.html", viewer_html(des))
        z.writestr(f"{n}_fin.step", fin_design.fin_step(des["spec"]))
        with zipfile.ZipFile(io.BytesIO(dxf_zip(des))) as dz:
            for name in dz.namelist():
                z.writestr(f"DXF/{name}", dz.read(name))
        z.writestr("design.json", json.dumps({"spec": des["spec"], "stations": [{k: v for k, v in st.items()} for st in des["stations"]],
                                              "parts": [{k: v for k, v in p.items() if k != "holes"} | {"holes": len(p["holes"])} for p in des["parts"]]},
                                             default=str, indent=1))
    return buf.getvalue()


def summary(des: dict) -> dict:
    return {"prefix": des["prefix"], "stations": [{k: st[k] for k in ("no", "code", "name", "kind", "x0")} for st in des["stations"]],
            "parts": [{k: p[k] for k in ("no", "drawing", "name", "qty", "material", "hardness", "dims", "notes", "std")} | {"holes": len(p["holes"])}
                      for p in des["parts"]],
            "dims": des["dims"], "die_cost_inr": des["die"]["value_inr"], "press": (des["die"]["trial"]["machine"] or {}).get("machine_id"),
            "warnings": des["die"]["warnings"], "example": des["die"]["example"]["any"], "spec": des["spec"]}


__all__ = ["build", "summary", "drawings_pdf", "strip_dxf", "part_dxf", "dxf_zip", "step_bytes", "stl_bytes", "viewer_html",
           "bom_xlsx", "po_pack_pdf", "all_zip", "math", "STRIP_GAP_MM"]
