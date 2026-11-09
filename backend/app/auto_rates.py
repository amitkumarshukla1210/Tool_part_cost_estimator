"""Monthly automatic country rate update (roadmap stage 52).

Once a month (when the app starts in a new month, by Admin → Monthly rates → Update rates now, or DTC_Country_Rates.bat)
the free official sources are downloaded (country_rate_book.fetch) and every country of Master data → Countries gets a
NEW APPROVED rate version for the month, written as the system user "Auto monthly update":

    forex           INR per currency = market monthly average (FRED; VND: World Bank yearly average)
    material        every RM grade        = last approved rate × (market index × local currency per USD) ratio
    tool_material   every tool steel      = same, with the index the grade follows (country_rate_book.index_for)
    material_scrap  scrap value           = same index as its grade
    power           Germany (EU): Eurostat half-yearly industrial price; other countries: last rate × US PPI electric power ratio
    labour_salary   every salary          = last salary × ILOSTAT yearly wage change, when ILO publishes a newer year

The ratio runs from the index month the last rate stands for (an auto rate says it in its source, "index 2026-08→2026-09";
a typed rate stands for the latest index month up to its own month) to the latest published index month. No newer
index → no new version. Machine hour and labour rates are formulas over these inputs, so they follow by themselves.

Admin stays in charge: any rate can be edited on the Rates page (a new version). A month that already has a version of
a rate (typed by someone, or auto) is never written again by this update, and the next update starts from the latest
approved version - so an admin's value is the base from then on. An EXAMPLE base gives an EXAMPLE result.
"""

from __future__ import annotations

import argparse
import re
import threading
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

from . import costing_db, costing_setup, country_rate_book as crb, rates

SYSTEM_USER = "Auto monthly update"
ORIGIN = "auto monthly"
_LOCK = threading.Lock()
TAG = re.compile(r"index (\d{4}-\d{2})→(\d{4}-\d{2})")
ILO_TAG = re.compile(r"ILO (\d{4})→(\d{4})")
EURO_TAG = re.compile(r"Eurostat (\d{4}-S[12])")
FX_TAG = re.compile(r"market (\d{4}-\d{2})")


def _db():
    con = costing_db.connect()
    con.execute("CREATE TABLE IF NOT EXISTS auto_rate_state (key TEXT PRIMARY KEY, value TEXT)")
    return con


def state(key: str, default: str = "") -> str:
    with closing(_db()) as con:
        r = con.execute("SELECT value FROM auto_rate_state WHERE key = ?", (key,)).fetchone()
    return r[0] if r else default


