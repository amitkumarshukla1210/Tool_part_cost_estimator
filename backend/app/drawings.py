"""Drawings for quotation and purchase orders (roadmap stage 26).

    part drawing        three views (top, front, side) projected from the 3D model, overall dimensions, title block
                        (part, revision, material, thickness, weight, blank, process) - PDF (A3) and DXF
    tool drawing        concept layout of a mould or of each die stage: plan view (mould base / die set outline,
                        die plate or insert pocket, work area / cavities, guide pillars) with dimensions, elevation of the
                        plate stack, main BOM (grade, make, part numbers), title block - PDF (A3) and DXF
    PO pack (ZIP)       everything a toolmaker / supplier needs for a quotation or a PO: part STEP and drawing, tool
                        drawings per stage, tool cost sheets per stage, blank / strip DXF and tool pack, RM / part cost

The 3D model (STEP) stays the master: the drawings are views of it and concept layouts of the tool, marked
"CONCEPT - for quotation", not detailed manufacturing drawings.
"""

from __future__ import annotations

import io
import math
import zipfile
from datetime import date

import ezdxf

VIEWS = (("TOP VIEW", 0, 1), ("FRONT VIEW", 0, 2), ("SIDE VIEW", 1, 2))   # (title, horizontal axis, vertical axis)


# ---------- geometry of the views ----------

def edge_polylines(shape) -> list[list[tuple]]:
    """Every edge of the model as a 3D polyline (straight edges: 2 points, curves: 24 segments)."""
    out = []
    for e in shape.Edges():
        n = 1 if e.geomType() == "LINE" else 24
        out.append([e.positionAt(k / n).toTuple() for k in range(n + 1)])
    return out


def project(lines, h: int, v: int) -> tuple[list, tuple]:
    """Lines projected on a plane (axis indices h, v); returns 2D polylines moved to the origin and their size."""
    pts = [(p[h], p[v]) for line in lines for p in line]
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
    seen, out = set(), []
    for line in lines:
        q = [(round(p[h] - x0, 3), round(p[v] - y0, 3)) for p in line]
        if len(set(q)) < 2:
            continue                                   # an edge seen end-on is a point in this view
        key = tuple(q) if q[0] <= q[-1] else tuple(reversed(q))
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out, (x1 - x0, y1 - y0)


def views(shape) -> list[dict]:
    lines = edge_polylines(shape)
    out = []
    for title, h, v in VIEWS:
        polys, (w, ht) = project(lines, h, v)
        out.append({"title": title, "polys": polys, "w": max(w, 1e-6), "h": max(ht, 1e-6), "axes": "XYZ"[h] + "XYZ"[v]})
    return out


# ---------- PDF helpers ----------

def _styles():
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from .pdf_report import _theme
    theme = _theme()
    ss = getSampleStyleSheet()
    return theme, ss, {
        "h1": ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=15, alignment=0, spaceAfter=2),
        "k": ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8),
        "n": ParagraphStyle("n", parent=ss["Normal"], textColor=theme["grey"], fontSize=7.5, leading=9),
        "c": ParagraphStyle("c", parent=ss["Normal"], fontSize=7.5, leading=9),
    }


def _dim(d, x1, y1, x2, y2, label, theme, side=1):
    """A dimension line with arrows and its value (drawing coordinates)."""
    from reportlab.graphics.shapes import Line, Polygon, String
    col = theme["brand"]
    d.add(Line(x1, y1, x2, y2, strokeColor=col, strokeWidth=0.5))
    ang = math.atan2(y2 - y1, x2 - x1)
    for (x, y, a) in ((x1, y1, ang), (x2, y2, ang + math.pi)):
        d.add(Polygon([x, y, x + 5 * math.cos(a + 0.3), y + 5 * math.sin(a + 0.3), x + 5 * math.cos(a - 0.3), y + 5 * math.sin(a - 0.3)],
                      fillColor=col, strokeColor=col, strokeWidth=0.3))
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    if abs(y2 - y1) < 1e-6:
        d.add(String(mx, my + 3 * side if side > 0 else my - 9, label, fontSize=7, textAnchor="middle", fillColor=col))
    else:
        d.add(String(mx - 4, my, label, fontSize=7, textAnchor="end", fillColor=col))


