"""Stage 50: opening a trace needs the permission "Open traces" (admin by default); the Suppliers page, menu and part-panel
block are gone (the data stays)."""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app
from tests.test_server_mode import login, make, server  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]


def test_open_traces_is_admin_only_by_default_and_can_be_given(server):
    make(server, "eric", "engineer")
    login(server)
    assert server.get("/api/auth/me").json()["permissions"]["open_traces"] is True
    perms = {p["action"]: p["min_role"] for p in server.get("/api/admin/permissions").json()["permissions"]}
    assert perms["open_traces"] == "admin"
    server.post("/api/auth/logout")
    login(server, "eric")
    assert server.get("/api/auth/me").json()["permissions"]["open_traces"] is False
    server.post("/api/auth/logout")
    login(server)
    assert server.put("/api/admin/permissions", json={"permissions": [{"action": "open_traces", "min_role": "engineer"}]}).status_code == 200
    server.post("/api/auth/logout")
    login(server, "eric")
    assert server.get("/api/auth/me").json()["permissions"]["open_traces"] is True
    # the page script refuses to open a trace without it, and values are plain text (CSS)
    js = (ROOT / "frontend" / "trace.js").read_text()
    assert "open_traces" in js and "if (!canTrace) return;" in js
    assert ".no-trace button.tv" in (ROOT / "frontend" / "register.css").read_text()


def test_suppliers_are_gone_from_the_pages_and_the_data_stays():
    c = TestClient(app)
    r = c.get("/suppliers", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/parts"
    for page in (ROOT / "frontend").glob("*.html"):
        assert 'href="/suppliers"' not in page.read_text(), page.name
    assert "suppliersBlock(p)}" not in (ROOT / "frontend" / "parts.js").read_text()
    assert c.post("/api/suppliers", json={"name": "Kept"}).status_code == 200      # data and API stay
    assert any(s["name"] == "Kept" for s in c.get("/api/suppliers").json()["suppliers"])
