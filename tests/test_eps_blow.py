import cadquery as cq
import pytest
from fastapi.testclient import TestClient

from backend.app import master_data, rates, register_setup
from backend.app.main import app

client = TestClient(app)


def step_file(tmp_path, name, shape):
    path = tmp_path / name
    cq.exporters.export(cq.Workplane("XY").add(shape), str(path))
    return path


def eps_tray():
    return cq.Workplane("XY").box(500, 300, 80).faces(">Z").workplane().rect(440, 240).cutBlind(-60).val()


def bottle():
    """0.5 l style bottle: revolved profile, 65 mm diameter, 200 mm high."""
    pts = [(0, 0), (30, 0), (32.5, 5), (32.5, 150), (20, 175), (14, 180), (14, 200), (0, 200)]
    return cq.Workplane("XZ").polyline(pts).close().revolve(360, (0, 0, 0), (0, 1, 0)).val()


def add(tmp_path, shape, name, material, process, code):
    path = step_file(tmp_path, name, shape)
    with open(path, "rb") as fh:
        m = client.post("/api/import/step", files={"file": (name, fh)}).json()
    p = client.post("/api/projects", json={"code": code, "name": "T"}).json()
    r = client.post(f"/api/import/{m['token']}/commit", json={"project_id": p["id"], "items": {m["root"]: {"material": material, "process": process, "part_code": code + "-1"}}})
    assert r.status_code == 200, r.text
    return r.json()["part_ids"][0]


def test_process_is_suggested_by_the_material(tmp_path):
    with open(step_file(tmp_path, "t.step", eps_tray()), "rb") as fh:
        m = client.post("/api/import/step", files={"file": ("t.step", fh)}).json()
    assert m["defs"][m["root"]]["suggestion"]["process"] != "eps_moulding"        # geometry alone cannot say
    procs = {p["code"]: p for p in register_setup.tables()["processes"]}
    assert procs["eps_moulding"]["part_type"] == "eps" and procs["stretch_blow_moulding"]["part_type"] == "blow"
    mats = {x["material"]: x for x in master_data.tables()["Materials"]}
    assert mats["EPS bead grade S (20 kg/m3)"]["part_type"] == "eps" and mats["PET bottle grade (IV 0.80)"]["part_type"] == "blow"


def test_eps_part_rm_tool_and_part_cost(tmp_path):
    pid = add(tmp_path, eps_tray(), "eps.step", "EPS bead grade S (20 kg/m3)", "eps_moulding", "EPS1")
    d = client.get(f"/api/parts/{pid}").json()
    assert d["rm"]["problem"] == "", d["rm"]["problem"]
    assert client.post(f"/api/parts/{pid}/rm-cost", json={}).status_code == 200
    rm = client.get(f"/api/parts/{pid}").json()["rm"]["latest"]
    vol_cm3 = (500 * 300 * 80 - 440 * 240 * 60) / 1000
    assert rm["net_weight_g"] == pytest.approx(vol_cm3 * 0.020, rel=1e-3)                      # foam density x volume
    assert rm["gross_weight_g"] == pytest.approx(rm["net_weight_g"] * 1.03, rel=1e-3)           # 3 % trim and fines
    tool = client.post(f"/api/parts/{pid}/tool-cost", json={})
    assert tool.status_code == 200, tool.text
    tr = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    assert tr["part_type"] == "eps" and tr["trial"]["machine"]["machine_id"].startswith("EPS")
    assert tr["base"]["series"] == "Steam chest"
    assert {l["element"] for l in tr["lines"]} >= {"Cavity block (aluminium)", "Steam vent (stainless insert)", "Fill gun / injector"}
    piece = client.post(f"/api/parts/{pid}/piece-cost", json={})
    assert piece.status_code == 200, piece.text
    pc = client.get(f"/api/parts/{pid}/piece-cost").json()["live"]
    steam = pc["nodes"]["calc:utility_cost"]["value"]
    assert steam == pytest.approx(pc["nodes"]["in:total_weight_kg"]["value"] * 0.8 * pc["nodes"]["in:steam_rate"]["value"]) and steam > 0
    assert pc["nodes"]["calc:preform_cost"]["value"] == 0 and pc["machine"].startswith("EPS")
    assert pc["nodes"]["in:cycle_s"]["value"] == 150


def test_bottle_weight_is_a_shell_and_both_costs_run(tmp_path):
    pid = add(tmp_path, bottle(), "bottle.step", "PET bottle grade (IV 0.80)", "stretch_blow_moulding", "SB1")
    assert client.post(f"/api/parts/{pid}/rm-cost", json={}).status_code == 200
    d = client.get(f"/api/parts/{pid}").json()
    g = d["revisions"][0]["geometry"]
    expected = g["surface_area_mm2"] / 100 * 0.30 / 10 * 1.38                                   # surface x wall x density
    assert d["rm"]["latest"]["net_weight_g"] == pytest.approx(expected, rel=1e-3) and 15 < expected < 40
    r = client.post(f"/api/parts/{pid}/rm-cost", json={"rm_inputs": {"wall_mm": 0.40}})
    assert r.status_code == 200
    assert client.get(f"/api/parts/{pid}").json()["rm"]["latest"]["net_weight_g"] == pytest.approx(expected * 0.40 / 0.30, rel=1e-3)
    assert client.post(f"/api/parts/{pid}/tool-cost", json={}).status_code == 200
    tr = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    assert tr["part_type"] == "blow" and tr["trial"]["machine"]["machine_id"].startswith("ISBM")
    assert {l["element"] for l in tr["lines"]} >= {"Cavity half (aluminium)", "Neck / ring insert", "Stretch rod and rod tip"}
    assert client.post(f"/api/parts/{pid}/piece-cost", json={}).status_code == 200
    pc = client.get(f"/api/parts/{pid}/piece-cost").json()["live"]
    rmc = pc["nodes"]["in:rm_cost"]["value"]
    assert pc["nodes"]["calc:preform_cost"]["value"] == pytest.approx(rmc * 0.28) and pc["nodes"]["calc:utility_cost"]["value"] == 0
    assert pc["nodes"]["in:cycle_s"]["value"] == 6 and pc["is_example"]


def test_new_types_work_in_the_country_comparison(tmp_path):
    pid = add(tmp_path, bottle(), "bottle2.step", "PET bottle grade (IV 0.80)", "stretch_blow_moulding", "SB2")
    client.post(f"/api/parts/{pid}/rm-cost", json={})
    res = client.get(f"/api/parts/{pid}/country-comparison", params={"countries": "IN,CN,DE"})
    assert res.status_code == 200, res.text
    rows = {r["country"]: r for r in res.json()["rows"]}
    assert all(not r["error"] for r in rows.values()), [r["error"] for r in rows.values()]
    assert rows["CN"]["landed"]["hs"] == "3923" and rows["CN"]["tool"]["landed"]["hs"] == "8480"
    assert rows["IN"]["landed"]["bcd"] == 0 and rows["DE"]["landed"]["landed"] > 0


def test_unsupported_cards_say_so(tmp_path):
    pid = add(tmp_path, bottle(), "bottle3.step", "PET bottle grade (IV 0.80)", "stretch_blow_moulding", "SB3")
    assert "plastic moulds and die-casting dies" in client.get(f"/api/parts/{pid}/concept").json()["detail"]