def _title_block(rows, theme, width):
    from reportlab.lib.units import mm
    from reportlab.platypus import Table, TableStyle
    t = Table(rows, colWidths=[width * 0.22, width * 0.28, width * 0.22, width * 0.28])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, theme["ink"]), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                           ("BACKGROUND", (0, 0), (0, -1), theme["alt"]), ("BACKGROUND", (2, 0), (2, -1), theme["alt"]),
                           ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2 * mm / 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm / 3)]))
    return t


def _doc(buf, title):
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate
    return SimpleDocTemplate(buf, pagesize=landscape(A3), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=10 * mm,
                             bottomMargin=10 * mm, title=title, author="Design to Cost")


def _frame_note(st):
    from reportlab.platypus import Paragraph
    return Paragraph("CONCEPT – for quotation and purchase order reference. The 3D model (STEP) is the master for all geometry; "
                     "general tolerances ISO 2768-m unless the 3D model or the PO says otherwise. Generated by Design to Cost.", st["n"])


# ---------- part drawing ----------

def part_drawing_pdf(part: dict, rev: dict, shape, info: dict) -> bytes:
    """A3 part drawing: top, front and side views (third-angle layout), overall dimensions, title block."""
    from reportlab.graphics.shapes import Drawing, PolyLine, Rect, String
    from reportlab.lib.units import mm
    from reportlab.platypus import Spacer
    theme, ss, st = _styles()
    vs = {v["title"]: v for v in views(shape)}
    top, front, side = vs["TOP VIEW"], vs["FRONT VIEW"], vs["SIDE VIEW"]
    W, H = 396 * mm, 205 * mm
    gap = 26 * mm
    need_w = front["w"] + side["w"]
    need_h = front["h"] + top["h"]
    sc = min((W - 3 * gap) / need_w, (H - 3 * gap) / need_h)
    d = Drawing(W, H)
    d.add(Rect(0, 0, W, H, strokeColor=theme["ink"], fillColor=None, strokeWidth=0.8))
    ox, oy = gap, gap                                         # front view bottom-left; top view above; side view right
    places = {"FRONT VIEW": (ox, oy), "TOP VIEW": (ox, oy + front["h"] * sc + gap), "SIDE VIEW": (ox + front["w"] * sc + gap, oy)}
    for title, (px, py) in places.items():
        v = vs[title]
        for poly in v["polys"]:
            d.add(PolyLine([c for x, y in poly for c in (px + x * sc, py + y * sc)], strokeColor=theme["ink"], strokeWidth=0.6))
        d.add(String(px, py - 14, f"{title} ({v['axes'][0]}–{v['axes'][1]})", fontSize=8, fillColor=theme["grey"]))
    fx, fy = places["FRONT VIEW"]
    _dim(d, fx, fy - 6, fx + front["w"] * sc, fy - 6, f"{front['w']:.1f}", theme, side=-1)
    _dim(d, fx - 8, fy, fx - 8, fy + front["h"] * sc, f"{front['h']:.1f}", theme)
    tx, ty = places["TOP VIEW"]
    _dim(d, tx - 8, ty, tx - 8, ty + top["h"] * sc, f"{top['h']:.1f}", theme)
    sx, sy = places["SIDE VIEW"]
    _dim(d, sx, sy - 6, sx + side["w"] * sc, sy - 6, f"{side['w']:.1f}", theme, side=-1)
    d.add(String(W - 6 * mm, H - 6 * mm, f"Scale 1:{1 / sc * mm:.2g}" if sc < mm else f"Scale {sc / mm:.2g}:1", fontSize=8,
                 textAnchor="end", fillColor=theme["grey"]))
    g = rev.get("geometry") or {}
    rows = [["Part code", part["part_code"], "Part name", part["name"]],
            ["Revision", rev.get("rev", ""), "Project", part.get("project_code", "")],
            ["Material", part.get("material") or "—", "Process", part.get("process") or "—"],
            ["Thickness / main wall", f"{g.get('wall_mm', 0):g} mm", "Net weight", info.get("weight", "—")],
            ["Overall size L × W × H", f"{g['bbox_mm']['length']:.1f} × {g['bbox_mm']['width']:.1f} × {g['bbox_mm']['height']:.1f} mm" if g.get("bbox_mm") else "—",
             "Blank (developed)", info.get("blank", "—")],
            ["3D file (master)", rev.get("original_name", ""), "Date / by", f"{date.today().isoformat()} · Design to Cost"]]
    from . import drawing_style
    buf = io.BytesIO()
    doc = _doc(buf, f"Design to Cost — Part drawing {part['part_code']}")
    fields = [(a, b) for r in rows[:-1] for a, b in ((r[0], r[1]), (r[2], r[3]))]
    doc.build([drawing_style.pdf_header(st, "PART DRAWING", f"{part['part_code']} · {part['name']} · rev {rev.get('rev', '')}"),
               d, Spacer(1, 2 * mm),
               drawing_style.pdf_title_block(396 * mm, fields, part.get("part_type", ""), _scale_label(sc), "1 / 1", part["part_code"],
                                             rev.get("rev", ""), ["The 3D model (STEP) is the master for all geometry; dimensions "
                                                                  "not shown are taken from it."])])
    return buf.getvalue()


