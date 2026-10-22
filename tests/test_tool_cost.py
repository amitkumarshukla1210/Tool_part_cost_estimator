"""Stage 4: tool cost engine. Rules, processes, machines, rates and formulas all come from master data; every value is traced."""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import costing_setup, mould_db, rate_engine, rates, tool_cost
from backend.app.main import app
from backend.app.trace import EXAMPLE_WARNING

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
MONTH = "2026-10"
client = TestClient(app)
COVER = dict(part_type="plastic", part_length_mm=120, part_width_mm=80, part_height_mm=30, projected_area_cm2=95.78,
             part_weight_g=48.66, part_volume_cm3=46.3, part_surface_cm2=420, material="ABS", as_of=MONTH)


def run(**kw):
    return tool_cost.run(tool_cost.ToolInput(**(COVER | {"cavities": 2} | kw)))


def line(r, element):
    return next(l for l in r["lines"] if l["element"] == element)


def val(r, node):
    return r["nodes"][node]["value"]


def step(r, name):
    return val(r, f"calc:{name}")


# ---------- the calculation ----------

def test_machine_hours_are_priced_with_mhr_plus_operators_times_labour():
    r = run()
    cnc = line(r, "Insert machining - CNC")
    mhr = rate_engine.mhr("VMC-850", "IN", MONTH)["value"]
    labour = rate_engine.labour_rate("skilled_machinist", "IN", MONTH)["value"]
    # Tool processes: CNC milling on VMC-850 with 1 skilled machinist.
    assert cnc["process_cost"] == pytest.approx(cnc["hours"] * (mhr + 1 * labour), rel=1e-9)
    # hours each = set-up + box ÷ 2 ÷ roughing rate + surface ÷ 2 ÷ finishing rate (Process time parameters)
    each = 2 + 120 * 80 * 30 / 1000 / 2 / 300 + 420 / 2 / 40
    assert cnc["hours"] == pytest.approx(4 * each, rel=1e-9)        # 2 × cavities insert halves
    edm = line(r, "Insert machining - EDM")                       # EDM: 0.5 operator per machine
    assert edm["process_cost"] == pytest.approx(
        edm["hours"] * (rate_engine.mhr("EDM-SINK", "IN", MONTH)["value"] + 0.5 * labour), rel=1e-9)
    design = line(r, "Tool design")                               # labour hours only, no machine
    assert design["process_cost"] == pytest.approx(
        design["hours"] * rate_engine.labour_rate("designer", "IN", MONTH)["value"], rel=1e-9)
    # The MHR in the trace opens to its breakup (depreciation, power, ...).
    root = r["nodes"]["ph:CNC milling"]
    mhr_node = next(i["node"] for i in root["inputs"] if i["name"] == "mhr")
    assert r["nodes"][mhr_node]["formula"] == "machine_cost + overhead"


def test_unit_priced_process_uses_the_rate_by_unit_and_the_minimum_charge():
    r = run(part_type="die_casting", cavities=1, material="Aluminium ADC12 / A383")
    ht = line(r, "Insert heat treatment")
    rate = rates.lookup("process_unit", "Heat treatment (per kg)", "IN", MONTH)["value"]
    minimum = rates.lookup("process_min_charge", "Heat treatment (per kg)", "IN", MONTH)["value"]
    assert ht["pricing"] == "unit" and ht["hours"] == 0
    assert ht["process_cost"] == pytest.approx(max(minimum, ht["quantity"] * ht["amount"] * rate), rel=1e-9)
    assert r["nodes"][ht["nodes"]["proc"]]["formula"] == "max(min_charge, qty * amount * rate)"
    cut = line(r, "Steel block cutting")                          # cutting has no minimum charge
    assert cut["process_cost"] == pytest.approx(
        cut["quantity"] * cut["amount"] * rates.lookup("process_unit", "Cutting (per kg)", "IN", MONTH)["value"], rel=1e-9)


