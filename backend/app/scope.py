"""Who sees which data (roadmap stage 26). Applies in server mode to the role 'user'; heads, admins and the local single-user mode see everything.

    part       a user sees a part when its process belongs to one of the user's groups (plastic, die_casting, foundry, sheet_metal, eps, blow),
               or when the part has no tool group (assembly, bought-out, machined) and the user created it
    project    a user sees a project he / she created, and every project that holds at least one visible part (with only the visible parts)
    design, variant, CAPEX line, file   follow their part or project
    harness / PCB extract               the user who made it (or any user who sees its project)
Groups are the admin's decision and can be changed at any time: the data stays where it is, who sees it changes (a part made by user 1 as
die casting is seen by whoever has die_casting now).
`guard` checks every request that names a part, project, variant, CAPEX line, design, file or extract; the list and roll-up queries use
`part_clause` / `project_clause` / `part_where`.
"""

from __future__ import annotations

import re

from sqlalchemy import and_, exists, or_, select

from . import auth, register_setup
from . import projects_db as db


def restricted() -> bool:
    """True when the current request comes from a role-'user' in server mode."""
    u = auth.current()
    return bool(auth.server_mode() and u and u["role"] == "user")


def me() -> str | None:
    u = auth.current()
    return u["username"] if u else None


def groups() -> set[str]:
    u = auth.current()
    return set(u["groups"]) if u else set(auth.GROUPS)


def deny(message: str):
    raise auth.AuthError(message, 403)


def _processes() -> tuple[list[str], list[str]]:
    procs = register_setup.processes()
    mine = groups()
    return ([c for c, p in procs.items() if p.get("part_type") in mine],
            [c for c, p in procs.items() if p.get("part_type") not in auth.GROUPS])


def part_clause():
    """SQL condition on db.parts for what the current user sees; None when the user sees everything."""
    if not restricted():
        return None
    in_group, no_group = _processes()
    return or_(db.parts.c.process.in_(in_group),
               and_(or_(db.parts.c.process.in_(no_group), db.parts.c.process.is_(None), db.parts.c.process == ""), db.parts.c.owner == me()))


def project_clause():
    if not restricted():
        return None
    pc = part_clause()
    return or_(db.projects.c.owner == me(), exists(select(db.parts.c.id).where(and_(db.parts.c.project_id == db.projects.c.id, pc))))


def part_where(project_id: int):
    """db.parts.c.project_id == project_id, narrowed to the parts the user sees."""
    pc = part_clause()
    base = db.parts.c.project_id == project_id
    return base if pc is None else and_(base, pc)


# ---------- single records ----------

def part_ok(conn, part_id: int) -> bool:
    pc = part_clause()
    if pc is None:
        return True
    if conn.execute(select(db.parts.c.id).where(db.parts.c.id == part_id)).first() is None:
        return True                                   # nothing there: the route answers "does not exist"
    return conn.execute(select(db.parts.c.id).where(and_(db.parts.c.id == part_id, pc))).first() is not None


def project_ok(conn, project_id: int) -> bool:
    pc = project_clause()
    if pc is None:
        return True
    if conn.execute(select(db.projects.c.id).where(db.projects.c.id == project_id)).first() is None:
        return True
    return conn.execute(select(db.projects.c.id).where(and_(db.projects.c.id == project_id, pc))).first() is not None


def check_new_part(process: str | None) -> None:
    """A user adds parts of his / her own groups (and parts without a tool group)."""
    if not restricted():
        return
    group = register_setup.processes().get(process or "", {}).get("part_type")
    if group in auth.GROUPS and group not in groups():
        deny(f"You are not responsible for '{group.replace('_', ' ')}' parts. Ask the admin to give you that group, or ask the head of department.")


def check_project_deletable(conn, project_id: int) -> None:
    """A user deletes a whole project only when every part in it is his / hers to see (nobody else's work is lost)."""
    if not restricted():
        return
    total = conn.execute(select(db.parts.c.id).where(db.parts.c.project_id == project_id)).all()
    mine = conn.execute(select(db.parts.c.id).where(and_(db.parts.c.project_id == project_id, part_clause()))).all()
    if len(total) != len(mine):
        deny("This project also holds parts of other groups. Delete your own parts, or ask the head of department or the admin to delete the project.")


def _id(path: str, pattern: str) -> int | None:
    m = re.match(pattern, path)
    return int(m.group(1)) if m else None


