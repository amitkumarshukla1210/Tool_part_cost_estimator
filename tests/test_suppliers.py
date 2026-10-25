import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def sup(**kw):
    r = client.post("/api/suppliers", json={"name": "Acme Plastics", "country": "in", "commodities": "injection moulding"} | kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_supplier_codes_come_from_the_pattern_and_are_unique():
    a, b = sup(), sup(name="Beta Tools")
    assert (a["code"], b["code"]) == ("SUP-0001", "SUP-0002")
    assert a["status"] == "approved" and a["country"] == "IN"                    # first status of supplier_statuses
    assert sup(code="cn-007", name="Gamma")["code"] == "CN-007"
    r = client.post("/api/suppliers", json={"code": "SUP-0001", "name": "dup"})
    assert r.status_code == 400 and "already exists" in r.text
    assert client.post("/api/suppliers", json={"name": "x", "status": "maybe"}).status_code == 400
    assert client.post("/api/suppliers", json={"name": "x", "quality_score": 120}).status_code == 400
    upd = client.put(f"/api/suppliers/{a['id']}", json={"quality_score": 80, "delivery_score": 90, "status": "trial"}).json()
    assert upd["rating"] == 85 and upd["status"] == "trial" and upd["history"][0]["action"] == "updated"
    found = client.get("/api/suppliers?q=beta").json()["suppliers"]
    assert [s["code"] for s in found] == ["SUP-0002"]
    assert client.get("/api/suppliers/export.xlsx").status_code == 200


def test_part_quotes_against_should_cost_and_main_supplier():
    pid = add_part(project("SQ"))
    a, b = sup(), sup(name="Beta", currency="USD")
    r = client.post(f"/api/parts/{pid}/suppliers", json={"supplier_id": a["id"], "piece_price": 12.5, "tool_price": 250000}).json()
    line = r["suppliers"][0]
    assert line["role"] == "main" and line["piece_price_inr"] == 12.5 and line["currency"] == "INR"
    r = client.post(f"/api/parts/{pid}/suppliers", json={"supplier_code": b["code"], "piece_price": 0.2, "role": "main"}).json()
    roles = {l["code"]: l["role"] for l in r["suppliers"]}
    assert roles == {a["code"]: "alternate", b["code"]: "main"}                   # one main at a time
    usd = next(l for l in r["suppliers"] if l["code"] == b["code"])
    assert usd["piece_price_inr"] == pytest.approx(0.2 * usd["forex"]) and usd["forex"] > 1
    assert client.post(f"/api/parts/{pid}/suppliers", json={"supplier_id": a["id"]}).status_code == 400   # already linked
    r = client.delete(f"/api/suppliers/{a['id']}")
    assert r.status_code == 400 and "inactive" in r.json()["detail"]                # in use: not deleted
    lid = next(l["id"] for l in client.get(f"/api/parts/{pid}/suppliers").json()["suppliers"] if l["code"] == a["code"])
    assert client.delete(f"/api/parts/{pid}/suppliers/{lid}").status_code == 200
    assert client.delete(f"/api/suppliers/{a['id']}").status_code == 200
    hist = client.get(f"/api/parts/{pid}").json()["history"]
    assert any(h["action"] == "supplier_added" for h in hist) and any(h["action"] == "supplier_removed" for h in hist)


def test_capex_line_takes_the_supplier_from_the_master():
    p = project("SC")
    s = sup(name="Delta Moulds", country="CN")
    r = client.post(f"/api/projects/{p['id']}/capex", json={"kind": "other", "description": "Mould", "amount_inr": 100000,
                                                            "supplier_id": s["id"]})
    assert r.status_code == 200, r.text
    plan = client.get(f"/api/projects/{p['id']}/leader").json()["plan"]
    item = plan["items"][0]
    assert item["supplier"] == "Delta Moulds" and item["country"] == "CN" and item["supplier_id"] == s["id"]
    client.put(f"/api/suppliers/{s['id']}", json={"name": "Delta Moulds Ltd"})
    assert client.get(f"/api/projects/{p['id']}/leader").json()["plan"]["by_supplier"][0][0] == "Delta Moulds Ltd"
