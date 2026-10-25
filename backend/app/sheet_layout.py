"""Sheet-metal tools II (roadmap stage 10): flat pattern, strip layout and the tool drawing pack.

    flat pattern   a flat part: its real outline and holes (planar face edges); a bent part: the developed
                   rectangle from the blank estimate (bend lines and hole positions need an unfolder, see README)
    strip layout   progressive die: blank turned both ways along the feed; pitch, bridge, edge, strip width,
                   stations, pilots and material utilisation from the Strip rules (master data)
    outputs        blank DXF, strip DXF, and a PDF pack: dimensioned blank, strip layout, simplified stage sketches
"""

from __future__ import annotations

import io
import math

import ezdxf
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

from . import formula, master_data, mould_db


def flat_pattern(shape, geometry: dict, blank: dict, thickness: float) -> dict:
    """Outline and holes (mm, origin at the lower-left of the blank)."""
    b = geometry["bbox_mm"]
    flat = (geometry.get("bend_count") or 0) == 0 and b["height"] <= thickness * 1.05
    if flat:
        face = max((f for f in shape.Faces() if f.geomType() == "PLANE"), key=lambda f: f.Area(), default=None)
        if face is not None:
            n = face.normalAt()
            drop = max(range(3), key=lambda i: abs((n.x, n.y, n.z)[i]))
            keep = [i for i in range(3) if i != drop]
            lines = []
            for e in face.Edges():
                pts = [e.positionAt(k / 24) for k in range(25)]
                lines.append(LineString([(p.toTuple()[keep[0]], p.toTuple()[keep[1]]) for p in pts]))
            polys = sorted(polygonize(unary_union(lines)), key=lambda p: -p.area)
            if polys:
                outer = Polygon(polys[0].exterior)          # polygonize returns the face with its holes cut out
                holes = [p for p in polys[1:] if outer.contains(p)]
                x0, y0, _, _ = outer.bounds
                mv = lambda poly: [[round(x - x0, 3), round(y - y0, 3)] for x, y in poly.exterior.coords]
                if outer.bounds[2] - outer.bounds[0] < outer.bounds[3] - outer.bounds[1]:   # long side along X
                    mv2 = lambda poly: [[y, x] for x, y in mv(poly)]
                else:
                    mv2 = mv
                o = mv2(outer)
                return {"method": "flat part: real outline from the 3D model", "outline": o, "holes": [mv2(h) for h in holes],
                        "length_mm": max(p[0] for p in o), "width_mm": max(p[1] for p in o),
                        "area_mm2": outer.area - sum(h.area for h in holes)}
    l, w = blank["length"], blank["width"]
    return {"method": f"bent part: {blank.get('method') or 'developed rectangle'} (no bend lines or hole positions drawn)",
            "outline": [[0, 0], [l, 0], [l, w], [0, w], [0, 0]], "holes": [], "length_mm": l, "width_mm": w, "area_mm2": l * w}


def strip_variant(fp: dict, feed_len: float, across: float, ops: int, t: float, sheet: dict) -> dict:
    params = master_data.parameters("sheet_metal")
    env = {k: float(v) for k, v in params.items() if isinstance(v, (int, float))}
    env |= {"t": t, "feed_len": feed_len, "across_w": across, "part_area": fp["area_mm2"], "operation_count": ops,
            "blank_l": fp["length_mm"], "blank_w": fp["width_mm"]}
    steps = []
    for r in sorted(mould_db.tables()["strip_rules"], key=lambda r: r["step"]):
        env[r["name"]] = float(formula.evaluate(r["formula"], env))
        steps.append({"name": r["name"], "label": r["label"], "formula": r["formula"], "unit": r["unit"], "value": env[r["name"]],
                      "is_example": r["is_example"]})
    return {"feed": "along the blank length" if feed_len == fp["length_mm"] else "along the blank width", "values": env, "steps": steps}


def strip_layout(fp: dict, t: float, ops: int) -> dict:
    a = strip_variant(fp, fp["length_mm"], fp["width_mm"], ops, t, {})
    b = strip_variant(fp, fp["width_mm"], fp["length_mm"], ops, t, {})
    best, other = sorted((a, b), key=lambda v: -v["values"]["utilisation_pct"])
    mx = master_data.parameters("sheet_metal").get("strip_max_width_mm")
    problems = []
    if mx and best["values"]["strip_width_mm"] > mx:
        problems.append(f"Strip width {best['values']['strip_width_mm']:.0f} mm is above the limit of {mx:g} mm "
                        "(Parameters → strip_max_width_mm): use multi-stage or a wider line.")
    return {"best": best, "other": other, "problems": problems, "is_example": any(s["is_example"] for s in best["steps"])}


