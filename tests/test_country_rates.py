import pytest
from fastapi.testclient import TestClient

from backend.app import costing_setup, country_rates, mould_db, rates
from backend.app.main import app

client = TestClient(app)
MONTH = "2026-10"


def approved(category, item, country):
    return rates.lookup(category, item, country, MONTH)


def test_seed_covers_all_countries_and_groups():
    grid = country_rates.grid(MONTH)
    codes = {c["code"] for c in grid["countries"]}
    assert len(codes) >= 9
    by_cat = {g["category"]: g for g in grid["groups"]}
    for cat, g in by_cat.items():
        assert g["items"], cat
        for it in g["items"]:
            assert set(it["cells"]) == codes, (cat, it["item"])
            assert all(c["rate"]["is_example"] for c in it["cells"].values())
    items = {it["item"] for it in by_cat["tool_material"]["items"]}
    assert {"P20 (1.2311)", "H13 (1.2344)", "2738 (1.2738)", "D2 (1.2379)", "SKD11 (JIS)",
            "Mould base steel (4140 / 1.7225)"} <= items
    units = {it["item"]: it["unit"] for it in by_cat["process_unit"]["items"]}
    assert units["Heat treatment (per kg)"] == "kg"
    assert units["Wire cut (per cm²)"] == "cm²"
    assert units["Polishing (per cm²)"] == "cm²"
    assert units["Painting (per m²)"] == "m²"
    assert units["Transport (per kg)"] == "kg"


def test_master_data_values_became_first_approved_version():
    row = next(r for r in mould_db.tables()["tool_materials"] if r["code"] == "H13 (1.2344)")
    r = approved("tool_material", "H13 (1.2344)", "IN")
    assert r["value"] == row["rate_per_kg"] and r["unit"] == "INR/kg" and r["status"] == "approved"


def test_other_country_is_base_times_index_over_forex():
    idx = {r["country"]: r for r in costing_setup.tables()["country_index"]}["JP"]
    base = approved("tool_material", "P20 (1.2311)", "IN")["value"]
    jpy = rates.lookup("forex", "JPY", "", MONTH)["value"]
    got = approved("tool_material", "P20 (1.2311)", "JP")
    assert got["currency"] == "JPY" and got["unit"] == "JPY/kg"
    assert got["value"] == pytest.approx(base * idx["tool_steel_index"] / jpy, rel=0.01)  # 3 significant digits


def test_propose_only_fills_gaps_and_makes_drafts():
    assert country_rates.propose(MONTH)["created"] == 0            # everything already has a rate
    rates.create({"category": "tool_material", "item": "Maraging 300", "country": "IN", "value": 2000,
                  "unit": "INR/kg", "currency": "INR", "month": MONTH}, approve=True, approver="t")
    res = country_rates.propose(MONTH)
    assert res["created"] == len(costing_setup.countries()) - 1 and res["status"] == "draft"
    with pytest.raises(rates.RateMissing):                         # drafts are not used in costing
        approved("tool_material", "Maraging 300", "CN")
    assert {d["draft"]["country"] for d in rates.review()["items"]} >= {"CN", "DE", "US"}
    assert country_rates.propose(MONTH)["created"] == 0            # second run adds nothing


def test_country_without_index_is_skipped_with_reason():
    data = costing_setup.tables()
    data["country_index"] = [r for r in data["country_index"] if r["country"] != "VN"]
    costing_setup.write(data)
    rates.create({"category": "process_hour", "item": "Lapping", "country": "IN", "value": 600, "unit": "INR/h",
                  "currency": "INR", "month": MONTH}, approve=True, approver="t")
    res = country_rates.propose(MONTH)
    assert [s["country"] for s in res["skipped"]] == ["VN"]
    assert "Country rate index" in res["skipped"][0]["reason"]


def test_index_table_is_validated():
    data = costing_setup.tables()
    data["country_index"][1]["process_index"] = 0
    with pytest.raises(costing_setup.SetupError, match="Country rate index row 3"):
        costing_setup.write(data)
    data = costing_setup.tables()
    data["country_index"][1]["country"] = "XX"
    with pytest.raises(costing_setup.SetupError, match="not in Countries"):
        costing_setup.write(data)


def test_grid_shows_inr_and_difference_against_india():
    it = next(i for g in country_rates.grid(MONTH)["groups"] if g["category"] == "process_unit"
              for i in g["items"] if i["item"] == "Polishing (per cm²)")
    india, cn = it["cells"]["IN"], it["cells"]["CN"]
    assert india["vs_base_pct"] == 0 and india["inr"] == india["rate"]["value"]
    assert cn["vs_base_pct"] == pytest.approx((cn["inr"] - india["inr"]) / india["inr"] * 100, abs=0.1)


def test_rm_cost_now_works_for_another_country():
    # part-material rates exist for every country, so the Stage 2 RM lookup works outside India
    for cat in ("material", "material_scrap"):
        assert approved(cat, "ABS", "DE")["currency"] == "EUR"


def test_api_grid_and_propose():
    body = client.get(f"/api/rates/grid?as_of={MONTH}").json()
    assert body["base"] == "IN" and len(body["groups"]) == 6
    r = client.post("/api/rates/propose-from-index", json={"month": MONTH})
    assert r.status_code == 200 and r.json()["created"] == 0
