"""Setup tables of the costing database: what the rate engine calculates with.

    countries        country code, name and currency
    country_index    price level of each country against India (part materials, tool steels, processes);
                     used only to PROPOSE rates for countries that have none yet
    machines         technical data per machine (power, area, life, residual,
                     maintenance); prices and consumables are country rates
    labour_grades    skill levels (operator, toolmaker, ...)
    cost_formulas    every step of the MHR, labour-rate, raw-material (RM) and tool cost
                     calculation as a formula, per scope ("mhr", "labour",
                     "rm_plastic", "rm_die_casting", "rm_foundry", "rm_sheet_metal",
                     "tool_clamp", "tool")
    formula_inputs   where each formula variable comes from: a country rate
                     (category + item, "{machine}" / "{grade}" / "{material}" filled
                     in), a machine field, a Parameters row of the part's family, or
                     a value of the part itself (net weight, density, sheet blank, ...)

Changing these rows changes the calculation logic without touching code.
"""

from __future__ import annotations

from . import formula
from .table_set import TableSet, col

RM_FAMILIES = ("plastic", "die_casting", "foundry", "sheet_metal")
TOOL_SCOPES = ("tool_clamp", "tool")
SCOPES = ("mhr", "labour") + tuple(f"rm_{f}" for f in RM_FAMILIES) + TOOL_SCOPES + ("piece",)
SOURCES = ("rate", "machine", "parameter", "part", "tool", "piece")
MACHINE_FIELDS = ("power_kw", "load_factor_pct", "floor_area_m2", "life_years", "residual_pct",
                  "maintenance_pct", "tonnage_t", "length_mm", "width_mm")
RESULT_OF = ({"mhr": "Machine hour rate", "labour": "Labour rate"} | {f"rm_{f}": "Net RM cost per part" for f in RM_FAMILIES}
             | {"tool_clamp": "Clamp force for the try-out machine", "tool": "Tool cost per tool", "piece": "Part cost per piece"})
# Values worked out by the part cost engine (piece_cost.py) that the piece formulas can use (source = piece);
# the Insert moulding rules (Part register setup) can be used by their key as well.
PIECE_ITEMS = {
    "rm_cost": "Net RM cost per part: latest RM cost version of the current revision",
    "cycle_s": "Cycle time (s): typed on the part, else Parameters → cycle_time_s",
    "cavities": "Cavities per tool: typed, else the latest tool cost version",
    "mhr": "Machine hour rate of the machine the tool's clamp force selects (full MHR trace)",
    "labour_rate": "Labour rate of Parameters → operator_grade (full labour-rate trace)",
    "secondary_ops_pct": "Secondary operations as % of the process cost: typed, else Parameters",
    "insert_cost": "Σ insert quantity × insert price per piece (bought-out), in the producing country's currency",
    "inserts_per_part": "Moulded-in inserts per part",
    "tool_capex": "Tool CAPEX of the latest tool cost version, in the producing country's currency",
    "lifetime_volume": "Annual volume × programme years (parts over the tool's programme)",
    "total_weight_kg": "Part weight body + inserts (kg)",
}
# Values worked out by the tool cost engine that the tool formulas can use (source = tool).
TOOL_ITEMS = {
    "cavities": "Cavities per tool",
    "projected_area_cm2": "Projected area of one part (cm²)",
    "shot_weight_kg": "Net weight of one shot = cavities × part weight (kg)",
    "material_cost": "Tool steel: Σ BOM quantity × weight × steel rate of the tool country",
    "bought_out_cost": "Mould base and standard parts: Σ BOM quantity × catalogue price, converted to the tool country's currency",
    "process_cost": "Processes: Σ BOM quantity × hours × (MHR + operators × labour rate), or amount × rate per unit (design excluded)",
    "design_cost": "Design: Σ design hours × designers × designer labour rate",
    "tool_weight_kg": "Tool weight = mould base + made BOM elements (kg)",
    "trial_mhr": "MHR of the try-out machine (smallest machine whose tonnage takes the clamp force)",
    "trial_labour_per_h": "Try-out crew per hour = operators × labour rate (Tool processes → try-out row)",
    "warranty_on": "1 if warranty / spares are included for this tool, else 0",
    "tools_count": "Tools over the programme (Stage C), for the tool CAPEX",
}
# Values of the part itself an RM formula can use (source = part).
PART_ITEMS = {
    "net_weight_g": "Net part weight (g): CAD volume × material density (body only for insert-moulded parts)",
    "density_g_cm3": "Material density (g/cm³) from Master data → Materials",
    "thickness_mm": "Sheet thickness (mm): most common wall of the 3D model",
    "blank_length_mm": "Flat blank length (mm): estimated from the 3D model",
    "blank_width_mm": "Flat blank width (mm): estimated from the 3D model",
    "blanks_per_sheet": "Blanks per sheet: best straight-grid nesting of the blank on the usable sheet",
}
# Part values you may type over per part (the others are measured or worked out).
OVERRIDABLE_PART_ITEMS = ("thickness_mm", "blank_length_mm", "blank_width_mm")
# Variables the nesting search needs when a scope uses blanks_per_sheet.
NESTING_VARIABLES = ("sheet_length_mm", "sheet_width_mm", "gap_mm", "edge_mm", "blank_length_mm", "blank_width_mm")


