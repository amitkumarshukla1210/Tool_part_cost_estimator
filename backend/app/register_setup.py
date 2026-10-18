"""Master data for the part register (in the costing database).

    processes        process codes offered for a part (auto-suggest uses part_type)
    part_statuses    the design-loop status flow, in order
    sourcing_types   Make / Bought-out / Existing / Not required, and whether each is costed
    register_settings
        part_code_pattern  used when a part code is left blank, e.g. {project}-{seq:04d}
        storage_folder     where CAD files and thumbnails are kept (relative to the app folder or absolute)
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
        col("part_type", "Estimator part type", "part_type", PART_TYPES),
        col("is_assembly", "Assembly", "bool"),
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
        col("notes", "Notes"),
    ]},
    "sourcing_types": {"title": "Sourcing", "unique": ("code",), "columns": [
        col("code", "Code"),
        col("name", "Sourcing"),
        col("is_costed", "Costed by us", "bool"),
        col("sort_order", "Order", "number"),
    ]},
    "register_settings": {"title": "Register settings", "unique": ("key",), "columns": [
        col("key", "Setting"),
        col("value", "Value"),
        col("description", "Description"),
    ]},
}
REQUIRED_SETTINGS = ("part_code_pattern", "storage_folder")

# Geometry values a process suggestion rule can use (measured from the STEP file).
SUGGEST_VARIABLES = {
    "wall_mm": "Most common wall / sheet thickness (mm)",
    "sheet_share": "Share of the surface that is pairs of parallel faces at that thickness (0-1)",
    "fill_ratio": "Volume ÷ bounding-box volume (0-1); high for solid blocks",
    "volume_cm3": "Part volume (cm³)",
    "max_dim_mm": "Largest bounding-box dimension (mm)",
    "min_dim_mm": "Smallest bounding-box dimension (mm)",
}


def _check(clean: dict) -> None:
    from . import formula
    sample = {"wall_mm": 2.5, "sheet_share": 0.5, "fill_ratio": 0.3, "volume_cm3": 50, "max_dim_mm": 120, "min_dim_mm": 30}
    for i, r in enumerate(clean["processes"], start=2):
        r["suggest_rule"] = r["suggest_rule"] or "0"
        try:
            formula.evaluate(r["suggest_rule"], sample)
        except formula.FormulaError as exc:
            raise RegisterSetupError(f"Processes row {i}, suggest_rule: {exc}") from None
    settings = {r["key"]: r["value"] for r in clean["register_settings"]}
    for k in REQUIRED_SETTINGS:
        if not settings.get(k):
            raise RegisterSetupError(f"Register settings: '{k}' must have a value.")
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


def initial_status() -> str:
    return next(s["code"] for s in statuses() if s["is_initial"])


def sourcing() -> dict:
    return {s["code"]: s for s in sorted(tables()["sourcing_types"], key=lambda r: r["sort_order"])}


def assembly_process() -> str:
    return next(code for code, p in processes().items() if p["is_assembly"])
