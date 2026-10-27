"""Stage 36: AI assistant. A fake Anthropic client stands in for the real one, so no key or internet is needed."""
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from backend.app import bot
from backend.app.main import app
from tests.test_scope import _part, _user
from tests.test_server_mode import PW, login, server  # noqa: F401  (fixture)

KEY = "sk-ant-api03-test-key-0000000000ABCD"


class FakeClient:
    """Plays back scripted model turns; each turn is a list of ("text", str) or ("tool", name, input)."""

    def __init__(self, script, stop="end_turn"):
        self.script, self.stop, self.calls = list(script), stop, []
        self.beta = NS(messages=NS(create=self._create))
        self.models = NS(retrieve=self._retrieve)

    async def _create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})      # a copy: the bot keeps adding to its list
        turn = self.script.pop(0)
        blocks = [NS(type="text", text=t[1]) if t[0] == "text" else NS(type="tool_use", id=f"tu{len(self.calls)}{i}", name=t[1], input=t[2])
                  for i, t in enumerate(turn)]
        tools = any(b.type == "tool_use" for b in blocks)
        return NS(content=blocks, stop_reason="tool_use" if tools else self.stop, model=kw["model"])

    async def _retrieve(self, model):
        return NS(id=model, display_name="Fake " + model)


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def use(script, stop="end_turn"):
        holder["c"] = FakeClient(script, stop)
        monkeypatch.setattr(bot, "_client", lambda key: holder["c"])
        return holder["c"]
    return use


def _results(call):
    """The tool results the model got back, by tool name (from the next request)."""
    msgs = call["messages"]
    asked = {b.id: b.name for b in msgs[-2]["content"] if getattr(b, "type", "") == "tool_use"}
    return {asked[r["tool_use_id"]]: r for r in msgs[-1]["content"]}


def test_every_tool_is_a_read_only_route_of_the_app():
    gets = {r.path for r in app.routes if "GET" in getattr(r, "methods", set())}
    for name, (path, *_rest) in bot.TOOLS.items():
        assert path in gets, f"{name}: {path} is not a GET route"
    for rows in bot.DOWNLOADS.values():
        for _, url in rows:
            u = url.replace("{id}", "{part_id}")
            assert any(u == g or g.replace("{kind}", u.rsplit(".", 1)[-1]) == u for g in gets) or "/sheet-layout/" in u, url
    names = [t["name"] for t in bot.tool_definitions()]
    assert len(names) == len(set(names)) and "download_links" in names
    assert "variant_bom" not in names            # the variant BOM route has no tool-group filter


def test_settings_switch_key_and_status(fake):
    c = TestClient(app)
    assert c.get("/api/bot/status").json() == {"enabled": False, "switched_on": False, "key_set": False}
    r = c.post("/api/bot/chat", json={"question": "hello"})
    assert r.status_code == 400 and "switched off" in r.json()["detail"]
    c.put("/api/admin/bot", json={"enabled": True})
    r = c.post("/api/bot/chat", json={"question": "hello"})
    assert r.status_code == 400 and "API key" in r.json()["detail"]
    assert c.put("/api/admin/bot", json={"api_key": "not-a-key"}).status_code == 400
    assert c.put("/api/admin/bot", json={"model": "gpt-x"}).status_code == 400
    s = c.put("/api/admin/bot", json={"api_key": KEY, "model": "claude-sonnet-5-5"}).json()
    assert s["key_set"] and s["key_hint"] == "…ABCD" and s["model"] == "claude-sonnet-5-5" and KEY not in str(s)
    assert c.get("/api/bot/status").json()["enabled"] is True
    fake([])
    assert c.post("/api/admin/bot/test").json() == {"ok": True, "model": "claude-sonnet-5-5", "name": "Fake claude-sonnet-5-5"}
    s = c.put("/api/admin/bot", json={"clear_key": True}).json()
    assert not s["key_set"] and c.get("/api/bot/status").json()["enabled"] is False


