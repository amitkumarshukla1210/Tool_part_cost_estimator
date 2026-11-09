"""Stage 54: 24-month history for every rate (market where free, indicative otherwise), more grades."""

import pytest

from backend.app import auto_rates, master_data, price_history, rates

MONTHS = ["2024-11", "2024-12"] + [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 11)]


def hist():
    ramp = lambda a, step: {m: a + i * step for i, m in enumerate(MONTHS)}
    return {"series": {"aluminium": {"values": ramp(2000.0, 20.0)}, "ppi_steel": {"values": ramp(300.0, 3.0)},
                       "ppi_resins": {"values": ramp(250.0, 1.0)}, "nickel": {"values": ramp(15000.0, 50.0)},
                       "ppi_power": {"values": ramp(180.0, 1.0)}, "ppi_sea": {"values": ramp(500.0, 2.0)},
                       "fx_INR": {"values": ramp(84.0, 0.5)}, "fx_CNY": {"values": ramp(7.2, -0.02)},
                       "fx_EUR": {"values": ramp(1.05, 0.005)},
                       "elec_eurostat_DE": {"values": {"2024-S2": 0.21, "2025-S1": 0.19, "2025-S2": 0.18, "2026-S1": 0.17}}},
            "ilo": {"hourly_by_skill": {"IND|OCU_SKILL_TOTAL|CUR_TYPE_LCU": {"2024": {"value": 80.0}, "2025": {"value": 90.0}}}}}


def test_every_rate_gets_24_months_market_or_indicative():
    res = price_history.backfill(hist(), end="2026-11")
    assert res["months"] == "2024-12..2026-11" and res["total"] > 1000
    adc = rates.lookup("material", "Aluminium ADC12 / A383", "CN", "2025-01")
    base = rates.lookup("material", "Aluminium ADC12 / A383", "CN", "2026-10")
    a = hist()["series"]
    ratio = (a["aluminium"]["values"]["2025-01"] * a["fx_CNY"]["values"]["2025-01"]) / (
        a["aluminium"]["values"]["2026-10"] * a["fx_CNY"]["values"]["2026-10"])
    assert adc["value"] == pytest.approx(base["value"] * ratio, rel=5e-3)
    assert adc["is_example"] and adc["source"].startswith("INDICATIVE history") and adc["approved_by"] == "Indicative history"
    cny = rates.lookup("forex", "CNY", "", "2025-03")                                      # forex: market, not example
    assert cny["value"] == pytest.approx(a["fx_INR"]["values"]["2025-03"] / a["fx_CNY"]["values"]["2025-03"], rel=5e-3)
    assert not cny["is_example"] and cny["source"].startswith("Market history")
    assert rates.lookup("power", "electricity_industrial", "DE", "2025-03")["value"] == 0.19      # Eurostat half-year
    assert rates.lookup("labour_salary", "operator", "IN", "2024-12")["value"] == pytest.approx(
        rates.lookup("labour_salary", "operator", "IN", "2026-10")["value"] * 80 / 90, rel=5e-3)  # ILO year ratio
    p20 = rates.lookup("tool_material", "NAK80", "IN", "2025-06")                           # no own index: steel PPI
    assert "US PPI: steel" in p20["source"]
    flat = rates.lookup("machine_price", "BANDSAW", "IN", "2024-12")                       # no index: flat, once
    assert flat["value"] == rates.lookup("machine_price", "BANDSAW", "IN", "2026-10")["value"] and flat["month"] == "2024-12"
    assert price_history.backfill(hist(), end="2026-11")["total"] == 0                     # idempotent


def test_an_existing_month_is_never_overwritten():
    rates.create({"category": "material", "item": "ABS", "country": "IN", "value": 150, "unit": "INR/kg", "currency": "INR",
                  "month": "2025-05", "source": "my quote"}, approve=True, approver="me", system=True)
    price_history.backfill(hist(), end="2026-11")
    assert rates.lookup("material", "ABS", "IN", "2025-05")["source"] == "my quote"
    assert rates.lookup("material", "ABS", "IN", "2025-04")["source"].startswith("INDICATIVE")   # before my quote: filled


def test_auto_update_fills_the_history_once(tmp_path, monkeypatch):
    from tests.test_country_rate_book import TODAY, fake
    monkeypatch.setattr(rates, "current_month", lambda: "2026-11")
    res = auto_rates.run(out_dir=tmp_path, http=fake, today=TODAY, build=False)
    assert "24-month history filled" in res["message"] and auto_rates.status()["history_done"]
    assert auto_rates.run_if_due() is None


def test_more_stainless_en_steel_and_plastic_grades():
    mats = {m["material"]: m for m in master_data.tables()["Materials"]}
    for name in ("Stainless steel 316L (1.4404)", "Stainless steel 202 (J4)", "EN24 (817M40, 34CrNiMo6) bar", "EN353 (815M17) bar",
                 "20MnCr5 (1.7147) bar", "HR IS 2062 E250 (S235)", "HDPE (injection grade)", "PMMA (acrylic)", "PA6 GF30",
                 "TPU (thermoplastic polyurethane)", "PPS GF40"):
        assert name in mats
        assert rates.lookup("material", name, "IN")["is_example"]
    assert mats["HDPE (injection grade)"]["material_type"] == "Polyethylene (PE)" and mats["HDPE (injection grade)"]["recommended"] == "yes"
    assert rates.lookup("tool_material", "Vanadis 4E (powder)", "CN")["value"] == rates.lookup("tool_material", "D2 (1.2379)", "CN")["value"]
