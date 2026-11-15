"""Stage 64: fin parts in the country comparison and landed cost; fin foils follow the aluminium / copper index
(24-month history and monthly update), and flat fin-foil history gets indexed versions on top (append-only)."""

import pytest
from fastapi.testclient import TestClient

from backend.app import country_rate_book as crb, fin_die, fin_part, mould_db, price_history, rates
from backend.app.main import app
from tests.test_fin_part import fin_part_id
from tests.test_price_history import MONTHS, hist

client = TestClient(app)
FOIL = fin_die.DEFAULT_MATERIAL                     # Al fin foil 8011-H24 hydrophilic coated
CU = "Cu fin foil C1220-O (DHP)"


def test_hs_codes_of_fin_shipped():
    assert fin_part.seed_hs() == 0
    hs = {(r["scope"], r["part_type"]): r for r in mould_db.tables()["hs_codes"]}
    assert hs[("part", "fin")]["hs_code"] == "7616" and hs[("tool", "fin")]["hs_code"] == "8207"
    assert hs[("part", "fin")]["is_example"] and hs[("tool", "fin")]["is_example"]


def test_fin_foils_follow_aluminium_and_copper():
    assert crb.index_for(FOIL) == "aluminium" and crb.index_for(CU) == "copper"
    assert crb.family_of(FOIL).startswith("Aluminium - wrought") and crb.family_of(CU) == "Copper & copper alloys"
    assert price_history.index_key("material_scrap", FOIL) == "aluminium"
    assert crb.index_for("PA66 GF30") == "ppi_resins" and crb.index_for("Aluminium ADC12 / A383") == "aluminium"   # unchanged


def test_country_comparison_and_landed_cost_of_a_fin_part():
    pid, _ = fin_part_id("FIN-7")
    assert client.put(f"/api/parts/{pid}", json={"compare_countries": ["CN", "VN"]}).status_code == 200
    v = client.get(f"/api/parts/{pid}/vs-country")
    assert v.status_code == 200, v.text
    v = v.json()
    for w in ("rm", "tool", "piece"):
        assert "error" not in v["own"][w], v["own"][w]
    assert v["own"]["piece"]["landed_inr"] > 0 and v["own"]["tool"]["landed_inr"] > 0
    for b in v["countries"]:
        assert not b["error"] and not b.get("rm_error"), b
        assert b["landed_inr"]["piece"] > 0 and b["landed_inr"]["tool"] > 0 and b["is_example"]
        assert b["traces"]["tool"]["value_inr"] > 0                        # the fin die worked out in that country
        assert b["saving_inr"]["piece"] == pytest.approx(b["landed_inr"]["piece"] - v["own"]["piece"]["landed_inr"])
        assert any(r["item"] == FOIL and r["country"] == b["country"] for r in b["rates_used"])   # the country's own foil rate
    allc = client.get(f"/api/parts/{pid}/country-comparison").json()
    assert all(not r["error"] for r in allc["rows"]) and len(allc["rows"]) >= 9
    cn = next(r for r in allc["rows"] if r["country"] == "CN")
    assert cn["landed"]["hs"] == "7616" and cn["tool"]["landed"]["hs"] == "8207" and cn["landed"]["bcd"] > 0
    for kind in ("xlsx", "pdf"):
        r = client.get(f"/api/parts/{pid}/vs-country/export.{kind}")
        assert r.status_code == 200 and len(r.content) > 1000


def _flat_history(item, country="CN"):
    """The PC state before stage 64: the fin foil was dated back once, flat, by stage 57 fill_new."""
    base = rates.lookup("material", item, country, "2026-10")
    rates.create({"category": "material", "item": item, "country": country, "value": base["value"], "unit": base["unit"],
                  "currency": base["currency"], "month": "2024-12", "source": price_history.FLAT + " (no free index for it)",
                  "is_example": True}, approve=True, origin=price_history.ORIGIN, approver=price_history.USER, system=True)
    return base


def test_flat_fin_foil_history_gets_indexed_versions():
    h = hist()
    h["series"]["copper"] = {"values": {m: 9000.0 + i * 30 for i, m in enumerate(MONTHS)}}
    base = _flat_history(FOIL)
    cu = _flat_history(CU)
    rates.create({"category": "material", "item": FOIL, "country": "CN", "value": 99.0, "unit": base["unit"],
                  "currency": base["currency"], "month": "2025-06", "source": "my quote"}, approve=True, approver="me", system=True)
    assert rates.lookup("material", FOIL, "CN", "2025-03")["value"] == base["value"]          # flat before
    assert price_history.flat_indexable() >= 2
    price_history.backfill(h, end="2026-11")
    a, fx = h["series"]["aluminium"]["values"], h["series"]["fx_CNY"]["values"]
    old = rates.lookup("material", FOIL, "CN", "2024-12")
    assert old["origin"] == "history" and old["source"].startswith("INDICATIVE history") and "×" in old["source"]
    # history before a rate follows the earliest real rate: here my quote of Jun-25 (99)
    assert old["value"] == pytest.approx(99.0 * a["2024-12"] * fx["2024-12"] / (a["2025-06"] * fx["2025-06"]), rel=5e-3)
    m3 = rates.lookup("material", FOIL, "CN", "2025-03")
    assert m3["month"] == "2025-03" and m3["value"] != base["value"]                          # every month now
    assert rates.lookup("material", FOIL, "CN", "2025-06")["source"] == "my quote"           # my rate never touched
    c1 = rates.lookup("material", CU, "CN", "2025-01")                                        # copper index, from the set-up rate
    cp = h["series"]["copper"]["values"]
    assert c1["value"] == pytest.approx(cu["value"] * cp["2025-01"] * fx["2025-01"] / (cp["2026-10"] * fx["2026-10"]), rel=5e-3)
    with_flat = [r for r in rates.history("material", FOIL, "CN") if r["month"] == "2024-12"]
    assert len(with_flat) == 2                                                                 # append-only: flat row kept
    assert price_history.flat_indexable(h["series"]) == 0                                     # nothing left that has index data
    assert price_history.backfill(h, end="2026-11")["total"] == 0                              # idempotent
