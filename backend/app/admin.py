"""Admin page (roadmap stage 22): activity log, backups, version and update reports.

Users & roles and Permissions live in auth.py; this module reads what happened and what is installed.

    activity    every history record (projects, parts, suppliers, users, permissions, master data saves) plus the
                rate approvals of the rate library, newest first, with filters and an Excel export
    backups     the backup ZIPs (backup_tools.backups_dir), make one now, download one
    about       installed version (DTC_Data\\version.json from the Windows kit, else git), the latest update reports
"""

from __future__ import annotations

import io
import json
import os
import subprocess
from contextlib import closing
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import and_, select

from . import backup_tools, rates
from . import projects_db as db
from .table_set import HEADER_FILL

ROOT = Path(__file__).resolve().parents[2]


class AdminError(ValueError):
    pass


def _labels(conn, rows) -> dict:
    """(entity, id) -> readable name: project / part / supplier code, user name."""
    want = {}
    for r in rows:
        want.setdefault(r["entity"], set()).add(r["entity_id"])
    out = {}
    for entity, table, col in (("project", db.projects, "code"), ("part", db.parts, "part_code"),
                               ("supplier", db.suppliers, "code"), ("user", db.users, "username"),
                               ("variant", db.variants, "code")):
        ids = want.get(entity)
        if ids:
            for i, v in conn.execute(select(table.c.id, table.c[col]).where(table.c.id.in_(ids))):
                out[(entity, i)] = v
    return out


def _summary(action: str, detail) -> str:
    if not isinstance(detail, dict):
        return str(detail or "")
    bits = []
    for k, v in detail.items():
        if isinstance(v, dict) and set(v) >= {"old", "new"}:
            bits.append(f"{k}: {v['old']!s} → {v['new']!s}")
        elif v not in (None, "", [], {}):
            bits.append(f"{k}: {v}")
    return "; ".join(bits)[:600]


def _rate_events(date_from: str, date_to: str) -> list[dict]:
    """Approvals in the rate library (it keeps approved_by / approved_date instead of history records)."""
    with closing(rates._connect()) as con:
        rows = con.execute("SELECT id, category, item, country, month, value, unit, approved_by, approved_date FROM rates "
                           "WHERE status = 'approved' AND approved_date IS NOT NULL AND approved_date != '' "
                           "AND COALESCE(origin, '') != 'seed'").fetchall()        # not the example seed of a fresh install
    out = []
    for r in rows:
        when = str(r["approved_date"])
        if (date_from and when < date_from) or (date_to and when[:10] > date_to):
            continue
        out.append({"id": f"rate-{r['id']}", "at": when, "user": r["approved_by"] or "", "entity": "rate", "entity_id": r["id"],
                    "name": f"{r['category']} / {r['item']}" + (f" · {r['country']}" if r["country"] else ""),
                    "action": "approved", "summary": f"{r['month']}: {r['value']:g} {r['unit'] or ''}".strip(), "detail": {}})
    return out


def activity(entity: str = "", user: str = "", q: str = "", date_from: str = "", date_to: str = "",
             limit: int = 200, offset: int = 0) -> dict:
    h = db.history
    cond = []
    if entity and entity != "rate":
        cond.append(h.c.entity == entity)
    if user:
        cond.append(h.c.user.ilike(f"%{user}%"))
    if date_from:
        cond.append(h.c.at >= datetime.fromisoformat(date_from))
    if date_to:
        cond.append(h.c.at < datetime.fromisoformat(date_to + "T23:59:59"))
    rows = []
    if entity != "rate":
        with db.engine().connect() as conn:
            recs = conn.execute(select(h).where(and_(*cond)) if cond else select(h)).mappings().all()
            names = _labels(conn, recs)
        for r in recs:
            d = r["detail"] or {}
            name = names.get((r["entity"], r["entity_id"])) or (d.get("code") or d.get("username") or d.get("table") or "") \
                if isinstance(d, dict) else ""
            rows.append({"id": r["id"], "at": r["at"].isoformat(timespec="seconds") if r["at"] else "", "user": r["user"] or "",
                         "entity": r["entity"], "entity_id": r["entity_id"], "name": name or "", "action": r["action"],
                         "summary": _summary(r["action"], d), "detail": d})
    if entity in ("", "rate"):
        rows += [e for e in _rate_events(date_from, date_to) if not user or user.lower() in e["user"].lower()]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in f"{r['name']} {r['action']} {r['summary']} {r['user']}".lower()]
    rows.sort(key=lambda r: (r["at"], r["id"] if isinstance(r["id"], int) else 0), reverse=True)
    return {"total": len(rows), "rows": rows[offset:offset + limit],
            "entities": sorted({"project", "part", "variant", "supplier", "user", "permissions", "master_data", "rate"} |
                               {r["entity"] for r in rows})}


def activity_excel(**filters) -> bytes:
    res = activity(**filters, limit=100000)
    wb = Workbook()
    ws = wb.active
    ws.title = "Activity log"
    cols = ["When", "Who", "What", "Which", "Action", "Details"]
    ws.append(cols)
    for r in res["rows"]:
        ws.append([r["at"].replace("T", " "), r["user"], r["entity"], r["name"], r["action"], r["summary"]])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEADER_FILL
    for col, w in zip("ABCDEF", (20, 18, 14, 22, 18, 90)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- backups ----------

def backups() -> dict:
    folder = backup_tools.backups_dir()
    files = sorted(folder.glob("*.zip"), key=lambda f: f.stat().st_mtime, reverse=True) if folder.exists() else []
    return {"folder": str(folder), "locations": {k: str(v) for k, v in backup_tools.locations().items()},
            "backups": [{"name": f.name, "size_mb": round(f.stat().st_size / 1e6, 2),
                         "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")} for f in files]}


def make_backup(label: str = "dtc-admin") -> dict:
    p = backup_tools.make_backup(label=label)
    with db.engine().begin() as conn:
        from . import auth
        auth.log(conn, "backup", 0, "created", {"file": p.name})
    return {"name": p.name, "size_mb": round(p.stat().st_size / 1e6, 2)}


def backup_file(name: str) -> Path:
    folder = backup_tools.backups_dir().resolve()
    p = (folder / name).resolve()
    if p.parent != folder or p.suffix.lower() != ".zip" or not p.exists():
        raise AdminError(f"There is no backup '{name}'.")
    return p


# ---------- version and update reports ----------

def about() -> dict:
    data = Path(os.environ["DTC_DATA_FOLDER"]) if os.environ.get("DTC_DATA_FOLDER") else None
    version = {}
    if data and (data / "version.json").exists():
        try:
            version = json.loads((data / "version.json").read_text(encoding="utf-8"))
        except ValueError:
            version = {}
    if not version and (ROOT / ".git").exists():
        r = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %cs %s"], capture_output=True, text=True)
        if r.returncode == 0:
            version = {"commit": r.stdout.strip(), "source": "git"}
    reports = []
    if data and (data / "logs").exists():
        for f in sorted((data / "logs").glob("*"), key=lambda f: f.stat().st_mtime, reverse=True)[:5]:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            reports.append({"name": f.name, "text": text[-6000:]})
    from . import auth
    release = (ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").exists() else ""
    return {"version": version, "release": release, "data_folder": str(data) if data else "", "logins": auth.server_mode(),
            "database": db.database_url().split(":", 1)[0], "update_reports": reports}
