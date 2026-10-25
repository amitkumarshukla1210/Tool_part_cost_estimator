"""Editing from the traceability panel (roadmap stage 24): every traced value can be corrected.

    for this part only     a value or a formula of one node replaces the master-data / rate-library one in this part's
                           RM, tool or part cost (parts.trace_overrides); the node shows what it replaced; reset any time
    for the future         the source itself is corrected:
                             rate library   a new rate version of the same category / item / country, this month
                                            (approved when you may approve rates, else a draft for the approver)
                             master data    the row the value came from (Mould & die database, Countries, machines &
                                            formulas, Parameters), checked like a save on the Master data page
    new rows               e.g. a new mould base or die set (Mould bases) to pick for the part

Costs already stored never change by themselves: the part shows "master data changed" and you recalculate.
"""

from __future__ import annotations

from datetime import datetime

from . import auth, costing_setup, formula, master_data, mould_db, rates
from . import projects_db as db
from .register import RegisterError, _log, _num, compute_piece, compute_rm, compute_tool, part_detail, user

SCOPES = ("rm", "tool", "piece")
STORES = {
    "mould_db": (mould_db.tables, mould_db.write, "edit_master_data"),
    "costing_setup": (costing_setup.tables, costing_setup.write, "edit_master_data"),
    "master_data": (master_data.tables, master_data.write, "edit_master_data"),
}
NUMBER_COLUMNS_SKIP = ("formula", "quantity_rule", "unit_cost_rule", "weight_rule", "hours_rule", "amount_rule", "condition")


def _dry_run(part_id: int, scope: str) -> None:
    from . import register
    if scope == "rm":
        register._rm_compute(part_id)
    elif scope == "tool":
        register._tool_compute(part_id)
    else:
        register.piece_live(part_id)


def _store(part_id: int, overrides: dict) -> None:
    with db.engine().begin() as conn:
        conn.execute(db.parts.update().where(db.parts.c.id == part_id).values(trace_overrides=overrides))


def set_override(part_id: int, scope: str, node: str, value=None, formula_text: str | None = None, note: str = "") -> dict:
    """This part only: a value or a formula of one traced node. Checked by recalculating; stored as a new cost version."""
    if scope not in SCOPES:
        raise RegisterError(f"Scope must be one of {', '.join(SCOPES)}.")
    node = str(node or "").strip()
    if not node:
        raise RegisterError("Which value? (node)")
    entry = {"note": (note or "").strip() or "Changed for this part", "by": user(), "at": datetime.now().isoformat(timespec="seconds")}
    if formula_text is not None and str(formula_text).strip():
        try:
            formula.names(str(formula_text))
        except formula.FormulaError as exc:
            raise RegisterError(f"Formula: {exc}") from None
        entry["formula"] = str(formula_text).strip()
    else:
        try:
            entry["value"] = float(str(value).replace(",", "").strip())
        except ValueError:
            raise RegisterError(f"Value: '{value}' is not a number.") from None
    d = part_detail(part_id, with_rm=False)
    old = dict(d.get("trace_overrides") or {})
    new = {k: dict(v) for k, v in old.items()}
    new.setdefault(scope, {})[node] = entry
    _store(part_id, new)
    try:
        _dry_run(part_id, scope)
    except Exception as exc:  # a formula that does not work here: nothing is kept
        _store(part_id, old)
        raise RegisterError(f"Not saved: {exc}") from None
    with db.engine().begin() as conn:
        _log(conn, "part", part_id, "value_changed", {"calculation": scope, "value": node,
                                                       **{k: v for k, v in entry.items() if k in ("value", "formula", "note")}})
    return _recalculate(part_id, scope, f"value changed for this part: {node}")


def reset_override(part_id: int, scope: str, node: str) -> dict:
    d = part_detail(part_id, with_rm=False)
    ov = {k: dict(v) for k, v in (d.get("trace_overrides") or {}).items()}
    if node not in ov.get(scope, {}):
        raise RegisterError("This value has no change of yours to reset.")
    ov[scope].pop(node)
    _store(part_id, ov)
    with db.engine().begin() as conn:
        _log(conn, "part", part_id, "value_reset", {"calculation": scope, "value": node})
    return _recalculate(part_id, scope, f"value reset to master data: {node}")


