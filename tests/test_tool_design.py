"""Roadmap stage 27: detailed tool design (3D + drawings), drawing settings, forming report and video, 3D correction."""

import io
import zipfile
from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from backend.app import part_fix, sim_report, unfold
from backend.app.geometry import load_step
from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)
SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def bracket(code="TD"):
    return add_part(project(code), "example_bracket_revA.step", "Galvanised steel GI", "sheet_metal_multistage", f"{code}-1")


def test_every_die_stage_is_designed_with_its_parts():
    pid = bracket("TD1")
    r = client.get(f"/api/parts/{pid}/tool-design")
    assert r.status_code == 200, r.text
    tools = r.json()["tools"]
    assert [t["key"] for t in tools] == ["blank", "pierce", "bend"]
    blank = {c["name"]: c for c in tools[0]["components"]}
    assert blank["Die plate"]["material"] == "D2 (1.2379)" and blank["Die plate"]["hardness"]
    assert blank["Blanking punch"]["qty"] == 1 and blank["Stock guide"]["qty"] == 2
    assert any(n.startswith("Guide pillar") and c["qty"] == 4 for n, c in blank.items())
    pierce = {c["name"]: c for c in tools[1]["components"]}
    assert pierce["Piercing punch Ø8.50"]["qty"] == 6                                 # one punch per hole of the part
    bend = {c["name"] for c in tools[2]["components"]}
    assert {"V-die block", "Bending punch"} <= bend


def test_release_pack_has_3d_of_every_part_and_drawings():
    pid = bracket("TD2")
    r = client.get(f"/api/parts/{pid}/tool-design.zip", params={"die": "blank"})
    assert r.status_code == 200, r.text
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "README.txt" in names
    assert any(n.endswith("_assembly.step") for n in names)
    parts = [n for n in names if "/3D/parts/" in n]
    assert len(parts) >= 12 and all(z.read(n)[:13] == b"ISO-10303-21;" for n in parts)
    pdf = next(n for n in names if n.endswith("_drawing_set.pdf"))
    assert z.read(pdf)[:4] == b"%PDF"
    dxf = next(n for n in names if n.endswith("_03_Die_plate.dxf"))
    doc = ezdxf.read(io.StringIO(z.read(dxf).decode()))
    msp = doc.modelspace()
    assert msp.query('HATCH[layer=="LOGO"]') and msp.query('TEXT[layer=="TITLE"]')        # logo and title block
    assert any("ISO 2768" in t.dxf.text for t in msp.query("TEXT"))                       # general tolerance
    assert any(n.endswith("_BOM.xlsx") for n in names)


def test_mould_is_designed_with_core_cavity_and_plates():
    pid = add_part(project("TD3"))
    r = client.get(f"/api/parts/{pid}/tool-design")
    assert r.status_code == 200, r.text
    (tool,) = r.json()["tools"]
    names = {c["name"] for c in tool["components"]}
    assert {"Cavity insert", "Core insert", "A plate (cavity side)", "B plate (core side)", "Top clamp plate",
            "Bottom clamp plate", "Ejector plate"} <= names
    assert any(n.startswith("Ejector pin") for n in names) and any(n.startswith("Sprue bush") for n in names)
    r = client.get(f"/api/parts/{pid}/tool-design.step")
    assert r.status_code == 200 and r.content[:13] == b"ISO-10303-21;"
    assert client.get(f"/api/parts/{pid}/tool-design.png").content[:4] == b"\x89PNG"


def test_drawing_settings_and_logo():
    r = client.put("/api/register-setup/drawing", json={"drawing_company": "ACME Tools", "drawing_checked_by": "QA"})
    assert r.status_code == 200 and r.json()["settings"]["drawing_company"] == "ACME Tools"
    png = (Path(__file__).resolve().parents[1] / "theme" / "logo.png").read_bytes()
    r = client.post("/api/register-setup/drawing/logo", files={"file": ("logo.png", png, "image/png")})
    assert r.status_code == 200 and r.json()["logo"] != "default"
    assert client.post("/api/register-setup/drawing/logo", files={"file": ("x.txt", b"not an image")}).status_code == 400
    assert client.get("/api/drawing-logo.png").content[:4] == b"\x89PNG"
    pid = bracket("TD4")
    dxf = client.get(f"/api/parts/{pid}/drawing.dxf").content.decode()
    assert "ACME Tools" in dxf
    assert client.delete("/api/register-setup/drawing/logo").json()["logo"] == "default"


def test_forming_report_pdf_and_video():
    pid = bracket("TD5")
    r = client.get(f"/api/parts/{pid}/forming-simulation.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    r = client.get(f"/api/parts/{pid}/forming-simulation.video")
    assert r.status_code == 200 and r.headers["content-type"] in ("video/mp4", "image/gif") and len(r.content) > 10000


def test_moulding_video_frames():
    pid = add_part(project("TD6"))
    from backend.app import register
    d, rev, res = register._simulate(pid)
    data, ext = sim_report.moulding_video(res, d, fps=2, size=(320, 180))
    assert ext in ("mp4", "gif") and len(data) > 1000


def test_bend_radius_correction_keeps_outside_size_and_matches_the_designer_rev_b():
    a = load_step(str(SAMPLES / "example_bracket_revA.step"))
    new, changes = part_fix.fix_bend_radius(a, 2.0, 2.0)
    assert changes == [{"from_mm": 0.5, "to_mm": 2.0, "angle_deg": 90.0}]
    bb0, bb1 = a.BoundingBox(), new.BoundingBox()
    assert (bb1.xlen, bb1.ylen, bb1.zlen) == pytest.approx((bb0.xlen, bb0.ylen, bb0.zlen), abs=0.01)
    b = load_step(str(SAMPLES / "example_bracket_revB.step"))        # the same correction made in CAD
    assert unfold.unfold(new, 2.0, 0.33)["length_mm"] == pytest.approx(unfold.unfold(b, 2.0, 0.33)["length_mm"], abs=0.01)
    sharp = load_step(str(SAMPLES / "sheet_metal_bracket.step"))      # sharp corner (no bend cylinders)
    s2, ch = part_fix.fix_bend_radius(sharp, 2.0, 2.0)
    assert ch[0]["from_mm"] == 0 and len(s2.Solids()) == 1
    with pytest.raises(part_fix.FixError):
        part_fix.fix_bend_radius(new, 2.0, 2.0)                       # nothing left to correct


def test_correction_released_as_a_new_revision():
    pid = bracket("TD7")
    pre = client.get(f"/api/parts/{pid}/correction").json()
    assert pre["changes"][0]["what"] == "inside bend radius" and pre["next_rev"] == "B"
    assert client.get(f"/api/parts/{pid}/correction.png").content[:4] == b"\x89PNG"
    assert client.get(f"/api/parts/{pid}/correction.step").content[:13] == b"ISO-10303-21;"
    r = client.post(f"/api/parts/{pid}/correction", json={"rev": "B"})
    assert r.status_code == 200, r.text
    d = client.get(f"/api/parts/{pid}").json()
    assert d["rev"] == "B" and len(d["revisions"]) == 2
    sim = client.get(f"/api/parts/{pid}/sheet-tools").json()
    assert not [p for p in sim["problems"] if p["check"] == "bend_radius"]
    assert client.get(f"/api/parts/{pid}/correction").status_code == 400            # nothing more to correct
