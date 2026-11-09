"""Unique codes for every master-data row, and the live Price master price of priced rows (roadmap stage 53).

Every row of every master-data table (General master data, Mould & die database, Countries, machines & formulas,
Part register setup) and every Price master item gets a code that is never changed or reused:

    part materials       RM-<family>-001   by material family: RM-STL carbon / alloy steel, RM-SHT sheet steel, RM-SS
                                           stainless, RM-ALC aluminium casting, RM-ALW aluminium wrought, RM-ZN zinc,
                                           RM-MG magnesium, RM-CU copper alloys, RM-CI cast iron, RM-PLC / RM-PLE plastics
                                           (commodity / engineering), RM-RUB rubber, RM-OTH other
    tool steels          TS-001            machines MC-, process rates PR-, process rates by unit PU-, standard parts SP-,
                                           part library PL-, countries CT-, labour grades LG-, parameters PA-
    every other table    initials of the table name (e.g. design_rules DR-001), made unique once and kept

A code belongs to the row's identity (its key columns: code, name, material, parameter …), not to its values: changing
a value keeps the code; a new row gets the next number. The register is append-only (table item_codes).
The same material has one code in Materials, the flow / process tables and the Price master.

Prices are never copied: a priced row shows the latest APPROVED Price master / rate-library version for the chosen
country and month (part material, tool steel, machine price, process rate per hour / per unit).
"""

from __future__ import annotations

import re
from contextlib import closing
from datetime import date

from . import costing_db, rates

FAMILY_PREFIX = {
    "Carbon & alloy steel (bar, forging)": "RM-STL", "Sheet & strip steel": "RM-SHT", "Stainless steel": "RM-SS",
    "Aluminium - casting alloys": "RM-ALC", "Aluminium - wrought (sheet, extrusion, bar)": "RM-ALW", "Zinc alloys": "RM-ZN",
    "Magnesium alloys": "RM-MG", "Copper & copper alloys": "RM-CU", "Cast iron": "RM-CI", "Plastics - commodity": "RM-PLC",
    "Plastics - engineering": "RM-PLE", "Rubber": "RM-RUB", "Other": "RM-OTH",
}
FIXED_PREFIX = {"tool_materials": "TS", "machines": "MC", "process_rates": "PR", "process_unit_rates": "PU",
                "standard_parts": "SP", "part_library": "PL", "countries": "CT", "labour_grades": "LG", "Parameters": "PA"}
# identity columns, in this order, where a table has them
KEY_COLS = ("scope", "part_type", "category", "series", "step", "system", "topic", "element", "code", "machine_id", "grade",
            "size_code", "material", "parameter", "name", "variable", "key", "fit", "tol_class", "kind", "shape", "from_mm",
            "to_mm", "item", "part_number", "country", "size_mm", "width_mm", "condition", "seq", "make")
# material-keyed tables share the code of the material (one material = one code)
MATERIAL_TABLES = {"Materials", "flow_materials", "process_windows", "sheet_materials", "machining_data"}
# priced tables -> (rate category, the column that is the rate item)
PRICED = {"Materials": ("material", "material"), "tool_materials": ("tool_material", "code"),
          "machines": ("machine_price", "machine_id"), "process_rates": ("process_hour", "code"),
          "process_unit_rates": ("process_unit", "code")}


def _db():
    con = costing_db.connect()
    con.execute("CREATE TABLE IF NOT EXISTS item_codes (code TEXT PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL, "
                "created TEXT, UNIQUE (kind, key))")
    con.execute("CREATE TABLE IF NOT EXISTS code_prefixes (kind TEXT PRIMARY KEY, prefix TEXT UNIQUE NOT NULL)")
    return con


def _kind_key(table: str, row: dict) -> tuple[str, str]:
    """What a code belongs to: (kind, key)."""
    if table in MATERIAL_TABLES:
        return "material", str(row.get("material") or "").strip()
    if table == "tool_materials":
        return "tool_material", str(row.get("code") or "").strip()
    cols = [c for c in KEY_COLS if c in row]
    if not cols:                                       # a table without identity columns: its whole content
        cols = sorted(k for k in row if k not in ("id", "is_example", "notes", "_id"))
    return f"table:{table}", "|".join(str(row.get(c, "")).strip() for c in cols)


