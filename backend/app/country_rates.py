"""Material & process rates by country (roadmap stage 3).

The rates themselves are ordinary versioned, approved rates in the rate library (rates.py). This module only

* moves the single-country values of Master data (tool steels, process rates per hour, process rates by unit)
  into the library as the first approved version for the base country (the country whose currency is INR),
* PROPOSES rates for countries that have none yet: base-country value × country index (Master data → Country rate
  index) ÷ forex, saved as drafts for review (or as approved EXAMPLE seeds on first set-up), and
* builds the item × country grid shown on the Rates page.

Library categories (item = material / steel / process name, country = the producing country):

    material, material_scrap   part materials, per kg
    tool_material              tool steels, per kg
    process_hour               machining / toolroom processes, per hour
    process_unit               heat treatment per kg, wire cut per cm², polishing per cm², painting per m², ...
    process_min_charge         minimum charge per job for a process rate by unit

Nothing is overwritten: a proposal is only made where a country has no version of that rate at all.
"""

from __future__ import annotations

import math
from contextlib import closing

from . import costing_db, costing_setup, mould_db, rates

# category -> (title, which index of the country index it follows)
GROUPS = {
    "material": ("Part materials (per kg)", "material_index"),
    "material_scrap": ("Part material scrap value (per kg)", "material_index"),
    "tool_material": ("Tool steels (per kg)", "tool_steel_index"),
    "process_hour": ("Processes charged per hour", "process_index"),
    "process_unit": ("Processes charged per unit (kg, cm², m², …)", "process_index"),
    "process_min_charge": ("Minimum charge per job", "process_index"),
}
SEED_SOURCE = "Moved from Master data in Stage 3"
SIGNIFICANT_DIGITS = 3


def base_country() -> dict:
    """The country whose currency is the base currency of the library (the rates all others are derived from)."""
    for c in costing_setup.tables()["countries"]:
        if c["currency"] == rates.BASE_CURRENCY:
            return c
    raise rates.RateError(f"Countries needs a country with currency {rates.BASE_CURRENCY} as the base of the rates.")


def _exists(con, category: str, item: str, country: str) -> bool:
    return con.execute("SELECT 1 FROM rates WHERE category = ? AND item = ? AND country = ? LIMIT 1",
                       (category, item, country)).fetchone() is not None


def sync_base(month: str | None = None, approver: str = "") -> int:
    """Master-data values of the base country → first approved library version. Never changes an existing rate."""
    month = month or rates.current_month()
    base = base_country()["code"]
    cur = rates.BASE_CURRENCY
    db = mould_db.tables()
    wanted = []
    for r in db["tool_materials"]:
        wanted.append(("tool_material", r["code"], r["rate_per_kg"], f"{cur}/kg", r["is_example"], "Tool materials"))
    for r in db["process_rates"]:
        wanted.append(("process_hour", r["code"], r["rate_per_hour"], f"{cur}/h", r["is_example"], "Process rates"))
    for r in db["process_unit_rates"]:
        wanted.append(("process_unit", r["code"], r["india_rate"], f"{cur}/{r['basis']}", r["is_example"],
                       "Process rates by unit"))
        if r["min_charge"]:
            wanted.append(("process_min_charge", r["code"], r["min_charge"], f"{cur}/job", r["is_example"],
                           "Process rates by unit"))
    made = 0
    with closing(rates._connect()) as con:
        todo = [w for w in wanted if not _exists(con, w[0], w[1], base)]
    for category, item, value, unit, example, sheet in todo:
        rates.create({"category": category, "item": item, "country": base, "value": value, "unit": unit,
                      "currency": cur, "month": month, "source": f"{SEED_SOURCE} ({sheet})",
                      "comment": "", "is_example": example}, approve=True, origin="seed", approver=approver or "Example seed")
        made += 1
    return made


def _round(value: float) -> float:
    if value == 0:
        return 0.0
    digits = SIGNIFICANT_DIGITS - 1 - math.floor(math.log10(abs(value)))
    out = round(value, digits)
    return int(out) if digits <= 0 else out


