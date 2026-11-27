"""Stage 65: the fin die set made to size (your IFB die: 2400 × 1600 × 650 mm, ~4700 kg), typed size wins, all die parts."""

import pytest

from backend.app import fin_die, fin_die_draw, mould_db


def test_rules_and_bom_shipped():
    assert fin_die.seed()["mould_db"] == 0
    rules = mould_db.sizing_rules("fin")
    assert all(k in rules and rules[k]["is_example"] for k in fin_die.SET_RULES)
    els = {r["element"] for r in mould_db.tables()["bom_elements"] if r["part_type"] == "fin"}
    assert {"Die backing plate (lower)", "Punch backing plate (upper)", "Stopper block", "Stripper springs / gas springs",
            "Lifting eye bolts"} <= els


def test_reference_die_is_2400_1600_650_and_4700_kg():
    die = fin_die.die_cost(fin_die.normalise({}))
    b, n = die["base"], die["nodes"]
    assert (b["length_mm"], b["width_mm"], b["stack_height_mm"], b["riser_h_mm"]) == (2400, 1600, 650, 380)
    assert b["size_code"] == "2400×1600×650" and b["made_to_size"] and b["is_example"]
    assert n["tool_weight"]["value"] == pytest.approx(4700, rel=0.02)
    assert "fin_set_end_mm" in str(n["v:set_l"]) and n["v:base_weight_kg"]["value"] == pytest.approx(b["weight_kg"], abs=0.1)
    line = next(l for l in die["lines"] if l.get("is_base"))
    assert line["element"] == "Fin die set 2400×1600×650" and line["weight_each_kg"] == pytest.approx(3658.7, abs=1)
    assert any("overhangs the bed" in w for w in die["warnings"])            # your choice: keep the press data, warn
    assert any("die height in closed condition 650 mm" in w.lower() for w in die["warnings"])


def test_design_parts_and_3d_fill_the_envelope():
    des = fin_die_draw.build(fin_die.default_spec())
    p = {x["name"]: x for x in des["parts"]}
    assert p["Lower die plate (die set)"]["dims"] == (2400, 1600, 55) and p["Upper die plate (die set)"]["dims"] == (2400, 1600, 45)
    assert p["Riser (parallel) block"]["qty"] == 2 and p["Riser (parallel) block"]["dims"] == (2400, 45, 380)
    assert p["Stopper block"]["qty"] == 4 and p["Stopper block"]["dims"][2] == 170
    assert "Guide post Ø80 and bush (set)" in p and p["Stripper spring / gas spring"]["qty"] == 12 * 4
    assert {"Die backing plate (lower)", "Punch backing plate (upper)", "Lifting eye bolt"} <= set(p)
    assert des["dims"]["weight_kg"] == pytest.approx(4700, rel=0.02) and des["dims"]["target_kg"] == 4700
    sol = fin_die_draw.solids(des)
    z = [x["shape"].BoundingBox() for x in sol if x["kind"] != "ref"]
    assert max(b.zmax for b in z) - min(b.zmin for b in z) == pytest.approx(650, abs=0.5)
    xs = [b for x, b in zip([x for x in sol if x["kind"] != "ref"], z) if x["name"] == "Lower die plate (die set)"][0]
    assert xs.xlen == pytest.approx(2400) and xs.ylen == pytest.approx(1600)


def test_typed_size_wins_and_bad_sizes_say_why():
    die = fin_die.die_cost(fin_die.normalise({"die_set_l_mm": 2600, "shut_h_mm": 700}))
    b = die["base"]
    assert (b["length_mm"], b["width_mm"], b["stack_height_mm"], b["riser_h_mm"]) == (2600, 1600, 700, 430)
    assert die["nodes"]["v:set_l"]["source"]["type"] == "user"
    ref = fin_die.die_cost(fin_die.normalise({}))
    assert die["nodes"]["tool_weight"]["value"] > ref["nodes"]["tool_weight"]["value"] and die["value_inr"] > ref["value_inr"]
    with pytest.raises(fin_die.FinDieError, match="smaller than the die area"):
        fin_die.die_cost(fin_die.normalise({"die_set_l_mm": 1000}))
    with pytest.raises(fin_die.FinDieError, match="type at least 270 mm"):
        fin_die.die_cost(fin_die.normalise({"shut_h_mm": 200}))


