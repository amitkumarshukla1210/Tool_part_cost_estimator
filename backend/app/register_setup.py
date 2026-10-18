"""Master data for the part register (in the costing database).

    processes        process codes offered for a part. The process suggestion uses
                     1. the material: its part type in Master data → Materials (plastic,
                        die_casting, foundry, sheet_metal) limits the choice to processes
                        of that family, then
                     2. the geometry: the highest-scoring rule among those processes wins.
    insert_materials materials of bought-out inserts (brass, steel, ...) with density
    insert_shapes    simple insert shapes and their volume formula, for inserts without a 3D file
    insert_rules     insert-moulding rules used by mould design, simulation and costing
    part_statuses    the design-loop status flow, in order
    sourcing_types   Make / Bought-out / Existing / Not required, and whether each is costed
    register_settings
        part_code_pattern  used when a part code is left blank, e.g. {project}-{seq:04d}
        storage_folder     where CAD files and thumbnails are kept (relative to the app folder or absolute)
        default_country    producing country of a part's RM cost when the part has none set
"""

from __future__ import annotations

from pathlib import Path

from .table_set import TableSet, col

ROOT = Path(__file__).resolve().parents[2]
PART_TYPES = ("", "plastic", "die_casting", "foundry", "sheet_metal")


class RegisterSetupError(ValueError):
    pass


TABLES = {
    "processes": {"title": "Processes", "unique": ("code",), "columns": [
        col("code", "Code"),
        col("name", "Process"),
        col("part_type", "Material family (part type in Materials)", "part_type", PART_TYPES),
        col("is_assembly", "Assembly", "bool"),
        col("is_insert_moulding", "Insert moulding / casting", "bool"),
        col("suggest_rule", "Auto-suggest score (rule)", "formula"),
        col("sort_order", "Order", "number"),
        col("notes", "Notes"),
    ]},
    "part_statuses": {"title": "Part statuses", "unique": ("code",), "columns": [
        col("code", "Code"),
        col("name", "Status"),
        col("sort_order", "Order", "number"),
        col("is_initial", "First status for new parts", "bool"),
        col("is_open_correction", "Counts as open correction", "bool"),
        col("next_statuses", "Allowed next statuses (codes, comma-separated; blank = any)", required=False),
        col("comment_required", "Comment required to enter", "bool"),
        col("on_new_revision", "Status after a new revision upload (blank = keep)", required=False),
        col("notes", "Notes"),
    ]},
    "capex_milestones": {"title": "CAPEX payment milestones", "unique": ("name",), "columns": [
        col("name", "Milestone"),
        col("pct", "Share of the amount (%)", "number"),
        col("weeks", "Weeks from the need-by date", "number"),
        col("is_after", "After the need-by date (else before)", "bool"),
        col("sort_order", "Order", "number"),
        col("notes", "Notes", required=False),
    ]},
    "part_library": {"title": "Part library (harness and PCB parts)", "unique": ("part_number",), "columns": [
        col("part_number", "Part number (MPN)"),
        col("maker", "Maker", required=False),
        col("description", "Description", required=False),
        col("unit", "Price per", "unit", ("pcs", "m")),
        col("unit_price", "Price per unit", "number"),
        col("currency", "Currency"),
        col("source", "Source (quote, catalogue)", required=False),
        col("month", "Price month (2026-10)", required=False),
        col("is_example", "Example", "bool"),
    ]},
    "electro_processes": {"title": "Harness and PCB processes", "unique": ("scope", "code"), "columns": [
        col("scope", "Of", "scope", ("harness", "pcb")),
        col("code", "Process"),
        col("description", "Description", required=False),
        col("driver", "Counted per (driver)"),
        col("seconds", "Seconds per driver unit", "number"),
        col("machine_id", "Machine (Machines sheet)", required=False),
        col("labour_grade", "Labour grade"),
        col("operators", "Operators", "number"),
        col("is_example", "Example", "bool"),
        col("notes", "Notes", required=False),
    ]},
    "sourcing_types": {"title": "Sourcing", "unique": ("code",), "columns": [
        col("code", "Code"),
        col("name", "Sourcing"),
        col("is_costed", "Costed by us", "bool"),
        col("sort_order", "Order", "number"),
    ]},
    "insert_materials": {"title": "Insert materials", "unique": ("name",), "columns": [
        col("name", "Material"),
        col("density_g_cm3", "Density (g/cm³)", "number"),
        col("is_metal", "Metal", "bool"),
        col("is_example", "Example value", "bool"),
        col("notes", "Notes", required=False),
    ]},
    "insert_shapes": {"title": "Insert shapes", "unique": ("code",), "columns": [
        col("code", "Code"),
        col("name", "Shape"),
        col("dimensions", "Dimensions (comma list, mm)"),
        col("volume_rule", "Volume (mm³) formula", "formula"),
        col("notes", "Notes", required=False),
    ]},
    "insert_rules": {"title": "Insert moulding rules", "unique": ("key",), "columns": [
        col("key", "Rule"),
        col("value", "Value", "number"),
        col("unit", "Unit", required=False),
        col("used_in", "Used in (roadmap stage)"),
        col("description", "Description"),
        col("is_example", "Example value", "bool"),
    ]},
    "register_settings": {"title": "Register settings", "unique": ("key",), "columns": [
        col("key", "Setting"),
        col("value", "Value"),
        col("description", "Description"),
    ]},
}
REQUIRED_SETTINGS = ("part_code_pattern", "storage_folder", "insert_detect_min_share", "insert_probe_offset_mm",
                     "insert_probe_points", "insert_default_sourcing", "insert_default_process", "default_country")
