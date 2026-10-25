"""Price master (roadmap stage 20): month-wise prices of tool materials, standard parts and part materials by country.

The prices are ordinary versioned rates of the rate library (rates.py); this module shows and edits them as an
item × month grid for one country, and adds new grades and makes:

    group           library category   items (master list)
    tool_material   tool_material      Mould & die database → Tool materials (type, grade, density, hardness)
    standard_part   standard_part      Mould & die database → Standard parts ("<BOM element> · <make>")
    part_material   material           Master data → Materials (part type, type, grade, density)
    part_scrap      material_scrap     Master data → Materials (the scrap value of each grade)

A cell shows the approved value that costing uses in that month (the latest approved version on or before it) and
whether a version starts in that month. Typing a price saves a NEW version for that month (approved at once with
"Save & approve", else a draft for the Rate review); old versions are never changed, so stored costs only move when
you recalculate them.

`seed_history` fills months back in time with EXAMPLE values (the latest value × an illustrative trend), so the
grid has two years of history until you replace them with your purchase records. It never touches a month that
already has a version.
"""

from __future__ import annotations

import io
import math
from contextlib import closing

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from . import costing_setup, country_rates, master_data, mould_db, rates
from .table_set import EXAMPLE_FILL, HEADER_FILL

GROUPS = {
    "tool_material": {"title": "Tool materials (per kg)", "category": "tool_material", "per": "kg"},
    "standard_part": {"title": "Standard parts by make (per piece)", "category": "standard_part", "per": "pc"},
    "part_material": {"title": "Part raw materials (per kg)", "category": "material", "per": "kg"},
    "part_scrap": {"title": "Part raw material scrap value (per kg)", "category": "material_scrap", "per": "kg"},
}
HISTORY_MONTHS = 24
HISTORY_SOURCE = "EXAMPLE history: latest value × illustrative trend, not market data"
# Illustrative trend per family for the EXAMPLE back-history: (lower by this share 2 years back, seasonal swing).
TRENDS = {"steel": (0.06, 0.02), "copper": (0.12, 0.04), "aluminium": (0.10, 0.03), "zinc": (0.08, 0.03),
          "plastic": (0.05, 0.03), "standard": (0.08, 0.0), "other": (0.06, 0.02)}


class PriceError(ValueError):
    pass


def _group(group: str) -> dict:
    if group not in GROUPS:
        raise PriceError(f"Unknown price group '{group}' ({', '.join(GROUPS)}).")
    return GROUPS[group]


def add_months(month: str, n: int) -> str:
    y, m = map(int, month.split("-"))
    k = y * 12 + m - 1 + n
    return f"{k // 12:04d}-{k % 12 + 1:02d}"


def months(end: str | None = None, count: int = HISTORY_MONTHS) -> list[str]:
    end = end or rates.current_month()
    return [add_months(end, -k) for k in range(count - 1, -1, -1)]


def _countries() -> dict:
    return {c["code"]: c for c in costing_setup.tables()["countries"]}


def items(group: str) -> list[dict]:
    """The master list of the group: one row per library item, with what describes it."""
    _group(group)
    if group == "tool_material":
        return [{"item": r["code"], "type": r.get("material_type") or "", "grade": r["code"], "info": r["application"],
                 "density": r["density_g_cm3"], "hardness": r["hardness"], "is_example": r["is_example"]}
                for r in mould_db.tables()["tool_materials"]]
    if group == "standard_part":
        db = mould_db.tables()
        origin = {m["make"]: m["origin_country"] for m in db["makes"]}
        return [{"item": country_rates.standard_part_item(r["element"], r["make"]), "type": r["element"], "grade": r["make"],
                 "info": r["catalogue_ref"], "origin": origin.get(r["make"], ""), "recommended": r["recommended"],
                 "is_example": r["is_example"]} for r in db["standard_parts"]]
    return [{"item": r["material"], "type": r["material_type"], "grade": r["material"], "info": r["part_type"],
             "density": r["density_g_cm3"], "recommended": bool(r["recommended"]), "is_example": False}
            for r in master_data.tables()["Materials"]]


