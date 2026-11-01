"""Progressive die vs stage dies, and tool / mould life in the part cost (roadmap stage 41).

    comparison   for a sheet-metal part: the live tool cost of both die types (progressive: one die, all stations on one
                 press; multi-stage: one die per operation, each on its own press), the same RM cost, and the Cost formulas
                 of scope "sheet_compare": hit time and operators per die type, process cost, rejection, overhead, profit,
                 packing, presses needed for the volume, tool life per die type, tools over the programme, tool CAPEX and
                 amortisation = die set cost ÷ parts per die set → part cost per piece of each die type.
    break-even   the same formulas over annual volumes from compare_volume_min_factor to compare_volume_max_factor × the
                 part's volume (compare_volume_points points); the volume where both part costs are equal is found by a
                 search (bisection), the one value here that is not a single formula.
    tool life    the part cost (scope piece) amortises one tool over the parts it makes in its life:
                 cost of one tool ÷ min(tool_life_shots × cavities, programme parts ÷ tools for capacity).

The comparison changes nothing stored: the part's own die type and part cost stay as they are. Every seeded row is EXAMPLE.
"""

from __future__ import annotations

import math

from . import costing_setup, formula, master_data, rate_engine, rates, register_setup
from .costing_setup import COMPARE_SCOPE
from .piece_cost import graft
from .trace import Trace

MODES = {"progressive": "Progressive die", "multi_stage": "Stage dies (multi-stage)"}

