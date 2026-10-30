"""Stage 41: progressive die vs stage dies, and tool / mould life in the part cost. Every value comes from master data and is traced."""
import pytest

from backend.app import costing_setup, master_data, sheet_compare
from tests.test_rm_cost import add_part, client, detail, project


def sheet_part(code="SM-1"):
    return add_part(project(), "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage", code)


def set_param(part_type, name, value):
    sheets = {k: [dict(r) for r in v] for k, v in master_data.tables().items()}
    row = next(r for r in sheets["Parameters"] if r["part_type"] == part_type and r["parameter"] == name)
    row["value"] = value
    master_data.write(sheets)


def test_both_die_types_are_costed_by_the_master_data_formulas():
    pid = sheet_part()
    c = client.get(f"/api/parts/{pid}/sheet-compare").json()
    assert not c["errors"] and set(c["modes"]) == {"progressive", "multi_stage"}
    params = master_data.parameters("sheet_metal")
    for mode, m in c["modes"].items():
        n, nodes = m["named"], m["nodes"]
        prog = mode == "progressive"
        assert n["hit_s"] == pytest.approx(60 / params["progressive_spm"] if prog else params["stage_hit_time_s"])
        presses = len(m["dies"]) if not prog else 1
        assert nodes["in:presses"]["value"] == presses
        ops = presses * (params["progressive_operators"] if prog else params["stage_operators_per_press"])
        used = {i["name"]: nodes[i["node"]]["value"] for i in nodes["calc:process_cost"]["inputs"]}
        assert n["operators"] == pytest.approx(ops)
        assert n["tool_life"] == (params["progressive_die_life_strokes"] if prog else params["stage_die_life_strokes"])
        tool = nodes["in:tool_cost"]["value"]
        assert n["amortisation"] == pytest.approx(tool / min(n["tool_life"], n["programme_parts"] / n["lines_needed"]))
        assert n["tool_capex"] == pytest.approx(tool * n["tools_needed"])
        assert m["value"] == pytest.approx(n["ex_works"] + n["amortisation"])
        assert n["process_cost"] == pytest.approx((used["presses_mhr"] + ops * used["labour_rate"]) * n["hit_s"] / 3600)
        # every formula step is a Cost formulas row of scope sheet_compare, every input has a source
        assert nodes["calc:piece_cost"]["ref"]["match"] == {"scope": "sheet_compare", "name": "piece_cost"}
        assert all(x["source"]["type"] != "unknown" for x in nodes.values() if x["kind"] == "input")
    assert c["cheaper"] in c["modes"]
    other = "multi_stage" if c["cheaper"] == "progressive" else "progressive"
    assert c["saving_per_piece_inr"] == pytest.approx(c["modes"][other]["value_inr"] - c["modes"][c["cheaper"]]["value_inr"])
    assert any(r["is_part_volume"] for r in c["sweep"]) and c["is_example"]


def test_comparison_changes_nothing_stored():
    pid = sheet_part()
    before = detail(pid)
    client.get(f"/api/parts/{pid}/sheet-compare")
    after = detail(pid)
    assert after["sheet_inputs"] == before["sheet_inputs"]
    assert client.get(f"/api/parts/{pid}/sheet-tools").json()["mode"] == "multi_stage"


def test_break_even_is_where_both_part_costs_are_equal():
    pid = sheet_part()
    set_param("sheet_metal", "progressive_operators", 22)       # progressive: cheaper die, dearer to run → a break-even
    c = client.get(f"/api/parts/{pid}/sheet-compare").json()
    assert c["break_even"], c["sweep"]
    b = c["break_even"][0]
    lo, hi = c["sweep"][0], c["sweep"][-1]
    assert (lo["progressive_inr"] < lo["multi_stage_inr"]) and (hi["progressive_inr"] > hi["multi_stage_inr"])
    assert not b["progressive_cheaper_above"]
    near = [r for r in c["sweep"] if r["annual_volume"] < b["annual_volume"]]
    assert all(r["progressive_inr"] <= r["multi_stage_inr"] for r in near)
    assert b["piece_inr"] > 0


def test_part_cost_amortises_one_tool_over_its_life():
    pid = add_part(project(), code="PC-41")
    assert client.post(f"/api/parts/{pid}/tool-cost", json={}).status_code == 200
    set_param("plastic", "tool_life_shots", 1000)               # the mould wears out long before the programme ends
    assert client.post(f"/api/parts/{pid}/piece-cost", json={}).status_code == 200
    n = client.get(f"/api/parts/{pid}/piece-cost").json()["live"]["nodes"]
    cav = n["in:cavities"]["value"]
    assert n["calc:tool_life_parts"]["value"] == 1000 * cav
    assert n["calc:parts_per_tool"]["value"] == pytest.approx(min(1000 * cav, n["in:lifetime_volume"]["value"] / n["in:tools_for_capacity"]["value"]))
    assert n["calc:amortisation"]["value"] == pytest.approx(n["in:tool_cost"]["value"] / (1000 * cav))
    assert n["calc:amortisation"]["formula"] == "tool_cost / parts_per_tool"
    assert n["in:tool_life_shots"]["source"] == {"type": "master", "sheet": "Parameters", "row": "plastic / tool_life_shots"}


def test_seed_only_adds_and_changes_the_amortisation_row_only_while_shipped():
    assert sheet_compare.seed() == {"parameters": 0, "formulas": 0, "inputs": 0, "amortisation": 0}
    s = costing_setup.tables()
    row = next(r for r in s["cost_formulas"] if r["scope"] == "piece" and r["name"] == "amortisation")
    row["formula"] = "tool_capex / lifetime_volume * 1.0"           # your own edit stays yours
    costing_setup.write(s)
    assert sheet_compare.seed()["amortisation"] == 0
    assert master_data.parameters("machined")["tool_life_shots"] == 500000
