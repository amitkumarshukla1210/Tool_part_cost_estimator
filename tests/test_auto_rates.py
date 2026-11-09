"""Monthly automatic country rate update (stage 52): approved rates by index / market, admin values kept."""

import pytest
from fastapi.testclient import TestClient

from backend.app import auto_rates, rates
from backend.app.main import app
from tests.test_country_rate_book import TODAY, fake

client = TestClient(app)


def hist(alu=None, extra=None, ilo=None):
    s = {"aluminium": {"meta": {}, "values": alu or {"2026-10": 2000.0, "2026-11": 2200.0}},
         "fx_INR": {"meta": {}, "values": {"2026-10": 95.0, "2026-11": 96.0}},
         "fx_CNY": {"meta": {}, "values": {"2026-10": 7.0, "2026-11": 7.0}},
         "fx_EUR": {"meta": {}, "values": {"2026-10": 1.1, "2026-11": 1.2}},
         "elec_eurostat_DE": {"meta": {}, "values": {"2025-S2": 0.19, "2026-S1": 0.174}}}
    s.update(extra or {})
    return {"series": s, "ilo": ilo or {}, "runs": []}


def adc12(month):
    return rates.lookup("material", "Aluminium ADC12 / A383", "CN", month)


def test_grade_follows_its_index_with_forex_and_stays_example():
    base = adc12("2026-10")
    res = auto_rates.apply(hist(), "2026-12")
    new = adc12("2026-12")
    assert new["month"] == "2026-12" and new["status"] == "approved" and new["approved_by"] == "Auto monthly update"
    assert new["value"] == pytest.approx(base["value"] * 1.1, rel=5e-3)                 # 2000 -> 2200, CNY/USD flat
    assert "index 2026-10→2026-11" in new["source"] and new["origin"] == "auto monthly"
    assert new["is_example"] == base["is_example"]                                       # EXAMPLE stays EXAMPLE
    assert res["written"]["material"] >= 5 and res["written"].get("material_scrap")       # scrap follows its grade
    again = auto_rates.apply(hist(), "2026-12")                                           # same month: nothing twice
    assert not again["written"].get("material") and again["kept"] > 0


def test_forex_and_german_power_from_the_market():
    auto_rates.apply(hist(), "2026-12")
    cny = rates.lookup("forex", "CNY", "", "2026-12")
    assert cny["value"] == pytest.approx(96.0 / 7.0, rel=5e-3) and "market 2026-11" in cny["source"]
    eur = rates.lookup("forex", "EUR", "", "2026-12")
    assert eur["value"] == pytest.approx(96.0 * 1.2, rel=5e-3)
    de = rates.lookup("power", "electricity_industrial", "DE", "2026-12")
    assert de["value"] == pytest.approx(0.174) and "Eurostat 2026-S1" in de["source"]


def test_admin_value_is_never_overwritten_and_becomes_the_base():
    auto_rates.apply(hist(), "2026-12")
    rates.create({"category": "material", "item": "Aluminium ADC12 / A383", "country": "CN", "value": 25, "unit": "CNY/kg",
                  "currency": "CNY", "month": "2027-01", "source": "admin quote"}, approve=True, approver="admin", system=True)
    auto_rates.apply(hist(), "2027-01")
    assert adc12("2027-01")["value"] == 25 and adc12("2027-01")["source"] == "admin quote"     # kept
    h = hist(alu={"2026-10": 2000.0, "2026-11": 2200.0, "2026-12": 2420.0, "2027-01": 2662.0},
             extra={"fx_CNY": {"meta": {}, "values": {"2026-12": 7.0, "2027-01": 7.0}}})
    auto_rates.apply(h, "2027-02")
    feb = adc12("2027-02")
    assert feb["value"] == pytest.approx(25 * 2662 / 2662, rel=5e-3) or feb["month"] == "2027-01"   # admin month = index month
    h["series"]["aluminium"]["values"]["2027-02"] = 2928.2
    h["series"]["fx_CNY"]["values"]["2027-02"] = 7.0
    auto_rates.apply(h, "2027-03")
    assert adc12("2027-03")["value"] == pytest.approx(25 * 2928.2 / 2662, rel=5e-3)          # from the admin's 25


def test_salaries_change_only_when_ilo_publishes_a_newer_year():
    ilo = {"hourly_by_skill": {"IND|OCU_SKILL_TOTAL|CUR_TYPE_LCU": {"2024": {"value": 85.7}}}}
    before = rates.lookup("labour_salary", "operator", "IN", "2026-12")["value"]
    res = auto_rates.apply(hist(ilo=ilo), "2026-12")
    assert not res["written"].get("labour_salary") and any("baseline 2024" in x for x in res["log"])
    ilo["hourly_by_skill"]["IND|OCU_SKILL_TOTAL|CUR_TYPE_LCU"]["2025"] = {"value": 91.7}
    auto_rates.apply(hist(ilo=ilo), "2027-01")
    new = rates.lookup("labour_salary", "operator", "IN", "2027-01")
    assert new["value"] == pytest.approx(before * 91.7 / 85.7, rel=5e-3) and "ILO 2024→2025" in new["source"]
    res = auto_rates.apply(hist(ilo=ilo), "2027-02")
    assert not res["written"].get("labour_salary")                                          # same ILO year: once only


def test_run_once_per_month_logs_and_builds_the_workbooks(tmp_path, monkeypatch):
    monkeypatch.setattr(rates, "current_month", lambda: "2026-11")
    res = auto_rates.run(out_dir=tmp_path, http=fake, today=TODAY)
    assert res["status"] == "ok" and len(res["workbooks"]) == 9 and "new approved rates for 2026-11" in res["message"]
    st = auto_rates.status()
    assert st["last_month"] == "2026-11" and not st["due"]
    assert auto_rates.run_if_due() is None                                                  # done for this month
    g = client.get("/api/admin/auto-rates").json()
    assert g["last_month"] == "2026-11" and g["runs"] and g["runs"][0]["source"] == "Auto monthly update"