def _prefix(con, kind: str, key: str) -> str:
    if kind == "material":
        from .country_rate_book import family_of
        return FAMILY_PREFIX.get(family_of(key), "RM-OTH")
    if kind == "tool_material":
        return "TS"
    table = kind.split(":", 1)[1]
    if table in FIXED_PREFIX:
        return FIXED_PREFIX[table]
    r = con.execute("SELECT prefix FROM code_prefixes WHERE kind = ?", (kind,)).fetchone()
    if r:
        return r[0]
    words = [w for w in re.split(r"[_\W]+", table) if w]
    base = "".join(w[0] for w in words).upper() or "X"
    if len(base) == 1:
        base = (words[0][:2] if words else "XX").upper()
    taken = {p for (p,) in con.execute("SELECT prefix FROM code_prefixes")} | set(FIXED_PREFIX.values()) | {"TS", "RM"}
    cand, extra = base, 1
    letters = "".join(words).upper()
    while cand in taken:
        cand = base + (letters[extra] if extra < len(letters) else str(extra))
        extra += 1
    con.execute("INSERT INTO code_prefixes (kind, prefix) VALUES (?, ?)", (kind, cand))
    return cand


def code_of(con, kind: str, key: str) -> str:
    """The code of (kind, key); a new one (next number of its prefix) when it has none yet."""
    r = con.execute("SELECT code FROM item_codes WHERE kind = ? AND key = ?", (kind, key)).fetchone()
    if r:
        return r[0]
    p = _prefix(con, kind, key)
    nums = [int(c.rsplit("-", 1)[1]) for (c,) in con.execute("SELECT code FROM item_codes WHERE code LIKE ?", (p + "-%",))
            if re.fullmatch(re.escape(p) + r"-\d+", c)]
    code = f"{p}-{(max(nums) + 1) if nums else 1:03d}"
    con.execute("INSERT INTO item_codes (code, kind, key, created) VALUES (?, ?, ?, ?)", (code, kind, key, date.today().isoformat()))
    return code


def codes(tables: dict) -> dict:
    """{table: [code per row, in the order of the rows]} for a data set's tables (new codes are registered)."""
    out = {}
    with closing(_db()) as con, con:
        for t, rows in tables.items():
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                out[t] = [code_of(con, *_kind_key(t, r)) if any(v not in ("", None) for v in r.values()) else "" for r in rows]
    return out


def price(category: str, item: str, country: str, month: str) -> dict | None:
    try:
        r = rates.lookup(category, item, country, month)
    except rates.RateError:
        return None
    return {k: r[k] for k in ("value", "unit", "currency", "month", "status", "is_example", "source")}


def prices(tables: dict, country: str, month: str) -> dict:
    """{table: [live approved price per row or None]} for the priced tables of a data set."""
    out = {}
    for t, (cat, col) in PRICED.items():
        if t in tables:
            out[t] = [price(cat, str(r.get(col) or ""), country, month) for r in tables[t]]
    return out


def dataset_tables(dataset: str) -> dict:
    from . import costing_setup, master_data, mould_db, register_setup
    mods = {"general": master_data, "mould": mould_db, "setup": costing_setup, "register": register_setup}
    if dataset not in mods:
        raise ValueError(f"Unknown data set '{dataset}' ({', '.join(mods)}).")
    return mods[dataset].tables()


def for_dataset(dataset: str, country: str = "IN", month: str | None = None) -> dict:
    month = month or rates.current_month()
    t = dataset_tables(dataset)
    return {"codes": codes(t), "prices": prices(t, country.upper(), month), "country": country.upper(), "month": month,
            "priced": {k: v[0] for k, v in PRICED.items() if k in t}}


def material_code(name: str) -> str:
    with closing(_db()) as con, con:
        return code_of(con, "material", name)


def tool_code(name: str) -> str:
    with closing(_db()) as con, con:
        return code_of(con, "tool_material", name)


def seed() -> int:
    """Register a code for every row of every data set now (idempotent). Returns the number of codes."""
    n = 0
    for ds in ("general", "mould", "setup", "register"):
        n += sum(len(v) for v in codes(dataset_tables(ds)).values())
    from . import price_master
    for g in ("part_material", "tool_material"):
        for it in price_master.items(g):
            (tool_code if g == "tool_material" else material_code)(it["item"])
    with closing(_db()) as con:
        return con.execute("SELECT COUNT(*) FROM item_codes").fetchone()[0]
