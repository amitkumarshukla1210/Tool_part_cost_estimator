"""Master data: every rate, default and rule the estimator uses.

All values live in one Excel workbook (``master_data/master_data.xlsx``) so
they can be changed without touching code, either on the Master data page
or directly in Excel. The workbook has three sheets:

    Parameters  part_type | parameter | value | unit | description
                part_type "all" applies to every part type.
    Materials   part_type | material | density_g_cm3 | rate_per_kg | scrap_rate_per_kg | notes
    Machines    part_type | machine | tonnage_t | length_mm | width_mm | mhr_per_hour | notes

The file is re-read whenever it changes on disk.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "master_data" / "master_data.xlsx"

PART_TYPES = ("plastic", "die_casting", "foundry", "sheet_metal")

# Sheet name -> columns, and which columns must be numbers.
SHEETS = {
    "Parameters": ["part_type", "parameter", "value", "unit", "description"],
    "Materials": ["part_type", "material", "density_g_cm3", "rate_per_kg", "scrap_rate_per_kg", "notes"],
    "Machines": ["part_type", "machine", "tonnage_t", "length_mm", "width_mm", "mhr_per_hour", "notes"],
}
NUMERIC = {
    "Materials": {"density_g_cm3", "rate_per_kg", "scrap_rate_per_kg"},
    "Machines": {"tonnage_t", "length_mm", "width_mm", "mhr_per_hour"},
}
# Parameters whose value is text or a comma list; every other parameter is a number.
TEXT_PARAMETERS = {"currency"}
LIST_PARAMETERS = {"standard_cavities"}

_cache: dict = {"key": None, "data": None}


class MasterDataError(ValueError):
    pass


def path() -> Path:
    return Path(os.environ.get("MASTER_DATA_PATH", DEFAULT_PATH))


# ---------- reading ----------

def _read_workbook(p: Path) -> dict:
    if not p.exists():
        raise MasterDataError(f"Master data file not found: {p}")
    wb = load_workbook(p, read_only=True, data_only=True)
    tables = {}
    for sheet, columns in SHEETS.items():
        if sheet not in wb.sheetnames:
            raise MasterDataError(f"Master data file has no '{sheet}' sheet.")
        rows = list(wb[sheet].iter_rows(values_only=True))
        header = [str(h).strip() if h is not None else "" for h in rows[0]] if rows else []
        missing = [c for c in columns if c not in header]
        if missing:
            raise MasterDataError(f"Sheet '{sheet}' is missing column(s): {', '.join(missing)}.")
        idx = {c: header.index(c) for c in columns}
        tables[sheet] = [
            {c: row[idx[c]] if idx[c] < len(row) else None for c in columns}
            for row in rows[1:]
            if any(v not in (None, "") for v in row)
        ]
    wb.close()
    return validate(tables)


def tables() -> dict:
    """All three sheets as lists of row dicts (cleaned and validated)."""
    p = path()
    key = (str(p), p.stat().st_mtime_ns if p.exists() else None)
    if _cache["key"] != key:
        _cache["data"] = _read_workbook(p)
        _cache["key"] = key
    return _cache["data"]


def parameters(part_type: str) -> dict:
    """Parameters for one part type, with the 'all' rows underneath."""
    merged: dict = {}
    for scope in ("all", part_type):
        for row in tables()["Parameters"]:
            if row["part_type"] == scope:
                merged[row["parameter"]] = row["value"]
    return merged


def require(params: dict, key: str, part_type: str):
    if key not in params:
        raise MasterDataError(f"Master data has no '{key}' parameter for {part_type} (sheet Parameters).")
    return params[key]


# ---------- validation ----------

def _number(value, where: str) -> float:
    if isinstance(value, bool):
        raise MasterDataError(f"{where}: '{value}' is not a number.")
    try:
        n = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        raise MasterDataError(f"{where}: '{value}' is not a number.") from None
    if n < 0:
        raise MasterDataError(f"{where}: must not be negative.")
    return int(n) if n.is_integer() else n


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def validate(raw: dict) -> dict:
    """Clean and check all sheets; raises MasterDataError naming the bad cell."""
    out = {}
    for sheet, columns in SHEETS.items():
        rows = []
        seen = set()
        for i, row in enumerate(raw.get(sheet, []), start=2):  # row 1 is the header
            clean = {c: _text(row.get(c)) for c in columns}
            pt = clean["part_type"].lower()
            if pt not in PART_TYPES and not (sheet == "Parameters" and pt == "all"):
                allowed = ", ".join(("all",) + PART_TYPES if sheet == "Parameters" else PART_TYPES)
                raise MasterDataError(f"{sheet} row {i}: part_type '{clean['part_type']}' must be one of {allowed}.")
            clean["part_type"] = pt
            for c in NUMERIC.get(sheet, ()):
                clean[c] = _number(row.get(c), f"{sheet} row {i}, {c}")

            name_col = {"Parameters": "parameter", "Materials": "material", "Machines": "machine"}[sheet]
            if not clean[name_col]:
                raise MasterDataError(f"{sheet} row {i}: {name_col} is empty.")
            if (pt, clean[name_col]) in seen:
                raise MasterDataError(f"{sheet} row {i}: '{clean[name_col]}' is listed twice for {pt}.")
            seen.add((pt, clean[name_col]))

            if sheet == "Parameters":
                name, value, where = clean["parameter"], row.get("value"), f"Parameters row {i}, {clean['parameter']}"
                if name in TEXT_PARAMETERS:
                    clean["value"] = _text(value)
                elif name in LIST_PARAMETERS:
                    if isinstance(value, (list, tuple)):
                        value = ",".join(map(str, value))
                    items = _text(value).replace(";", " ").replace(",", " ").split()
                    nums = [_number(s, where) for s in items]
                    if not nums or any(not isinstance(n, int) or n < 1 for n in nums):
                        raise MasterDataError(f"{where}: use whole numbers separated by commas, e.g. 1, 2, 4, 8.")
                    clean["value"] = sorted(set(nums))
                else:
                    clean["value"] = _number(value, where)
            if sheet == "Materials" and clean["density_g_cm3"] <= 0:
                raise MasterDataError(f"Materials row {i}: density must be greater than zero.")
            rows.append(clean)
        out[sheet] = rows
    return out


# ---------- writing ----------

HEADER_FILL = PatternFill("solid", fgColor="102A43")


def write(data: dict, p: Path | None = None) -> None:
    """Validate and save all sheets. Writes to a temp file first so a failed
    save never leaves a half-written workbook."""
    clean = validate(data)
    p = p or path()
    wb = Workbook()
    wb.remove(wb.active)
    for sheet, columns in SHEETS.items():
        ws = wb.create_sheet(sheet)
        ws.append(columns)
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = HEADER_FILL
        for row in clean[sheet]:
            values = []
            for c in columns:
                v = row[c]
                # ", " keeps Excel from reading "1,2,4" as the number 124.
                values.append(", ".join(map(str, v)) if isinstance(v, list) else v)
            ws.append(values)
        for i, c in enumerate(columns, start=1):
            width = max([len(c)] + [len(str(r[c])) for r in clean[sheet]])
            ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 70)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=p.parent)
    os.close(fd)
    try:
        wb.save(tmp)
        os.replace(tmp, p)
    except PermissionError as exc:
        raise MasterDataError(
            "Could not save the master data file. If it is open in Excel, close it and try again."
        ) from exc
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    _cache["key"] = None


def replace_from_upload(content: bytes) -> None:
    """Check an uploaded workbook and, if valid, make it the master data."""
    fd, tmp = tempfile.mkstemp(suffix=".xlsx")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        try:
            data = _read_workbook(Path(tmp))
        except MasterDataError:
            raise
        except Exception as exc:
            raise MasterDataError(f"Could not read the uploaded file as Excel (.xlsx): {exc}") from exc
    finally:
        os.remove(tmp)
    write(data)