def grid(group: str, country: str, end: str | None = None, count: int = HISTORY_MONTHS) -> dict:
    """Items × months of one country: the approved value costing uses in each month, and any open drafts."""
    g = _group(group)
    country = (country or "").upper()
    countries = _countries()
    if country not in countries:
        raise PriceError(f"Country '{country}' is not in Master data → Countries.")
    end = end or rates.current_month()
    cols = months(add_months(end, 1), count + 1)  # one month ahead, to enter next month's prices
    with closing(rates._connect()) as con:
        rows = [rates._row(r) for r in con.execute(
            "SELECT * FROM rates WHERE category = ? AND country = ? AND month <= ? ORDER BY item, month, approved_date, id",
            (g["category"], country, cols[-1]))]
    by_item: dict[str, list] = {}
    for r in rows:
        by_item.setdefault(r["item"], []).append(r)
    out = []
    for it in items(group):
        versions = by_item.pop(it["item"], [])
        out.append(it | {"cells": _cells(versions, cols)})
    for item, versions in sorted(by_item.items()):  # rates of items no longer in the master list
        out.append({"item": item, "type": "", "grade": item, "info": "not in the master list", "is_example": False,
                    "cells": _cells(versions, cols), "orphan": True})
    return {"group": group, "title": g["title"], "category": g["category"], "country": country,
            "currency": countries[country]["currency"], "unit": f"{countries[country]['currency']}/{g['per']}",
            "months": cols, "current_month": rates.current_month(), "rows": out}


def _cells(versions: list[dict], cols: list[str]) -> dict:
    approved = [v for v in versions if v["status"] == "approved"]
    cells = {}
    for m in cols:
        best = None
        for v in approved:  # sorted by month, approval date, id: the last one on or before m wins
            if v["month"] <= m:
                best = v
        drafts = [v for v in versions if v["month"] == m and v["status"] in rates.OPEN]
        if best is None and not drafts:
            continue
        cells[m] = {"value": best["value"] if best else None, "id": best["id"] if best else None,
                    "is_example": bool(best and best["is_example"]), "starts": bool(best and best["month"] == m),
                    "source": best["source"] if best else "", "draft": drafts[-1]["value"] if drafts else None,
                    "draft_id": drafts[-1]["id"] if drafts else None}
    return cells


def set_price(group: str, item: str, country: str, month: str, value, approve: bool = True, comment: str = "",
              source: str = "") -> dict:
    """A new version of one price for that month (approved, or a draft for review)."""
    g = _group(group)
    country = (country or "").upper()
    countries = _countries()
    if country not in countries:
        raise PriceError(f"Country '{country}' is not in Master data → Countries.")
    if item not in {i["item"] for i in items(group)}:
        raise PriceError(f"'{item}' is not in the master list of {g['title']}. Add it as a new grade or make first.")
    cur = countries[country]["currency"]
    return rates.create({"category": g["category"], "item": item, "country": country, "value": value,
                         "unit": f"{cur}/{g['per']}", "currency": cur, "month": month, "comment": comment,
                         "source": source or "Price master (typed)", "is_example": False},
                        approve=approve, origin="price master")


