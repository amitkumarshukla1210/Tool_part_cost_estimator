"""Logins, roles, permissions and who-did-what (roadmap stages 17 and 22).

    logins            every page and API call needs a login (cookie session). The first start, with no user yet, shows
                      /setup to create the first admin. DTC_MODE=local turns logins off: only for the automated tests
                      and developers; the Windows kit always starts with logins.
    roles             viewer < engineer < approver < head < admin  (head = head of department: sees all data, stage 30)
    tool groups       each login ID has tool groups (scope.py): it sees the parts and projects of those groups
    permissions       the lowest role for each action (PERMISSIONS); the admin changes them on Admin → Permissions
                      (table role_permissions). Managing users and permissions is always admin only.
    who               the logged-in user is the author of every history record and the approver of every rate approval

Passwords: scrypt with a random salt (standard library). Sessions: a random token in an HttpOnly cookie; only its SHA-256 is stored.
"""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select

from . import projects_db as db

ROLES = ("viewer", "engineer", "approver", "head", "admin")
COOKIE = "dtc_session"
SESSION_HOURS = 12
MIN_PASSWORD = 10
PUBLIC_PREFIXES = ("/login", "/setup", "/static", "/theme", "/api/auth/login", "/api/auth/setup", "/api/server/health", "/favicon")
ADMIN_PREFIXES = ("/api/users", "/api/admin/users", "/api/admin/bot")

# action -> (default lowest role, label, what it covers). Order = order on the Admin page.
PERMISSIONS = {
    "change_data": ("engineer", "Change project data", "Create and change projects, variants, parts, revisions, imports, costs, design-loop status, CAPEX, BOM extracts"),
    "edit_master_data": ("engineer", "Edit master data", "General master data, mould & die database, countries, machines & formulas, part register setup"),
    "edit_rates": ("engineer", "Edit rates", "Create, change, upload and fetch rate drafts; rate settings"),
    "approve_rates": ("approver", "Approve rates", "Approve rate drafts (only approved rates are used in costing)"),
    "manage_suppliers": ("engineer", "Manage suppliers", "Supplier master and the suppliers / quotes of parts"),
    "delete_part": ("approver", "Delete parts", "Delete a part from the register (a backup is made first); taking it out of a BOM is 'Change project data'"),
    "delete_project": ("admin", "Delete projects", "Delete a project with its parts and costs (a backup is made first)"),
    "view_activity": ("approver", "See the activity log", "Admin → Activity log: who changed what, when"),
    "backups": ("admin", "Backups", "Admin → Backups: list, make and download backups"),
}
# Pure calculations that change nothing: anyone logged in may run them.
CALC_PATHS = ("/api/analyze", "/api/gross-weight", "/api/capacity", "/api/mould/estimate", "/api/tool-cost", "/api/suggest-process")
MASTER_PATHS = ("/api/master-data", "/api/mould-db", "/api/costing-setup", "/api/register-setup", "/api/examples",
                "/api/tool-materials", "/api/standard-parts", "/api/master-rows")
RATE_PATHS = ("/api/rates", "/api/settings", "/api/price-master")
# The AI assistant (bot.py): any logged-in user may ask; it only reads, with that user's own login.
BOT_PATHS = ("/api/bot/",)

_user: contextvars.ContextVar = contextvars.ContextVar("dtc_user", default=None)


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


def server_mode() -> bool:
    """Logins on (the default). Only DTC_MODE=local turns them off (automated tests, developers)."""
    return os.environ.get("DTC_MODE", "server").lower() != "local"


def current() -> dict | None:
    return _user.get()


def username() -> str | None:
    u = current()
    return (u["name"] or u["username"]) if u else None


def set_current(user: dict | None):
    return _user.set(user)


def reset(token) -> None:
    _user.reset(token)


def has_role(minimum: str, user: dict | None = None) -> bool:
    u = user or current()
    return bool(u) and ROLES.index(u["role"]) >= ROLES.index(minimum)