def test_tool_cost_follows_the_formulas_in_master_data():
    r = run(tools_count=3)
    groups = sum(val(r, g["node"]) for g in r["groups"])
    assert val(r, "sum:process") + val(r, "sum:design") == pytest.approx(groups, rel=1e-12)
    assert sum(l["total"] for l in r["lines"]) == pytest.approx(
        val(r, "sum:material") + val(r, "sum:bought_out") + groups, rel=1e-12)
    mfg = step(r, "manufacturing_cost")
    assert mfg == pytest.approx(val(r, "sum:material") + val(r, "sum:bought_out") + val(r, "sum:process")
                                + val(r, "sum:design") + step(r, "trial_cost"), rel=1e-12)
    price = mfg * 1.12 * 1.10                                      # overhead 12 %, profit 10 % (EXAMPLE rates)
    assert step(r, "tool_price") == pytest.approx(price, rel=1e-12)
    assert r["value"] == pytest.approx(price * (1 + 0.01 + 0.03) + val(r, "tool_weight") * 8, rel=1e-12)
    assert r["capex"] == pytest.approx(3 * r["value"]) and r["capex_inr"] == pytest.approx(r["capex"])
    no_warranty = run(warranty=False)
    assert no_warranty["value"] == pytest.approx(r["value"] - 0.03 * price, rel=1e-12)


def test_trial_machine_is_the_smallest_that_takes_the_clamp_force():
    r = run()
    force = 95.78 * 2 * 400 * 1.2 / 1000                           # area × cavities × pressure × safety ÷ 1000
    assert r["trial"]["force_t"] == pytest.approx(force) and r["trial"]["machine"]["machine_id"] == "IMM-120"
    assert run(cavities=4)["trial"]["machine"]["machine_id"] == "IMM-200"   # 184 t
    trial = 3 * 4 * (rate_engine.mhr("IMM-120", "IN", MONTH)["value"]
                     + rate_engine.labour_rate("toolmaker", "IN", MONTH)["value"])
    material = 3 * 200 * 2 * 48.66 / 1000 * rates.lookup("material", "ABS", "IN", MONTH)["value"]
    assert step(r, "trial_cost") == pytest.approx(trial + material, rel=1e-9)


def test_no_machine_big_enough_is_reported_not_hidden():
    r = run(projected_area_cm2=9000, part_length_mm=100, part_width_mm=90)   # 4320 t: above the 3000 t ladder
    assert not r["priced"] and r["trial"]["machine"] is None
    assert any("Injection moulding" in m and "takes" in m for m in r["missing"])


def test_other_country_uses_its_own_rates_and_currency():
    india, china = run(), run(country="CN")
    assert china["currency"] == "CNY"
    fx = rates.lookup("forex", "CNY", "", MONTH)["value"]
    assert china["value_inr"] == pytest.approx(china["value"] * fx, rel=1e-12)
    steel = rates.lookup("tool_material", "2738 (1.2738)", "CN", MONTH)
    assert val(china, "steel:2738 (1.2738)") == steel["value"]
    # catalogue prices (INR in master data) are converted
    base = line(china, "Mould base Standard 2-plate 3040")
    assert base["total"] == pytest.approx(china["base"]["cost"] / fx, rel=1e-9)
    assert china["value_inr"] != pytest.approx(india["value_inr"])


def test_missing_rate_marks_the_result_not_priced():
    r = run(material="Unobtainium")
    assert not r["priced"] and any("Unobtainium" in m for m in r["missing"])
    assert step(r, "trial_material_cost") == 0


def test_sheet_metal_and_foundry_tools_come_later():
    for pt, msg in (("sheet_metal", "stages 9 and 10"), ("foundry", "later stage")):
        with pytest.raises(tool_cost.ToolCostError, match=msg):
            run(part_type=pt)


def test_every_value_is_traceable():
    r = run()
    for nid, n in r["nodes"].items():
        if n["kind"] == "calculated":
            assert n["formula"]
            for i in n["inputs"]:
                assert i["node"] in r["nodes"], (nid, i)
        else:
            assert n["source"]["type"] != "unknown", nid
    for l in r["lines"]:
        for k, node in l["nodes"].items():
            assert node is None or node in r["nodes"], (l["element"], k)
    assert r["nodes"][r["root"]]["label"] == "Tool cost per tool"
    assert r["nodes"]["v:cnc_rough_cm3_per_h"]["source"]["sheet"].endswith("Process time parameters")


# ---------- master data drives everything ----------

