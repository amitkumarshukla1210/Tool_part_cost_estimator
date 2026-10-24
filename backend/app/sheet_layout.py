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
    return {"method": "bent part: developed rectangle from the blank estimate (no bend lines or hole positions)",
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


def blank_dxf(fp: dict, part_code: str, meta: dict | None = None) -> bytes:
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
    from . import drawing_sheet
    meta = meta or drawing_sheet.sheet_meta(None, [], f"{part_code} blank (flat pattern)", f"{part_code}-BLANK", "A", "1:1 (as drawn)")
    drawing_sheet.dxf_title_block(doc, msp, 0.0, -45.0 - 12 * max(1, len(meta["history"])) * 0, meta, max(1.0, fp["length_mm"] / 150),
                                  [f"Blank {fp['length_mm']:.2f} x {fp['width_mm']:.2f} mm, area {fp['area_mm2']:.0f} mm2 - {fp['method']}"])
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


def strip_dxf(fp: dict, sl: dict, part_code: str, meta: dict | None = None) -> bytes:
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
    from . import drawing_sheet
    meta = meta or drawing_sheet.sheet_meta(None, [], f"{part_code} strip layout", f"{part_code}-STRIP", "A", "1:1 (as drawn)")
    drawing_sheet.dxf_title_block(doc, msp, 0.0, -50.0, meta, max(1.0, n * v["pitch_mm"] / 300),
                                  [f"Feed {sl['best']['feed']}  pitch {v['pitch_mm']:.2f}  strip width {v['strip_width_mm']:.2f}  stations {n}  utilisation {v['utilisation_pct']:.1f} %"])
    return _dxf_bytes(doc)


def pack_pdf(fp: dict, sl: dict, res: dict, part: dict, rev: str, meta: dict | None = None) -> bytes:
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
    from . import drawing_sheet
    meta = meta or drawing_sheet.sheet_meta(None, [], f"{part['part_code']} tool pack", f"{part['part_code']}-PACK", rev)
    head = [drawing_sheet.flow_title(meta, theme, 267), Spacer(1, 3 * mm), Paragraph("SHEET-METAL TOOL PACK", ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8)),
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
    story += [Paragraph("Revision history", h2), drawing_sheet.flow_history(meta, theme, 267)]
    doc.build(story)
    return buf.getvalue()


def strip_sheet_pdf(fp: dict, sl: dict, part: dict, rev: str, meta: dict | None = None) -> bytes:
    """The strip layout as one A3 drawing to scale: strip with blanks, pilots and dimensions, the blank, the data table, notes and the title block
    (logo, name, release date, approved by, projection, revision history)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph, Table, TableStyle
    from . import drawing_sheet
    from .pdf_report import _theme
    theme = _theme()
    code = part["part_code"]
    meta = meta or drawing_sheet.sheet_meta(None, [], f"{code} strip layout", f"{code}-STRIP", rev)
    v = sl["best"]["values"]
    n = int(v["stations"])
    show = min(n, 8)
    total_l = max(show * v["pitch_mm"], v["pitch_mm"])
    area_w, area_h = 380.0, 165.0                      # mm on the sheet for the strip
    scales = [1, 2, 2.5, 5, 10, 20, 25, 50, 100]
    sc = next((1 / k for k in scales if (total_l + 2 * 15) / k <= area_w and (v["strip_width_mm"] + 35) / k <= area_h), 1 / 100)
    ratio = f"1:{round(1 / sc):g}"
    meta = dict(meta, scale=ratio)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A3))
    c.setTitle(f"Design to Cost - strip layout {code}")
    c.setStrokeColor(theme["border"]); c.setLineWidth(0.6)
    c.rect(8 * mm, 8 * mm, 404 * mm, 281 * mm)
    ox, oy = 22.0, 108.0                               # mm: strip origin (lower-left)

    def poly(pts, color=None, w=0.5, close=True):
        c.setStrokeColor(color or theme["ink"]); c.setLineWidth(w)
        p = c.beginPath()
        p.moveTo((ox + pts[0][0] * sc) * mm, (oy + pts[0][1] * sc) * mm)
        for x, y in pts[1:]:
            p.lineTo((ox + x * sc) * mm, (oy + y * sc) * mm)
        if close:
            p.close()
        c.drawPath(p, stroke=1, fill=0)
    poly([(0, 0), (show * v["pitch_mm"], 0), (show * v["pitch_mm"], v["strip_width_mm"]), (0, v["strip_width_mm"])], w=0.8)
    outs, hs = strip_cells(fp, sl, show)
    for o, hh in zip(outs, hs):
        poly(o, w=0.6)
        for h in hh:
            poly(h, w=0.4)
    c.setStrokeColor(colors.HexColor("#b91c1c")); c.setLineWidth(0.4)
    for i in range(show + 1):
        c.circle((ox + i * v["pitch_mm"] * sc) * mm, (oy + v["edge_mm"] / 2 * sc) * mm, max(v["pilot_dia_mm"] / 2 * sc, 0.4) * mm)
    # dimensions
    c.setStrokeColor(theme["brand"]); c.setFillColor(theme["brand"]); c.setFont("Helvetica", 7.5); c.setLineWidth(0.3)
    y = (oy - 8) * mm
    c.line(ox * mm, y, (ox + v["pitch_mm"] * sc) * mm, y)
    c.drawCentredString((ox + v["pitch_mm"] * sc / 2) * mm, y - 3.5 * mm, f"pitch {v['pitch_mm']:.2f}")
    x = (ox - 8) * mm
    c.line(x, oy * mm, x, (oy + v["strip_width_mm"] * sc) * mm)
    c.saveState(); c.translate(x - 1.5 * mm, (oy + v["strip_width_mm"] * sc / 2) * mm); c.rotate(90); c.drawCentredString(0, 0, f"strip width {v['strip_width_mm']:.2f}"); c.restoreState()
    c.setFillColor(theme["ink"]); c.setFont("Helvetica-Bold", 11)
    c.drawString(ox * mm, (oy + v["strip_width_mm"] * sc + 8) * mm, f"STRIP LAYOUT  {code} · {part['name']}")
    c.setFont("Helvetica", 8)
    c.drawString(ox * mm, (oy + v["strip_width_mm"] * sc + 3.5) * mm, f"Feed {sl['best']['feed']} · first {show} of {n} stations shown · scale {ratio} · material utilisation {v['utilisation_pct']:.1f} %")
    # table and notes (right of the lower area), title block and history at the lower right
    RX = 420 - 12 - 113
    tb_rows = [("Part", f"{code} {part['name']}"[:46], "Strip rev", rev), ("Blank", f"{fp['length_mm']:.1f} × {fp['width_mm']:.1f} mm", "Area", f"{fp['area_mm2']:.0f} mm²"),
               ("Feed", sl["best"]["feed"][:34], "Stations", str(n))]
    th = drawing_sheet.pdf_title_block(c, 420 - 12, 12, meta, theme, tb_rows, width=113)
    hh = drawing_sheet.pdf_history(c, RX, 12 + th + 3, meta["history"], theme, width=113)
    rows = [["Item", "Value"], ["Pitch (mm)", f"{v['pitch_mm']:.2f}"], ["Bridge (mm)", f"{v['bridge_mm']:.2f}"], ["Edge margin (mm)", f"{v['edge_mm']:.2f}"],
            ["Strip width (mm)", f"{v['strip_width_mm']:.2f}"], ["Stations", str(n)], ["Pilots", f"{int(v['pilots'])} × Ø{v['pilot_dia_mm']:.1f}"],
            ["Utilisation (%)", f"{v['utilisation_pct']:.1f}"], ["Other feed utilisation (%)", f"{sl['other']['values']['utilisation_pct']:.1f}"]]
    t = Table(rows, colWidths=[42 * mm, 30 * mm], rowHeights=5 * mm)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.5), ("BACKGROUND", (0, 0), (-1, 0), theme["head"]), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("GRID", (0, 0), (-1, -1), 0.2, theme["border"])]))
    w, h = t.wrapOn(c, 0, 0)
    t.drawOn(c, 15 * mm, 90 * mm - h)
    c.setFont("Helvetica-Bold", 8); c.setFillColor(theme["ink"]); c.drawString(15 * mm, 91 * mm, "STRIP DATA")
    ss = getSampleStyleSheet()
    small = ParagraphStyle("s", parent=ss["Normal"], fontSize=7, leading=8.5)
    notes = ["1. All dimensions in mm. Third-angle projection. Feed direction left to right.",
             "2. Pitch, bridge and edge margin from the Strip rules (Master data); check against the die before cutting steel.",
             f"3. {fp['method']}."] + sl["problems"]
    c.setFont("Helvetica-Bold", 8); c.drawString(100 * mm, 91 * mm, "NOTES")
    py = 88 * mm
    for line in notes:
        p = Paragraph(line, small)
        w, h = p.wrapOn(c, 150 * mm, 30 * mm)
        p.drawOn(c, 100 * mm, py - h)
        py -= h + 1 * mm
    # the blank, small, beside the notes
    bs = min(80 / max(fp["length_mm"], 1), 38 / max(fp["width_mm"], 1))
    bx, by = 200.0, 16.0
    c.setStrokeColor(theme["ink"]); c.setLineWidth(0.5)
    for pts in [fp["outline"]] + fp["holes"]:
        p = c.beginPath()
        p.moveTo((bx + pts[0][0] * bs) * mm, (by + pts[0][1] * bs) * mm)
        for x, y in pts[1:]:
            p.lineTo((bx + x * bs) * mm, (by + y * bs) * mm)
        c.drawPath(p, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 8); c.setFillColor(theme["ink"]); c.drawString(bx * mm, (by + fp["width_mm"] * bs + 3) * mm, "BLANK (flat pattern)")
    c.setFont("Helvetica", 6); c.setFillColor(theme["grey"])
    c.drawString(15 * mm, 9.2 * mm, "Design to Cost · concept-level strip layout from the Strip rules: check before cutting steel" + (" · EXAMPLE rules" if sl["is_example"] else ""))
    c.showPage()
    c.save()
    return buf.getvalue()
