"""Fin die design from the part file (roadmap stage 58).

    part file (STEP, else DXF or PDF) + RM grade
        -> fin geometry read from the file (tube / collar Ø, row pitch, hole pitch, fin rows, holes per fin, stagger,
           thickness, fin pitch → FPI, pattern hint), shown for you to confirm or correct
        -> die size proposed from the press: rows across the strip = whole fins in the press foil width × fin_foil_use_pct,
           progressions by tube Ø (Design rules fin), both changeable
        -> the fin die design (fin_die_draw.py): strip layout, 3D die, detail drawing of every die part, fin drawing,
           BOM, PO pack, CAD files

A STEP and a DXF are measured exactly; a PDF is read from its text (vector drawing with dimensions as text) and every value
found there is marked 'check'. A scanned PDF has no text: you type the values. Nothing read is used before you confirm it.
"""

from __future__ import annotations

import io
import math
import re
import tempfile
from collections import Counter
from pathlib import Path

from . import fin_die, mould_db

EXAMPLE = "EXAMPLE - typical fin die practice: replace with your toolroom's value"
# Design rules of part type fin (stage 58): proposal of the die size and drawing tolerances (EXAMPLE until replaced)
RULES = [
    ("fin_foil_use_pct", 80, "", "%", "Share of the press foil width the die uses (rows across the strip proposed from it; your 66-row die: 848 of 1080 mm)"),
    ("fin_tube_small_mm", 5.5, "", "mm", "Tube Ø up to this: progressions fin_prog_small"),
    ("fin_tube_mid_mm", 7.5, "", "mm", "Tube Ø up to this: progressions fin_prog_mid, above: fin_prog_large"),
    ("fin_prog_small", 4, "", "holes", "Progressions per stroke for small tubes (Ø5: 4P as your die)"),
    ("fin_prog_mid", 3, "", "holes", "Progressions per stroke for Ø7 tubes"),
    ("fin_prog_large", 2, "", "holes", "Progressions per stroke for Ø9.52 tubes and larger"),
    ("general_tolerance", None, "ISO 2768-mK", "", "General tolerance of the fin die drawings"),
    ("hole_tol", None, "±0.03", "mm", "Fin hole (collar) Ø tolerance (your spec: Ø5.2 ±0.03)"),
    ("pitch_tol", None, "±0.05", "mm", "Hole pitch and row pitch tolerance (your spec: ±0.05)"),
    ("punch_tol", None, "0 / −0.005", "mm", "Punch working Ø"),
    ("die_opening_tol", None, "+0.005 / 0", "mm", "Die button opening"),
    ("position_tol", None, "±0.005", "mm", "Position of punch and button holes (jig ground)"),
    ("plate_thk_tol", None, "±0.01", "mm", "Plate thickness"),
    ("plate_flatness", None, "0.005", "mm", "Flatness of sub-die and stripper plates"),
    ("fit_punch", None, "m5 / H6", "", "Punch in holder"),
    ("finish_working", None, "Ra 0.2", "", "Working surfaces of punches and buttons"),
    ("heat_treat_note", None, "Vacuum harden and temper HSS / powder steel 3 times; stress relieve before wire cut", "", "Heat treatment note"),
]


class ReadError(ValueError):
    pass


def seed() -> int:
    """Add the fin Design rules that are missing (existing rows are never changed)."""
    d = mould_db.tables()
    have = {(r["part_type"], r["parameter"]) for r in d["design_rules"]}
    add = [{"part_type": fin_die.PART_TYPE, "parameter": k, "value": v, "text": text, "unit": unit, "description": f"{desc} (stage 58)",
            "is_example": True} for k, v, text, unit, desc in RULES if (fin_die.PART_TYPE, k) not in have]
    if add:
        d["design_rules"] += add
        mould_db.write(d)
    return len(add)


