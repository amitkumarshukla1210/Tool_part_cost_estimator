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


def test_two_cavity_mould_drawing_set_builds_and_cuts_are_noted_on_their_part():
    """A 2-cavity mould: the B / support plate hole table and the technical data overflowed the page (LayoutError);
    the cut labels (runner, cooling) were added to every plate through the shared notes list."""
    from backend.app import register
    from tests.test_rm_cost import add_part, project
    pid = add_part(project("DW2C"), "plastic_cover.step", "ABS", "injection_moulding", "DW2C-1")
    client.put(f"/api/parts/{pid}/cavities", json={"cavities": 2})
    r = client.get(f"/api/parts/{pid}/tool-design.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    des = register.tool_designs(pid)[2][0][1]
    notes = {c.name: c.notes for c in des["components"]}
    assert not any("Runner" in n for n in notes["Support plate"]) and not any("Runner" in n for n in notes["Bottom clamp plate"])


def _pages(pdf: bytes) -> list[str]:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return [p.extract_text() or "" for p in doc.pages]


def test_every_drawing_of_a_large_mould_is_one_sheet_and_the_hole_table_stays_on_it():
    """A large PP mould: the B plate (48 holes), support and ejector retainer plates ran their hole table and title block on
    to the next page (17 pages for 11 drawings). Now one sheet per drawing; every hole and the title block are on it."""
    from backend.app import register
    pid = add_part(project("DW1S"), "large_plastic_tub.step", "PP (polypropylene)", "injection_moulding", "DW1S-1")
    r = client.get(f"/api/parts/{pid}/tool-design.pdf")
    assert r.status_code == 200
    des = register.tool_designs(pid)[2][0][1]
    made = [c for c in des["components"] if c.kind == "made" and c.drawing != "none"]
    pages = _pages(r.content)
    assert len(pages) == 1 + len(made)
    assert "TOOL ASSEMBLY" in pages[0] and f"1 / {len(pages)}" in pages[0]
    for k, c in enumerate(made, start=2):
        text = pages[k - 1]
        assert f"{c.no} · {c.name}" in text and f"{k} / {len(pages)}" in text and "General" in text, c.name     # title block on it
        if len(c.holes) > 22:                                                       # hole table under the views
            assert all(f"H{i}" in text for i in range(1, len(c.holes) + 1)), c.name
    assert max(len(c.holes) for c in made) > 22                                     # the case that overflowed is in it

