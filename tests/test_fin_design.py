"""Stage 58: fin die design from the part file - reading STEP / DXF / PDF, die size proposal, design and every output."""

import io
import zipfile

import ezdxf
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader

from backend.app import fin_design, fin_die, fin_die_draw
from backend.app.main import FIN_FILES, app

client = TestClient(app)


@pytest.fixture(scope="module")
def fin_step():
    return fin_design.fin_step({})                       # your IFB fin: Ø5.2 collars, 16 × 12.7 staggered, 2 rows × 24 holes, FPI 21


def _pdf(lines):
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i, line in enumerate(lines):
        c.drawString(40, 800 - 16 * i, line)
    c.save()
    return buf.getvalue()


def test_design_rules_shipped():
    assert fin_design.seed() == 0
    assert fin_design.rule("fin_foil_use_pct") == 80 and fin_design.rule("hole_tol") == "±0.03"


def test_read_step(fin_step):
    r = fin_design.read_part(fin_step, "fin.step")
    assert (r["source"], r["hole_d_mm"], r["tube_od_mm"], r["row_pitch_mm"], r["hole_pitch_mm"], r["fin_rows"], r["fin_holes"]) == \
        ("STEP", 5.2, 5.0, 12.7, 16.0, 2, 24)
    assert r["staggered"] and r["holes"] == 48 and r["foil_t_mm"] == 0.095 and r["fpi"] == 21.0
    assert (r["fin_l_mm"], r["fin_w_mm"]) == (384.0, 25.4)
    assert set(r["check"]) == {"tube_od_mm", "pattern"}           # the tube and the pattern are proposals to confirm


def test_read_step_other_fin():
    st = fin_design.fin_step({"tube_od_mm": 7, "hole_d_mm": 7.3, "row_pitch_mm": 18.19, "hole_pitch_mm": 21, "fin_rows": 3,
                              "fin_holes": 10, "staggered": False, "foil_t_mm": 0.105, "fpi": 18})
    r = fin_design.read_part(st, "fin7.stp")
    assert (r["hole_d_mm"], r["tube_od_mm"], r["row_pitch_mm"], r["hole_pitch_mm"], r["fin_rows"], r["fin_holes"], r["staggered"]) == \
        (7.3, 7.0, 18.19, 21.0, 3, 10, False)
    assert r["foil_t_mm"] == 0.105 and r["fpi"] == pytest.approx(18, abs=0.1)


def test_read_dxf():
    r = fin_design.read_part(fin_design.fin_dxf({}), "fin.dxf")
    assert (r["source"], r["hole_d_mm"], r["row_pitch_mm"], r["hole_pitch_mm"], r["fin_rows"], r["fin_holes"], r["staggered"]) == \
        ("DXF", 5.2, 12.7, 16.0, 2, 24, True)
    assert "foil_t_mm" in r["check"] and r["foil_t_mm"] is None    # a 2D drawing has no thickness: you type it


def test_read_pdf_text():
    pdf = _pdf(["Fin drawing  Ø5 x 66R x 4P (12.7*16)", "Hole size in fin Ø5.2 ±0.03", "Distance Between Holes in Row 16mm ±0.05",
                "Distance Between Rows 12.7mm ±0.05", "Fin thickness T=0.095mm", "FPI 21", "Louver fin, staggered"])
    r = fin_design.read_part(pdf, "fin.pdf")
    assert (r["hole_d_mm"], r["hole_pitch_mm"], r["row_pitch_mm"], r["foil_t_mm"], r["fpi"], r["pattern"], r["staggered"]) == \
        (5.2, 16.0, 12.7, 0.095, 21.0, "louver", True)
    assert r["tube_od_mm"] == 5.0 and r["die_rows_text"] == 66
    assert "hole_d_mm" in r["check"]                                # every value read from a PDF is to check


@pytest.mark.parametrize("content,name,msg", [(b"", "fin.dwg", "DWG"), (b"x", "fin.igs", "STEP"), (_pdf([]), "scan.pdf", "no text"),
                                              (b"not a step", "bad.step", "Could not read")])
def test_read_errors(content, name, msg):
    with pytest.raises(fin_design.ReadError, match=msg):
        fin_design.read_part(content, name)


def test_propose_from_press():
    p = fin_design.propose({})
    assert (p["press"], p["die_rows"], p["progressions"], p["foil_width_mm"]) == ("YKC-48SH-125", 66, 4, 848.2)   # = your IFB die
    assert fin_design.propose({"tube_od_mm": 7, "hole_d_mm": 7.3, "row_pitch_mm": 18.19})["progressions"] == 3
    assert fin_design.propose({"tube_od_mm": 9.52, "hole_d_mm": 9.9, "row_pitch_mm": 22})["progressions"] == 2
    big = fin_design.propose({"press": "YKC-60A-160"})               # 1200 mm foil: (960 − 10) ÷ 12.7 = 74 rows (whole 2-row fins)
    assert big["die_rows"] == 74 and big["press"] == "YKC-60A-160"
    assert fin_design.propose({"fin_rows": 3})["die_rows"] % 3 == 0