P = lambda v, u, d: (v, u, d)  # noqa: E731
SEED_PARAMETERS = {
    "sheet_metal": {
        "stage_hit_time_s": P(6, "s", "EXAMPLE: one press hit with manual loading per stage die (stage 41 comparison)"),
        "stage_operators_per_press": P(1, "operators", "EXAMPLE: operators per press for stage dies (manual load / unload)"),
        "progressive_spm": P(30, "strokes/min", "EXAMPLE: strokes per minute of a coil-fed progressive die"),
        "progressive_operators": P(0.5, "operators", "EXAMPLE: operators per progressive press (coil fed, one operator for two presses)"),
        "stage_die_life_strokes": P(1000000, "strokes", "EXAMPLE: life of a stage die before replacement (one stroke per part)"),
        "progressive_die_life_strokes": P(2000000, "strokes", "EXAMPLE: life of a progressive die before replacement (one stroke per part)"),
        "compare_volume_min_factor": P(0.1, "× volume", "EXAMPLE: break-even chart from this share of the part's annual volume"),
        "compare_volume_max_factor": P(10, "× volume", "EXAMPLE: break-even chart up to this multiple of the part's annual volume"),
        "compare_volume_points": P(9, "points", "EXAMPLE: volumes in the break-even table (spread evenly on a log scale)"),
    },
    "machined": {
        "tool_life_shots": P(500000, "parts", "EXAMPLE: fixture life in parts before it is replaced (tool amortisation, stage 41)"),
    },
}
FORMULAS = [  # scope, name, label, formula, unit, result, description
    ("piece", "tool_life_parts", "Parts per tool life", "tool_life_shots * cavities", "pcs", 0,
     "Tool / mould life in shots × cavities"),
    ("piece", "parts_per_tool", "Parts per tool", "min(tool_life_parts, lifetime_volume / tools_for_capacity)", "pcs", 0,
     "Parts one tool makes: its life, or its share of the programme when the programme ends first"),
    (COMPARE_SCOPE, "hit_s", "Time per part (one hit)", "60 / progressive_spm if progressive > 0 else stage_hit_time_s", "s", 0,
     "Progressive: one stroke per part; stage dies: each press hits once per part, side by side"),
    (COMPARE_SCOPE, "operators", "Operators", "presses * (progressive_operators if progressive > 0 else stage_operators_per_press)",
     "operators", 0, "Operators per press × presses"),
    (COMPARE_SCOPE, "parts_per_h", "Parts per hour", "3600 / hit_s", "pcs/h", 0, ""),
    (COMPARE_SCOPE, "process_cost", "Process cost", "(presses_mhr + operators * labour_rate) / parts_per_h", "{cur}", 0,
     "(Σ press MHR + operators × labour rate) ÷ parts per hour"),
    (COMPARE_SCOPE, "rejection_cost", "Rejection cost", "(rm_cost + process_cost) * rejection_pct / (100 - rejection_pct)", "{cur}", 0, ""),
    (COMPARE_SCOPE, "overhead", "Overhead", "process_cost * part_overhead_pct / 100", "{cur}", 0, "On conversion cost"),
    (COMPARE_SCOPE, "before_profit", "Cost before profit", "rm_cost + process_cost + rejection_cost + overhead", "{cur}", 0, ""),
    (COMPARE_SCOPE, "profit", "Profit", "before_profit * profit_pct / 100", "{cur}", 0, ""),
    (COMPARE_SCOPE, "packing", "Packing", "(before_profit + profit) * packing_pct / 100", "{cur}", 0, ""),
    (COMPARE_SCOPE, "ex_works", "Ex-works part cost without tool", "before_profit + profit + packing", "{cur}", 0, ""),
    (COMPARE_SCOPE, "programme_parts", "Parts over the programme", "annual_volume * programme_years", "pcs", 0, ""),
    (COMPARE_SCOPE, "available_h", "Hours one press line runs per year", "working_days * shifts_per_day * hours_per_shift", "h", 0, ""),
    (COMPARE_SCOPE, "lines_needed", "Press lines (die sets) needed for the volume",
     "max(1, ceil(annual_volume * hit_s / 3600 / (oee_pct / 100) / available_h))", "lines", 0, ""),
    (COMPARE_SCOPE, "tool_life", "Die life", "progressive_die_life_strokes if progressive > 0 else stage_die_life_strokes", "parts", 0,
     "One stroke per part"),
    (COMPARE_SCOPE, "tools_needed", "Die sets over the programme", "max(lines_needed, ceil(programme_parts / tool_life))", "sets", 0,
     "For capacity, or more when the dies wear out"),
    (COMPARE_SCOPE, "tool_capex", "Tool CAPEX", "tool_cost * tools_needed", "{cur}", 0, "Die set cost × die sets"),
    (COMPARE_SCOPE, "parts_per_tool", "Parts per die set", "min(tool_life, programme_parts / lines_needed)", "parts", 0,
     "Its life, or its share of the programme when the programme ends first"),
    (COMPARE_SCOPE, "amortisation", "Tool amortisation", "tool_cost / parts_per_tool", "{cur}", 0, "Die set cost ÷ parts per die set"),
    (COMPARE_SCOPE, "programme_cost", "Cost over the programme", "ex_works * programme_parts + tool_capex", "{cur}", 0,
     "Parts × ex-works cost + tool CAPEX (cash)"),
    (COMPARE_SCOPE, "piece_cost", "Part cost per piece", "ex_works + amortisation", "{cur}", 1, "Ex-works + tool amortisation"),
]
INPUTS = [  # scope, variable, label, source, category, item, money, unit
    ("piece", "tool_cost", "Cost of one tool", "piece", "", "tool_cost", 1, "{cur}"),
    ("piece", "tools_for_capacity", "Tools for capacity", "piece", "", "tools_for_capacity", 0, "tools"),
    ("piece", "tool_life_shots", "Tool / mould life", "parameter", "", "tool_life_shots", 0, "shots"),
] + [(COMPARE_SCOPE, k, label, "piece", "", k, money, unit) for k, label, money, unit in (
    ("rm_cost", "Net RM cost per part", 1, "{cur}"), ("progressive", "Progressive die (1) or stage dies (0)", 0, ""),
    ("presses", "Presses", 0, "presses"), ("presses_mhr", "Σ press MHR", 1, "{cur}/h"), ("labour_rate", "Labour rate", 1, "{cur}/h"),
    ("tool_cost", "Die set cost", 1, "{cur}"), ("annual_volume", "Annual volume", 0, "parts/yr"),
    ("programme_years", "Programme years", 0, "years"))] + [
    (COMPARE_SCOPE, k, label, "parameter", "", k, 0, unit) for k, label, unit in (
        ("stage_hit_time_s", "Hit time per stage die", "s"), ("stage_operators_per_press", "Operators per press, stage dies", "operators"),
        ("progressive_spm", "Strokes per minute, progressive", "strokes/min"),
        ("progressive_operators", "Operators per press, progressive", "operators"),
        ("stage_die_life_strokes", "Stage die life", "strokes"), ("progressive_die_life_strokes", "Progressive die life", "strokes"),
        ("oee_pct", "OEE", "%"), ("working_days", "Working days", "days/yr"), ("shifts_per_day", "Shifts per day", "shifts"),
        ("hours_per_shift", "Hours per shift", "h"), ("rejection_pct", "Rejection", "%"), ("part_overhead_pct", "Overhead", "%"),
        ("packing_pct", "Packing", "%"))] + [
    (COMPARE_SCOPE, "profit_pct", "Profit", "rate", "profit", "profit_pct", 0, "%"),
]
# The one shipped row stage 41 changes (approved): taken only while it is still the shipped text, like the update kit does.
AMORTISATION_OLD = "tool_capex / lifetime_volume"
AMORTISATION = {"formula": "tool_cost / parts_per_tool",
                "description": "Cost of one tool ÷ parts per tool (tool / mould life, stage 41); before: tool_capex / lifetime_volume"}


