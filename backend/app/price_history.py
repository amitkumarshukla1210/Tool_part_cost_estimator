"""24-month price history for every rate of every country (roadmap stage 54).

The rate library usually starts with one month (the set-up month). This fills the months BEFORE the first approved version
of each rate, back to 24 months before today, so the Price master, the country rate book and costing for an earlier month
have a value:

    material, material_scrap,          INDICATIVE: first rate × (market index × local currency per USD) of the month ÷ the
    tool_material                      same in the first rate's month (index = country_rate_book.index_for; tool steels
                                       without one follow the US steel PPI, part materials without one their family)
    forex                              MARKET: the monthly market average (FRED; VND: World Bank yearly)
    power                              MARKET for Germany (Eurostat half-year), else INDICATIVE by the US PPI electric power
    labour_salary                      INDICATIVE: × ILOSTAT yearly wage ratio (year of the month ÷ year of the first rate)
    freight (sea)                      INDICATIVE: × US PPI deep-sea freight
    everything else                    INDICATIVE flat: the first value, dated back once (no free index: machine prices,
                                       process rates, consumables, rent, utilities, overheads, duties, hours, % settings)

Every row is a new APPROVED version by the system user "Indicative history" (origin "history"), never over an existing
version of that month; INDICATIVE rows are marked EXAMPLE and say how they were made. Idempotent.
"""

from __future__ import annotations

from contextlib import closing
from datetime import date

from . import country_rate_book as crb, rates

USER = "Indicative history"
ORIGIN = "history"
MONTHS = 24
INDEXED = ("material", "material_scrap", "tool_material")
FAMILY_INDEX = {"Plastics - commodity": "ppi_resins", "Plastics - engineering": "ppi_resins", "Rubber": "rubber",
                "Aluminium - casting alloys": "aluminium", "Aluminium - wrought (sheet, extrusion, bar)": "aluminium",
                "Zinc alloys": "zinc", "Copper & copper alloys": "copper", "Stainless steel": "nickel", "Cast iron": "iron_ore",
                "Carbon & alloy steel (bar, forging)": "ppi_steel", "Sheet & strip steel": "ppi_steel"}


def _months(end: str, n: int) -> list[str]:
    return crb.month_list(end, n)


def index_key(category: str, item: str) -> str | None:
    if category == "power":
        return "ppi_power"
    if category == "freight":
        return "ppi_sea" if "sea" in item.lower() else None
    if category not in INDEXED:
        return None
    ix = crb.index_for(item)
    if ix:
        return ix
    if category == "tool_material":
        return "ppi_steel"
    return FAMILY_INDEX.get(crb.family_of(item))


def _at_or_before(values: dict, m: str) -> str | None:
    ms = [p for p in values if len(p) == 7 and p <= m]
    return max(ms) if ms else None


def _fx(series: dict, cur: str, m: str) -> float | None:
    if cur in ("", "USD"):
        return 1.0
    if cur not in crb.FX_FRED:
        return None
    v = series.get(f"fx_{cur}", {}).get("values", {}).get(m)
    if v is None:
        return None
    return 1 / v if crb.FX_FRED[cur][1] else v


def _semester(m: str) -> str:
    return f"{m[:4]}-S{1 if int(m[5:]) <= 6 else 2}"


