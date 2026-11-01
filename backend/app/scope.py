"""Data access by tool group (roadmap stage 30).

Each login ID has tool groups (part types: plastic, die casting, foundry, sheet metal, EPS, blow moulding) that the admin
sets on Admin → Users & roles (machined parts since stage 37 as the group Machining) and can change at any time (people change responsibility, the data stays where it is).

    viewer / engineer / approver   see and work on the parts whose process belongs to one of their groups, and the projects
                                   that hold such parts (or that they created, or that have no tool-group part yet)
    head (head of department)      sees and works on everything, like admin, without managing users
    admin                          everything
A user with no group ticked sees everything (as before this stage), so existing IDs keep working until the admin sets them.
Parts without a tool group (assemblies, bought-out, machined) are visible to everyone. Logins off (DTC_MODE=local): no limits.
"""

from __future__ import annotations

import re

from sqlalchemy import and_, func, not_, or_, select

from . import auth, register_setup
from . import projects_db as db

GROUPS = ("plastic", "die_casting", "foundry", "sheet_metal", "eps", "blow", "machined")
LABELS = {"plastic": "Plastic moulding", "die_casting": "Die casting", "foundry": "Foundry", "sheet_metal": "Sheet metal",
          "eps": "EPS (thermocole)", "blow": "Blow moulding", "machined": "Machining"}


def groups(user: dict | None = None) -> set | None:
    """The tool groups the user is limited to; None = no limit."""
    if not auth.server_mode():
        return None
    u = user or auth.current()
    if not u or auth.has_role("head", u):
        return None
    g = {x for x in (u.get("groups") or []) if x in GROUPS}
    return g or None


def _typed() -> dict:
    """process code -> tool group, for the processes that belong to a group."""
    return {code: p.get("part_type") for code, p in register_setup.processes().items() if p.get("part_type") in GROUPS}


def part_condition(g: set | None):
    """SQL condition on parts: visible to a user limited to the groups g (None = everything)."""
    if g is None:
        return None
    typed = _typed()
    mine = [c for c, pt in typed.items() if pt in g]
    return or_(db.parts.c.process.in_(mine), not_(db.parts.c.process.in_(list(typed))), db.parts.c.process.is_(None))


def project_condition(g: set | None):
    """SQL condition on projects: has one of my parts, was created by me, or has no tool-group part."""
    if g is None:
        return None
    typed = _typed()
    mine = [c for c, pt in typed.items() if pt in g]
    has_mine = select(db.parts.c.id).where(and_(db.parts.c.project_id == db.projects.c.id, db.parts.c.process.in_(mine))).exists()
    has_typed = select(db.parts.c.id).where(and_(db.parts.c.project_id == db.projects.c.id, db.parts.c.process.in_(list(typed)))).exists()
    u = auth.current() or {}
    me = [x for x in (u.get("username"), u.get("name")) if x]
    return or_(has_mine, not_(has_typed), db.projects.c.created_by.in_(me))


def part_ok(conn, part_id: int, g: set | None) -> bool:
    if g is None:
        return True
    row = conn.execute(select(db.parts.c.process).where(db.parts.c.id == part_id)).first()
    if not row:
        return True                     # the endpoint itself says "does not exist"
    pt = _typed().get(row[0])
    return pt is None or pt in g


def project_ok(conn, project_id: int, g: set | None) -> bool:
    if g is None:
        return True
    exists = conn.execute(select(db.projects.c.id).where(db.projects.c.id == project_id)).first()
    if not exists:
        return True
    return conn.execute(select(func.count()).select_from(db.projects).where(and_(db.projects.c.id == project_id, project_condition(g)))).scalar() > 0


def _names(g: set) -> str:
    return ", ".join(LABELS[x] for x in GROUPS if x in g)


def check_process(process: str | None) -> None:
    """A user limited to groups may only give a part a process of one of them."""
    g = groups()
    pt = _typed().get(process or "")
    if g is not None and pt is not None and pt not in g:
        raise auth.AuthError(f"Process '{process}' belongs to the tool group {LABELS[pt]}; your tool groups are {_names(g)} "
                             "(Admin → Users & roles).", 403)


PART_PATH = re.compile(r"^/api/parts/(\d+)(/|$)")
PROJECT_PATH = re.compile(r"^/api/projects/(\d+)(/|$)")
FILE_PATH = re.compile(r"^/api/files/(\d+)$")
VARIANT_PATH = re.compile(r"^/api/variants/(\d+)(/|$)")


def guard(path: str) -> str | None:
    """None if the logged-in user may open this part / project URL, else the reason."""
    g = groups()
    if g is None:
        return None
    m, p = PART_PATH.match(path), PROJECT_PATH.match(path)
    f, v = FILE_PATH.match(path), VARIANT_PATH.match(path)
    if not (m or p or f or v):
        return None
    with db.engine().connect() as conn:
        if f:                       # a 3D file or thumbnail of a part revision: the part's tool group decides
            r = db.revisions
            owners = conn.execute(select(r.c.part_id).where((r.c.file_id == int(f.group(1))) | (r.c.thumbnail_file_id == int(f.group(1))))).scalars().all()
            if owners and not any(part_ok(conn, pid, g) for pid in owners):
                return f"This file belongs to a part of a tool group that is not yours ({_names(g)})."
            return None
        if v:
            row = conn.execute(select(db.variants.c.project_id).where(db.variants.c.id == int(v.group(1)))).first()
            if row and not project_ok(conn, row[0], g):
                return f"This variant's project has no parts of your tool groups ({_names(g)})."
            return None
        if m and not part_ok(conn, int(m.group(1)), g):
            return f"This part belongs to a tool group that is not yours ({_names(g)}). The admin sets the tool groups on Admin → Users & roles."
        if p and not project_ok(conn, int(p.group(1)), g):
            return f"This project has no parts of your tool groups ({_names(g)})."
    return None


# ---------- project totals per tool group (stage 40) ----------

def project_view(conn, project_id: int) -> dict:
    """What the project dashboard / leader view of the logged-in user covers: {limited, visible (part ids or None = all),
    hidden (count), note}."""
    g = groups()
    if g is None:
        return {"limited": False, "visible": None, "hidden": 0, "note": ""}
    all_ids = set(conn.execute(select(db.parts.c.id).where(db.parts.c.project_id == project_id)).scalars())
    vis = set(conn.execute(select(db.parts.c.id).where(and_(db.parts.c.project_id == project_id, part_condition(g)))).scalars())
    hidden = len(all_ids - vis)
    note = (f"Your tool groups only ({_names(g)}): {hidden} part(s) of other tool groups are not counted in these figures."
            if hidden else f"Your tool groups: {_names(g)}.")
    return {"limited": True, "visible": vis, "hidden": hidden, "note": note}
