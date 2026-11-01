"""Stage 44: design skills - drawing-data corrections made on enough parts become the starting value of the next tool designs."""

from fastapi.testclient import TestClient

from backend.app import design_skills, mould_db
from backend.app.main import app
from tests.test_drawing_data import sign_review
from tests.test_rm_cost import add_part, project

client = TestClient(app)
HT = "Nitride 0.1 mm"


def cover(code):
    return add_part(project(code), "plastic_cover.step", "ABS", "injection_moulding", f"{code}-1")


def insert(pid, name="Cavity insert"):
    d = client.get(f"/api/parts/{pid}/drawing-data").json()
    t = d["tools"][0]
    return t, next(i for i in t["items"] if i["name"] == name)


def correct(pid, value=HT, field="heat_treatment"):
    t, i = insert(pid)
    r = client.put(f"/api/parts/{pid}/drawing-data", json={"items": [{"tool": t["key"], "item": i["item"], "fields": {field: value}, "notes": []}]})
    assert r.status_code == 200 and r.json()["changed"], r.text


def test_rule_is_master_data_and_seed_adds_only_missing_rows():
    assert not design_skills.seed()
    assert design_skills.min_parts("plastic") == 2
    assert mould_db.design_rules("plastic")["skill_min_parts"]["is_example"]


def test_correction_on_enough_parts_becomes_a_skill_and_typed_value_wins():
    a, b, c = cover("SK1"), cover("SK2"), cover("SK3")
    correct(a)
    _, i = insert(c)
    assert i["effective"]["heat_treatment"] != HT and not i["from_skill"]          # one part is not yet a skill
    s = client.get("/api/design-skills", params={"part_type": "plastic"}).json()["skills"]
    assert s[0]["parts"] == 1 and not s[0]["qualifies"] and s[0]["component"] == "cavity insert"
    correct(b)
    _, i = insert(c)
    assert i["effective"]["heat_treatment"] == HT and i["from_skill"] == ["heat_treatment"] and i["defaults"]["heat_treatment"] == HT
    assert i["base_defaults"]["heat_treatment"] != HT
    _, other = insert(c, "Core insert")
    assert other["effective"]["heat_treatment"] != HT                               # only the same part name learns it
    correct(c, "Harden 52 HRC")
    _, i = insert(c)
    assert i["effective"]["heat_treatment"] == "Harden 52 HRC" and not i["from_skill"]


def test_skill_can_be_switched_off_and_on_and_needs_its_rule():
    a, b, c = cover("SK4"), cover("SK5"), cover("SK6")
    correct(a, 0.8, "finish_ra")
    correct(b, 0.8, "finish_ra")
    assert insert(c)[1]["effective"]["finish_ra"] == 0.8
    key = {"part_type": "plastic", "component": "Cavity insert", "field": "finish_ra", "value": "0.8"}
    assert client.post("/api/design-skills/status", json=key | {"active": False}).status_code == 200
    assert insert(c)[1]["effective"]["finish_ra"] != 0.8
    assert client.post("/api/design-skills/status", json=key | {"active": True}).status_code == 200
    assert insert(c)[1]["effective"]["finish_ra"] == 0.8
    assert client.post("/api/design-skills/status", json=key | {"value": "9.9", "active": False}).status_code == 400
    d = mould_db.tables()
    d["design_rules"] = [r for r in d["design_rules"] if r["parameter"] != "skill_min_parts"]
    mould_db.write(d)
    assert insert(c)[1]["effective"]["finish_ra"] != 0.8                              # no rule in master data: nothing applied


def test_released_design_keeps_the_skill_values_it_showed():
    from backend.app import register_setup
    a, b, c = cover("SK7"), cover("SK8"), cover("SK9")
    correct(a)
    correct(b)
    order = [x["code"] for x in register_setup.statuses()]
    for _ in range(10):
        loop = client.get(f"/api/parts/{c}/design-loop").json()
        if loop["status"] == order[-1]:
            break
        if order[-1] in loop["next"]:
            sign_review(c)
        nxt = max((x for x in loop["next"] if x != "corrections_required"), key=order.index)
        assert client.put(f"/api/parts/{c}", json={"status": nxt, "status_comment": "ok"}).status_code == 200
    key = {"part_type": "plastic", "component": "Cavity insert", "field": "heat_treatment", "value": HT, "active": False}
    assert client.post("/api/design-skills/status", json=key).status_code == 200      # the team switches it off later
    d = client.get(f"/api/parts/{c}/drawing-data").json()
    i = next(x for x in d["tools"][0]["items"] if x["name"] == "Cavity insert")
    assert d["release"]["released"] and i["effective"]["heat_treatment"] == HT and i["changed"]
    assert any("Design skill values kept at release" in h["text"] for h in d["history"])