def _place(outline, dx, dy, rot=False):
    return [[(y if rot else x) + dx, (x if rot else y) + dy] for x, y in outline]


def blank_dxf(fp: dict, part_code: str) -> bytes:
    doc = ezdxf.new("R2010")
    doc.layers.add("CUT", color=7)
    doc.layers.add("DIM", color=3)
    msp = doc.modelspace()
    msp.add_lwpolyline(fp["outline"], close=True, dxfattribs={"layer": "CUT"})
    for h in fp["holes"]:
        msp.add_lwpolyline(h, close=True, dxfattribs={"layer": "CUT"})
    msp.add_linear_dim(base=(0, -12), p1=(0, 0), p2=(fp["length_mm"], 0), dimstyle="EZDXF").render()
    msp.add_linear_dim(base=(-12, 0), p1=(0, 0), p2=(0, fp["width_mm"]), angle=90, dimstyle="EZDXF").render()
    msp.add_text(f"{part_code} blank", dxfattribs={"layer": "DIM", "height": 4}).set_placement((0, fp["width_mm"] + 8))
    return _dxf_bytes(doc)


def _dxf_bytes(doc) -> bytes:
    s = io.StringIO()
    doc.write(s)
    return s.getvalue().encode()


def strip_cells(fp: dict, sl: dict, count: int = 5):
    """Blank positions along the strip (first `count` stations of parts), turned when the feed is along the width."""
    v = sl["best"]["values"]
    rot = sl["best"]["feed"].endswith("width")
    return [_place(fp["outline"], i * v["pitch_mm"] + v["bridge_mm"] / 2, v["edge_mm"], rot) for i in range(count)], \
           [[_place(h, i * v["pitch_mm"] + v["bridge_mm"] / 2, v["edge_mm"], rot) for h in fp["holes"]] for i in range(count)]


def strip_dxf(fp: dict, sl: dict, part_code: str) -> bytes:
    v = sl["best"]["values"]
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    n = int(v["stations"])
    msp.add_lwpolyline([(0, 0), (n * v["pitch_mm"], 0), (n * v["pitch_mm"], v["strip_width_mm"]), (0, v["strip_width_mm"])], close=True)
    outs, holes = strip_cells(fp, sl, n)
    for o, hs in zip(outs, holes):
        msp.add_lwpolyline(o, close=True)
        for h in hs:
            msp.add_lwpolyline(h, close=True)
    for i in range(n + 1):
        msp.add_circle((i * v["pitch_mm"], v["edge_mm"] / 2 + 0.0), v["pilot_dia_mm"] / 2)
    msp.add_linear_dim(base=(0, -14), p1=(0, 0), p2=(v["pitch_mm"], 0), dimstyle="EZDXF").render()
    msp.add_linear_dim(base=(-14, 0), p1=(0, 0), p2=(0, v["strip_width_mm"]), angle=90, dimstyle="EZDXF").render()
    msp.add_text(f"{part_code} strip, feed {sl['best']['feed']}, pitch {v['pitch_mm']:.1f}", dxfattribs={"height": 4}).set_placement((0, v["strip_width_mm"] + 8))
    return _dxf_bytes(doc)


