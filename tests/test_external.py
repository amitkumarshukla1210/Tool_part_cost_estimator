import io
import stat

import ezdxf
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from backend.app import bom_extract, external
from backend.app.main import app

client = TestClient(app)

ROWS = [("Item", "Part number", "Description", "Qty", "Length (mm)"), ("1", "FLRY-B-0.5", "Wire FLRY 0.5 mm2", "4", "350"),
        ("2", "1-967640-1", "Connector housing", "2", ""), ("3", "TUBE-12", "Corrugated tube", "1", "")]
XS = [20, 120, 240, 420, 500]


def tsv_for(rows, bad_word=None):
    """What Tesseract would print (word boxes) for a table laid out on a grid."""
    out = ["level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"]
    for ri, row in enumerate(rows):
        for ci, text in enumerate(row):
            for wi, word in enumerate(text.split()):
                conf = 40 if word == bad_word else 95
                out.append(f"5\t1\t1\t1\t{ri + 1}\t{wi + 1}\t{XS[ci] + wi * 40}\t{20 + ri * 24}\t30\t12\t{conf}\t{word}")
    return "\n".join(out)


def test_ocr_words_become_a_table_with_cell_confidence():
    table, conf = external.grid_from_boxes(external._tsv_boxes(tsv_for(ROWS, bad_word="350")))
    assert table[0] == ["Item", "Part number", "Description", "Qty", "Length (mm)"]
    assert table[1] == ["1", "FLRY-B-0.5", "Wire FLRY 0.5 mm2", "4", "350"] and conf[1][4] == 0.4
    lines = bom_extract.table_to_lines(table, "scan", conf)
    assert [l["category"] for l in lines] == ["wire", "connector", "sleeve"]
    assert lines[0]["qty"] == 4 and lines[0]["length_mm"] == 1400 and lines[0]["confidence"] == 0.4
    assert "OCR: least sure word 40%" in lines[0]["flags"] and lines[1]["confidence"] == 1.0


def scanned_pdf():
    buf = io.BytesIO()
    Image.new("RGB", (400, 200), "white").save(buf, format="PNG")
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    c.drawImage(ImageReader(io.BytesIO(buf.getvalue())), 50, 500, 300, 150)
    c.save()
    return out.getvalue()


def test_scanned_pdf_without_tesseract_says_how_to_install(monkeypatch):
    monkeypatch.setattr(external, "tesseract", lambda: None)
    with pytest.raises(bom_extract.ExtractError, match="Tesseract is not installed"):
        bom_extract.parse_pdf(scanned_pdf())
    r = client.post("/api/bom-extracts", files={"file": ("scan.pdf", scanned_pdf())})
    assert r.status_code == 400 and "Install Tesseract" in r.json()["detail"]


def test_scanned_pdf_with_tesseract_uses_the_ocr_table(monkeypatch):
    monkeypatch.setattr(external, "tesseract", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(external, "page_tsv", lambda png: tsv_for(ROWS))
    lines = bom_extract.parse_pdf(scanned_pdf())
    assert len(lines) == 3 and lines[0]["source"].startswith("scan page 1 (OCR)")
    monkeypatch.setattr(external, "page_tsv", lambda png: tsv_for([("a", "b", "c")]))
    with pytest.raises(bom_extract.ExtractError, match="found no BOM table"):
        bom_extract.parse_pdf(scanned_pdf())


def test_image_upload_goes_through_ocr(monkeypatch):
    monkeypatch.setattr(external, "tesseract", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(external, "page_tsv", lambda png: tsv_for(ROWS))
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, format="PNG")
    e = bom_extract.extract(buf.getvalue(), "scan.png")
    assert e["format"] == "image (OCR)" and len(e["lines"]) == 3


def dxf_bytes():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for ri, row in enumerate(ROWS):
        for ci, text in enumerate(row):
            msp.add_text(text, dxfattribs={"height": 2.5, "insert": (XS[ci] / 4, 200 - ri * 6)})
    s = io.StringIO()
    doc.write(s)
    return s.getvalue().encode()


def test_dxf_text_grid_is_read():
    e = bom_extract.extract(dxf_bytes(), "bom.dxf")
    assert e["format"] == "DXF drawing" and [l["category"] for l in e["lines"]] == ["wire", "connector", "sleeve"]
    assert e["lines"][0]["part_number"] == "FLRY-B-0.5" and e["lines"][0]["length_mm"] == 1400
    empty = ezdxf.new("R2010")
    s = io.StringIO()
    empty.write(s)
    with pytest.raises(bom_extract.ExtractError, match="No BOM table"):
        bom_extract.extract(s.getvalue().encode(), "empty.dxf")


def test_dwg_without_converter_and_with_a_fake_one(monkeypatch, tmp_path):
    monkeypatch.setattr(external, "dwg_converter", lambda: None)
    with pytest.raises(bom_extract.ExtractError, match="needs a converter"):
        bom_extract.extract(b"AC1032", "drawing.dwg")
    (tmp_path / "bom.dxf").write_bytes(dxf_bytes())
    script = tmp_path / "dwg2dxf"
    script.write_text('#!/bin/sh\ncp "%s" "$2"\n' % (tmp_path / "bom.dxf"))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(external, "dwg_converter", lambda: (str(script), "libredwg"))
    e = bom_extract.extract(b"AC1032", "drawing.dwg")
    assert e["format"].startswith("DWG") and len(e["lines"]) == 3


def test_tools_status_endpoint():
    s = client.get("/api/bom-extract-tools").json()
    assert set(s) >= {"tesseract", "dwg_converter", "ocr_help", "dwg_help"}


@pytest.mark.skipif(not external.tesseract(), reason="Tesseract not installed")
def test_real_tesseract_round_trip():
    from PIL import ImageDraw
    img = Image.new("RGB", (900, 300), "white")
    d = ImageDraw.Draw(img)
    for ri, row in enumerate(ROWS):
        for ci, text in enumerate(row):
            d.text((20 + ci * 170, 20 + ri * 40), text, fill="black")
    buf = io.BytesIO()
    img.resize((1800, 600)).save(buf, format="PNG")
    assert external.ocr_image(buf.getvalue())
