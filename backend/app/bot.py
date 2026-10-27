"""AI assistant (roadmap stage 36): ask questions about parts, costs, tools and rates in plain language.

    who           everyone who is logged in. The assistant sees only what that user's role and tool groups already allow:
                  every tool below is a GET call to this app's own API, sent with the user's own login cookie, so the
                  login, permission and tool-group checks (auth.py, scope.py) apply exactly as on the screens.
    read only     the tools are GET calls only, so the assistant can never approve, change or delete anything. For a
                  change it tells the user which page to use.
    files         reports, drawings, 3D and videos are not read into the chat: the assistant gives download links.
    settings      Admin → AI assistant: on / off, model and the Anthropic API key. They are stored in the project
                  database (data/, never in GitHub); the key is never shown again, only its last 4 characters.
    log           every question goes to the activity log (who asked what, which tools ran), not the answers.

Conversation: the browser keeps the chat and sends the earlier turns back as plain text with each question.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime
from urllib.parse import urlencode

from sqlalchemy import select

from . import auth, register_setup
from . import projects_db as db

MODELS = {
    "claude-opus-5-5": "Claude Opus 5.5 (best answers, recommended)",
    "claude-sonnet-5-5": "Claude Sonnet 5.5 (faster, about half the cost)",
    "claude-haiku-5-5": "Claude Haiku 5.5 (fastest, lowest cost, simple questions)",
}
DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")   # server-side refusal fallback ("default" form)
MAX_ROUNDS = 10            # tool rounds per question
MAX_RESULT_CHARS = 30000   # one tool result sent to the model
MAX_TURNS = 20             # earlier chat turns sent back
MAX_TURN_CHARS = 8000
KEYS = ("bot_enabled", "bot_model", "bot_api_key")


class BotError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------- settings (Admin → AI assistant) ----------

def _raw() -> dict:
    with db.engine().connect() as conn:
        rows = conn.execute(select(db.app_settings).where(db.app_settings.c.key.in_(KEYS))).mappings().all()
    return {r["key"]: r for r in rows}


def api_key() -> str:
    """The saved key; ANTHROPIC_API_KEY on the server is used only when none is saved."""
    r = _raw().get("bot_api_key")
    return (r["value"] if r and r["value"] else "") or os.environ.get("ANTHROPIC_API_KEY", "")


def settings() -> dict:
    """For the Admin page: never the key itself, only whether one is set and its last 4 characters."""
    raw = _raw()
    saved = raw["bot_api_key"]["value"] if "bot_api_key" in raw else ""
    key = api_key()
    return {
        "enabled": (raw["bot_enabled"]["value"] == "yes") if "bot_enabled" in raw else False,
        "model": raw["bot_model"]["value"] if "bot_model" in raw and raw["bot_model"]["value"] in MODELS else DEFAULT_MODEL,
        "models": [{"code": k, "name": v} for k, v in MODELS.items()],
        "key_set": bool(key),
        "key_hint": f"…{key[-4:]}" if key else "",
        "key_source": "saved" if saved else ("server environment (ANTHROPIC_API_KEY)" if key else ""),
        "updated_by": raw["bot_api_key"]["updated_by"] if "bot_api_key" in raw else "",
        "updated_at": raw["bot_api_key"]["updated_at"].isoformat(timespec="seconds") if "bot_api_key" in raw and raw["bot_api_key"]["updated_at"] else "",
    }


def save_settings(data: dict) -> dict:
    """enabled, model; api_key only when typed (blank = keep the saved one); clear_key = remove the saved key."""
    values = {}
    if "enabled" in data:
        values["bot_enabled"] = "yes" if data["enabled"] else "no"
    if data.get("model"):
        if data["model"] not in MODELS:
            raise BotError(f"Unknown model '{data['model']}' ({', '.join(MODELS)}).")
        values["bot_model"] = data["model"]
    key = (data.get("api_key") or "").strip()
    if key:
        if not key.startswith("sk-ant-") or len(key) < 20 or any(c.isspace() for c in key):
            raise BotError("That does not look like an Anthropic API key (it starts with sk-ant-).")
        values["bot_api_key"] = key
    elif data.get("clear_key"):
        values["bot_api_key"] = ""
    who = auth.username() or "local user"
    with db.engine().begin() as conn:
        for k, v in values.items():
            if conn.execute(select(db.app_settings.c.key).where(db.app_settings.c.key == k)).first():
                conn.execute(db.app_settings.update().where(db.app_settings.c.key == k).values(value=v, updated_by=who))
            else:
                conn.execute(db.app_settings.insert().values(key=k, value=v, updated_by=who))
        auth.log(conn, "bot", 0, "settings saved", {k: ("(key changed)" if k == "bot_api_key" else v) for k, v in values.items()})
    return settings()


def status() -> dict:
    """For every page: is the assistant there to use?"""
    s = settings()
    return {"enabled": s["enabled"] and s["key_set"], "switched_on": s["enabled"], "key_set": s["key_set"]}


# ---------- tools: read-only GET calls to this app's own API ----------

def _int(desc):
    return {"type": "integer", "description": desc}


def _str(desc):
    return {"type": "string", "description": desc}


PART = {"part_id": _int("Part id (the number from search_parts, not the part code)")}
PROJECT = {"project_id": _int("Project id (from list_projects)")}

# name -> (path template, description, input properties, required)
TOOLS: dict[str, tuple[str, str, dict, list]] = {
    "list_projects": ("/api/projects", "All projects the user may see: id, code, name, customer, status, part count.", {}, []),
    "project_details": ("/api/projects/{project_id}", "One project with its variants.", PROJECT, ["project_id"]),
    "project_dashboard": ("/api/projects/{project_id}/dashboard", "Project dashboard: BOM of the parts with their status, RM / part / tool cost and target.", PROJECT, ["project_id"]),
    "project_leader_view": ("/api/projects/{project_id}/leader", "Project leader view: BOM cost against target, CAPEX (tool cost) and CAPEX plan, open corrections.", PROJECT, ["project_id"]),
    "search_parts": ("/api/parts", "Search the part register (only the user's tool groups). Returns id, part_code, name, process, material, status, target, RM / tool cost.", {
        "q": _str("Text in part code or name"), "project_id": _int("Only parts of this project"),
        "process": _str("Process code, e.g. injection_moulding, hpdc, sheet_metal_multistage"), "status": _str("Part status code"),
        "sort": _str("Sort column, e.g. part_code, -target_cost"), "limit": _int("Rows (default 50, max 200)")}, []),
    "part_details": ("/api/parts/{part_id}", "Everything about one part: geometry, weight, material, process, country, revisions, tool summary, recommended material grade.", PART, ["part_id"]),
    "part_geometry_trace": ("/api/parts/{part_id}/trace", "How volume, net and gross weight of the part were worked out (traced).", PART, ["part_id"]),
    "rm_cost": ("/api/parts/{part_id}/rm-cost", "Raw-material cost versions of the part (gross weight, yield, rate, scrap credit).", PART, ["part_id"]),
    "part_cost": ("/api/parts/{part_id}/piece-cost", "Part (piece) cost: latest stored version, all versions, outdated flag and the live traced result (RM, process, MHR, labour, overhead, profit, packing, tool amortisation, logistics).", PART, ["part_id"]),
    "part_cost_trace": ("/api/parts/{part_id}/piece-cost/trace", "Full traceability of the part cost: every value with formula and source (rate, master data).", PART, ["part_id"]),
    "tool_cost": ("/api/parts/{part_id}/tool-cost", "Tool (mould / die) cost versions: cavities, tool size, BOM, machining, total, tool country.", PART, ["part_id"]),
    "tool_cost_trace": ("/api/parts/{part_id}/tool-cost/trace", "Full traceability of the tool cost (one version, default latest): BOM, steel grades, rates, hours.", {**PART, "version": _int("Tool cost version (optional)")}, ["part_id"]),
    "mould_concept": ("/api/parts/{part_id}/concept", "Mould / die concept: opening direction, undercuts, slides / lifters, gate, runner, cooling, ejection, inserts.", PART, ["part_id"]),
    "simulation": ("/api/parts/{part_id}/simulation", "Simulation & analysis: wall thickness, draft, risks, cycle time, clamp force, machine, corrections required.", PART, ["part_id"]),
    "sheet_metal_tools": ("/api/parts/{part_id}/sheet-tools", "Sheet-metal tools: operation sequence, die type, forces, tonnage, press, formability.", PART, ["part_id"]),
    "tool_design": ("/api/parts/{part_id}/tool-design", "3D tool design: each tool (die stage or mould) with its parts, material, hardness, standard parts.", PART, ["part_id"]),
    "process_parameters": ("/api/parts/{part_id}/process-parameters", "Machine settings for the first trial with their range, and quality warnings.", PART, ["part_id"]),
    "machine_check": ("/api/parts/{part_id}/machine-check", "Each tool checked against the production machine, or the recommended machine.", PART, ["part_id"]),
    "design_loop": ("/api/parts/{part_id}/design-loop", "Design loop status of the part: steps, corrections, approvals.", PART, ["part_id"]),
    "country_comparison": ("/api/parts/{part_id}/country-comparison", "Part and tool made in each country: ex-works and landed in India with freight and duties.", {
        **PART, "countries": _str("Comma-separated country codes, e.g. IN,CN,TH (optional)"),
        "mode": _str("Freight: sea or air (default sea)")}, ["part_id"]),
    "part_suppliers": ("/api/parts/{part_id}/suppliers", "Suppliers and quotes linked to the part.", PART, ["part_id"]),
    "search_suppliers": ("/api/suppliers", "Supplier master: name, status, country, commodity, ratings.", {
        "q": _str("Text in name or code"), "status": _str("Supplier status"), "country": _str("Country code"),
        "commodity": _str("Commodity")}, []),
    "rates_grid": ("/api/rates/grid", "Material and process rates as item × country (approved rates used in costing, EXAMPLE flags).", {
        "as_of": _str("Costing month YYYY-MM (optional, default this month)")}, []),
    "rate_history": ("/api/rates/history", "All versions of one rate (value, month, status, approver, source).", {
        "category": _str("Rate category, e.g. material, material_scrap, tool_material, process, forex"),
        "item": _str("Item name exactly as in the rates grid"), "country": _str("Country code (optional)")}, ["category", "item"]),
    "price_master": ("/api/price-master/grid", "Month-by-month prices for one country: tool steels (group tool_material), part raw materials (material) or scrap (material_scrap).", {
        "group": _str("tool_material, material or material_scrap"), "country": _str("Country code, e.g. IN"),
        "months": _int("How many months back (default 12)")}, ["group", "country"]),
    "tool_steel_prices": ("/api/tool-bom/grade-prices", "Tool steel grade prices per kg in one country.", {"country": _str("Country code (default IN)")}, []),
}

DOWNLOADS = {
    "all": [("Part cost PDF", "/api/parts/{id}/piece-cost/export.pdf"), ("Part cost Excel", "/api/parts/{id}/piece-cost/export.xlsx"),
            ("RM cost PDF", "/api/parts/{id}/rm-cost/export.pdf"), ("Tool cost PDF", "/api/parts/{id}/tool-cost/export.pdf"),
            ("Tool cost Excel", "/api/parts/{id}/tool-cost/export.xlsx"), ("Country comparison PDF", "/api/parts/{id}/country-comparison/export.pdf"),
            ("Part drawing PDF", "/api/parts/{id}/drawing.pdf"), ("Part drawing DXF", "/api/parts/{id}/drawing.dxf"),
            ("Tool concept drawing PDF", "/api/parts/{id}/tool-drawing.pdf"), ("Tool design release pack ZIP (3D STEP, drawings, BOM)", "/api/parts/{id}/tool-design.zip"),
            ("Process parameters PDF", "/api/parts/{id}/process-parameters.pdf"), ("PO pack ZIP (everything for a quotation / PO)", "/api/parts/{id}/po-pack.zip")],
    "sheet_metal": [("Blank DXF", "/api/parts/{id}/sheet-layout/blank.dxf"), ("Strip layout DXF", "/api/parts/{id}/sheet-layout/strip.dxf"),
                    ("Sheet-metal tool pack PDF", "/api/parts/{id}/sheet-layout/tool-pack.pdf"),
                    ("Forming simulation report PDF", "/api/parts/{id}/forming-simulation.pdf"), ("Forming simulation video", "/api/parts/{id}/forming-simulation.video")],
    "moulded": [("Simulation report PDF", "/api/parts/{id}/simulation/report.pdf"), ("Simulation video", "/api/parts/{id}/simulation/video")],
}


def tool_definitions() -> list[dict]:
    """Fixed order and content, so the prompt cache keeps working."""
    out = [{"name": n, "description": d, "input_schema": {"type": "object", "properties": props, "required": req}}
           for n, (_, d, props, req) in TOOLS.items()]
    out.append({"name": "download_links", "description": "Download links (PDF, Excel, DXF, STEP, ZIP, video) for one part. "
                "Give these to the user as links instead of reading files. A file that is not calculated yet answers with a message.",
                "input_schema": {"type": "object", "properties": PART, "required": ["part_id"]}})
    return out


SYSTEM = """You are the AI assistant inside Design to Cost, the Part Cost Estimator of an OEM. Its users are cost, sourcing, \
tooling, production and project people. You answer questions about projects, parts, raw-material (RM) cost, part cost, \
tool (mould / die) cost, tool design, simulation, machines, suppliers and rates.

