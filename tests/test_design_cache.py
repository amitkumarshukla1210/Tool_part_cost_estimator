"""The 3D tool design is made once per state of the part: every block of the panel and every download reuse it."""

from fastapi.testclient import TestClient

from backend.app import register
from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def test_design_is_made_once_and_again_after_a_change(monkeypatch):
    pid = add_part(project("DC1"), "plastic_cover.step", "ABS", "injection_moulding", "DC1-1")
    made = []
    build = register._tool_designs_build
    monkeypatch.setattr(register, "_tool_designs_build", lambda p, k=None: made.append((p, k)) or build(p, k))
    register.clear_design_cache()
    for url in ("tool-design", "production-data", "tool-review", "drawing-data", "fea", "machine-check"):
        assert client.get(f"/api/parts/{pid}/{url}").status_code == 200, url
    assert client.get(f"/api/parts/{pid}/tool-design.stl").status_code == 200
    assert len(made) == 1                                                       # 7 calls, one 3D design
    _, _, des = register.tool_designs(pid)
    des[0][1]["notes"].append("changed by a caller")
    assert "changed by a caller" not in register.tool_designs(pid)[2][0][1]["notes"]       # callers get their own copy
    d = client.get(f"/api/parts/{pid}/drawing-data").json()
    t = d["tools"][0]
    r = client.put(f"/api/parts/{pid}/drawing-data", json={"items": [{"tool": t["key"], "item": t["items"][0]["item"],
                                                                        "fields": {"surface_treatment": "Nitride"}, "notes": []}]})
    assert r.status_code == 200 and len(made) == 1
    d2 = client.get(f"/api/parts/{pid}/drawing-data").json()
    assert len(made) == 2 and d2["tools"][0]["items"][0]["effective"]["surface_treatment"] == "Nitride"      # the change made a new design