def guard(path: str) -> str | None:
    """None if the request may go on, else the reason (HTTP 403). Only for restricted users."""
    if not restricted() or not path.startswith("/api/"):
        return None
    with db.engine().connect() as conn:
        if (pid := _id(path, r"^/api/parts/(\d+)(?:/|$)")) is not None:
            return None if part_ok(conn, pid) else "This part belongs to a tool group you are not responsible for."
        if (pid := _id(path, r"^/api/projects/(\d+)(?:/|$)")) is not None:
            return None if project_ok(conn, pid) else "This project is not yours."
        if (vid := _id(path, r"^/api/variants/(\d+)(?:/|$)")) is not None:
            row = conn.execute(select(db.variants.c.project_id).where(db.variants.c.id == vid)).first()
            return None if row is None or project_ok(conn, row[0]) else "This variant is not yours."
        if (cid := _id(path, r"^/api/capex/(\d+)(?:/|$)")) is not None:
            row = conn.execute(select(db.capex_items.c.project_id).where(db.capex_items.c.id == cid)).first()
            return None if row is None or project_ok(conn, row[0]) else "This CAPEX line is not yours."
        if (did := _id(path, r"^/api/tool-designs/(\d+)(?:/|$)")) is not None:
            row = conn.execute(select(db.tool_designs.c.part_id).where(db.tool_designs.c.id == did)).first()
            return None if row is None or part_ok(conn, row[0]) else "This tool design belongs to a tool group you are not responsible for."
        if (eid := _id(path, r"^/api/bom-extracts/(\d+)(?:/|$)")) is not None:
            row = conn.execute(select(db.bom_extracts.c.owner, db.bom_extracts.c.project_id).where(db.bom_extracts.c.id == eid)).first()
            if row is None or row[0] == me() or (row[1] and project_ok(conn, row[1])):
                return None
            return "This harness / PCB extract is not yours."
        if (fid := _id(path, r"^/api/files/(\d+)$")) is not None:
            return None if file_ok(conn, fid) else "This file belongs to data you do not see."
    return None


def file_ok(conn, file_id: int) -> bool:
    for col, tbl in ((db.revisions.c.file_id, db.revisions), (db.revisions.c.thumbnail_file_id, db.revisions)):
        rows = conn.execute(select(db.revisions.c.part_id).where(col == file_id)).all()
        if rows:
            return any(part_ok(conn, r[0]) for r in rows)
    rows = conn.execute(select(db.tool_designs.c.part_id).join(db.tool_components, db.tool_components.c.design_id == db.tool_designs.c.id)
                        .where(db.tool_components.c.file_id == file_id)).all()
    if rows:
        return any(part_ok(conn, r[0]) for r in rows)
    ext = conn.execute(select(db.bom_extracts.c.owner).where(db.bom_extracts.c.file_id == file_id)).all()
    if ext:
        return any(r[0] == me() for r in ext)
    return not restricted()          # a file nothing refers to (the VTK result of a design …) is not handed out to users


def overview() -> dict:
    """Parts and projects per tool group and the users who see each group."""
    from collections import defaultdict
    from sqlalchemy import func
    procs = register_setup.processes()
    with db.engine().connect() as conn:
        by_proc = conn.execute(select(db.parts.c.process, db.parts.c.project_id, func.count()).group_by(db.parts.c.process, db.parts.c.project_id)).all()
        owners = dict(conn.execute(select(db.parts.c.owner, func.count()).group_by(db.parts.c.owner)).all())
        users = conn.execute(select(db.users)).mappings().all()
    parts, projects = defaultdict(int), defaultdict(set)
    for proc, pid, n in by_proc:
        g = procs.get(proc or "", {}).get("part_type")
        g = g if g in auth.GROUPS else "other"
        parts[g] += n
        projects[g].add(pid)
    who = {g: [u["username"] for u in users if u["active"] and (auth._role(u["role"]) != "user" or g in (u["groups"] or []))] for g in auth.GROUPS}
    return {"groups": [{"group": g, "parts": parts.get(g, 0), "projects": len(projects.get(g, ())), "seen_by": who.get(g, [])} for g in auth.GROUPS]
            + [{"group": "other", "parts": parts.get("other", 0), "projects": len(projects.get("other", ())), "seen_by": ["head and admin; the user who created the part"]}],
            "parts_by_creator": {(k or "(before users existed)"): v for k, v in owners.items()}}
