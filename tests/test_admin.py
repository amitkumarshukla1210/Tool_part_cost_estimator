import pytest
from fastapi.testclient import TestClient

from backend.app import admin, auth, server_tools
from backend.app.main import app
from tests.test_server_mode import PW, login, make, server  # noqa: F401  (fixture)


def test_logins_are_on_by_default(monkeypatch):
    monkeypatch.delenv("DTC_MODE")
    assert auth.server_mode()
    monkeypatch.setenv("DTC_MODE", "local")
    assert not auth.server_mode()


def test_first_start_asks_for_the_first_admin(monkeypatch):
    monkeypatch.setenv("DTC_MODE", "server")
    monkeypatch.delenv("DTC_ADMIN_PASSWORD", raising=False)
    with TestClient(app) as c:
        page = c.get("/dashboard", follow_redirects=False)
        assert page.status_code == 303 and page.headers["location"] == "/setup"
        r = c.get("/api/projects")
        assert r.status_code == 401 and r.json()["setup"] is True
        assert c.get("/login", follow_redirects=False).headers["location"] == "/setup"
        assert c.post("/api/auth/setup", json={"username": "amit", "password": "short"}).status_code == 400
        r = c.post("/api/auth/setup", json={"username": "amit", "name": "Amit", "password": PW})
        assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
        assert c.get("/api/projects").status_code == 200                      # logged in straight away
        assert c.post("/api/auth/setup", json={"username": "evil", "password": PW}).status_code == 400   # only once
        assert c.get("/setup", follow_redirects=False).headers["location"] == "/login"


def test_permissions_per_role_can_be_changed_by_the_admin(server):
    make(server, "eric", "engineer")
    make(server, "vera", "viewer")
    login(server, "eric")
    assert server.post("/api/suppliers", json={"name": "S1"}).status_code == 200
    assert server.put("/api/admin/permissions", json={"permissions": []}).status_code == 403        # admin only
    assert server.get("/api/admin/permissions").status_code == 403                                   # admin only
    assert server.get("/api/admin/activity").status_code == 403                                     # approver by default
    server.post("/api/auth/logout")
    login(server)
    r = server.put("/api/admin/permissions", json={"permissions": [{"action": "manage_suppliers", "min_role": "approver"},
                                                                  {"action": "view_activity", "min_role": "engineer"}]})
    assert r.status_code == 200
    assert {p["action"]: p["min_role"] for p in r.json()["permissions"]}["manage_suppliers"] == "approver"
    assert server.put("/api/admin/permissions", json={"permissions": [{"action": "x", "min_role": "admin"}]}).status_code == 400
    server.post("/api/auth/logout")
    login(server, "eric")
    r = server.post("/api/suppliers", json={"name": "S2"})
    assert r.status_code == 403 and "Manage suppliers" in r.json()["detail"]
    assert server.get("/api/admin/activity").status_code == 200
    mine = server.get("/api/auth/me").json()["permissions"]
    assert mine["manage_suppliers"] is False and mine["view_activity"] is True
    server.post("/api/auth/logout")
    login(server, "vera")
    assert server.post("/api/gross-weight", json={"part_type": "foundry", "net_weight_g": 650, "density_g_cm3": 7.2}).status_code == 200  # a calculation
    assert server.post("/api/projects", json={"code": "V", "name": "v"}).status_code == 403


