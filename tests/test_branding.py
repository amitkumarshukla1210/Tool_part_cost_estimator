"""Stage 35: logo and company name on every Excel and PDF download (and inside ZIP packs); round-trip files stay plain."""

import io
import zipfile

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from backend.app import branding
from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def _plain_xlsx() -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(["Part", "Cost"])
    wb.active.append(["A-1", 12.5])
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()


def test_excel_gets_the_header_rows_and_the_footer():
    """Stage 67: logo + name in two new top rows of every sheet (content from row 3), copyright under the data and in print."""
    out = branding.stamp(_plain_xlsx(), "x.xlsx")
    ws = load_workbook(io.BytesIO(out)).active
    assert [c.value for c in ws[3]] == ["Part", "Cost"] and ws.cell(4, 2).value == 12.5      # moved down two rows, unchanged
    img = ws._images[0]
    assert (img.anchor._from.row, img.anchor._from.col) == (0, 0) and ws.oddHeader.center.text == "Design to Cost"
    assert ws.cell(ws.max_row, 1).value == branding.FOOTER and ws.oddFooter.center.text == branding.FOOTER
    assert branding.FOOTER == "Copyright © 2026 Design to Cost, all rights reserved"
    assert branding.stamp(out, "x.xlsx") == out                                              # once only


def test_excel_formulas_merges_and_panes_move_with_the_rows():
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Cost"
    ws.append(["Title"]); ws.merge_cells("A1:C1")
    ws.append(["Item", "Qty", "Price", "Total"]); ws.append(["A", 2, 10, "=B3*C3"]); ws.append(["B", 3, 5, "=B4*$C$4"])
    ws.append(["Sum", None, None, "=SUM(D3:D4)"]); ws.freeze_panes = "A3"; ws.auto_filter.ref = "A2:D4"
    wb.create_sheet("Ref")["A1"] = "='Cost'!$D$5+1"
    buf = io.BytesIO(); wb.save(buf)
    out = load_workbook(io.BytesIO(branding.stamp(buf.getvalue(), "x.xlsx")))
    c = out["Cost"]
    assert [str(r) for r in c.merged_cells.ranges] == ["A3:C3"] and c.freeze_panes == "A5" and c.auto_filter.ref == "A4:D6"
    assert (c["D5"].value, c["D6"].value, c["D7"].value) == ("=B5*C5", "=B6*$C$6", "=SUM(D5:D6)")
    assert out["Ref"]["A3"].value == "='Cost'!$D$7+1"                                       # other sheets follow too


def test_files_uploaded_again_keep_their_cells():
    out = branding.stamp(_plain_xlsx(), "x.xlsx", upload=True)
    ws = load_workbook(io.BytesIO(out)).active
    assert [c.value for c in ws[1]] == ["Part", "Cost"] and not ws._images
    assert ws.oddHeader.center.text == "Design to Cost" and ws.oddFooter.center.text == branding.FOOTER


def test_pdf_without_the_name_is_stamped_once():
    buf = io.BytesIO(); c = canvas.Canvas(buf); c.drawString(100, 700, "plain report"); c.save()
    out = branding.stamp(buf.getvalue(), "x.pdf")
    text = PdfReader(io.BytesIO(out)).pages[0].extract_text()
    assert "Design to Cost" in text and branding.FOOTER in text                          # header and footer
    assert branding.stamp(out, "x.pdf") == out


def test_downloads_are_stamped_and_round_trip_files_are_not():
    p = project("BR1")
    add_part(p, code="BR1-1")
    ws = load_workbook(io.BytesIO(client.get("/api/parts/export.xlsx").content)).worksheets[0]
    assert ws.oddHeader.center.text == "Design to Cost" and ws._images
    md = load_workbook(io.BytesIO(client.get("/api/master-data/download").content)).worksheets[0]
    assert md["A1"].value and not md._images and md.oddFooter.center.text == branding.FOOTER   # uploaded again: cells stay
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("a.xlsx", _plain_xlsx())
    out = zipfile.ZipFile(io.BytesIO(branding.stamp(zbuf.getvalue(), "x.zip")))
    assert load_workbook(io.BytesIO(out.read("a.xlsx"))).active._images