def require(minimum: str) -> None:
    """With logins: the logged-in user must have at least this role. Local mode: always fine."""
    if server_mode() and not has_role(minimum):
        raise AuthError(f"This needs the role '{minimum}' (you are {current()['role'] if current() else 'not logged in'}).", 403)


# ---------- permissions ----------

def permissions() -> list[dict]:
    with db.engine().connect() as conn:
        saved = {r["action"]: r for r in conn.execute(select(db.role_permissions)).mappings()}
    return [{"action": a, "label": label, "covers": covers, "default": d,
             "min_role": saved[a]["min_role"] if a in saved else d,
             "updated_by": saved[a]["updated_by"] if a in saved else "",
             "updated_at": saved[a]["updated_at"].isoformat(timespec="seconds") if a in saved and saved[a]["updated_at"] else ""}
            for a, (d, label, covers) in PERMISSIONS.items()]


def min_role(action: str) -> str:
    return next(p["min_role"] for p in permissions() if p["action"] == action)


def may(action: str, user: dict | None = None) -> bool:
    return not server_mode() or has_role(min_role(action), user)


def require_perm(action: str) -> None:
    if not may(action):
        label = PERMISSIONS[action][1]
        raise AuthError(f"'{label}' needs the role '{min_role(action)}' or higher (Admin → Permissions).", 403)


def save_permissions(rows: list[dict], by: dict | None) -> list[dict]:
    """[{action, min_role}] -> saved; a history record per change."""
    old = {p["action"]: p["min_role"] for p in permissions()}
    changes = {}
    for r in rows:
        a, role = r.get("action"), r.get("min_role")
        if a not in PERMISSIONS:
            raise AuthError(f"Unknown permission '{a}'.", 400)
        if role not in ROLES:
            raise AuthError(f"Role must be one of {', '.join(ROLES)}.", 400)
        if old[a] != role:
            changes[a] = {"old": old[a], "new": role}
    who = (by or {}).get("username") or "local user"
    with db.engine().begin() as conn:
        for a, ch in changes.items():
            conn.execute(db.role_permissions.delete().where(db.role_permissions.c.action == a))
            conn.execute(db.role_permissions.insert().values(action=a, min_role=ch["new"], updated_by=who))
        if changes:
            log(conn, "permissions", 0, "updated", changes)
    return permissions()


def log(conn, entity: str, entity_id: int, action: str, detail: dict | None = None) -> None:
    conn.execute(db.history.insert().values(entity=entity, entity_id=entity_id, action=action, detail=detail or {},
                                            user=username() or "local user"))


# ---------- passwords ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got.hex(), h)
    except (ValueError, TypeError):
        return False


def _check_new_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"The password must have at least {MIN_PASSWORD} characters.", 400)


# ---------- users ----------

def _groups(value) -> list:
    from .scope import GROUPS
    bad = [g for g in (value or []) if g not in GROUPS]
    if bad:
        raise AuthError(f"Unknown tool group {', '.join(map(str, bad))}: use {', '.join(GROUPS)}.", 400)
    return [g for g in GROUPS if g in (value or [])]


def _public(u) -> dict:
    return {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"], "active": bool(u["active"]),
            "groups": list(u.get("groups") or []),
            "last_login": u["last_login"].isoformat(timespec="seconds") if u["last_login"] else None}


def create_user(username: str, password: str, role: str = "engineer", name: str = "", groups: list | None = None) -> dict:
    username = (username or "").strip().lower()
    if not username or not username.replace(".", "").replace("_", "").replace("-", "").isalnum():
        raise AuthError("The user name may only have letters, digits, . _ -", 400)
    if role not in ROLES:
        raise AuthError(f"Role must be one of {', '.join(ROLES)}.", 400)
    _check_new_password(password)
    with db.engine().begin() as conn:
        if conn.execute(select(db.users.c.id).where(db.users.c.username == username)).first():
            raise AuthError(f"User '{username}' already exists.", 400)
        gl = _groups(groups)
        uid = conn.execute(db.users.insert().values(username=username, name=name.strip(), password_hash=hash_password(password), role=role,
                                                     active=True, groups=gl)).inserted_primary_key[0]
        log(conn, "user", uid, "created", {"username": username, "role": role, "name": name.strip(), "groups": gl})
    return get_user(uid)


