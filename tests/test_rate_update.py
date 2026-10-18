import json

import pytest
from fastapi.testclient import TestClient

from backend.app import mould_db, rate_update, rates
from backend.app.main import app

client = TestClient(app)
M = "2026-10"
ECB = b"""<?xml version="1.0"?><gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<Cube><Cube time="2026-10-16"><Cube currency="USD" rate="1.0800"/><Cube currency="INR" rate="90.5"/><Cube currency="JPY" rate="160"/>
<Cube currency="CNY" rate="7.8"/></Cube></Cube></gesmes:Envelope>"""


def wb(**years):
    return json.dumps([{"page": 1}, [{"date": y, "value": v} for y, v in years.items()]]).encode()


def fake(url: str) -> bytes:
    if "ecb.europa.eu" in url:
        return ECB
    if "/country/IN/" in url:
        return wb(**{"2025": 200.0, "2024": 190.0, "2023": 180.0, "2026": None})
    if "/country/DE/" in url:
        raise OSError("connection refused")
    return wb(**{"2025": 100.0, "2023": 100.0})


def drafts(cat):
    return [r for r in rates.review()["items"] if r["draft"]["category"] == cat]


def test_ecb_forex_arrives_as_drafts_by_hand_and_is_not_duplicated():
    n, note = rate_update.fetch_forex(M, fake)
    by = {d["draft"]["item"]: d for d in drafts("forex")}
    assert by["USD"]["draft"]["value"] == pytest.approx(90.5 / 1.08, rel=1e-3) and by["USD"]["draft"]["status"] == "draft"
    assert by["EUR"]["draft"]["value"] == pytest.approx(90.5) and by["JPY"]["draft"]["value"] == pytest.approx(90.5 / 160, rel=1e-3)
    assert by["USD"]["approved"]["value"] == 83.5 and by["USD"]["change_pct"] == pytest.approx((90.5 / 1.08 - 83.5) / 83.5 * 100, abs=0.1)
    assert "KRW" in note and n == 4                                          # KRW, THB, TWD, VND are not in this ECB sample
    assert rate_update.fetch_forex(M, fake)[0] == 0                          # a second "Fetch now" adds nothing


def test_index_proposal_follows_the_formula_and_leaves_examples_alone():
    rates.save_settings({"approver_name": "T"})
    rates.create({"category": "material", "item": "TESTALLOY", "country": "IN", "value": 200, "unit": "INR/kg", "currency": "INR", "month": "2023-06"}, approve=True)
    rate_update.fetch_index(fake)
    rate_update.propose_by_index(M)
    d = [x for x in drafts("material") if x["draft"]["country"] == "IN" and x["draft"]["item"] == "TESTALLOY"]
    assert len(d) == 1 and d[0]["draft"]["value"] == pytest.approx(200 * 200 / 180, rel=2e-3)       # 2025 index ÷ 2023 index (2026 is empty)
    assert d[0]["draft"]["origin"] == "monthly update" and "×" in d[0]["draft"]["comment"]
    assert not [x for x in drafts("material") if x["draft"]["item"] != "TESTALLOY"]                        # EXAMPLE rates get no proposals


def test_a_failing_source_is_logged_and_never_stops_the_run():
    res = rate_update.run_update(M, user="tester", http=fake)
    assert [r["status"] for r in res["runs"]] == ["ok", "ok", "ok"]
    index = next(r for r in res["runs"] if "World Bank" in r["source"])
    assert "DE: connection refused" in index["message"] and "TW" in index["message"]                 # DE failed, TW has no series
    bad = rate_update.run_update(M, user="tester", http=lambda u: (_ for _ in ()).throw(OSError("offline")))
    assert [r["status"] for r in bad["runs"]][0] == "failed" and "last approved values stay in use" in bad["runs"][0]["message"]
    assert rates.lookup("forex", "USD", "", M)["value"] == 83.5                                       # costing is untouched


def test_update_rules_are_data_and_api():
    db = mould_db.tables()
    assert any(r["category"] == "material" and r["enabled"] for r in db["update_rules"])
    r = client.get("/api/rates/updates")
    assert r.status_code == 200 and isinstance(r.json()["runs"], list)