def add_item(group: str, data: dict, approve: bool = True) -> dict:
    """A new grade (tool material or part material) or a new make of a standard part, with its first price."""
    g = _group(group)
    if group == "part_scrap":
        raise PriceError("Add the grade under Part raw materials; its scrap value is entered there too.")
    country = (data.get("country") or country_rates.base_country()["code"]).upper()
    month = str(data.get("month") or rates.current_month()).strip()
    if not rates.MONTH.match(month):
        raise PriceError(f"Month '{month}' must look like 2026-10.")
    price = data.get("price")
    if price in (None, ""):
        raise PriceError("Give the price for the month.")
    if approve:
        rates._approver()  # no approver set (or not allowed): stop before the master list changes
    base = country_rates.base_country()["code"]
    text = lambda k: str(data.get(k) or "").strip()
    if group == "tool_material":
        code = text("code")
        if not code:
            raise PriceError("Give the grade (e.g. 1.2738, NAK80, Beryllium copper C17200).")
        db = mould_db.tables()
        if any(r["code"] == code for r in db["tool_materials"]):
            raise PriceError(f"Grade '{code}' is already in Tool materials: type its price in the grid.")
        db["tool_materials"].append({
            "code": code, "material_type": text("material_type"), "application": text("application") or "core_cavity",
            "density_g_cm3": data.get("density"), "rate_per_kg": price if country == base else 0,
            "hardness": text("hardness"), "is_example": False, "notes": text("notes")})
        mould_db.write(db)
        item = code
    elif group == "standard_part":
        element, make = text("element"), text("make")
        db = mould_db.tables()
        if not any(m["make"] == make for m in db["makes"]):
            if not make:
                raise PriceError("Give the make (e.g. HASCO, MISUMI, DME).")
            db["makes"].append({"make": make, "origin_country": text("origin_country").upper(), "is_example": False,
                                "notes": "Added on the Price master page"})
        if any(r["element"] == element and r["make"] == make for r in db["standard_parts"]):
            raise PriceError(f"'{element}' already has the make '{make}': type its price in the grid.")
        db["standard_parts"].append({
            "element": element, "make": make, "catalogue_ref": text("catalogue_ref"), "recommended": False,
            "india_price": price if country == base else 0, "size_rule": text("size_rule") or _size_rule_of(db, element),
            "is_example": False, "notes": text("notes")})
        mould_db.write(db)
        item = country_rates.standard_part_item(element, make)
    else:
        part_type, grade = text("part_type").lower(), text("material")
        if not grade:
            raise PriceError("Give the grade (material name).")
        md = master_data.tables()
        if any(r["part_type"] == part_type and r["material"] == grade for r in md["Materials"]):
            raise PriceError(f"'{grade}' is already a {part_type} material: type its price in the grid.")
        md = {k: [dict(r) for r in v] for k, v in md.items()}
        md["Materials"].append({"part_type": part_type, "material": grade, "material_type": text("material_type"),
                                "recommended": "", "density_g_cm3": data.get("density"), "notes": text("notes")})
        master_data.write(md)
        item = grade
    made = [set_price(group, item, country, month, price, approve, source="Price master (new item)")]
    if group == "part_material" and data.get("scrap_price") not in (None, ""):
        made.append(set_price("part_scrap", item, country, month, data["scrap_price"], approve,
                              source="Price master (new item)"))
    return {"item": item, "group": group, "rates": made}


def _size_rule_of(db: dict, element: str) -> str:
    """A new make of a standard part follows the size factor of the element's other makes."""
    return next((r["size_rule"] for r in db["standard_parts"] if r["element"] == element), "1")


# ---------- Excel ----------

def to_excel(group: str, country: str, end: str | None = None, count: int = HISTORY_MONTHS) -> bytes:
    """The grid as a sheet: item, type, grade, info, then one column per month (EXAMPLE values shaded)."""
    g = grid(group, country, end, count)
    wb = Workbook()
    ws = wb.active
    ws.title = "Prices"
    wb.properties.title = f"Design to Cost — Price master: {g['title']} · {g['country']}"
    wb.properties.creator = "Design to Cost"
    head = ["item", "type", "grade / make", "info"] + g["months"]
    ws.append(head)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
    for i, r in enumerate(g["rows"], start=2):
        ws.append([r["item"], r["type"], r["grade"], r["info"]] + [(r["cells"].get(m) or {}).get("value") for m in g["months"]])
        for j, m in enumerate(g["months"], start=5):
            if (r["cells"].get(m) or {}).get("is_example"):
                ws.cell(row=i, column=j).fill = EXAMPLE_FILL
    ws.append([])
    ws.append([f"Unit: {g['unit']}. Shaded = EXAMPLE value. Type a price under a month and upload the file on the Price "
               "master page: every changed cell becomes a new version for that month; the rest is left alone."])
    ws.freeze_panes = "E2"
    ws.column_dimensions["A"].width = 38
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def import_excel(group: str, country: str, content: bytes, approve: bool = True) -> dict:
    """Every cell that differs from the value costing uses in that month becomes a new version for that month."""
    current = grid(group, country, rates.current_month(), 1)  # only to check the country and group
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise PriceError(f"Could not read the uploaded file as Excel (.xlsx): {exc}") from exc
    ws = wb["Prices"] if "Prices" in wb.sheetnames else wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows or not rows[0] or str(rows[0][0] or "").strip() != "item":
        raise PriceError("The first column of the sheet must be 'item' (download the grid to get the layout).")
    month_cols = {j: str(h).strip() for j, h in enumerate(rows[0]) if h is not None and rates.MONTH.match(str(h).strip())}
    if not month_cols:
        raise PriceError("The sheet has no month columns (headers like 2026-10).")
    known = {i["item"] for i in items(group)}
    wanted = []
    for n, row in enumerate(rows[1:], start=2):
        item = str(row[0] or "").strip() if row else ""
        if not item or item.startswith("Unit:"):
            continue
        if item not in known:
            raise PriceError(f"Row {n}: '{item}' is not in the master list. Add it as a new grade or make first.")
        for j, m in month_cols.items():
            v = row[j] if j < len(row) else None
            if v in (None, ""):
                continue
            try:
                v = float(str(v).replace(",", ""))
            except ValueError:
                raise PriceError(f"Row {n}, {m}: '{v}' is not a number.") from None
            wanted.append((item, m, v))
    lo, hi = min(m for _, m, _ in wanted) if wanted else None, max(m for _, m, _ in wanted) if wanted else None
    made = 0
    if wanted:
        span = (int(hi[:4]) * 12 + int(hi[5:])) - (int(lo[:4]) * 12 + int(lo[5:])) + 1
        cells = {r["item"]: r["cells"] for r in grid(group, current["country"], add_months(hi, -1), span)["rows"]}
        for item, m, v in wanted:
            cell = cells.get(item, {}).get(m) or {}
            if cell.get("value") is not None and abs(float(cell["value"]) - v) < 1e-9:
                continue
            set_price(group, item, current["country"], m, v, approve, source="Price master (Excel upload)")
            made += 1
    return {"versions_created": made, "status": "approved" if approve else "draft"}


