"""Server-mode tools (roadmap stage 17), run from the command line:

    python -m backend.app.server_tools create-user NAME --role user|head|admin [--groups plastic,die_casting,...] [--password ...]
    python -m backend.app.server_tools migrate-projects --from sqlite:///data/projects.sqlite --to postgresql+psycopg://user:pw@host/dtc
    python -m backend.app.server_tools check

migrate-projects copies every project table (projects, parts, revisions, costs, history, users, ...) into an EMPTY database and keeps the ids.
CAD files are not in the database: copy the storage folder (Master data → Register settings → storage_folder) to the shared location.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import create_engine, func, select, text

from . import auth, projects_db


def migrate(src_url: str, dst_url: str) -> dict:
    if src_url == dst_url:
        raise ValueError("The source and the target are the same database.")
    src = create_engine(src_url, future=True)
    dst = projects_db._engine(dst_url)                       # creates the tables, adds missing columns
    counts = {}
    with src.connect() as s, dst.begin() as d:
        for t in projects_db.meta.sorted_tables:
            if d.execute(select(func.count()).select_from(t)).scalar():
                raise ValueError(f"The target database is not empty (table {t.name} has rows). Use a new, empty database.")
        for t in projects_db.meta.sorted_tables:
            rows = [dict(r) for r in s.execute(select(t)).mappings()]
            if rows:
                d.execute(t.insert(), rows)
            counts[t.name] = len(rows)
        if dst.dialect.name == "postgresql":                 # keep the id counters in step with the copied ids
            for t in projects_db.meta.sorted_tables:
                if "id" in t.c and counts[t.name]:
                    d.execute(text(f"SELECT setval(pg_get_serial_sequence('{t.name}', 'id'), (SELECT max(id) FROM {t.name}))"))
    return counts


def check() -> dict:
    url = projects_db.database_url()
    eng = projects_db.engine()
    with eng.connect() as c:
        c.execute(text("SELECT 1"))
        n = c.execute(select(func.count()).select_from(projects_db.users)).scalar()
    return {"database": eng.dialect.name, "users": n, "server_mode": auth.server_mode(), "storage": str(__import__("backend.app.register_setup", fromlist=["x"]).storage_root())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="server_tools")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("create-user")
    u.add_argument("username")
    u.add_argument("--role", default="user", choices=auth.ROLES)
    u.add_argument("--groups", default="", help="role user: comma list of " + ", ".join(auth.GROUPS))
    u.add_argument("--name", default="")
    u.add_argument("--password")
    m = sub.add_parser("migrate-projects")
    m.add_argument("--from", dest="src", required=True)
    m.add_argument("--to", dest="dst", required=True)
    sub.add_parser("check")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "create-user":
            pw = a.password or getpass.getpass("Password: ")
            print(auth.create_user(a.username, pw, a.role, a.name, [g for g in a.groups.split(",") if g]))
        elif a.cmd == "migrate-projects":
            for k, v in migrate(a.src, a.dst).items():
                print(f"{k}: {v}")
        else:
            print(check())
    except (auth.AuthError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
