"""Monthly rate update (roadmap stage 12): free official sources, index-based proposals, always as DRAFTS.

    forex   European Central Bank euro reference rates (daily XML) -> INR per USD, EUR, CNY, JPY, KRW, THB
    index   World Bank WDI consumer price index (FP.CPI.TOTL, annual) per country -> index-based proposals:
            new rate = last approved rate × (latest index ÷ index of the year the rate was approved),
            for the categories switched on in Mould & die database → Update rules (EXAMPLE rates are left alone)

Nothing is approved here: every value arrives as a Draft on the Rate review page. A source that fails (network,
format, licence change) is logged and skipped; the last approved values stay in use and costing never breaks.
Run from the app ("Fetch now" on the Rates page) or monthly by GitHub Actions: python -m backend.app.rate_update
"""

from __future__ import annotations

import json
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import date, datetime

from . import costing_db, costing_setup, mould_db, rates

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
WB_URL = "https://api.worldbank.org/v2/country/{iso}/indicator/FP.CPI.TOTL?format=json&per_page=80"
WB_PAGE = "https://data.worldbank.org/indicator/FP.CPI.TOTL"
ECB_PAGE = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"
NO_WB = {"TW": "Taiwan is not published by the World Bank"}      # country code -> why there is no index
SIG = 5


