"""Stage 57: heat-exchanger fin dies - master data, fin die cost, fin part cost, press choice, API and downloads."""

import io
import math

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import costing_setup, fin_die, master_data, mould_db, price_history, rates
from backend.app.main import app

client = TestClient(app)


def test_seed_is_shipped_and_idempotent():
    assert not any(fin_die.seed().values())                       # rows are in the shipped master data already
    md = master_data.tables()
    foils = [r for r in md["Materials"] if r["part_type"] == "fin"]
    assert len(foils) == len(fin_die.foil_grades()) == 40         # 5 alloys × 4 tempers × plain / coated
    assert all(r["material_type"] == fin_die.FOIL_TYPE for r in foils)
    db = mould_db.tables()
    assert {r["pattern"] for r in db["fin_patterns"]} == set(fin_die.PATTERNS)
    ykc = next(r for r in db["fin_presses"] if r["machine_id"] == "FIN-125A")
    assert (ykc["max_foil_width_mm"], ykc["spm_min"], ykc["spm_max"], ykc["die_height_min_mm"], ykc["die_height_max_mm"],
            ykc["coil_od_max_mm"], ykc["coil_id_mm"], ykc["is_example"]) == (1080, 150, 300, 280, 330, 1200, 150, False)
    m = {r["machine_id"]: r for r in costing_setup.tables()["machines"]}
    assert (m["FIN-125A"]["tonnage_t"], m["FIN-125A"]["power_kw"], m["FIN-125A"]["process"]) == (125, 22, "Fin press")
    assert "TO CONFIRM" in m["FIN-125SH"]["notes"]
    assert all(r["is_example"] for r in db["bom_elements"] if r["part_type"] == "fin")


def test_rates_seeded_as_examples():
    for country in ("IN", "CN"):
        r = rates.lookup("material", fin_die.DEFAULT_MATERIAL, country, "2026-10")
        assert r["is_example"] and "EXAMPLE" in r["source"]
        assert rates.lookup("material_scrap", fin_die.DEFAULT_MATERIAL, country, "2026-10")
        assert rates.lookup("machine_price", "FIN-125A", country, "2026-10")["is_example"]
        assert rates.lookup("tool_material", fin_die.HAP, country, "2026-10")["is_example"]
        assert rates.lookup("process_unit", fin_die.OIL_ITEM, country, "2026-10")["is_example"]
    assert rates.lookup("process_unit", fin_die.OIL_ITEM, "IN", "2026-10")["value"] == fin_die.OIL_REF_INR


def test_reference_louver_die_and_fin_pack():
    """Your IFB φ5 × 66R × 4P louver die (spec INFB02M-20250807) on the YKC-48A-125."""
    r = fin_die.run({})
    d, p, s = r["die"], r["part"], r["summary"]
    assert d["die"]["holes_per_stroke"] == 264 and d["die"]["feed_mm"] == 64 and d["die"]["foil_width_mm"] == 848
    assert d["die"]["stations"] == 12                             # 3 draw + iron + louver + 7 fixed stations
    assert d["trial"]["machine"]["machine_id"] == "FIN-125A" == s["press"]
    n = p["nodes"]
    assert n["calc:fins_across"]["value"] == 33 and n["calc:fins_per_stroke"]["value"] == 5.5
    assert n["calc:fins_per_pack"]["value"] == math.ceil(700 * 21 / 25.4) == 579
    assert n["calc:strokes_per_pack"]["value"] == pytest.approx(579 / 5.5)
    assert n["calc:spm"]["value"] == pytest.approx(220 * 0.9)      # fin_spm × louver speed factor, below the press 300 SPM
    assert s["per_fin_inr"] == pytest.approx(s["pack_cost_inr"] / 579)
    assert s["per_kg_inr"] == pytest.approx(s["pack_cost_inr"] / n["calc:net_kg"]["value"])
    assert 0 < n["calc:net_kg"]["value"] < n["calc:gross_kg"]["value"]
    assert s["die_cost_inr"] > 0 and s["example"] and d["example"]["any"]
    assert not d["missing"] and not p["missing"]
    # every part-cost step is a master-data formula, clickable to its row
    assert all(n[x["node"]]["ref"]["table"] == "cost_formulas" for x in p["steps"])
    # the die cost is grafted into the part trace: the amortisation goes back to the die BOM
    assert n["die:" + d["root"]]["value"] == pytest.approx(d["value"])
    assert any(i["node"] == "die:" + d["root"] for i in n["calc:amortisation"]["inputs"])
    elements = {line["element"] for line in d["lines"]}
    assert {"Louver punch & die set", "Ironing punch", "Pierce & burring punch", "Row slit blade (upper + lower)"} <= elements
    spares = next(line for line in d["lines"] if line["element"] == "Spare pierce & burring punches")
    assert spares["quantity"] == math.ceil(264 * 10 / 100) == 27           # the 27 sets of your spec's free accessories
    assert next(line for line in d["lines"] if line["element"] == "Pierce & burring punch")["grade"] == fin_die.HAP


@pytest.mark.parametrize("pattern,stations,has,lacks", [
    ("plain", 10, set(), {"Louver punch & die set", "Ironing punch", "Wire cut - rippled cut-off blades"}),
    ("slit", 11, {"Slit (lance) punch & die set"}, {"Louver punch & die set"}),
    ("wavy", 11, {"Wave forming die (upper + lower)", "Wire cut - rippled cut-off blades"}, {"Louver punch & die set"}),
])
def test_patterns_change_the_die(pattern, stations, has, lacks):
    d = fin_die.run({"pattern": pattern})["die"]
    elements = {line["element"] for line in d["lines"]}
    assert d["die"]["stations"] == stations and has <= elements and not (lacks & elements)


