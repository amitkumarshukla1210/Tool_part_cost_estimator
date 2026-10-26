"""Roadmap stage 28: large parts (10-20 kg, presses and moulding machines up to 3000-4000 t) and the tool-room audit gaps."""

import pytest
from fastapi.testclient import TestClient

from backend.app import part_fix, tool_cost
from backend.app.capacity import CapacityInput, calculate
from backend.app.geometry import load_step
from backend.app.main import app
from tests.test_rm_cost import SAMPLES, add_part, project

client = TestClient(app)


def test_large_part_gets_one_cavity_in_the_largest_base():
    r = calculate(CapacityInput(part_type="plastic", footprint_length_mm=1050, footprint_width_mm=700))
    assert r["cavities_per_tool"] == 1 and r["large_part"]


def test_large_tub_runs_on_a_big_moulding_machine():
    pid = add_part(project("LP1"), "large_plastic_tub.step", "PP (polypropylene)", "injection_moulding", "LP1-1")
    tr = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    m = tr["trial"]["machine"]
    assert m and int(m["machine_id"].split("-")[1]) >= 1000            # a 1000 t+ machine from the new range
    assert tr["value_inr"] > 0


def test_large_sheet_parts_use_the_large_sheet_and_heavy_presses():
    pid = add_part(project("LP2"), "large_sheet_tray.step", "Mild steel CRCA / HR", "sheet_metal_multistage", "LP2-1")
    s = client.get(f"/api/parts/{pid}/sheet-tools").json()
    codes = [o["code"] for o in s["operations"]]
    assert "draw" in " ".join(codes).lower() or any("draw" in (o.get("name") or "").lower() for o in s["operations"])
    assert all(o.get("press") for o in s["operations"])
    td = client.get(f"/api/parts/{pid}/tool-design").json()["tools"]
    names = {c["name"] for t in td for c in t["components"]}
    assert any("blank holder" in n.lower() for n in names)


def test_u_channel_gets_a_u_bending_die_with_a_pressure_pad():
    pid = add_part(project("LP3"), "large_sheet_channel.step", "Mild steel CRCA / HR", "sheet_metal_multistage", "LP3-1")
    td = client.get(f"/api/parts/{pid}/tool-design").json()["tools"]
    names = {c["name"].lower() for t in td for c in t["components"]}
    assert any("pressure pad" in n for n in names)


def test_foundry_has_tool_cost_and_pattern_design():
    pid = add_part(project("LP4"), material="Grey cast iron FG260", process="foundry", code="LP4-1")
    assert client.get(f"/api/parts/{pid}").json()["tool_capex_inr"] > 0
    (tool,) = client.get(f"/api/parts/{pid}/tool-design").json()["tools"]
    names = {c["name"].lower() for c in tool["components"]}
    assert any("pattern" in n for n in names) and any("flask" in n for n in names)


def test_no_machine_big_enough_still_reported():
    r = tool_cost.run(tool_cost.ToolInput(part_type="plastic", part_length_mm=100, part_width_mm=90, part_height_mm=30,
                                          projected_area_cm2=20000, part_weight_g=48.66, cavities=2))
    assert not r["priced"] and any("largest: 4000 t" in m for m in r["missing"])


def test_draft_correction_for_moulded_parts():
    shape = load_step(str(SAMPLES / "plastic_cover.step"))
    new, changes = part_fix.add_draft(shape, "z", 1.5)
    assert changes and len(new.Solids()) >= 1
    bb0, bb1 = shape.BoundingBox(), new.BoundingBox()
    assert bb1.zlen == pytest.approx(bb0.zlen, abs=0.5)
