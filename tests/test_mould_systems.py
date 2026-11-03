"""Stage 46: Mould systems - gate, runner, overflow (ejection, cooling) of the mould design worked out by master-data formulas."""

import math

from fastapi.testclient import TestClient

from backend.app import mould_db, mould_systems, register
from backend.app.main import app
from tests.test_eps_blow import add, bottle, eps_tray
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def _design(pid):
    return register.tool_designs(pid)[2][0][1]


def _rows(des):
    return {r["name"]: r for r in des["systems"]["rows"]}


def test_seed_is_idempotent_and_rows_are_example():
    assert mould_systems.seed() == {"rules": 0, "rows": 0}               # shipped in master_data/costing_db.sqlite
    t = mould_db.tables()
    rows = [r for r in t["mould_systems"] if r["part_type"] == "plastic"]
    assert {"gates", "gate_thk", "gate_width", "runner_dia"} <= {r["name"] for r in rows} and all(r["is_example"] for r in rows)
    assert {"gate_thk_factor", "gate_n_factor"} <= set(mould_db.design_rules("plastic"))
    for pt in ("die_casting", "eps", "foundry"):
        assert any(r["part_type"] == pt for r in t["mould_systems"])


def test_plastic_gate_is_sized_by_formula_traced_and_built():
    pid = add_part(project("MSY1"), "plastic_cover.step", "ABS", "injection_moulding", "MSY1-1")
    client.put(f"/api/parts/{pid}/cavities", json={"cavities": 2})
    des = _design(pid)
    r, f = _rows(des), des["systems"]["facts"]
    rules = {k: float(v["value"]) for k, v in mould_db.design_rules("plastic").items() if v["value"] is not None}
    assert r["gate_thk"]["value"] == round(max(rules["gate_thk_min_mm"], rules["gate_thk_factor"] * f["wall_mm"]), 3)
    w = max(r["gate_thk"]["value"], rules["gate_n_factor"] * math.sqrt(f["part_surface_cm2"] * 100) / 30 / r["gates"]["value"])
    assert abs(r["gate_width"]["value"] - w) < 1e-3
    assert r["gate_thk"]["inputs"]["wall_mm"] == round(f["wall_mm"], 4) and "formula" in r["gate_thk"]["source"] and r["gate_thk"]["is_example"]
    assert len(des["gates"]) == 2 * r["gates"]["value"] and all(g["kind"] == "edge" for g in des["gates"])
    assert any(f"edge gate(s) {r['gate_width']['value']:.1f} × {r['gate_thk']['value']:.1f}" in n for n in des["notes"])
    assert any(n.startswith("Gate (Mould systems, EXAMPLE rules)") for n in des["notes"])


def test_typed_value_wins_and_changes_the_design():
    pid = add_part(project("MSY2"), "plastic_cover.step", "ABS", "injection_moulding", "MSY2-1")
    client.put(f"/api/parts/{pid}/cavities", json={"cavities": 2})
    r = client.put(f"/api/parts/{pid}/mould-systems", json={"values": {"gate_width": 5.5, "gates": 2}})
    assert r.status_code == 200, r.text
    rows = {x["name"]: x for x in r.json()["tools"][0]["systems"]["rows"]}
    assert rows["gate_width"]["value"] == 5.5 and rows["gate_width"]["source"] == "typed by you" and rows["gates"]["value"] == 2
    assert len(_design(pid)["gates"]) == 4
    assert client.put(f"/api/parts/{pid}/mould-systems", json={"values": {"nope": 1}}).status_code == 400
    assert client.put(f"/api/parts/{pid}/mould-systems", json={"values": {"gate_width": "x"}}).status_code == 400
    r = client.put(f"/api/parts/{pid}/mould-systems", json={"values": {"gate_width": None, "gates": ""}}).json()
    assert {x["name"]: x for x in r["tools"][0]["systems"]["rows"]}["gate_width"]["source"].startswith("formula")


def test_die_casting_gate_by_nadca_and_overflows():
    pid = add_part(project("MSY3"), "plastic_cover.step", "Aluminium ADC12 / A383", "die_casting", "MSY3-1")
    des = _design(pid)
    r = _rows(des)
    assert r["fill_time"]["value"] > 0 and r["gate_area"]["value"] > 0
    assert abs(r["gate_area"]["value"] - r["shot_cm3"]["value"] / (r["fill_time"]["value"] * 40)) / r["gate_area"]["value"] < 1e-3
    assert abs(r["gate_width"]["value"] * r["gate_thk"]["value"] - r["gate_area"]["value"]) < 0.01
    assert r["overflows"]["value"] >= 1 and r["overflow_len"]["value"] >= 8
    assert any(f"{int(r['overflows']['value'])} overflow(s)" in n for n in des["notes"])


def test_eps_fill_guns_and_foundry_gating_by_formula(tmp_path):
    pid = add(tmp_path, eps_tray(), "eps.step", "EPS bead grade S (20 kg/m3)", "eps_moulding", "MSY4")
    des = _design(pid)
    guns, cav = _rows(des)["fill_guns"]["value"], des["systems"]["facts"]["cavities"]
    assert guns == max(1, math.ceil(_rows(des)["fill_guns"]["inputs"]["part_volume_cm3"] / 1500))
    assert 1 <= len(des["gates"]) <= guns * cav and all(g["kind"] == "fill gun" for g in des["gates"])
    injector = next(c for c in des["components"] if c.name.startswith("Fill injector"))
    assert len(injector.locs) == len(des["gates"])
    pid = add_part(project("MSY5"), material="Grey cast iron FG260", process="foundry", code="MSY5-1")
    des = _design(pid)
    r = _rows(des)
    assert r["choke_area"]["value"] > 0 and abs(r["sprue_dia"]["value"] - math.sqrt(4 * r["choke_area"]["value"] / math.pi)) < 0.01
    assert abs(r["riser_dia"]["value"] - 6 * 1.2 * des["systems"]["facts"]["part_modulus_mm"]) < 0.01
    gating = next(c for c in des["components"] if c.name.startswith("Gating & riser pattern"))
    assert f"riser Ø{r['riser_dia']['value']:.0f}" in gating.notes[0]


def test_blow_mould_has_no_gate_rows(tmp_path):
    pid = add(tmp_path, bottle(), "bottle.step", "PET bottle grade (IV 0.80)", "stretch_blow_moulding", "MSY6")
    des = _design(pid)
    assert not [r for r in des["systems"]["rows"] if r["system"] in ("gate", "overflow")]


def test_failed_checks_reach_the_toolmaker_review():
    pid = add_part(project("MSY7"), "plastic_cover.step", "ABS", "injection_moulding", "MSY7-1")
    client.put(f"/api/parts/{pid}/cavities", json={"cavities": 1})
    client.put(f"/api/parts/{pid}/mould-systems", json={"values": {"gates": 3}})       # one cavity, three gates: a direct sprue cannot
    des = _design(pid)
    bad = [c for c in des["systems"]["checks"] if c["ok"] is False]
    assert [c["name"] for c in bad] == ["chk_one_cavity"] and "3-plate" in bad[0]["message"]
    rv = client.get(f"/api/parts/{pid}/tool-review").json()
    row = next(r for t in rv["tools"] for r in t["rows"] if r["item"].startswith("Mould systems checks pass"))
    assert row["status"] != "ok" and any("3-plate" in n for n in des["notes"])