def _scale_label(sc) -> str:
    from reportlab.lib.units import mm
    r = sc / mm
    return f"1:{1 / r:.2g}" if r < 1 else f"{r:.2g}:1"


def part_drawing_dxf(part: dict, rev: dict, shape) -> bytes:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.add("VIEWS", color=7)
    doc.layers.add("TEXT", color=5)
    x = 0.0
    for v in views(shape):
        for poly in v["polys"]:
            msp.add_lwpolyline([(x + a, b) for a, b in poly], dxfattribs={"layer": "VIEWS"})
        msp.add_text(f"{v['title']} {v['w']:.1f} x {v['h']:.1f}", dxfattribs={"layer": "TEXT", "height": 3}).set_placement((x, -8))
        x += v["w"] + 30
    msp.add_text(f"{part['part_code']} {part['name']} rev {rev.get('rev', '')} - views of the 3D model (STEP is master)",
                 dxfattribs={"layer": "TEXT", "height": 4}).set_placement((0, -20))
    _dxf_frame(doc, msp, "Part drawing", part, rev.get("rev", ""), [("Material", part.get("material") or "-")])
    return _dxf_bytes(doc)


def _dxf_frame(doc, msp, title, part, rev, rows, part_type=""):
    """Move what is drawn up and right, then put the frame with logo and title block around it."""
    from ezdxf import bbox
    from ezdxf.math import Matrix44
    from . import drawing_style
    xs, ys = [], []
    for e in msp:
        try:
            box = bbox.extents([e])
            if box.has_data:
                xs += [box.extmin.x, box.extmax.x]
                ys += [box.extmin.y, box.extmax.y]
        except Exception:
            pass
    x0, y0, x1, y1 = (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 400, 250)
    for e in list(msp):
        e.transform(Matrix44.translate(10 - x0, 80 - y0, 0))
    drawing_style.dxf_frame(doc, msp, max(x1 - x0 + 20, 420), y1 - y0 + 90, f"{title} {part['part_code']}",
                            [("Part", f"{part['part_code']} {part['name']}")] + rows, part_type, "1:1", part["part_code"], rev)


def _dxf_bytes(doc) -> bytes:
    s = io.StringIO()
    doc.write(s)
    return s.getvalue().encode()


