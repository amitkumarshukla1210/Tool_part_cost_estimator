import pytest
from fastapi.testclient import TestClient

from backend.app import mould_db, rates
from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def bracket(code="SM-1"):
    return add_part(project("TE" + code[-1]), "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage", code)


def tool(pid):
    return client.get(f"/api/parts/{pid}/tool-cost/trace").json()


def override(pid, scope, node, **kw):
    r = client.put(f"/api/parts/{pid}/trace-override", json={"scope": scope, "node": node, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_rate_value_changed_for_this_part_only():
    pid = bracket()
    tr = tool(pid)
    node = next(k for k, n in tr["nodes"].items() if n.get("source", {}).get("type") == "rate"
                and n["source"]["rate"]["item"] == "tool_overhead_pct")
    before = tr["value_inr"]
    res = override(pid, "tool", node, value=20, note="toolmaker quote")
    assert res["stored"]
    tr = tool(pid)
    n = tr["nodes"][node]
    assert n["value"] == 20 and n["source"]["type"] == "override" and n["source"]["was"] == 12
    assert tr["value_inr"] > before                                                  # 20 % overhead instead of 12 %
    other = bracket("SM-2")
    o = tool(other)["nodes"][node]
    assert o["value"] == 12                                                          # other parts keep the rate library value
    client.put(f"/api/parts/{pid}/trace-override", json={"scope": "tool", "node": node, "reset": True})
    assert tool(pid)["value_inr"] == pytest.approx(before)


def test_a_rule_formula_changed_for_this_part_and_bad_formulas_are_refused():
    pid = bracket()
    tr = tool(pid)
    node = next(k for k in tr["nodes"] if k.endswith("Screws, dowels & bolts (set):each"))
    assert tr["nodes"][node]["formula"].startswith("1500") and tr["nodes"][node]["ref"]["column"] == "unit_cost_rule"
    assert "constants" in tr["nodes"][node]["description"]
    override(pid, "tool", node, formula="2000 + die_l * die_w / 100")
    n = tool(pid)["nodes"][node]
    assert n["formula"].startswith("2000") and n["override"]["was_formula"].startswith("1500")
    r = client.put(f"/api/parts/{pid}/trace-override", json={"scope": "tool", "node": node, "formula": "2000 + nonsense"})
    assert r.status_code == 400 and "Not saved" in r.json()["detail"]
    assert tool(pid)["nodes"][node]["formula"].startswith("2000")                    # the good one stays


def test_save_for_the_future_corrects_master_data_and_the_rate_library():
    pid = bracket()
    tr = tool(pid)
    node = next(k for k, n in tr["nodes"].items() if (n.get("source") or {}).get("ref", {}).get("table") == "sizing_rules"
                and n["source"]["ref"]["match"]["parameter"] == "die_wall_mm")
    r = client.post("/api/trace/save-default", json={"ref": tr["nodes"][node]["source"]["ref"], "value": 40})
    assert r.status_code == 200, r.text
    row = next(x for x in mould_db.tables()["sizing_rules"] if x["part_type"] == "sheet_metal" and x["parameter"] == "die_wall_mm")
    assert row["value"] == 40 and not row["is_example"]
    rnode = next(n for n in tr["nodes"].values() if n.get("source", {}).get("type") == "rate")
    client.put("/api/settings", json={"approver_name": "Amit", "review_threshold_pct": "5"})
    r = client.post("/api/trace/save-default", json={"rate": rnode["source"]["rate"], "value": rnode["value"] * 1.1})
    assert r.status_code == 200 and r.json()["approved"]
    rr = rnode["source"]["rate"]
    assert rates.lookup(rr["category"], rr["item"], rr["country"])["value"] == pytest.approx(rnode["value"] * 1.1)
    f = next(n for n in tr["nodes"].values() if n.get("ref", {}).get("table") == "bom_elements")
    r = client.post("/api/trace/save-default", json={"ref": f["ref"], "formula": f["formula"] + " + 1"})
    assert r.status_code == 200


def test_pick_another_die_set_and_add_a_new_one():
    pid = bracket()
    tr = tool(pid)
    die = tr["dies"][0]
    base_node = next(k for k, n in tr["nodes"].items() if (n.get("source") or {}).get("ref", {}).get("choose_base") and k.startswith(die["key"]))
    ref = tr["nodes"][base_node]["source"]["ref"]
    assert ref["line_key"] == f"{die['key']}|__base__" and ref["part_type"] == "sheet_metal"
    r = client.post("/api/master-rows/mould_db/mould_bases", json={"row": {
        "part_type": "sheet_metal", "series": "My die set", "size_code": "X1", "length_mm": 900, "width_mm": 700,
        "max_insert_length_mm": 800, "max_insert_width_mm": 600, "a_plate_mm": 0, "b_plate_mm": 0, "clamp_plates_mm": 40,
        "support_plate_mm": 0, "spacer_block_mm": 0, "ejector_plates_mm": 0, "stack_height_mm": 300, "weight_kg": 900, "cost": 99000}})
    assert r.status_code == 200, r.text
    r = client.put(f"/api/parts/{pid}/tool-bom", json={"key": ref["line_key"], "line": {"base": "X1"}})
    assert r.status_code == 200, r.text
    d = tool(pid)["dies"][0]
    assert d["base"]["size_code"] == "X1"


def test_rm_value_for_this_part():
    pid = bracket()
    rm = client.get(f"/api/parts/{pid}/rm-cost/trace").json()
    node = next(k for k, n in rm["nodes"].items() if (n.get("source") or {}).get("type") == "rate")
    before = rm["value"]
    override(pid, "rm", node, value=rm["nodes"][node]["value"] * 2)
    assert client.get(f"/api/parts/{pid}/rm-cost/trace").json()["value"] != before


def test_steel_grade_traced_and_changed_for_several_lines():
    pid = bracket()
    tr = tool(pid)
    mat = next(n for k, n in tr["nodes"].items() if k.endswith("Die plate (cutting):mat"))
    assert mat["grade"]["grade"] == "D2 (1.2379)" and "D2" in mat["description"] and mat["grade"]["reason"]
    keys = [l["key"] for l in tr["lines"] if l["grade"] == "D2 (1.2379)"]
    assert len(keys) >= 2                                                              # die plate, punch, bending steels ...
    prices = client.get("/api/tool-bom/grade-prices", params={"country": "IN"}).json()
    assert prices["SKD11 (JIS)"]["value"] > 0 and prices["D2 (1.2379)"]["unit"] == "INR/kg"
    r = client.put(f"/api/parts/{pid}/tool-bom/grade", json={"keys": keys, "grade": "SKD11 (JIS)"})
    assert r.status_code == 200, r.text
    tr2 = tool(pid)
    assert all(l["grade"] == "SKD11 (JIS)" for l in tr2["lines"] if l["key"] in keys)
    assert all(l["grade_reason"] == "your choice" for l in tr2["lines"] if l["key"] in keys)
    assert tr2["value"] > tr["value"]                                                   # SKD11 costs more per kg than D2
    assert client.put(f"/api/parts/{pid}/tool-bom/grade", json={"keys": keys, "grade": "Unobtainium"}).status_code == 400


def test_base_plate_material_traced_and_changeable_en8():
    pid = bracket()
    tr = tool(pid)
    base = next(l for l in tr["lines"] if l.get("is_base"))
    assert base["grade"] == "C45 / S50C" and base["grade_reason"] == "Mould bases → plate material"
    steel = tr["nodes"][base["nodes"]["steel"]]
    assert steel["grade"]["line_key"] == base["key"] and steel["value"] > 0
    assert "EN8 (080M40)" in client.get("/api/tool-bom/grade-prices", params={"country": "IN"}).json()
    assert client.get("/api/tool-bom/grade-prices", params={"country": "CN"}).json()["EN8 (080M40)"]["value"] > 0
    r = client.put(f"/api/parts/{pid}/tool-bom/grade", json={"keys": [base["key"]], "grade": "EN8 (080M40)"})
    assert r.status_code == 200, r.text
    b2 = next(l for l in tool(pid)["lines"] if l.get("is_base"))
    assert b2["grade"] == "EN8 (080M40)" and b2["grade_reason"] == "your choice"
    assert b2["total"] == pytest.approx(base["total"])                                # catalogue price: material is information


def test_base_without_catalogue_price_is_priced_by_weight():
    db = mould_db.tables()
    for b in db["mould_bases"]:
        if b["part_type"] == "sheet_metal":
            b["cost"] = 0
    mould_db.write(db)
    pid = bracket()
    tr = tool(pid)
    base = next(l for l in tr["lines"] if l.get("is_base"))
    node = tr["nodes"][base["nodes"]["total"]]
    assert node["formula"] == "steel * factor" and base["total"] == pytest.approx(tr["nodes"][base["nodes"]["steel"]]["value"] * 2.2)