def backfill(hist: dict, end: str | None = None, months: int = MONTHS) -> dict:
    """Write the missing history. Returns counts per category."""
    end = end or rates.current_month()
    window = _months(end, months)
    start = window[0]
    series = hist.get("series", {})
    ilo = hist.get("ilo", {})
    today = date.today().isoformat()
    with closing(rates._connect()) as con:
        rows = [rates._row(r) for r in con.execute(
            "SELECT * FROM rates WHERE status = 'approved' ORDER BY category, item, country, month, approved_date, id")]
        taken = {(r[0], r[1], r[2], r[3]) for r in con.execute(
            "SELECT category, item, country, month FROM rates WHERE status != 'rejected'")}
    first: dict[tuple, dict] = {}
    for r in rows:
        first.setdefault((r["category"], r["item"], r["country"]), r)
    out: dict[str, int] = {}
    new: list[dict] = []

    def add(base, m, value, how, example):
        if (base["category"], base["item"], base["country"], m) in taken or value is None or value < 0:
            return
        new.append({"category": base["category"], "item": base["item"], "country": base["country"],
                    "value": crb_round(value), "unit": base["unit"], "currency": base["currency"], "month": m,
                    "source": how, "source_url": "", "fetched_date": today, "status": "approved", "approved_by": USER,
                    "approved_date": today, "comment": f"from {base['value']} ({base['month']})",
                    "is_example": 1 if example else 0, "origin": ORIGIN, "created_at": today})
        taken.add((base["category"], base["item"], base["country"], m))
        out[base["category"]] = out.get(base["category"], 0) + 1

    inr = series.get("fx_INR", {}).get("values", {})
    for (cat, item, country), base in first.items():
        a = base["month"]
        if a <= start:
            continue
        todo = [m for m in window if m < a]
        cur = base["currency"]
        if cat == "forex":
            for m in todo:
                if item == "USD":
                    v = inr.get(m)
                else:
                    per = _fx(series, item, m)
                    if per is None and item not in crb.FX_FRED:
                        wb = series.get(f"fxwb_{item}", {}).get("values", {})
                        per = wb.get(m[:4])
                    v = inr[m] / per if inr.get(m) and per else None
                add(base, m, v, f"Market history: INR per {item}, monthly average (FRED / World Bank)", False)
            continue
        if cat == "power":
            geo = crb.COUNTRY_SOURCES.get(country, (None, None))[1]
            euro = series.get(f"elec_eurostat_{geo}", {}).get("values", {}) if geo else {}
            if euro and cur == "EUR":
                for m in todo:
                    add(base, m, euro.get(_semester(m)), f"Market history: Eurostat nrg_pc_205 {geo} {_semester(m)}", False)
                continue
        if cat == "labour_salary":
            iso3 = crb.COUNTRY_SOURCES.get(country, ("",))[0]
            wage = (ilo.get("hourly_by_skill", {}).get(f"{iso3}|OCU_SKILL_TOTAL|CUR_TYPE_LCU")
                    or ilo.get("monthly_manufacturing", {}).get(f"{iso3}|ECO_ISIC4_C|CUR_TYPE_LCU") or {})
            ya = max((y for y in wage if y <= a[:4]), default=None)
            for m in todo:
                yb = max((y for y in wage if y <= m[:4]), default=None)
                if ya and yb:
                    add(base, m, base["value"] * wage[yb]["value"] / wage[ya]["value"],
                        f"INDICATIVE history: × ILOSTAT wage {yb}/{ya} ({iso3})", True)
            if wage:
                continue
        ix = index_key(cat, item)
        vals = series.get(ix, {}).get("values", {}) if ix else {}
        ia = _at_or_before(vals, a) if vals else None
        if ix and ia:
            name = (crb.COMMODITIES.get(ix) or crb.INDICES.get(ix) or crb.ENERGY.get(ix) or crb.TRANSPORT.get(ix) or ("", ix))[1]
            fa = _fx(series, cur, ia)
            for m in todo:
                im = _at_or_before(vals, m)
                if not im:
                    continue
                ratio = vals[im] / vals[ia]
                fm = _fx(series, cur, im)
                if fa and fm:
                    ratio *= fm / fa
                add(base, m, base["value"] * ratio, f"INDICATIVE history: {name} {im} ÷ {ia} incl. forex = ×{ratio:.4f}", True)
            continue
        add(base, start, base["value"], "INDICATIVE history: same as the first rate (no free index for it)", True)

    if new:
        cols = list(new[0])
        with closing(rates._connect()) as con, con:
            con.executemany(f"INSERT INTO rates ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                            [[r[c] for c in cols] for r in new])
    return {"months": f"{start}..{end}", "written": out, "total": len(new)}


def crb_round(v: float) -> float:
    from .country_rates import _round
    return _round(v)