# ---------- tool drawings (concept layouts) ----------

def tool_layout(tr: dict, die: str | None = None) -> dict:
    """Plan and stack of one die stage (sheet metal) or of the mould, from the stored tool cost trace."""
    if tr.get("dies"):
        d = next((x for x in tr["dies"] if x["key"] == die), None) if die else tr["dies"][0]
        if d is None:
            raise ValueError(f"There is no die '{die}' in this tool cost.")
        b, p = d["base"], d["die_plate"]
        nodes = tr["nodes"]
        wl = next((n["value"] for k, n in nodes.items() if k.startswith(d["key"] + ":v:work_l")), None)
        ww = next((n["value"] for k, n in nodes.items() if k.startswith(d["key"] + ":v:work_w")), None)
        rule = lambda name, dflt: next((n["value"] for k, n in nodes.items() if k == f"{d['key']}:v:{name}"), dflt)
        stack = [("Top shoe (die set)", b.get("clamp_plates_mm") or 40), ("Punch holder plate", rule("punch_plate_h_mm", 22)),
                 ("Stripper plate", rule("stripper_h_mm", 20)), ("Die plate", p["die_h"]), ("Backing plate", rule("backing_h_mm", 12)),
                 ("Bottom shoe (die set)", b.get("clamp_plates_mm") or 40)]
        lines = [l for l in tr["lines"] if l.get("die_key") == d["key"]]
        n = tr["dies"].index(d) + 1
        return {"kind": "die", "title": d["name"], "stage": f"Stage {n} of {len(tr['dies'])}", "ops": ", ".join(d["op_names"]),
                "base": b, "outer": (b["length_mm"], b["width_mm"]), "plate": (p["die_l"], p["die_w"]), "plate_label": "Die plate",
                "work": (wl or p["die_l"] - 70, ww or p["die_w"] - 70), "work_label": "Work area (blank / strip)",
                "cells": [], "stack": stack, "press": d["press"], "force_t": d["force_t"], "lines": lines, "value": d["value"],
                "value_inr": d["value_inr"], "currency": tr["currency"], "pillars": 4}
    b = tr["base"]
    nodes = tr["nodes"]
    val = lambda k, dflt=0: nodes[k]["value"] if k in nodes else dflt
    rows_, cols = int(val("v:layout_rows", 1)), int(val("v:layout_cols", 1))
    il, iw, gap = val("v:insert_each_l"), val("v:insert_each_w"), val("v:insert_gap_mm", 10)
    pl, pw = val("v:pocket_l", il), val("v:pocket_w", iw)
    cells = []
    for r in range(rows_):
        for c in range(cols):
            cells.append((c * (il + gap), r * (iw + gap), il, iw))
    stack = [("Top clamp plate", b.get("clamp_plates_mm") or 0), ("A plate (cavity)", b.get("a_plate_mm") or 0),
             ("B plate (core)", b.get("b_plate_mm") or 0), ("Support plate", b.get("support_plate_mm") or 0),
             ("Spacer blocks / ejector plates", max(b.get("spacer_block_mm") or 0, b.get("ejector_plates_mm") or 0)),
             ("Bottom clamp plate", b.get("clamp_plates_mm") or 0)]
    return {"kind": "mould", "title": f"Mould · {tr.get('cavities', 1)} cavit{'y' if tr.get('cavities', 1) == 1 else 'ies'}",
            "stage": "Mould", "ops": tr.get("part_type", "").replace("_", " "), "base": b, "outer": (b["length_mm"], b["width_mm"]),
            "plate": (pl, pw), "plate_label": "Insert pocket", "work": None, "work_label": "", "cells": cells,
            "stack": [s for s in stack if s[1]], "press": (tr.get("trial") or {}).get("machine"),
            "force_t": (tr.get("trial") or {}).get("force_t"), "lines": tr["lines"], "value": tr["value"], "value_inr": tr["value_inr"],
            "currency": tr["currency"], "pillars": 4}