def rule(name: str, default=None):
    r = mould_db.design_rules(fin_die.PART_TYPE).get(name)
    if r is None:
        return default
    return r["text"] if r["text"] else r["value"]


# ---------------------------------------------------------------- reading the part ----------

def _grid(values: list[float], tol: float) -> list[float]:
    """Distinct coordinates (clustered within tol), sorted."""
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _pitch(coords: list[float]) -> float | None:
    if len(coords) < 2:
        return None
    gaps = [round(b - a, 3) for a, b in zip(coords, coords[1:]) if b - a > 0.05]
    return Counter(gaps).most_common(1)[0][0] if gaps else None


def _from_centres(centres: list[tuple[float, float]], hole_d: float) -> dict:
    """Fin rows, row pitch, hole pitch, holes per fin and stagger from the hole centres (u = long side, v = short side)."""
    us, vs = [c[0] for c in centres], [c[1] for c in centres]
    span_u, span_v = max(us) - min(us), max(vs) - min(vs)
    if span_v > span_u:                                    # long side first
        centres = [(v, u) for u, v in centres]
        us, vs = vs, us
    tol = max(0.2, hole_d / 4)
    rows_v = _grid(vs, tol)
    row_pitch = _pitch(rows_v)
    per_row = [sorted(u for u, v in centres if abs(v - rv) <= tol) for rv in rows_v]
    hole_pitch = _pitch(per_row[0]) if per_row and len(per_row[0]) > 1 else None
    stagger = False
    if len(per_row) > 1 and hole_pitch and per_row[1]:
        off = (per_row[1][0] - per_row[0][0]) % hole_pitch
        stagger = abs(off - hole_pitch / 2) < hole_pitch / 4
    return {"fin_rows": len(rows_v), "row_pitch_mm": row_pitch, "hole_pitch_mm": hole_pitch,
            "fin_holes": max((len(r) for r in per_row), default=0), "staggered": stagger}


def _group(circles: list[tuple[float, float, float]]) -> tuple[dict, list[tuple[float, float]]]:
    """Concentric circles (hole, collar) grouped by centre: {key: [diameters]} and the exact mean centre of each group."""
    groups: dict[tuple, list] = {}
    for u, v, d in circles:
        key = next((k for k in groups if abs(k[0] - u) < 0.05 and abs(k[1] - v) < 0.05), (u, v))
        groups.setdefault(key, []).append((u, v, d))
    by_centre = {k: [c[2] for c in g] for k, g in groups.items()}
    exact = [(sum(c[0] for c in g) / len(g), sum(c[1] for c in g) / len(g)) for g in groups.values()]
    return by_centre, exact


