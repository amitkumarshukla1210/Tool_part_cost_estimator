"""Stage 66: output packs - every output of a part in one ZIP, made in the background, saved with revisions, auto next revision."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.app import output_pack, projects_db as db
from backend.app.main import app
from tests.test_fin_part import fin_part_id
from tests.test_rm_cost import add_part, project
from tests.test_server_mode import server  # noqa: F401  (fixture)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    output_pack._PENDING.clear()
    output_pack._STOP.clear()
    yield
    output_pack._PENDING.clear()


@pytest.fixture
def no_jobs(monkeypatch):
    """Packs without the slow simulation / FEA jobs (they are tested on their own)."""
    cat = {k: [x for x in v if x["kind"] != "job"] for k, v in output_pack.CATALOGUE.items()}
    monkeypatch.setattr(output_pack, "CATALOGUE", cat)


def _part(code="OP"):
    pid = add_part(project(code), code=f"{code}-1")
    client.put(f"/api/parts/{pid}", json={"annual_volume": 100000, "programme_life_years": 5})
    return pid


def _make(pid, force=True):
    p = client.post(f"/api/parts/{pid}/output-packs", json={"force": force})
    assert p.status_code == 200, p.text
    return output_pack.wait(pid, p.json()["id"], 1500)


def test_columns_follow_the_tool_type():
    keys = lambda pt: [c["key"] for c in output_pack.columns(pt)]
    assert "strip" in keys("fin") and "strip" in keys("sheet_metal") and "strip" not in keys("plastic")
    assert keys("plastic")[:3] == ["design", "2d", "3d"] and "fea" in keys("die_casting") and "sim" not in keys("machined")
    assert {"tool_cost", "rm", "part_cost"} <= set(keys("fin"))


def test_plastic_pack_with_simulation(monkeypatch):
    cat = dict(output_pack.CATALOGUE)
    cat["mould"] = [x for x in cat["mould"] if not (x["kind"] == "job" and x.get("path") == "fea")]          # FEA has its own tests (minutes)
    monkeypatch.setattr(output_pack, "CATALOGUE", cat)
    pid = _part()
    p = _make(pid)
    assert p["status"] == "done" and p["progress"] == 100 and p["rev"] == "Rev.00" and p["zip_name"] == "OP-1_Rev.00_output_pack.zip"
    st = {x["label"]: x for x in p["items"]}
    assert st["Flow simulation"]["status"] == "done" and st["Simulation & analysis video"]["status"] == "done"
    assert st["Tool design release pack (ZIP)"]["status"] == "done" and st["3D tool (STEP)"]["filename"].endswith(".step")
    assert st["Saved simulation runs (PDF, video)"]["files"]
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/parts/{pid}/output-packs/{p['id']}/pack.zip").content))
    names = z.namelist()
    assert "OP-1_Rev.00_output_pack/00 Index.txt" in names
    assert any(n.startswith("OP-1_Rev.00_output_pack/01 Tool design pack/") for n in names)
    assert any("/02 2D drawings (PDF, DXF)/" in n for n in names) and any(n.endswith(".mp4") for n in names)
    assert any("Tool cost - all countries" in n for n in names) and len(names) >= 25
    n = next(i for i, x in enumerate(p["items"]) if x["label"] == "Part cost (PDF)")
    r = client.get(f"/api/parts/{pid}/output-packs/{p['id']}/items/{n}")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    o = client.get(f"/api/parts/{pid}/output-packs").json()
    assert o["auto"] and not o["out_of_date"] and o["packs"][0]["groups"]["sim"]
    same = client.post(f"/api/parts/{pid}/output-packs", json={}).json()     # nothing changed: the same revision
    assert same["id"] == p["id"]


def test_a_change_makes_the_next_revision_by_itself(no_jobs, monkeypatch):
    monkeypatch.setattr(output_pack, "AUTO_DELAY_S", 0)
    pid = _part("AU")
    r0 = _make(pid)
    assert output_pack.watch_once() == [] and output_pack.watch_once() == []       # no change: no new pack (no loop)
    client.put(f"/api/parts/{pid}", json={"annual_volume": 250000})
    assert client.get(f"/api/parts/{pid}/output-packs").json()["out_of_date"]
    assert output_pack.watch_once() == []                    # first sight of the change: the delay starts
    assert output_pack.watch_once() == [pid]                 # unchanged for the delay: the next revision starts
    r1 = output_pack.wait(pid, output_pack.packs(pid)[0]["id"], 1500)
    assert r1["rev"] == "Rev.01" and r1["status"] == "done" and r1["auto"] and "part data" in r1["changed"]
    assert output_pack.watch_once() == [] and output_pack.watch_once() == []
    revs = [x["rev"] for x in client.get(f"/api/parts/{pid}/output-packs").json()["packs"]]
    assert revs == ["Rev.01", "Rev.00"]
    old = client.get(f"/api/parts/{pid}/output-packs/{r0['id']}/pack.zip")
    assert old.status_code == 200 and "AU-1_Rev.00_output_pack.zip" in old.headers["content-disposition"]
    client.put(f"/api/parts/{pid}/output-packs/auto", json={"enabled": False})
    client.put(f"/api/parts/{pid}", json={"annual_volume": 300000})
    assert output_pack.watch_once() == [] and output_pack.watch_once() == []         # auto off


def test_stop_and_start_again_after_a_restart(no_jobs):
    pid = _part("ST")
    p = client.post(f"/api/parts/{pid}/output-packs", json={}).json()
    client.post(f"/api/parts/{pid}/output-packs/{p['id']}/stop")
    s = output_pack.wait(pid, p["id"], 600)
    assert s["status"] == "stopped" and not s["zip_file_id"]
    with db.engine().begin() as conn:                         # the app stopped while a pack was running
        conn.execute(db.output_packs.update().where(db.output_packs.c.id == p["id"]).values(status="running"))
    assert output_pack.resume() >= 1
    again = output_pack.wait(pid, p["id"], 1500)
    assert again["status"] == "done" and again["zip_file_id"]


def test_fin_pack_and_the_page(no_jobs):
    pid, _ = fin_part_id("FIN-9")
    p = _make(pid)
    labels = {x["label"]: x for x in p["items"]}
    assert labels["Strip layout (PDF)"]["status"] == "done" and labels["3D fin die (STEP)"]["status"] == "done"
    assert labels["Fin die BOM (Excel)"]["status"] == "done"
    lst = client.get("/api/output-packs?part_type=fin").json()
    row = next(x for x in lst["parts"] if x["id"] == pid)
    assert row["packs"][0]["rev"] == "Rev.00" and [c["key"] for c in lst["columns"]][0] == "design"
    assert client.get("/output-packs").status_code == 200
    assert "output-pack.js" in client.get("/parts").text


def test_a_download_that_does_not_apply_is_listed(no_jobs, monkeypatch):
    cat = dict(output_pack.CATALOGUE)
    cat["mould"] = cat["mould"] + [output_pack._get("strip", "sheet-layout/strip.dxf", "Strip layout (DXF)")]
    monkeypatch.setattr(output_pack, "CATALOGUE", cat)
    pid = _part("NA")
    p = _make(pid)
    it = next(x for x in p["items"] if x["label"] == "Strip layout (DXF)")
    assert it["status"] == "n/a" and it["reason"] and p["status"] == "done"


def test_with_logins_the_pack_runs_as_its_user_and_follows_tool_groups(server, no_jobs):   # noqa: F811
    from tests.test_scope import _part as scope_part, _user
    from tests.test_server_mode import login
    login(server)
    pl = server.post("/api/projects", json={"code": "PK", "name": "Packs"}).json()
    pid = scope_part(server, pl["id"], "plastic_cover.step", "ABS", "injection_moulding", "PK-1").json()["part_ids"][0]
    server.post("/api/auth/logout")
    _user(server, "pam", "engineer", ["plastic"])
    _user(server, "sid", "engineer", ["sheet_metal"])
    login(server, "pam")
    p = server.post(f"/api/parts/{pid}/output-packs", json={})
    assert p.status_code == 200, p.text
    done = output_pack.wait(pid, p.json()["id"], 1500)
    assert done["status"] == "done" and done["created_by"] == "pam"
    assert all(x["status"] in ("done", "n/a") for x in done["items"])
    assert sum(x["status"] == "done" for x in done["items"]) >= 20               # made logged in as pam (no 401)
    with db.engine().connect() as conn:                                           # the service login was removed
        assert conn.execute(db.sessions.select().where(db.sessions.c.user_id == done["user_id"])).fetchall().__len__() == 1
    server.post("/api/auth/logout")
    login(server, "sid")
    assert server.get(f"/api/parts/{pid}/output-packs").status_code == 403        # not sid's tool group
    assert all(x["id"] != pid for x in server.get("/api/output-packs").json()["parts"])


def test_quick_zip_first_and_unchanged_design_reuses_simulation_and_fea(monkeypatch):
    """Stage 66b: the ZIP of the files is ready before simulation / FEA run; a change that leaves the tool as it was (volume)
    reuses their results; a change of the tool (material) runs them again."""
    calls, seen = [], []

    def fake_job(client, base, it, progress, stopped):
        pid, pack = int(base.split("/")[3]), output_pack.packs(int(base.split("/")[3]))[0]
        seen.append((pack["zip_stage"], bool(pack["zip_file_id"])))           # the first ZIP exists while jobs run
        calls.append(it["path"])
        it |= {"status": "done", "run_id": None}
    monkeypatch.setattr(output_pack, "_do_job", fake_job)
    cat = {k: [x for x in v if x["kind"] != "fea" and x["kind"] != "runs"] for k, v in output_pack.CATALOGUE.items()}
    monkeypatch.setattr(output_pack, "CATALOGUE", cat)
    pid = _part("RU")
    r0 = _make(pid)
    assert r0["status"] == "done" and r0["zip_stage"] == "full" and len(calls) == 3
    assert seen and all(s == ("quick", True) for s in seen)
    client.put(f"/api/parts/{pid}", json={"annual_volume": 150000})
    r1 = _make(pid)
    jobs = [x for x in r1["items"] if x["kind"] == "job"]
    assert len(calls) == 3 and all(x["reused"] == "Rev.00" for x in jobs) and "Rev.00 used" in r1["step"]
    client.put(f"/api/parts/{pid}", json={"material": "PP (polypropylene)"})
    r2 = _make(pid)
    assert len(calls) == 6 and not any(x.get("reused") for x in r2["items"] if x["kind"] == "job")
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/parts/{pid}/output-packs/{r2['id']}/pack.zip").content))
    infos = {i.filename.rsplit("/", 1)[-1]: i.compress_type for i in z.infolist()}
    assert any(n.endswith(".zip") and t == zipfile.ZIP_STORED for n, t in infos.items())          # not compressed twice
    assert any(n.endswith(".pdf") and t == zipfile.ZIP_DEFLATED for n, t in infos.items())
