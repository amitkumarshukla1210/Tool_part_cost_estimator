from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from backend.app import auth, projects_db, server_tools
from backend.app.main import app

PW = "correct horse battery"


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("DTC_MODE", "server")
    monkeypatch.setenv("DTC_ADMIN_PASSWORD", PW)
    with TestClient(app) as c:            # the startup hook creates the first admin from DTC_ADMIN_PASSWORD
        yield c


def login(c, user="admin", password=PW):
    return c.post("/api/auth/login", json={"username": user, "password": password})


def make(c, username, role):
    assert login(c).status_code == 200
    r = c.post("/api/users", json={"username": username, "password": PW, "role": role, "name": username.title()})
    assert r.status_code == 200, r.text
    c.post("/api/auth/logout")


def test_local_mode_needs_no_login():
    c = TestClient(app)
    assert c.get("/api/projects").status_code == 200
    assert c.get("/api/auth/me").json() == {"mode": "local", "user": None}


def test_server_mode_blocks_everything_until_login(server):
    assert server.get("/api/projects").status_code == 401
    page = server.get("/dashboard", follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"] == "/login"
    assert server.get("/login").status_code == 200 and server.get("/api/server/health").json()["mode"] == "server"
    assert login(server, password="wrong password!").status_code == 401
    assert login(server, user="nobody").status_code == 401
    assert login(server).status_code == 200
    me = server.get("/api/auth/me").json()
    assert me["mode"] == "server" and me["user"]["username"] == "admin" and me["user"]["role"] == "admin"
    assert server.get("/api/projects").status_code == 200
    server.post("/api/auth/logout")
    assert server.get("/api/projects").status_code == 401


def test_roles_decide_who_may_change_what(server):
    make(server, "eric", "user")
    make(server, "alan", "head")
    login(server, "eric")
    assert server.get("/api/users").status_code == 403                                 # the user page is the admin's
    p = server.post("/api/projects", json={"code": "E1", "name": "User project"})
    assert p.status_code == 200
    r = server.post("/api/rates", json={"category": "material", "item": "ZZ2", "country": "IN", "value": 10, "unit": "INR/kg", "currency": "INR"})
    assert r.status_code == 403 and "head" in r.json()["detail"]                       # master data and rates are the head's / admin's
    server.post("/api/auth/logout")

    login(server, "alan")
    draft = server.post("/api/rates", json={"category": "material", "item": "ZZZ", "country": "IN", "value": 10, "unit": "INR/kg", "currency": "INR"}).json()
    assert draft["status"] == "draft"
    ok = server.post("/api/rates/status", json={"ids": [draft["id"]], "status": "approved"})
    assert ok.status_code == 200 and ok.json()[0]["approved_by"] == "Alan"             # the logged-in head, not a typed name
    assert server.get("/api/users").status_code == 403                                 # a head does not manage users


def test_history_records_the_logged_in_user(server):
    make(server, "eric", "user")
    login(server, "eric")
    pid = server.post("/api/projects", json={"code": "H1", "name": "History"}).json()["id"]
    part = server.post(f"/api/projects/{pid}/variants", json={"code": "STD", "name": "Std"})
    assert part.status_code == 200
    from backend.app import register
    with projects_db.engine().connect() as c:
        who = {r["user"] for r in c.execute(select(projects_db.history)).mappings() if r["entity"] == "project"}
    assert "Eric" in who


def test_user_management_rules(server):
    login(server)
    users = server.get("/api/users").json()
    admin_id = users[0]["id"]
    assert server.post("/api/users", json={"username": "short", "password": "tiny", "role": "user"}).status_code == 400
    assert server.post("/api/users", json={"username": "x", "password": PW, "role": "boss"}).status_code == 400
    assert server.post("/api/users", json={"username": "admin", "password": PW, "role": "user"}).status_code == 400
    assert server.put(f"/api/users/{admin_id}", json={"role": "user"}).status_code == 400          # the last admin cannot be demoted
    assert server.put(f"/api/users/{admin_id}", json={"active": False}).status_code == 400
    make(server, "bob", "user")
    login(server)
    bob = next(u for u in server.get("/api/users").json() if u["username"] == "bob")
    server.post("/api/auth/logout")
    login(server, "bob")
    assert server.get("/api/projects").status_code == 200
    login(server)
    server.put(f"/api/users/{bob['id']}", json={"active": False})
    server.post("/api/auth/logout")
    assert login(server, "bob").status_code == 401                                                    # deactivated: cannot log in
    login(server)
    server.put(f"/api/users/{bob['id']}", json={"active": True, "password": "another long password"})
    server.post("/api/auth/logout")
    assert login(server, "bob", "another long password").status_code == 200
    r = server.post("/api/auth/password", json={"old": "wrong", "new": "yet another password"})
    assert r.status_code == 400
    assert server.post("/api/auth/password", json={"old": "another long password", "new": "yet another password"}).status_code == 200
    server.post("/api/auth/logout")
    assert login(server, "bob", "yet another password").status_code == 200


def test_passwords_are_hashed_and_sessions_expire(server):
    h = auth.hash_password(PW)
    assert PW not in h and auth.check_password(PW, h) and not auth.check_password("x", h) and h != auth.hash_password(PW)
    login(server)
    cookie = server.cookies.get(auth.COOKIE)
    with projects_db.engine().begin() as c:
        c.execute(projects_db.sessions.update().values(expires_at=datetime(2000, 1, 1)))
    assert auth.user_of(cookie) is None and server.get("/api/projects").status_code == 401


def test_migrate_projects_copies_everything_and_refuses_a_filled_target(tmp_path, monkeypatch):
    c = TestClient(app)
    pid = c.post("/api/projects", json={"code": "MG", "name": "Migrate"}).json()["id"]
    c.post(f"/api/projects/{pid}/variants", json={"code": "STD", "name": "Std"})
    src = projects_db.database_url()
    dst = f"sqlite:///{tmp_path / 'copy.sqlite'}"
    counts = server_tools.migrate(src, dst)
    assert counts["projects"] == 1 and counts["variants"] == 1 and counts["history"] >= 2
    with create_engine(dst).connect() as conn:
        assert conn.execute(select(func.count()).select_from(projects_db.projects)).scalar() == 1
        assert conn.execute(select(projects_db.projects.c.code)).scalar() == "MG"
    with pytest.raises(ValueError, match="not empty"):
        server_tools.migrate(src, dst)
    with pytest.raises(ValueError, match="same database"):
        server_tools.migrate(src, src)


def test_cli_create_user_and_check(capsys):
    assert server_tools.main(["create-user", "cli.user", "--role", "head", "--password", PW]) == 0
    assert "head" in capsys.readouterr().out
    assert server_tools.main(["create-user", "cli.user", "--password", PW]) == 1
    assert server_tools.main(["check"]) == 0 and "sqlite" in capsys.readouterr().out