def _http(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "DesignToCost-rate-update/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:      # honours HTTPS_PROXY
        return r.read()


def _db():
    con = costing_db.connect()
    con.execute("CREATE TABLE IF NOT EXISTS update_runs (id INTEGER PRIMARY KEY, at TEXT, source TEXT, status TEXT, "
                "message TEXT, created INTEGER, user TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS rate_indices (series TEXT, country TEXT, period TEXT, value REAL, source_url TEXT, "
                "fetched TEXT, PRIMARY KEY (series, country, period))")
    return con


def _round(v: float) -> float:
    from .country_rates import _round as r
    return r(v)


def _log(source: str, status: str, message: str, created: int, user: str) -> dict:
    row = {"at": datetime.now().isoformat(timespec="seconds"), "source": source, "status": status, "message": message,
           "created": created, "user": user}
    with closing(_db()) as con, con:
        con.execute("INSERT INTO update_runs (at, source, status, message, created, user) VALUES (:at, :source, :status, :message, :created, :user)", row)
    return row


def runs(limit: int = 30) -> list[dict]:
    with closing(_db()) as con:
        return [dict(r) for r in con.execute("SELECT * FROM update_runs ORDER BY id DESC LIMIT ?", (limit,))]


def _open_draft_exists(category, item, country, month, value) -> bool:
    with closing(rates._connect()) as con:
        return con.execute("SELECT 1 FROM rates WHERE category=? AND item=? AND country=? AND month=? AND status IN ('draft','reviewed') "
                           "AND ABS(value - ?) < 1e-12", (category, item, country, month, value)).fetchone() is not None


def _draft(cat, item, country, value, unit, currency, month, source, url, comment, example=False) -> bool:
    if _open_draft_exists(cat, item, country, month, value):
        return False
    rates.create({"category": cat, "item": item, "country": country, "value": value, "unit": unit, "currency": currency,
                  "month": month, "source": source, "source_url": url, "fetched_date": date.today().isoformat(),
                  "comment": comment, "is_example": example}, approve=False, origin="monthly update")
    return True


# ---------- forex: ECB ----------

def parse_ecb(xml: bytes) -> dict[str, float]:
    """Units of currency per 1 EUR."""
    root = ET.fromstring(xml)
    out = {"EUR": 1.0}
    for el in root.iter():
        if el.tag.endswith("Cube") and "currency" in el.attrib:
            out[el.attrib["currency"]] = float(el.attrib["rate"])
    return out


def fetch_forex(month: str, http=_http) -> tuple[int, str]:
    per_eur = parse_ecb(http(ECB_URL))
    if "INR" not in per_eur:
        raise ValueError("the ECB file has no INR rate")
    inr_per_eur = per_eur["INR"]
    have = {r["item"] for r in rates.current(month, "", "forex")}
    created, skipped = 0, []
    for cur in sorted(have):
        if cur not in per_eur:
            skipped.append(cur)
            continue
        value = _round(inr_per_eur / per_eur[cur])
        if _draft("forex", cur, "", value, f"INR per {cur}", "INR", month, "European Central Bank euro reference rates", ECB_PAGE,
                  f"{cur} per EUR {per_eur[cur]} and INR per EUR {inr_per_eur}: INR per {cur} = {inr_per_eur} ÷ {per_eur[cur]}"):
            created += 1
    return created, ("not published by the ECB: " + ", ".join(skipped)) if skipped else ""


# ---------- index: World Bank CPI ----------

def parse_wb(body: bytes) -> dict[str, float]:
    """{year: index} from a World Bank API v2 response; empty values left out."""
    data = json.loads(body)
    if not isinstance(data, list) or len(data) < 2 or not data[1]:
        return {}
    return {str(p["date"]): float(p["value"]) for p in data[1] if p.get("value") is not None}


def fetch_index(http=_http) -> tuple[int, str]:
    """Store the CPI series of every country in Countries. Returns (rows stored, notes)."""
    stored, notes = 0, []
    for c in costing_setup.tables()["countries"]:
        if c["code"] in NO_WB:
            notes.append(f"{c['code']}: {NO_WB[c['code']]}")
            continue
        try:
            series = parse_wb(http(WB_URL.format(iso=c["code"])))
        except Exception as exc:       # one country failing must not stop the others
            notes.append(f"{c['code']}: {exc}")
            continue
        with closing(_db()) as con, con:
            for year, v in series.items():
                con.execute("INSERT OR REPLACE INTO rate_indices VALUES ('cpi', ?, ?, ?, ?, ?)",
                            (c["code"], year, v, WB_URL.format(iso=c["code"]), date.today().isoformat()))
                stored += 1
    return stored, "; ".join(notes)


def index_series(country: str, series: str = "cpi") -> dict[str, float]:
    with closing(_db()) as con:
        return {r["period"]: r["value"] for r in con.execute("SELECT period, value FROM rate_indices WHERE series=? AND country=?", (series, country))}


def propose_by_index(month: str) -> tuple[int, str]:
    """Drafts for approved, non-EXAMPLE rates of the categories in Update rules: value × latest index ÷ index at approval."""
    rules = [r for r in mould_db.tables()["update_rules"] if r["enabled"]]
    created, notes = 0, []
    for rule in rules:
        for row in rates.current(month, None, rule["category"]):
            a = row["approved"]
            if not a or a["is_example"] or not a["country"]:
                continue
            ser = index_series(a["country"], rule["series"])
            if not ser:
                continue
            latest = max(ser)
            base_year = int(a["month"][:4])
            earlier = [y for y in ser if int(y) <= base_year]
            if not earlier or int(latest) <= base_year:
                continue
            ratio = ser[latest] / ser[max(earlier)]
            if abs(ratio - 1) < 0.0005:
                continue
            new = _round(a["value"] * ratio)
            if _draft(row["category"], row["item"], a["country"], new, a["unit"], a["currency"], month,
                      f"Index proposal ({rule['series'].upper()}, World Bank WDI)", WB_PAGE,
                      f"{a['value']} ({a['month']}) × index {ser[latest]:.2f} ({latest}) ÷ {ser[max(earlier)]:.2f} ({max(earlier)}) = {new}. "
                      "A proxy: replace with a supplier quote or market price if you have one.", example=False):
                created += 1
    return created, "; ".join(notes)


# ---------- the run ----------

def run_update(month: str | None = None, user: str = "scheduled job", http=_http) -> dict:
    """Fetch every source; each is logged, a failing one is skipped. Returns the log lines of this run."""
    month = month or rates.current_month()
    out = []
    for source, fn in (("Forex · ECB", lambda: fetch_forex(month, http)),
                       ("Price index · World Bank CPI", lambda: fetch_index(http)),
                       ("Index-based proposals", lambda: propose_by_index(month))):
        try:
            n, note = fn()
            out.append(_log(source, "ok", note or "done", n, user))
        except Exception as exc:
            out.append(_log(source, "failed", f"{exc}. The last approved values stay in use.", 0, user))
    return {"month": month, "runs": out, "drafts": sum(r["created"] for r in out if r["source"] != "Price index · World Bank CPI")}


if __name__ == "__main__":
    res = run_update(user="GitHub Actions")
    for r in res["runs"]:
        print(f"{r['source']}: {r['status']} ({r['created']}) {r['message']}")
