"""Stage 30: head of department, data access by tool group (built on the logins and roles of stages 17 and 22)."""
from backend.app import auth
from tests.test_server_mode import PW, login, server  # noqa: F401  (fixture)

SAMPLES = __import__("pathlib").Path(__file__).resolve().parents[1] / "samples"


def _part(c, project_id, file, material, process, code):
    with open(SAMPLES / file, "rb") as fh:
        m = c.post("/api/import/step", files={"file": (file, fh)}).json()
    return c.post(f"/api/import/{m['token']}/commit", json={"project_id": project_id, "items": {m["root"]: {"material": material, "process": process, "part_code": code}}})


def _user(c, username, role, groups):
    assert login(c).status_code == 200
    r = c.post("/api/users", json={"username": username, "password": PW, "role": role, "name": username.title(), "groups": groups})
    assert r.status_code == 200, r.text
    c.post("/api/auth/logout")
    return r.json()


def test_head_role_sits_between_approver_and_admin():
    assert auth.ROLES == ("viewer", "engineer", "approver", "head", "admin")
    head = {"role": "head"}
    assert auth.has_role("approver", head) and not auth.has_role("admin", head)


def test_users_see_only_their_tool_groups_and_the_admin_can_move_them(server):
    login(server)
    pl = server.post("/api/projects", json={"code": "PL", "name": "Plastic project"}).json()
    sm = server.post("/api/projects", json={"code": "SM", "name": "Sheet project"}).json()
    assert _part(server, pl["id"], "plastic_cover.step", "ABS", "injection_moulding", "PL-1").status_code == 200
    assert _part(server, sm["id"], "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage", "SM-1").status_code == 200
    server.post("/api/auth/logout")
    u1 = _user(server, "user1", "engineer", ["sheet_metal", "eps"])
    _user(server, "boss", "head", [])
    assert u1["groups"] == ["sheet_metal", "eps"]
    assert server.post("/api/users", json={"username": "x", "password": PW, "groups": ["wood"]}).status_code in (400, 401, 403)

    login(server, "user1")
    codes = {p["code"] for p in server.get("/api/projects").json()}
    assert codes == {"SM"}
    parts = server.get("/api/parts").json()["rows"]
    assert [p["part_code"] for p in parts] == ["SM-1"]
    pl_part = server.get("/api/parts", params={"q": "PL-1"}).json()["rows"]
    assert pl_part == []
    # opening a part or project of another group is refused
    login(server)
    pid_pl = server.get("/api/parts", params={"q": "PL-1"}).json()["rows"][0]["id"]
    server.post("/api/auth/logout")
    login(server, "user1")
    r = server.get(f"/api/parts/{pid_pl}")
    assert r.status_code == 403 and "tool group" in r.json()["detail"]
    assert server.get(f"/api/projects/{pl['id']}").status_code == 403
    # a new part only in my groups; my own new project stays visible
    mine = server.post("/api/projects", json={"code": "U1", "name": "Mine"}).json()
    assert "U1" in {p["code"] for p in server.get("/api/projects").json()}
    r = _part(server, mine["id"], "plastic_cover.step", "ABS", "injection_moulding", "U1-PL")
    assert r.status_code == 403 and "Plastic moulding" in r.json()["detail"]
    server.post("/api/auth/logout")

    login(server, "boss")                                   # head of department sees everything
    assert {"PL", "SM"} <= {p["code"] for p in server.get("/api/projects").json()}
    assert server.get(f"/api/parts/{pid_pl}").status_code == 200
    assert server.get("/api/users").status_code == 403      # but does not manage users
    server.post("/api/auth/logout")

    login(server)                                           # six months later: user1 moves to plastic
    r = server.put(f"/api/users/{u1['id']}", json={"groups": ["plastic", "die_casting"]})
    assert r.status_code == 200 and r.json()["groups"] == ["plastic", "die_casting"]
    server.post("/api/auth/logout")
    login(server, "user1")
    assert server.get(f"/api/parts/{pid_pl}").status_code == 200
    assert {p["part_code"] for p in server.get("/api/parts").json()["rows"]} == {"PL-1"}


def test_user_without_groups_sees_everything(server):
    login(server)
    p = server.post("/api/projects", json={"code": "A1", "name": "a"}).json()
    _part(server, p["id"], "plastic_cover.step", "ABS", "injection_moulding", "A1-1")
    server.post("/api/auth/logout")
    _user(server, "old", "engineer", [])
    login(server, "old")
    assert {"A1"} <= {x["code"] for x in server.get("/api/projects").json()}
    assert server.get("/api/parts").json()["total"] == 1
