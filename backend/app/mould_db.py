"""Mould / die tables in the costing database.

Holds the data that sizes a mould or die and builds its BOM:

    mould_bases     standard mould base / die holder sizes, plates, weight, cost
    tool_materials  core/cavity and plate steels, density, rate per kg
    bom_elements    BOM lines with formula rules for quantity, cost, weight, hours
    process_rates   machining and other process rates per hour (India values; other countries are in the rate library)
    process_unit_rates  heat treatment per kg, wire cut per cm², polishing per cm², painting per m², transport per kg, ...
    sizing_rules    walls and gaps that turn part size into insert size

Every row has an is_example flag: seeded placeholder values are 1 until you
replace them. The whole database can be exported to Excel and imported back.
"""

from __future__ import annotations

from . import costing_db, formula
from .table_set import TableSet, col

DEFAULT_PATH = costing_db.DEFAULT_PATH
PART_TYPES = ("plastic", "die_casting", "foundry", "sheet_metal")
CATEGORIES = ("made", "bought_out", "process")
# What a process rate is charged per (the unit of the rate in the library is "<currency>/<basis>").
BASES = ("kg", "cm²", "mm", "m²", "unit")


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
}


def _check(clean: dict) -> None:
    materials = {r["code"] for r in clean["tool_materials"]}
    processes = {r["code"] for r in clean["process_rates"]}
    for i, r in enumerate(clean["bom_elements"], start=2):
        where = f"BOM elements row {i}"
        if r["material_code"] and r["material_code"] not in materials:
            raise MouldDbError(f"{where}: material '{r['material_code']}' is not in Tool materials.")
        if r["process_code"] and r["process_code"] not in processes:
            raise MouldDbError(f"{where}: process '{r['process_code']}' is not in Process rates.")
        for c in ("quantity_rule", "unit_cost_rule", "weight_rule", "hours_rule"):
            if r[c] == "":
                r[c] = "0"
            try:
                formula.check(r[c])
            except formula.FormulaError as exc:
                raise MouldDbError(f"{where}, {c}: {exc}") from None
    for i, r in enumerate(clean["mould_bases"], start=2):
        if r["max_insert_length_mm"] > r["length_mm"] or r["max_insert_width_mm"] > r["width_mm"]:
            raise MouldDbError(f"Mould bases row {i}: insert pocket is larger than the mould base.")


def _help() -> list:
    rows = [["Design to Cost — Mould & die database: formula help"], [], ["variable", "meaning"]]
    rows += [[k, v] for k, v in formula.VARIABLE_HELP.items()]
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
