"""Raw-material (RM) cost per part: gross weight, yield, RM cost and scrap credit, fully traced.

No number and no formula is written here. The steps are the Cost formulas of the
scope rm_<family> (Master data → Countries, machines & formulas) and their
variables are the Formula inputs of that scope:

    rate        the rate library: the latest APPROVED version up to the costing
                month, with {material} filled in (e.g. material / ABS / IN)
    parameter   Master data → Parameters of the part's family (runner %, yield %,
                sheet size, ...); can be typed over per part (traced as your input)
    part        the part itself: net weight, density, sheet thickness, flat blank,
                blanks per sheet

Only the sheet nesting is a search done in code: the best straight grid of the
blank on the usable sheet, both orientations tried. Its inputs come from master
data or the part, and it gives "blanks per sheet" to the formulas.

A missing material rate does not stop the calculation: weights are still worked
out, the rate is shown as missing and the result is marked as not priced.
"""

from __future__ import annotations

from . import costing_setup, master_data, rate_engine, rates
from .costing_setup import NESTING_VARIABLES, OVERRIDABLE_PART_ITEMS, RM_FAMILIES
from .trace import Trace

FAMILIES = RM_FAMILIES


class RMError(ValueError):
    pass


def scope(family: str) -> str:
    return f"rm_{family}"


