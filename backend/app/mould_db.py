"""Mould / die master database (SQLite).

Holds the data that sizes a mould or die and builds its BOM:

    mould_bases     standard mould base / die holder sizes, plates, weight, cost
    tool_materials  core/cavity and plate steels, density, rate per kg
    bom_elements    BOM lines with formula rules for quantity, cost, weight, hours
    process_rates   machining and other process rates per hour
    sizing_rules    walls and gaps that turn part size into insert size

Every row has an is_example flag: seeded placeholder values are 1 until you
replace them. The whole database can be exported to Excel and imported back.
"""

from __future__ import annotations

import io
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from . import formula

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "master_data" / "mould_db.sqlite"
PART_TYPES = ("plastic", "die_casting", "foundry", "sheet_metal")

# table -> (sheet title, [(column, label, kind)], unique key columns)
# kinds: part_type, text, number, bool, formula, material, process, category
TABLES = {
    "mould_bases": ("Mould bases", [
        ("part_type", "Part type", "part_type"),
        ("series", "Series", "text"),
        ("size_code", "Size code", "text"),
        ("length_mm", "Length (mm)", "number"),
        ("width_mm", "Width (mm)", "number"),
        ("max_insert_length_mm", "Insert pocket L (mm)", "number"),
        ("max_insert_width_mm", "Insert pocket W (mm)", "number"),
        ("a_plate_mm", "A plate (mm)", "number"),
        ("b_plate_mm", "B plate (mm)", "number"),
        ("clamp_plates_mm", "Clamp plates, each (mm)", "number"),
        ("support_plate_mm", "Support plate (mm)", "number"),
        ("spacer_block_mm", "Spacer blocks (mm)", "number"),
        ("ejector_plates_mm", "Ejector plates (mm)", "number"),
        ("stack_height_mm", "Stack height (mm)", "number"),
        ("weight_kg", "Weight (kg)", "number"),
        ("cost", "Cost", "number"),
        ("is_example", "Example", "bool"),
        ("notes", "Notes", "text"),
    ], ("part_type", "series", "size_code")),
    "tool_materials": ("Tool materials", [
        ("code", "Steel / material", "text"),
        ("application", "Used for", "text"),
        ("density_g_cm3", "Density (g/cm³)", "number"),
        ("rate_per_kg", "Rate / kg", "number"),
        ("hardness", "Hardness", "text"),
        ("is_example", "Example", "bool"),
        ("notes", "Notes", "text"),
    ], ("code",)),
    "bom_elements": ("BOM elements", [
        ("part_type", "Part type", "part_type"),
        ("element", "Element", "text"),
        ("category", "Category", "category"),
        ("quantity_rule", "Quantity rule", "formula"),
        ("unit_cost_rule", "Bought-out cost each (rule)", "formula"),
        ("material_code", "Material", "material"),
        ("weight_rule", "Weight each, kg (rule)", "formula"),
        ("process_code", "Process", "process"),
        ("hours_rule", "Hours each (rule)", "formula"),
        ("is_example", "Example", "bool"),
        ("notes", "Notes", "text"),
    ], ("part_type", "element")),
    "process_rates": ("Process rates", [
        ("code", "Process", "text"),
        ("description", "Description", "text"),
        ("rate_per_hour", "Rate / hour", "number"),
        ("is_example", "Example", "bool"),
        ("notes", "Notes", "text"),
    ], ("code",)),
    "sizing_rules": ("Sizing rules", [
        ("part_type", "Part type", "part_type"),
        ("parameter", "Parameter", "text"),
        ("value", "Value", "number"),
        ("unit", "Unit", "text"),
        ("description", "Description", "text"),
        ("is_example", "Example", "bool"),
    ], ("part_type", "parameter")),
}
CATEGORIES = ("made", "bought_out", "process")
SQL_TYPE = {"number": "REAL", "bool": "INTEGER"}


class MouldDbError(ValueError):
    pass


def path() -> Path:
    return Path(os.environ.get("MOULD_DB_PATH", DEFAULT_PATH))


def _connect() -> sqlite3.Connection:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    for table, (_, cols, unique) in TABLES.items():
        defs = ", ".join(f"{c} {SQL_TYPE.get(kind, 'TEXT')}" for c, _, kind in cols)
        con.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY, {defs}, UNIQUE ({', '.join(unique)}))")
    return con


def schema() -> dict:
    return {
        "tables": {
            t: {"title": title, "columns": [{"key": c, "label": label, "kind": kind} for c, label, kind in cols]}
            for t, (title, cols, _) in TABLES.items()
        },
        "part_types": list(PART_TYPES),
        "categories": list(CATEGORIES),
        "formula_variables": formula.VARIABLE_HELP,
    }


def tables() -> dict:
    with closing(_connect()) as con:
        out = {}
        for table, (_, cols, _) in TABLES.items():
            names = ", ".join(c for c, _, _ in cols)
            rows = con.execute(f"SELECT {names} FROM {table} ORDER BY id").fetchall()
            out[table] = [_from_sql(dict(r), cols) for r in rows]
        return out