class CompareError(ValueError):
    pass


def seed() -> dict:
    """Add the stage-41 master data that is missing; existing rows are never changed, except the piece amortisation formula
    while it is still the shipped 'tool_capex / lifetime_volume' (approved change to life-based amortisation)."""
    out = {"parameters": 0, "formulas": 0, "inputs": 0, "amortisation": 0}
    sheets = {k: [dict(r) for r in v] for k, v in master_data.tables().items()}
    have = {(r["part_type"], r["parameter"]) for r in sheets["Parameters"]}
    for pt, rows in SEED_PARAMETERS.items():
        for k, (v, u, d) in rows.items():
            if (pt, k) not in have:
                sheets["Parameters"].append({"part_type": pt, "parameter": k, "value": v, "unit": u, "description": d})
                out["parameters"] += 1
    if out["parameters"]:
        master_data.write(sheets)
    s = costing_setup.tables()
    have = {(r["scope"], r["name"]) for r in s["cost_formulas"]}
    for scope, name, label, f, unit, res, desc in FORMULAS:
        if (scope, name) not in have:
            s["cost_formulas"].append({"scope": scope, "name": name, "label": label, "formula": f, "unit": unit, "is_result": bool(res),
                                       "description": desc})
            out["formulas"] += 1
    have = {(r["scope"], r["variable"]) for r in s["formula_inputs"]}
    for scope, var, label, source, cat, item, money, unit in INPUTS:
        if (scope, var) not in have:
            s["formula_inputs"].append({"scope": scope, "variable": var, "label": label, "source": source, "category": cat,
                                        "item": item, "is_money": bool(money), "unit": unit})
            out["inputs"] += 1
    for r in s["cost_formulas"]:
        if r["scope"] == "piece" and r["name"] == "amortisation" and r["formula"].replace(" ", "") == AMORTISATION_OLD.replace(" ", ""):
            r.update(AMORTISATION)
            out["amortisation"] = 1
    if out["formulas"] or out["inputs"] or out["amortisation"]:
        costing_setup.write(s)
    return out


# ---------- the comparison ----------