How to work:
- Get every number from the tools. Never estimate, invent or remember a cost, rate, weight or result. If the tools do not \
have it, say what is missing and on which page the user can calculate or enter it.
- Find a part by its code with search_parts first, then use its id. A project by code: list_projects.
- Say where a number comes from (traced value, rate and month, master data). Mention when a rate is an EXAMPLE rate, \
when a stored cost is outdated, and the currency and unit of every amount (costs are INR unless the tool says otherwise).
- You are read only. You cannot change, approve, recalculate or delete anything. For that, tell the user which page and \
button to use (e.g. Parts → open the part → Part cost → Recalculate; Rates → Rate review).
- A tool answer with status 403 means this user may not see that part or project (role or tool group). Say so plainly; \
do not try to get the data another way.
- For reports, drawings, 3D models and videos use download_links and give the links as markdown links, exactly as \
returned (they start with /api/).
- Answer short and to the point for busy managers: the answer first, then the key numbers, then the reasons. Use a \
small table to compare parts, versions or countries. Plain language, no internal tool names in the answer."""


def _part_type(process: str | None) -> str:
    proc = register_setup.processes().get(process or "")
    return proc["part_type"] if proc else ""


def _links(part: dict) -> list[dict]:
    kind = _part_type(part.get("process"))
    rows = DOWNLOADS["all"] + (DOWNLOADS["sheet_metal"] if kind == "sheet_metal" else
                               DOWNLOADS["moulded"] if kind in ("plastic", "die_casting") else [])
    return [{"name": n, "url": u.format(id=part["id"])} for n, u in rows]


async def asgi_get(app, path: str, params: dict, cookie: str) -> tuple[int, str, bytes]:
    """One GET request straight into this app (no network), with the user's login cookie: the same checks as the screens."""
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    headers = [(b"host", b"dtc-assistant"), (b"accept", b"application/json")]
    if cookie:
        headers.append((b"cookie", f"{auth.COOKIE}={cookie}".encode("latin-1")))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": path, "raw_path": path.encode(), "root_path": "", "query_string": query.encode(), "headers": headers,
             "client": ("127.0.0.1", 0), "server": ("dtc-assistant", 80)}
    sent = False
    status, ctype, body = 500, "", []

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()                  # the caller never disconnects

    async def send(msg):
        nonlocal status, ctype
        if msg["type"] == "http.response.start":
            status = msg["status"]
            ctype = dict(msg.get("headers") or []).get(b"content-type", b"").decode("latin-1")
        elif msg["type"] == "http.response.body":
            body.append(msg.get("body", b""))

    await app(scope, receive, send)
    return status, ctype, b"".join(body)


