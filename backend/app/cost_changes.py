"""Cost change report of a project (roadmap stage 55): every part's cost now against the cost that was valid on a date.

    then     the latest stored part cost version made on or before the date (end of that day)
    now      the latest stored part cost version
    lines    the cost lines of the part cost, read from each version's own trace: the terms of the result formula, with every
             term that is itself only a sum of other steps (e.g. cost before profit) opened up. So the lines follow the
             Cost formulas of scope piece as they were when each version was made; nothing is listed here in code
    flag     |change| ≥ Parameters → all / cost_change_flag_pct (EXAMPLE): the row is highlighted and sorted first

Stored versions are never changed; the report only reads them. Parts of other tool groups are left out for a limited user.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sqlalchemy import and_, select

from . import master_data
from . import projects_db as db

SEED_PARAMETERS = {
    "cost_change_flag_pct": (5, "%", "EXAMPLE: part cost changes of at least this % (up or down) are highlighted in the project's "
                                     "cost change report (stage 55)"),
    "cost_change_lookback_days": (30, "days", "EXAMPLE: the cost change report compares with the part costs valid this many days "
                                              "ago unless you pick a date (stage 55)"),
}
_SUM = re.compile(r"\s*[A-Za-z_]\w*(\s*\+\s*[A-Za-z_]\w*)*\s*")


class ChangeError(ValueError):
    pass


def seed() -> int:
    """Add the report's Parameters rows that are missing (part type 'all'); existing rows are never changed."""
    sheets = {k: [dict(r) for r in v] for k, v in master_data.tables().items()}
    have = {(r["part_type"], r["parameter"]) for r in sheets["Parameters"]}
    add = [{"part_type": "all", "parameter": k, "value": v, "unit": u, "description": d}
           for k, (v, u, d) in SEED_PARAMETERS.items() if ("all", k) not in have]
    if add:
        sheets["Parameters"] += add
        master_data.write(sheets)
    return len(add)


def _param(name: str) -> float:
    v = master_data.parameters("all").get(name)
    if not isinstance(v, (int, float)) or v < 0:
        raise ChangeError(f"Master data → Parameters needs a number 'all / {name}' (the cost change report uses it).")
    return float(v)


def cost_lines(trace: dict) -> list[dict]:
    """[{name, label, value}] in the version's currency: the terms of the part cost formula, sums opened up."""
    nodes = trace.get("nodes") or {}
    root = nodes.get(trace.get("root") or "calc:piece_cost") or nodes.get("calc:piece_cost")
    if not root:
        return []
    out, seen = [], set()

    def visit(node: dict, name: str):
        if node["id"] in seen:
            return
        seen.add(node["id"])
        if node.get("kind") == "calculated" and _SUM.fullmatch(node.get("formula") or "") and node.get("inputs"):
            by_name = {i["name"]: i["node"] for i in node["inputs"]}
            for term in (t.strip() for t in node["formula"].split("+")):     # in the formula's own order
                if by_name.get(term) in nodes:
                    visit(nodes[by_name[term]], term)
            return
        out.append({"name": name, "label": node.get("label") or name, "value": float(node.get("value") or 0)})

    if root.get("kind") == "calculated" and _SUM.fullmatch(root.get("formula") or ""):
        visit(root, "piece_cost")
    return out


def _version(row) -> dict:
    fx = row["piece_cost_inr"] / row["piece_cost"] if row["piece_cost"] else 1.0
    return {"version": row["version"], "at": row["created_at"].isoformat(timespec="minutes"), "by": row["created_by"],
            "reason": row["reason"], "as_of": row["as_of"], "country": row["country"], "rev": row["rev"],
            "cost_inr": row["piece_cost_inr"],
            "lines": {x["name"]: x | {"inr": x["value"] * fx} for x in cost_lines(row["trace"] or {})}}


def report(project_id: int, since: str | None = None) -> dict:
    from . import scope
    flag = _param("cost_change_flag_pct")
    if since:
        try:
            day = date.fromisoformat(since)
        except ValueError:
            raise ChangeError("The date must be written as YYYY-MM-DD.") from None
    else:
        day = date.today() - timedelta(days=_param("cost_change_lookback_days"))
    cut = datetime.combine(day, datetime.max.time())
    with db.engine().connect() as conn:
        proj = conn.execute(select(db.projects).where(db.projects.c.id == project_id)).mappings().first()
        if not proj:
            raise ChangeError(f"Project {project_id} does not exist.")
        sv = scope.project_view(conn, project_id)
        parts = [p for p in conn.execute(select(db.parts.c.id, db.parts.c.part_code, db.parts.c.name).where(
                 and_(db.parts.c.project_id == project_id, db.parts.c.is_assembly.is_(False))).order_by(db.parts.c.part_code)).mappings()
                 if sv["visible"] is None or p["id"] in sv["visible"]]
        rows_by_part: dict[int, list] = {}
        if parts:
            for r in conn.execute(select(db.piece_costs).where(db.piece_costs.c.part_id.in_([p["id"] for p in parts]))
                                  .order_by(db.piece_costs.c.part_id, db.piece_costs.c.version)).mappings():
                rows_by_part.setdefault(r["part_id"], []).append(r)
    rows = []
    for p in parts:
        vs = rows_by_part.get(p["id"], [])
        row = {"part_id": p["id"], "part_code": p["part_code"], "name": p["name"], "then": None, "now": None,
               "delta_inr": None, "delta_pct": None, "flagged": False, "lines": []}
        if not vs:
            rows.append(row | {"status": "no_cost"})
            continue
        now = vs[-1]
        then = next((v for v in reversed(vs) if v["created_at"] <= cut), None)
        row["now"] = _version(now)
        if then is None:
            rows.append(row | {"status": "new"})
            continue
        row["then"] = _version(then)
        a, b = row["then"]["cost_inr"] or 0.0, row["now"]["cost_inr"] or 0.0
        row["delta_inr"] = b - a
        row["delta_pct"] = (b - a) / a * 100 if a else None
        row["flagged"] = row["delta_pct"] is not None and abs(row["delta_pct"]) >= flag
        names = list(row["now"]["lines"]) + [n for n in row["then"]["lines"] if n not in row["now"]["lines"]]
        for n in names:
            o, w = row["then"]["lines"].get(n), row["now"]["lines"].get(n)
            row["lines"].append({"name": n, "label": (w or o)["label"], "then_inr": o["inr"] if o else None,
                                 "now_inr": w["inr"] if w else None, "delta_inr": (w["inr"] if w else 0) - (o["inr"] if o else 0)})
        status = "unchanged" if then["version"] == now["version"] or abs(row["delta_inr"]) < 1e-9 else "changed"
        rows.append(row | {"status": status})
    order = {"changed": 1, "new": 2, "unchanged": 3, "no_cost": 4}
    rows.sort(key=lambda r: (not r["flagged"], order[r["status"]], -abs(r["delta_pct"] or 0), r["part_code"]))
    for r in rows:
        for v in (r["then"], r["now"]):
            if v:
                v.pop("lines")
    count = lambda s: sum(r["status"] == s for r in rows)  # noqa: E731
    return {"project": {"id": proj["id"], "code": proj["code"], "name": proj["name"]}, "since": day.isoformat(),
            "flag_pct": flag, "rows": rows,
            "totals": {"parts": len(rows), "changed": count("changed"), "flagged": sum(r["flagged"] for r in rows),
                       "new": count("new"), "unchanged": count("unchanged"), "no_cost": count("no_cost")},
            "scope": {"limited": sv["limited"], "note": sv["note"]}}
