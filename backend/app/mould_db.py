"""Mould / die tables in the costing database.

Holds the data that sizes a mould or die and builds its BOM:

    mould_bases     standard mould base / die holder sizes, plates, weight, cost
    tool_materials  core/cavity and plate steels, density, rate per kg
    bom_elements    BOM lines with formula rules for quantity, cost, weight, hours
    process_rates   machining and other process rates per hour (India values; other countries are in the rate library)
    process_unit_rates  heat treatment per kg, wire cut per cm², polishing per cm², painting per m², transport per kg, ...
    concept_rules   gate / runner / cooling / ejection / insert proposals (first rule that applies), and\n                    sizing_rules undercut_* thresholds for the concept analysis\n    simulation_rules  cooling / cycle, pressure / clamp formulas and map thresholds (roadmap stage 6)
    sizing_rules    walls and gaps that turn part size into insert size
    tool_processes  how each tool process is priced: machine hours (MHR + operators × labour rate), labour hours,
                    or a rate per unit (kg, cm², ...); its machine, labour grade, operators and cost group
    time_parameters removal rates, set-up hours and shares that the BOM hour / amount rules use

Every row has an is_example flag: seeded placeholder values are 1 until you
replace them. The whole database can be exported to Excel and imported back.
"""

from __future__ import annotations

from . import costing_db, formula
from .table_set import TableSet, col

DEFAULT_PATH = costing_db.DEFAULT_PATH
PART_TYPES = ("plastic", "die_casting", "foundry", "sheet_metal", "eps", "blow")
CATEGORIES = ("made", "bought_out", "process")
# What a process rate is charged per (the unit of the rate in the library is "<currency>/<basis>").
BASES = ("kg", "cm²", "mm", "m²", "unit")
# How a tool process is priced (tool cost engine, roadmap stage 4).
PRICING = ("machine_hour", "labour_hour", "unit")
# Concept rules (roadmap stage 5): one proposal per topic, the first rule that applies.
TOPICS = ("gate", "runner", "cooling", "ejection", "insert")
COST_GROUPS = ("cutting", "machining", "polishing", "treatment", "assembly", "design", "trial")
# Machine of the try-out process: the smallest moulding / die-casting machine whose tonnage takes the clamp force.
BY_TONNAGE = "by tonnage"


class MouldDbError(ValueError):
    pass


def path():
    return costing_db.path()


