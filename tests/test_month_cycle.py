"""Month by month costing: each analysis month uses that month's approved rates and stores its own cost version.

The clock is frozen by tests/conftest.py (31 October 2026, after every shipped example rate); a test moves it with clock.set(...).
Stored versions (the app's "Rev00, Rev01 ..." are version 1, 2 ...) are never overwritten.
"""
from backend.app import price_master, rates
from tests.test_rm_cost import add_part, approver, client, detail, new_rate, project


def grid_row(item="ABS", group="part_material"):
    g = client.get("/api/price-master/grid", params={"group": group, "country": "IN"}).json()
    return g, next(r for r in g["rows"] if r["item"] == item)


def test_frozen_clock_is_october_2026(clock):
    assert rates.current_month() == "2026-10"
    clock.set("2026-11-05")
    assert rates.current_month() == "2026-11"


def test_1_october_uses_october_rates_and_stores_the_first_version():
    approver()
    pid = add_part(project())
    d = detail(pid)
    assert d["rm"]["latest"]["version"] == 1                            # first version (Rev00)
    assert {x["category"]: x for x in d["rm"]["latest"]["rates_used"]}["material"]["month"] == "2026-10"
    assert d["rm"]["outdated"] == ""


def test_2_november_with_a_new_price_gives_the_next_version_and_keeps_october(clock):
    approver()
    pid = add_part(project())
    v1 = detail(pid)["rm"]["latest"]
    clock.set("2026-11-05")
    new_rate("ABS", 240, month="2026-11")
    d = detail(pid)
    assert "Newer approved rates" in d["rm"]["outdated"]                # the software tells you November has a new price
    assert d["rm"]["latest"]["version"] == 1                            # nothing changes until you recalculate
    assert client.post(f"/api/parts/{pid}/rm-cost", json={}).json()["version"] == 2
    versions = client.get(f"/api/parts/{pid}/rm-cost").json()
    assert [x["version"] for x in versions] == [2, 1]
    assert versions[1]["net_rm_cost"] == v1["net_rm_cost"]              # October stays frozen
    used = {x["category"]: x for x in versions[0]["rates_used"]}["material"]
    assert used["value"] == 240 and used["month"] == "2026-11"
    new_rate("ABS", 260, month="2026-12")                               # and so on: Rev02 ...
    clock.set("2026-12-02")
    assert client.post(f"/api/parts/{pid}/rm-cost", json={}).json()["version"] == 3


def test_3_november_without_a_new_price_stays_on_the_october_version(clock):
    approver()
    pid = add_part(project())
    clock.set("2026-11-05")
    d = detail(pid)
    assert d["rm"]["latest"]["version"] == 1 and d["rm"]["outdated"] == ""
    assert client.post(f"/api/parts/{pid}/rm-cost", json={}).json()["stored"] is False   # same result: no new version


def test_4_next_month_starts_from_last_month_price_and_can_be_edited(clock):
    approver()
    new_rate("ABS", 200, month="2026-10")
    g, r = grid_row()
    assert g["current_month"] == "2026-10" and g["months"][-1] == "2026-11"             # next month is shown, to enter prices
    nov = r["cells"]["2026-11"]
    assert nov["value"] == 200 and not nov["starts"]                                     # carried over from October
    pid = add_part(project())
    clock.set("2026-11-05")
    assert detail(pid)["rm"]["outdated"] == ""                                           # carried price = nothing new
    new_rate("ABS", 215, month="2026-11")                                                # edit November
    _, r = grid_row()
    assert r["cells"]["2026-11"]["value"] == 215 and r["cells"]["2026-11"]["starts"]
    assert r["cells"]["2026-10"]["value"] == 200                                         # October is not rewritten
    assert price_master.grid("part_material", "IN")["months"][-1] == "2026-12"


def costed_all(pid):
    for kind in ("rm-cost", "tool-cost", "piece-cost"):
        assert client.post(f"/api/parts/{pid}/{kind}", json={}).status_code == 200, kind


def versions(pid, kind):
    return [x["version"] for x in client.get(f"/api/parts/{pid}/{kind}").json()["versions"] if isinstance(x, dict)] \
        if kind == "piece-cost" else [x["version"] for x in client.get(f"/api/parts/{pid}/{kind}").json()]


def test_tool_and_part_cost_follow_the_same_month_rules(clock):
    approver()
    pid = add_part(project())
    costed_all(pid)                                                     # October: Rev00 of RM, tool and part cost
    clock.set("2026-11-05")                                             # November, no price updated
    for kind in ("rm-cost", "tool-cost", "piece-cost"):
        assert client.post(f"/api/parts/{pid}/{kind}", json={}).json()["stored"] is False, kind
    new_rate("ABS", 240, month="2026-11")                               # November price arrives
    assert "Newer approved rates" in detail(pid)["rm"]["outdated"]
    costed_all(pid)
    assert versions(pid, "rm-cost") == [2, 1] and versions(pid, "piece-cost") == [2, 1]
