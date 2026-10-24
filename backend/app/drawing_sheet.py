"""Title block, technical data and revision history shared by the 2D drawings (PDF and DXF): tool assembly, tool part and strip layout.

meta = {title, number, rev, scale, release_date, approved_by, status, checksum, history: [{rev, date, text, by, approved}], example}
Every sheet shows the logo and the name "Design to Cost", release date, approved by, the projection (third angle) and the revision history.
A drawing of a draft or of a part without a released tool design says NOT RELEASED instead of a release date.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from . import branding

PROJECTION = "Third-angle projection"
HIST_ROWS = 7


def sheet_meta(design: dict | None, history: list[dict], title: str, number: str, rev: str, scale: str = "", checksum: str = "", example: bool = False) -> dict:
    """Release block of a drawing from the tool design it belongs to (None: not part of any design yet)."""
    released = design.get("released_at") if design else None
    if hasattr(released, "date"):
        released = released.date().isoformat()
    elif isinstance(released, str):
        released = released[:10]
    ok = bool(design and released and design.get("status") in ("released", "superseded"))
    return {"title": title, "number": number, "rev": rev, "scale": scale, "release_date": released if ok else "NOT RELEASED",
            "approved_by": (design.get("released_by") or "—") if ok else "— (not approved)", "status": design["status"] if design else "none",
            "checksum": checksum, "history": history, "example": example, "date": datetime.utcnow().date().isoformat()}


# ---------------------------------------------------------------- PDF

def pdf_projection(c, x, y, mm) -> None:
    """Third-angle projection symbol: side view of a cone left, its circular view to the right of it."""
    c.saveState()
    c.translate(x, y); c.scale(0.7, 0.7); c.translate(-x, -y)
    c.setLineWidth(0.5)
    c.line(x, y, x, y + 7 * mm)
    c.line(x, y, x + 9 * mm, y + 1.5 * mm)
    c.line(x, y + 7 * mm, x + 9 * mm, y + 5.5 * mm)
    c.line(x + 9 * mm, y + 1.5 * mm, x + 9 * mm, y + 5.5 * mm)
    c.line(x + 4.5 * mm, y - 0.5 * mm, x + 4.5 * mm, y + 7.5 * mm)
    c.setDash(1, 1)
    c.circle(x + 15 * mm, y + 3.5 * mm, 1.6 * mm)
    c.setDash()
    c.circle(x + 15 * mm, y + 3.5 * mm, 3.5 * mm)
    c.line(x + 10.5 * mm, y + 3.5 * mm, x + 19.5 * mm, y + 3.5 * mm)
    c.restoreState()


def pdf_title_block(c, right: float, bottom: float, meta: dict, theme, rows: list[tuple] | None = None, width: float = 160) -> float:
    """Draw the title block at the lower right (mm from the page corner); returns its height in mm. rows: extra [(label, value, label, value)] lines."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Table, TableStyle
    st = meta["status"]
    cells = [["Release date", meta["release_date"], "Approved by", meta["approved_by"]],
             ["Drawing no.", meta["number"], "Revision", meta["rev"]],
             ["Title", meta["title"], "Scale", meta.get("scale") or "-"],
             *[list(r) for r in (rows or [])],
             ["Projection", "", "Printed", meta["date"]]]
    cells = [[(str(x)[:26] + "…" if len(str(x)) > 27 and i == 1 else x) if i % 2 == 1 else x for i, x in enumerate(r)] for r in cells]
    t = Table(cells, colWidths=[23 * mm, (width - 23 - 21 - 26) * mm, 21 * mm, 26 * mm], rowHeights=6.2 * mm)
    style = [("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.4, theme["ink"]), ("BACKGROUND", (0, 0), (0, -1), theme["alt"]),
             ("BACKGROUND", (2, 0), (2, -1), theme["alt"]), ("FONTNAME", (1, 1), (1, 1), "Helvetica-Bold"), ("FONTSIZE", (1, 1), (1, 1), 10),
             ("SPAN", (1, len(cells) - 1), (1, len(cells) - 1))]
    if meta["release_date"] == "NOT RELEASED":
        style += [("TEXTCOLOR", (1, 0), (1, 0), colors.HexColor("#b91c1c")), ("FONTNAME", (1, 0), (1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    w, h = t.wrapOn(c, 0, 0)
    brand_h = 12 * mm
    x0 = right * mm - w
    t.drawOn(c, x0, bottom * mm)
    # brand band over the table: logo and name
    c.setStrokeColor(theme["ink"]); c.setLineWidth(0.4); c.setFillColor(colors.white)
    c.rect(x0, bottom * mm + h, w, brand_h, stroke=1, fill=1)
    if branding.LOGO.exists():
        c.drawImage(str(branding.LOGO), x0 + 1.5 * mm, bottom * mm + h + 1 * mm, 10 * mm, 10 * mm, mask="auto")
    c.setFillColor(theme["ink"]); c.setFont("Helvetica-Bold", 13)
    c.drawString(x0 + 14 * mm, bottom * mm + h + 5.5 * mm, branding.NAME)
    c.setFont("Helvetica", 6.5); c.setFillColor(theme["grey"])
    c.drawString(x0 + 14 * mm, bottom * mm + h + 2 * mm, f"{branding.TAGLINE} · {PROJECTION}")
    if st in ("draft", "none"):
        c.setFillColor(colors.HexColor("#b91c1c")); c.setFont("Helvetica-Bold", 9)
        c.drawRightString(x0 + w - 2 * mm, bottom * mm + h + 5 * mm, "DRAFT · NOT FOR PRODUCTION")
    c.setStrokeColor(theme["ink"]); c.setFillColor(theme["ink"])
    pdf_projection(c, x0 + 27 * mm, bottom * mm + 1.0 * mm, mm)
    return (h + brand_h) / mm


def pdf_history(c, left: float, bottom: float, history: list[dict], theme, width: float = 150, rows: int = HIST_ROWS) -> float:
    """Revision history table (newest at the bottom, the last `rows` shown); returns height in mm."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle
    small = ParagraphStyle("hs", parent=getSampleStyleSheet()["Normal"], fontSize=6.3, leading=7.2)
    shown = history[-rows:]
    data = [["Rev", "Date", "Change", "By", "Approved"]]
    if len(history) > rows:
        data.append(["…", "", f"{len(history) - rows} earlier change(s): see the drawing data sheet (Excel)", "", ""])
    data += [[h["rev"], h["date"], Paragraph(str(h["text"])[:160], small), str(h["by"])[:14], str(h["approved"])[:14]] for h in shown] or [["A", "", "First issue", "", ""]]
    t = Table(data, colWidths=[9 * mm, 17 * mm, (width - 9 - 17 - 22 - 22) * mm, 22 * mm, 22 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 6.3), ("BACKGROUND", (0, 0), (-1, 0), theme["head"]), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("GRID", (0, 0), (-1, -1), 0.2, theme["border"]), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 1.5), ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
                           ("TOPPADDING", (0, 0), (-1, -1), 0.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.6)]))
    w, h = t.wrapOn(c, 0, 0)
    c.setFont("Helvetica-Bold", 7.5); c.setFillColor(theme["ink"])
    c.drawString(left * mm, bottom * mm + h + 1.2 * mm, "REVISION HISTORY")
    t.drawOn(c, left * mm, bottom * mm)
    return h / mm + 5


# ---------------------------------------------------------------- DXF

@lru_cache(maxsize=1)
def _logo_runs() -> list[tuple]:
    """Run-length rectangles of the logo (48 × 48 cells): [(col, row, run, aci)]; dark 250, orange 30, white 7."""
    from PIL import Image
    if not branding.LOGO.exists():
        return []
    im = Image.open(branding.LOGO).convert("RGBA").resize((48, 48))
    def aci(p):
        r, g, b, a = p
        if a < 100:
            return None
        if r > 180 and g < 170 and b < 100:
            return 30
        return 250 if r + g + b < 300 else 7
    runs = []
    for y in range(48):
        x = 0
        while x < 48:
            k = aci(im.getpixel((x, y)))
            x2 = x
            while x2 < 48 and aci(im.getpixel((x2, y))) == k:
                x2 += 1
            if k is not None and k != 7:
                runs.append((x, 47 - y, x2 - x, k))
            x = x2
    return runs


def dxf_title_block(doc, msp, x: float, y: float, meta: dict, size: float = 1.0, extra: list[str] | None = None) -> None:
    """Title block with the vector logo, name, release data, projection note and the revision history as text lines, lower-left corner at (x, y).
    size scales the whole block (1.0 = 3.5 mm text)."""
    if "TITLE" not in doc.layers:
        doc.layers.add("TITLE", color=7)
    a = {"layer": "TITLE"}
    k = size
    cell = 0.22 * k
    for cx, ry, run, col in _logo_runs():
        x0, y0 = x + cx * cell, y + ry * cell
        msp.add_solid([(x0, y0), (x0 + run * cell, y0), (x0, y0 + cell), (x0 + run * cell, y0 + cell)], dxfattribs={"layer": "TITLE", "color": col})
    tx = x + 48 * cell + 3 * k
    top = y + 48 * cell
    msp.add_text(branding.NAME, dxfattribs=a | {"height": 6 * k}).set_placement((tx, top - 7 * k))
    msp.add_text(f"{branding.TAGLINE} · {PROJECTION}", dxfattribs=a | {"height": 2.2 * k}).set_placement((tx, top - 11.5 * k))
    lines = [f"Drawing no.: {meta['number']}   Rev: {meta['rev']}   {meta['title']}",
             f"Release date: {meta['release_date']}   Approved by: {meta['approved_by']}",
             f"Projection: {PROJECTION} (symbol: cone, side view left of the circle view)   Scale: {meta.get('scale') or '1:1 (as drawn)'}   Printed: {meta['date']}"]
    if meta.get("checksum"):
        lines.append(f"STEP checksum: sha256 {meta['checksum'][:24]}")
    if meta["status"] in ("draft", "none"):
        lines.append("DRAFT - NOT FOR PRODUCTION")
    lines += (extra or [])
    ty = y - 5 * k
    for t in lines:
        msp.add_text(t, dxfattribs=a | {"height": 3 * k}).set_placement((x, ty))
        ty -= 4.6 * k
    ty -= 2 * k
    msp.add_text("REVISION HISTORY", dxfattribs=a | {"height": 3.4 * k}).set_placement((x, ty))
    ty -= 5 * k
    msp.add_text("Rev | Date | Change | By | Approved", dxfattribs=a | {"height": 2.6 * k}).set_placement((x, ty))
    ty -= 4 * k
    for h in (meta["history"] or [{"rev": "A", "date": "", "text": "First issue", "by": "", "approved": ""}]):
        msp.add_text(f"{h['rev']} | {h['date']} | {h['text'][:150]} | {h['by']} | {h['approved']}", dxfattribs=a | {"height": 2.6 * k}).set_placement((x, ty))
        ty -= 4 * k
    # a frame around the logo
    msp.add_lwpolyline([(x, y), (x + 48 * cell, y), (x + 48 * cell, y + 48 * cell), (x, y + 48 * cell)], close=True, dxfattribs=a)


# ---------------------------------------------------------------- PDF flowables (assembly sheet, strip pack)

def flow_title(meta: dict, theme, width_mm: float = 390):
    """Title block as a flowable: logo + name, then drawing no., revision, release date, approved by, projection."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, Table, TableStyle
    ss = getSampleStyleSheet()
    big = ParagraphStyle("tb", parent=ss["Normal"], fontSize=13, leading=15, fontName="Helvetica-Bold", textColor=theme["ink"])
    sm = ParagraphStyle("ts", parent=ss["Normal"], fontSize=7, textColor=theme["grey"])
    red = meta["release_date"] == "NOT RELEASED"
    logo = Image(str(branding.LOGO), 10 * mm, 10 * mm) if branding.LOGO.exists() else ""
    head = [logo, [Paragraph(branding.NAME, big), Paragraph(f"{branding.TAGLINE} · {PROJECTION}", sm)],
            Paragraph(f"<b>{meta['title']}</b><br/>Drawing no. {meta['number']}", ParagraphStyle("tt", parent=ss["Normal"], fontSize=8.5, leading=10)),
            Paragraph(f"<b>Rev {meta['rev']}</b><br/>Scale {meta.get('scale') or 'n/a'}", ParagraphStyle("tr", parent=ss["Normal"], fontSize=8.5, leading=10)),
            Paragraph(f"Release date<br/><b><font color='{'#b91c1c' if red else '#152238'}'>{meta['release_date']}</font></b>", ParagraphStyle("td", parent=ss["Normal"], fontSize=8, leading=10)),
            Paragraph(f"Approved by<br/><b>{meta['approved_by']}</b>", ParagraphStyle("ta", parent=ss["Normal"], fontSize=8, leading=10))]
    ws = [13, 55, 120, 40, 40, 100]
    k = width_mm / sum(ws)
    t = Table([head], colWidths=[w * k * mm for w in ws])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, theme["ink"]), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BACKGROUND", (2, 0), (-1, 0), theme["alt"])]))
    return t


def flow_history(meta: dict, theme, width_mm: float = 390):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle
    small = ParagraphStyle("hs", parent=getSampleStyleSheet()["Normal"], fontSize=7, leading=8)
    rows = [["Rev", "Date", "Change", "By", "Approved"]] + [[h["rev"], h["date"], Paragraph(str(h["text"])[:200], small), h["by"], h["approved"]] for h in meta["history"]] \
        or [["Rev", "Date", "Change", "By", "Approved"], ["A", "", "First issue", "", ""]]
    t = Table(rows, colWidths=[w * width_mm / 390 * mm for w in (14, 24, 250, 50, 52)], repeatRows=1)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7), ("BACKGROUND", (0, 0), (-1, 0), theme["head"]), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("GRID", (0, 0), (-1, -1), 0.2, theme["border"]), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t