NUMBER_SETTINGS = ("insert_detect_min_share", "insert_probe_offset_mm", "insert_probe_points")

# Geometry values a process suggestion rule can use (measured from the STEP file).
SUGGEST_VARIABLES = {
    "wall_mm": "Most common wall / sheet thickness (mm)",
    "sheet_share": "Share of the surface that is pairs of parallel faces at that thickness (0-1)",
    "fill_ratio": "Volume ÷ bounding-box volume (0-1); high for solid blocks",
    "volume_cm3": "Part volume (cm³)",
    "max_dim_mm": "Largest bounding-box dimension (mm)",
    "min_dim_mm": "Smallest bounding-box dimension (mm)",
    "bend_count": "Bends found: coaxial cylinder pairs at the wall, or changes of direction of the wall",
    "insert_count": "Moulded-in inserts per part (linked in the register or detected in the assembly)",
}
SAMPLE_GEOMETRY = {"wall_mm": 2.5, "sheet_share": 0.5, "fill_ratio": 0.3, "volume_cm3": 50, "max_dim_mm": 120,
                   "min_dim_mm": 30, "bend_count": 1, "insert_count": 0}
SHAPE_CONSTANTS = {"pi": 3.141592653589793}


def _check(clean: dict) -> None:
    from . import formula
    import re
    for i, r in enumerate(clean["processes"], start=2):
        r["suggest_rule"] = r["suggest_rule"] or "0"
        try:
            formula.evaluate(r["suggest_rule"], SAMPLE_GEOMETRY)
        except formula.FormulaError as exc:
            raise RegisterSetupError(f"Processes row {i}, suggest_rule: {exc}") from None
        if r["is_insert_moulding"] and r["is_assembly"]:
            raise RegisterSetupError(f"Processes row {i}: a process cannot be both assembly and insert moulding.")
    for i, r in enumerate(clean["insert_materials"], start=2):
        if r["density_g_cm3"] <= 0:
            raise RegisterSetupError(f"Insert materials row {i}: density must be more than 0.")
    for i, r in enumerate(clean["insert_shapes"], start=2):
        dims = [d.strip() for d in r["dimensions"].split(",") if d.strip()]
        bad = [d for d in dims if not re.fullmatch(r"[a-z][a-z0-9_]*", d) or d in SHAPE_CONSTANTS]
        if not dims or bad:
            raise RegisterSetupError(f"Insert shapes row {i}: dimensions must be a comma list of names like d_mm, l_mm"
                                     + (f" (not {', '.join(bad)})" if bad else "") + ".")
        r["dimensions"] = ", ".join(dims)
        try:
            formula.evaluate(r["volume_rule"], SHAPE_CONSTANTS | {d: 10.0 for d in dims})
        except formula.FormulaError as exc:
            raise RegisterSetupError(f"Insert shapes row {i}, volume_rule: {exc}") from None
    settings = {r["key"]: r["value"] for r in clean["register_settings"]}
    for k in REQUIRED_SETTINGS:
        if not settings.get(k):
            raise RegisterSetupError(f"Register settings: '{k}' must have a value.")
    for k in NUMBER_SETTINGS:
        try:
            if float(settings[k]) <= 0:
                raise ValueError
        except ValueError:
            raise RegisterSetupError(f"Register settings: '{k}' must be a number more than 0.") from None
    if settings["insert_default_sourcing"] not in {r["code"] for r in clean["sourcing_types"]}:
        raise RegisterSetupError(f"Register settings: insert_default_sourcing '{settings['insert_default_sourcing']}' "
                                 "is not a Sourcing code.")
    if settings["insert_default_process"] not in {r["code"] for r in clean["processes"]}:
        raise RegisterSetupError(f"Register settings: insert_default_process '{settings['insert_default_process']}' "
                                 "is not a Process code.")
    from . import costing_setup
    settings["default_country"] = settings["default_country"].strip().upper()
    for r in clean["register_settings"]:
        if r["key"] == "default_country":
            r["value"] = settings["default_country"]
    if settings["default_country"] not in costing_setup.countries():
        raise RegisterSetupError(f"Register settings: default_country '{settings['default_country']}' is not a code in "
                                 "Countries, machines & formulas → Countries.")
    pattern = settings["part_code_pattern"]
    try:
        sample = pattern.format(project="PRJ", seq=1)
    except (KeyError, IndexError, ValueError) as exc:
        raise RegisterSetupError(f"Register settings: part_code_pattern '{pattern}' is not valid ({exc}). "
                                 "Use {project} and {seq}, e.g. {project}-{seq:04d}.") from None
    if "{seq" not in pattern or not sample.strip():
        raise RegisterSetupError("Register settings: part_code_pattern must contain {seq}, e.g. {project}-{seq:04d}.")
    initial = [r for r in clean["part_statuses"] if r["is_initial"]]
    if len(initial) != 1:
        raise RegisterSetupError(f"Part statuses: mark exactly one status as 'First status for new parts' "
                                 f"(found {len(initial)}).")
    codes = {r["code"] for r in clean["part_statuses"]}
    for i, r in enumerate(clean["part_statuses"], start=2):
        bad = [c for c in next_codes(r) + ([r["on_new_revision"]] if r.get("on_new_revision") else []) if c not in codes]
        if bad:
            raise RegisterSetupError(f"Part statuses row {i}: '{', '.join(bad)}' is not a status code.")
    if clean["capex_milestones"] and abs(sum(r["pct"] for r in clean["capex_milestones"]) - 100) > 0.01:
        raise RegisterSetupError("CAPEX payment milestones: the shares must add up to 100 % "
                                 f"(now {sum(r['pct'] for r in clean['capex_milestones']):g} %).")
    if not any(r["is_assembly"] for r in clean["processes"]):
        raise RegisterSetupError("Processes: one process must be marked 'Assembly' (used for split assemblies).")