def read_step(path: str) -> dict:
    import cadquery as cq
    shape = cq.importers.importStep(path).val()
    bb = shape.BoundingBox()
    dims = {"x": bb.xlen, "y": bb.ylen, "z": bb.zlen}
    normal = min(dims, key=dims.get)                       # the fin plate lies across its thinnest direction
    axes = [a for a in "xyz" if a != normal]
    cyl = []
    tilted = 0
    for f in shape.Faces():
        gt = f.geomType()
        if gt == "CYLINDER":
            s = f._geomAdaptor().Cylinder()
            ax, loc = s.Axis().Direction(), s.Location()
            d = {"x": abs(ax.X()), "y": abs(ax.Y()), "z": abs(ax.Z())}
            if d[normal] > 0.95:                            # holes and collars run across the plate
                p = {"x": loc.X(), "y": loc.Y(), "z": loc.Z()}
                cyl.append((p[axes[0]], p[axes[1]], 2 * s.Radius()))
        elif gt == "PLANE":
            n = f.normalAt()
            c = abs({"x": n.x, "y": n.y, "z": n.z}[normal])
            if 0.2 < c < 0.97:                              # tilted faces: louvers, lances, waves
                tilted += 1
    if not cyl:
        raise ReadError("No round holes across the fin plate were found in this STEP file: is it a fin? Type the values.")
    by_centre, exact = _group(cyl)
    diam = sorted({round(min(ds), 3) for ds in by_centre.values()})
    hole_d = Counter(round(min(ds), 2) for ds in by_centre.values()).most_common(1)[0][0]
    outer = [max(ds) for ds in by_centre.values() if max(ds) - min(ds) > 1e-3]
    wall = (Counter(round((max(ds) - min(ds)) / 2, 3) for ds in by_centre.values() if max(ds) - min(ds) > 1e-3).most_common(1)[0][0]
            if outer else None)
    grid = _from_centres(exact, hole_d)
    long_side, short_side = sorted((dims[axes[0]], dims[axes[1]]), reverse=True)
    t = wall if wall else dims[normal]
    collar_h = dims[normal] if wall else None
    out = {"source": "STEP", "hole_d_mm": round(hole_d, 3), "tube_od_mm": None, "foil_t_mm": round(t, 4),
           "fin_l_mm": round(long_side, 2), "fin_w_mm": round(short_side, 2), "holes": len(by_centre), **grid,
           "collar_h_mm": round(collar_h, 3) if collar_h else None,
           "fpi": round(25.4 / collar_h, 1) if collar_h else None,
           "pattern": "louver" if tilted >= 4 else "plain", "pattern_faces": tilted, "diameters": diam[:6],
           "check": ["tube_od_mm", "pattern"] + ([] if collar_h else ["fpi"]) + ([] if wall else ["foil_t_mm"])}
    return out


def read_dxf(path: str) -> dict:
    import ezdxf
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    circles = [(e.dxf.center.x, e.dxf.center.y, 2 * e.dxf.radius) for e in msp.query("CIRCLE")]
    if not circles:
        raise ReadError("No circles (holes) in this DXF: draw the fin with its holes as circles, or type the values.")
    by_centre, exact = _group(circles)
    hole_d = Counter(round(min(ds), 2) for ds in by_centre.values()).most_common(1)[0][0]
    xs, ys = [], []
    for e in msp.query("LINE LWPOLYLINE POLYLINE"):
        pts = [e.dxf.start, e.dxf.end] if e.dxftype() == "LINE" else list(e.vertices() if e.dxftype() == "POLYLINE" else e.get_points("xy"))
        for p in pts:
            p = getattr(p, "dxf", None) and p.dxf.location or p
            xs.append(float(p[0]))
            ys.append(float(p[1]))
    grid = _from_centres(exact, hole_d)
    sides = sorted(((max(xs) - min(xs)) if xs else 0, (max(ys) - min(ys)) if ys else 0), reverse=True)
    return {"source": "DXF", "hole_d_mm": round(hole_d, 3), "tube_od_mm": None, "foil_t_mm": None, "fin_l_mm": round(sides[0], 2),
            "fin_w_mm": round(sides[1], 2), "holes": len(by_centre), **grid, "fpi": None, "pattern": None,
            "check": ["tube_od_mm", "foil_t_mm", "fpi", "pattern"]}


_NUM = r"(\d+(?:[.,]\d+)?)"


