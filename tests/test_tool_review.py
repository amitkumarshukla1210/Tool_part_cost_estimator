"""Stage 43: toolmaker review of the tool design - checklist from master data, sign-offs kept as history, gate on freezing the design."""

from fastapi.testclient import TestClient

from backend.app import mould_db, register_setup, tool_review
from backend.app.main import app
from tests.test_drawing_data import bracket
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def cover(code):
    return add_part(project(code), "plastic_cover.step", "ABS", "injection_moulding", f"{code}-1")


def rows(r, tool=0):
    return {x["item"]: x for x in r["tools"][tool]["rows"]}


def test_checklist_is_master_data_and_seed_adds_only_missing_rows():
    assert not tool_review.seed()                                        # shipped already, nothing added twice
    d = mould_db.tables()["review_checklist"]
    assert {r["part_type"] for r in d} >= {"plastic", "sheet_metal", "die_casting"} and all(r["is_example"] for r in d)
    bad = {"review_checklist": [{"part_type": "plastic", "step": 1, "item": "x", "rule": "nonsense_fact > 0", "blocking": True}]}
    try:
        tool_review.validate(bad)
        assert False, "an unknown fact must be refused"
    except mould_db.MouldDbError as exc:
        assert "nonsense_fact" in str(exc) and "no_material" in str(exc)


def test_review_shows_automatic_and_manual_rows_per_tool():
    pid = cover("TR1")
    r = client.get(f"/api/parts/{pid}/tool-review").json()
    x = rows(r)
    assert x["Every made part has a material"]["auto"] and x["Every made part has a material"]["status"] == "ok"
    assert x["A flow simulation of the part is saved"]["status"] == "issue" and "run one" in x["A flow simulation of the part is saved"]["message"]
    manual = [v for v in x.values() if not v["auto"]]
    assert manual and all(v["status"] == "open" for v in manual)
    assert r["blocking_open"] == sum(v["blocks_release"] for v in x.values()) and not r["can_release"]
    assert r["tools"][0]["facts"]["made_parts"] > 0
    sheet = client.get(f"/api/parts/{bracket('TR2')}/tool-review").json()
    assert any("die clearances" in i for i in rows(sheet))


def test_signoff_needs_a_comment_for_issue_and_is_kept_as_history():
    pid = cover("TR3")
    t = client.get(f"/api/parts/{pid}/tool-review").json()["tools"][0]
    item = next(x["item"] for x in t["rows"] if not x["auto"])
    post = lambda **k: client.post(f"/api/parts/{pid}/tool-review", json={"tool": t["key"], "item": item} | k)
    assert post(status="issue").status_code == 400 and post(status="maybe").status_code == 400
    assert client.post(f"/api/parts/{pid}/tool-review", json={"tool": "nope", "item": item, "status": "ok"}).status_code == 400
    assert client.post(f"/api/parts/{pid}/tool-review", json={"tool": t["key"], "item": "not on the list", "status": "ok"}).status_code == 400
    assert post(status="issue", comment="Cooling too far from the core").status_code == 200
    r = post(status="ok", comment="Fixed")
    assert r.status_code == 200
    got = rows(r.json())[item]
    assert got["status"] == "ok" and got["comment"] == "Fixed"
    assert [h["status"] for h in r.json()["history"] if h["item"] == item] == ["ok", "issue"]       # newest first, nothing overwritten


def test_design_cannot_be_frozen_while_a_blocking_point_is_open():
    pid = cover("TR4")
    final = register_setup.statuses()[-1]["code"]
    res = client.put(f"/api/parts/{pid}", json={"status": final, "status_comment": "go"})
    assert res.status_code == 400 and "toolmaker review" in res.json()["detail"]
    t = client.get(f"/api/parts/{pid}/tool-review").json()["tools"][0]
    for x in t["rows"]:
        if x["blocks_release"]:
            st = "ok" if not x["auto"] else "waived"
            assert client.post(f"/api/parts/{pid}/tool-review", json={"tool": t["key"], "item": x["item"], "status": st, "comment": "checked"}).status_code == 200
    assert client.get(f"/api/parts/{pid}/tool-review").json()["can_release"]
    ok = client.put(f"/api/parts/{pid}", json={"status": final, "status_comment": "go"})
    assert ok.status_code == 200 or "can only move to" in ok.json()["detail"]        # review no longer stops it; the flow rules may still decide
    assert "toolmaker review" not in (ok.json().get("detail", "") if ok.status_code != 200 else "")
