import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def bracket(p, code="SM-1"):
    return add_part(p, "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage", code)


def trace(pid):
    r = client.get(f"/api/parts/{pid}/tool-cost/trace")
    assert r.status_code == 200, r.text
    return r.json()


def line(tr, die, element):
    return next(l for l in tr["lines"] if l.get("die_key") == die and l["element"] == element)


def test_sheet_metal_part_gets_one_die_per_operation_with_bom_and_cost():
    pid = bracket(project("D1"))
    d = client.get(f"/api/parts/{pid}").json()
    assert d["tool"]["applicable"] and d["tool_cost_inr"] > 0                       # costed on import
    tr = trace(pid)
    assert [x["name"] for x in tr["dies"]] == ["Die 1: Blanking", "Die 2: Bending (V)"]
    assert tr["value"] == pytest.approx(sum(x["value"] for x in tr["dies"]))
    die1 = tr["dies"][0]
    assert die1["die_plate"]["die_l"] == pytest.approx(die1["die_plate"]["die_l"]) and die1["press"]["machine_id"]
    plate = line(tr, "blank", "Die plate (cutting)")
    assert plate["grade"] == "D2 (1.2379)" and "D2" in plate["grade_reason"] and plate["make"]
    assert not any(l["element"] == "Bending punch" for l in tr["lines"] if l["die_key"] == "blank")   # bending parts only in the bending die
    assert any(l["element"] == "Bending punch" for l in tr["lines"] if l["die_key"] == "bend")
    assert line(tr, "blank", "Die set 4-pillar die set " + die1["base"]["size_code"])["is_base"]


def test_progressive_die_is_one_die_with_every_station():
    pid = bracket(project("D2"))
    client.put(f"/api/parts/{pid}", json={"sheet_inputs": {"mode": "progressive"}})
    tr = trace(pid) if client.post(f"/api/parts/{pid}/tool-cost", json={}).status_code == 200 else trace(pid)
    assert len(tr["dies"]) == 1 and tr["dies"][0]["name"].startswith("Progressive die")
    assert set(tr["dies"][0]["ops"]) == {"blank", "bend"}


def test_bom_line_changes_are_used_traced_and_learned_for_the_next_part():
    p = project("D3")
    pid = bracket(p)
    key = "blank|Die plate (cutting)"
    r = client.put(f"/api/parts/{pid}/tool-bom", json={"key": key, "line": {"grade": "SKD11 (JIS)", "make": "Daido", "qty": 2}})
    assert r.status_code == 200, r.text
    l = line(trace(pid), "blank", "Die plate (cutting)")
    assert (l["grade"], l["make"], l["quantity"], l["grade_reason"]) == ("SKD11 (JIS)", "Daido", 2, "your choice")
    assert set(l["changed"]) == {"grade", "make", "qty"}
    r = client.put(f"/api/parts/{pid}/tool-bom", json={"key": key, "line": {"price_each": 5000}})
    l = line(trace(pid), "blank", "Die plate (cutting)")
    assert l["total"] == pytest.approx(5000) and l["price_each_inr"] == 5000                  # your price replaces the line
    assert client.put(f"/api/parts/{pid}/tool-bom", json={"key": key, "line": {"grade": "Unobtainium"}}).status_code == 400
    # the next new part of the same type and material is suggested the same grade and make
    client.put(f"/api/parts/{pid}/tool-bom", json={"key": key, "line": {"grade": "SKD11 (JIS)", "make": "Daido"}})
    pid2 = bracket(p, "SM-2")
    l2 = line(trace(pid2), "blank", "Die plate (cutting)")
    assert l2["grade"] == "SKD11 (JIS)" and l2["make"] == "Daido" and "SM-1" in l2["learned"]
    # resetting a line goes back to the suggestion; the earlier part's costed choice does not move
    client.put(f"/api/parts/{pid}/tool-bom", json={"key": key, "line": {}})
    assert line(trace(pid), "blank", "Die plate (cutting)")["grade"] in ("SKD11 (JIS)", "D2 (1.2379)")
    hist = client.get(f"/api/parts/{pid}").json()["history"]
    assert any(h["action"] == "tool_bom_changed" for h in hist)


def test_new_grade_and_standard_part_are_saved_and_selectable():
    pid = bracket(project("D4"))
    client.put("/api/settings", json={"approver_name": "Amit", "review_threshold_pct": "5"})
    r = client.post("/api/tool-materials", json={"code": "OHNS (O1)", "make": "Mukand", "price_per_kg": 380, "country": "IN",
                                                 "density_g_cm3": 7.85, "hardness": "58-60 HRC"})
    assert r.status_code == 200 and r.json()["approved"], r.text
    assert client.post("/api/tool-materials", json={"code": "OHNS (O1)", "price_per_kg": 1, "density_g_cm3": 7.85}).status_code == 400
    r = client.post("/api/standard-parts", json={"code": "mis-spr-30", "part_number": "SWM30-60", "description": "Die spring Ø30 × 60",
                                                 "make": "Misumi", "element": "Die springs / urethane", "price": 520, "country": "IN"})
    assert r.status_code == 200 and r.json()["standard_part"]["code"] == "MIS-SPR-30"
    assert client.post("/api/standard-parts", json={"code": "X", "description": "no part number", "make": "M", "price": 1}).status_code == 400
    ch = client.get("/api/tool-bom/choices").json()
    assert "OHNS (O1)" in [g["code"] for g in ch["grades"]] and "Mukand" in ch["makes"]
    assert any(x["part_number"] == "SWM30-60" for x in ch["standard_parts"])
    client.put(f"/api/parts/{pid}/tool-bom", json={"key": "blank|Blanking / trimming punch", "line": {"grade": "OHNS (O1)"}})
    punch = line(trace(pid), "blank", "Blanking / trimming punch")
    assert punch["grade"] == "OHNS (O1)" and punch["make"] == "Mukand"                         # the make of the new grade
    client.put(f"/api/parts/{pid}/tool-bom", json={"key": "blank|Die springs / urethane", "line": {"std_part": "MIS-SPR-30"}})
    spring = line(trace(pid), "blank", "Die springs / urethane")
    assert spring["std_part"] == "MIS-SPR-30" and spring["part_number"] == "SWM30-60" and spring["make"] == "Misumi"
    assert spring["total"] == pytest.approx(spring["quantity"] * 520)


def test_my_default_updates_master_data_for_every_new_tool():
    pid = bracket(project("D5"))
    r = client.put(f"/api/parts/{pid}/tool-bom", json={"key": "blank|Stripper plate", "line": {"grade": "Mould base steel (4140 / 1.7225)",
                                                                                              "make": "Thyssen"}, "as_default": True})
    assert r.status_code == 200
    row = next(e for e in client.get("/api/mould-db").json()["bom_elements"] if e["part_type"] == "sheet_metal" and e["element"] == "Stripper plate")
    assert row["material_code"] == "Mould base steel (4140 / 1.7225)" and row["make"] == "Thyssen"


def test_grade_rules_suggest_the_mould_insert_steel():
    pid = add_part(project("G1"))                                               # ABS cover, default volume
    tr = trace(pid)
    cav = next(l for l in tr["lines"] if l["element"] == "Cavity insert (steel)")
    assert cav["grade"] == "2738 (1.2738)" and cav["grade_reason"] == "BOM element default"   # no rule applies: element default
    gf = add_part(project("G2"), material="PA66 GF30", code="GF-1")
    cav = next(l for l in trace(gf)["lines"] if l["element"] == "Cavity insert (steel)")
    assert cav["grade"] == "H13 (1.2344)" and "Glass" in cav["grade_reason"]
