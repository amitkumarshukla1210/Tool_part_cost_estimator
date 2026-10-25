from fastapi.testclient import TestClient

from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def test_delete_project_needs_its_code_and_removes_everything(tmp_path):
    p = project("DEL")
    pid = add_part(p)
    client.post(f"/api/projects/{p['id']}/variants", json={"code": "STD", "name": "Standard"})
    r = client.delete(f"/api/projects/{p['id']}?confirm=WRONG")
    assert r.status_code == 400 and "type its code DEL" in r.json()["detail"]
    r = client.delete(f"/api/projects/{p['id']}?confirm=del")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["deleted"] == "DEL" and out["parts"] == 1 and out["variants"] == 1
    assert (tmp_path / "backups" / out["backup"]).exists()                # backup made first
    assert all(x["code"] != "DEL" for x in client.get("/api/projects").json())
    assert client.get(f"/api/parts/{pid}").status_code == 400
    assert client.post("/api/projects", json={"code": "DEL", "name": "again"}).status_code == 200   # code free again


def test_delete_refused_when_a_part_is_used_by_another_project():
    a, b = project("DA"), project("DB")
    insert = add_part(a, code="INS-1")
    body = add_part(b, code="BODY-1")
    assert client.post(f"/api/parts/{body}/inserts", json={"insert_part_code": "INS-1", "quantity": 2}).status_code == 200
    r = client.delete(f"/api/projects/{a['id']}?confirm=DA")
    assert r.status_code == 400 and "used elsewhere" in r.json()["detail"] and "BODY-1" in r.json()["detail"]