# ---------- EXAMPLE back-history ----------

def _family(group: str, it: dict) -> str:
    if group == "standard_part":
        return "standard"
    name = f"{it.get('type', '')} {it['item']}".lower()
    for word, fam in (("copper", "copper"), ("becu", "copper"), ("bronze", "copper"), ("brass", "copper"),
                      ("alumin", "aluminium"), ("zinc", "zinc"), ("zamak", "zinc"), ("magnesium", "aluminium")):
        if word in name:
            return fam
    if group in ("part_material", "part_scrap") and it.get("info") in ("plastic", "blow", "eps"):
        return "plastic"
    return "steel" if group == "tool_material" or it.get("info") in ("sheet_metal", "foundry") else "other"


def trend_factor(family: str, months_back: int) -> float:
    """Illustrative price level `months_back` months ago against today (1.0 today)."""
    drift, swing = TRENDS.get(family, TRENDS["other"])
    season = swing * (math.sin(2 * math.pi * (HISTORY_MONTHS - months_back) / 12) - math.sin(2 * math.pi * HISTORY_MONTHS / 12))
    return (1 - drift * months_back / HISTORY_MONTHS) * (1 + season)


def seed_history(end: str | None = None, count: int = HISTORY_MONTHS, groups=tuple(GROUPS)) -> dict:
    """Approved EXAMPLE versions for the `count - 1` months before `end`, from each item's value in `end`."""
    end = end or rates.current_month()
    back = months(end, count)[:-1]
    made = 0
    for group in groups:
        g = GROUPS[group]
        fam = {it["item"]: _family(group, it) for it in items(group)}
        with closing(rates._connect()) as con:
            have = {(r["item"], r["country"], r["month"]) for r in con.execute(
                "SELECT item, country, month FROM rates WHERE category = ?", (g["category"],))}
        for row in rates.current(end, None, g["category"]):
            a = row["approved"]
            if not a or row["item"] not in fam:
                continue
            for k, m in enumerate(reversed(back), start=1):
                if (row["item"], row["country"], m) in have:
                    continue
                value = country_rates._round(a["value"] * trend_factor(fam[row["item"]], k))
                rates.create({"category": g["category"], "item": row["item"], "country": row["country"], "value": value,
                              "unit": a["unit"], "currency": a["currency"], "month": m, "is_example": True,
                              "source": HISTORY_SOURCE},
                             approve=True, origin="seed history", approver="Example seed")
                made += 1
    return {"created": made, "months": back}


if __name__ == "__main__":  # python -m backend.app.price_master seed-history [end month]
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == "seed-history":
        print(seed_history(sys.argv[2] if len(sys.argv) > 2 else None))
    else:
        print(__doc__)
