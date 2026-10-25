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


def test_remove_part_from_project_bom_and_delete_part(tmp_path):
    p = project("PDL")
    v = client.post(f"/api/projects/{p['id']}/variants", json={"code": "STD", "name": "Standard"}).json()
    from pathlib import Path
    samples = Path(__file__).resolve().parents[1] / "samples"
    with open(samples / "plastic_cover.step", "rb") as fh:
        m = client.post("/api/import/step", files={"file": ("plastic_cover.step", fh)}).json()
    r = client.post(f"/api/import/{m['token']}/commit", json={"project_id": p["id"], "variant_id": v["variants"][0]["id"],
                                                              "items": {m["root"]: {"material": "ABS", "process": "injection_moulding", "part_code": "PDL-1"}}})
    pid = r.json()["part_ids"][0]
    bom = client.get(f"/api/variants/{v['variants'][0]['id']}/bom").json()
    assert any(b["child_part_id"] == pid for b in bom)
    r = client.post(f"/api/parts/{pid}/remove-from-bom")
    assert r.status_code == 200 and "stays in the register" in r.json()["message"]
    assert not any(b["child_part_id"] == pid for b in client.get(f"/api/variants/{v['variants'][0]['id']}/bom").json())
    assert client.post(f"/api/parts/{pid}/remove-from-bom").status_code == 400            # not in any BOM now
    assert client.get(f"/api/parts/{pid}").status_code == 200                              # still in the register
    r = client.delete(f"/api/parts/{pid}?confirm=WRONG")
    assert r.status_code == 400 and "PDL-1" in r.json()["detail"]
    r = client.delete(f"/api/parts/{pid}?confirm=pdl-1")
    assert r.status_code == 200 and (tmp_path / "backups" / r.json()["backup"]).exists()
    assert client.get(f"/api/parts/{pid}").status_code == 400
    assert client.get("/api/parts", params={"project_id": p["id"]}).json()["total"] == 0


def test_delete_part_refused_while_moulded_into_another_part():
    p = project("PDM")
    insert = add_part(p, code="INS-9")
    body = add_part(p, code="BODY-9")
    client.post(f"/api/parts/{body}/inserts", json={"insert_part_code": "INS-9", "quantity": 1})
    r = client.delete(f"/api/parts/{insert}?confirm=INS-9")
    assert r.status_code == 400 and "BODY-9" in r.json()["detail"]
    assert client.delete(f"/api/parts/{body}?confirm=BODY-9").status_code == 200           # the body can go; the insert stays
    assert client.get(f"/api/parts/{insert}").status_code == 200