def test_user_permission_overrides_allow_deny_and_inherit(server, monkeypatch):
    make(server, "eric", "engineer")
    login(server)
    eric = next(u for u in server.get("/api/users").json() if u["username"] == "eric")
    assert "password_hash" not in eric
    server.post("/api/auth/logout")

    login(server, "eric")
    assert server.get("/api/admin/users/1/permissions").status_code == 403
    mine = server.get("/api/auth/me").json()["permissions"]
    assert mine["approve_rates"] is False and mine["backups"] is False and mine["update_app"] is False
    assert server.get("/api/admin/backups").status_code == 403
    assert server.post("/api/admin/update").status_code == 403
    server.post("/api/auth/logout")

    login(server)
    url = f"/api/admin/users/{eric['id']}/permissions"
    initial = server.get(url)
    assert initial.status_code == 200 and initial.json()["overrides"] == []
    saved = server.put(url, json={"overrides": [
        {"action": "approve_rates", "effect": "allow"},
        {"action": "backups", "effect": "allow"},
        {"action": "update_app", "effect": "allow"},
        {"action": "change_data", "effect": "deny"},
    ]})
    assert saved.status_code == 200
    assert server.put(url, json={"overrides": [{"action": "unknown", "effect": "allow"}]}).status_code == 400
    assert server.put(url, json={"overrides": [{"action": "backups", "effect": "maybe"}]}).status_code == 400
    assert server.put(url, json={"overrides": [{"action": "backups", "effect": "allow"},
                                                {"action": "backups", "effect": "deny"}]}).status_code == 400
    server.post("/api/auth/logout")

    login(server, "eric")
    mine = server.get("/api/auth/me").json()["permissions"]
    assert mine["approve_rates"] and mine["backups"] and mine["update_app"]
    assert mine["change_data"] is False
    assert server.get("/api/admin/backups").status_code == 200
    def no_kit():
        raise admin.AdminError("test: Windows kit unavailable")
    monkeypatch.setattr(admin, "start_windows_update", no_kit)
    assert server.post("/api/admin/update").status_code == 503  # permission passed; updater reports unavailable
    assert server.post("/api/projects", json={"code": "DENY", "name": "Denied"}).status_code == 403
    server.post("/api/auth/logout")

    login(server)
    reset = server.put(url, json={"overrides": []})
    assert reset.status_code == 200 and reset.json()["overrides"] == []
    rows = server.get("/api/admin/activity?entity=permissions").json()["rows"]
    assert any(r["entity_id"] == eric["id"] and r["action"] == "user_overrides_updated" for r in rows)
    server.post("/api/auth/logout")
    login(server, "eric")
    mine = server.get("/api/auth/me").json()["permissions"]
    assert mine["approve_rates"] is False and mine["backups"] is False and mine["update_app"] is False


def test_app_update_requires_windows_kit(monkeypatch):
    monkeypatch.delenv("DTC_KIT_MANAGER", raising=False)
    with pytest.raises(admin.AdminError, match="only when this app is running from the Windows kit"):
        admin.start_windows_update()


def test_activity_log_shows_who_did_what(server):
    make(server, "eric", "engineer")
    login(server, "eric")
    server.post("/api/projects", json={"code": "ACT", "name": "Activity"})
    server.post("/api/suppliers", json={"name": "Logged supplier"})
    server.post("/api/auth/logout")
    login(server)
    rows = server.get("/api/admin/activity").json()["rows"]
    assert any(r["entity"] == "project" and r["name"] == "ACT" and r["user"] == "Eric" for r in rows)
    assert any(r["entity"] == "supplier" and r["action"] == "created" for r in rows)
    assert any(r["entity"] == "user" and r["name"] == "eric" and r["action"] == "created" for r in rows)
    only = server.get("/api/admin/activity?entity=supplier").json()["rows"]
    assert only and all(r["entity"] == "supplier" for r in only)
    assert server.get("/api/admin/activity?user=nobody").json()["total"] == 0
    assert server.get("/api/admin/activity?date_from=bad").status_code == 400
    x = server.get("/api/admin/activity.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_master_data_saves_are_logged(server):
    login(server)
    t = server.get("/api/register-setup").json()
    assert server.put("/api/register-setup", json=t).status_code == 200
    rows = server.get("/api/admin/activity?entity=master_data").json()["rows"]
    assert rows and rows[0]["user"] == "Administrator" and "register-setup" in rows[0]["summary"]


def test_backups_from_the_admin_page(server):
    make(server, "eric", "engineer")
    login(server, "eric")
    assert server.post("/api/admin/backups").status_code == 403                                      # admin by default
    server.post("/api/auth/logout")
    login(server)
    b = server.post("/api/admin/backups").json()
    names = [x["name"] for x in server.get("/api/admin/backups").json()["backups"]]
    assert b["name"] in names
    assert server.get(f"/api/admin/backups/{b['name']}").content[:2] == b"PK"
    assert server.get("/api/admin/backups/..%2Fprojects.sqlite").status_code == 404
    assert server.get("/api/admin/about").json()["logins"] is True
    assert server.get("/admin").status_code == 200 and server.get("/users", follow_redirects=False).headers["location"] == "/admin"


def test_reset_password_from_the_command_line(server, capsys):
    login(server)
    assert server_tools.main(["reset-password", "admin", "--password", "a brand new password"]) == 0
    assert "logged out everywhere" in capsys.readouterr().out
    assert server.get("/api/projects").status_code == 401                                             # old session gone
    assert login(server, password="a brand new password").status_code == 200
    assert server_tools.main(["reset-password", "nobody", "--password", "a brand new password"]) == 1
