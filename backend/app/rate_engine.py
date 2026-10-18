"""Machine hour rate (MHR) and labour rate per country, fully traced.

Nothing here holds a number. The steps are the `cost_formulas` rows of a
scope ("mhr" or "labour"); their variables are the `formula_inputs` rows,
which point at a country rate (category + item, with {machine} / {grade}
filled in) or a machine field. Rates are the latest APPROVED version up to
the costing month. Money rates are converted to the producing country's
currency with that month's forex rates, and the result is also given in INR.
"""

from __future__ import annotations

from . import costing_setup, rates
from .costing_setup import formula_order
from .trace import Trace


class EngineError(ValueError):
    pass


def fx_to_inr(trace: Trace, currency: str, as_of: str) -> str:
    """Node id holding INR per 1 unit of `currency`."""
    node = f"fx:{currency}"
    if node not in trace.nodes:
        if currency == rates.BASE_CURRENCY:
            trace.add_input(node, "INR per INR", 1, "INR/INR", {"type": "base", "note": "INR is the base currency."})
        else:
            trace.add_rate(node, f"Forex: INR per {currency}", rates.lookup("forex", currency, "", as_of))
    return node


def _convert(trace: Trace, node: str, label: str, from_cur: str, to_cur: str, as_of: str) -> str:
    """Add a conversion node when a money input is not in the country's currency."""
    if not from_cur or from_cur == to_cur:
        return node
    a, b = fx_to_inr(trace, from_cur, as_of), fx_to_inr(trace, to_cur, as_of)
    out = f"{node}:{to_cur}"
    unit = trace.nodes[node]["unit"].replace(from_cur, to_cur)
    trace.compute(out, f"{label} in {to_cur}", "value * fx_from / fx_to", unit, money=True,
                  description=f"Converted from {from_cur} to {to_cur} via INR forex rates of {as_of}.",
                  names={"value": node, "fx_from": a, "fx_to": b})
    return out


def _context(country: str, as_of: str):
    setup = costing_setup.tables()
    countries = {c["code"]: c for c in setup["countries"]}
    if country not in countries:
        raise EngineError(f"Country '{country}' is not in Master data → Countries.")
    return setup, countries[country]


def run(scope: str, country: str, as_of: str | None = None, machine: dict | None = None,
        grade: dict | None = None) -> dict:
    as_of = as_of or rates.current_month()
    setup, c = _context(country, as_of)
    cur = c["currency"]
    trace = Trace(cur)
    fill = {"machine": machine["machine_id"] if machine else "", "grade": grade["grade"] if grade else ""}

    names = {}
    for inp in (r for r in setup["formula_inputs"] if r["scope"] == scope):
        var = inp["variable"]
        nid = f"in:{var}"
        if inp["source"] == "machine":
            if not machine:
                raise EngineError(f"Input '{var}' needs a machine.")
            trace.add_input(nid, inp["label"] or var, machine[inp["item"]] or 0, inp["unit"], {
                "type": "machine", "sheet": "Machines", "machine_id": machine["machine_id"],
                "field": inp["item"], "is_example": machine["is_example"]})
        else:
            item = inp["item"].format(**fill)
            rate = rates.lookup(inp["category"], item, country, as_of)
            trace.add_rate(nid, inp["label"] or var, rate, money=bool(inp["is_money"]))
            if inp["is_money"]:
                nid = _convert(trace, nid, inp["label"] or var, rate["currency"], cur, as_of)
        names[var] = nid

    result, components, _ = evaluate_scope(trace, setup, scope, names, cur, as_of)
    out = trace.to_dict(result)
    out |= {"scope": scope, "country": country, "currency": cur, "as_of": as_of,
            "value": trace.value(result), "value_inr": trace.value("result:inr"), "components": components}
    return out


def evaluate_scope(trace: Trace, setup: dict, scope: str, names: dict, cur: str, as_of: str):
    """Run the cost formulas of a scope in order on the inputs in `names` (variable -> node id).

    Adds one node per formula plus the result in INR ("result:inr").
    Returns (result node, component nodes in sheet order, formula rows in calculation order).
    """
    rows = [(i, r) for i, r in enumerate(setup["cost_formulas"], start=2) if r["scope"] == scope]
    if not rows:
        raise EngineError(f"Master data has no cost formulas for '{scope}'.")
    result = result_unit = None
    order = formula_order(rows, set(names))
    for r in order:
        nid = f"calc:{r['name']}"
        # Units are written with {cur}, e.g. "{cur}/h"; those values are money.
        trace.compute(nid, r["label"] or r["name"], r["formula"], r["unit"].replace("{cur}", cur),
                      money="{cur}" in r["unit"], description=r["description"], names=names)
        names[r["name"]] = nid
        if r["is_result"]:
            result, result_unit = nid, r["unit"]

    # The result in INR as well (always shown next to the local currency).
    fx = fx_to_inr(trace, cur, as_of)
    trace.compute("result:inr", f"{trace.nodes[result]['label']} in INR", "value * fx",
                  result_unit.replace("{cur}", "INR"), money=True,
                  description=f"Converted with the INR per {cur} forex rate of {as_of}.",
                  names={"value": result, "fx": fx})
    return result, [names[r["name"]] for _, r in rows if not r["is_result"]], order


def mhr(machine_id: str, country: str, as_of: str | None = None) -> dict:
    machines = {m["machine_id"]: m for m in costing_setup.tables()["machines"]}
    if machine_id not in machines:
        raise EngineError(f"Machine '{machine_id}' is not in Master data → Machines.")
    return run("mhr", country, as_of, machine=machines[machine_id]) | {"machine": machines[machine_id]}


def labour_rate(grade: str, country: str, as_of: str | None = None) -> dict:
    grades = {g["grade"]: g for g in costing_setup.tables()["labour_grades"]}
    if grade not in grades:
        raise EngineError(f"Labour grade '{grade}' is not in Master data → Labour grades.")
    return run("labour", country, as_of, grade=grades[grade]) | {"grade": grades[grade]}


def overview(country: str, as_of: str | None = None) -> dict:
    """MHR of every machine and labour rate of every grade for one country.

    A missing approved rate does not break the page: that row carries the
    error and the others still calculate.
    """
    as_of = as_of or rates.current_month()
    setup, c = _context(country, as_of)

    def safe(fn, *a):
        try:
            return fn(*a)
        except (rates.RateError, EngineError, ValueError) as exc:
            return {"error": str(exc)}

    return {
        "country": c, "as_of": as_of,
        "machines": [{"machine": m, **safe(mhr, m["machine_id"], country, as_of)} for m in setup["machines"]],
        "labour": [{"grade": g, **safe(labour_rate, g["grade"], country, as_of)} for g in setup["labour_grades"]],
    }