def _recalculate(part_id: int, scope: str, reason: str) -> dict:
    fn = {"rm": compute_rm, "tool": compute_tool, "piece": compute_piece}[scope]
    try:
        res = fn(part_id, reason)
    except Exception as exc:
        res = {"stored": False, "message": str(exc)}
    # the part cost uses the RM and tool cost: keep it in step
    if scope != "piece":
        try:
            compute_piece(part_id, reason)
        except Exception:
            pass
    return res


def save_default(ref: dict | None = None, rate: dict | None = None, value=None, formula_text: str | None = None,
                 note: str = "") -> dict:
    """For the future: correct the source of a traced value (a master-data row, or a new rate-library version)."""
    if rate:
        auth.require_perm("edit_rates")
        v = _num(value, "Value", required=True)
        approve = auth.may("approve_rates") and (auth.server_mode() or bool(rates.settings()["approver_name"].strip()))
        new = rates.create({"category": rate["category"], "item": rate["item"], "country": rate.get("country", ""), "value": v,
                            "unit": rate.get("unit", ""), "currency": rate.get("currency", ""), "month": rates.current_month(),
                            "source": "corrected from the traceability panel",
                            "comment": (note or "").strip() or f"Corrected by {user()} (was {rate.get('value')})"}, approve=approve)
        return {"rate": new, "approved": new["status"] == "approved",
                "message": f"New version #{new['id']} of {rate['category']} / {rate['item']} {rate.get('country', '')}: {v:g} {rate.get('unit', '')}"
                           + ("" if new["status"] == "approved" else " as a DRAFT: an approver approves it on Rates → Rate review.")}
    if not ref or ref.get("store") not in STORES:
        raise RegisterError("This value does not come from master data or the rate library, so there is no source to correct.")
    read, write, perm = STORES[ref["store"]]
    auth.require_perm(perm)
    data = read()
    rows = data.get(ref["table"])
    if rows is None:
        raise RegisterError(f"Master data has no table '{ref['table']}'.")
    row = next((r for r in rows if all(str(r.get(k)) == str(v) for k, v in ref["match"].items())), None)
    if row is None:
        raise RegisterError(f"The master-data row {ref['match']} no longer exists in {ref['table']}.")
    col = ref["column"]
    old = row.get(col)
    if formula_text is not None and str(formula_text).strip():
        row[col] = str(formula_text).strip()
    elif col in NUMBER_COLUMNS_SKIP:
        row[col] = str(value)
    else:
        row[col] = _num(value, "Value", required=True)
    if "is_example" in row:
        row["is_example"] = False                           # your own value is no longer an EXAMPLE placeholder
    try:
        write(data)
    except Exception as exc:
        raise RegisterError(f"Not saved: {exc}") from None
    with db.engine().begin() as conn:
        _log(conn, "master_data", 0, "saved", {"table": f"{ref['store']}/{ref['table']}", "row": ref["match"],
                                                col: {"old": old, "new": row[col]}, "note": note or "from the traceability panel"})
    return {"message": f"Master data updated: {ref['table']} {', '.join(str(v) for v in ref['match'].values())} · {col} = {row[col]}. "
                       "Parts recalculated from now on use it (stored costs show 'master data changed').", "row": row}


def add_row(store: str, table: str, row: dict) -> dict:
    """A new master-data row from the traceability panel, e.g. a mould base or die set to pick for a part."""
    if store not in STORES:
        raise RegisterError(f"Unknown master data '{store}'.")
    read, write, perm = STORES[store]
    auth.require_perm(perm)
    data = read()
    if table not in data:
        raise RegisterError(f"Master data has no table '{table}'.")
    data[table].append(dict(row) | ({"is_example": False} if "is_example" in (data[table][0] if data[table] else {}) else {}))
    try:
        write(data)
    except Exception as exc:
        raise RegisterError(f"Not saved: {exc}") from None
    with db.engine().begin() as conn:
        _log(conn, "master_data", 0, "saved", {"table": f"{store}/{table}", "added": row})
    return {"message": f"Row added to {table}.", "row": row}