def _mode_trace(d: dict, rm: dict, mode: str, setup: dict, params: dict) -> dict:
    """Traced part cost of one die type; raises CompareError."""
    from . import register
    from .tool_cost import ToolCostError
    try:
        with register.sheet_mode(mode):
            tl = register._tool_compute(d["id"])
    except (register.ToolNotApplicable, ToolCostError, ValueError) as exc:
        raise CompareError(str(exc)) from None
    country, as_of, cur = rm["country"], rm["as_of"], rm["currency"]
    t = Trace(cur)
    reg = lambda note: {"type": "register", "note": note}  # noqa: E731
    presses = [x["press"] for x in tl["dies"]]
    lack = [x["name"] for x in tl["dies"] if not (x.get("press") or {}).get("machine_id")]
    if lack:
        raise CompareError(f"No press in Master data → Machines takes the force of {', '.join(lack)}.")
    grade = params.get("operator_grade")
    if not grade:
        raise CompareError("Master data → Parameters has no 'operator_grade' for sheet_metal.")
    try:
        mhrs = [graft(t, rate_engine.mhr(p["machine_id"], country, as_of), f"mhr{i}:") for i, p in enumerate(presses, start=1)]
        lab = graft(t, rate_engine.labour_rate(grade, country, as_of), "lab:")
    except (rate_engine.EngineError, rates.RateError) as exc:
        raise CompareError(str(exc)) from None
    t.compute("in:presses_mhr", "Σ press MHR", " + ".join(f"m{i}" for i in range(len(mhrs))), f"{cur}/h", money=True,
              description=", ".join(p["machine_id"] for p in presses), names={f"m{i}": n for i, n in enumerate(mhrs)})
    fx_cur = 1.0 if cur == "INR" else rates.lookup("forex", cur, "", as_of)["value"]
    volume, vnote = register._annual_volume(d)
    volume = volume or params.get("annual_volume")
    years = d["programme_life_years"] or params.get("programme_years")
    items = {
        "rm_cost": (rm["value"], cur, reg(f"Live RM cost of rev {d['rev']} ({rm['country']}, {rm['as_of']})"), True),
        "progressive": (1.0 if mode == "progressive" else 0.0, "", reg(MODES[mode]), False),
        "presses": (float(len(presses)), "presses", reg(", ".join(f"{x['name']}: {x['press']['machine_id']}" for x in tl["dies"])), False),
        "presses_mhr": "in:presses_mhr", "labour_rate": lab,
        "tool_cost": (tl["value_inr"] / fx_cur, cur, reg(f"Live tool cost of the {MODES[mode].lower()}: INR {tl['value_inr']:,.0f} "
                                                         f"({len(tl['dies'])} die(s), {tl['country']}, {tl['as_of']})"), True),
        "annual_volume": (volume, "parts/yr", reg(vnote), False),
        "programme_years": (years, "years", reg("Programme life of the part, else Parameters"), False),
    }
    names, missing = {}, []
    inputs = [r for r in setup["formula_inputs"] if r["scope"] == COMPARE_SCOPE]
    if not inputs:
        raise CompareError(f"Master data has no Formula inputs for scope '{COMPARE_SCOPE}'.")
    for inp in inputs:
        var, label, nid = inp["variable"], inp["label"] or inp["variable"], f"in:{inp['variable']}"
        if inp["source"] == "piece":
            v = items.get(inp["item"])
            if v is None:
                raise CompareError(f"{label}: '{inp['item']}' is not a comparison value ({', '.join(costing_setup.COMPARE_ITEMS)}).")
            if isinstance(v, str):
                nid = v
            else:
                if v[0] is None:
                    raise CompareError(f"{label}: no value (Master data → Parameters or the part).")
                t.add_input(nid, label, float(v[0]), v[1], v[2], money=v[3])
        elif inp["source"] == "parameter":
            if not isinstance(params.get(inp["item"]), (int, float)):
                raise CompareError(f"{label}: Master data → Parameters has no number '{inp['item']}' for sheet_metal.")
            t.add_input(nid, label, params[inp["item"]], inp["unit"], {"type": "master", "sheet": "Parameters", "row": f"sheet_metal / {inp['item']}"})
        elif inp["source"] == "rate":
            try:
                rate = rates.lookup(inp["category"], inp["item"], country, as_of)
            except rates.RateMissing as exc:
                missing.append(str(exc))
                t.add_input(nid, label, 0, inp["unit"], {"type": "missing", "note": str(exc)}, money=bool(inp["is_money"]))
            else:
                t.add_rate(nid, label, rate, money=bool(inp["is_money"]))
                if inp["is_money"]:
                    nid = rate_engine._convert(t, nid, label, rate["currency"], cur, as_of)
        else:
            raise CompareError(f"Formula input '{var}' of scope {COMPARE_SCOPE} has source '{inp['source']}', which it cannot use.")
        names[var] = nid
    try:
        result, _, order = rate_engine.evaluate_scope(t, setup, COMPARE_SCOPE, names, cur, as_of)
    except (rate_engine.EngineError, rates.RateMissing, formula.FormulaError) as exc:
        raise CompareError(str(exc)) from None
    except ZeroDivisionError:
        raise CompareError("A comparison formula divides by zero: check hit time, strokes per minute, die life and the volume.") from None
    out = t.to_dict(result)
    out |= {"mode": mode, "label": MODES[mode], "currency": cur, "value": t.value(result), "value_inr": t.value("result:inr"),
            "missing": missing, "dies": [{"name": x["name"], "press": x["press"]["machine_id"], "tonnage_t": x["press"].get("tonnage_t"),
                                          "force_t": x["force_t"]} for x in tl["dies"]],
            "named": {r["name"]: t.value(f"calc:{r['name']}") for r in order},
            "steps": [{"name": r["name"], "label": r["label"], "node": f"calc:{r['name']}", "unit": r["unit"].replace("{cur}", cur),
                       "is_result": bool(r["is_result"])} for r in order]}
    # what the volume sweep needs: every input value, then the formulas in order
    out["_env"] = {var: t.value(nid) for var, nid in names.items()}
    out["_order"] = order
    out["is_example"] = any(x.get("is_example") for x in out["rates_used"]) or bool(tl.get("example"))
    return out


