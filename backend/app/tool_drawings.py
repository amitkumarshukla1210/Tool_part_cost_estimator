"""Manufacturing drawings of tool components and the tool assembly (roadmap stage 21).

One A3 sheet per made component: front / top / right views with overall dimensions, ballooned holes (H), openings (O) and pockets (P),
the tables that give their size and position from the datum corner, notes (steel, hardness, tolerances, finish, raw stock, route) and a
title block with the part number and drawing revision. The same views and tables go to a DXF. The assembly sheet shows the numbered
exploded tool and its bill of materials. Everything is read from the solid and from the component's class, nothing is typed per part.
"""

from __future__ import annotations

import io
import math
from datetime import date

import cadquery as cq
import numpy as np

from . import outputs3d

SCALES = [(1, 1), (1, 2), (1, 2.5), (1, 5), (1, 10), (1, 20), (1, 25), (1, 50), (1, 100)]
PAGE_W, PAGE_H = 420.0, 297.0          # A3 landscape, mm
VIEW_BOX = (15.0, 80.0, 275.0, 205.0)  # x, y, w, h of the area for the views (mm from the lower-left corner)


def _scale_for(L, W, H) -> tuple:
    gap = 38.0
    for n, d in SCALES:
        s = n / d
        if (L + W) * s + gap + 30 <= VIEW_BOX[2] and (H + W) * s + gap + 30 <= VIEW_BOX[3]:
            return n, d
    return SCALES[-1]


def _hole_view(axis: str) -> str:
    return {"z": "top", "y": "front", "x": "right"}[axis]


def _uv(view: str, p) -> tuple:
    """World / datum coordinates (x, y, z) -> the (u, v) of a view (front: x,z; top: x,y; right: y,z)."""
    x, y, z = p
    return {"front": (x, z), "top": (x, y), "right": (y, z)}[view]


def feature_items(info: dict) -> dict:
    """Numbered holes, openings and pockets: [{id, view, u, v, ...}] in datum coordinates, for drawing and tables."""
    f = info["features"]
    holes, n = [], 0
    for h in f["holes"]:
        for pos in h["positions_mm"]:
            n += 1
            holes.append({"id": f"H{n}", "dia": h["dia_mm"], "depth": h["depth_mm"], "through": h["through"], "axis": h["axis"], "pos": pos,
                          "thread": h.get("thread", "")})
    openings = [dict(o, id=f"O{i}") for i, o in enumerate(f["openings"], start=1)]
    pockets = [dict(p, id=f"P{i}") for i, p in enumerate(f["pockets"], start=1)]
    return {"holes": holes, "openings": openings, "pockets": pockets}


def _group_holes(holes: list[dict]) -> list[dict]:
    """Rows of the hole table: one row per hole (position from the datum)."""
    return [{"id": h["id"], "dia": h["dia"], "depth": h["depth"], "through": h["through"], "axis": h["axis"], "thread": h.get("thread", ""),
             "x": h["pos"][0], "y": h["pos"][1], "z": h["pos"][2]} for h in holes]


# ------------------------------------------------------------ PDF