def tool_drawing_pdf(part: dict, tr: dict, die: str | None = None) -> bytes:
    from reportlab.graphics.shapes import Circle, Drawing, Rect, String
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table
    from .pdf_report import _table
    theme, ss, st = _styles()
    lay = tool_layout(tr, die)
    OL, OW = lay["outer"]
    PW_, PH_ = 230 * mm, 175 * mm
    sc = min((PW_ - 40 * mm) / OL, (PH_ - 40 * mm) / OW)
    plan = Drawing(PW_, PH_)
    ox, oy = 25 * mm, 22 * mm
    R = lambda x, y, w, h, **k: plan.add(Rect(ox + x * sc, oy + y * sc, w * sc, h * sc, fillColor=None, **k))
    R(0, 0, OL, OW, strokeColor=theme["ink"], strokeWidth=1.0)
    pl, pw = lay["plate"]
    px, py = (OL - pl) / 2, (OW - pw) / 2
    R(px, py, pl, pw, strokeColor=theme["brand"], strokeWidth=0.9)
    plan.add(String(ox + (px + 3) * sc, oy + (py + pw) * sc - 10, lay["plate_label"], fontSize=7, fillColor=theme["brand"]))
    if lay["work"]:
        wl, ww = lay["work"]
        R((OL - wl) / 2, (OW - ww) / 2, wl, ww, strokeColor=theme["grey"], strokeWidth=0.6, strokeDashArray=[3, 2])
        plan.add(String(ox + ((OL - wl) / 2 + 2) * sc, oy + ((OW - ww) / 2 + 2) * sc, lay["work_label"], fontSize=6.5, fillColor=theme["grey"]))
        _dim(plan, ox + (OL - wl) / 2 * sc, oy + (OW + ww) / 2 * sc + 6, ox + (OL + wl) / 2 * sc, oy + (OW + ww) / 2 * sc + 6, f"{wl:.1f}", theme)
    for (cx, cy, cl, cw) in lay["cells"]:
        R(px + cx, py + cy, cl, cw, strokeColor=theme["grey"], strokeWidth=0.6)
    r = max(min(OL, OW) * 0.04, 8)
    for (x, y) in ((r * 2, r * 2), (OL - r * 2, r * 2), (r * 2, OW - r * 2), (OL - r * 2, OW - r * 2)):
        plan.add(Circle(ox + x * sc, oy + y * sc, r * sc, fillColor=None, strokeColor=theme["ink"], strokeWidth=0.6))
    _dim(plan, ox, oy - 10, ox + OL * sc, oy - 10, f"{OL:.0f}", theme, side=-1)
    _dim(plan, ox - 10, oy, ox - 10, oy + OW * sc, f"{OW:.0f}", theme)
    _dim(plan, ox + px * sc, oy + py * sc + 6, ox + (px + pl) * sc, oy + py * sc + 6, f"{pl:.1f}", theme)
    _dim(plan, ox + (px + pl) * sc + 10, oy + py * sc, ox + (px + pl) * sc + 10, oy + (py + pw) * sc, f"{pw:.1f}", theme)
    plan.add(String(ox, PH_ - 10, "PLAN VIEW (bottom half)", fontSize=8, fillColor=theme["grey"]))
    # elevation: the plate stack
    EW, EH = 150 * mm, 175 * mm
    elev = Drawing(EW, EH)
    total = sum(h for _, h in lay["stack"]) or 1
    esc = min((EH - 40 * mm) / total, (EW - 70 * mm) / OL)
    y = 20 * mm
    for name, h in reversed(lay["stack"]):
        elev.add(Rect(10 * mm, y, OL * esc, h * esc, fillColor=None, strokeColor=theme["ink"], strokeWidth=0.7))
        elev.add(String(10 * mm + OL * esc + 4, y + h * esc / 2 - 3, f"{name} {h:g}", fontSize=7, fillColor=theme["ink"]))
        y += h * esc
    _dim(elev, 6 * mm, 20 * mm, 6 * mm, y, f"{total:.0f}", theme)
    elev.add(String(10 * mm, EH - 10, "ELEVATION (plate stack, mm)", fontSize=8, fillColor=theme["grey"]))
    b = lay["base"]
    press = lay["press"] or {}
    rows = [["Part", f"{part['part_code']} · {part['name']}", "Tool / stage", f"{lay['title']} · {lay['stage']}"],
            ["Operations", lay["ops"], "Press / machine", f"{press.get('machine_id') or '—'}" + (f" for {lay['force_t']:.1f} t" if lay["force_t"] else "")],
            ["Mould base / die set", f"{b['series']} {b['size_code']} · {OL:.0f} × {OW:.0f} mm", "Plate material",
             f"{b.get('material') or '—'} · make {b.get('make') or '—'}"],
            ["Tool cost (estimate)", f"{lay['value']:,.0f} {lay['currency']} = {lay['value_inr']:,.0f} INR", "Date",
             f"{date.today().isoformat()} · Design to Cost"]]
    main = [l for l in lay["lines"] if l["category"] != "process"]
    bom = [["Element", "Qty", "Grade", "Make", "Part no."]] + [
        [l["element"][:38], f"{l['quantity']:g}", (l.get("grade") or "")[:22], (l.get("make") or "")[:22],
         " ".join(x for x in (l.get("std_part") or "", l.get("part_number") or "") if x)[:24]] for l in main]
    from . import drawing_style
    buf = io.BytesIO()
    doc = _doc(buf, f"Design to Cost — Tool drawing {part['part_code']} {lay['title']}")
    fields = [(a, b) for r in rows for a, b in ((r[0], r[1]), (r[2], r[3]))]
    doc.build([drawing_style.pdf_header(st, f"TOOL CONCEPT DRAWING · {lay['stage'].upper()}", f"{part['part_code']} · {lay['title']}"),
               Table([[plan, elev]], colWidths=[PW_, EW]), Spacer(1, 2 * mm),
               Paragraph("Main bill of material (processes are in the tool cost sheet)", st["k"]),
               _table(bom, theme, [110 * mm, 18 * mm, 70 * mm, 70 * mm, 70 * mm]), Spacer(1, 2 * mm),
               drawing_style.pdf_title_block(396 * mm, fields, lay.get("part_type", ""), "as shown", "1 / 1",
                                             f"{part['part_code']}-C-{lay['stage'].replace(' ', '')}", "",
                                             ["CONCEPT layout for quotation and PO reference; the detailed tool design (3D and "
                                              "drawings of every part) is in Tool design → release pack."])])
    return buf.getvalue()