def test_editing_master_data_changes_the_result():
    before = run()
    db = mould_db.tables()
    for t in db["time_parameters"]:
        if t["part_type"] == "plastic" and t["parameter"] == "cnc_finish_cm2_per_h":
            t["value"] = 80
    for p in db["tool_processes"]:
        if p["code"] == "CNC milling":
            p["machine_id"] = "HSM-5AX"
    mould_db.write(db)
    after = run()
    cnc_b, cnc_a = line(before, "Insert machining - CNC"), line(after, "Insert machining - CNC")
    assert cnc_a["hours"] == pytest.approx(cnc_b["hours"] - 4 * (420 / 2 / 40 - 420 / 2 / 80))
    assert any(k.startswith("mhr:HSM-5AX:") for k in after["nodes"])

    setup = costing_setup.tables()
    for f in setup["cost_formulas"]:
        if f["scope"] == "tool" and f["name"] == "tool_transport":
            f["formula"] = "0"
    costing_setup.write(setup)
    assert step(run(), "tool_transport") == 0


def test_setup_checks_for_tool_formulas():
    setup = costing_setup.tables()
    for r in setup["formula_inputs"]:
        if r["scope"] == "tool" and r["variable"] == "material_cost":
            r["item"] = "gold_cost"
    res = client.put("/api/costing-setup", json=setup)
    assert res.status_code == 400 and "tool value must be one of" in res.json()["detail"]
    setup = costing_setup.tables()
    setup["formula_inputs"].append({"scope": "mhr", "variable": "x", "label": "", "source": "tool", "category": "",
                                    "item": "cavities", "is_money": False, "unit": ""})
    res = client.put("/api/costing-setup", json=setup)
    assert res.status_code == 400 and "only for the tool scopes" in res.json()["detail"]


# ---------- example warning ----------

def test_example_values_are_flagged_with_counts_and_on_every_export():
    r = run()
    ex = r["example"]
    assert ex["any"] and ex["warning"] == EXAMPLE_WARNING and ex["rates"] > 0
    assert "Machines · VMC-850" in ex["rows"] and any(x.startswith("Tool processes") for x in ex["rows"])
    body = COVER | {"cavities": 2}
    x = client.post("/api/tool-cost/export.xlsx", json=body)
    wb = load_workbook(io.BytesIO(x.content))
    assert {"Summary", "Cost build-up", "BOM & processes", "Steps", "Inputs", "Rates used", "Example values"} <= set(wb.sheetnames)
    for ws in wb.worksheets:
        assert ws["A1"].value == EXAMPLE_WARNING, ws.title
    pdf = client.post("/api/tool-cost/export.pdf", json=body)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_examples_helper_is_clean_when_nothing_is_an_example():
    tr = {"rates_used": [{"id": 1, "is_example": False}],
          "nodes": {"a": {"kind": "input", "source": {"type": "master", "sheet": "x", "row": "y", "is_example": False}}},
          "lines": [{"element": "Guide pillar", "is_example": False}]}
    ex = tool_cost.examples(tr)
    assert not ex["any"] and ex["warning"] == "" and ex["detail"] == ""


# ---------- part register ----------

def project(code="T", budget=None):
    return client.post("/api/projects", json={"code": code, "name": "Test", "capex_budget_inr": budget}).json()


def add_part(p, file="plastic_cover.step", material="ABS", process="injection_moulding", code="PC-1"):
    with open(SAMPLES / file, "rb") as fh:
        m = client.post("/api/import/step", files={"file": (file, fh)}).json()
    r = client.post(f"/api/import/{m['token']}/commit", json={
        "project_id": p["id"], "items": {m["root"]: {"material": material, "process": process, "part_code": code}}})
    assert r.status_code == 200, r.text
    return r.json()["part_ids"][0]


def detail(pid):
    return client.get(f"/api/parts/{pid}").json()


def test_registered_part_gets_a_tool_cost_version_automatically():
    pid = add_part(project(budget=5_000_000))
    d = detail(pid)
    t = d["tool"]
    v = t["latest"]
    assert t["applicable"] and v["version"] == 1 and v["part_type"] == "plastic" and v["country"] == "IN"
    assert v["is_example"] and d["tool_cost_inr"] == v["tool_cost_inr"] and d["tool_capex_inr"] == v["tool_capex_inr"]
    assert v["cavities"] == t["live"]["stage_c"]["cavities_per_tool"]   # cavities from Stage C
    assert t["outdated"] == "" and t["problem"] == ""
    tr = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    assert tr["stored"] and tr["nodes"]["v:part_l"]["source"]["type"] == "cad"
    assert "Stage C" in tr["nodes"]["v:cavities"]["source"]["note"]
    assert client.post(f"/api/parts/{pid}/tool-cost", json={}).json()["stored"] is False   # nothing changed