def test_smallest_press_takes_the_die_area_and_country_costs():
    die = fin_die.die_cost(fin_die.normalise({"press": "auto"}))
    assert die["trial"]["machine"] and not die["missing"]
    cn = fin_die.die_cost(fin_die.normalise({"country": "CN"}))
    assert cn["nodes"]["tool_weight"]["value"] == pytest.approx(die["nodes"]["tool_weight"]["value"])
    assert cn["currency"] == "CNY" and cn["value_inr"] != die["value_inr"]


def test_typed_die_set_on_the_fin_part():
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from tests.test_fin_part import fin_part_id
    client = TestClient(app)
    pid, _ = fin_part_id("FIN-8")
    r = client.put(f"/api/parts/{pid}/fin", json={"die_set_l_mm": 2600, "die_set_w_mm": 1700, "shut_h_mm": 700})
    assert r.status_code == 200, r.text
    assert r.json()["typed"] == {"die_set_l_mm": 2600, "die_set_w_mm": 1700, "shut_h_mm": 700}
    d = client.get(f"/api/parts/{pid}/fin-design").json()
    assert (d["dims"]["base_l"], d["dims"]["base_w"], d["dims"]["shut_h"]) == (2600, 1700, 700)
    tool = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    assert tool["nodes"]["tool_weight"]["value"] == pytest.approx(d["dims"]["weight_kg"], abs=0.5)   # stored tool cost follows


def test_part_edits_of_a_fin_die_are_used():
    """Bugs found in testing: a fin part ignored its own tool BOM changes and 'for this part only' corrections, and a catalogue
    die set chosen for it kept the made-to-size weight."""
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from tests.test_fin_part import fin_part_id
    client = TestClient(app)
    pid, _ = fin_part_id("FIN-E")
    tr = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    feed = next(l for l in tr["lines"] if l["element"] == "Hitch-finger feed unit")
    assert client.put(f"/api/parts/{pid}/tool-bom", json={"key": feed["key"], "line": {"price_each": feed["total"] + 100000}}).status_code == 200
    tr2 = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    assert tr2["value_inr"] > tr["value_inr"] + 50000                                   # your price is in the fin die cost
    assert client.put(f"/api/parts/{pid}/trace-override", json={"scope": "tool", "node": "v:station_min_mm", "value": 160,
                                                                 "note": "test"}).status_code == 200
    assert client.get(f"/api/parts/{pid}/tool-cost/trace").json()["nodes"]["v:station_min_mm"]["value"] == 160
    base = next(l for l in tr2["lines"] if l.get("is_base"))
    assert client.put(f"/api/parts/{pid}/tool-bom", json={"key": base["key"], "line": {"base": "2515"}}).status_code == 200
    tr3 = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    cat = next(b for b in mould_db.tables()["mould_bases"] if b["part_type"] == "fin" and b["size_code"] == "2515")
    line = next(l for l in tr3["lines"] if l.get("is_base"))
    assert line["element"] == "Fin die set 2515" and tr3["nodes"]["v:base_weight_kg"]["value"] == pytest.approx(cat["weight_kg"])
    d = client.get(f"/api/parts/{pid}/fin-design").json()                               # the design follows your choice
    assert (d["dims"]["base_l"], d["dims"]["base_w"]) == (cat["length_mm"], cat["width_mm"]) and not d["dims"]["sized"]
    r = client.put(f"/api/parts/{pid}/fin", json={"shut_h_mm": 100})                    # refused when saved, not later
    assert r.status_code == 400 and "type at least 270 mm" in r.text


def test_made_to_size_die_set_price_for_the_future_says_how():
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from tests.test_fin_part import fin_part_id
    client = TestClient(app)
    pid, _ = fin_part_id("FIN-F")
    tr = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    bl = next(l for l in tr["lines"] if l.get("is_base"))
    r = client.post("/api/trace/save-default", json={"ref": tr["nodes"][bl["nodes"]["bo"]]["ref"], "value": 123456, "note": "t"})
    assert r.status_code == 400 and "made to size" in r.text and "base_make_factor" in r.text