def test_generic_geometry_and_foil_width_formula():
    r = fin_die.run({"tube_od_mm": 7, "hole_d_mm": 7.3, "row_pitch_mm": 18.19, "hole_pitch_mm": 21, "die_rows": 24, "progressions": 3,
                     "foil_width_mm": 0, "fin_rows": 2, "fin_holes": 16, "pattern": "plain"})
    d = r["die"]
    assert d["die"]["foil_width_mm"] == pytest.approx(24 * 18.19 + 2 * 5)   # rows × row pitch + 2 × edge trim (Parameters)
    assert d["nodes"]["v:foil_w"]["formula"] == "die_rows * row_pitch + 2 * trim"
    assert d["die"]["holes_per_stroke"] == 72 and d["die"]["feed_mm"] == 63
    assert d["trial"]["machine"]["machine_id"] == "FIN-063"                  # 446 mm foil: the 45 t press takes only 400 mm
    assert any(x.startswith("FIN-045: ") and "foil width" in x for x in d["trial"]["rejected"])


def test_press_choice_and_warnings():
    r = fin_die.run({"press": "FIN-200"})
    assert r["summary"]["press"] == "FIN-200"
    assert r["die"]["nodes"]["trial:machine"]["formula"].startswith("your choice")
    small = fin_die.run({"press": "FIN-045"})
    assert any("does not suit" in w and "foil width" in w for w in small["die"]["warnings"])
    with pytest.raises(fin_die.FinDieError, match="not a fin press"):
        fin_die.run({"press": "PRESS-200"})


def test_validation():
    for bad, msg in (({"fin_rows": 70}, "Fin rows"), ({"pattern": "pin"}, "pattern"), ({"progressions": 2.5}, "whole number"),
                     ({"hole_d_mm": 4}, "collar"), ({"foil_t_mm": 2}, "between")):
        with pytest.raises(fin_die.FinDieError, match=msg):
            fin_die.run(bad)


def test_other_country_in_its_currency():
    r = fin_die.run({"country": "CN"})
    assert r["die"]["currency"] == r["part"]["currency"] == "CNY"
    assert r["summary"]["pack_cost_inr"] == pytest.approx(r["part"]["value"] * r["part"]["fx_inr"])


def test_master_data_checks_fin_tables():
    db = mould_db.tables()
    db["fin_patterns"][0]["spm_factor"] = 0
    with pytest.raises(mould_db.MouldDbError, match="Fin patterns"):
        mould_db.write(db)
    db = mould_db.tables()
    db["fin_presses"][0]["spm_max"] = 10
    with pytest.raises(mould_db.MouldDbError, match="Fin presses"):
        mould_db.write(db)


def test_api_save_cost_and_downloads():
    opts = client.get("/api/fin-dies/options").json()
    assert {p["machine_id"] for p in opts["presses"]} >= {"FIN-125A", "FIN-125SH"} and fin_die.DEFAULT_MATERIAL in opts["materials"]
    live = client.post("/api/fin-dies/calculate", json={"spec": {"pattern": "plain"}})
    assert live.status_code == 200 and live.json()["die"]["die"]["stations"] == 10
    assert client.post("/api/fin-dies", json={"name": "", "spec": {}}).status_code == 400
    rec = client.post("/api/fin-dies", json={"name": "IFB φ5 × 66R × 4P louver", "spec": {}}).json()
    cost = client.get(f"/api/fin-dies/{rec['id']}/cost").json()
    assert cost["record"]["result"]["pack_cost_inr"] == pytest.approx(cost["summary"]["pack_cost_inr"])
    assert client.get("/api/fin-dies").json()[0]["result"]["press"] == "FIN-125A"
    upd = client.put(f"/api/fin-dies/{rec['id']}", json={"name": "renamed", "spec": {"pattern": "wavy"}}).json()
    assert upd["name"] == "renamed" and upd["spec"]["pattern"] == "wavy"
    x = client.get(f"/api/fin-dies/{rec['id']}/export.xlsx")
    assert x.status_code == 200 and x.headers["content-disposition"].endswith('renamed_fin_cost.xlsx"')
    wb = load_workbook(io.BytesIO(x.content))
    assert {"Summary", "Fin spec", "Die BOM", "Die cost steps", "Part cost steps", "Rates used"} <= set(wb.sheetnames)
    pdf = client.get(f"/api/fin-dies/{rec['id']}/export.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get("/fin-dies").status_code == 200
    assert client.delete(f"/api/fin-dies/{rec['id']}").status_code == 200
    assert client.get(f"/api/fin-dies/{rec['id']}").status_code == 400


def test_non_ascii_name_gives_a_safe_file_name():
    rec = client.post("/api/fin-dies", json={"name": "φ5 fin", "spec": {}}).json()
    r = client.get(f"/api/fin-dies/{rec['id']}/export.pdf")
    assert r.status_code == 200 and r.headers["content-disposition"] == 'attachment; filename="5_fin_fin_cost.pdf"'


def test_history_for_rates_added_later(tmp_path):
    assert price_history.missing() > 0                            # the shipped data has one month: history is made on the PC
    assert price_history.fill_new(tmp_path) is None               # no saved market history yet: nothing to do, no download
