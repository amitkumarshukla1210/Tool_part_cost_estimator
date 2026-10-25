"""Server mode (roadmap stage 17): logins, roles and who-did-what.

    DTC_MODE=server   every request needs a login (cookie session); without it (the default, "local") the app is single-user, no login
    roles             viewer    reads everything
                      engineer  + creates and changes projects, parts, costs, master data
                      approver  + approves rates (draft -> approved)
                      admin     + manages users
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

ROLES = ("viewer", "engineer", "approver", "admin")
COOKIE = "dtc_session"
SESSION_HOURS = 12
MIN_PASSWORD = 10
PUBLIC_PREFIXES = ("/login", "/static", "/theme", "/api/auth/login", "/api/server/health", "/favicon")
ADMIN_PREFIXES = ("/api/users",)

_user: contextvars.ContextVar = contextvars.ContextVar("dtc_user", default=None)


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


def server_mode() -> bool:
    return os.environ.get("DTC_MODE", "local").lower() == "server"


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
    """In server mode: the logged-in user must have at least this role. Local mode: always fine."""
    if server_mode() and not has_role(minimum):
        raise AuthError(f"This needs the role '{minimum}' (you are {current()['role'] if current() else 'not logged in'}).", 403)


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

def _public(u) -> dict:
    return {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"], "active": bool(u["active"]),
            "last_login": u["last_login"].isoformat(timespec="seconds") if u["last_login"] else None}


def create_user(username: str, password: str, role: str = "engineer", name: str = "") -> dict:
    username = (username or "").strip().lower()
    if not username or not username.replace(".", "").replace("_", "").replace("-", "").isalnum():
        raise AuthError("The user name may only have letters, digits, . _ -", 400)
    if role not in ROLES:
        raise AuthError(f"Role must be one of {', '.join(ROLES)}.", 400)
    _check_new_password(password)
    with db.engine().begin() as conn:
        if conn.execute(select(db.users.c.id).where(db.users.c.username == username)).first():
            raise AuthError(f"User '{username}' already exists.", 400)
        uid = conn.execute(db.users.insert().values(username=username, name=name.strip(), password_hash=hash_password(password), role=role,
                                                     active=True)).inserted_primary_key[0]
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


# ---------- request rules ----------

def needs_login(path: str) -> bool:
    return not path.startswith(PUBLIC_PREFIXES)


def allowed(user: dict, method: str, path: str) -> str | None:
    """None if allowed, else the reason."""
    if path.startswith(ADMIN_PREFIXES) and not has_role("admin", user):
        return "Managing users needs the role 'admin'."
    if method in ("GET", "HEAD", "OPTIONS"):
        return None
    if path in ("/api/auth/logout", "/api/auth/password"):
        return None
    if not has_role("engineer", user):
        return "Your role 'viewer' can read but not change anything."
    if method == "DELETE" and path.startswith("/api/projects/") and not has_role("admin", user):
        return "Deleting a project needs the role 'admin'."
    return None