SET = TableSet("Part register setup", TABLES, error=RegisterSetupError, check=_check)


def schema() -> dict:
    return SET.schema() | {"formula_variables": SUGGEST_VARIABLES}


def tables() -> dict:
    return SET.read()


def write(data: dict) -> None:
    SET.write(data)


def to_excel() -> bytes:
    return SET.to_excel()


def from_excel(content: bytes) -> None:
    SET.from_excel(content)


def settings() -> dict:
    return {r["key"]: r["value"] for r in tables()["register_settings"]}


def storage_root() -> Path:
    import os
    raw = os.environ.get("DTC_STORAGE_FOLDER") or settings().get("storage_folder") or "storage"
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def processes() -> dict:
    return {p["code"]: p for p in sorted(tables()["processes"], key=lambda r: r["sort_order"])}


def statuses() -> list[dict]:
    return sorted(tables()["part_statuses"], key=lambda r: r["sort_order"])


def electro_processes(scope: str) -> list[dict]:
    return [r for r in tables()["electro_processes"] if r["scope"] == scope]


def capex_milestones() -> list[dict]:
    return sorted(tables()["capex_milestones"], key=lambda r: r["sort_order"])


def next_codes(row: dict) -> list[str]:
    return [c.strip() for c in (row.get("next_statuses") or "").split(",") if c.strip()]


def initial_status() -> str:
    return next(s["code"] for s in statuses() if s["is_initial"])


def sourcing() -> dict:
    return {s["code"]: s for s in sorted(tables()["sourcing_types"], key=lambda r: r["sort_order"])}


def assembly_process() -> str:
    return next(code for code, p in processes().items() if p["is_assembly"])


def insert_detection() -> dict:
    s = settings()
    return {"min_share": float(s["insert_detect_min_share"]), "offset_mm": float(s["insert_probe_offset_mm"]),
            "points": int(float(s["insert_probe_points"]))}


def insert_materials() -> dict:
    return {r["name"]: r for r in tables()["insert_materials"]}


def insert_shapes() -> dict:
    out = {}
    for r in tables()["insert_shapes"]:
        out[r["code"]] = r | {"dims": [d.strip() for d in r["dimensions"].split(",") if d.strip()]}
    return out


def insert_rules() -> dict:
    return {r["key"]: r for r in tables()["insert_rules"]}
