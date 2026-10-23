"""Logo and the name "Design to Cost" on every downloaded Excel, PDF and PowerPoint file (also inside ZIP packs).

Applied centrally to the response of every download (see the middleware in main.py), so each exporter stays as it is:
    xlsx   three rows at the top of the first sheet with the logo and the name; "Design to Cost" in the print header of every sheet
    pdf    logo and name in the top margin of every page (pages that already carry the name are left alone)
    pptx   logo and name in the corner of every slide
    zip    the same for the xlsx / pdf / pptx files inside it
Files meant to be uploaded again (master-data downloads, templates) are not stamped: see SKIP.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

NAME = "Design to Cost"
TAGLINE = "Part Cost Estimator"
LOGO = Path(__file__).resolve().parents[2] / "theme" / "logo.png"
SKIP = ("/download", "/template.xlsx")           # round-trip files: the upload expects the plain layout
ROWS = 3


def _shift_rows(ws, n: int) -> None:
    merged = [str(m) for m in ws.merged_cells.ranges]
    for m in merged:
        ws.unmerge_cells(m)
    ws.insert_rows(1, n)
    from openpyxl.worksheet.cell_range import CellRange
    for m in merged:
        cr = CellRange(m)
        cr.shift(row_shift=n)
        ws.merge_cells(cr.coord)
    for img in getattr(ws, "_images", []):
        try:
            img.anchor._from.row += n
            if hasattr(img.anchor, "to") and img.anchor.to is not None:
                img.anchor.to.row += n
        except Exception:
            pass
    if ws.freeze_panes:
        from openpyxl.utils import coordinate_to_tuple, get_column_letter
        r, c = coordinate_to_tuple(ws.freeze_panes)
        ws.freeze_panes = f"{get_column_letter(c)}{r + n}"
    for r in sorted((k for k in ws.row_dimensions if isinstance(k, int)), reverse=True):
        if r + n not in ws.row_dimensions or True:
            ws.row_dimensions[r + n].height = ws.row_dimensions[r].height


def stamp_xlsx(data: bytes) -> bytes:
    from openpyxl import load_workbook
    from openpyxl.drawing.image import Image as XlImage
    from openpyxl.styles import Font
    wb = load_workbook(io.BytesIO(data))
    if not wb.worksheets:
        return data
    first = wb.worksheets[0]
    if str(first.cell(1, 2).value or "") == NAME:
        return data
    _shift_rows(first, ROWS)
    for r in range(1, ROWS + 1):
        first.row_dimensions[r].height = 16
    first.cell(1, 2, NAME).font = Font(bold=True, size=14, color="1F3A5F")
    first.cell(2, 2, TAGLINE).font = Font(color="6B7280")
    if LOGO.exists():
        img = XlImage(str(LOGO))
        img.width = img.height = 44
        first.add_image(img, "A1")
        first.column_dimensions["A"].width = max(first.column_dimensions["A"].width or 0, 8)
    for ws in wb.worksheets:
        ws.oddHeader.center.text = NAME
        ws.oddHeader.center.size = 10
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def stamp_pdf(data: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    try:
        rd = PdfReader(io.BytesIO(data))
        if not rd.pages:
            return data
        if NAME in (rd.pages[0].extract_text() or ""):
            return data
        wr = PdfWriter()
        for page in rd.pages:
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=(w, h))
            size = 7 * mm
            x, y = 6 * mm, h - size - 2 * mm
            if LOGO.exists():
                c.drawImage(str(LOGO), x, y, size, size, mask="auto")
            c.setFont("Helvetica-Bold", 9)
            c.setFillColorRGB(0.12, 0.23, 0.37)
            c.drawString(x + size + 2 * mm, y + 2.4 * mm, NAME)
            c.save()
            buf.seek(0)
            page.merge_page(PdfReader(buf).pages[0])
            wr.add_page(page)
        out = io.BytesIO()
        wr.write(out)
        return out.getvalue()
    except Exception:
        return data


def stamp_pptx(data: bytes) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    prs = Presentation(io.BytesIO(data))
    for slide in prs.slides:
        if any(getattr(s, "name", "") == "dtc_brand" for s in slide.shapes):
            continue
        if LOGO.exists():
            pic = slide.shapes.add_picture(str(LOGO), Inches(0.15), Inches(0.08), Inches(0.38), Inches(0.38))
            pic.name = "dtc_brand"
        tb = slide.shapes.add_textbox(Inches(0.58), Inches(0.12), Inches(2.5), Inches(0.3))
        tb.name = "dtc_brand_text"
        run = tb.text_frame.paragraphs[0].add_run()
        run.text = NAME
        run.font.size, run.font.bold = Pt(12), True
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def stamp_zip(data: bytes) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            content = src.read(info.filename)
            content = stamp(content, info.filename)
            z.writestr(info.filename, content)
    return out.getvalue()


def stamp(data: bytes, name: str) -> bytes:
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    fn = {"xlsx": stamp_xlsx, "pdf": stamp_pdf, "pptx": stamp_pptx, "zip": stamp_zip}.get(ext)
    if not fn:
        return data
    try:
        return fn(data)
    except Exception:
        return data


MEDIA = {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx", "application/pdf": "pdf",
         "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx", "application/zip": "zip"}
