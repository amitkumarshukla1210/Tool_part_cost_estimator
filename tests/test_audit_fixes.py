"""Bugs found by the end-to-end audit (scripts/audit_e2e.py) and their fixes."""

from pathlib import Path

import pytest

from backend.app import master_data, mould_db, part_fix
from backend.app.geometry import load_step

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_every_material_has_the_rows_its_calculations_need():
    """A material that can be chosen must also be in the tables the costing reads (Sheet materials, Process windows)."""
    t = mould_db.tables()
    sheet = {r["material"] for r in t["sheet_materials"]}
    windows = {r["material"] for r in t["process_windows"]}
    missing = [f"{m['part_type']}: {m['material']} (Sheet materials)" for m in master_data.tables()["Materials"]
               if m["part_type"] == "sheet_metal" and m["material"] not in sheet]
    missing += [f"{m['part_type']}: {m['material']} (Process windows)" for m in master_data.tables()["Materials"]
                if m["part_type"] in ("plastic", "die_casting", "eps", "blow", "foundry") and m["material"] not in windows]
    assert not missing, missing


def test_draft_correction_never_crashes_on_faces_opencascade_rejects():
    """large_plastic_tub.step: BRepOffsetAPI_DraftAngle.Add threw Standard_ConstructionError (server error); now a clear FixError."""
    shape = load_step(str(SAMPLES / "large_plastic_tub.step"))
    try:
        part_fix.add_draft(shape, "z", 1.5)
    except part_fix.FixError:
        pass


def test_deep_drawing_steel_gets_sheet_tools():
    from tests.test_rm_cost import add_part, client, project
    pid = add_part(project("DDQ"), "large_sheet_tray.step", "CRCA D513 EDD (deep drawing)", "sheet_metal_multistage", "DDQ-1")
    r = client.get(f"/api/parts/{pid}/sheet-tools")
    assert r.status_code == 200, r.text
    assert client.post(f"/api/parts/{pid}/tool-cost", json={}).status_code == 200


def test_part_cost_explains_a_material_without_density():
    """Was a server error (KeyError 'weight'); RM and tool cost already explained it."""
    from tests.test_rm_cost import add_part, client, project
    pid = add_part(project("NOD"), code="NOD-1")
    for u in ("rm-cost", "tool-cost"):
        client.post(f"/api/parts/{pid}/{u}", json={})
    client.put(f"/api/parts/{pid}", json={"material": "NO SUCH MATERIAL"})
    r = client.post(f"/api/parts/{pid}/piece-cost", json={})
    assert r.status_code == 400 and "density" in r.json()["detail"]