async def run_tool(app, name: str, args: dict, cookie: str) -> tuple[str, bool]:
    """(text for the model, is_error). Only the tools above, only GET."""
    if name == "download_links":
        part_id = _as_int(args.get("part_id"), "part_id")
        status, _, body = await asgi_get(app, f"/api/parts/{part_id}", {}, cookie)
        if status != 200:
            return _error_text(status, body), True
        return json.dumps({"links": _links(json.loads(body))}), False
    if name not in TOOLS:
        return f"Unknown tool '{name}'.", True
    template, _, props, required = TOOLS[name]
    missing = [r for r in required if args.get(r) in (None, "")]
    if missing:
        return f"Missing: {', '.join(missing)}.", True
    path_keys = [k for k in props if "{" + k + "}" in template]
    path = template.format(**{k: _as_int(args[k], k) for k in path_keys})
    params = {}
    for k, schema in props.items():
        if k in path_keys or args.get(k) in (None, ""):
            continue
        params[k] = _as_int(args[k], k) if schema["type"] == "integer" else str(args[k])
    if name == "search_parts":
        params["limit"] = max(1, min(int(params.get("limit", 50)), 200))
    status, ctype, body = await asgi_get(app, path, params, cookie)
    if status != 200:
        return _error_text(status, body), True
    if "json" not in ctype:
        return f"(not data: {ctype or 'unknown type'}; use download_links for files)", True
    text = json.dumps(json.loads(body), ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f' … [cut: {len(text):,} characters in all; ask for one part or version at a time]'
    return text, False


def _as_int(v, name) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        raise BotError(f"{name} must be a whole number, not '{v}'.") from None


def _error_text(status: int, body: bytes) -> str:
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        detail = body[:300].decode("utf-8", "replace")
    return f"status {status}: {detail}"


# ---------- the conversation ----------

def _client(key: str):
    import anthropic
    return anthropic.AsyncAnthropic(api_key=key, timeout=180.0, max_retries=2)


def _history(turns: list[dict]) -> list[dict]:
    """Earlier turns as plain text (no tool calls, no thinking): the model asks the tools again when it needs data."""
    out = []
    for t in turns[-MAX_TURNS:]:
        role = t.get("role")
        text = str(t.get("text") or "").strip()[:MAX_TURN_CHARS]
        if role in ("user", "assistant") and text:
            if out and out[-1]["role"] == role:
                out[-1]["content"] += "\n\n" + text
            else:
                out.append({"role": role, "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def _context(page: str) -> str:
    u = auth.current()
    who = f"{u['name'] or u['username']} (role {u['role']}{', tool groups ' + ', '.join(u['groups']) if u.get('groups') else ''})" if u else "local user"
    return f"[Context: user {who}; page open: {page or 'unknown'}; today {date.today().isoformat()}]"


async def chat(app, question: str, turns: list[dict], page: str, cookie: str) -> dict:
    question = (question or "").strip()
    if not question:
        raise BotError("Type a question.")
    s = settings()
    if not s["enabled"]:
        raise BotError("The AI assistant is switched off (Admin → AI assistant).")
    key = api_key()
    if not key:
        raise BotError("No API key yet: the admin enters it on Admin → AI assistant.")
    model = s["model"]
    messages = _history(turns) + [{"role": "user", "content": [
        {"type": "text", "text": _context(page)}, {"type": "text", "text": question[:MAX_TURN_CHARS]}]}]
    extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if model in FALLBACK_MODELS else {}
    client = _client(key)
    used, response = [], None
    import anthropic
    try:
        for _ in range(MAX_ROUNDS):
            response = await client.beta.messages.create(
                model=model, max_tokens=16000, system=SYSTEM, tools=tool_definitions(), messages=messages,
                output_config={"effort": "medium"}, cache_control={"type": "ephemeral"}, **extra)
            if response.stop_reason == "refusal":
                return _answer(question, "I can't help with that request.", used, response)
            if response.stop_reason != "tool_use":
                break
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    text, is_error = await run_tool(app, block.name, dict(block.input or {}), cookie)
                except BotError as exc:
                    text, is_error = str(exc), True
                used.append({"tool": block.name, "ok": not is_error})
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": is_error})
            messages.append({"role": "user", "content": results})
        else:
            return _answer(question, "That needed too many steps. Please ask about one part or project at a time.", used, response)
    except anthropic.AuthenticationError:
        raise BotError("The API key was refused by Anthropic. The admin can enter a new one on Admin → AI assistant.", 502) from None
    except anthropic.PermissionDeniedError:
        raise BotError(f"This API key may not use {model}. The admin can choose another model on Admin → AI assistant.", 502) from None
    except anthropic.RateLimitError:
        raise BotError("The assistant is busy (rate limit). Please try again in a minute.", 503) from None
    except anthropic.APIConnectionError:
        raise BotError("Cannot reach Anthropic. Check the internet connection or proxy of the PC that runs the app.", 502) from None
    except anthropic.APIStatusError as exc:
        raise BotError(f"The assistant had a problem ({exc.status_code}). Please try again.", 502) from None
    text = "\n\n".join(b.text for b in response.content if b.type == "text").strip() or "(no answer)"
    if response.stop_reason == "max_tokens":
        text += "\n\n(The answer was cut off. Ask for a shorter answer or one part at a time.)"
    return _answer(question, text, used, response)


def _answer(question: str, text: str, used: list[dict], response) -> dict:
    with db.engine().begin() as conn:
        auth.log(conn, "bot", 0, "asked", {"question": question[:300], "tools": [u["tool"] for u in used]})
    return {"reply": text, "tools": used, "model": getattr(response, "model", ""), "at": datetime.now().isoformat(timespec="seconds")}


async def check_key() -> dict:
    """Admin → Test: the key and the chosen model answer (reads the model, uses no tokens)."""
    key, model = api_key(), settings()["model"]
    if not key:
        raise BotError("No API key saved yet.")
    import anthropic
    try:
        m = await _client(key).models.retrieve(model)
    except anthropic.AuthenticationError:
        raise BotError("Anthropic refused this API key.") from None
    except (anthropic.NotFoundError, anthropic.PermissionDeniedError):
        raise BotError(f"This API key cannot use {model}. Choose another model.") from None
    except anthropic.APIConnectionError:
        raise BotError("Cannot reach Anthropic from this PC (internet or proxy).") from None
    return {"ok": True, "model": m.id, "name": getattr(m, "display_name", m.id)}
