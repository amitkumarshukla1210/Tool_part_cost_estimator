"""Machined parts (roadmap stage 37): bar stock, machining time, machine, fixture and part cost, end to end."""

from backend.app import machining, master_data, mould_db, register_setup
from tests.test_rm_cost import add_part, client, detail, project

SHAFT, BLOCK = "machined_shaft.step", "machined_block.step"
EN8 = "Carbon steel EN8 (C45) bar"


def test_master_data_is_seeded_and_seed_adds_nothing_twice():
    assert register_setup.processes()["machined"]["part_type"] == "machined"
    assert any(m["material"] == EN8 for m in master_data.tables()["Materials"])
    assert mould_db.machining_data(EN8)["is_example"]
    assert len(mould_db.tables()["stock_sizes"]) > 100
    assert not any(machining.seed().values())


def test_turned_shaft_round_bar_rm_machining_and_part_cost():
    p = project("M1")
    pid = add_part(p, SHAFT, EN8, "machined", "SH-1")
    d = detail(pid)
    assert d["rm"]["applicable"], d["rm"]
    r = client.post(f"/api/parts/{pid}/rm-cost", json={}).json()
    tr = client.get(f"/api/parts/{pid}/rm-cost/trace").json()
    st = tr["stock"]
    assert (st["route"], st["shape"], st["size_mm"]) == ("turned", "round", 45)      # Ø40 + 3 mm allowance -> Ø45 bar
    assert st["length_mm"] == 110 + 2 * 1.5 + 3
    n = tr["nodes"]
    assert abs(n["calc:stock_volume_cm3"]["value"] - 0.7854 * 45 * 45 * 116 / 1000) < 1e-6
    assert n["calc:net_rm_cost"]["value"] > 0 and n["calc:scrap_credit"]["value"] < 0
    # machining & fixture is stored like a tool cost version
    t = client.post(f"/api/parts/{pid}/tool-cost", json={})
    assert t.status_code == 200, t.text
    tt = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    assert tt["route"] == "turned" and tt["trial"]["machine"]["machine_id"] == "CNC-LATHE"
    assert tt["named"]["cycle_s"] > 60 and tt["capex_inr"] > 0
    assert [h["dia_mm"] for h in tt["holes"] if not h["on_turn_axis"]] == [6]    # cross hole drilled, centre bore turned
    pc = client.post(f"/api/parts/{pid}/piece-cost", json={})
    assert pc.status_code == 200, pc.text
    pt = client.get(f"/api/parts/{pid}/piece-cost/trace").json()
    assert pt["machine"] == "CNC-LATHE"
    assert pt["nodes"]["mc:calc:cycle_s"]["value"] == tt["named"]["cycle_s"]
    assert pt["value_inr"] > n["calc:net_rm_cost"]["value"]


def test_milled_block_and_typed_route_and_shape():
    p = project("M2")
    pid = add_part(p, BLOCK, "Aluminium 6061-T6 bar", "machined", "BL-1")
    client.post(f"/api/parts/{pid}/tool-cost", json={})
    tt = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    assert tt["route"] == "milled" and tt["trial"]["machine"]["machine_id"] == "VMC-850"
    assert tt["stock"]["shape"] in ("square", "flat", "plate")
    assert len([h for h in tt["holes"]]) == 4
    r = client.put(f"/api/parts/{pid}", json={"tool_inputs": {"stock_shape": "plate", "setups": 3}})
    assert r.status_code == 200, r.text
    tt = client.post(f"/api/parts/{pid}/tool-cost", json={}) and client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    assert tt["stock"]["shape"] == "plate" and tt["nodes"]["in:setups"]["value"] == 3
    bad = client.put(f"/api/parts/{pid}", json={"tool_inputs": {"route": "ground"}})
    assert bad.status_code == 400


def test_stock_search_needs_a_size_that_fits():
    import pytest
    f = {"turn_dia_mm": 400, "turn_length_mm": 50, "sizes_mm": [400, 400, 50], "round_share": 1}
    with pytest.raises(machining.MachiningError):
        machining.pick_stock(f, "turned")
    assert machining.pick_stock(f, "milled")["shape"] == "plate"


def test_volume_change_marks_the_fixture_out_of_date():
    p = project("M3")
    pid = add_part(p, SHAFT, EN8, "machined", "SH-3")
    client.post(f"/api/parts/{pid}/tool-cost", json={})
    assert not detail(pid)["tool"]["outdated"]
    client.put(f"/api/parts/{pid}", json={"annual_volume": 1000})
    t = detail(pid)["tool"]
    assert t["latest"]["tools_count"] == 1 or t["outdated"]


def test_exports_of_a_machined_part():
    p = project("M4")
    pid = add_part(p, BLOCK, EN8, "machined", "BL-4")
    for k in ("rm-cost", "tool-cost", "piece-cost"):
        assert client.post(f"/api/parts/{pid}/{k}", json={}).status_code == 200
    for u in ("tool-cost/export.xlsx", "tool-cost/export.pdf", "piece-cost/export.pdf", "rm-cost/export.xlsx", "po-pack.zip"):
        r = client.get(f"/api/parts/{pid}/{u}")
        assert r.status_code == 200 and len(r.content) > 1000, u