def test_typed_tool_features_and_tool_country_make_a_new_version():
    pid = add_part(project())
    res = client.post(f"/api/parts/{pid}/tool-cost", json={"tool_inputs": {"cavities": 4, "slides_per_cavity": 1},
                                                          "tool_country": "CN"}).json()
    assert res["stored"] and res["version"] == 2
    v = res["part"]["tool"]["latest"]
    assert v["cavities"] == 4 and v["country"] == "CN" and v["currency"] == "CNY"
    tr = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    assert tr["nodes"]["v:cavities"]["source"]["type"] == "user"
    assert any(l["element"] == "Slide block" for l in tr["lines"])
    bad = client.post(f"/api/parts/{pid}/tool-cost", json={"tool_inputs": {"cavities": 0}})
    assert bad.status_code == 400 and "between 1 and 256" in bad.json()["detail"]
    assert client.put(f"/api/parts/{pid}", json={"tool_inputs": {"colour": 1}}).status_code == 400


def test_new_approved_rate_marks_tool_cost_outdated_until_recalculated():
    pid = add_part(project())
    client.put("/api/settings", json={"approver_name": "Tester"})
    old = detail(pid)["tool"]["latest"]
    client.post("/api/rates", json={"category": "tool_material", "item": "2738 (1.2738)", "country": "IN", "value": 500,
                                    "unit": "INR/kg", "currency": "INR", "month": MONTH, "approve": True})
    t = detail(pid)["tool"]
    assert t["latest"]["version"] == old["version"] and "Newer approved rates" in t["outdated"]
    assert any(c["new_value"] == 500 for c in t["rate_changes"])
    res = client.post(f"/api/projects/{detail(pid)['project_id']}/tool-cost/recalculate").json()
    assert res["new_versions"] == 1
    new = detail(pid)["tool"]["latest"]
    assert new["version"] == old["version"] + 1 and new["tool_cost_inr"] > old["tool_cost_inr"]


def test_parts_without_a_tool_say_why():
    p = project()
    sm = add_part(p, "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage", "SM-1")
    t = detail(sm)["tool"]
    assert not t["applicable"] and "stages 9 and 10" in t["problem"]
    bo = add_part(p, code="BO-1")
    client.put(f"/api/parts/{bo}", json={"sourcing": "bought_out"})
    assert "bought ready-made" in detail(bo)["tool"]["problem"]


def test_search_dashboard_and_exports_show_the_tool_cost():
    p = project(budget=2_000_000)
    pid = add_part(p)
    add_part(p, "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage", "SM-1")
    d = detail(pid)
    rows = client.get("/api/parts", params={"project_id": p["id"], "tool_min": 1}).json()["rows"]
    assert [r["id"] for r in rows] == [pid] and rows[0]["tool_is_example"]
    assert client.get("/api/parts", params={"project_id": p["id"], "tool_missing": "yes"}).json()["total"] == 0
    dash = client.get(f"/api/projects/{p['id']}/dashboard").json()
    cap = dash["capex"]
    assert cap["tool_cost_inr"] == pytest.approx(d["tool_capex_inr"]) and cap["tool_parts_costed"] == 1
    assert cap["tool_is_example"] and cap["tool_share_of_budget_pct"] == round(100 * d["tool_capex_inr"] / 2_000_000, 1)
    x = client.get(f"/api/parts/{pid}/tool-cost/export.xlsx")
    wb = load_workbook(io.BytesIO(x.content))
    assert all(ws["A1"].value == EXAMPLE_WARNING for ws in wb.worksheets)
    assert client.get(f"/api/parts/{pid}/tool-cost/export.pdf").content.startswith(b"%PDF")
    parts = load_workbook(io.BytesIO(client.get("/api/parts/export.xlsx", params={"project_id": p["id"]}).content)).active
    assert parts["A1"].value == EXAMPLE_WARNING and "tool_capex_inr" in [c.value for c in parts[2]]
    assert client.get(f"/api/projects/{p['id']}/dashboard.pdf").content.startswith(b"%PDF")
