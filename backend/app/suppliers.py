"""Supplier master and the suppliers of each part (quoted piece and tool price against our should-cost).

Rules
- A supplier code is unique. A blank code is generated from Register settings → supplier_code_pattern
  (e.g. SUP-{seq:04d}); the statuses come from Register settings → supplier_statuses.
- A part can have several suppliers (one main, the others alternates), each with its quoted piece price
  and tool price, currency, quote reference and date. The comparison with our should-cost (the part's
  stored part cost and tool cost, in INR) uses the approved forex of the quote month.
- Every change writes a history record (entity "supplier" or "part"), like the rest of the register.
"""

from __future__ import annotations

import io
import re
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import func, or_, select

from . import projects_db as db
from . import rates, register_setup
from .register import RegisterError, _log, _num, _plain, user
from .table_set import HEADER_FILL

FIELDS = ("code", "name", "country", "city", "address", "commodities", "contact_person", "email", "phone", "tax_id",
          "payment_terms", "currency", "status", "certifications", "quality_score", "delivery_score", "cost_score",
          "capacity", "audit_date", "notes")
SCORES = ("quality_score", "delivery_score", "cost_score")
LINK_FIELDS = ("role", "piece_price", "tool_price", "currency", "quote_ref", "quote_date", "notes")
ROLES = ("main", "alternate")


def settings() -> dict:
    s = register_setup.settings()
    return {"pattern": s.get("supplier_code_pattern") or "SUP-{seq:04d}",
            "statuses": [x.strip() for x in (s.get("supplier_statuses") or "approved,trial,blocked,inactive").split(",") if x.strip()]}


def _date(v, where):
    v = str(v or "").strip()
    if v:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise RegisterError(f"{where}: '{v}' must be a date like 2026-10-25.") from None
    return v


def _values(data: dict) -> dict:
    out = {}
    for k in FIELDS:
        if k not in data:
            continue
        v = data[k]
        if k in SCORES:
            n = _num(v, f"Supplier: {k.replace('_', ' ')}")
            if n is not None and n > 100:
                raise RegisterError(f"Supplier: {k.replace('_', ' ')} is a score from 0 to 100.")
            out[k] = n
        elif k == "audit_date":
            out[k] = _date(v, "Supplier: audit date")
        else:
            out[k] = str(v or "").strip()
    for k in ("code", "country", "currency"):
        if k in out:
            out[k] = out[k].upper()
    if "name" in out and not out["name"]:
        raise RegisterError("Supplier: name must not be empty.")
    if out.get("email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", out["email"]):
        raise RegisterError(f"Supplier: '{out['email']}' is not an e-mail address.")
    st = settings()["statuses"]
    if "status" in out:
        out["status"] = out["status"].lower() or st[0]
        if out["status"] not in st:
            raise RegisterError(f"Supplier: status must be one of {', '.join(st)} (Register settings → supplier_statuses).")
    return out


def next_code(conn) -> str:
    pattern = settings()["pattern"]
    seq = conn.execute(select(func.count()).select_from(db.suppliers)).scalar() + 1
    while True:
        try:
            code = pattern.format(seq=seq).upper()
        except (KeyError, IndexError, ValueError) as exc:
            raise RegisterError(f"Register settings: supplier_code_pattern '{pattern}' is not valid ({exc}). "
                                "Use {seq}, e.g. SUP-{seq:04d}.") from None
        if not conn.execute(select(db.suppliers.c.id).where(db.suppliers.c.code == code)).first():
            return code
        seq += 1


def create(data: dict) -> dict:
    vals = _values(data)
    if not vals.get("name"):
        raise RegisterError("Supplier: name must not be empty.")
    vals.setdefault("status", settings()["statuses"][0])
    with db.engine().begin() as conn:
        vals["code"] = vals.get("code") or next_code(conn)
        if conn.execute(select(db.suppliers.c.id).where(db.suppliers.c.code == vals["code"])).first():
            raise RegisterError(f"Supplier code '{vals['code']}' already exists.")
        sid = conn.execute(db.suppliers.insert().values(**vals, created_by=user())).inserted_primary_key[0]
        _log(conn, "supplier", sid, "created", {"code": vals["code"], "name": vals["name"]})
    return get(sid)


