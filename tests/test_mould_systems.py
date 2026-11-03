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
    bad = [c for c in des["systems"]["checks"] if c["ok"] is False and c["system"] == "gate"]
    assert [c["name"] for c in bad] == ["chk_one_cavity"] and "3-plate" in bad[0]["message"]
    rv = client.get(f"/api/parts/{pid}/tool-review").json()
    row = next(r for t in rv["tools"] for r in t["rows"] if r["item"].startswith("Mould systems checks pass"))
    assert row["status"] != "ok" and any("3-plate" in n for n in des["notes"])


# ---------- ejection (stage 46, 3/5) ----------

def test_ejector_stroke_raises_spacer_blocks_and_part_comes_off():
    pid = add_part(project("MSE1"), "large_plastic_tub.step", "PP (polypropylene)", "injection_moulding", "MSE1-1")
    des = _design(pid)
    r, f = _rows(des), des["systems"]["facts"]
    assert r["eject_stroke"]["value"] == round(f["part_h"] + 10, 6)
    assert r["base_stroke"]["value"] == f["spacer_block_mm"] - f["ejector_plates_mm"] - 5
    sb = next(c for c in des["components"] if c.name == "Spacer block")
    assert abs(sb.size[2] - max(f["spacer_block_mm"], r["spacer_used"]["value"])) < 0.2
    chk = {c["name"]: c for c in des["systems"]["checks"]}
    assert chk["chk_stroke"]["ok"] is True                                       # the designed stroke always clears the part
    if r["base_stroke"]["value"] < r["eject_stroke"]["value"]:
        assert chk["chk_base"]["ok"] is False and "raised" in chk["chk_base"]["message"]
        assert any(n.startswith("Spacer blocks raised from") for n in des["notes"])
    # the ejector plate + pins move up by the stroke in the 3D viewer, the A side lifts by the opening stroke
    assert des["motion"]["eject_mm"] == round(r["eject_stroke"]["value"], 1) and des["motion"]["opening_mm"] == round(r["opening_stroke"]["value"], 1)
    html = client.get(f"/api/parts/{pid}/tool-design.html").text
    assert 'id="motion"' in html and '"moves":' in html and '"eject_mm":' in html
    from backend.app import outputs3d
    data = outputs3d.viewer_data({"part_code": "X"}, des, "A")
    mv = {p["name"]: set(p["moves"]) for p in data["parts"]}
    assert mv["Ejector plate"] == {"eject"} and mv["Moulded part (reference)"] == {"eject"} and mv["A plate (cavity side)"] == {"open"}
    assert mv["B plate (core side)"] == {""} and data["motion"]["eject_mm"] > 0


def test_machine_check_uses_the_ejector_stroke_of_the_mould_systems():
    pid = add_part(project("MSE2"), "plastic_cover.step", "ABS", "injection_moulding", "MSE2-1")
    stroke = _rows(_design(pid))["eject_stroke"]["value"]
    client.put(f"/api/parts/{pid}/machine", json={"spec": {"ejector_stroke_mm": round(stroke) - 1}})
    r = client.get(f"/api/parts/{pid}/machine-check").json()
    row = next(c for c in r["check"] if c["what"] == "Ejector stroke")
    assert row["needs"] == f"{round(stroke):g} mm" and not row["ok"]
    assert r["recommended"]["values"]["ejector_stroke_mm"] == round(stroke)


def test_eps_pneumatic_ejectors_and_blow_opening(tmp_path):
    pid = add(tmp_path, eps_tray(), "eps2.step", "EPS bead grade S (20 kg/m3)", "eps_moulding", "MSE3")
    des = _design(pid)
    n = _rows(des)["eps_ejectors"]["value"]
    ej = next(c for c in des["components"] if c.name.startswith("Pneumatic ejector"))
    assert n >= 2 and 1 <= len(ej.locs) <= n * des["systems"]["facts"]["cavities"] and des["motion"]["eject_mm"] > 0
    pid = add(tmp_path, bottle(), "bottle4.step", "PET bottle grade (IV 0.80)", "stretch_blow_moulding", "MSE4")
    des = _design(pid)
    assert des["motion"]["eject_mm"] == 0 and des["motion"]["opening_mm"] == round(_rows(des)["opening_stroke"]["value"], 1)