def tool_drawing_dxf(part: dict, tr: dict, die: str | None = None) -> bytes:
    lay = tool_layout(tr, die)
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for name, col in (("OUTLINE", 7), ("PLATE", 5), ("WORK", 8), ("TEXT", 3)):
        doc.layers.add(name, color=col)
    OL, OW = lay["outer"]
    rect = lambda x, y, w, h, layer: msp.add_lwpolyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)], dxfattribs={"layer": layer})
    rect(0, 0, OL, OW, "OUTLINE")
    pl, pw = lay["plate"]
    px, py = (OL - pl) / 2, (OW - pw) / 2
    rect(px, py, pl, pw, "PLATE")
    if lay["work"]:
        wl, ww = lay["work"]
        rect((OL - wl) / 2, (OW - ww) / 2, wl, ww, "WORK")
    for (cx, cy, cl, cw) in lay["cells"]:
        rect(px + cx, py + cy, cl, cw, "WORK")
    r = max(min(OL, OW) * 0.04, 8)
    for (x, y) in ((r * 2, r * 2), (OL - r * 2, r * 2), (r * 2, OW - r * 2), (OL - r * 2, OW - r * 2)):
        msp.add_circle((x, y), r, dxfattribs={"layer": "OUTLINE"})
    msp.add_text(f"{part['part_code']} {lay['title']} {lay['stage']} - base {lay['base']['series']} {lay['base']['size_code']} "
                 f"{OL:.0f}x{OW:.0f}, {lay['plate_label']} {pl:.1f}x{pw:.1f} - CONCEPT", dxfattribs={"layer": "TEXT", "height": 5}).set_placement((0, -15))
    _dxf_frame(doc, msp, f"Tool concept {lay['stage']}", part, "", [("Tool", lay["title"])])
    return _dxf_bytes(doc)