def update(sid: int, data: dict) -> dict:
    vals = _values(data)
    with db.engine().begin() as conn:
        old = conn.execute(select(db.suppliers).where(db.suppliers.c.id == sid)).mappings().first()
        if not old:
            raise RegisterError(f"Supplier {sid} does not exist.")
        if vals.get("code") and vals["code"] != old["code"] and conn.execute(
                select(db.suppliers.c.id).where(db.suppliers.c.code == vals["code"])).first():
            raise RegisterError(f"Supplier code '{vals['code']}' already exists.")
        if "code" in vals and not vals["code"]:
            vals.pop("code")
        changes = {k: {"old": old[k], "new": v} for k, v in vals.items() if old[k] != v and not (old[k] in (None, "") and v in (None, ""))}
        if changes:
            conn.execute(db.suppliers.update().where(db.suppliers.c.id == sid).values(**vals))
            _log(conn, "supplier", sid, "updated", changes)
            if "name" in changes:
                conn.execute(db.capex_items.update().where(db.capex_items.c.supplier_id == sid).values(supplier=vals["name"]))
    return get(sid)


def delete(sid: int) -> dict:
    with db.engine().begin() as conn:
        s = conn.execute(select(db.suppliers).where(db.suppliers.c.id == sid)).mappings().first()
        if not s:
            raise RegisterError(f"Supplier {sid} does not exist.")
        parts = conn.execute(select(func.count()).select_from(db.part_suppliers).where(db.part_suppliers.c.supplier_id == sid)).scalar()
        capex = conn.execute(select(func.count()).select_from(db.capex_items).where(db.capex_items.c.supplier_id == sid)).scalar()
        if parts or capex:
            raise RegisterError(f"Supplier {s['code']} is used by {parts} part(s) and {capex} CAPEX line(s). "
                                "Set its status to inactive instead, or remove those links first.")
        conn.execute(db.suppliers.delete().where(db.suppliers.c.id == sid))
        _log(conn, "supplier", sid, "deleted", {"code": s["code"], "name": s["name"]})
    return {"deleted": s["code"]}


def _rating(s: dict) -> float | None:
    xs = [s[k] for k in SCORES if s.get(k) is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def get(sid: int) -> dict:
    with db.engine().connect() as conn:
        s = conn.execute(select(db.suppliers).where(db.suppliers.c.id == sid)).mappings().first()
        if not s:
            raise RegisterError(f"Supplier {sid} does not exist.")
        ps = db.part_suppliers
        parts = conn.execute(select(ps, db.parts.c.part_code, db.parts.c.name.label("part_name"), db.projects.c.code.label("project"))
                             .join(db.parts, ps.c.part_id == db.parts.c.id).join(db.projects, db.parts.c.project_id == db.projects.c.id)
                             .where(ps.c.supplier_id == sid).order_by(db.parts.c.part_code)).mappings().all()
        hist = conn.execute(select(db.history).where((db.history.c.entity == "supplier") & (db.history.c.entity_id == sid))
                            .order_by(db.history.c.at.desc(), db.history.c.id.desc())).mappings().all()
    d = _plain(s)
    return d | {"rating": _rating(d), "parts": [_plain(p) for p in parts], "history": [_plain(h) for h in hist]}


def search(q: str = "", status: str = "", country: str = "", commodity: str = "") -> list[dict]:
    s = db.suppliers
    stmt = select(s)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(s.c.code.ilike(like), s.c.name.ilike(like), s.c.city.ilike(like), s.c.contact_person.ilike(like),
                              s.c.commodities.ilike(like), s.c.notes.ilike(like)))
    if status:
        stmt = stmt.where(s.c.status == status)
    if country:
        stmt = stmt.where(s.c.country == country.upper())
    if commodity:
        stmt = stmt.where(s.c.commodities.ilike(f"%{commodity}%"))
    with db.engine().connect() as conn:
        counts = dict(conn.execute(select(db.part_suppliers.c.supplier_id, func.count()).group_by(db.part_suppliers.c.supplier_id)).all())
        rows = conn.execute(stmt.order_by(s.c.code)).mappings().all()
    return [_plain(r) | {"rating": _rating(dict(r)), "part_count": counts.get(r["id"], 0)} for r in rows]