def propose(month: str | None = None, approve: bool = False, approver: str = "", origin: str = "index proposal") -> dict:
    """Rates for countries that have none yet: base value × country index ÷ forex. Drafts unless `approve`."""
    month = month or rates.current_month()
    base = base_country()
    tables = costing_setup.tables()
    index = {r["country"]: r for r in tables["country_index"]}
    created, skipped = 0, []
    base_rows = [r for cat in GROUPS for r in rates.current(month, base["code"], cat)
                 if r["approved"] and r["country"] == base["code"]]
    for c in tables["countries"]:
        if c["code"] == base["code"]:
            continue
        if c["code"] not in index:
            skipped.append({"country": c["code"], "reason": "no row in Master data → Country rate index"})
            continue
        try:
            inr_per_unit = 1.0 if c["currency"] == base["currency"] else rates.lookup("forex", c["currency"], "", month)["value"]
        except rates.RateMissing as exc:
            skipped.append({"country": c["code"], "reason": str(exc)})
            continue
        for row in base_rows:
            a = row["approved"]
            with closing(rates._connect()) as con:
                if _exists(con, row["category"], row["item"], c["code"]):
                    continue
            factor = index[c["code"]][GROUPS[row["category"]][1]]
            unit = a["unit"].replace(base["currency"], c["currency"], 1) if a["unit"].startswith(base["currency"]) else a["unit"]
            rates.create({
                "category": row["category"], "item": row["item"], "country": c["code"],
                "value": _round(a["value"] * factor / inr_per_unit), "unit": unit, "currency": c["currency"],
                "month": month, "is_example": True,
                "source": f"Proposed: {base['code']} rate × {GROUPS[row['category']][1].replace('_', ' ')} {factor} ÷ forex",
                "comment": f"{base['code']} {a['value']} {a['unit']} ({a['month']}) × {factor} ÷ {inr_per_unit} INR per {c['currency']}. "
                           "EXAMPLE: replace with a supplier quote or market rate.",
            }, approve=approve, origin=origin, approver=approver)
            created += 1
    return {"created": created, "skipped": skipped, "status": "approved" if approve else "draft"}


def seed(month: str | None = None) -> dict:
    """First set-up: master-data values into the library, other countries as approved EXAMPLE seeds."""
    moved = sync_base(month)
    return {"moved": moved} | propose(month, approve=True, approver="Example seed", origin="seed")


def grid(as_of: str | None = None) -> dict:
    """Item × country grid of approved values, each also in INR and as % against the base country."""
    as_of = as_of or rates.current_month()
    base = base_country()
    countries = costing_setup.tables()["countries"]
    inr_per = {base["currency"]: 1.0}
    for c in countries:
        if c["currency"] not in inr_per:
            try:
                inr_per[c["currency"]] = rates.lookup("forex", c["currency"], "", as_of)["value"]
            except rates.RateMissing:
                inr_per[c["currency"]] = None
    cur_of = {c["code"]: c["currency"] for c in countries}
    groups = []
    for category, (title, _) in GROUPS.items():
        items: dict[str, dict] = {}
        for r in rates.current(as_of, None, category):
            cell = {"rate": r["approved"], "open_drafts": r["open_drafts"], "inr": None, "vs_base_pct": None}
            a = r["approved"]
            if a and inr_per.get(cur_of.get(r["country"])) is not None:
                cell["inr"] = a["value"] * inr_per[cur_of[r["country"]]]
            items.setdefault(r["item"], {"item": r["item"], "unit": "", "cells": {}})["cells"][r["country"]] = cell
        for it in items.values():
            b = it["cells"].get(base["code"])
            for code, cell in it["cells"].items():
                if cell["rate"] and not it["unit"]:
                    it["unit"] = cell["rate"]["unit"].split("/", 1)[-1] if "/" in cell["rate"]["unit"] else ""
                if b and b["inr"] and cell["inr"] is not None:
                    cell["vs_base_pct"] = round((cell["inr"] - b["inr"]) / b["inr"] * 100, 1)
        groups.append({"category": category, "title": title, "items": sorted(items.values(), key=lambda x: x["item"])})
    return {"as_of": as_of, "base": base["code"], "countries": countries, "groups": groups}