def test_answers_from_the_tools_and_sends_download_links(fake):
    c = TestClient(app)
    c.put("/api/admin/bot", json={"enabled": True, "api_key": KEY})
    p = c.post("/api/projects", json={"code": "P1", "name": "Bracket project"}).json()
    assert _part(c, p["id"], "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage", "SM-9").status_code == 200
    pid = c.get("/api/parts", params={"q": "SM-9"}).json()["rows"][0]["id"]
    f = fake([[("tool", "search_parts", {"q": "SM-9"})],
              [("tool", "part_details", {"part_id": pid}), ("tool", "download_links", {"part_id": pid}),
               ("tool", "part_cost", {"part_id": "abc"}), ("tool", "delete_part", {"part_id": pid})],
              [("text", "SM-9 is a sheet-metal bracket.")]])
    r = c.post("/api/bot/chat", json={"question": "What is SM-9?", "page": "/parts?part=1",
                                      "history": [{"role": "assistant", "text": "Hi"}, {"role": "user", "text": "earlier"},
                                                  {"role": "assistant", "text": "earlier answer"}]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["reply"] == "SM-9 is a sheet-metal bracket." and out["model"] == "claude-opus-5-5"
    assert [t["tool"] for t in out["tools"]] == ["search_parts", "part_details", "download_links", "part_cost", "delete_part"]
    assert [t["ok"] for t in out["tools"]] == [True, True, True, False, False]
    first = f.calls[0]
    assert first["messages"][0] == {"role": "user", "content": "earlier"}          # history starts with a user turn
    assert "page open: /parts?part=1" in first["messages"][-1]["content"][0]["text"]
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert first["output_config"] == {"effort": "medium"} and first["system"] == bot.SYSTEM
    assert '"SM-9"' in _results(f.calls[1])["search_parts"]["content"]
    res = _results(f.calls[2])
    assert '"part_code":"SM-9"' in res["part_details"]["content"]
    links = res["download_links"]["content"]
    assert f"/api/parts/{pid}/sheet-layout/blank.dxf" in links and "simulation/report.pdf" not in links
    assert res["part_cost"]["is_error"] and "whole number" in res["part_cost"]["content"]
    assert res["delete_part"]["is_error"] and "Unknown tool" in res["delete_part"]["content"]
    act = c.get("/api/admin/activity", params={"entity": "bot"}).json()
    assert any(r["action"] == "asked" and r["detail"]["question"] == "What is SM-9?" for r in act["rows"])


def test_refusal_too_many_steps_and_no_fallback_for_haiku(fake):
    c = TestClient(app)
    c.put("/api/admin/bot", json={"enabled": True, "api_key": KEY, "model": "claude-haiku-5-5"})
    f = fake([[("text", "")]], stop="refusal")
    assert c.post("/api/bot/chat", json={"question": "x"}).json()["reply"] == "I can't help with that request."
    assert "fallbacks" not in f.calls[0] and "betas" not in f.calls[0]
    fake([[("tool", "list_projects", {})]] * bot.MAX_ROUNDS)
    assert "too many steps" in c.post("/api/bot/chat", json={"question": "x"}).json()["reply"]


def test_anthropic_errors_become_plain_messages(monkeypatch):
    import anthropic
    import httpx2

    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

    async def refused(**kw):
        raise anthropic.AuthenticationError("bad key", response=httpx2.Response(401, request=req), body=None)
    monkeypatch.setattr(bot, "_client", lambda key: NS(beta=NS(messages=NS(create=refused))))
    c = TestClient(app)
    c.put("/api/admin/bot", json={"enabled": True, "api_key": KEY})
    r = c.post("/api/bot/chat", json={"question": "x"})
    assert r.status_code == 502 and "refused" in r.json()["detail"]


def test_with_logins_everyone_may_ask_but_sees_only_their_own_data(server, fake):  # noqa: F811
    login(server)
    pl = server.post("/api/projects", json={"code": "PL", "name": "Plastic project"}).json()
    sm = server.post("/api/projects", json={"code": "SM", "name": "Sheet project"}).json()
    assert _part(server, pl["id"], "plastic_cover.step", "ABS", "injection_moulding", "PL-1").status_code == 200
    assert _part(server, sm["id"], "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage", "SM-1").status_code == 200
    pl_id = server.get("/api/parts", params={"q": "PL-1"}).json()["rows"][0]["id"]
    assert server.put("/api/admin/bot", json={"enabled": True, "api_key": KEY}).status_code == 200
    server.post("/api/auth/logout")
    _user(server, "sheetguy", "viewer", ["sheet_metal"])

    login(server, "sheetguy")
    # settings and the key are admin only
    assert server.get("/api/admin/bot").status_code == 403
    assert server.put("/api/admin/bot", json={"enabled": False}).status_code == 403
    assert server.post("/api/admin/bot/test").status_code == 403
    assert server.get("/api/bot/status").json()["enabled"] is True
    f = fake([[("tool", "search_parts", {}), ("tool", "part_details", {"part_id": pl_id}),
               ("tool", "project_dashboard", {"project_id": pl["id"]})],
              [("text", "You can see SM-1 only.")]])
    r = server.post("/api/bot/chat", json={"question": "Which parts are there?"})      # a viewer may ask
    assert r.status_code == 200, r.text
    res = _results(f.calls[1])
    assert '"SM-1"' in res["search_parts"]["content"] and "PL-1" not in res["search_parts"]["content"]
    assert res["part_details"]["is_error"] and "403" in res["part_details"]["content"] and "tool group" in res["part_details"]["content"]
    assert res["project_dashboard"]["is_error"] and "403" in res["project_dashboard"]["content"]
    assert "role viewer" in f.calls[0]["messages"][-1]["content"][0]["text"]
    server.post("/api/auth/logout")
    assert server.post("/api/bot/chat", json={"question": "x"}).status_code == 401        # not logged in