def read_pdf(path: str) -> dict:
    from pypdf import PdfReader
    text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    if not text.strip():
        raise ReadError("This PDF has no text (a scan): type the fin values.")
    t = text.replace(",", ".")
    num = lambda pats: next((float(m.group(1)) for p in pats for m in [re.search(p, t, re.I)] if m), None)
    out = {"source": "PDF",
           "hole_d_mm": num([r"(?:hole|collar)[^\n\d]{0,25}[Øφ⌀]?\s*" + _NUM, r"[Øφ⌀]\s*" + _NUM + r"\s*(?:±|\+)"]),
           "tube_od_mm": num([r"tube[^\n\d]{0,25}[Øφ⌀]?\s*" + _NUM, r"[Øφ⌀]\s*" + _NUM + r"\s*[x×*]\s*\d+\s*R"]),
           "row_pitch_mm": num([r"(?:row pitch|between rows|row distance)[^\n\d]{0,25}" + _NUM, r"\(\s*" + _NUM + r"\s*[x×*]\s*\d+(?:\.\d+)?\s*(?:mm)?\s*\)"]),
           "hole_pitch_mm": num([r"(?:hole pitch|between holes|step pitch|pitch)[^\n\d]{0,25}" + _NUM,
                                 r"\(\s*\d+(?:\.\d+)?\s*[x×*]\s*" + _NUM + r"\s*(?:mm)?\s*\)"]),
           "foil_t_mm": num([r"(?:thickness|thk|t\s*=)[^\n\d]{0,15}" + _NUM]),
           "fpi": num([r"FPI[^\n\d]{0,10}" + _NUM, _NUM + r"\s*FPI"]),
           "fin_rows": None, "fin_holes": None, "staggered": bool(re.search(r"stagger", t, re.I)),
           "pattern": next((p for p in fin_die.PATTERNS if re.search(p, t, re.I)), None)}
    rows = re.search(r"[Øφ⌀]?\s*\d+(?:\.\d+)?\s*[x×*]\s*(\d+)\s*R", t)
    out["die_rows_text"] = int(rows.group(1)) if rows else None
    out["check"] = [k for k in ("hole_d_mm", "tube_od_mm", "row_pitch_mm", "hole_pitch_mm", "foil_t_mm", "fpi", "fin_rows", "fin_holes", "pattern")]
    if not any(out[k] for k in ("hole_d_mm", "row_pitch_mm", "hole_pitch_mm")):
        raise ReadError("No fin dimensions found in the PDF text: type the fin values.")
    return out


def read_part(content: bytes, name: str) -> dict:
    """Fin geometry from a part file; every value is a proposal for you to confirm."""
    ext = Path(name).suffix.lower()
    if ext in (".dwg",):
        raise ReadError("DWG is a closed format: save the drawing as DXF (or export a STEP) and upload that.")
    readers = {".step": read_step, ".stp": read_step, ".dxf": read_dxf, ".pdf": read_pdf}
    if ext not in readers:
        raise ReadError("Upload the fin as STEP (.step / .stp), DXF or PDF.")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / f"part{ext}"
        p.write_bytes(content)
        try:
            out = readers[ext](str(p))
        except ReadError:
            raise
        except Exception as exc:  # noqa: BLE001 - a broken file is reported, not a crash
            raise ReadError(f"Could not read {name}: {exc}") from None
    if not out.get("tube_od_mm") and out.get("hole_d_mm"):
        out["tube_od_mm"] = tube_from_hole(out["hole_d_mm"])
    out["file_name"] = name
    return out


TUBES = (4.0, 5.0, 6.35, 7.0, 7.94, 9.52, 12.7, 15.88)


def tube_from_hole(hole_d: float) -> float:
    """Largest standard tube Ø that fits the collar (the collar is a little bigger than the tube before expansion)."""
    fit = [t for t in TUBES if t <= hole_d]
    return fit[-1] if fit else round(hole_d, 2)


def to_spec(read: dict, base: dict | None = None) -> dict:
    """Spec fields filled from what was read (only values found), on top of base."""
    s = dict(base or fin_die.default_spec())
    for k in ("tube_od_mm", "hole_d_mm", "row_pitch_mm", "hole_pitch_mm", "foil_t_mm", "fpi", "fin_rows", "fin_holes"):
        if read.get(k):
            s[k] = read[k]
    if read.get("pattern") in fin_die.PATTERNS:
        s["pattern"] = read["pattern"]
    if "staggered" in read:
        s["staggered"] = bool(read["staggered"])
    return s


# ---------------------------------------------------------------- die size from the press ----------

