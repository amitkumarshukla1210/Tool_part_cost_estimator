"""The look of every drawing (roadmap stage 27): logo, title block, tolerances, notes, signatures - PDF and DXF.

    Register settings   drawing_company, drawing_logo (uploaded on Admin → Drawings), drawing_projection,
                        drawing_drawn_by ('login user' = whoever downloads), drawing_checked_by, drawing_approved_by,
                        drawing_notes
    Design rules        general_tolerance, plate / fit / finish texts of the part type (Mould & die database)

PDF: a header with the logo and a title block (logo, company, drawing number, title, material, heat treatment, qty,
scale, sheet, revision, date, general tolerance, projection symbol, drawn / checked / approved).
DXF: the same title block drawn in model space at the lower right of a frame; the logo is drawn as solid hatches
(one per run of pixels of the same colour), so it stays inside the single DXF file.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOGO = ROOT / "theme" / "logo.png"
LOGO_NAME = "drawing_logo.png"


def settings() -> dict:
    from . import auth, register_setup
    s = register_setup.settings()
    drawn = s.get("drawing_drawn_by") or "login user"
    if drawn == "login user":
        drawn = auth.username() or "-"
    return {"company": s.get("drawing_company") or "Design to Cost", "projection": s.get("drawing_projection") or "Third angle",
            "drawn": drawn, "checked": s.get("drawing_checked_by") or "-", "approved": s.get("drawing_approved_by") or "-",
            "notes": s.get("drawing_notes") or "", "logo": s.get("drawing_logo") or "default"}


def logo_path() -> Path:
    from . import register_setup
    name = register_setup.settings().get("drawing_logo") or "default"
    if name != "default":
        p = register_setup.storage_root() / name
        if p.exists():
            return p
    return DEFAULT_LOGO


def save_logo(content: bytes) -> str:
    """Store an uploaded logo (PNG / JPG / GIF / BMP) as the drawing logo; returns its file name."""
    from PIL import Image
    from . import register_setup
    try:
        im = Image.open(io.BytesIO(content))
        im.load()
    except Exception:
        raise ValueError("The logo must be an image file (PNG, JPG, GIF or BMP).") from None
    im = im.convert("RGBA")
    if max(im.size) > 600:
        im.thumbnail((600, 600))
    root = register_setup.storage_root()
    root.mkdir(parents=True, exist_ok=True)
    im.save(root / LOGO_NAME, "PNG")
    data = register_setup.tables()
    for r in data["register_settings"]:
        if r["key"] == "drawing_logo":
            r["value"] = LOGO_NAME
    if not any(r["key"] == "drawing_logo" for r in data["register_settings"]):
        data["register_settings"].append({"key": "drawing_logo", "value": LOGO_NAME, "description": "Drawings: logo file"})
    register_setup.write(data)
    return LOGO_NAME


def reset_logo() -> None:
    from . import register_setup
    data = register_setup.tables()
    for r in data["register_settings"]:
        if r["key"] == "drawing_logo":
            r["value"] = "default"
    register_setup.write(data)


def tolerances(part_type: str) -> dict:
    """Text rules of the part type (general tolerance, fits, finishes, notes) from Mould & die database → Design rules."""
    from . import mould_db
    rules = mould_db.design_rules(part_type) if part_type else {}
    out = {k: (r["text"] or (f"{r['value']:g}" if r["value"] is not None else "")) for k, r in rules.items()}
    out.setdefault("general_tolerance", "ISO 2768-mK")
    return out


# ---------- PDF ----------

def _logo_image(h_mm: float):
    from reportlab.lib.units import mm
    from reportlab.platypus import Image
    from PIL import Image as PImage
    p = logo_path()
    w, h = PImage.open(p).size
    return Image(str(p), h_mm * mm * w / h, h_mm * mm)


def _projection_symbol(size: float, first_angle: bool):
    """ISO 128 projection symbol: third angle = cone (large end left) with its end view (two circles) at the right;
    first angle = the mirror image."""
    from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon
    W, h, y0 = size * 2.4, size * 0.8, size * 0.1
    cone = [0, y0, 0, y0 + h, size, y0 + h * 0.75, size, y0 + h * 0.25]
    cx = size * 1.85
    if first_angle:
        cone = [W - x if i % 2 == 0 else x for i, x in enumerate(cone)]
        cx = W - cx
    d = Drawing(W, size)
    d.add(Polygon(cone, fillColor=None, strokeWidth=0.6))
    d.add(Circle(cx, y0 + h / 2, h / 2, fillColor=None, strokeWidth=0.6))
    d.add(Circle(cx, y0 + h / 2, h / 4, fillColor=None, strokeWidth=0.6))
    d.add(Line(0, y0 + h / 2, W, y0 + h / 2, strokeWidth=0.3, strokeDashArray=[2, 1]))
    return d


def pdf_header(st, kicker: str, title: str):
    """Logo and company at the left, kicker and title next to it."""
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle
    s = settings()
    t = Table([[_logo_image(11), [Paragraph(f"{s['company']} · {kicker}", st["k"]), Paragraph(title, st["h1"])]]],
              colWidths=[16 * mm, None])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def pdf_title_block(width: float, rows: list[tuple[str, str]], part_type: str = "", scale: str = "", sheet: str = "1 / 1",
                    drawing_no: str = "", rev: str = "", extra_notes: list[str] | None = None, release: dict | None = None,
                    history: list[dict] | None = None, general_tolerance: str | None = None):
    """Title block: logo + company | fields (2 columns) | tolerance, projection, scale, sheet, signatures.
    release (drawing_data.release, stage 31): release date and approved by from the design loop; history: revision table under it."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle
    from .pdf_report import _theme
    theme = _theme()
    s = settings()
    tol = tolerances(part_type)
    small = ParagraphStyle("tb", fontSize=7, leading=8.5)
    bold = ParagraphStyle("tbb", fontSize=7, leading=8.5, fontName="Helvetica-Bold")
    P = lambda x, st=small: Paragraph(str(x), st)
    lw, rw = (44 * mm, 78 * mm) if width > 250 * mm else (32 * mm, 58 * mm)     # A3 / A4
    left = Table([[_logo_image(14 if width > 250 * mm else 10)], [P(s["company"], bold)], [P(f"Drawing no. <b>{drawing_no}</b>", small)],
                  [P(f"Rev <b>{rev or '-'}</b>", small)]], colWidths=[lw])
    left.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 1),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    half = (len(rows) + 1) // 2
    pairs = []
    for i in range(half):
        a = rows[i]
        b = rows[i + half] if i + half < len(rows) else ("", "")
        pairs.append([P(a[0], bold), P(a[1]), P(b[0], bold), P(b[1])])
    mid_w = width - lw - rw
    mid = Table(pairs, colWidths=[mid_w * 0.17, mid_w * 0.33, mid_w * 0.17, mid_w * 0.33])
    mid.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, theme["border"]), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("BACKGROUND", (0, 0), (0, -1), theme["alt"]), ("BACKGROUND", (2, 0), (2, -1), theme["alt"]),
                             ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    first = s["projection"].lower().startswith("first")
    approved = s["approved"]
    rel_rows = []
    if release is not None:
        approved = release["by"] if release["released"] else s["approved"]
        red = "" if release["released"] else "<font color='#b91c1c'><b>NOT RELEASED</b></font> · "
        rel_rows = [[P("Released", bold), P(release["date"] if release["released"] else f"{red}design loop: {release['status']}")]]
    right = Table([[P("General tolerance", bold), P(general_tolerance or tol["general_tolerance"])],
                   [P("Projection", bold), _projection_symbol(6 * mm, first)],
                   [P("Scale", bold), P(scale or "as shown")], [P("Sheet", bold), P(sheet)],
                   [P("Drawn", bold), P(f"{s['drawn']} · {date.today().isoformat()}")],
                   [P("Checked", bold), P(s["checked"])], [P("Approved", bold), P(approved)]] + rel_rows,
                  colWidths=[22 * mm, rw - 22 * mm])
    right.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, theme["border"]), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    outer = Table([[left, mid, right]], colWidths=[lw, mid_w, rw])
    outer.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.9, theme["ink"]), ("LINEBEFORE", (1, 0), (2, 0), 0.6, theme["ink"]),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
    notes = [n for n in ([s["notes"]] if s["notes"] else []) + list(extra_notes or []) if n]
    parts = []
    if notes:
        parts.append([Paragraph("<b>Notes:</b> " + " · ".join(f"{i}. {n}" for i, n in enumerate(notes, start=1)),
                                ParagraphStyle("nt", fontSize=7, leading=9))])
    if history is not None:
        parts.append([pdf_history(width, history)])
    if not parts:
        return outer
    return Table(parts + [[outer]], colWidths=[width], style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                                                                        ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))