# ---------- suppliers of a part ----------

def _link_values(data: dict) -> dict:
    out = {}
    for k in LINK_FIELDS:
        if k not in data:
            continue
        v = data[k]
        if k in ("piece_price", "tool_price"):
            out[k] = _num(v, f"Quote: {k.replace('_', ' ')}")
        elif k == "quote_date":
            out[k] = _date(v, "Quote: date")
        else:
            out[k] = str(v or "").strip()
    if "role" in out:
        out["role"] = out["role"].lower() or "main"
        if out["role"] not in ROLES:
            raise RegisterError(f"Supplier role must be {' or '.join(ROLES)}.")
    if "currency" in out:
        out["currency"] = out["currency"].upper() or "INR"
    return out


def _to_inr(amount, currency: str, date: str):
    """(value in INR, forex rate or None, note). Uses the approved forex of the quote month (current month if no date)."""
    if amount is None:
        return None, None, ""
    if not currency or currency == "INR":
        return amount, 1.0, ""
    try:
        fx = rates.lookup("forex", currency, "", (date or "")[:7] or rates.current_month())["value"]
    except rates.RateMissing as exc:  # a missing forex rate: shown, not fatal
        return None, None, str(exc)
    return amount * fx, fx, ""


def _check_main(conn, part_id: int, link_id: int | None, role: str) -> None:
    if role != "main":
        return
    q = select(db.part_suppliers.c.id).where((db.part_suppliers.c.part_id == part_id) & (db.part_suppliers.c.role == "main"))
    if link_id:
        q = q.where(db.part_suppliers.c.id != link_id)
    for (other,) in conn.execute(q):
        conn.execute(db.part_suppliers.update().where(db.part_suppliers.c.id == other).values(role="alternate"))


def link(part_id: int, data: dict) -> dict:
    vals = _link_values(data)
    with db.engine().begin() as conn:
        if not conn.execute(select(db.parts.c.id).where(db.parts.c.id == part_id)).first():
            raise RegisterError(f"Part {part_id} does not exist.")
        sid = data.get("supplier_id")
        if not sid and data.get("supplier_code"):
            sid = conn.execute(select(db.suppliers.c.id).where(db.suppliers.c.code == str(data["supplier_code"]).strip().upper())).scalar()
        sup = conn.execute(select(db.suppliers).where(db.suppliers.c.id == sid)).mappings().first() if sid else None
        if not sup:
            raise RegisterError("Choose a supplier from the supplier master.")
        if conn.execute(select(db.part_suppliers.c.id).where((db.part_suppliers.c.part_id == part_id)
                                                              & (db.part_suppliers.c.supplier_id == sup["id"]))).first():
            raise RegisterError(f"{sup['code']} is already a supplier of this part. Edit its line instead.")
        has_main = conn.execute(select(db.part_suppliers.c.id).where((db.part_suppliers.c.part_id == part_id)
                                                                     & (db.part_suppliers.c.role == "main"))).first()
        vals.setdefault("role", "alternate" if has_main else "main")
        vals.setdefault("currency", sup["currency"] or "INR")
        _check_main(conn, part_id, None, vals["role"])
        conn.execute(db.part_suppliers.insert().values(part_id=part_id, supplier_id=sup["id"], created_by=user(), **vals))
        _log(conn, "part", part_id, "supplier_added", {"supplier": f"{sup['code']} {sup['name']}", **{k: v for k, v in vals.items() if v not in (None, "")}})
    return part_suppliers(part_id)