def propose(spec: dict) -> dict:
    """Rows across the strip and progressions proposed for the press (Design rules fin); you may change both."""
    s = fin_die.normalise(spec)
    want = s["press"] if s["press"] and s["press"] != "auto" else fin_die.default_press()
    line = fin_die.press_rows().get(want)
    if not line:
        raise fin_die.FinDieError(f"Press '{want}' is not in Fin presses.")
    use = float(rule("fin_foil_use_pct", 80))
    trim = float(fin_die._param("fin_edge_trim_mm")["value"])
    usable = line["max_foil_width_mm"] * use / 100 - 2 * trim
    rows = int(usable // s["row_pitch_mm"])
    rows -= rows % s["fin_rows"]                            # whole fins across the strip
    rows = max(rows, s["fin_rows"])
    tube = s["tube_od_mm"]
    prog = int(rule("fin_prog_small", 4) if tube <= float(rule("fin_tube_small_mm", 5.5)) else
               rule("fin_prog_mid", 3) if tube <= float(rule("fin_tube_mid_mm", 7.5)) else rule("fin_prog_large", 2))
    width = rows * s["row_pitch_mm"] + 2 * trim
    return {"press": want, "die_rows": rows, "progressions": prog, "foil_width_mm": round(width, 1),
            "how": (f"{line['max_foil_width_mm']:g} mm foil width of {want} × {use:g} % (fin_foil_use_pct) − 2 × {trim:g} mm edge trim "
                    f"= {usable:.1f} mm ÷ {s['row_pitch_mm']:g} mm row pitch = {rows} rows (whole fins of {s['fin_rows']} rows); "
                    f"progressions {prog} for tube Ø{tube:g} (Design rules fin_prog_*)")}


# ---------------------------------------------------------------- the fin as a 3D model ----------

def fin_holes(s: dict) -> list[tuple[float, float]]:
    """Hole centres of one fin: (along the fin length, across its width), staggered rows."""
    pts = []
    for r in range(int(s["fin_rows"])):
        off = s["hole_pitch_mm"] / 2 if s.get("staggered", True) and r % 2 else 0.0
        for h in range(int(s["fin_holes"])):
            pts.append((s["hole_pitch_mm"] / 4 + off + h * s["hole_pitch_mm"], s["row_pitch_mm"] / 2 + r * s["row_pitch_mm"]))
    return pts


def fin_solid(spec: dict, collars: bool = True):
    """The fin plate with its collared holes (used for the fin STEP / drawing, and as a test part)."""
    import cadquery as cq
    s = fin_die.normalise(spec)
    L, W, t = s["fin_holes"] * s["hole_pitch_mm"], s["fin_rows"] * s["row_pitch_mm"], s["foil_t_mm"]
    pts = fin_holes(s)
    d = s["hole_d_mm"]
    plate = cq.Workplane("XY").box(L, W, t, centered=False)
    if collars:
        h = 25.4 / s["fpi"]
        ring = (cq.Workplane("XY").pushPoints(pts).circle(d / 2 + t).circle(d / 2).extrude(h))
        plate = plate.union(ring)
    plate = plate.faces(">Z").workplane(origin=(0, 0, 0)).pushPoints(pts).hole(d)
    return plate.val()


def fin_step(spec: dict) -> bytes:
    from .tool_design import step_bytes
    return step_bytes(fin_solid(spec))


def fin_dxf(spec: dict) -> bytes:
    """2D fin outline and holes (also a test part for the DXF reader)."""
    import ezdxf
    s = fin_die.normalise(spec)
    L, W = s["fin_holes"] * s["hole_pitch_mm"], s["fin_rows"] * s["row_pitch_mm"]
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (L, 0), (L, W), (0, W)], close=True)
    for x, y in fin_holes(s):
        msp.add_circle((x, y), s["hole_d_mm"] / 2)
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()


__all__ = ["seed", "read_part", "to_spec", "propose", "fin_solid", "fin_step", "fin_dxf", "ReadError", "math"]
