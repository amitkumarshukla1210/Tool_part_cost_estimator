import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app
from tests.test_design_loop import move
from tests.test_rm_cost import add_part, project

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


def test_part_drawing_pdf_and_dxf_of_the_current_revision():
    pid = add_part(project("DW1"), "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage", "DW-1")
    r = client.get(f"/api/parts/{pid}/drawing.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    r = client.get(f"/api/parts/{pid}/drawing.dxf")
    assert r.status_code == 200 and b"SECTION" in r.content and b"LINE" in r.content
    assert client.get(f"/api/parts/{pid}/drawing.png").status_code in (400, 404)


def test_tool_drawing_per_die_stage_and_po_pack():
    pid = add_part(project("DW2"), "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage", "DW-2")
    dies = client.get(f"/api/parts/{pid}/tool-cost/trace").json()["dies"]
    for d in dies:
        r = client.get(f"/api/parts/{pid}/tool-drawing.pdf", params={"die": d["key"]})
        assert r.status_code == 200 and r.content[:4] == b"%PDF", r.text
        r = client.get(f"/api/parts/{pid}/tool-drawing.dxf", params={"die": d["key"]})
        assert r.status_code == 200 and b"SECTION" in r.content
    r = client.get(f"/api/parts/{pid}/po-pack.zip")
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "README.txt" in names
    assert any(n.startswith("01_part/") and n.endswith(".step") for n in names)
    assert any(n.startswith("01_part/") and n.endswith("drawing.pdf") for n in names)
    assert sum(1 for n in names if n.startswith("02_tool/stage") and n.endswith("drawing.pdf")) == len(dies)
    assert any(n.startswith("03_cost/") for n in names)


def test_mould_drawing_for_a_plastic_part():
    pid = add_part(project("DW3"))
    r = client.get(f"/api/parts/{pid}/tool-drawing.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    names = zipfile.ZipFile(io.BytesIO(client.get(f"/api/parts/{pid}/po-pack.zip").content)).namelist()
    assert any("mould" in n and n.endswith(".pdf") for n in names)


def test_forward_move_after_a_revision_is_not_a_step_back():
    pid = add_part(project("DW4"))
    for s, c in (("concept_tool", ""), ("simulation", ""), ("corrections_required", "thick boss")):
        assert move(pid, s, c).status_code == 200
    with open(ROOT / "samples" / "plastic_cover.step", "rb") as fh:
        client.post(f"/api/parts/{pid}/revisions", files={"file": ("plastic_cover.step", fh)}, data={"rev": "B", "change_note": "x"})
    loop = move(pid, "simulation").json()                     # revised -> simulation: the next step, no comment needed
    assert loop["status"] == "simulation" and not loop["timeline"][-1].get("step_back")


def test_work_instruction_and_example_files_are_served():
    r = client.get("/static/docs/DTC_Work_Instruction.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    for f in ("example_bracket_revA.step", "EX26-0001_PO_pack.zip", "EX26-0001_stage1_blank_tool_drawing.pdf"):
        assert client.get(f"/static/docs/example/{f}").status_code == 200
    help_page = client.get("/help").text
    assert "DTC_Work_Instruction.pdf" in help_page and "every category" in help_page