def set_state(key: str, value: str) -> None:
    with closing(_db()) as con, con:
        con.execute("INSERT INTO auto_rate_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value))


def _round(v: float) -> float:
    from .country_rates import _round as r
    return r(v)


def _has_version(cat: str, item: str, country: str, month: str) -> bool:
    with closing(rates._connect()) as con:
        return con.execute("SELECT 1 FROM rates WHERE category=? AND item=? AND country=? AND month=? AND status != 'rejected'",
                           (cat, item, country, month)).fetchone() is not None


def _write(base: dict, value: float, month: str, source: str, url: str, comment: str) -> dict:
    return rates.create({"category": base["category"], "item": base["item"], "country": base["country"], "value": _round(value),
                         "unit": base["unit"], "currency": base["currency"], "month": month, "source": source,
                         "source_url": url, "fetched_date": date.today().isoformat(), "comment": comment,
                         "is_example": base["is_example"]}, approve=True, origin=ORIGIN, approver=SYSTEM_USER, system=True)


def _latest_rates(cat: str, country: str, month: str) -> list[dict]:
    return [r["approved"] for r in rates.current(month, country, cat) if r["approved"] and r["country"] == country]


def _months(values: dict) -> list[str]:
    return sorted(p for p in values if re.fullmatch(r"\d{4}-\d{2}", p))


def _fx_per_usd(series: dict, cur: str, m: str) -> float | None:
    """Local currency per USD in month m (None: not published)."""
    if cur == "USD":
        return 1.0
    if cur not in crb.FX_FRED:
        return None
    v = series.get(f"fx_{cur}", {}).get("values", {}).get(m)
    if v is None:
        return None
    return 1 / v if crb.FX_FRED[cur][1] else v


def index_step(series: dict, ix: str, cur: str, base: dict) -> tuple[str, str, float] | None:
    """(from index month, to index month, ratio) for a rate, or None when there is no newer index month."""
    vals = series.get(ix, {}).get("values", {})
    months = _months(vals)
    if not months:
        return None
    t = TAG.search(base.get("source") or "")
    start = t.group(2) if t else next((m for m in reversed(months) if m <= base["month"]), None)
    end = months[-1]
    if not start or end <= start:
        return None
    ratio = vals[end] / vals[start]
    fx_a, fx_b = _fx_per_usd(series, cur, start), _fx_per_usd(series, cur, end)
    if fx_a and fx_b:                                   # the index is in USD: the local price also moves with the forex
        ratio *= fx_b / fx_a
    return start, end, ratio


def _index_name(ix: str) -> tuple[str, str]:
    for table in (crb.COMMODITIES, crb.INDICES, crb.ENERGY):
        if ix in table:
            sid, name = table[ix][0], table[ix][1]
            return name, crb.FRED_PAGE.format(id=sid)
    return ix, ""


def apply(hist: dict, month: str | None = None) -> dict:
    """Write this month's approved rates from the downloaded history. Returns counts and the log."""
    month = month or rates.current_month()
    series = hist.get("series", {})
    countries = costing_setup.tables()["countries"]
    out = {"month": month, "written": {}, "kept": 0, "unchanged": 0, "log": []}

    def wrote(cat):
        out["written"][cat] = out["written"].get(cat, 0) + 1

    # forex (country '')
    inr = series.get("fx_INR", {}).get("values", {})
    if inr:
        m_last = _months(inr)[-1]
        for base in _latest_rates("forex", "", month):
            cur = base["item"]
            if _has_version("forex", cur, "", month):
                out["kept"] += 1
                continue
            t = FX_TAG.search(base.get("source") or "")
            if cur == "USD":
                v, m_used, how = inr[m_last], m_last, f"INR per USD {inr[m_last]:.4f}"
            elif cur in crb.FX_FRED:
                per = _fx_per_usd(series, cur, m_last)
                if not per:
                    continue
                v, m_used, how = inr[m_last] / per, m_last, f"INR per USD {inr[m_last]:.4f} ÷ {cur} per USD {per:.4f}"
            else:
                wb = series.get(f"fxwb_{cur}", {}).get("values", {})
                if not wb:
                    continue
                y = max(wb)
                yr = [inr[m] for m in inr if m.startswith(y)]
                if not yr:
                    continue
                v, m_used = (sum(yr) / len(yr)) / wb[y], f"{y}-12"
                how = f"INR per USD average {y} ÷ {cur} per USD {wb[y]:.2f} (World Bank, yearly)"
            if t and t.group(1) >= m_used:
                out["unchanged"] += 1
                continue
            _write(base, v, month, f"{SYSTEM_USER}: market {m_used}", crb.FRED_PAGE.format(id="EXINUS"), how)
            wrote("forex")
    for c in countries:
        code, cur = c["code"], c["currency"]
        # grades, tool steels, scrap: index-linked
        for cat in ("material", "tool_material", "material_scrap"):
            for base in _latest_rates(cat, code, month):
                if _has_version(cat, base["item"], code, month):
                    out["kept"] += 1
                    continue
                ix = crb.index_for(base["item"])
                if not ix or ix not in series:
                    continue
                step = index_step(series, ix, base["currency"] or cur, base)
                if not step:
                    out["unchanged"] += 1
                    continue
                a, b, ratio = step
                name, url = _index_name(ix)
                _write(base, base["value"] * ratio, month, f"{SYSTEM_USER}: index {a}→{b} ×{ratio:.4f}", url,
                       f"{base['value']} ({base['month']}) × {name} {a}→{b} incl. {base['currency'] or cur} per USD = ×{ratio:.4f}")
                wrote(cat)
        # electricity
        geo = crb.COUNTRY_SOURCES.get(code, (None, None))[1]
        for base in _latest_rates("power", code, month):
            if _has_version("power", base["item"], code, month):
                out["kept"] += 1
                continue
            euro = series.get(f"elec_eurostat_{geo}", {}).get("values", {}) if geo else {}
            if euro and (base["currency"] or cur) == "EUR":
                p = max(euro)
                t = EURO_TAG.search(base.get("source") or "")
                if t and t.group(1) >= p:
                    out["unchanged"] += 1
                    continue
                _write(base, euro[p], month, f"{SYSTEM_USER}: Eurostat {p}", crb.EUROSTAT_PAGE,
                       f"Eurostat nrg_pc_205 {geo} {p}: non-household 2-20 GWh/yr, excl. VAT and recoverable taxes")
                wrote("power")
                continue
            step = index_step(series, "ppi_power", base["currency"] or cur, base)
            if not step:
                out["unchanged"] += 1
                continue
            a, b, ratio = step
            name, url = _index_name("ppi_power")
            _write(base, base["value"] * ratio, month, f"{SYSTEM_USER}: index {a}→{b} ×{ratio:.4f}", url,
                   f"{base['value']} ({base['month']}) × {name} {a}→{b} incl. forex = ×{ratio:.4f} (no free tariff series)")
            wrote("power")
        # salaries: ILOSTAT yearly wage change
        iso3 = crb.COUNTRY_SOURCES.get(code, ("",))[0]
        ilo = hist.get("ilo", {})
        wage = (ilo.get("hourly_by_skill", {}).get(f"{iso3}|OCU_SKILL_TOTAL|CUR_TYPE_LCU")
                or ilo.get("monthly_manufacturing", {}).get(f"{iso3}|ECO_ISIC4_C|CUR_TYPE_LCU") or {})
        if wage:
            years = sorted(wage)
            y_new = years[-1]
            key = f"ilo_year:{code}"
            y_old = state(key)
            if not y_old:                               # first sight: today's salaries already stand for this year
                set_state(key, y_new)
                out["log"].append(f"{code}: ILO wage baseline {y_new} recorded; salaries change when a newer year is published")
            elif y_new > y_old and y_old in wage:
                ratio = wage[y_new]["value"] / wage[y_old]["value"]
                for base in _latest_rates("labour_salary", code, month):
                    if _has_version("labour_salary", base["item"], code, month):
                        out["kept"] += 1
                        continue
                    _write(base, base["value"] * ratio, month, f"{SYSTEM_USER}: ILO {y_old}→{y_new} ×{ratio:.4f}", crb.ILO_PAGE,
                           f"{base['value']} × ILOSTAT mean earnings {iso3} {y_old}→{y_new} ({wage[y_old]['value']:g} → "
                           f"{wage[y_new]['value']:g} {cur}) = ×{ratio:.4f}")
                    wrote("labour_salary")
                set_state(key, y_new)
    return out


def run(user: str = SYSTEM_USER, out_dir: Path | None = None, http=crb._http, ilo_files: list[Path] | None = None,
        build: bool = True, today: date | None = None) -> dict:
    """Download, write this month's rates, build the workbooks. One run at a time."""
    if not _LOCK.acquire(blocking=False):
        return {"status": "busy", "message": "An update is already running."}
    try:
        from . import rate_update
        out_dir = Path(out_dir or crb.default_out())
        countries = costing_setup.tables()["countries"]
        started = datetime.now().isoformat(timespec="seconds")      # the history keeps only its last 60 runs: select by time
        crb.fetch(out_dir, countries, http, today)
        if ilo_files:
            crb.import_ilo(out_dir, ilo_files, today)
        hist = crb.load_history(out_dir)
        res = apply(hist)
        n = sum(res["written"].values())
        last_log = [x for r in hist.get("runs", []) if r.get("at", "") >= started for x in r.get("log", [])]   # this refresh
        fails = [line for line in last_log if line.startswith("FAILED") and "ILOSTAT" not in line]   # ILO: refused by design,
        ilo_note = any(line.startswith("FAILED ILOSTAT") for line in last_log)                        # saved files are used
        msg = (f"{n} new approved rates for {res['month']} ({', '.join(f'{k} {v}' for k, v in res['written'].items()) or 'none'}); "
               f"{res['kept']} kept (already set this month), {res['unchanged']} without a newer index"
               + (f"; {len(fails)} source(s) failed" if fails else "")
               + ("; ILOSTAT: saved wage data used (new year: DTC_Country_Rates.bat --ilo-file)" if ilo_note else ""))
        rate_update._log("Auto monthly update", "ok" if not fails else "partial", msg, n, user)
        set_state("last_month", res["month"])
        set_state("last_run", datetime.now().isoformat(timespec="seconds"))
        set_state("last_message", msg)
        paths = crb.run(None, out_dir, offline=True, today=today) if build else []
        return {"status": "ok", "message": msg, "written": res["written"], "log": res["log"] + fails,
                "workbooks": [str(p) for p in paths], "folder": str(out_dir)}
    except Exception as exc:  # noqa: BLE001 - the app keeps running; the last approved rates stay in use
        try:
            from . import rate_update
            rate_update._log("Auto monthly update", "failed", str(exc), 0, user)
        except Exception:  # noqa: BLE001
            pass
        set_state("last_message", f"FAILED: {exc}")
        return {"status": "failed", "message": str(exc)}
    finally:
        _LOCK.release()


def status() -> dict:
    return {"last_month": state("last_month"), "last_run": state("last_run"), "last_message": state("last_message"),
            "this_month": rates.current_month(), "due": state("last_month") != rates.current_month(),
            "running": _LOCK.locked(), "folder": str(crb.default_out())}


def run_if_due() -> dict | None:
    """App start: once per new month, in the background."""
    if state("last_month") == rates.current_month():
        return None
    return run()


def start_in_background() -> threading.Thread:
    t = threading.Thread(target=run_if_due, name="auto-rates", daemon=True)
    t.start()
    return t


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Monthly country rate update: new approved rates + country rate book.")
    ap.add_argument("--out", help="folder of the workbooks (default: DTC_Data/country_rates or data/country_rates)")
    ap.add_argument("--ilo-file", action="append", default=[], help="ILOSTAT CSV or a folder with them; repeatable")
    a = ap.parse_args(argv)
    res = run("DTC_Country_Rates.bat", Path(a.out) if a.out else None, ilo_files=[Path(f) for f in a.ilo_file])
    print(res.get("message", ""))
    for line in res.get("log", []):
        print(line)
    for p in res.get("workbooks", []):
        print(f"Written: {p}")
    return 0 if res.get("status") in ("ok", "busy") else 1


if __name__ == "__main__":
    raise SystemExit(main())