def test_to_spec_keeps_what_was_not_read():
    s = fin_design.to_spec({"hole_d_mm": 7.3, "tube_od_mm": 7, "fpi": None, "pattern": "slit", "staggered": False}, fin_die.default_spec())
    assert (s["hole_d_mm"], s["tube_od_mm"], s["fpi"], s["pattern"], s["staggered"]) == (7.3, 7, 21.0, "slit", False)


def test_design_parts_and_drawings():
    des = fin_die_draw.build({}, 7, "IFB louver")
    assert [st["name"] for st in des["stations"]] == ["Draw 1", "Draw 2", "Draw 3", "Pierce & burr", "Ironing", "Louver", "Reflare",
                                                       "Edge trim", "Pilot", "Row slit", "Feed (hitch finger)", "Cut-off"]
    drawings = [p["drawing"] for p in des["parts"]]
    assert len(drawings) == len(set(drawings)) and drawings[0] == "FD-7-01"
    pierce = next(p for p in des["parts"] if p["name"].startswith("Sub-die plate · station 4 Pierce"))
    assert len(pierce["holes"]) == 264 and pierce["material"] == fin_die.PX5
    punch = next(p for p in des["parts"] if p["name"] == "Pierce & burring punch")
    assert punch["qty"] == 264 and punch["material"] == fin_die.HAP and punch["hardness"] == "64 ±1 HRC"
    assert punch["dims"][0] == pytest.approx(0.6 * 5.2)              # pierce Ø = fin_pierce_factor × collar Ø
    plain = fin_die_draw.build({"pattern": "plain"})
    assert len(plain["stations"]) == 10 and not any("Louver" in p["name"] for p in plain["parts"])
    wavy = fin_die_draw.build({"pattern": "wavy"})
    assert any(p["name"].startswith("Wave forming die") for p in wavy["parts"]) and wavy["stations"][-1]["name"] == "Cut-off (rippled)"


def test_outputs():
    des = fin_die_draw.build({}, 7, "IFB louver")
    pdf = PdfReader(io.BytesIO(fin_die_draw.drawings_pdf(des)))
    assert len(pdf.pages) == 2 + len(des["parts"])
    text = pdf.pages[0].extract_text()
    assert "FD-7-00" in text and "Strip / station layout" in text
    strip = ezdxf.read(io.StringIO(fin_die_draw.strip_dxf(des).decode()))
    assert len(strip.modelspace().query("CIRCLE")) == 264 * 7      # holes drawn at 3 draw + pierce + iron + reflare + pilot stations
    with zipfile.ZipFile(io.BytesIO(fin_die_draw.dxf_zip(des))) as z:
        names = z.namelist()
    assert len(names) == 2 + len(des["parts"]) and any(n.startswith("FD-7-00_strip") for n in names)
    wb = load_workbook(io.BytesIO(fin_die_draw.bom_xlsx(des)))
    assert wb.sheetnames == ["Die BOM", "Drawings", "Stations"] and wb["Die BOM"].max_row == len(des["die"]["lines"]) + 1
    po = PdfReader(io.BytesIO(fin_die_draw.po_pack_pdf(des)))
    first = po.pages[0].extract_text()
    assert "PURCHASE ORDER PACK" in first and "Technical specification" in first and len(po.pages) > len(des["parts"]) + 2
    assert fin_die_draw.step_bytes(des).startswith(b"ISO-10303-21")
    assert fin_die_draw.stl_bytes(des)[:14] == b"Design to Cost"
    html = fin_die_draw.viewer_html(des)
    assert "FD-7" in html and "Pierce &amp; burring punch" in html or "Pierce & burring punch" in html


def test_api_read_save_design_and_files(fin_step):
    r = client.post("/api/fin-dies/read-part", files={"file": ("fin.step", fin_step)}, data={"spec": ""})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["read"]["hole_d_mm"] == 5.2 and body["spec"]["die_rows"] == 66 and body["proposal"]["progressions"] == 4
    assert client.post("/api/fin-dies/read-part", files={"file": ("fin.dwg", b"x")}).status_code == 400
    assert client.post("/api/fin-dies/propose", json={"spec": {}}).json()["die_rows"] == 66
    rec = client.post("/api/fin-dies", json={"name": "Fin from STEP", "spec": body["spec"], "part_file": body["file"], "read": body["read"]}).json()
    assert rec["part_file"]["name"] == "fin.step" and rec["read"]["fin_holes"] == 24
    d = client.get(f"/api/fin-dies/{rec['id']}/design").json()
    assert d["prefix"] == f"FD-{rec['id']}" and d["press"] == "YKC-48SH-125"
    assert d["spec"]["pattern"] == "plain" and len(d["stations"]) == 10     # the test fin has no louvers: read as plain
    for kind in FIN_FILES:
        res = client.get(f"/api/fin-dies/{rec['id']}/design/{kind}")
        assert res.status_code == 200 and len(res.content) > 1000, kind
    pdf = client.get(f"/api/fin-dies/{rec['id']}/design/po-pack.pdf")
    assert pdf.headers["content-disposition"] == 'attachment; filename="Fin_from_STEP_PO_pack.pdf"'
    assert client.get(f"/api/fin-dies/{rec['id']}/design/nothing").status_code == 404
