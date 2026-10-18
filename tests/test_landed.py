import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import landed, rates
from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)
M = "2026-10"


def test_import_cost_by_hand_standard_and_fta():
    used = {}
    r = landed.import_cost(100.0, 2.0, "CN", "3926", M, "sea", False, used)
    freight = 12 * 2
    ins = 0.005 * (100 + freight)
    cif = 100 + freight + ins
    bcd = cif * 0.10
    sws = bcd * 0.10
    igst = (cif + bcd + sws) * 0.18
    clear = cif * 0.008
    inland = 8 * 2
    assert r["freight"] == freight and r["cif"] == pytest.approx(cif) and r["bcd"] == pytest.approx(bcd)
    assert r["igst"] == pytest.approx(igst) and r["landed_with_igst"] == pytest.approx(cif + bcd + sws + igst + clear + inland)
    assert r["igst_credit"] == pytest.approx(igst) and r["landed"] == pytest.approx(r["landed_with_igst"] - igst)
    assert r["duty_basis"] == "standard rate" and used
    jp = landed.import_cost(100.0, 2.0, "JP", "3926", M, "sea", True, {})
    assert jp["bcd_pct"] == 0 and jp["duty_basis"] == "FTA preferential rate"
    assert landed.import_cost(100.0, 2.0, "JP", "3926", M, "sea", False, {})["bcd_pct"] == 10          # FTA switched off
    air = landed.import_cost(100.0, 2.0, "CN", "3926", M, "air", False, {})
    assert air["freight"] == 280 * 2
    home = landed.import_cost(100.0, 2.0, "IN", "3926", M, "sea", True, {})
    assert home["bcd"] == 0 and home["landed"] == pytest.approx(100 + 16)


def test_a_missing_rate_is_reported_not_raised_for_the_rest():
    with pytest.raises(rates.RateMissing):
        landed.import_cost(100.0, 1.0, "CN", "9999", M, "sea", False, {})


def test_country_comparison_endpoint_and_exports():
    pid = add_part(project("LC11"))
    r = client.get(f"/api/parts/{pid}/country-comparison", params={"countries": "IN,CN,JP"})
    assert r.status_code == 200, r.text
    res = r.json()
    by = {x["country"]: x for x in res["rows"]}
    assert set(by) == {"IN", "CN", "JP"} and all(not x["error"] for x in res["rows"])
    for x in res["rows"]:
        comp = x["components_inr"]
        assert sum(comp.values()) == pytest.approx(x["exw_inr"])                    # the breakup adds up
        assert x["exw_usd"] == pytest.approx(x["exw_inr"] / 83.5)
    assert by["IN"]["landed"]["bcd"] == 0 and by["CN"]["landed"]["bcd"] > 0
    assert by["JP"]["landed"]["duty_basis"] == "FTA preferential rate"
    assert res["cheapest"] == min(res["rows"], key=lambda x: x["landed"]["landed"])["country"]
    s = by["CN"]["forex"]["scenario"]
    assert s["+5%"] > s["0%"] > s["-5%"] and by["IN"]["forex"]["scenario"]["+5%"] == by["IN"]["forex"]["scenario"]["0%"]
    wb = load_workbook(io.BytesIO(client.get(f"/api/parts/{pid}/country-comparison/export.xlsx", params={"countries": "IN,CN"}).content))
    assert wb.sheetnames == ["Comparison (INR)", "Forex scenario", "Duty basis", "Rates used"]
    assert client.get(f"/api/parts/{pid}/country-comparison/export.pdf", params={"countries": "IN,CN"}).content[:4] == b"%PDF"
    assert client.get(f"/api/parts/{pid}/country-comparison", params={"countries": "ZZ"}).status_code == 400
    assert client.get(f"/api/parts/{pid}/country-comparison", params={"mode": "rail"}).status_code == 400