# ---------- cooling circuits and water data (stage 46, 4/5) ----------

def test_cooling_circuits_are_built_with_nipples_plugs_and_o_rings():
    pid = add_part(project("MSC1"), "plastic_cover.step", "ABS", "injection_moulding", "MSC1-1")
    client.put(f"/api/parts/{pid}/cavities", json={"cavities": 2})
    des = _design(pid)
    circ = des["cooling"]
    assert len(circ) >= 2 and {c["half"] for c in circ} == {"cavity", "core"} and all(c["len_mm"] > 0 for c in circ)
    names = {c.name: c for c in des["components"]}
    nin = next(c for n, c in names.items() if n.startswith("Cooling nipple IN"))
    assert len(nin.locs) == len(circ) and all(x < 0 for x, _, _ in nin.locs)          # IN on the operator (-X) side
    nout = sum(len(c.locs) for n, c in names.items() if n.startswith("Cooling nipple OUT"))
    assert nout == len(circ)
    if any(c["uturn"] for c in circ):
        assert any(n.startswith("Cooling plug") for n in names) and any("U-turn" in " ".join(c.notes) for c in des["components"] if c.name.startswith("Cavity insert") or c.name.startswith("Core insert"))
    assert any(n.startswith("O-ring") for n in names)
    assert any(n.startswith("Cooling circuits: C1") for n in des["notes"])


def test_water_data_by_formula_and_checks():
    pid = add_part(project("MSC2"), "plastic_cover.step", "ABS", "injection_moulding", "MSC2-1")
    des = _design(pid)
    r, f = _rows(des), des["systems"]["facts"]
    rules = {k: float(v["value"]) for k, v in mould_db.design_rules("plastic").items() if v["value"] is not None}
    from backend.app import process_params
    win = process_params.window("ABS")
    assert r["water_in"]["value"] == win["mould_c"] - rules["water_below_mould_c"]
    assert r["flow_set"]["value"] == max(r["flow_heat"]["value"], r["flow_turb"]["value"])
    assert r["reynolds"]["value"] >= rules["reynolds_min"] - 1
    q = r["flow_set"]["value"]
    out = r["water_in"]["value"] + r["heat_kw"]["value"] / f["cool_circuits"] / (4.186 * 1.0 * q / 60)
    assert abs(r["water_out"]["value"] - out) < 1e-3 and r["water_out"]["value"] - r["water_in"]["value"] <= rules["water_dt_max_c"] + 1e-6
    assert f["cool_circuits"] == len(des["cooling"]) and f["circuit_len_mm"] == max(c["len_mm"] for c in des["cooling"])
    assert r["pressure_drop"]["value"] > 0 and any(n.startswith("Cooling with water") for n in des["notes"])
    # the inlet temperature to keep is typed colder than the dew point: the check tells why
    client.put(f"/api/parts/{pid}/mould-systems", json={"values": {"water_in": 10}})
    chk = {c["name"]: c for c in _design(pid)["systems"]["checks"]}
    assert chk["chk_dew"]["ok"] is False and "10 °C is below the dew point" in chk["chk_dew"]["message"]


def test_die_casting_uses_thermal_oil_and_eps_spray_circuits(tmp_path):
    pid = add_part(project("MSC3"), "plastic_cover.step", "Aluminium ADC12 / A383", "die_casting", "MSC3-1")
    des = _design(pid)
    assert des["systems"]["coolant"].startswith("Thermal oil") and any(n.startswith("Cooling with thermal oil") for n in des["notes"])
    assert _rows(des)["water_in"]["value"] > 100
    pid = add(tmp_path, eps_tray(), "eps3.step", "EPS bead grade S (20 kg/m3)", "eps_moulding", "MSC4")
    des = _design(pid)
    assert des["systems"]["facts"]["cool_circuits"] == 2 and _rows(des)["flow_set"]["value"] > 0 and des["cooling"] == []