def get_user(uid: int) -> dict:
    with db.engine().connect() as conn:
        u = conn.execute(select(db.users).where(db.users.c.id == uid)).mappings().first()
    if not u:
        raise AuthError(f"User {uid} does not exist.", 404)
    return _public(u)


def list_users() -> list[dict]:
    with db.engine().connect() as conn:
        return [_public(u) for u in conn.execute(select(db.users).order_by(db.users.c.username)).mappings()]


def update_user(uid: int, data: dict, by: dict) -> dict:
    vals = {}
    if "role" in data:
        if data["role"] not in ROLES:
            raise AuthError(f"Role must be one of {', '.join(ROLES)}.", 400)
        vals["role"] = data["role"]
    if "active" in data:
        vals["active"] = bool(data["active"])
    if "name" in data:
        vals["name"] = str(data["name"]).strip()
    if "groups" in data:
        vals["groups"] = _groups(data["groups"])
    if data.get("password"):
        _check_new_password(data["password"])
        vals["password_hash"] = hash_password(data["password"])
    with db.engine().begin() as conn:
        old = conn.execute(select(db.users).where(db.users.c.id == uid)).mappings().first()
        if not old:
            raise AuthError(f"User {uid} does not exist.", 404)
        new_role, new_active = vals.get("role", old["role"]), vals.get("active", old["active"])
        if old["role"] == "admin" and (new_role != "admin" or not new_active):
            others = conn.execute(select(db.users.c.id).where((db.users.c.role == "admin") & db.users.c.active & (db.users.c.id != uid))).first()
            if not others:
                raise AuthError("There must always be one active admin.", 400)
        if vals:
            conn.execute(db.users.update().where(db.users.c.id == uid).values(**vals))
            detail = {k: {"old": old[k], "new": v} for k, v in vals.items() if k != "password_hash" and (old[k] or ([] if k == "groups" else old[k])) != v}
            if "password_hash" in vals:
                detail["password"] = "changed"
            if detail:
                log(conn, "user", uid, "updated", {"username": old["username"], **detail})
        if "active" in vals and not vals["active"] or "password_hash" in vals:
            conn.execute(db.sessions.delete().where(db.sessions.c.user_id == uid))      # log the user out everywhere
    return get_user(uid)


# ---------- sessions ----------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login(username: str, password: str) -> tuple[str, dict]:
    username = (username or "").strip().lower()
    with db.engine().begin() as conn:
        u = conn.execute(select(db.users).where(db.users.c.username == username)).mappings().first()
        ok = u is not None and u["active"] and check_password(password or "", u["password_hash"])
        if u is None:
            check_password(password or "", "scrypt$00$00")              # similar timing for unknown users
        if not ok:
            raise AuthError("Wrong user name or password.", 401)
        token = secrets.token_urlsafe(32)
        conn.execute(db.sessions.insert().values(token_hash=_hash(token), user_id=u["id"], expires_at=datetime.utcnow() + timedelta(hours=SESSION_HOURS)))
        conn.execute(db.sessions.delete().where(db.sessions.c.expires_at < datetime.utcnow()))
        conn.execute(db.users.update().where(db.users.c.id == u["id"]).values(last_login=datetime.utcnow()))
    return token, _public(u)


def user_of(token: str | None) -> dict | None:
    if not token:
        return None
    with db.engine().connect() as conn:
        row = conn.execute(select(db.users, db.sessions.c.expires_at).join(db.sessions, db.sessions.c.user_id == db.users.c.id)
                           .where(db.sessions.c.token_hash == _hash(token))).mappings().first()
    if not row or not row["active"] or row["expires_at"] < datetime.utcnow():
        return None
    return _public(row)


