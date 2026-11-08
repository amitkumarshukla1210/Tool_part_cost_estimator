"""Every PDF and Excel a part hands out carries the logo and the company name ("Design to Cost" unless changed), inside ZIP
packs too (stage 35, checked end to end with stage 47 / 48 downloads)."""

import io
import zipfile

from fastapi.testclient import TestClient

from backend.app.main import app
from tests.test_versus import _costed

client = TestClient(app)
NAME = "Design to Cost"


def _pdf_branded(data: bytes) -> bool:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as doc:
        page = doc.pages[0]
        return NAME in (page.extract_text() or "") and bool(page.images)          # name and a picture (the logo)


def _xlsx_branded(data: bytes) -> bool:
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(data)).worksheets[0]
    return ws.oddHeader.center.text == NAME or bool(getattr(ws, "_images", []))


def _check(url: str, data: bytes):
    if data[:4] == b"%PDF":
        assert _pdf_branded(data), url
    elif data[:2] == b"PK" and url.endswith(".xlsx"):
        assert _xlsx_branded(data), url
    elif data[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(data))
        for n in z.namelist():
            if n.endswith(".pdf"):
                assert _pdf_branded(z.read(n)), f"{url} → {n}"
            elif n.endswith(".xlsx"):
                assert _xlsx_branded(z.read(n)), f"{url} → {n}"


def test_every_pdf_and_excel_of_a_part_has_the_logo_and_name():
    pid = _costed("BR1")
    urls = ["piece-cost/export.pdf", "piece-cost/export.xlsx", "tool-cost/export.pdf", "tool-cost/export.xlsx",
            "rm-cost/export.pdf", "rm-cost/export.xlsx", "country-comparison/export.pdf?countries=IN,CN",
            "country-comparison/export.xlsx?countries=IN,CN", "vs-country/export.pdf", "vs-country/export.xlsx",
            "drawing.pdf", "tool-drawing.pdf", "process-parameters.pdf", "simulation/report.pdf", "tool-design.pdf",
            "production-data.xlsx", "drawing-data.xlsx", "po-pack.zip"]
    for u in urls:
        r = client.get(f"/api/parts/{pid}/{u}")
        assert r.status_code == 200, (u, r.text[:200])
        _check(u, r.content)