class SetupError(ValueError):
    pass


TABLES = {
    "countries": {"title": "Countries", "unique": ("code",), "columns": [
        col("code", "Code"),
        col("name", "Country"),
        col("currency", "Currency"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "country_index": {"title": "Country rate index", "unique": ("country",), "columns": [
        col("country", "Country code"),
        col("material_index", "Part materials (India = 1)", "number"),
        col("tool_steel_index", "Tool steels (India = 1)", "number"),
        col("process_index", "Processes (India = 1)", "number"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "machines": {"title": "Machines", "unique": ("machine_id",), "columns": [
        col("machine_id", "Machine ID"),
        col("name", "Machine"),
        col("process", "Process"),
        col("power_kw", "Connected power (kW)", "number"),
        col("load_factor_pct", "Power load factor (%)", "number"),
        col("floor_area_m2", "Floor area (m²)", "number"),
        col("life_years", "Life (years)", "number"),
        col("residual_pct", "Residual value (%)", "number"),
        col("maintenance_pct", "Maintenance (% of price / yr)", "number"),
        col("tonnage_t", "Tonnage (t)", "number", required=False),
        col("length_mm", "Tie-bar / bed length (mm)", "number", required=False),
        col("width_mm", "Tie-bar / bed width (mm)", "number", required=False),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "labour_grades": {"title": "Labour grades", "unique": ("grade",), "columns": [
        col("grade", "Grade ID"),
        col("name", "Skill level"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "cost_formulas": {"title": "Cost formulas", "unique": ("scope", "name"), "columns": [
        col("scope", "Scope", "scope", SCOPES),
        col("name", "Name"),
        col("label", "Shown as"),
        col("formula", "Formula", "formula"),
        col("unit", "Unit"),
        col("is_result", "Final result", "bool"),
        col("description", "Description"),
    ]},
    "formula_inputs": {"title": "Formula inputs", "unique": ("scope", "variable"), "columns": [
        col("scope", "Scope", "scope", SCOPES),
        col("variable", "Variable"),
        col("label", "Shown as"),
        col("source", "Comes from", "source", SOURCES),
        col("category", "Rate category"),
        col("item", "Rate item / machine field"),
        col("is_money", "Money (convert currency)", "bool"),
        col("unit", "Unit"),
    ]},
}


def formula_order(rows: list[dict], inputs: set[str], where=lambda i: f"row {i}") -> list[dict]:
    """Formulas of one scope in calculation order; checks names and cycles."""
    by_name = {r["name"]: (i, r) for i, r in rows}
    order, state = [], {}

    def visit(name, chain):
        i, r = by_name[name]
        if state.get(name) == "done":
            return
        if state.get(name) == "busy":
            raise SetupError(f"Cost formulas {where(i)}: '{name}' depends on itself ({' → '.join(chain + [name])}).")
        state[name] = "busy"
        try:
            used = formula.names(r["formula"])
        except formula.FormulaError as exc:
            raise SetupError(f"Cost formulas {where(i)}, formula: {exc}") from None
        for n in used:
            if n in by_name:
                visit(n, chain + [name])
            elif n not in inputs:
                raise SetupError(f"Cost formulas {where(i)}, formula: unknown name '{n}'. Use a formula name of the "
                                 f"same scope or a variable from Formula inputs.")
        state[name] = "done"
        order.append(r)

    for name in by_name:
        visit(name, [])
    return order


def _check(clean: dict) -> None:
    for i, c in enumerate(clean["countries"], start=2):
        c["code"] = c["code"].upper()
        c["currency"] = c["currency"].upper()
        if len(c["currency"]) != 3:
            raise SetupError(f"Countries row {i}: currency must be a 3-letter code such as INR, USD, JPY.")
    codes = {c["code"] for c in clean["countries"]}
    for i, r in enumerate(clean["country_index"], start=2):
        r["country"] = r["country"].upper()
        if r["country"] not in codes:
            raise SetupError(f"Country rate index row {i}: country '{r['country']}' is not in Countries.")
        for k in ("material_index", "tool_steel_index", "process_index"):
            if r[k] <= 0:
                raise SetupError(f"Country rate index row {i}: {k} must be more than 0 (India = 1).")
    for i, r in enumerate(clean["formula_inputs"], start=2):
        if r["source"] == "rate" and not (r["category"] and r["item"]):
            raise SetupError(f"Formula inputs row {i}: a rate input needs a rate category and item.")
        if r["source"] == "machine" and r["item"] not in MACHINE_FIELDS:
            raise SetupError(f"Formula inputs row {i}: machine field must be one of {', '.join(MACHINE_FIELDS)}.")
        if r["scope"] == "piece" and r["source"] not in ("piece", "parameter", "rate"):
            raise SetupError(f"Formula inputs row {i}: scope piece takes sources piece, parameter and rate.")
        if r["source"] == "piece" and r["scope"] != "piece":
            raise SetupError(f"Formula inputs row {i}: source 'piece' is only for scope piece.")
        if r["source"] == "part" and not r["scope"].startswith("rm_"):
            raise SetupError(f"Formula inputs row {i}: source 'part' is only for the RM scopes (rm_...).")
        if r["source"] == "parameter" and not (r["scope"].startswith("rm_") or r["scope"] in TOOL_SCOPES + ("piece",)):
            raise SetupError(f"Formula inputs row {i}: source 'parameter' is only for the RM and tool scopes.")
        if r["source"] == "tool" and r["scope"] not in TOOL_SCOPES:
            raise SetupError(f"Formula inputs row {i}: source 'tool' is only for the tool scopes ({', '.join(TOOL_SCOPES)}).")
        if r["source"] == "tool" and r["item"] not in TOOL_ITEMS:
            raise SetupError(f"Formula inputs row {i}: tool value must be one of {', '.join(TOOL_ITEMS)}.")
        if r["source"] == "parameter" and not r["item"]:
            raise SetupError(f"Formula inputs row {i}: a parameter input needs the parameter name in 'item' "
                             "(a row of Master data → Parameters).")
        if r["source"] == "part" and r["item"] not in PART_ITEMS:
            raise SetupError(f"Formula inputs row {i}: part value must be one of {', '.join(PART_ITEMS)}.")
    for scope in SCOPES:
        rows = [r for r in clean["formula_inputs"] if r["scope"] == scope]
        if any(r["source"] == "part" and r["item"] == "blanks_per_sheet" for r in rows):
            have = {r["variable"] for r in rows}
            lack = [v for v in NESTING_VARIABLES if v not in have]
            if lack:
                raise SetupError(f"Formula inputs: scope '{scope}' uses blanks_per_sheet, so the nesting also needs "
                                 f"the variables {', '.join(lack)}.")
    for scope in SCOPES:
        rows = [(i, r) for i, r in enumerate(clean["cost_formulas"], start=2) if r["scope"] == scope]
        if not rows:
            continue
        results = [r for _, r in rows if r["is_result"]]
        if len(results) != 1:
            raise SetupError(f"Cost formulas: scope '{scope}' needs exactly one row marked 'Final result' "
                             f"(found {len(results)}).")
        inputs = {r["variable"] for r in clean["formula_inputs"] if r["scope"] == scope}
        clash = inputs & {r["name"] for _, r in rows}
        if clash:
            raise SetupError(f"Cost formulas: '{sorted(clash)[0]}' is both a formula and an input in scope '{scope}'.")
        order = formula_order(rows, inputs)
        env = {n: 1.0 for n in inputs}
        for r in order:
            try:
                env[r["name"]] = formula.evaluate(r["formula"], env)
            except formula.FormulaError as exc:
                i = next(i for i, x in rows if x is r)
                raise SetupError(f"Cost formulas row {i}, formula: {exc}") from None


def _help() -> list:
    return [
        ["Design to Cost — Countries, machines & formulas: help"], [],
        ["variable", "meaning"],
        ["Cost formulas", "One row per calculation step. A formula may use the scope's Formula inputs and the names "
                          "of other formulas in the same scope. Mark exactly one row per scope as the final result."],
        ["Formula inputs", "source = rate: the country rate with this category and item ({machine}, {grade} and "
                           "{material} are filled in). source = machine: a field of the Machines sheet. Money inputs "
                           "are converted to the producing country's currency with the forex rate of the month."],
        ["source = parameter", "RM scopes only: the Master data → Parameters row with this name for the part's family "
                               "(e.g. runner_pct). You can type over it per part; that is then traced as your input."],
        ["source = part", "RM scopes only: a value of the part: " + "; ".join(f"{k} = {v}" for k, v in PART_ITEMS.items())],
        ["RM scopes", "rm_plastic, rm_die_casting, rm_foundry, rm_sheet_metal: gross weight, yield, RM cost and scrap "
                      "credit. Units written with {cur} are money in the producing country's currency."],
        ["Tool scopes", "tool_clamp: clamp force that picks the try-out machine. tool: trial, design, overhead, profit, "
                        "packing, transport, warranty and the tool cost per tool, in the tool country's currency. "
                        "{material} is the part material (trial shots)."],
        ["source = tool", "Tool scopes only: a value of the tool cost engine: " + "; ".join(f"{k} = {v}" for k, v in TOOL_ITEMS.items())],
        ["source = piece", "Scope piece only: a value of the part cost engine: " + "; ".join(f"{k} = {v}" for k, v in PIECE_ITEMS.items())
                           + "; and any key of Part register setup → Insert moulding rules"],
        ["functions", "ceil, floor, round, min, max, abs, sqrt; 'a if condition else b'; and, or, not"],
    ]


SET = TableSet("Countries, machines & formulas", TABLES, error=SetupError, check=_check, help_sheet=_help)


def schema() -> dict:
    return SET.schema() | {"machine_fields": list(MACHINE_FIELDS), "part_items": PART_ITEMS, "tool_items": TOOL_ITEMS}


def tables() -> dict:
    return SET.read()


def write(data: dict) -> None:
    SET.write(data)


def to_excel() -> bytes:
    return SET.to_excel()


def from_excel(content: bytes) -> None:
    SET.from_excel(content)


def countries() -> dict:
    return {c["code"]: c for c in tables()["countries"]}