def _from_sql(row: dict, cols) -> dict:
    for c, _, kind in cols:
        v = row[c]
        if kind == "bool":
            row[c] = bool(v)
        elif kind == "number" and v is not None and float(v).is_integer():
            row[c] = int(v)
        elif v is None:
            row[c] = "" if kind != "number" else None
    return row


# ---------- validation ----------

def _number(value, where):
    if isinstance(value, bool):
        raise MouldDbError(f"{where}: '{value}' is not a number.")
    if value is None or str(value).strip() == "":
        raise MouldDbError(f"{where}: is empty.")
    try:
        n = float(str(value).replace(",", "").strip())
    except ValueError:
        raise MouldDbError(f"{where}: '{value}' is not a number.") from None
    if n < 0:
        raise MouldDbError(f"{where}: must not be negative.")
    return int(n) if n.is_integer() else n


def _bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "x", "example")
    return bool(value)


def validate(raw: dict) -> dict:
    """Clean and check every table; errors name the sheet and Excel row."""
    clean: dict = {}
    for table, (title, cols, unique) in TABLES.items():
        rows, seen = [], set()
        for i, row in enumerate(raw.get(table, []), start=2):
            where = f"{title} row {i}"
            out = {}
            for c, label, kind in cols:
                v = row.get(c)
                if kind == "number":
                    out[c] = _number(v, f"{where}, {label}")
                elif kind == "bool":
                    out[c] = _bool(v)
                else:
                    out[c] = "" if v is None else str(v).strip()
                if kind == "part_type":
                    out[c] = out[c].lower()
                    if out[c] not in PART_TYPES:
                        raise MouldDbError(f"{where}: part type '{out[c]}' must be one of {', '.join(PART_TYPES)}.")
            key = tuple(out[c] for c in unique)
            if not all(key):
                raise MouldDbError(f"{where}: {', '.join(unique)} must not be empty.")
            if key in seen:
                raise MouldDbError(f"{where}: {' / '.join(key)} is listed twice.")
            seen.add(key)
            rows.append(out)
        clean[table] = rows

    materials = {r["code"] for r in clean["tool_materials"]}
    processes = {r["code"] for r in clean["process_rates"]}
    for i, r in enumerate(clean["bom_elements"], start=2):
        where = f"BOM elements row {i}"
        if r["category"] not in CATEGORIES:
            raise MouldDbError(f"{where}: category must be one of {', '.join(CATEGORIES)}.")
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
    return clean


def write(data: dict) -> None:
    clean = validate(data)
    with closing(_connect()) as con, con:  # one transaction: all or nothing
        for table, (_, cols, _) in TABLES.items():
            names = [c for c, _, _ in cols]
            con.execute(f"DELETE FROM {table}")
            con.executemany(
                f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
                [[int(r[c]) if isinstance(r[c], bool) else r[c] for c in names] for r in clean[table]],
            )


# ---------- Excel ----------

# Design to Cost theme: table-head-dark and input-cell-bg
HEADER_FILL = PatternFill("solid", fgColor="0E1A2C")
EXAMPLE_FILL = PatternFill("solid", fgColor="FFF9DB")


def to_excel() -> bytes:
    data = tables()
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.title = "Design to Cost — Mould & die database"
    wb.properties.creator = "Design to Cost"
    for table, (title, cols, _) in TABLES.items():
        ws = wb.create_sheet(title)
        ws.append([c for c, _, _ in cols])
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = HEADER_FILL
        for r in data[table]:
            ws.append(["yes" if r[c] is True else "no" if r[c] is False else r[c] for c, _, _ in cols])
            if r.get("is_example"):
                for cell in ws[ws.max_row]:
                    cell.fill = EXAMPLE_FILL
        for i, (c, _, _) in enumerate(cols, start=1):
            width = max([len(c)] + [len(str(r[c])) for r in data[table]])
            ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 60)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
    ws = wb.create_sheet("Formula help")
    ws.append(["Design to Cost — Mould & die database: formula help"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    ws.append(["variable", "meaning"])
    for cell in ws[3]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
    for name, meaning in formula.VARIABLE_HELP.items():
        ws.append([name, meaning])
    ws.append([])
    ws.append(["functions", "ceil, floor, round, min, max, abs, sqrt; 'a if condition else b'; and, or, not"])
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 90
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def from_excel(content: bytes) -> None:
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise MouldDbError(f"Could not read the uploaded file as Excel (.xlsx): {exc}") from exc
    data = {}
    for table, (title, cols, _) in TABLES.items():
        if title not in wb.sheetnames:
            raise MouldDbError(f"The Excel file has no '{title}' sheet.")
        rows = list(wb[title].iter_rows(values_only=True))
        header = [str(h).strip() if h is not None else "" for h in rows[0]] if rows else []
        missing = [c for c, _, _ in cols if c not in header]
        if missing:
            raise MouldDbError(f"Sheet '{title}' is missing column(s): {', '.join(missing)}.")
        idx = {c: header.index(c) for c, _, _ in cols}
        data[table] = [
            {c: row[idx[c]] if idx[c] < len(row) else None for c, _, _ in cols}
            for row in rows[1:]
            if any(v not in (None, "") for v in row)
        ]
    wb.close()
    write(data)


def sizing_rules(part_type: str) -> dict:
    return {r["parameter"]: r for r in tables()["sizing_rules"] if r["part_type"] == part_type}