def logout(token: str | None) -> None:
    if token:
        with db.engine().begin() as conn:
            conn.execute(db.sessions.delete().where(db.sessions.c.token_hash == _hash(token)))


def change_password(user: dict, old: str, new: str) -> None:
    with db.engine().connect() as conn:
        u = conn.execute(select(db.users).where(db.users.c.id == user["id"])).mappings().first()
    if not check_password(old or "", u["password_hash"]):
        raise AuthError("The old password is wrong.", 400)
    update_user(user["id"], {"password": new}, user)


def bootstrap_admin() -> str | None:
    """Server mode with no users yet: create the first admin from DTC_ADMIN_PASSWORD (user name DTC_ADMIN_USER, default admin)."""
    with db.engine().connect() as conn:
        if conn.execute(select(db.users.c.id).limit(1)).first():
            return None
    pw = os.environ.get("DTC_ADMIN_PASSWORD")
    if not pw:
        return None
    u = create_user(os.environ.get("DTC_ADMIN_USER", "admin"), pw, "admin", "Administrator")
    return u["username"]


def has_users() -> bool:
    with db.engine().connect() as conn:
        return conn.execute(select(db.users.c.id).limit(1)).first() is not None


def setup_first_admin(username: str, password: str, name: str = "") -> dict:
    """First start: create the first admin. Refused as soon as any user exists."""
    if has_users():
        raise AuthError("The first admin already exists. Log in instead.", 400)
    return create_user(username, password, "admin", name or "Administrator")


def reset_password(username: str, password: str) -> dict:
    """Command line (the PC owner): new password for a user, e.g. a forgotten admin password; the user is made active again."""
    with db.engine().connect() as conn:
        u = conn.execute(select(db.users).where(db.users.c.username == (username or "").strip().lower())).mappings().first()
    if not u:
        raise AuthError(f"User '{username}' does not exist.", 404)
    return update_user(u["id"], {"password": password, "active": True}, None)


# ---------- request rules ----------

def needs_login(path: str) -> bool:
    return not path.startswith(PUBLIC_PREFIXES)


def action_for(method: str, path: str) -> str | None:
    """The permission a request needs (None = any logged-in user)."""
    if method in ("GET", "HEAD", "OPTIONS"):
        if path.startswith("/api/admin/activity"):
            return "view_activity"
        if path.startswith("/api/admin/backups"):
            return "backups"
        return None
    if path in ("/api/auth/logout", "/api/auth/password") or path.startswith(CALC_PATHS) or path.startswith(BOT_PATHS):
        return None
    if path.startswith("/api/admin/backups"):
        return "backups"
    if method == "DELETE" and path.startswith("/api/projects/"):
        return "delete_project"
    if method == "DELETE" and path.startswith("/api/parts/") and path.count("/") == 3:
        return "delete_part"
    if path.startswith("/api/suppliers") or (path.startswith("/api/parts/") and "/suppliers" in path):
        return "manage_suppliers"
    if path.startswith(MASTER_PATHS):
        return "edit_master_data"
    if path == "/api/trace/save-default":
        return None                     # trace_edit checks edit_rates or edit_master_data, by what is corrected
    if path == "/api/rates/status":
        return None                     # rates.set_status checks edit_rates, and approve_rates for an approval
    if path.startswith(RATE_PATHS):
        return "edit_rates"
    return "change_data"


def allowed(user: dict, method: str, path: str) -> str | None:
    """None if allowed, else the reason."""
    if (path.startswith(ADMIN_PREFIXES) or path.startswith("/api/admin/permissions") and method != "GET") and not has_role("admin", user):
        return "Managing users and permissions needs the role 'admin'."
    action = action_for(method, path)
    if action and not has_role(min_role(action), user):
        return f"'{PERMISSIONS[action][1]}' needs the role '{min_role(action)}' or higher; you are '{user['role']}' (Admin → Permissions)."
    return None