def grid_fit(area_l: float, area_w: float, item_l: float, item_w: float, gap: float) -> dict:
    """Best straight-grid layout of a rectangle in an area, trying both orientations."""

    def count(il, iw):
        # n items need n × size + (n − 1) gaps
        return int((area_l + gap) // (il + gap)), int((area_w + gap) // (iw + gap))

    options = [count(item_l, item_w), count(item_w, item_l)]
    along, across = max(options, key=lambda o: o[0] * o[1])
    return {"along": along, "across": across, "per_sheet": along * across, "rotated": options.index((along, across)) == 1}


def _inputs(setup: dict, family: str) -> list[dict]:
    rows = [r for r in setup["formula_inputs"] if r["scope"] == scope(family)]
    if not rows:
        raise RMError(f"Master data has no RM formula inputs for {family} (scope {scope(family)} in "
                      "Countries, machines & formulas → Formula inputs).")
    return rows


def _parameter_row(family: str, name: str) -> dict | None:
    """The Parameters row for the family, else the 'all' row."""
    rows = master_data.tables()["Parameters"]
    return (next((r for r in rows if r["part_type"] == family and r["parameter"] == name), None)
            or next((r for r in rows if r["part_type"] == "all" and r["parameter"] == name), None))


def _material_value(family: str, material: str, name: str) -> float | None:
    """A parameter the material sets for itself (Materials column of the same name, not blank), else None."""
    if name not in master_data.MATERIAL_PARAMETERS or not material:
        return None
    row = next((r for r in master_data.tables()["Materials"] if r["part_type"] == family and r["material"] == material), None)
    v = (row or {}).get(name)
    return float(v) if isinstance(v, (int, float)) else None


# ---------- scrap reuse and scrap rate as % of the RM price (roadmap stage 49) ----------
# Moulding and casting: part of the scrap (gross - net: runner, sprue, biscuit, overflows, gating) goes back into the
# process; only the virgin material is bought, the scrap left is sold at the scrap rate - the fixed rate of the rate library,
# or a % of the RM price when that % is set (above 0). Both % come from the part (typed), else the material (Materials
# columns), else the family (Parameters). Starting values 0 % and 0 = the RM cost stays as before until you set yours.
SCRAP_REUSE_FAMILIES = ("plastic", "die_casting", "foundry", "eps", "blow")
SCRAP_PARAMETERS = [
    ("scrap_reuse_pct", 0, "% of scrap", "Share of the scrap (gross - net weight) used again in production (regrind / remelt); "
                                         "the rest is sold. A material can set its own (Materials), a part too (RM inputs)."),
    ("scrap_rate_pct_of_rm", 0, "% of RM rate", "Scrap selling rate as % of the virgin RM rate; 0 = use the fixed scrap rate of "
                                                "the rate library (material_scrap). A material can set its own, a part too."),
]
SCRAP_INPUTS = [("scrap_reuse_pct", "Scrap used again", "% of scrap"),
                ("scrap_rate_pct_of_rm", "Scrap rate as % of RM rate (0 = fixed rate)", "% of RM rate")]
SCRAP_FORMULAS = [
    ("reused_g", "Scrap used again", "returns_g * scrap_reuse_pct / 100", "g",
     "Scrap (gross - net) × share used again in production"),
    ("virgin_g", "Virgin material bought per part", "input_g - reused_g", "g", "Material used per part less the scrap used again"),
    ("sold_g", "Scrap left to sell", "returns_g - reused_g", "g", "Scrap not used again: sold at the scrap rate"),
    ("scrap_value", "Scrap selling rate", "material_rate * scrap_rate_pct_of_rm / 100 if scrap_rate_pct_of_rm > 0 else scrap_rate",
     "{cur}/kg", "% of the RM rate when that % is above 0, else the fixed scrap rate of the rate library"),
]
SCRAP_CHANGED = {   # formula rows that change, only when they still are as shipped before (yours stay)
    "rm_cost": ("input_g / 1000 * material_rate", "virgin_g / 1000 * material_rate", "RM cost (virgin material × rate)"),
    "scrap_credit": ("0 - returns_g / 1000 * scrap_rate", "0 - sold_g / 1000 * scrap_value", "Scrap credit (−) for the scrap sold"),
}


def seed_scrap_reuse() -> dict:
    """Add the stage-49 rows (Parameters, Formula inputs, Cost formulas) that are missing; change the RM cost and scrap
    credit formulas of the moulding / casting families only where they are still the shipped formula."""
    added = {"parameters": 0, "inputs": 0, "formulas": 0, "changed": 0}
    md = master_data.tables()
    data = {k: [dict(r) for r in v] for k, v in md.items()}
    have = {(r["part_type"], r["parameter"]) for r in data["Parameters"]}
    for fam in SCRAP_REUSE_FAMILIES:
        for name, value, unit, desc in SCRAP_PARAMETERS:
            if (fam, name) not in have:
                data["Parameters"].append({"part_type": fam, "parameter": name, "value": value, "unit": unit,
                                           "description": desc + " EXAMPLE: replace with your value."})
                added["parameters"] += 1
    if added["parameters"]:
        master_data.write(data)
    setup = costing_setup.tables()
    ins = {(r["scope"], r["variable"]) for r in setup["formula_inputs"]}
    fms = {(r["scope"], r["name"]): r for r in setup["cost_formulas"]}
    for fam in SCRAP_REUSE_FAMILIES:
        sc = scope(fam)
        for var, label, unit in SCRAP_INPUTS:
            if (sc, var) not in ins:
                setup["formula_inputs"].append({"scope": sc, "variable": var, "label": label, "source": "parameter", "category": "",
                                                "item": var, "is_money": False, "unit": unit})
                added["inputs"] += 1
        for name, label, formula, unit, desc in SCRAP_FORMULAS:
            if (sc, name) not in fms:
                setup["cost_formulas"].append({"scope": sc, "name": name, "label": label, "formula": formula, "unit": unit,
                                               "is_result": False, "description": desc})
                added["formulas"] += 1
        for name, (old, new, label) in SCRAP_CHANGED.items():
            r = fms.get((sc, name))
            if r and r["formula"].replace(" ", "") == old.replace(" ", ""):
                r["formula"], r["label"] = new, label
                added["changed"] += 1
    if added["inputs"] or added["formulas"] or added["changed"]:
        costing_setup.write(setup)
    return added


def overridable(family: str) -> list[dict]:
    """Inputs you may type over per part, with their master-data default (None for part values)."""
    if family not in FAMILIES:
        return []
    out = []
    for r in _inputs(costing_setup.tables(), family):
        if r["source"] == "parameter" or (r["source"] == "part" and r["item"] in OVERRIDABLE_PART_ITEMS):
            row = _parameter_row(family, r["item"]) if r["source"] == "parameter" else None
            out.append({"variable": r["variable"], "label": r["label"] or r["variable"],
                        "unit": r["unit"] or (row or {}).get("unit") or "", "source": r["source"],
                        "default": row["value"] if row else None})
    return out


def run(family: str, *, country: str, as_of: str | None = None, material: str = "", part: dict | None = None,
        given: dict | None = None, given_source: dict | None = None, trace: Trace | None = None) -> dict:
    """RM cost of one part.

    part:   item -> node id already in `trace` (e.g. "weight") or {"value", "unit", "label", "source"}
    given:  variable -> value typed by you; replaces that input whatever its source
    """
    if family not in FAMILIES:
        raise RMError(f"There are no RM formulas for '{family}'. RM is worked out for {', '.join(FAMILIES)}.")
    as_of = as_of or rates.current_month()
    setup = costing_setup.tables()
    countries = {c["code"]: c for c in setup["countries"]}
    if country not in countries:
        raise RMError(f"Country '{country}' is not in Master data → Countries.")
    cur = countries[country]["currency"]
    trace = trace or Trace(cur)
    trace.currency = cur
    part, given = part or {}, given or {}
    names, missing, deferred, inputs = {}, [], [], []

    for inp in _inputs(setup, family):
        var, label = inp["variable"], inp["label"] or inp["variable"]
        nid = f"in:{var}"
        if var in given and given[var] is not None:
            trace.add_input(nid, label, float(given[var]), inp["unit"], given_source or {"type": "user"},
                            money=bool(inp["is_money"]))
        elif inp["source"] == "rate":
            item = inp["item"].format(material=material, machine="", grade="")
            if "{material}" in inp["item"] and not material:
                msg = f"{label}: choose a material first."
                missing.append(msg)
                trace.add_input(nid, label, 0, inp["unit"], {"type": "missing", "note": msg}, money=bool(inp["is_money"]))
            else:
                try:
                    rate = rates.lookup(inp["category"], item, country, as_of)
                except rates.RateMissing as exc:
                    missing.append(str(exc))
                    trace.add_input(nid, label, 0, inp["unit"], {"type": "missing", "note": str(exc)},
                                    money=bool(inp["is_money"]))
                else:
                    trace.add_rate(nid, label, rate, money=bool(inp["is_money"]))
                    if inp["is_money"]:
                        try:
                            nid = rate_engine._convert(trace, nid, label, rate["currency"], cur, as_of)
                        except rates.RateMissing as exc:
                            raise RMError(str(exc)) from None
        elif inp["source"] == "parameter":
            own = _material_value(family, material, inp["item"])
            row = _parameter_row(family, inp["item"])
            if own is not None:                  # stage 49: the material's own value (Materials column of the same name)
                trace.add_input(nid, label, own, inp["unit"] or (row or {}).get("unit") or "",
                                {"type": "master", "sheet": "Materials", "row": f"{family} / {material} / {inp['item']}"})
            else:
                if row is None or not isinstance(row["value"], (int, float)):
                    raise RMError(f"{label}: Master data → Parameters has no number '{inp['item']}' for {family}.")
                trace.add_input(nid, label, row["value"], inp["unit"] or row["unit"] or "",
                                {"type": "master", "sheet": "Parameters", "row": f"{row['part_type']} / {inp['item']}"})
        elif inp["source"] == "part":
            if inp["item"] == "blanks_per_sheet":
                deferred.append((var, label))
                continue
            v = part.get(inp["item"])
            if v is None:
                raise RMError(f"{label}: not available for this part.")
            if isinstance(v, str):
                nid = v
            else:
                trace.add_input(nid, v.get("label") or label, v["value"], v.get("unit", inp["unit"]), v.get("source"))
        else:
            raise RMError(f"Formula input '{var}' of {scope(family)} has source '{inp['source']}', which RM cannot use.")
        names[var] = nid
        inputs.append(var)

    nesting = None
    for var, label in deferred:  # blanks per sheet, once sheet and blank sizes are known
        v = {k: trace.value(names[k]) for k in NESTING_VARIABLES}
        nesting = grid_fit(v["sheet_length_mm"] - 2 * v["edge_mm"], v["sheet_width_mm"] - 2 * v["edge_mm"],
                           v["blank_length_mm"], v["blank_width_mm"], v["gap_mm"])
        if nesting["per_sheet"] == 0:
            # large part: the bigger sheet / cut-to-length coil of Parameters (large_sheet_length_mm, large_sheet_width_mm)
            big = {k: _parameter_row(family, f"large_{k}") for k in ("sheet_length_mm", "sheet_width_mm")}
            if all(r and isinstance(r["value"], (int, float)) for r in big.values()):
                for k, r in big.items():
                    nid_ = f"in:{k}"
                    trace.add_input(nid_, f"{trace.nodes[names[k]]['label']} (large sheet: the blank does not fit the standard sheet)",
                                    r["value"], r["unit"] or "mm",
                                    {"type": "master", "sheet": "Parameters", "row": f"{family} / large_{k}"})
                    names[k] = nid_
                v = {k: trace.value(names[k]) for k in NESTING_VARIABLES}
                nesting = grid_fit(v["sheet_length_mm"] - 2 * v["edge_mm"], v["sheet_width_mm"] - 2 * v["edge_mm"],
                                   v["blank_length_mm"], v["blank_width_mm"], v["gap_mm"])
        if nesting["per_sheet"] == 0:
            raise RMError("The blank does not fit on the sheet, nor on the large sheet (Parameters → large_sheet_length_mm / "
                          "large_sheet_width_mm). Check blank and sheet sizes.")
        nid = f"in:{var}"
        trace.add_derived(
            nid, label, nesting["per_sheet"], "pcs",
            "best straight grid of blank_length_mm × blank_width_mm on the usable sheet "
            "(sheet_length_mm − 2 × edge_mm) × (sheet_width_mm − 2 × edge_mm), gap_mm between blanks, both orientations",
            {k: names[k] for k in NESTING_VARIABLES},
            description=f"{nesting['along']} × {nesting['across']} = {nesting['per_sheet']} blanks"
                        + (", blank turned 90°" if nesting["rotated"] else "") + ". Searched in code; inputs from master data.")
        names[var] = nid
        inputs.append(var)

    try:
        result, components, order = rate_engine.evaluate_scope(trace, setup, scope(family), names, cur, as_of)
    except rates.RateMissing as exc:
        raise RMError(str(exc)) from None
    except rate_engine.EngineError as exc:
        raise RMError(str(exc)) from None
    named = {r["name"]: trace.value(f"calc:{r['name']}") for r in order}
    out = trace.to_dict(result)
    out |= {"scope": scope(family), "family": family, "country": country, "currency": cur, "as_of": as_of,
            "material": material, "value": trace.value(result), "value_inr": trace.value("result:inr"),
            "components": components, "named": named, "missing": missing, "priced": not missing,
            "nesting": nesting,
            "inputs": [{"variable": v, "node": names[v]} for v in inputs],
            "steps": [{"name": r["name"], "node": f"calc:{r['name']}", "is_result": bool(r["is_result"])} for r in order]}
    return out