def _at_volume(m: dict, volume: float) -> float:
    """The part cost of one die type at another annual volume: the same formulas on the same inputs."""
    env = dict(m["_env"], annual_volume=volume)
    for r in m["_order"]:
        env[r["name"]] = formula.evaluate(r["formula"], env)
    return next(env[r["name"]] for r in m["_order"] if r["is_result"])


def run(part_id: int) -> dict:
    from . import register
    from .rm_cost import RMError
    d = register.part_detail(part_id, with_rm=False)
    proc = register_setup.processes().get(d["process"]) or {}
    if d["is_assembly"] or proc.get("part_type") != "sheet_metal":
        raise CompareError("The progressive vs stage comparison is for sheet-metal parts.")
    try:
        rm = register._rm_compute(part_id)
    except (register.RegisterError, register.RMNotApplicable, RMError) as exc:
        raise CompareError(f"RM cost: {exc}") from None
    if rm["missing"]:
        raise CompareError("RM cost: " + " ".join(rm["missing"]))
    setup, params = costing_setup.tables(), master_data.parameters("sheet_metal")
    modes, errors = {}, {}
    for mode in MODES:
        try:
            modes[mode] = _mode_trace(d, rm, mode, setup, params)
        except CompareError as exc:
            errors[mode] = str(exc)
    try:
        sheet = register.sheet_tools_result(part_id)
    except (register.ToolNotApplicable, ValueError):
        sheet = {}
    out = {"part_id": part_id, "part_code": d["part_code"], "rev": d["rev"], "currency": rm["currency"], "country": rm["country"],
           "as_of": rm["as_of"], "current_mode": sheet.get("mode"), "recommended": sheet.get("recommended"),
           "formability": [p["message"] for p in sheet.get("problems", [])], "errors": errors, "modes": {}, "sweep": [], "break_even": []}
    for mode, m in modes.items():
        out["modes"][mode] = {k: v for k, v in m.items() if not k.startswith("_")}
    if len(modes) < 2:
        return out
    p, s = modes["progressive"], modes["multi_stage"]
    fx = p["value_inr"] / p["value"] if p["value"] else 1.0
    volume = p["_env"]["annual_volume"]
    lo, hi, n = (params.get(k) for k in ("compare_volume_min_factor", "compare_volume_max_factor", "compare_volume_points"))
    if not all(isinstance(x, (int, float)) and x > 0 for x in (lo, hi, n)) or hi <= lo:
        raise CompareError("Master data → Parameters (sheet_metal) needs compare_volume_min_factor < compare_volume_max_factor "
                           "and compare_volume_points (numbers above 0).")
    n = max(2, int(n))
    vols = sorted({max(1, round(volume * lo * (hi / lo) ** (i / (n - 1)))) for i in range(n)} | {round(volume)})
    diff = lambda v: _at_volume(p, v) - _at_volume(s, v)  # noqa: E731
    try:
        out["sweep"] = [{"annual_volume": v, "progressive_inr": _at_volume(p, v) * fx, "multi_stage_inr": _at_volume(s, v) * fx,
                         "is_part_volume": v == round(volume)} for v in vols]
        for a, b in zip(vols, vols[1:]):
            if (diff(a) > 0) != (diff(b) > 0):
                x0, x1 = float(a), float(b)
                for _ in range(60):
                    mid = (x0 + x1) / 2
                    x0, x1 = (mid, x1) if (diff(mid) > 0) == (diff(x0) > 0) else (x0, mid)
                v = math.ceil(x1)
                out["break_even"].append({"annual_volume": v, "piece_inr": _at_volume(p, v) * fx,
                                          "progressive_cheaper_above": diff(b) < 0})
    except ZeroDivisionError:
        raise CompareError("A comparison formula divides by zero at another volume: check the volume range parameters.") from None
    cheaper = "progressive" if p["value"] <= s["value"] else "multi_stage"
    other = "multi_stage" if cheaper == "progressive" else "progressive"
    out["cheaper"] = cheaper
    out["saving_per_piece_inr"] = modes[other]["value_inr"] - modes[cheaper]["value_inr"]
    out["saving_per_year_inr"] = out["saving_per_piece_inr"] * volume
    out["annual_volume"] = volume
    out["break_even_method"] = ("Search (bisection) for the annual volume where the part costs per piece of both die types are equal, "
                                f"between the volumes of the table ({lo:g}× to {hi:g}× the part's volume, Parameters → compare_volume_*)")
    out["is_example"] = any(m["is_example"] for m in modes.values())
    return out