def pack_pdf(fp: dict, sl: dict, res: dict, part: dict, rev: str) -> bytes:
    """Tool drawing pack: dimensioned blank, strip layout, simplified stage sketches, forces."""
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
    from .pdf_report import _example_banner, _table, _theme
    theme = _theme()
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=18, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=11, spaceBefore=8, spaceAfter=4)
    note = ParagraphStyle("n", parent=ss["Normal"], textColor=theme["grey"], fontSize=7.5)
    W, H = 255 * mm, 120 * mm

    def drawing(polys_list, extent_w, extent_h, dims=()):
        sc = min((W - 30 * mm) / extent_w, (H - 30 * mm) / extent_h)
        d = Drawing(W, H)
        ox, oy = 18 * mm, 16 * mm
        for poly in polys_list:
            d.add(PolyLine([c for x, y in poly for c in (ox + x * sc, oy + y * sc)], strokeColor=theme["ink"], strokeWidth=0.8))
        for (x1, y1, x2, y2, label, off) in dims:
            horizontal = y1 == y2
            if horizontal:
                y = oy + y1 * sc - off
                d.add(Line(ox + x1 * sc, y, ox + x2 * sc, y, strokeColor=theme["brand"]))
                d.add(String((ox + (x1 + x2) / 2 * sc), y - 9, label, fontSize=7, textAnchor="middle", fillColor=theme["brand"]))
            else:
                x = ox + x1 * sc - off
                d.add(Line(x, oy + y1 * sc, x, oy + y2 * sc, strokeColor=theme["brand"]))
                d.add(String(x - 3, oy + (y1 + y2) / 2 * sc, label, fontSize=7, textAnchor="end", fillColor=theme["brand"]))
        return d

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=f"Design to Cost — Tool pack {part['part_code']}", author="Design to Cost")
    head = [Paragraph("SHEET-METAL TOOL PACK", ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8)),
            Paragraph(f"{part['part_code']} · {part['name']}", h1),
            Paragraph(f"Rev {rev} · {res['material']} · thickness {res['features']['t']:g} mm · {fp['method']}", note)]
    if res["is_example"] or sl["is_example"]:
        head += [Spacer(1, 2 * mm), _example_banner(ss, "Sheet rules and Strip rules are EXAMPLE values.")]
    holes_txt = ", ".join(f"Ø{math.sqrt(4 * Polygon(h).area / math.pi):.1f}" for h in fp["holes"][:12]) or "none drawn"
    story = head + [Paragraph("1 · Blank (flat pattern)", h2),
        drawing([fp["outline"]] + fp["holes"], fp["length_mm"], fp["width_mm"],
                [(0, 0, fp["length_mm"], 0, f"{fp['length_mm']:.1f}", 8), (0, 0, 0, fp["width_mm"], f"{fp['width_mm']:.1f}", 8)]),
        Paragraph(f"Blank {fp['length_mm']:.1f} × {fp['width_mm']:.1f} mm, area {fp['area_mm2']:.0f} mm², holes: {holes_txt}.", note), PageBreak()]
    v = sl["best"]["values"]
    n = int(v["stations"])
    outs, hs = strip_cells(fp, sl, min(n, 6))
    strip = [[(0, 0), (n * v["pitch_mm"], 0), (n * v["pitch_mm"], v["strip_width_mm"]), (0, v["strip_width_mm"]), (0, 0)]] + outs + [h for g in hs for h in g]
    story += [Paragraph("2 · Progressive strip layout", h2),
        drawing(strip, n * v["pitch_mm"], v["strip_width_mm"],
                [(0, 0, v["pitch_mm"], 0, f"pitch {v['pitch_mm']:.1f}", 8), (0, 0, 0, v["strip_width_mm"], f"width {v['strip_width_mm']:.1f}", 8)]),
        _table([["Item", "Value"], ["Feed", sl["best"]["feed"]], ["Pitch (mm)", f"{v['pitch_mm']:.2f}"], ["Bridge (mm)", f"{v['bridge_mm']:.2f}"],
                ["Edge margin (mm)", f"{v['edge_mm']:.2f}"], ["Strip width (mm)", f"{v['strip_width_mm']:.2f}"], ["Stations", f"{n}"],
                ["Pilots", f"{int(v['pilots'])} × Ø{v['pilot_dia_mm']:.1f}"], ["Material utilisation (%)", f"{v['utilisation_pct']:.1f}"],
                ["Other feed direction utilisation (%)", f"{sl['other']['values']['utilisation_pct']:.1f}"]], theme, [80 * mm, 60 * mm])]
    for p in sl["problems"]:
        story.append(Paragraph(f"<font color='#b91c1c'>■</font> {p}", ss["Normal"]))
    story += [PageBreak(), Paragraph("3 · Stages (simplified sketches)", h2)]
    ew, eh = 85 * mm, 55 * mm
    sketches, pierced = [], False
    for o in res["operations"]:
        pierced = pierced or o["code"] == "pierce"
        sc = min((ew - 10 * mm) / fp["length_mm"], (eh - 18 * mm) / fp["width_mm"])
        d = Drawing(ew, eh)
        for poly in [fp["outline"]] + (fp["holes"] if pierced else []):
            d.add(PolyLine([c for x, y in poly for c in (5 * mm + x * sc, 5 * mm + y * sc)], strokeColor=theme["ink"], strokeWidth=0.7))
        d.add(String(5 * mm, eh - 8 * mm, f"{o['n']} · {o['name']}", fontSize=8, fillColor=theme["brand"]))
        sketches.append(d)
    from reportlab.platypus import Table
    rows = [sketches[i:i + 3] for i in range(0, len(sketches), 3)]
    if rows:
        story.append(Table(rows))
    story += [Spacer(1, 3 * mm), _table([["#", "Operation", "Force (t)", "Stage weight (g)"]] +
              [[str(o["n"]), o["name"], f"{o['force_t']:.1f}", f"{o['stage_weight_g']:.1f}"] for o in res["operations"]], theme, [15 * mm, 80 * mm, 30 * mm, 40 * mm])]
    story.append(Paragraph("Bend and draw stages are shown as the flat blank: the sketches are not formed-shape drawings.", note))
    doc.build(story)
    return buf.getvalue()