HISTORY_ROWS = 6


def pdf_history(width: float, history: list[dict]):
    """Revision history (stage 31): the last HISTORY_ROWS changes, newest at the bottom."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle
    from .pdf_report import _theme
    theme = _theme()
    small = ParagraphStyle("hs", fontSize=6.5, leading=7.5)
    rows = [["Rev", "Date", "Revision history: change", "By"]]
    if len(history) > HISTORY_ROWS:
        rows.append(["…", "", f"{len(history) - HISTORY_ROWS} earlier change(s): see the drawing data sheet (Excel)", ""])
    rows += [[h["rev"], h["date"], Paragraph(str(h["text"])[:180], small), str(h["by"])[:24]] for h in history[-HISTORY_ROWS:]] \
        or [["-", "", "First issue", ""]]
    t = Table(rows, colWidths=[12 * mm, 22 * mm, width - 74 * mm, 40 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 6.5), ("GRID", (0, 0), (-1, -1), 0.25, theme["border"]),
                           ("BACKGROUND", (0, 0), (-1, 0), theme["head"]), ("TEXTCOLOR", (0, 0), (-1, 0), theme["head_text"]),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 0.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8)]))
    return t


# ---------- DXF ----------

def _logo_runs(max_px: int = 40):
    """The logo as runs of same-coloured pixels: (row, col_start, col_end, (r, g, b)), row 0 at the top."""
    from PIL import Image
    im = Image.open(logo_path()).convert("RGBA")
    im.thumbnail((max_px, max_px))
    w, h = im.size
    q = im.convert("RGB").quantize(colors=8).convert("RGB")
    alpha = im.getchannel("A")
    runs = []
    for y in range(h):
        x = 0
        while x < w:
            if alpha.getpixel((x, y)) < 128:
                x += 1
                continue
            c = q.getpixel((x, y))
            x1 = x
            while x1 + 1 < w and alpha.getpixel((x1 + 1, y)) >= 128 and q.getpixel((x1 + 1, y)) == c:
                x1 += 1
            runs.append((y, x, x1 + 1, c))
            x = x1 + 1
    return runs, w, h


def dxf_logo(msp, x: float, y: float, size: float, layer: str = "LOGO") -> None:
    """Draw the logo as solid hatches inside a size × size square whose lower-left corner is (x, y)."""
    runs, w, h = _logo_runs()
    px = size / max(w, h)
    for row, c0, c1, rgb in runs:
        yy = y + (h - row - 1) * px
        hatch = msp.add_hatch(dxfattribs={"layer": layer})
        hatch.rgb = rgb
        hatch.paths.add_polyline_path([(x + c0 * px, yy), (x + c1 * px, yy), (x + c1 * px, yy + px), (x + c0 * px, yy + px)])


def dxf_frame(doc, msp, w: float, h: float, title: str, rows: list[tuple[str, str]], part_type: str = "", scale: str = "1:1",
              drawing_no: str = "", rev: str = "", sheet: str = "1 / 1", margin: float = 10, extra_notes: list[str] | None = None,
              release: dict | None = None, history: list[dict] | None = None, general_tolerance: str | None = None):
    """Frame around (0, 0)-(w, h) (model units, mm) with the title block at its lower right; returns the title block height.
    release / history (stage 31): release date, approved by (design loop) and the revision history above the title block."""
    s = settings()
    tol = tolerances(part_type)
    for name, col in (("FRAME", 7), ("TITLE", 7), ("LOGO", 7)):
        if name not in doc.layers:
            doc.layers.add(name, color=col)
    fx0, fy0, fx1, fy1 = -margin, -margin, w + margin, h + margin
    msp.add_lwpolyline([(fx0, fy0), (fx1, fy0), (fx1, fy1), (fx0, fy1), (fx0, fy0)], dxfattribs={"layer": "FRAME", "lineweight": 50})
    tb_w, row_h = 180.0, 7.0
    approved = s["approved"]
    rel = []
    if release is not None:
        approved = release["by"] if release["released"] else s["approved"]
        rel = [("Released", release["date"] if release["released"] else f"NOT RELEASED (design loop: {release['status']})")]
    fields = [("Title", title), ("Drawing no.", drawing_no), ("Rev", rev or "-")] + list(rows) + [
        ("General tolerance", general_tolerance or tol["general_tolerance"]), ("Projection", s["projection"]), ("Scale", scale), ("Sheet", sheet),
        ("Drawn", f"{s['drawn']} {date.today().isoformat()}"), ("Checked", s["checked"]), ("Approved", approved)] + rel
    n = len(fields)
    tb_h = max(n * row_h, 40)
    x0, y0 = fx1 - tb_w, fy0
    T = lambda x, y, text, hgt=2.5: msp.add_text(str(text)[:70], dxfattribs={"layer": "TITLE", "height": hgt}).set_placement((x, y))
    msp.add_lwpolyline([(x0, y0), (fx1, y0), (fx1, y0 + tb_h), (x0, y0 + tb_h), (x0, y0)], dxfattribs={"layer": "TITLE"})
    logo_w = 40.0
    msp.add_line((x0 + logo_w, y0), (x0 + logo_w, y0 + tb_h), dxfattribs={"layer": "TITLE"})
    dxf_logo(msp, x0 + 5, y0 + tb_h - 35, 30)
    T(x0 + 3, y0 + 4, s["company"], 2.8)
    for i, (k, v) in enumerate(fields):
        yy = y0 + tb_h - (i + 1) * row_h
        msp.add_line((x0 + logo_w, yy), (fx1, yy), dxfattribs={"layer": "TITLE"})
        T(x0 + logo_w + 2, yy + 2, k)
        T(x0 + logo_w + 38, yy + 2, v)
    msp.add_line((x0 + logo_w + 36, y0), (x0 + logo_w + 36, y0 + tb_h), dxfattribs={"layer": "TITLE"})
    notes = [x for x in ([s["notes"]] if s["notes"] else []) + list(extra_notes or []) if x]
    for i, note in enumerate(notes):
        T(fx0 + 4, fy0 + 4 + i * 5, f"{i + 1}. {note}", 2.5)
    if history is not None:
        shown = (history or [{"rev": "-", "date": "", "text": "First issue", "by": ""}])[-HISTORY_ROWS:]
        hy = y0 + tb_h + 3
        for hrow in reversed(shown):
            msp.add_text(f"{hrow['rev']} | {hrow['date']} | {str(hrow['text'])[:90]} | {hrow['by']}", dxfattribs={"layer": "TITLE", "height": 2.2}).set_placement((x0, hy))
            hy += 4
        T(x0, hy + 1, "REVISION HISTORY  (rev | date | change | by)", 2.8)
        tb_h += hy + 6 - (y0 + tb_h)
    return tb_h