# ---------- PO pack ----------

def po_pack(part_id: int) -> tuple[bytes, str]:
    """ZIP with every file needed for a quotation / PO of the part and its tooling."""
    from . import register
    d = register.part_detail(part_id, with_rm=False)
    code = d["part_code"]
    files, missing = {}, []

    def add(name, fn):
        try:
            files[name] = fn()
        except Exception as exc:              # a file that cannot be made is listed in the README of the pack
            missing.append(f"{name}: {exc}")

    rev = d["revisions"][0] if d["revisions"] else None
    if rev and rev.get("file_id"):
        add(f"01_part/{code}_rev{rev['rev']}.step", lambda: register.revision_file_bytes(rev))
    add(f"01_part/{code}_part_drawing.pdf", lambda: register.part_drawing(part_id, "pdf"))
    add(f"01_part/{code}_part_drawing.dxf", lambda: register.part_drawing(part_id, "dxf"))
    tr = None
    try:
        tr = register.tool_trace(part_id)
    except Exception as exc:
        missing.append(f"tool cost: {exc}")
    if tr:
        add(f"02_tool/{code}_tool_cost_all.pdf", lambda: register.export_tool_pdf(part_id))
        add(f"02_tool/{code}_tool_cost_all.xlsx", lambda: register.export_tool_excel(part_id))
        if tr.get("dies"):
            for k, x in enumerate(tr["dies"], start=1):
                stem = f"02_tool/stage{k}_{x['key']}"
                add(f"{stem}_drawing.pdf", lambda x=x: tool_drawing_pdf(d, tr, x["key"]))
                add(f"{stem}_drawing.dxf", lambda x=x: tool_drawing_dxf(d, tr, x["key"]))
                add(f"{stem}_cost.pdf", lambda x=x: register.export_tool_pdf(part_id, None, x["key"]))
                add(f"{stem}_bom.xlsx", lambda x=x: register.export_tool_excel(part_id, None, x["key"]))
            for kind in ("blank.dxf", "strip.dxf", "tool-pack.pdf"):
                add(f"02_tool/{code}_{kind.replace('-', '_')}", lambda kind=kind: register.sheet_layout_file(part_id, kind)[0])
        else:
            add(f"02_tool/{code}_mould_drawing.pdf", lambda: tool_drawing_pdf(d, tr))
            add(f"02_tool/{code}_mould_drawing.dxf", lambda: tool_drawing_dxf(d, tr))
    add(f"03_cost/{code}_rm_cost.pdf", lambda: register.export_rm_pdf(part_id))
    try:
        from . import piece_cost  # noqa: F401
        add(f"03_cost/{code}_part_cost.pdf", lambda: register.piece_pdf(part_id, None))
    except Exception:
        pass
    readme = [f"Design to Cost - PO pack for {code} · {d['name']}", f"Made {date.today().isoformat()}", "",
              "01_part   part 3D model (master) and part drawing", "02_tool   tool cost sheets and concept drawings per stage / mould, "
              "blank and strip layout", "03_cost   RM and part cost sheets", "",
              "Drawings are CONCEPT layouts for quotation and PO reference; the 3D model is the master for geometry.", ""]
    if missing:
        readme += ["Not included (reason):"] + [f"  - {m}" for m in missing]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", "\n".join(readme))
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue(), f"{code}_PO_pack.zip"