def update_link(part_id: int, link_id: int, data: dict) -> dict:
    vals = _link_values(data)
    with db.engine().begin() as conn:
        old = conn.execute(select(db.part_suppliers).where((db.part_suppliers.c.id == link_id) & (db.part_suppliers.c.part_id == part_id))).mappings().first()
        if not old:
            raise RegisterError("This supplier line does not exist.")
        changes = {k: {"old": old[k], "new": v} for k, v in vals.items() if old[k] != v and not (old[k] in (None, "") and v in (None, ""))}
        if changes:
            _check_main(conn, part_id, link_id, vals.get("role", old["role"]))
            conn.execute(db.part_suppliers.update().where(db.part_suppliers.c.id == link_id).values(**vals))
            code = conn.execute(select(db.suppliers.c.code).where(db.suppliers.c.id == old["supplier_id"])).scalar()
            _log(conn, "part", part_id, "supplier_changed", {"supplier": code, **changes})
    return part_suppliers(part_id)


def unlink(part_id: int, link_id: int) -> dict:
    with db.engine().begin() as conn:
        old = conn.execute(select(db.part_suppliers).where((db.part_suppliers.c.id == link_id) & (db.part_suppliers.c.part_id == part_id))).mappings().first()
        if not old:
            raise RegisterError("This supplier line does not exist.")
        conn.execute(db.part_suppliers.delete().where(db.part_suppliers.c.id == link_id))
        code = conn.execute(select(db.suppliers.c.code).where(db.suppliers.c.id == old["supplier_id"])).scalar()
        _log(conn, "part", part_id, "supplier_removed", {"supplier": code})
    return part_suppliers(part_id)


def part_suppliers(part_id: int) -> dict:
    """The part's suppliers with quotes in INR and the gap to our should-cost (stored part cost and tool cost)."""
    ps, s = db.part_suppliers, db.suppliers
    with db.engine().connect() as conn:
        p = conn.execute(select(db.parts.c.piece_cost_inr, db.parts.c.tool_cost_inr).where(db.parts.c.id == part_id)).mappings().first()
        if not p:
            raise RegisterError(f"Part {part_id} does not exist.")
        rows = conn.execute(select(ps, s.c.code, s.c.name, s.c.status, s.c.country.label("supplier_country"))
                            .join(s, ps.c.supplier_id == s.c.id).where(ps.c.part_id == part_id)
                            .order_by(ps.c.role.desc(), s.c.code)).mappings().all()
    out = []
    for r in rows:
        d = _plain(r)
        d["piece_price_inr"], d["forex"], note1 = _to_inr(r["piece_price"], r["currency"], r["quote_date"])
        d["tool_price_inr"], _, note2 = _to_inr(r["tool_price"], r["currency"], r["quote_date"])
        d["forex_note"] = note1 or note2
        for k, ref in (("piece", p["piece_cost_inr"]), ("tool", p["tool_cost_inr"])):
            q = d[f"{k}_price_inr"]
            d[f"{k}_gap_inr"] = q - ref if q is not None and ref else None
            d[f"{k}_gap_pct"] = round(100 * (q - ref) / ref, 1) if q is not None and ref else None
        out.append(d)
    return {"part_id": part_id, "should_cost": {"piece_inr": p["piece_cost_inr"], "tool_inr": p["tool_cost_inr"]}, "suppliers": out}


def to_excel() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Suppliers"
    cols = list(FIELDS) + ["rating", "part_count"]
    ws.append(cols)
    for r in search():
        ws.append([r.get(c) for c in cols])
    links = wb.create_sheet("Part quotes")
    lcols = ["supplier", "part_code", "project", "role", "piece_price", "tool_price", "currency", "quote_ref", "quote_date", "notes"]
    links.append(lcols)
    with db.engine().connect() as conn:
        for r in conn.execute(select(db.suppliers.c.code.label("supplier"), db.parts.c.part_code, db.projects.c.code.label("project"),
                                     *[db.part_suppliers.c[k] for k in LINK_FIELDS])
                              .join(db.suppliers, db.part_suppliers.c.supplier_id == db.suppliers.c.id)
                              .join(db.parts, db.part_suppliers.c.part_id == db.parts.c.id)
                              .join(db.projects, db.parts.c.project_id == db.projects.c.id)
                              .order_by(db.suppliers.c.code, db.parts.c.part_code)).mappings():
            links.append([r[c] for c in lcols])
    for sh in (ws, links):
        for c in sh[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = HEADER_FILL
        sh.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
