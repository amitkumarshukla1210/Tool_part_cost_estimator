"""Logo, company name and copyright footer on every Excel and PDF the software hands out, also inside ZIP packs (stage 35;
header position and footer: stage 67).

Applied centrally to the response of a download (middleware in main.py), so each exporter stays as it is:
    xlsx   every sheet: two new rows at the top with the logo and the company name (the sheet's own content starts in row 3;
           formulas, merged cells, frozen panes, filters, validations, conditional formats and pictures move with it), the
           copyright line under the data, and the name / copyright in the printed page header / footer
    pdf    every page: logo and name in the top margin (a page that already shows the name, e.g. a drawing title block, keeps
           its own) and the copyright line at the bottom
    zip    the same for the xlsx and pdf files inside it
Files meant to be filled in and uploaded again (UPLOAD: master-data, rates and setup downloads, the import template, the price
master, the drawing data) keep their cells: only the printed page header and footer are added.
The logo and name are those of the drawings (drawing_style.py: Admin → Drawings); the footer text is FOOTER.
"""

from __future__ import annotations

import io
import re
import zipfile
from functools import lru_cache

FOOTER = "Copyright © 2026 Design to Cost, all rights reserved"
UPLOAD = ("/download", "/template.xlsx", "/price-master/export.xlsx", "/drawing-data.xlsx")
UPLOAD_NAMES = ("drawing_data.xlsx", "drawing-data.xlsx")          # inside ZIP packs
SKIP = UPLOAD                                                    # stage 35 name, kept for callers
MEDIA = {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx", "application/pdf": "pdf", "application/zip": "zip"}
MARK = "dtc-branded"
HEAD_ROWS = 2


def _brand() -> tuple:
    from . import drawing_style
    return str(drawing_style.logo_path()), drawing_style.settings()["company"]


@lru_cache(maxsize=4)
def _banner_png(logo: str, name: str) -> bytes:
    """Logo with the name next to it, as one picture for Excel."""
    from PIL import Image, ImageDraw, ImageFont
    h = 48
    lg = Image.open(logo).convert("RGBA")
    lg.thumbnail((h, h))
    font = None
    for f in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        try:
            font = ImageFont.truetype(f, 22)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    w = lg.width + 12 + int(ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(name, font=font)) + 8
    im = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    im.paste(lg, (0, (h - lg.height) // 2), lg)
    ImageDraw.Draw(im).text((lg.width + 12, h // 2), name, font=font, fill=(21, 34, 56, 255), anchor="lm")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- Excel ----------

_REF = re.compile(r"(\$?)([A-Za-z]{1,3})(\$?)(\d+)")


def _shift_ref(text: str, n: int) -> str:
    """A1 references in a range text (Sheet!A1:B5, 'My sheet'!$C$3) with every row + n."""
    sheet, bang, ref = text.rpartition("!")
    return sheet + bang + _REF.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{int(m.group(4)) + n}", ref)


def _shift_formula(f: str, n: int) -> str:
    """Every cell reference of a formula + n rows (all sheets of the workbook move by the same n)."""
    from openpyxl.formula.tokenizer import Token, Tokenizer
    tok = Tokenizer(f if f.startswith("=") else "=" + f)
    for t in tok.items:
        if t.type == Token.OPERAND and t.subtype == Token.RANGE:
            t.value = _shift_ref(t.value, n)
    out = tok.render()
    return out if f.startswith("=") else out[1:]


def _shift_range(ref: str, n: int) -> str:
    return " ".join(_shift_ref(r, n) for r in str(ref).split())


def _shift_sheet(ws, n: int) -> None:
    """Move the whole sheet down n rows, with everything that points at its cells."""
    from openpyxl.formatting.formatting import ConditionalFormattingList
    from openpyxl.utils import get_column_letter
    max_r, max_c = ws.max_row, ws.max_column
    merged = [str(r) for r in ws.merged_cells.ranges]
    for r in merged:
        ws.unmerge_cells(r)
    heights = {r: (d.height, d.hidden, d.outlineLevel) for r, d in list(ws.row_dimensions.items()) if r <= max_r}
    if ws._cells:
        ws.move_range(f"A1:{get_column_letter(max_c)}{max_r}", rows=n)
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str) and c.value.startswith("="):
                try:
                    c.value = _shift_formula(c.value, n)
                except Exception:  # noqa: BLE001 - a formula the tokenizer cannot read stays as it was
                    pass
    for r in merged:
        ws.merge_cells(_shift_range(r, n))
    for r in sorted(heights, reverse=True):
        h, hidden, lvl = heights[r]
        d = ws.row_dimensions[r + n]
        d.height, d.hidden, d.outlineLevel = h, hidden, lvl
    for r in range(1, n + 1):
        ws.row_dimensions[r].height, ws.row_dimensions[r].hidden, ws.row_dimensions[r].outlineLevel = None, False, 0
    if ws.freeze_panes:
        col, row = re.match(r"([A-Z]+)(\d+)", ws.freeze_panes).groups()
        ws.freeze_panes = f"{col}{int(row) + n}" if int(row) > 1 else ws.freeze_panes
    if ws.auto_filter.ref:
        ws.auto_filter.ref = _shift_range(ws.auto_filter.ref, n)
    for dv in ws.data_validations.dataValidation:
        dv.sqref = _shift_range(str(dv.sqref), n)
        for attr in ("formula1", "formula2"):
            v = getattr(dv, attr)
            if v:
                setattr(dv, attr, _shift_formula(v, n))
    old = ws.conditional_formatting
    new = ConditionalFormattingList()
    for cf in old:
        for rule in cf.rules:
            rule.formula = [_shift_formula(x, n) for x in (rule.formula or [])]
            new.add(_shift_range(str(cf.sqref), n), rule)
    ws.conditional_formatting = new
    for img in list(getattr(ws, "_images", [])):
        a = img.anchor
        if isinstance(a, str):
            img.anchor = _shift_ref(a, n)
        else:
            for part in (getattr(a, "_from", None), getattr(a, "to", None)):
                if part is not None:
                    part.row += n
    if ws.print_title_rows:
        a, _, b = ws.print_title_rows.partition(":")
        ws.print_title_rows = f"{int(a) + n}:{int(b or a) + n}"


def _print_header_footer(ws, name: str) -> None:
    for hf in (ws.oddHeader, ws.evenHeader, ws.firstHeader):
        hf.center.text, hf.center.size = name, 10
    for hf in (ws.oddFooter, ws.evenFooter, ws.firstFooter):
        hf.center.text, hf.center.size = FOOTER, 8


def stamp_xlsx(data: bytes, upload: bool = False) -> bytes:
    from openpyxl import load_workbook
    from openpyxl.drawing.image import Image as XlImage
    from openpyxl.styles import Font
    logo, name = _brand()
    wb = load_workbook(io.BytesIO(data))
    sheets = [ws for ws in wb.worksheets if hasattr(ws, "iter_rows")]
    if not sheets or MARK in (wb.properties.keywords or ""):
        return data
    if upload:                                   # filled in and uploaded again: cells stay where they are
        if sheets[0].oddFooter.center.text == FOOTER:
            return data
        for ws in sheets:
            _print_header_footer(ws, name)
    else:
        if any(getattr(ws, "_charts", None) for ws in sheets):      # charts keep their cells (their series point at them)
            moved = False
        else:
            moved = True
            for ws in sheets:
                _shift_sheet(ws, HEAD_ROWS)
        for ws in sheets:
            if moved:
                img = XlImage(io.BytesIO(_banner_png(logo, name)))
                img.height, img.width = 32, int(32 * img.width / img.height)
                img._dtc_brand = True
                ws.add_image(img, "A1")
                ws.row_dimensions[1].height = 27
                ws.row_dimensions[2].height = 6
            last = ws.max_row
            cell = ws.cell(last + 2, 1, FOOTER)
            cell.font = Font(name="Arial", size=8, italic=True, color="666666")
            _print_header_footer(ws, name)
    wb.properties.keywords = ((wb.properties.keywords or "") + " " + MARK).strip()
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- PDF ----------

def stamp_pdf(data: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    logo, name = _brand()
    rd = PdfReader(io.BytesIO(data))
    if not rd.pages:
        return data
    texts = [(p.extract_text() or "") for p in rd.pages]
    if all("all rights reserved" in t for t in texts):
        return data
    wr = PdfWriter()
    for page, text in zip(rd.pages, texts):
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        x0, y0 = float(page.mediabox.left), float(page.mediabox.bottom)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(w + x0, h + y0))
        if name not in text:                                    # a page that shows the name already keeps its own header
            size = 7 * mm
            x, y = x0 + 6 * mm, y0 + h - size - 2 * mm
            c.drawImage(logo, x, y, size, size, mask="auto", preserveAspectRatio=True)
            c.setFont("Helvetica-Bold", 9)
            c.setFillColorRGB(0.08, 0.13, 0.22)
            c.drawString(x + size + 2 * mm, y + 2.4 * mm, name)
        if "all rights reserved" not in text:
            c.setFont("Helvetica", 6.5)
            c.setFillColorRGB(0.4, 0.4, 0.4)
            c.drawCentredString(x0 + w / 2, y0 + 2.2 * mm, FOOTER)
        c.save()
        buf.seek(0)
        page.merge_page(PdfReader(buf).pages[0])
        wr.add_page(page)
    out = io.BytesIO()
    wr.write(out)
    return out.getvalue()


def stamp_zip(data: bytes) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            z.writestr(info, stamp(src.read(info.filename), info.filename,
                                   upload=info.filename.lower().endswith(UPLOAD_NAMES)))
    return out.getvalue()


def stamp(data: bytes, name: str, upload: bool = False) -> bytes:
    """The file with the brand; unchanged when it cannot be read (a download must never fail because of the logo).
    upload = a file that is filled in and uploaded again: only the printed header and footer."""
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    fn = {"xlsx": lambda d: stamp_xlsx(d, upload), "pdf": stamp_pdf, "zip": stamp_zip}.get(ext)
    if not fn:
        return data
    try:
        return fn(data)
    except Exception as exc:                     # say why in the server window (a missing library left PDFs without the logo)
        import logging
        logging.getLogger("dtc.branding").warning("Logo and name not added to %s: %s: %s", name, exc.__class__.__name__, exc)
        return data
