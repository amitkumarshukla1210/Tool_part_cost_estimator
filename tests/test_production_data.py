"""Stage 45: supplier production data - stock, weight, operations and the tool cost split per made tool part."""

import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import mould_db, production_data
from backend.app.main import app
from tests.test_drawing_data import bracket
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def cover(code):
    return add_part(project(code), "plastic_cover.step", "ABS", "injection_moulding", f"{code}-1")


def test_rules_are_master_data_and_seed_adds_only_missing_rows():
    assert not production_data.seed()
    r = mould_db.design_rules("plastic")
    assert r["stock_allowance_mm"]["is_example"] and r["stock_round_mm"]["value"] > 0 and "machining" in r["production_cost_groups"]["text"]


def test_mould_parts_add_up_to_the_tool_cost():
    pid = cover("PD1")
    r = client.get(f"/api/parts/{pid}/production-data").json()
    t = r["tools"][0]
    s = t["sums"]
    assert s["check_inr"] == pytest.approx(s["tool_cost_inr"], abs=0.01)
    tool = client.get(f"/api/parts/{pid}").json()
    by = {p["name"]: p for p in t["parts"]}
    cav = by["Cavity insert"]
    allow, step = t["rules"]["allow"], t["rules"]["step"]
    for fin, st in zip(cav["finished_mm"], cav["stock_mm"]):
        assert st >= fin + 2 * allow - 0.1
        assert min(st % step, step - st % step) < 1e-6                                   # a whole number of size steps
    assert cav["kg_each"] == pytest.approx(cav["stock_mm"][0] * cav["stock_mm"][1] * cav["stock_mm"][2] / 1e6 * cav["density"], rel=1e-3)
    assert cav["steel_inr"] > 0 and cav["process_inr"] > 0 and any("Deep-hole" in o for o in cav["operations"])
    assert by["A plate (cavity side)"]["steel_inr"] > 0                                 # the mould base goes to the plates
    assert any(x["element"] == "Ejector pin" for x in t["standard"]) and any("Fitting" in x["element"] for x in t["tool_level"])
    assert tool["part_code"] == r["part_code"]


def test_every_sheet_metal_die_adds_up_and_excel_downloads():
    pid = bracket("PD2")
    r = client.get(f"/api/parts/{pid}/production-data").json()
    assert len(r["tools"]) >= 2
    for t in r["tools"]:
        assert t["sums"]["check_inr"] == pytest.approx(t["sums"]["tool_cost_inr"], abs=0.01) and t["parts"]
    x = client.get(f"/api/parts/{pid}/production-data.xlsx")
    assert x.status_code == 200
    ws = load_workbook(io.BytesIO(x.content)).worksheets[0]
    text = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
    assert "Stock L×W×H" in text and "Tool cost (= Σ parts + standard + tool level)" in text and r["tools"][0]["parts"][0]["name"] in text


def test_missing_rule_is_named():
    d = mould_db.tables()
    d["design_rules"] = [x for x in d["design_rules"] if not (x["part_type"] == "plastic" and x["parameter"] == "stock_round_mm")]
    mould_db.write(d)
    r = client.get(f"/api/parts/{cover('PD3')}/production-data")
    assert r.status_code == 400 and "stock_round_mm" in r.json()["detail"]