TABLES = {
    "mould_bases": {"title": "Mould bases", "unique": ("part_type", "series", "size_code"), "columns": [
        col("part_type", "Part type", "part_type", PART_TYPES),
        col("series", "Series"),
        col("size_code", "Size code"),
        col("length_mm", "Length (mm)", "number"),
        col("width_mm", "Width (mm)", "number"),
        col("max_insert_length_mm", "Insert pocket L (mm)", "number"),
        col("max_insert_width_mm", "Insert pocket W (mm)", "number"),
        col("a_plate_mm", "A plate (mm)", "number"),
        col("b_plate_mm", "B plate (mm)", "number"),
        col("clamp_plates_mm", "Clamp plates, each (mm)", "number"),
        col("support_plate_mm", "Support plate (mm)", "number"),
        col("spacer_block_mm", "Spacer blocks (mm)", "number"),
        col("ejector_plates_mm", "Ejector plates (mm)", "number"),
        col("stack_height_mm", "Stack height (mm)", "number"),
        col("weight_kg", "Weight (kg)", "number"),
        col("cost", "Cost", "number"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "tool_materials": {"title": "Tool materials", "unique": ("code",), "columns": [
        col("code", "Steel / material"),
        col("application", "Used for"),
        col("density_g_cm3", "Density (g/cm³)", "number"),
        col("rate_per_kg", "Rate / kg (India)", "number"),
        col("hardness", "Hardness"),
        col("make", "Make / mill (suggested)", required=False),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "bom_elements": {"title": "BOM elements", "unique": ("part_type", "element"), "columns": [
        col("part_type", "Part type", "part_type", PART_TYPES),
        col("element", "Element"),
        col("category", "Category", "category", CATEGORIES),
        col("quantity_rule", "Quantity rule", "formula"),
        col("unit_cost_rule", "Bought-out cost each (rule)", "formula"),
        col("material_code", "Material", "material"),
        col("weight_rule", "Weight each, kg (rule)", "formula"),
        col("process_code", "Process", "process"),
        col("hours_rule", "Hours each (rule)", "formula"),
        col("amount_rule", "Amount each, in the process unit (rule)", "formula", required=False),
        col("make", "Make (suggested brand / supplier)", required=False),
        col("std_part", "Standard part (default, code from Standard parts)", required=False),
        col("price_each_inr", "Price each, INR (default; replaces the calculated line)", "number", required=False),
        col("operations", "Sheet-metal dies: operations it belongs to (codes, comma-separated; blank = every die)", required=False),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    # Standard parts catalogue (roadmap stage 23): pick one on a BOM line; its price, currency and make are used.
    "standard_parts": {"title": "Standard parts", "unique": ("code",), "columns": [
        col("code", "Code"),
        col("part_number", "Part number (maker's catalogue no.)"),
        col("description", "Description"),
        col("element", "BOM element it fits (blank = any bought-out line)", required=False),
        col("make", "Make"),
        col("country", "Country of the price", required=False),
        col("currency", "Currency"),
        col("price", "Price each", "number"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    # Grade suggestion (roadmap stage 23): the first rule (lowest order) of an element that applies gives its steel grade.
    "grade_rules": {"title": "Grade rules", "unique": ("part_type", "element", "step"), "columns": [
        col("part_type", "Part type", "part_type", PART_TYPES),
        col("element", "BOM element"),
        col("step", "Order", "number"),
        col("condition", "Applies when (rule)", "formula"),
        col("material_contains", "Part material contains (comma-separated; blank = any)", required=False),
        col("material_code", "Suggested grade", "material"),
        col("reason", "Reason shown"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "process_rates": {"title": "Process rates", "unique": ("code",), "columns": [
        col("code", "Process"),
        col("description", "Description"),
        col("rate_per_hour", "Rate / hour (India)", "number"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "process_unit_rates": {"title": "Process rates by unit", "unique": ("code",), "columns": [
        col("code", "Process"),
        col("description", "Description"),
        col("basis", "Charged per", "basis", BASES),
        col("india_rate", "Rate (India)", "number"),
        col("min_charge", "Minimum charge per job (India)", "number", required=False),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "sizing_rules": {"title": "Sizing rules", "unique": ("part_type", "parameter"), "columns": [
        col("part_type", "Part type", "part_type", PART_TYPES),
        col("parameter", "Parameter"),
        col("value", "Value", "number"),
        col("unit", "Unit"),
        col("description", "Description"),
        col("is_example", "Example", "bool"),
    ]},
    "concept_rules": {"title": "Concept rules", "unique": ("part_type", "topic", "step"), "columns": [
        col("part_type", "Part type", "part_type", PART_TYPES),
        col("topic", "Topic", "topic", TOPICS),
        col("step", "Order", "number"),
        col("condition", "Applies when (rule)", "formula"),
        col("proposal", "Proposal"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "simulation_rules": {"title": "Simulation rules", "unique": ("part_type", "name"), "columns": [
        col("part_type", "Part type", "part_type", PART_TYPES),
        col("step", "Order", "number"),
        col("name", "Name"),
        col("formula", "Formula", "formula"),
        col("unit", "Unit"),
        col("label", "Meaning"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "sheet_materials": {"title": "Sheet materials", "unique": ("material",), "columns": [
        col("material", "Material (Materials sheet)"),
        col("shear_mpa", "Shear strength (MPa)", "number"),
        col("tensile_mpa", "Tensile strength (MPa)", "number"),
        col("yield_mpa", "Yield strength (MPa)", "number"),
        col("e_gpa", "Young's modulus (GPa)", "number"),
        col("min_bend_r_factor", "Min inside bend radius (× thickness)", "number"),
        col("min_hole_factor", "Min hole diameter (× thickness)", "number"),
        col("ldr", "Limiting drawing ratio", "number"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "sheet_operations": {"title": "Sheet operations", "unique": ("code",), "columns": [
        col("seq", "Order", "number"),
        col("code", "Code"),
        col("name", "Operation"),
        col("condition", "Applies when (rule)", "formula"),
        col("force_t", "Force, tonnes (rule)", "formula"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "sheet_rules": {"title": "Sheet rules", "unique": ("name",), "columns": [
        col("step", "Order", "number"),
        col("name", "Name"),
        col("formula", "Formula", "formula"),
        col("unit", "Unit"),
        col("label", "Meaning"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "sheet_checks": {"title": "Sheet checks", "unique": ("name",), "columns": [
        col("name", "Check"),
        col("condition", "Problem when (rule)", "formula"),
        col("message", "Message ({name} fills in a value)"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "strip_rules": {"title": "Strip rules", "unique": ("name",), "columns": [
        col("step", "Order", "number"),
        col("name", "Name"),
        col("formula", "Formula", "formula"),
        col("unit", "Unit"),
        col("label", "Meaning"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "hs_codes": {"title": "HS codes", "unique": ("scope", "part_type"), "columns": [
        col("scope", "Of", "scope_of", ("tool", "part")),
        col("part_type", "Part type", "part_type", PART_TYPES),
        col("hs_code", "HS code (duty and IGST rates use it)"),
        col("description", "Description"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "update_rules": {"title": "Update rules", "unique": ("category",), "columns": [
        col("category", "Rate category (rate library)"),
        col("series", "Index series"),
        col("enabled", "Propose each month", "bool"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "tool_processes": {"title": "Tool processes", "unique": ("code",), "columns": [
        col("code", "Process"),
        col("pricing", "Priced by", "pricing", PRICING),
        col("cost_group", "Cost group", "cost_group", COST_GROUPS),
        col("machine_id", "Machine (Machines sheet)", required=False),
        col("labour_grade", "Labour grade", required=False),
        col("operators", "Operators per machine", "number", required=False),
        col("is_example", "Example", "bool"),
        col("notes", "Notes"),
    ]},
    "time_parameters": {"title": "Process time parameters", "unique": ("part_type", "parameter"), "columns": [
        col("part_type", "Part type", "part_type", PART_TYPES),
        col("parameter", "Parameter"),
        col("value", "Value", "number"),
        col("unit", "Unit"),
        col("description", "Description"),
        col("is_example", "Example", "bool"),
    ]},
}


def _check(clean: dict) -> None:
    from . import concept
    for i, r in enumerate(clean["concept_rules"], start=2):
        try:
            formula.evaluate(r["condition"], {k: 1.0 for k in concept.CONCEPT_VARS})
        except formula.FormulaError as exc:
            raise MouldDbError(f"Concept rules row {i}, condition: {exc}") from None
    from . import sheet_tools
    sheet_tools.validate(clean)
    senv = sheet_tools.sample_env() | {k: 1.0 for k in ("feed_len", "across_w", "part_area", "operation_count")}
    for r in sorted(clean["strip_rules"], key=lambda r: r["step"]):
        if not r["name"].isidentifier():
            raise MouldDbError(f"Strip rules '{r['name']}' must be one word (letters, digits and _).")
        try:
            senv[r["name"]] = float(formula.evaluate(r["formula"], senv))
        except formula.FormulaError as exc:
            raise MouldDbError(f"Strip rules ({r['name']}): {exc}") from None
        except ArithmeticError:
            senv[r["name"]] = 1.0
    from . import simulation
    for pt in PART_TYPES:
        env = simulation.sample_env(pt)
        for i, r in sorted(((i, r) for i, r in enumerate(clean["simulation_rules"], start=2) if r["part_type"] == pt),
                           key=lambda x: x[1]["step"]):
            if not r["name"].isidentifier():
                raise MouldDbError(f"Simulation rules row {i}: '{r['name']}' must be one word (letters, digits and _).")
            try:
                env[r["name"]] = formula.evaluate(r["formula"], env)
            except formula.FormulaError as exc:
                raise MouldDbError(f"Simulation rules row {i} ({r['name']}): {exc}") from None
            except (ArithmeticError, ValueError):
                env[r["name"]] = 1.0  # e.g. log of a sample value; checked again with the real part
    from . import costing_setup
    materials = {r["code"] for r in clean["tool_materials"]}
    unit_rates = {r["code"] for r in clean["process_unit_rates"]}
    tool_processes = {r["code"]: r for r in clean["tool_processes"]}
    try:
        setup = costing_setup.tables()
    except Exception:  # first set-up: the setup tables are checked when they are saved
        setup = None
    machines = {m["machine_id"] for m in setup["machines"]} if setup else None
    grades = {g["grade"] for g in setup["labour_grades"]} if setup else None
    for i, r in enumerate(clean["tool_processes"], start=2):
        where = f"Tool processes row {i}"
        if r["pricing"] == "unit" and r["code"] not in unit_rates:
            raise MouldDbError(f"{where}: a process priced per unit must be a row of Process rates by unit "
                               f"('{r['code']}' is not).")
        if r["pricing"] == "machine_hour":
            if not r["machine_id"]:
                raise MouldDbError(f"{where}: a process priced by machine hours needs a machine.")
            if r["machine_id"] == BY_TONNAGE and r["cost_group"] != "trial":
                raise MouldDbError(f"{where}: machine '{BY_TONNAGE}' is only for the try-out (cost group trial).")
            if machines is not None and r["machine_id"] not in machines | {BY_TONNAGE}:
                raise MouldDbError(f"{where}: machine '{r['machine_id']}' is not in Countries, machines & formulas → Machines.")
        if r["pricing"] in ("machine_hour", "labour_hour") and (r["operators"] or r["pricing"] == "labour_hour"):
            if not r["labour_grade"]:
                raise MouldDbError(f"{where}: give the labour grade of the operators.")
            if grades is not None and r["labour_grade"] not in grades:
                raise MouldDbError(f"{where}: labour grade '{r['labour_grade']}' is not in Labour grades.")
        if r["pricing"] == "labour_hour" and not r["operators"]:
            raise MouldDbError(f"{where}: a process priced by labour hours needs at least one person (operators).")
    reserved = set(formula.VARIABLE_HELP)
    for i, r in enumerate(clean["time_parameters"], start=2):
        if not r["parameter"].isidentifier():
            raise MouldDbError(f"Process time parameters row {i}: '{r['parameter']}' must be one word "
                               "(letters, digits and _), so the rules can use it.")
        if r["parameter"] in reserved:
            raise MouldDbError(f"Process time parameters row {i}: '{r['parameter']}' is already a rule variable.")
    env = formula.SAMPLE | {r["parameter"]: 1.0 for r in clean["time_parameters"]} \
        | {r["parameter"]: 1.0 for r in clean["sizing_rules"]} | {f"op_{r['code']}": 1.0 for r in clean["sheet_operations"]}
    for i, r in enumerate(clean["bom_elements"], start=2):
        where = f"BOM elements row {i}"
        if r["material_code"] and r["material_code"] not in materials:
            raise MouldDbError(f"{where}: material '{r['material_code']}' is not in Tool materials.")
        if r["process_code"]:
            tp = tool_processes.get(r["process_code"])
            if not tp:
                raise MouldDbError(f"{where}: process '{r['process_code']}' is not in Tool processes.")
            if tp["cost_group"] == "trial":
                raise MouldDbError(f"{where}: the try-out is costed by the tool formulas (trial cost), not as a BOM line.")
        for c in ("quantity_rule", "unit_cost_rule", "weight_rule", "hours_rule", "amount_rule"):
            if r[c] == "":
                r[c] = "0"
            try:
                formula.evaluate(r[c], env)
            except formula.FormulaError as exc:
                raise MouldDbError(f"{where}, {c}: {exc}") from None
    ops = {r["code"] for r in clean.get("sheet_operations", [])}
    for i, r in enumerate(clean["bom_elements"], start=2):
        bad = [c for c in (r.get("operations") or "").replace(" ", "").split(",") if c and c not in ops]
        if bad:
            raise MouldDbError(f"BOM elements row {i}: operation '{bad[0]}' is not in Sheet operations ({', '.join(sorted(ops))}).")
    std = {r["code"] for r in clean.get("standard_parts", [])}
    for i, r in enumerate(clean["bom_elements"], start=2):
        if r.get("std_part") and r["std_part"] not in std:
            raise MouldDbError(f"BOM elements row {i}: standard part '{r['std_part']}' is not in Standard parts.")
    elements = {(r["part_type"], r["element"]) for r in clean["bom_elements"]}
    for i, r in enumerate(clean.get("grade_rules", []), start=2):
        where = f"Grade rules row {i}"
        if (r["part_type"], r["element"]) not in elements:
            raise MouldDbError(f"{where}: '{r['element']}' is not a BOM element of {r['part_type']}.")
        if r["material_code"] not in materials:
            raise MouldDbError(f"{where}: grade '{r['material_code']}' is not in Tool materials.")
        try:
            formula.evaluate(r["condition"], env)
        except formula.FormulaError as exc:
            raise MouldDbError(f"{where}, condition: {exc}") from None
    for i, r in enumerate(clean["mould_bases"], start=2):
        if r["max_insert_length_mm"] > r["length_mm"] or r["max_insert_width_mm"] > r["width_mm"]:
            raise MouldDbError(f"Mould bases row {i}: insert pocket is larger than the mould base.")


def _help() -> list:
    rows = [["Design to Cost — Mould & die database: formula help"], [], ["variable", "meaning"]]
    rows += [[k, v] for k, v in formula.VARIABLE_HELP.items()]
    rows += [["(Process time parameters)", "every parameter name of the part type, e.g. cnc_rough_cm3_per_h"]]
    rows += [[], ["Tool processes", "machine_hour: hours × (MHR of the machine + operators × labour rate of the grade), "
                                    "country rates; labour_hour: hours × operators × labour rate; unit: amount × the "
                                    "process rate by unit, at least the minimum charge per job"]]
    rows += [[], ["functions", "ceil, floor, round, min, max, abs, sqrt; 'a if condition else b'; and, or, not"]]
    return rows


SET = TableSet("Mould & die database", TABLES, error=MouldDbError, check=_check, help_sheet=_help)


def schema() -> dict:
    return SET.schema() | {"formula_variables": formula.VARIABLE_HELP}


def tables() -> dict:
    return SET.read()


def write(data: dict) -> None:
    SET.write(data)


def to_excel() -> bytes:
    return SET.to_excel()


def from_excel(content: bytes) -> None:
    SET.from_excel(content)


def sizing_rules(part_type: str) -> dict:
    return {r["parameter"]: r for r in tables()["sizing_rules"] if r["part_type"] == part_type}


def time_parameters(part_type: str) -> dict:
    return {r["parameter"]: r for r in tables()["time_parameters"] if r["part_type"] == part_type}