def component_pdf(comp: dict, info: dict, shape: cq.Shape, head: dict, data: dict | None = None, meta: dict | None = None) -> bytes:
    """comp: {part_no, name, rev, qty, stage}; head: {part_code, part_name, tool, revision_label, status, country, project, date};
    data: effective technical data (drawing_data.effective); meta: title-block / release / revision history (drawing_sheet.sheet_meta)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph, Table, TableStyle
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from .pdf_report import _theme
    theme = _theme()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A3))
    views = outputs3d.three_views(shape)
    L, W, H = (info["bbox_mm"])
    n, d = _scale_for(L, W, H)
    s = n / d
    feats = feature_items(info)
    from . import drawing_data, drawing_sheet
    data = data or drawing_data.effective(info, None)
    ft = data.get("feature_tol") or drawing_data.feature_tolerances(info, data["tolerance_class"], {}, data.get("tolerance_unit", "mm"))
    dim_key = {"top": ("L", "W"), "front": ("L", "H"), "right": ("W", "H")}
    ss = getSampleStyleSheet()
    small = ParagraphStyle("s", parent=ss["Normal"], fontSize=7, leading=8.5)
    bb = shape.BoundingBox()
    org = (bb.xmin, bb.ymin, bb.zmin)
    vx0, vy0, vw, vh = VIEW_BOX
    gap = 30.0
    # placement of each view's datum corner on the sheet
    place = {"top": (vx0 + 12, vy0 + (H * s) + gap + 12 + (W * s) - (W * s)), "front": (vx0 + 12, vy0 + 12),
             "right": (vx0 + 12 + L * s + gap, vy0 + 12)}
    place["top"] = (vx0 + 12, vy0 + 12 + H * s + gap)

    def to_page(view, u, v):
        px, py = place[view]
        vb = views[view]["bounds"]
        return (px + (u - vb[0]) * s) * mm, (py + (v - vb[1]) * s) * mm

    c.setStrokeColor(theme["border"]); c.setLineWidth(0.6)
    c.rect(8 * mm, 8 * mm, (PAGE_W - 16) * mm, (PAGE_H - 16) * mm)
    for name in ("top", "front", "right"):
        v = views[name]
        c.setLineWidth(0.25); c.setStrokeColor(theme["grey"]); c.setDash(2, 1.5)
        for pl in v["hidden"]:
            p = c.beginPath()
            p.moveTo(*to_page(name, *pl[0]))
            for pt in pl[1:]:
                p.lineTo(*to_page(name, *pt))
            c.drawPath(p, stroke=1, fill=0)
        c.setDash()
        c.setLineWidth(0.5); c.setStrokeColor(theme["ink"])
        for pl in v["visible"]:
            p = c.beginPath()
            p.moveTo(*to_page(name, *pl[0]))
            for pt in pl[1:]:
                p.lineTo(*to_page(name, *pt))
            c.drawPath(p, stroke=1, fill=0)
        # overall dimensions
        x0, y0, x1, y1 = v["bounds"]
        ax, ay = to_page(name, x0, y0)
        bx, by = to_page(name, x1, y1)
        c.setStrokeColor(theme["brand"]); c.setFillColor(theme["brand"]); c.setLineWidth(0.3); c.setFont("Helvetica", 7)
        c.line(ax, ay - 6 * mm, bx, ay - 6 * mm)
        c.line(ax, ay - 8 * mm, ax, ay - 4 * mm); c.line(bx, ay - 8 * mm, bx, ay - 4 * mm)
        c.drawCentredString((ax + bx) / 2, ay - 9.5 * mm, f"{(x1 - x0):.2f} {ft['overall'][dim_key[name][0]]['text']}")
        c.line(ax - 6 * mm, ay, ax - 6 * mm, by)
        c.line(ax - 8 * mm, ay, ax - 4 * mm, ay); c.line(ax - 8 * mm, by, ax - 4 * mm, by)
        c.saveState(); c.translate(ax - 7.5 * mm, (ay + by) / 2); c.rotate(90); c.drawCentredString(0, 0, f"{(y1 - y0):.2f} {ft['overall'][dim_key[name][1]]['text']}"); c.restoreState()
        c.setFont("Helvetica-Bold", 8); c.drawString(ax, by + 3 * mm, {"top": "TOP", "front": "FRONT", "right": "RIGHT"}[name])
        # datum marker O at the minimum corner of the view
        c.setStrokeColor(colors.HexColor("#b91c1c")); c.setFillColor(colors.HexColor("#b91c1c"))
        c.circle(ax, ay, 1.2 * mm, stroke=1, fill=0); c.setFont("Helvetica-Bold", 6); c.drawString(ax + 1.8 * mm, ay + 1.2 * mm, "O")
    # balloons
    def balloon(view, u, v, label, color):
        px, py = to_page(view, u, v)
        c.setStrokeColor(color); c.setFillColor(color); c.setLineWidth(0.35)
        c.circle(px, py, 0.9 * mm, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 6); c.drawString(px + 1.4 * mm, py + 1.0 * mm, label)
    red, green, orange = colors.HexColor("#b91c1c"), colors.HexColor("#15803d"), colors.HexColor("#c2410c")
    for h in feats["holes"]:
        view = _hole_view(h["axis"])
        u, v = _uv(view, (h["pos"][0] + org[0], h["pos"][1] + org[1], h["pos"][2] + org[2]))
        balloon(view, u, v, h["id"], red)
    for o in feats["openings"]:
        balloon("top", o["x_mm"] + org[0] + o["length_mm"] / 2, o["y_mm"] + org[1] + o["width_mm"] / 2, o["id"], green)
    for p_ in feats["pockets"]:
        balloon("top", p_["x_mm"] + org[0] + p_["length_mm"] / 2, p_["y_mm"] + org[1] + p_["width_mm"] / 2, p_["id"], orange)
    # right column: the tables, above the revision history and the title block
    meta = meta or drawing_sheet.sheet_meta(None, [], comp["name"], comp["part_no"], comp["rev"], f"{n}:{d:g}", comp.get("sha", ""), bool(info.get("is_example")))
    meta = dict(meta, scale=f"{n}:{d:g}", checksum=meta.get("checksum") or comp.get("sha", ""))
    st = info["stock"]
    tb_rows = [("Tool", head["tool"], "Stage", str(comp["stage"]) if comp.get("stage") else "-"),
               ("Project / part", f"{head['project']} / {head['part_code']} {head['part_name']}"[:46], "Design", f"{head['status']} {head['revision_label']}"),
               ("Material", data["steel"][:28], "Qty / tool", str(comp.get("qty", 1))),
               ("Size (finished)", f"{L:g} × {W:g} × {H:g} mm", "Weight", f"{st['finished_weight_kg']:g} kg"),
               ("STEP sha256", f"{meta['checksum'][:24]}", "Sheet", "1 / 1")]
    tb_h = drawing_sheet.pdf_title_block(c, PAGE_W - 12, 12, meta, theme, tb_rows, width=113)
    hist_h = drawing_sheet.pdf_history(c, PAGE_W - 12 - 113, 12 + tb_h + 3, meta["history"], theme, width=113)
    y_min = 12 + tb_h + 3 + hist_h + 4
    RX = PAGE_W - 12 - 113

    def table(rows, widths, y_top, title):
        avail = y_top - 4 - y_min
        cap = max(3, int(avail // 4.4))
        if len(rows) > cap:
            rows = rows[:cap - 1] + [[f"+{len(rows) - cap + 1} more: see the DXF / Excel"] + [""] * (len(rows[0]) - 1)]
        c.setFont("Helvetica-Bold", 8); c.setFillColor(theme["ink"])
        c.drawString(RX * mm, y_top * mm, title)
        t = Table(rows, colWidths=[w * mm for w in widths], rowHeights=4.4 * mm)
        t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 6.5), ("BACKGROUND", (0, 0), (-1, 0), theme["head"]),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.2, theme["border"]),
                               ("LEFTPADDING", (0, 0), (-1, -1), 1.5), ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
                               ("TOPPADDING", (0, 0), (-1, -1), 0.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5)]))
        w, h = t.wrapOn(c, 0, 0)
        t.drawOn(c, RX * mm, y_top * mm - 1.5 * mm - h)
        return y_top - (h / mm) - 8
    y = PAGE_H - 18
    hole_rows = _group_holes(feats["holes"])
    unit = ft["unit"]
    if hole_rows:
        rows = [["ID", "Ø", "Ø tolerance", "Depth", "Thru", "Ax", "X", "Y", "Z", "Pos ±"]]
        for r in hole_rows:
            t = ft["holes"][r["id"]]
            size = (f"{r['thread']}-{t['size']['text']}" if t["rule"] == "hole_thread" and r["thread"] else t["size"]["text"])
            rows.append([r["id"], f"{r['dia']:g}", size[:20], f"{r['depth']:g}", "yes" if r["through"] else "no", r["axis"],
                         f"{r['x']:.2f}", f"{r['y']:.2f}", f"{r['z']:.2f}", t["pos"]["text"].replace(" µm", "")])
        y = table(rows, [8, 9, 24, 10, 8, 6, 13, 13, 13, 9], y, f"HOLES  (position from datum O; tolerances in {unit})")
    if feats["openings"] and y - 4 > y_min + 14:
        rows = [["ID", "X", "Y", "Length", "Width", "Size tol.", "Pos ±", "Contour"]] + [[o["id"], f"{o['x_mm']:.2f}", f"{o['y_mm']:.2f}", f"{o['length_mm']:.2f}",
                f"{o['width_mm']:.2f}", ft["openings"][o["id"]]["size"]["text"].replace(" µm", ""), ft["openings"][o["id"]]["pos"]["text"].replace(" µm", ""),
                f"{o['perimeter_mm']:.1f}"] for o in feats["openings"]]
        y = table(rows, [8, 15, 15, 15, 15, 18, 13, 13], y, f"OPENINGS  (wire cut / profile; tolerances in {unit})")
    if feats["pockets"] and y - 4 > y_min + 14:
        rows = [["ID", "X", "Y", "Length", "Width", "Depth", "Size tol.", "Pos ±"]] + [[p["id"], f"{p['x_mm']:.2f}", f"{p['y_mm']:.2f}", f"{p['length_mm']:.2f}",
                f"{p['width_mm']:.2f}", f"{p['depth_mm']:.2f}", ft["pockets"][p["id"]]["size"]["text"].replace(" µm", ""), ft["pockets"][p["id"]]["pos"]["text"].replace(" µm", "")]
                for p in feats["pockets"]]
        y = table(rows, [8, 15, 15, 15, 15, 13, 19, 12], y, f"POCKETS  (depth below the top face; tolerances in {unit})")
    radii = [f for f in info["features"]["fillets"] if f["radius_mm"] > 0][:8]
    if radii and y - 4 > y_min + 14:
        rows = [["R", "Type", "Length"]] + [[f"{f['radius_mm']:g}", "convex" if f["convex"] else "concave", f"{f['length_mm']:g}"] for f in radii]
        y = table(rows, [20, 25, 20], y, "RADII  (largest first)")
    # bottom-left strip: technical data, general tolerances, notes
    sy, sh = 12.0, 60.0           # bottom and height of the strip, mm
    def block(x, title, rows, widths, hdr=True):
        c.setFont("Helvetica-Bold", 8); c.setFillColor(theme["ink"]); c.drawString(x * mm, (sy + sh) * mm, title)
        t = Table(rows, colWidths=[w * mm for w in widths], rowHeights=4.6 * mm)
        sty = [("FONTSIZE", (0, 0), (-1, -1), 6.8), ("GRID", (0, 0), (-1, -1), 0.2, theme["border"]), ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
               ("RIGHTPADDING", (0, 0), (-1, -1), 1.5), ("TOPPADDING", (0, 0), (-1, -1), 0.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5)]
        sty += [("BACKGROUND", (0, 0), (-1, 0), theme["head"]), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)] if hdr else [("BACKGROUND", (0, 0), (0, -1), theme["alt"])]
        t.setStyle(TableStyle(sty))
        w_, h_ = t.wrapOn(c, 0, 0)
        t.drawOn(c, x * mm, (sy + sh) * mm - 1.5 * mm - h_)
        return h_ / mm
    ra = data["finish_ra"]
    block(15, "TECHNICAL DATA", [["Material grade", data["steel"]], ["Hardness", data["hardness"]], ["Heat treatment", data["heat_treatment"]],
                                 ["Surface treatment", data["surface_treatment"]], ["Surface roughness", f"Ra {ra:g} µm unless stated"],
                                 ["Gen. tolerance", data["general_tolerance_text"][:42]],
                                 ["Raw stock", f"{st['size_mm'][0]:g} × {st['size_mm'][1]:g} × {st['size_mm'][2]:g} mm"],
                                 ["Weight", f"{st['weight_kg']:g} kg raw · {st['finished_weight_kg']:g} kg finished"],
                                 ["Quantity", f"{comp.get('qty', 1)} per tool"], ["Edges", "Break 0.3 × 45° unless stated"]], [26, 64], hdr=False)
    block(110, f"TOLERANCES ISO 2768-{data['tolerance_class']} (± mm)",
          [["Linear size", "±"]] + [[r["range"], r["value"]] for r in data["linear_table"]], [30, 14])
    block(160, "ANGLES (±, shorter leg mm)", [["Shorter leg", "±"]] + [[r["range"], r["value"]] for r in data["angular_table"]], [28, 16])
    # notes: the fixed ones, then the reviewer's note points
    notes = ["1. All dimensions in mm. Datum O = minimum corner of the part. Dimensions are those of the 3D file whose checksum is in the title block.",
             f"2. Tolerances in {unit}: each dimension carries its own; a dimension without one is to {data['general_tolerance_text'].split(' · ')[0]} (table). Fits to ISO 286 (H7 = hole, g6 = shaft).",
             f"3. Route: {info['route']}.", "4. No marks on formed or sealing surfaces. Mark the part number on a non-functional face.",
             "5. Material certificate EN 10204 3.1 with the steel."]
    if any(views[k].get("simplified") for k in ("front", "top", "right")):
        notes.append("Views are simplified (bounding outline): too complex for hidden-line removal in the time allowed. The 3D STEP file and the hole table govern.")
    notes += [f"{6 + i}. {t}" for i, t in enumerate(data["notes"])]
    NX, NW = 206, 84
    c.setFont("Helvetica-Bold", 8); c.setFillColor(theme["ink"]); c.drawString(NX * mm, (sy + sh) * mm, "NOTES")
    py, floor = (sy + sh - 3) * mm, sy * mm
    for i, line in enumerate(notes):
        p = Paragraph(line, small)
        w, h = p.wrapOn(c, NW * mm, 40 * mm)
        if py - h < floor + 4 * mm and i < len(notes) - 1:
            c.setFont("Helvetica-Oblique", 6.5); c.setFillColor(colors.HexColor("#b91c1c"))
            c.drawString(NX * mm, py - 3 * mm, f"+ {len(notes) - i} more note point(s): see the drawing data sheet (Excel)")
            break
        p.drawOn(c, NX * mm, py - h)
        py -= h + 1 * mm
    c.setFont("Helvetica", 6); c.setFillColor(theme["grey"])
    c.drawString(15 * mm, 9.2 * mm, "Design to Cost · concept-level tool drawing generated from the 3D model: the 3D file governs; check before cutting steel"
                 + (" · EXAMPLE rates/rules" if info.get("is_example") else ""))
    c.showPage()
    c.save()
    return buf.getvalue()


# ------------------------------------------------------------ DXF

def component_dxf(comp: dict, info: dict, shape: cq.Shape, head: dict, data: dict | None = None, meta: dict | None = None) -> bytes:
    import ezdxf
    doc = ezdxf.new("R2010")
    for name, color, lt in (("VISIBLE", 7, "CONTINUOUS"), ("HIDDEN", 8, "DASHED"), ("DIM", 3, "CONTINUOUS"), ("HOLES", 1, "CONTINUOUS"),
                            ("TEXT", 5, "CONTINUOUS")):
        doc.layers.add(name, color=color, linetype=lt)
    msp = doc.modelspace()
    views = outputs3d.three_views(shape)
    L, W, H = info["bbox_mm"]
    gap = max(L, W, H) * 0.3
    origin = {"front": (0.0, 0.0), "top": (0.0, H + gap), "right": (L + gap, 0.0)}
    feats = feature_items(info)
    from . import drawing_data
    data = data or drawing_data.effective(info, None)
    ft = data.get("feature_tol") or drawing_data.feature_tolerances(info, data["tolerance_class"], {}, data.get("tolerance_unit", "mm"))
    dim_key = {"top": ("L", "W"), "front": ("L", "H"), "right": ("W", "H")}
    bb = shape.BoundingBox()
    org = (bb.xmin, bb.ymin, bb.zmin)
    for name, (ox, oy) in origin.items():
        v = views[name]
        x0, y0, x1, y1 = v["bounds"]
        for layer, key in (("VISIBLE", "visible"), ("HIDDEN", "hidden")):
            for pl in v[key]:
                msp.add_lwpolyline([(x - x0 + ox, y - y0 + oy) for x, y in pl], dxfattribs={"layer": layer})
        w, h = x1 - x0, y1 - y0
        tl, tw = (ft["overall"][k]["text"].replace("µm", "um") for k in dim_key[name])
        msp.add_linear_dim(base=(ox, oy - 12), p1=(ox, oy), p2=(ox + w, oy), text=f"<> {tl}", dimstyle="EZDXF", dxfattribs={"layer": "DIM"}).render()
        msp.add_linear_dim(base=(ox - 12, oy), p1=(ox, oy), p2=(ox, oy + h), angle=90, text=f"<> {tw}", dimstyle="EZDXF", dxfattribs={"layer": "DIM"}).render()
        msp.add_text(name.upper(), dxfattribs={"height": 5, "layer": "TEXT"}).set_placement((ox, oy + h + 6))
        msp.add_circle((ox, oy), 1.5, dxfattribs={"layer": "HOLES"})
        msp.add_text("O", dxfattribs={"height": 3, "layer": "HOLES"}).set_placement((ox + 2, oy + 2))

    def mark(view, u, v, label, radius):
        ox, oy = origin[view]
        x0, y0, _, _ = views[view]["bounds"]
        cx, cy = u - x0 + ox, v - y0 + oy
        msp.add_circle((cx, cy), max(radius, 0.4), dxfattribs={"layer": "HOLES"})
        msp.add_text(label, dxfattribs={"height": 3, "layer": "HOLES"}).set_placement((cx + radius + 1, cy + 1))
    for h in feats["holes"]:
        view = _hole_view(h["axis"])
        u, v = _uv(view, (h["pos"][0] + org[0], h["pos"][1] + org[1], h["pos"][2] + org[2]))
        t = ft["holes"][h["id"]]
        tol = t["size"]["text"].replace("µm", "um")
        mark(view, u, v, f"{h['id']} Ø{h['dia']:g} {tol}x{h['depth']:g}{' thru' if h['through'] else ''}{' ' + h['thread'] + ' tap' if h.get('thread') and not h['through'] else ''}"
             f" pos {t['pos']['text'].replace('µm', 'um')}", h["dia"] / 2)
    from . import drawing_sheet
    meta = meta or drawing_sheet.sheet_meta(None, [], comp["name"], comp["part_no"], comp["rev"], "1:1 (as drawn)", comp.get("sha", ""), bool(info.get("is_example")))
    meta = dict(meta, checksum=meta.get("checksum") or comp.get("sha", ""))
    st = info["stock"]
    y = -30.0
    notes = [f"TECHNICAL DATA  {comp['part_no']} rev {comp['rev']}  {comp['name']}  qty {comp.get('qty', 1)}",
             f"Material grade: {data['steel']}   Hardness: {data['hardness']}   Heat treatment: {data['heat_treatment']}   Surface treatment: {data['surface_treatment']}",
             f"Surface roughness: Ra {data['finish_ra']:g} um unless stated   General tolerances: {data['general_tolerance_text']}   Tolerances in {ft['unit'].replace('µm', 'um')}",
             "Linear (+/- mm): " + "  ".join(f"{r['range']}: {r['value']}" for r in data["linear_table"]),
             "Angular (+/- by shorter leg, mm): " + "  ".join(f"{r['range']}: {r['value']}" for r in data["angular_table"]),
             f"Raw stock {st['size_mm']} mm  {st['weight_kg']} kg (finished {st['finished_weight_kg']} kg)",
             f"Route: {info['route']}", f"Tool: {head['tool']}  design {head['status']} {head['revision_label']}"]
    for i, t in enumerate(data["notes"], start=1):
        notes.append(f"NOTE {i}: {t}")
    for t in notes:
        msp.add_text(t, dxfattribs={"height": 3.5, "layer": "TEXT"}).set_placement((0, y))
        y -= 6
    for o in feats["openings"]:
        msp.add_text(f"{o['id']} {o['length_mm']}x{o['width_mm']} {ft['openings'][o['id']]['size']['text'].replace('µm', 'um')} at X{o['x_mm']} Y{o['y_mm']} "
                     f"pos {ft['openings'][o['id']]['pos']['text'].replace('µm', 'um')} contour {o['perimeter_mm']}mm",
                     dxfattribs={"height": 3, "layer": "TEXT"}).set_placement((0, y))
        y -= 5
    for p in feats["pockets"]:
        msp.add_text(f"{p['id']} {p['length_mm']}x{p['width_mm']} {ft['pockets'][p['id']]['size']['text'].replace('µm', 'um')} depth {p['depth_mm']} at X{p['x_mm']} Y{p['y_mm']} "
                     f"pos {ft['pockets'][p['id']]['pos']['text'].replace('µm', 'um')}",
                     dxfattribs={"height": 3, "layer": "TEXT"}).set_placement((0, y))
        y -= 5
    drawing_sheet.dxf_title_block(doc, msp, 0.0, y - 25, meta, 1.0)
    s = io.StringIO()
    doc.write(s)
    return s.getvalue().encode()


# ------------------------------------------------------------ assembly sheet

def assembly_pdf(design: dict, bill: dict, parts: list[dict], head: dict, meta: dict | None = None) -> bytes:
    """Exploded 3D picture with item numbers, the bill of materials, bought-out parts and assembly steps. parts = [{shape, group, color,
    item(no. or None)}] in assembly coordinates."""
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer
    from .pdf_report import _table, _theme
    theme = _theme()
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=18, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=11, spaceBefore=8, spaceAfter=4)
    note = ParagraphStyle("n", parent=ss["Normal"], textColor=theme["grey"], fontSize=8)
    png = _exploded_png(parts, head)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A3), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Design to Cost - assembly {head['part_code']}")
    from . import drawing_sheet
    meta = meta or drawing_sheet.sheet_meta(design, [], f"Tool assembly {head['part_code']}", f"{head['part_code']}-ASM", head["revision_label"])
    story = [drawing_sheet.flow_title(meta, theme), Spacer(1, 3 * mm),
             Paragraph("TOOL ASSEMBLY", ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8)),
             Paragraph(f"{head['tool']} - {head['part_code']} {head['part_name']}", h1),
             Paragraph(f"Design {head['status']} {head['revision_label']} · {head['date']} · tool country {head['country']} · "
                       f"{bill['totals']['made_parts']} made parts, {len(bill['standard'])} bought-out items", note),
             Spacer(1, 3 * mm), Image(io.BytesIO(png), width=250 * mm, height=160 * mm), Paragraph("Bill of materials: made parts", h2)]
    rows = [["Item", "Part no.", "Name", "Rev", "Qty", "Steel", "Finished (mm)", "Stock (mm)", "Stock kg", "Hardness"]]
    for i, m in enumerate(bill["made"], start=1):
        inf = m["info"]
        rows.append([str(i), m["part_no"], m["name"], m["rev"], str(m["qty"]), inf["steel"], " × ".join(f"{x:g}" for x in inf["bbox_mm"]),
                     " × ".join(f"{x:g}" for x in inf["stock"]["size_mm"]), f"{inf['stock']['weight_kg']:g}", inf["hardness"]])
    story.append(_table(rows, theme, [14 * mm, 34 * mm, 55 * mm, 10 * mm, 10 * mm, 48 * mm, 45 * mm, 45 * mm, 18 * mm, 44 * mm]))
    story.append(Paragraph("Bill of materials: bought-out parts", h2))
    rows = [["Item", "Specification", "Qty", "Unit", "Unit cost (INR)", "Amount (INR)", "Source"]] + [
        [l["item"], l["spec"], str(l["quantity"]), l["unit"], f"{l['unit_cost_inr']:,.0f}", f"{l['amount_inr']:,.0f}", l["source"]] for l in bill["standard"]]
    story.append(_table(rows, theme, [60 * mm, 110 * mm, 15 * mm, 15 * mm, 30 * mm, 30 * mm, 40 * mm]))
    story.append(Paragraph("Assembly steps (in the toolroom)", h2))
    rows = [["Step", "Work", "Hours"]] + [[str(a["step"]), a["text"], f"{a['hours']:g}"] for a in bill["assembly"]]
    story.append(_table(rows, theme, [15 * mm, 300 * mm, 20 * mm]))
    story += [Paragraph("Revision history", h2), drawing_sheet.flow_history(meta, theme)]
    doc.build(story)
    return buf.getvalue()


def _exploded_png(parts: list[dict], head: dict) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    items = [p for p in parts if p["group"] in ("lower", "upper")]
    meshes = [(p, *outputs3d.mesh(p["shape"], 0.8)) for p in items]
    allv = np.concatenate([m[1] for m in meshes])
    span = (allv.max(0) - allv.min(0)).max()
    fig = plt.figure(figsize=(10, 6.4), dpi=110)
    ax = fig.add_subplot(111, projection="3d")
    lift = span * 0.35
    for p, v, f in meshes:
        v = v + np.array([0, 0, lift if p["group"] == "upper" else 0])
        tri = v[f]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n = n / np.where(np.linalg.norm(n, axis=1) > 0, np.linalg.norm(n, axis=1), 1)[:, None]
        light = np.clip(0.55 + 0.45 * (n @ np.array([0.4, -0.5, 0.75])), 0.25, 1.0)
        ax.add_collection3d(Poly3DCollection(tri, facecolors=np.clip(np.array(p["color"])[None, :] * light[:, None], 0, 1), edgecolor="none"))
    lo, hi = allv.min(0), allv.max(0) + np.array([0, 0, lift])
    mid, r = (lo + hi) / 2, (hi - lo).max() / 2
    ax.set_xlim(mid[0] - r, mid[0] + r); ax.set_ylim(mid[1] - r, mid[1] + r); ax.set_zlim(mid[2] - r, mid[2] + r)
    ax.view_init(24, -55); ax.set_axis_off()
    from mpl_toolkits.mplot3d import proj3d
    fig.canvas.draw()
    for p, v, f in meshes:
        if p.get("item"):
            c = v.mean(0) + np.array([0, 0, lift if p["group"] == "upper" else 0])
            x2, y2, _ = proj3d.proj_transform(c[0], c[1], c[2], ax.get_proj())
            fx, fy = ax.transAxes.inverted().transform(ax.transData.transform((x2, y2)))
            ax.text2D(fx, fy, str(p["item"]), transform=ax.transAxes, fontsize=9, ha="center", va="center", color="#152238", zorder=100,
                      bbox=dict(boxstyle="circle,pad=0.25", fc="white", ec="#1f5fa8", lw=0.9))
    b = io.BytesIO()
    fig.savefig(b, format="png", bbox_inches="tight")
    plt.close(fig)
    return b.getvalue()
