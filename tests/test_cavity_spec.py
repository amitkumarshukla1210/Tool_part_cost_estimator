"""Stage 46: cavities asked before the mould design (recommended by Stage C, confirmed or typed)."""

from fastapi.testclient import TestClient

from sqlalchemy import func, select

from backend.app import projects_db as db
from backend.app import register
from backend.app.main import app
from tests.test_drawing_data import bracket
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def cover(code):
    return add_part(project(code), "plastic_cover.step", "ABS", "injection_moulding", f"{code}-1")


def test_cavities_are_recommended_and_not_asked_yet():
    c = client.get(f"/api/parts/{cover('CV1')}/cavities").json()
    assert not c["asked"] and c["typed"] is None and c["recommended"] >= 1 and "Stage C" in c["stage_c_note"]
    assert c["in_use"] == c["recommended"] and "recommended" in c["source"]
    assert client.get(f"/api/parts/{bracket('CV2')}/cavities").status_code == 400           # a sheet-metal die: nothing asked


def test_typed_cavities_drive_the_tool_cost_and_the_design():
    pid = cover("CV3")
    r = client.put(f"/api/parts/{pid}/cavities", json={"cavities": 4})
    assert r.status_code == 200 and r.json()["asked"] and r.json()["typed"] == 4 and r.json()["answer"]["typed"] == 4
    assert client.get(f"/api/parts/{pid}").json()["tool_inputs"]["cavities"] == 4
    assert register.tool_trace(pid)["key"]["cavities"] == 4
    assert "4 cavities" in client.get(f"/api/parts/{pid}/tool-design").json()["tools"][0]["name"]
    for bad in (0, 300, "2.5", "abc"):
        assert client.put(f"/api/parts/{pid}/cavities", json={"cavities": bad}).status_code == 400
    r = client.put(f"/api/parts/{pid}/cavities", json={"cavities": None}).json()        # back to the recommendation
    assert r["typed"] is None and r["asked"] and "cavities" not in (client.get(f"/api/parts/{pid}").json()["tool_inputs"] or {})
    with db.engine().connect() as conn:
        n = conn.execute(select(func.count()).select_from(db.history).where((db.history.c.entity_id == pid) & (db.history.c.action == "cavities_set"))).scalar()
    assert n == 2
