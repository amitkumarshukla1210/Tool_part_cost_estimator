"""One click: 'Recalculate part costs' recalculates RM cost and tool cost first, then the part cost."""

from sqlalchemy import select

from backend.app import price_master, rates
from backend.app import projects_db as db
from tests.test_rm_cost import add_part, approver, client, project


def test_a_new_price_reaches_the_part_cost_in_one_click():
    p = project()
    pid = add_part(p, material="ABS", code="OC-1")
    assert client.post(f"/api/parts/{pid}/tool-cost", json={}).status_code == 200
    first = client.post(f"/api/parts/{pid}/piece-cost", json={}).json()
    assert first["stored"]
    approver()
    month = rates.current_month()
    old = rates.lookup("material", "ABS", "IN", month)["value"]
    price_master.set_price("part_material", "ABS", "IN", month, old * 1.5, approve=True)      # +50 % RM price
    r = client.post(f"/api/projects/{p['id']}/piece-cost/recalculate").json()
    assert r["rm_new_versions"] == 1 and r["new_versions"] == 1 and r["unchanged"] == 0
    with db.engine().connect() as conn:
        v = [r for r in conn.execute(select(db.piece_costs.c.version, db.piece_costs.c.piece_cost_inr)
                                     .where(db.piece_costs.c.part_id == pid).order_by(db.piece_costs.c.version))]
    assert [x[0] for x in v] == [1, 2] and v[1][1] > v[0][1]                                    # the part cost went up
    again = client.post(f"/api/projects/{p['id']}/piece-cost/recalculate").json()              # nothing new: nothing stored
    assert again["rm_new_versions"] == 0 and again["tool_new_versions"] == 0 and again["new_versions"] == 0
