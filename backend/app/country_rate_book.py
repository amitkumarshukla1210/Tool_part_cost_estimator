"""Country rate book (roadmap stage 51): one Excel workbook per country, last 24 months, every value with its source.

    python -m backend.app.country_rate_book                    # all countries of Master data → Countries
    python -m backend.app.country_rate_book --countries CN,IN  # some of them
    python -m backend.app.country_rate_book --offline          # no download: build from the saved history only

Sheets: Summary · RM_Price · Labour · Process_Cost · Electricity · Transport · Forex · Sources.

Two kinds of numbers, never mixed up:

* MARKET  - downloaded from free official sources (FRED / IMF commodity prices, FRED forex, ILOSTAT earnings by skill
            level, Eurostat industrial electricity, World Bank forex). Real history, monthly / half-yearly / yearly as
            the source publishes it. A month the source has not published stays EMPTY - nothing is filled in or guessed.
* APP     - the approved rates of this tool (rate library, machine hour rates and labour rates of rate_engine) with
            their month, status and source. EXAMPLE rates are marked as such until you replace them.

Downloads are kept in a history file (append-only: a new month is added, a month already there is kept as first
fetched unless the source revised it - the revision is then logged). A source that fails is logged and the saved
history is used, so the workbooks are always built. Nothing in Master data is changed.

Monthly: GitHub Actions (monthly-rate-update.yml) builds the workbooks and attaches them to the run; on the Windows
kit DTC_Country_Rates.bat does the same into DTC_Data\\country_rates.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import urllib.request
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

MONTHS = 24

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}&cosd={start}"
FRED_PAGE = "https://fred.stlouisfed.org/series/{id}"
ILO_DATA = ("https://sdmx.ilo.org/rest/data/ILO,{flow}/{areas}.A..SEX_T.{cls}.?startPeriod={start}")
ILO_PAGE = "https://ilostat.ilo.org/data/"
EUROSTAT = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nrg_pc_205?format=JSON&lang=EN"
            "&geo={geo}&nrg_cons=MWH2000-19999&unit=KWH&tax=X_VAT&currency={cur}&sinceTimePeriod={since}")
EUROSTAT_PAGE = "https://ec.europa.eu/eurostat/databrowser/view/nrg_pc_205/default/table"
WB_FX = "https://api.worldbank.org/v2/country/{iso2}/indicator/PA.NUS.FCRF?format=json&per_page=20"
WB_FX_PAGE = "https://data.worldbank.org/indicator/PA.NUS.FCRF"

# --- market series (what is downloaded; no values here) ----------------------------------------------------------
# key: (FRED id, name, source unit, sheet, conversion to a per-kg price: factor applied to the USD value, or None)
COMMODITIES = {
    "aluminium": ("PALUMUSDM", "Aluminium (LME, 99.5% min, CIF UK ports)", "USD/t", 1 / 1000),
    "copper": ("PCOPPUSDM", "Copper (LME grade A cathode)", "USD/t", 1 / 1000),
    "nickel": ("PNICKUSDM", "Nickel (LME, melting grade)", "USD/t", 1 / 1000),
    "zinc": ("PZINCUSDM", "Zinc (LME high grade)", "USD/t", 1 / 1000),
    "lead": ("PLEADUSDM", "Lead (LME, 99.97% pure)", "USD/t", 1 / 1000),
    "tin": ("PTINUSDM", "Tin (LME standard grade)", "USD/t", 1 / 1000),
    "iron_ore": ("PIORECRUSDM", "Iron ore (China import, 62% Fe fines, CFR)", "USD/dmt", 1 / 1000),
    "rubber": ("PRUBBUSDM", "Natural rubber (SGP/MYS, RSS3)", "US cents/lb", 1 / 100 / 0.45359237),
    "brent": ("POILBREUSDM", "Crude oil Brent (plastics and freight driver)", "USD/bbl", None),
}
INDICES = {   # US producer price indices: the only free monthly series for steel and plastic resins (trend, not price)
    "ppi_steel": ("WPU1017", "US PPI: steel mill products (index 1982=100)", "index"),
    "ppi_iron_steel": ("WPU101", "US PPI: iron and steel (index 1982=100)", "index"),
    "ppi_resins": ("WPU066", "US PPI: plastic resins and materials (index 1982=100)", "index"),
    "ppi_rubber_plastic": ("WPU07210603", "US PPI: plastic products for industry (index)", "index"),
}
ENERGY = {
    "gas_eu": ("PNGASEUUSDM", "Natural gas, Europe (TTF)", "USD/MMBtu"),
    "coal_au": ("PCOALAUUSDM", "Coal, Australia (thermal)", "USD/t"),
    "ppi_power": ("PCU221122221122", "US PPI: electric power distribution (index)", "index"),
}
TRANSPORT = {
    "brent": ("POILBREUSDM", "Crude oil Brent", "USD/bbl"),
    "diesel_us": ("GASDESW", "US on-highway diesel retail (monthly mean of weekly)", "USD/gal"),
    "ppi_sea": ("PCU483111483111", "US PPI: deep sea freight transportation (index)", "index"),
    "ppi_truck": ("PCU484121484121", "US PPI: general freight trucking, long distance TL (index)", "index"),
}
# currency -> FRED series of currency units per 1 USD (EUR is published the other way round: USD per EUR)
FX_FRED = {"INR": ("EXINUS", False), "CNY": ("EXCHUS", False), "KRW": ("EXKOUS", False), "JPY": ("EXJPUS", False),
           "TWD": ("EXTAUS", False), "THB": ("EXTHUS", False), "EUR": ("EXUSEU", True), "MXN": ("EXMXUS", False)}
# ISO-3 for ILOSTAT, Eurostat geo code, and where the official industrial electricity tariff is published
COUNTRY_SOURCES = {
    "IN": ("IND", None, "State electricity regulatory commission (SERC) tariff order, HT industrial category", ""),
    "CN": ("CHN", None, "Provincial grid company / NDRC price bureau: general industrial & commercial tariff", ""),
    "KR": ("KOR", None, "KEPCO electricity tariff table: industrial (B) rate", "https://online.kepco.co.kr/"),
    "JP": ("JPN", None, "Regional EPCO high-voltage tariff / METI statistics", "https://www.enecho.meti.go.jp/"),
    "TW": ("TWN", None, "Taipower electricity price schedule: high-voltage industrial", "https://www.taipower.com.tw/"),
    "TH": ("THA", None, "PEA / MEA tariff: large general service (industrial)", "https://www.pea.co.th/"),
    "VN": ("VNM", None, "EVN retail tariff: manufacturing customers by voltage", "https://www.evn.com.vn/"),
    "DE": ("DEU", "DE", "Eurostat nrg_pc_205 (downloaded)", EUROSTAT_PAGE),
    "US": ("USA", None, "US EIA Electric Power Monthly, table 5.6.A industrial average price", "https://www.eia.gov/electricity/monthly/"),
}
SKILLS = [("OCU_SKILL_L1", "Skill level 1 - helper / elementary"),
          ("OCU_SKILL_L2", "Skill level 2 - operator / craft / machinist"),
          ("OCU_SKILL_L3-4", "Skill level 3-4 - technician / engineer / designer"),
          ("OCU_SKILL_TOTAL", "All skill levels")]
# which market index an RM grade follows (first keyword found in the grade name, lower case)
GRADE_INDEX = [
    (("stainless", "ss3", "ss4", "sus"), "nickel"), (("alumin", "adc", "lm6", "a380", "a356", "alsi"), "aluminium"),
    (("copper", "brass", "bronze", "cw6", "phosphor"), "copper"), (("zinc", "zamak", "zama"), "zinc"),
    (("tin",), "tin"), (("lead",), "lead"),
    (("cast iron", "fg2", "fg3", "sg iron", "ductile", "pig iron"), "iron_ore"), (("rubber", "epdm", "nbr", "silicone"), "rubber"),
    (("pp", "abs", "pa6", "pa66", "pc", "pom", "pbt", "pe", "hdpe", "ldpe", "pvc", "eps", "pet", "pmma", "tpe", "nylon",
      "polymer", "plastic", "glass fill", "gf"), "ppi_resins"),
    (("steel", "crca", "hr ", "hrpo", "gi", "spcc", "en", "c45", "p20", "h13", "d2", "skd", "s50c", "1.23", "die", "tool",
      "bar", "sheet", "dc0"), "ppi_steel"),
]

FONT = Font(name="Arial", size=10)
BOLD = Font(name="Arial", size=10, bold=True)
TITLE = Font(name="Arial", size=14, bold=True)
SMALL = Font(name="Arial", size=9, italic=True, color="555555")
HEAD_FILL = PatternFill("solid", fgColor="1F3864")
HEAD_FONT = Font(name="Arial", size=10, bold=True, color="FFFFFF")
MARKET_FILL = PatternFill("solid", fgColor="E2EFDA")     # downloaded market data
APP_FILL = PatternFill("solid", fgColor="DDEBF7")        # approved rate of this tool
EXAMPLE_FILL = PatternFill("solid", fgColor="FCE4D6")    # EXAMPLE / fallback value
ENTRY_FILL = PatternFill("solid", fgColor="FFFF00")      # for you to fill in
THIN = Border(*(Side(style="thin", color="BFBFBF"),) * 4)


# ------------------------------------------------------------------ downloads
def _http(url: str, accept: str | None = None) -> bytes:
    headers = {}            # Python's own User-Agent: FRED's front end refuses unknown agent names
    if accept:
        headers["Accept"] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:   # honours HTTPS_PROXY
        return r.read()


def parse_fred(body: bytes) -> dict[str, float]:
    """FRED graph CSV -> {YYYY-MM: value} (weekly / daily series averaged per month; '.' = missing)."""
    sums: dict[str, list[float]] = {}
    for row in list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))[1:]:
        if len(row) < 2 or not re.match(r"\d{4}-\d{2}-\d{2}", row[0]):
            continue
        try:
            v = float(row[1])
        except ValueError:
            continue
        sums.setdefault(row[0][:7], []).append(v)
    return {m: sum(v) / len(v) for m, v in sums.items()}


def parse_ilo(body: bytes) -> list[dict]:
    """ILOSTAT SDMX-CSV -> rows {area, cls, cur, year, value, source, note}."""
    out = []
    for r in csv.DictReader(io.StringIO(body.decode("utf-8-sig"))):
        try:
            v = float(r["OBS_VALUE"])
        except (KeyError, ValueError, TypeError):
            continue
        out.append({"flow": r.get("DATAFLOW", ""), "sex": r.get("SEX", "SEX_T"),
                    "area": r.get("REF_AREA", ""), "cls": r.get("OCU") or r.get("ECO") or "", "cur": r.get("CUR", ""),
                    "year": str(r.get("TIME_PERIOD", "")), "value": v, "source": r.get("SOURCE", ""),
                    "note": r.get("NOTE_INDICATOR", "") or ""})
    return out


def parse_eurostat(body: bytes) -> dict[str, float]:
    """Eurostat JSON-stat with one value per time period -> {YYYY-S1: value}."""
    d = json.loads(body)
    tdim = d["dimension"]["time"]["category"]["index"]
    ids, sizes = d["id"], d["size"]
    strides, s = [], 1
    for n in reversed(sizes):
        strides.insert(0, s)
        s *= n
    t_stride = strides[ids.index("time")]
    out = {}
    for period, pos in tdim.items():
        v = d["value"].get(str(pos * t_stride))
        if v is not None:
            out[period] = float(v)
    return out


def parse_wb(body: bytes) -> dict[str, float]:
    data = json.loads(body)
    rows = data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []
    return {r["date"]: float(r["value"]) for r in rows if r.get("value") is not None}


ILO_TAGS = {"EHRA_SEX_OCU": "hourly_by_skill", "EMTA_SEX_ECO": "monthly_manufacturing"}
ILO_KEEP = {"hourly_by_skill": {s for s, _ in SKILLS}, "monthly_manufacturing": {"ECO_ISIC4_C"}}


def merge_ilo(hist: dict, tag: str | None, rows: list[dict], log: list, today: date) -> int:
    """Add ILOSTAT rows (both sexes, the classes used here) to the history; a revised value is logged. Returns rows added."""
    n = 0
    for r in rows:
        t = tag or next((v for k, v in ILO_TAGS.items() if k in r.get("flow", "")), None)
        if not t or r.get("sex", "SEX_T") != "SEX_T" or r["cls"] not in ILO_KEEP[t]:
            continue
        store = hist.setdefault("ilo", {}).setdefault(t, {})
        k = f"{r['area']}|{r['cls']}|{r['cur']}"
        old = store.get(k, {}).get(r["year"])
        if old is not None and abs(old["value"] - r["value"]) > 1e-9:
            log.append(f"ILO {t} {k} {r['year']}: revised {old['value']:g} -> {r['value']:g}")
        store.setdefault(k, {})[r["year"]] = {"value": r["value"], "source": r["source"], "note": r["note"][:200],
                                              "fetched": today.isoformat()}
        n += 1
    return n


def import_ilo(out_dir: Path, files: list[Path], today: date | None = None) -> int:
    """ILOSTAT SDMX-CSV files downloaded by hand (data explorer → Download → CSV) into the history."""
    today = today or date.today()
    hist = load_history(out_dir)
    log: list[str] = []
    n = sum(merge_ilo(hist, None, parse_ilo(Path(f).read_bytes()), log, today) for f in files)
    hist.setdefault("runs", []).append({"at": datetime.now().isoformat(timespec="seconds"),
                                        "log": [f"ILOSTAT file import: {n} values from {len(files)} file(s)"] + log})
    out_dir.mkdir(parents=True, exist_ok=True)
    history_path(out_dir).write_text(json.dumps(hist, indent=1, sort_keys=True), encoding="utf-8")
    return n


def history_path(out_dir: Path) -> Path:
    return out_dir / "country_rate_book_history.json"


def load_history(out_dir: Path) -> dict:
    p = history_path(out_dir)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"series": {}, "ilo": {}, "runs": []}


def _merge(store: dict, key: str, new: dict[str, float], meta: dict, log: list) -> None:
    """Append-only: add new periods; a revised value replaces the old one and is logged."""
    s = store.setdefault(key, {"meta": meta, "values": {}})
    s["meta"] = meta
    for period, v in new.items():
        old = s["values"].get(period)
        if old is not None and abs(old - v) > 1e-9 * max(1.0, abs(old)):
            log.append(f"{key} {period}: revised by the source {old:g} -> {v:g}")
        s["values"][period] = v


def start_month(end: str, months: int = MONTHS) -> str:
    y, m = map(int, end.split("-"))
    m -= months - 1
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}"


def fetch(out_dir: Path, countries: list[dict], http=_http, today: date | None = None) -> dict:
    """Download every source; failures are logged and the saved history stays in use."""
    today = today or date.today()
    hist = load_history(out_dir)
    log: list[str] = []
    start = f"{today.year - 6}-01-01"          # long enough for the yearly labour figures (converted at that year's forex)
    fred = {**{k: (v[0], v[1], v[2]) for k, v in COMMODITIES.items()}, **INDICES, **ENERGY, **TRANSPORT}
    fred.update({f"fx_{c}": (sid, f"{c} per USD" if not inv else f"USD per {c}", "rate") for c, (sid, inv) in FX_FRED.items()})
    for key, (sid, name, unit) in fred.items():
        try:
            vals = parse_fred(http(FRED_CSV.format(id=sid, start=start)))
            if not vals:
                raise ValueError("no values in the answer")
            _merge(hist["series"], key, vals, {"name": name, "unit": unit, "publisher": "FRED, Federal Reserve Bank of St. Louis"
                   + (" (IMF Primary Commodity Prices)" if sid.startswith("P") and sid.endswith("USDM") else
                      " (US BLS)" if sid.startswith(("WPU", "PCU")) else " (US EIA)" if sid == "GASDESW" else
                      " (Federal Reserve H.10)"), "url": FRED_PAGE.format(id=sid), "series_id": sid,
                   "fetched": today.isoformat(), "frequency": "monthly"}, log)
        except Exception as exc:  # noqa: BLE001 - any failure: keep the history
            log.append(f"FAILED {key} ({sid}): {exc}")
    areas = "+".join(COUNTRY_SOURCES[c["code"]][0] for c in countries if c["code"] in COUNTRY_SOURCES)
    ilo_start = today.year - 6
    for flow, cls, tag in (("DF_EAR_EHRA_SEX_OCU_CUR_NB", "+".join(s for s, _ in SKILLS), "hourly_by_skill"),
                           ("DF_EAR_EMTA_SEX_ECO_CUR_NB", "ECO_ISIC4_C", "monthly_manufacturing")):
        url = ILO_DATA.format(flow=flow, areas=areas, cls=cls, start=ilo_start)
        try:
            rows = parse_ilo(http(url, "application/vnd.sdmx.data+csv;version=1.0.0"))
            if not rows:
                raise ValueError("no values in the answer")
            merge_ilo(hist, tag, rows, log, today)
        except Exception as exc:  # noqa: BLE001
            log.append(f"FAILED ILOSTAT {tag}: {exc} - download the CSV from the ILOSTAT data explorer and run with "
                       f"--ilo-file (the saved history stays in use)")
    for c in countries:
        geo = COUNTRY_SOURCES.get(c["code"], (None, None))[1]
        if not geo:
            continue
        for g in (geo, "EU27_2020"):
            try:
                vals = parse_eurostat(http(EUROSTAT.format(geo=g, cur="EUR", since=today.year - 4)))
                _merge(hist["series"], f"elec_eurostat_{g}", vals,
                       {"name": f"Electricity, non-household 2-20 GWh/yr, excl. VAT and recoverable taxes ({g})",
                        "unit": "EUR/kWh", "publisher": "Eurostat (nrg_pc_205)", "url": EUROSTAT_PAGE,
                        "fetched": today.isoformat(), "frequency": "half-yearly"}, log)
            except Exception as exc:  # noqa: BLE001
                log.append(f"FAILED Eurostat {g}: {exc}")
    for c in countries:
        if c["currency"] in FX_FRED or c["currency"] == "USD":
            continue
        try:
            vals = parse_wb(http(WB_FX.format(iso2=c["code"])))
            _merge(hist["series"], f"fxwb_{c['currency']}", vals,
                   {"name": f"{c['currency']} per USD, official rate, annual average", "unit": "rate",
                    "publisher": "World Bank WDI (PA.NUS.FCRF)", "url": WB_FX_PAGE, "fetched": today.isoformat(),
                    "frequency": "yearly"}, log)
        except Exception as exc:  # noqa: BLE001
            log.append(f"FAILED World Bank forex {c['currency']}: {exc}")
    hist["runs"].append({"at": datetime.now().isoformat(timespec="seconds"), "log": log})
    hist["runs"] = hist["runs"][-60:]
    out_dir.mkdir(parents=True, exist_ok=True)
    history_path(out_dir).write_text(json.dumps(hist, indent=1, sort_keys=True), encoding="utf-8")
    return hist


# ------------------------------------------------------------------ app data (read only)
def app_data(country: str, as_of: str | None = None) -> dict:
    from . import costing_setup, rate_engine, rates
    from .costing_db import connect

    as_of = as_of or rates.current_month()
    with connect() as con:
        con.row_factory = None
        rows = con.execute("SELECT category, item, country, value, unit, currency, month, source, status, approved_by "
                           "FROM rates WHERE status='approved' AND (country=? OR (category='forex' AND country='')) "
                           "ORDER BY category, item, month", (country,)).fetchall()
    keys = ["category", "item", "country", "value", "unit", "currency", "month", "source", "status", "approved_by"]
    approved = [dict(zip(keys, r)) for r in rows]
    for r in approved:
        r["is_example"] = "EXAMPLE" in (r["source"] or "").upper() or r["approved_by"] == "Example seed"
    ov = rate_engine.overview(country, as_of)

    def root(res):
        if "error" in res or "nodes" not in res:
            return None
        return res["nodes"][res["root"]]["value"]

    def example(res):
        return any((n.get("source") or {}).get("rate", {}).get("is_example") for n in (res.get("nodes") or {}).values())

    machines = [{"id": m["machine"]["machine_id"], "name": m["machine"]["name"], "process": m["machine"]["process"],
                 "kw": m["machine"]["power_kw"], "value": root(m), "currency": m.get("currency", ""),
                 "error": m.get("error", ""), "example": example(m) or m["machine"].get("is_example")} for m in ov["machines"]]
    labour = [{"grade": g["grade"]["grade"], "name": g["grade"]["name"], "value": root(g), "currency": g.get("currency", ""),
               "error": g.get("error", ""), "example": example(g)} for g in ov["labour"]]
    return {"as_of": as_of, "rates": approved, "machines": machines, "labour": labour,
            "country": ov["country"], "countries": costing_setup.tables()["countries"]}


# ------------------------------------------------------------------ workbook
def month_list(end: str, months: int = MONTHS) -> list[str]:
    y, m = map(int, start_month(end, months).split("-"))
    out = []
    for _ in range(months):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out


def _mlabel(m: str) -> str:
    return datetime.strptime(m, "%Y-%m").strftime("%b-%y")


def index_for(grade: str) -> str | None:
    g = f" {grade.lower()} "
    for words, key in GRADE_INDEX:
        for w in words:
            if (len(w) <= 3 and re.search(rf"(?<![a-z]){re.escape(w.strip())}(?![a-z])", g)) or (len(w) > 3 and w in g):
                return key
    return None


# Common grades by family (names and equivalents only - reference, no prices). Grades the tool already has are not repeated.
FAMILIES = [
    ("Carbon & alloy steel (bar, forging)", [
        ("EN8 / C45 / 080M40", "IS 1570 C40-C45, DIN 1.0503, AISI 1045, JIS S45C"), ("EN9 / C55", "DIN 1.0535, AISI 1055"),
        ("EN1A / 11SMnPb30", "free-cutting, DIN 1.0718"), ("EN19 / 42CrMo4", "DIN 1.7225, AISI 4140, SCM440"),
        ("EN24 / 34CrNiMo6", "DIN 1.6582, AISI 4340"), ("EN31 / 100Cr6", "bearing steel, DIN 1.3505, AISI 52100"),
        ("EN36 / 15NiCr13", "case hardening"), ("20MnCr5 / 16MnCr5", "case hardening, DIN 1.7147 / 1.7131"),
        ("SAE 1010 / 1018", "low carbon, C10 / C15"), ("SAE 8620", "DIN 1.6523, case hardening")]),
    ("Sheet & strip steel", [
        ("CRCA IS 513 D / DD / EDD", "DC01 / DC03 / DC04, JIS SPCC / SPCD / SPCE"), ("HR IS 1079 / HRPO", "DD11, JIS SPHC"),
        ("HR structural IS 2062 E250 / E350", "S235 / S355, ASTM A36"), ("GI / GP IS 277", "DX51D+Z, JIS SGCC"),
        ("Electro-galvanised (EG)", "DC01+ZE, SECC"), ("HSLA IS 5986", "S315MC / S355MC / S420MC"),
        ("CRNO electrical steel", "M400-50A / M470-50A")]),
    ("Stainless steel", [
        ("SS 304 / 304L", "1.4301 / 1.4307, SUS304"), ("SS 316 / 316L", "1.4401 / 1.4404, SUS316"), ("SS 202", "J4 / 201 series"),
        ("SS 409L", "1.4512, exhaust"), ("SS 410 / 420", "1.4006 / 1.4021, martensitic"), ("SS 430", "1.4016, SUS430"),
        ("SS 303", "1.4305, free-machining"), ("SS 17-4PH", "1.4542, precipitation hardening")]),
    ("Tool & mould steel", [
        ("P20 / 1.2311", "AISI P20, 3Cr2Mo"), ("P20+Ni / 1.2738", "718H"), ("H13 / 1.2344", "SKD61, 4Cr5MoSiV1"),
        ("H11 / 1.2343", "SKD6"), ("D2 / 1.2379", "SKD11, Cr12Mo1V1"), ("D3 / 1.2080", "SKD1, Cr12"),
        ("O1 / 1.2510", "SKS3, oil hardening"), ("A2 / 1.2363", "SKD12"), ("M2 / 1.3343", "HSS, SKH51"),
        ("S136 / 1.2083 ESR", "420 mod., mirror polish"), ("NAK80", "pre-hardened 40 HRC"), ("1.2316", "stainless mould steel"),
        ("1.2767", "45NiCrMo16"), ("C45 / S50C mould base", "1.0503 / 1.1730")]),
    ("Aluminium - casting alloys", [
        ("ADC12", "JIS ADC12, A383, AlSi11Cu3, IS LM24-like"), ("ALDC1 / ADC1", "A413, AlSi12"),
        ("ALDC2 / ADC3", "A360, AlSi10Mg (die casting)"), ("A380", "ADC10, AlSi8Cu3"), ("LM2", "BS 1490 LM2, AlSi10Cu2"),
        ("LM4", "AlSi5Cu3"), ("LM6", "AlSi12, A413.2"), ("LM24", "A380 equivalent"), ("LM25", "A356, AlSi7Mg"),
        ("A356-T6", "AlSi7Mg0.3"), ("AlSi9Cu3 (EN AC-46000)", "226"), ("AC4C / AC2B", "JIS gravity casting")]),
    ("Aluminium - wrought (sheet, extrusion, bar)", [
        ("1100 / 1050", "commercially pure"), ("3003 / 3105", "Al-Mn"), ("5052 / 5083", "Al-Mg"),
        ("6061-T6", "Al-Mg-Si"), ("6063-T6", "extrusion"), ("6082-T6", "HE30"), ("7075-T6", "aerospace, high strength"),
        ("2014 / 2024", "HE15, Al-Cu")]),
    ("Zinc alloys", [("Zamak 3", "ZnAl4, ZP3"), ("Zamak 5", "ZnAl4Cu1, ZP5"), ("ZA-8", "zinc-aluminium")]),
    ("Magnesium alloys", [("AZ91D", "die casting"), ("AM60B", "die casting")]),
    ("Copper & copper alloys", [
        ("ETP copper C11000", "Cu-ETP, busbar"), ("Brass CW614N / CuZn39Pb3", "free-cutting, C38500"),
        ("Brass CuZn37 / C27200", "sheet"), ("Phosphor bronze C51000", "CuSn5"), ("Gunmetal LG2", "CuSn5Zn5Pb5"),
        ("Beryllium copper C17200", "CuBe2")]),
    ("Cast iron", [("Grey iron FG220 / FG260", "EN-GJL-250, GG25"), ("SG iron 400/15, 500/7", "EN-GJS-400 / 500, GGG40 / 50"),
                   ("SG iron 600/3", "EN-GJS-600")]),
    ("Plastics - commodity", [
        ("PP homopolymer", ""), ("PP copolymer", "impact"), ("PP talc / mineral filled", "TD20 / TD40"),
        ("HDPE", ""), ("LDPE / LLDPE", ""), ("PVC rigid / flexible", ""), ("HIPS", ""), ("GPPS", "")]),
    ("Plastics - engineering", [
        ("ABS", "general / plating / V0"), ("PC", "polycarbonate"), ("PC/ABS", ""), ("PA6 / PA6 GF30", "nylon 6"),
        ("PA66 / PA66 GF30", "nylon 66"), ("POM", "acetal copolymer"), ("PBT / PBT GF30", ""), ("PMMA", "acrylic"),
        ("SAN / ASA", ""), ("PPS GF40", "high temperature"), ("PET / rPET", ""), ("TPE / TPU", "thermoplastic elastomer"),
        ("EPS bead", "expandable polystyrene")]),
    ("Rubber", [("Natural rubber RSS / ISNR", ""), ("EPDM", ""), ("NBR", "nitrile"), ("Silicone (VMQ)", "")]),
]


def family_of(grade: str) -> str:
    """Family of a grade of the tool, from its name (first match)."""
    g = f" {grade.lower()} "
    rules = [("Stainless steel", ("stainless", " ss ", "ss3", "ss4", "sus")),
             ("Aluminium - casting alloys", ("adc", "lm6", "lm2", "lm4", "lm24", "lm25", "a380", "a356", "a383", "alsi", "aldc")),
             ("Aluminium - wrought (sheet, extrusion, bar)", ("alumin",)),
             ("Zinc alloys", ("zinc", "zamak")), ("Magnesium alloys", ("magnesium", "az91", "am60")),
             ("Copper & copper alloys", ("copper", "brass", "bronze", "becu")),
             ("Cast iron", ("cast iron", "ductile", "sg ", "fg2")),
             ("Sheet & strip steel", ("crca", "galvan", " gi", " hr", "sheet", "d513", "dc0", "spcc")),
             ("Carbon & alloy steel (bar, forging)", ("steel", " en", "c45", "42crmo", "bar")),
             ("Plastics - commodity", ("pp ", "(polypropylene)", "pp copolymer", "pp talc", "hdpe", "ldpe", "pvc", "hips")),
             ("Plastics - engineering", ("abs", "pa6", "pa66", "pc", "pom", "pbt", "pet", "pmma", "eps")),
             ("Rubber", ("rubber", "epdm", "nbr", "silicone"))]
    for fam, words in rules:
        if any(w in g for w in words):
            return fam
    return "Other"


def _norm(text: str) -> str:
    t = text.lower().replace("stainless steel", "ss").replace("aluminium", "").replace("zinc", "")
    return re.sub(r"[^a-z0-9.]", "", t)


def in_tool(grade: str, known: set[str]) -> bool:
    """A catalogue grade the tool already has: one of its '/' names (e.g. 'ADC12', 'FG260', '1.2738') is in a grade name of
    the tool (2-letter names like 'PC' only at the start)."""
    names = [_norm(k) for k in known]
    for seg in grade.split("/"):
        n = _norm(seg.split(",")[0])
        if len(n) >= 3 and any(re.search(re.escape(n) + r"(?![0-9])", k) for k in names):     # ADC1 is not ADC12
            return True
        if len(n) == 2 and any(k.startswith(n) for k in names):
            return True
    return False


def last_pos(rng: str) -> str:
    """Position (1..n) of the last cell with a number in a one-row range."""
    first = rng.split(":")[0]
    return f"LOOKUP(2,1/ISNUMBER({rng}),COLUMN({rng})-COLUMN({first})+1)"


def delta(rng: str, n: int | None) -> str:
    """Formula text (no '='): latest value ÷ value n months earlier - 1; n None = ÷ first value of the range - 1."""
    p = last_pos(rng)
    base = f"INDEX({rng},{p}-{n})" if n else f"INDEX({rng},MATCH(TRUE,INDEX(ISNUMBER({rng}),0),0))"
    return f'IFERROR(INDEX({rng},{p})/{base}-1,"")'


class Sheet:
    def __init__(self, ws):
        self.ws, self.row = ws, 1

    def title(self, text, sub=""):
        self.ws.cell(self.row, 1, text).font = TITLE
        self.row += 1
        if sub:
            self.ws.cell(self.row, 1, sub).font = SMALL
            self.row += 1
        self.row += 1

    def head(self, values, col=1):
        for i, v in enumerate(values):
            c = self.ws.cell(self.row, col + i, v)
            c.font, c.fill, c.border = HEAD_FONT, HEAD_FILL, THIN
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        self.row += 1

    def put(self, col, value, fill=None, fmt=None, bold=False, comment=None):
        c = self.ws.cell(self.row, col, value)
        c.font, c.border = (BOLD if bold else FONT), THIN
        if fill:
            c.fill = fill
        if fmt:
            c.number_format = fmt
        if comment:
            c.comment = Comment(comment, "Design to Cost")
        return c

    def note(self, text):
        self.ws.cell(self.row, 1, text).font = SMALL
        self.row += 1


def _widths(ws, first=34, rest=11, cols=40, extra: dict | None = None):
    ws.column_dimensions["A"].width = first
    for i in range(2, cols + 1):
        ws.column_dimensions[get_column_letter(i)].width = rest
    for k, v in (extra or {}).items():
        ws.column_dimensions[k].width = v


def _chart(ws, title, ytitle, first_row, last_row, first_col, last_col, anchor, height=7.5, width=22):
    ch = LineChart()
    ch.title, ch.y_axis.title, ch.height, ch.width = title, ytitle, height, width
    data = Reference(ws, min_col=first_col - 1, max_col=last_col, min_row=first_row, max_row=last_row)
    ch.add_data(data, from_rows=True, titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=first_col, max_col=last_col, min_row=first_row - 1))
    ws.add_chart(ch, anchor)


def build(country_code: str, hist: dict, app: dict, months: int = MONTHS, end: str | None = None,
          today: date | None = None) -> Workbook:
    """Workbook for one country. `app` = app_data(country); `hist` = fetch()/load_history()."""
    country = app["country"]
    cur, name = country["currency"], country["name"]
    series = hist.get("series", {})
    fx_key = f"fx_{cur}"
    last_market = max((p for k, s in series.items() for p in s["values"] if re.fullmatch(r"\d{4}-\d{2}", p)), default=None)
    t = today or date.today()
    if not end:
        prev = f"{t.year - (t.month == 1):04d}-{(t.month - 2) % 12 + 1:02d}"      # last complete month
        end = min(last_market, prev) if last_market else prev
    ms = month_list(end, months)
    first_col, last_col = 3, 3 + months - 1          # month columns C .. Z
    col_of = {m: first_col + i for i, m in enumerate(ms)}
    L = get_column_letter
    app_fx = {r["item"]: r for r in app["rates"] if r["category"] == "forex"}

    wb = Workbook()
    wb.remove(wb.active)
    sheets = {n: Sheet(wb.create_sheet(n)) for n in
              ("Summary", "RM_Price", "Labour", "Process_Cost", "Electricity", "Transport", "Forex", "Sources")}
    sources: list[list] = []

    def src(what, publisher, url, freq, unit, last, kind, note=""):
        sources.append([what, kind, publisher, url, freq, unit, last, note])

    def mkt_row(sh: Sheet, label, key, unit, fmt="#,##0.00"):
        s = series.get(key)
        sh.put(1, label, bold=True)
        sh.put(2, unit)
        for m in ms:
            v = (s or {}).get("values", {}).get(m)
            sh.put(col_of[m], v, MARKET_FILL if v is not None else None, fmt)
        if s:
            last = max(s["values"]) if s["values"] else ""
            src(label, s["meta"]["publisher"], s["meta"]["url"], s["meta"].get("frequency", "monthly"), unit, last, "MARKET")
        else:
            src(label, "not downloaded yet", "", "", unit, "", "GAP", "run the refresh with internet access")
        sh.row += 1
        return sh.row - 1

    # ---------------- Forex
    fx = sheets["Forex"]
    fx.title(f"{name} - Forex (INR first)", f"Monthly averages. Green = downloaded market data, orange = fallback. Months {ms[0]} to {ms[-1]}.")
    fx.head(["Rate", "Unit"] + [_mlabel(m) for m in ms] + ["Source"])
    r_inr_usd = mkt_row(fx, "INR per USD", "fx_INR", "INR/USD", "#,##0.0000")
    fx.ws.cell(r_inr_usd, last_col + 1, "FRED EXINUS (Federal Reserve H.10)").font = SMALL
    fx.put(1, f"{cur} per USD", bold=True)
    fx.put(2, f"{cur}/USD")
    lcu_note = ""
    for m in ms:
        if cur == "USD":
            fx.put(col_of[m], 1, MARKET_FILL, "#,##0.0000")
        elif cur in FX_FRED:
            v = series.get(fx_key, {}).get("values", {}).get(m)
            if v is not None and FX_FRED[cur][1]:
                fx.put(col_of[m], f"=1/{v}", MARKET_FILL, "#,##0.0000")
            else:
                fx.put(col_of[m], v, MARKET_FILL if v is not None else None, "#,##0.0000")
        else:
            wbv = series.get(f"fxwb_{cur}", {}).get("values", {}).get(m[:4])
            if wbv is not None:
                fx.put(col_of[m], wbv, EXAMPLE_FILL, "#,##0.0000",
                       comment=f"World Bank annual average {m[:4]} (PA.NUS.FCRF), shown in every month of the year")
                lcu_note = "World Bank annual average"
    r_lcu_usd = fx.row
    fx.ws.cell(r_lcu_usd, last_col + 1, "FRED " + FX_FRED[cur][0] if cur in FX_FRED else (lcu_note or "USD") if cur == "USD"
               else lcu_note or "no monthly market source").font = SMALL
    fx.row += 1
    fx.put(1, f"INR per {cur}", bold=True)
    fx.put(2, f"INR/{cur}")
    fb = app_fx.get(cur)
    for m in ms:
        a, b = f"{L(col_of[m])}{r_inr_usd}", f"{L(col_of[m])}{r_lcu_usd}"
        if cur == "INR":
            fx.put(col_of[m], 1, None, "#,##0.0000")
        elif fb:
            fx.put(col_of[m], f'=IF(AND(ISNUMBER({a}),ISNUMBER({b})),{a}/{b},{fb["value"]})', None, "#,##0.0000")
        else:
            fx.put(col_of[m], f'=IF(AND(ISNUMBER({a}),ISNUMBER({b})),{a}/{b},"")', None, "#,##0.0000")
    r_inr_lcu = fx.row
    fx.ws.cell(r_inr_lcu, last_col + 1, "INR per USD ÷ LCU per USD; month without market data: the tool's approved rate").font = SMALL
    fx.row += 2
    fx.head(["The tool's approved forex", "Unit", "Value", "Month", "Status", "Source"])
    for k, r in sorted(app_fx.items()):
        fx.put(1, f"INR per {k}")
        fx.put(2, r["unit"])
        fx.put(3, r["value"], EXAMPLE_FILL if r["is_example"] else APP_FILL, "#,##0.0000")
        fx.put(4, r["month"])
        fx.put(5, "EXAMPLE" if r["is_example"] else r["status"])
        fx.put(6, r["source"])
        fx.row += 1
    if fb and cur != "INR":
        fx.row += 1
        fx.put(1, f"Check: tool rate vs latest market INR/{cur}", bold=True)
        last_c = f"{L(last_col)}{r_inr_lcu}"
        fx.put(3, f'=IFERROR({fb["value"]}/LOOKUP(2,1/ISNUMBER(C{r_inr_usd}:{L(last_col)}{r_inr_usd}),C{r_inr_lcu}:{last_c})-1,"")',
               None, "0.0%", comment="Difference of the tool's approved forex to the latest month with market data")
        fx.row += 1
    _widths(fx.ws, 30, 10, last_col + 1, {L(last_col + 1): 48})
    _chart(fx.ws, f"INR per {cur}" if cur != "INR" else "INR per USD", "INR", r_inr_lcu if cur != "INR" else r_inr_usd,
           r_inr_lcu if cur != "INR" else r_inr_usd, first_col, last_col, f"B{fx.row + 2}")
    fxref = lambda m: f"Forex!${L(col_of[m])}${r_inr_usd}"          # INR per USD
    fxlcu = lambda m: f"Forex!${L(col_of[m])}${r_inr_lcu}"          # INR per LCU

    # ---------------- RM price
    rm = sheets["RM_Price"]
    rm.title(f"{name} - Raw material prices", "A: world market prices (downloaded, monthly). B: grade rates of the tool "
             "(approved, per month) with the market index each grade follows.")
    rm.head(["A1. Market price", "Unit"] + [_mlabel(m) for m in ms])
    usd_rows = {}
    for key, (sid, label, unit, _) in COMMODITIES.items():
        usd_rows[key] = mkt_row(rm, label, key, unit)
    rm.row += 1
    rm.head(["A2. Market price in INR / kg", "Unit"] + [_mlabel(m) for m in ms])
    inr_rows = {}
    for key, (sid, label, unit, k) in COMMODITIES.items():
        if k is None:
            continue
        rm.put(1, label.split(" (")[0], bold=True)
        rm.put(2, "INR/kg")
        for m in ms:
            c = f"{L(col_of[m])}{usd_rows[key]}"
            rm.put(col_of[m], f'=IF(ISNUMBER({c}),{c}*{k}*{fxref(m)},"")', None, "#,##0.00")
        inr_rows[key] = rm.row
        rm.row += 1
    if cur != "INR":
        rm.row += 1
        rm.head([f"A3. Market price in {cur} / kg", "Unit"] + [_mlabel(m) for m in ms])
        for key in inr_rows:
            rm.put(1, COMMODITIES[key][1].split(" (")[0], bold=True)
            rm.put(2, f"{cur}/kg")
            for m in ms:
                c = f"{L(col_of[m])}{inr_rows[key]}"
                rm.put(col_of[m], f'=IFERROR({c}/{fxlcu(m)},"")', None, "#,##0.00")
            rm.row += 1
    rm.row += 1
    rm.head(["A4. Price index (trend only)", "Unit"] + [_mlabel(m) for m in ms])
    idx_rows = {}
    for key, (sid, label, unit) in INDICES.items():
        idx_rows[key] = mkt_row(rm, label, key, unit, "#,##0.0")
    chart_anchor_row = rm.row + 1
    rm.row += 18
    # change columns helper: % change over 12 and 24 months of a row with market values
    def chg(row, n):
        """Change of the latest month with data to exactly n months before it ('' when that month is not in the window)."""
        return "=" + delta(f"$C${row}:${L(last_col)}${row}", n)
    index_rows = {**usd_rows, **idx_rows}
    rm.note("B. Grade rates of the tool (rate library, approved). Blue = approved, orange = EXAMPLE (replace with your quotes). "
            "Columns fill month by month as you approve new rates; empty = no approved rate that month.")
    hdr = ["B. Grade / RM", "Unit"] + [_mlabel(m) for m in ms] + ["Latest", "Latest INR/kg", "Status", "Source",
                                                                     "Follows market index", "Index Δ 12 m", f"Index Δ since {_mlabel(ms[0])}"]
    rm.head(hdr)
    def index_cells(ix, base):
        rm.put(base, (COMMODITIES.get(ix) or INDICES.get(ix) or ("", ix or "-"))[1] if ix else "-")
        if ix and ix in index_rows:
            rng = f"$C${index_rows[ix]}:${L(last_col)}${index_rows[ix]}"
            rm.put(base + 1, "=" + delta(rng, 12), None, "0.0%")
            rm.put(base + 2, "=" + delta(rng, None), None, "0.0%")

    inr_latest = (f'LOOKUP(2,1/ISNUMBER(Forex!C{r_inr_lcu}:{L(last_col)}{r_inr_lcu}),'
                  f'Forex!C{r_inr_lcu}:{L(last_col)}{r_inr_lcu})')
    # every grade of the tool, grouped by material family (tool & mould steels and scrap values in their own groups)
    fam_rows: dict[str, list[tuple[str, str, list[dict]]]] = {}
    for cat in ("material", "tool_material", "material_scrap"):
        items: dict[str, list[dict]] = {}
        for r in app["rates"]:
            if r["category"] == cat:
                items.setdefault(r["item"], []).append(r)
        for item, versions in items.items():
            fam = ("Tool & mould material" if cat == "tool_material" else "Scrap value (all materials)"
                   if cat == "material_scrap" else family_of(item))
            fam_rows.setdefault(fam, []).append((cat, item, versions))
    order = [f for f, _ in FAMILIES] + ["Tool & mould material", "Other", "Scrap value (all materials)"]
    known = set()
    for fam in sorted(fam_rows, key=lambda f: order.index(f) if f in order else len(order)):
        rm.put(1, fam, bold=True)
        rm.row += 1
        for cat, item, versions in sorted(fam_rows[fam], key=lambda t: t[1].lower()):
            known.add(item.lower())
            latest = versions[-1]
            fill = EXAMPLE_FILL if latest["is_example"] else APP_FILL
            rm.put(1, item)
            rm.put(2, latest["unit"])
            per_month = {v["month"]: v for v in versions}
            for m in ms:
                v = per_month.get(m)
                if v:
                    rm.put(col_of[m], v["value"], EXAMPLE_FILL if v["is_example"] else APP_FILL, "#,##0.00")
                else:
                    rm.put(col_of[m], None)
            base = last_col + 1
            rm.put(base, latest["value"], fill, "#,##0.00", comment=f"Approved rate of {latest['month']}")
            cur_r = latest["currency"] or cur
            if cur_r == "INR":
                rm.put(base + 1, f"={L(base)}{rm.row}", None, "#,##0.00")
            elif cur_r == cur:
                rm.put(base + 1, f'=IFERROR({L(base)}{rm.row}*{inr_latest},"")', None, "#,##0.00")
            elif app_fx.get(cur_r):
                rm.put(base + 1, f"={L(base)}{rm.row}*{app_fx[cur_r]['value']}", None, "#,##0.00")
            rm.put(base + 2, "EXAMPLE" if latest["is_example"] else latest["status"])
            rm.put(base + 3, latest["source"])
            index_cells(index_for(item), base + 4)
            rm.row += 1
        rm.row += 1
    # C: common grades that are not in the tool yet - names and equivalents only, rate cells for you (no free price source)
    rm.row += 1
    rm.note("C. Other common grades, not yet in the tool. No free source publishes these prices: enter your supplier quote in "
            "the yellow cells, or better add the grade on Master data → Price master so it is used in costing and shows in B.")
    rm.head(["C. Grade (not in the tool yet)", "Unit"] + [_mlabel(m) for m in ms] + ["Equivalent / standard", "Family", "", "",
                                                                                     "Follows market index", "Index Δ 12 m",
                                                                                     f"Index Δ since {_mlabel(ms[0])}"])
    shown = 0
    for fam, grades in FAMILIES:
        rows = [g for g in grades if not in_tool(g[0], known)]
        if not rows:
            continue
        rm.put(1, fam, bold=True)
        rm.row += 1
        for grade, equiv in rows:
            rm.put(1, grade)
            rm.put(2, f"{cur}/kg")
            for m in ms:
                rm.put(col_of[m], None, ENTRY_FILL, "#,##0.00")
            base = last_col + 1
            rm.put(base, equiv)
            rm.put(base + 1, fam)
            index_cells(index_for(f"{grade} {fam}"), base + 4)
            rm.row += 1
            shown += 1
        rm.row += 1
    src("Grade rates (part RM, tool steel, scrap)", "This tool: Rates page (approved rate library)", "", "monthly", "per kg",
        app["as_of"], "APP", "EXAMPLE rates until you replace them")
    rm.row += 1
    rm.note("Enter supplier / index quotes for a grade on the Rates page of the tool (new price = draft, approve it): the next "
            "refresh shows it in its month here. Steel and plastic grades have no free monthly market price: the US PPI is a trend only.")
    _widths(rm.ws, 44, 10, last_col + 8, {L(last_col + 4): 40, L(last_col + 5): 40})
    rm.ws.freeze_panes = "C5"
    keys = [k for k in ("aluminium", "copper", "nickel", "zinc") if k in inr_rows]
    if keys:
        ch = LineChart()
        ch.title, ch.y_axis.title, ch.height, ch.width = "Metals, INR/kg (24 months)", "INR/kg", 8, 24
        for k in keys:
            ch.add_data(Reference(rm.ws, min_col=1, max_col=last_col, min_row=inr_rows[k], max_row=inr_rows[k]),
                        from_rows=True, titles_from_data=True)
        ch.set_categories(Reference(rm.ws, min_col=first_col, max_col=last_col, min_row=4))
        # first column of the data reference is the label (titles_from_data); drop column B (unit) from the series
        for s, k in zip(ch.series, keys):
            s.val.numRef.f = f"'RM_Price'!$C${inr_rows[k]}:${L(last_col)}${inr_rows[k]}"
            s.tx.strRef.f = f"'RM_Price'!$A${inr_rows[k]}"
        ch.set_categories(Reference(rm.ws, min_col=first_col, max_col=last_col, min_row=4, max_row=4))
        rm.ws.add_chart(ch, f"C{chart_anchor_row}")

    # ---------------- Labour
    lb = sheets["Labour"]
    iso3 = COUNTRY_SOURCES.get(country_code, ("",))[0]
    lb.title(f"{name} - Labour rate by skill level",
             "A: ILOSTAT mean nominal hourly earnings of employees by skill level (ISCO-08), yearly as published. "
             "B: the tool's labour rates per grade (fully loaded, per hour).")
    ilo = hist.get("ilo", {})
    years = sorted({y for k, v in ilo.get("hourly_by_skill", {}).items() if k.startswith(iso3 + "|") for y in v} |
                   {y for k, v in ilo.get("monthly_manufacturing", {}).items() if k.startswith(iso3 + "|") for y in v})[-4:]
    if not years:
        years = [str(int(end[:4]) - i) for i in (3, 2, 1, 0)]
    # yearly INR per USD = mean of the months of that year in the history
    inr_usd_year = {}
    for y in years:
        vals = [v for p, v in series.get("fx_INR", {}).get("values", {}).items() if p.startswith(y)]
        inr_usd_year[y] = sum(vals) / len(vals) if vals else None
    lb.head(["A1. Hourly earnings (employees)", "Unit"] + years + ["Source / note"])
    any_ilo = False
    for cls, label in SKILLS:
        for curtype, unit in (("CUR_TYPE_LCU", f"{cur}/h"), ("CUR_TYPE_USD", "USD/h")):
            d = ilo.get("hourly_by_skill", {}).get(f"{iso3}|{cls}|{curtype}", {})
            lb.put(1, label, bold=curtype == "CUR_TYPE_LCU")
            lb.put(2, unit)
            note = ""
            for i, y in enumerate(years):
                v = d.get(y)
                lb.put(3 + i, v["value"] if v else None, MARKET_FILL if v else None, "#,##0.00")
                note = (v or {}).get("source", note) if v else note
                any_ilo = any_ilo or bool(v)
            lb.put(3 + len(years), note)
            lb.row += 1
        usd_row = lb.row - 1
        if cur == "INR":
            continue                                   # the local-currency row is already INR
        lb.put(1, label)
        lb.put(2, "INR/h")
        for i, y in enumerate(years):
            c = f"{L(3 + i)}{usd_row}"
            rate = inr_usd_year.get(y)
            lb.put(3 + i, f'=IF(ISNUMBER({c}),{c}*{rate},"")' if rate else None, None, "#,##0.00",
                   comment=f"USD × INR/USD average of {y} ({rate:.4f}, FRED EXINUS)" if rate else None)
        lb.put(3 + len(years), "USD value × yearly average INR/USD")
        lb.row += 1
    lb.row += 1
    lb.head(["A2. Monthly earnings, manufacturing", "Unit"] + years + ["Source / note"])
    for curtype, unit in (("CUR_TYPE_LCU", f"{cur}/month"), ("CUR_TYPE_USD", "USD/month")):
        d = ilo.get("monthly_manufacturing", {}).get(f"{iso3}|ECO_ISIC4_C|{curtype}", {})
        lb.put(1, "Mean monthly earnings, manufacturing (ISIC C)")
        lb.put(2, unit)
        note = ""
        for i, y in enumerate(years):
            v = d.get(y)
            lb.put(3 + i, v["value"] if v else None, MARKET_FILL if v else None, "#,##0")
            note = (v or {}).get("source", note) if v else note
            any_ilo = any_ilo or bool(v)
        lb.put(3 + len(years), note)
        lb.row += 1
    src("Hourly earnings by skill level; monthly earnings in manufacturing",
        "ILOSTAT, International Labour Organization (EAR_EHRA_SEX_OCU_CUR_NB, EAR_EMTA_SEX_ECO_CUR_NB)", ILO_PAGE,
        "yearly", f"{cur}/h, USD/h", years[-1] if any_ilo else "", "MARKET" if any_ilo else "GAP",
        "" if any_ilo else f"ILOSTAT publishes no earnings for {name}: use the tool's rates / your survey")
    lb.note("Earnings are what the employee earns (gross). A cost rate adds employer contributions, supervision and productive time:"
            " that is the tool's labour rate below.")
    lb.row += 1
    lb.head(["B. The tool's labour rate", "Unit", "Value", "INR/h", "Status", "Note"])
    inr_now = f"LOOKUP(2,1/ISNUMBER(Forex!C{r_inr_lcu}:{L(last_col)}{r_inr_lcu}),Forex!C{r_inr_lcu}:{L(last_col)}{r_inr_lcu})"
    for g in app["labour"]:
        lb.put(1, f"{g['name']} ({g['grade']})")
        lb.put(2, f"{g['currency'] or cur}/h")
        lb.put(3, g["value"], EXAMPLE_FILL if g["example"] else APP_FILL, "#,##0.00")
        lb.put(4, f'=IFERROR(C{lb.row}*{inr_now},"")' if g["value"] is not None else None, None, "#,##0.00")
        lb.put(5, "EXAMPLE" if g["example"] else "approved")
        lb.put(6, g["error"] or "Traced on the tool's Rates → Machine & labour rates page")
        lb.row += 1
    lb.row += 1
    lb.head(["Salary and loading inputs of the tool", "Unit", "Value", "Month", "Status", "Source"])
    for r in app["rates"]:
        if r["category"] in ("labour_salary", "labour", "hours"):
            lb.put(1, f"{r['category']}: {r['item']}")
            lb.put(2, r["unit"])
            lb.put(3, r["value"], EXAMPLE_FILL if r["is_example"] else APP_FILL, "#,##0.00")
            lb.put(4, r["month"])
            lb.put(5, "EXAMPLE" if r["is_example"] else r["status"])
            lb.put(6, r["source"])
            lb.row += 1
    src("Labour rate per grade, salaries, loading, hours", "This tool: rate_engine (labour scope) on approved rates", "",
        "monthly", f"{cur}/h", app["as_of"], "APP")
    _widths(lb.ws, 46, 13, 10, {"F": 50, L(3 + len(years)): 40})

    # ---------------- Process cost
    pc = sheets["Process_Cost"]
    pc.title(f"{name} - Process cost", "Machine hour rate (MHR) of every machine = depreciation + interest + power + space + "
             "maintenance + consumables + operator, calculated by the tool on approved rates; process rates per hour and per unit.")
    pc.head(["A. Machine hour rate", "Process", "kW", f"{cur}/h", "INR/h", "Status", "Note"])
    for mc in app["machines"]:
        pc.put(1, f"{mc['name']} ({mc['id']})")
        pc.put(2, mc["process"])
        pc.put(3, mc["kw"], None, "#,##0.0")
        pc.put(4, mc["value"], EXAMPLE_FILL if mc["example"] else APP_FILL, "#,##0.00")
        pc.put(5, f'=IFERROR(D{pc.row}*{inr_now},"")' if mc["value"] is not None else None, None, "#,##0.00")
        pc.put(6, "EXAMPLE" if mc["example"] else "approved")
        pc.put(7, mc["error"] or "")
        pc.row += 1
    pc.row += 1
    pc.head(["B. Process rates", "Unit"] + [_mlabel(m) for m in ms] + ["Latest", "Status", "Source"])
    for cat, gname in (("process_hour", "Per hour"), ("process_unit", "Per unit"), ("process_min_charge", "Minimum charge per job")):
        items: dict[str, list[dict]] = {}
        for r in app["rates"]:
            if r["category"] == cat:
                items.setdefault(r["item"], []).append(r)
        if not items:
            continue
        pc.put(1, gname, bold=True)
        pc.row += 1
        for item, versions in sorted(items.items()):
            latest = versions[-1]
            per_month = {v["month"]: v for v in versions}
            pc.put(1, item)
            pc.put(2, latest["unit"])
            for m in ms:
                v = per_month.get(m)
                pc.put(col_of[m], v["value"] if v else None, (EXAMPLE_FILL if v["is_example"] else APP_FILL) if v else None, "#,##0.00")
            pc.put(last_col + 1, latest["value"], EXAMPLE_FILL if latest["is_example"] else APP_FILL, "#,##0.00")
            pc.put(last_col + 2, "EXAMPLE" if latest["is_example"] else latest["status"])
            pc.put(last_col + 3, latest["source"])
            pc.row += 1
    pc.row += 1
    pc.head(["C. Cost drivers of a process (market)", "Unit"] + [_mlabel(m) for m in ms])
    mkt_row(pc, "US PPI: electric power distribution", "ppi_power", "index", "#,##0.0")
    mkt_row(pc, "Crude oil Brent", "brent", "USD/bbl")
    pc.note("No free source publishes machine hour rates: the rates above come from the tool (machine price, kW, life, hours, "
            "power and labour rates). Replace EXAMPLE machine prices on the Rates page; the MHR follows.")
    src("Machine hour rates and process rates", "This tool: rate_engine (mhr scope) and rate library", "", "monthly",
        f"{cur}/h", app["as_of"], "APP")
    _widths(pc.ws, 44, 10, last_col + 3, {"B": 26, L(last_col + 3): 44})

    # ---------------- Electricity
    el = sheets["Electricity"]
    el.title(f"{name} - Electricity (industrial)", "Official tariffs are published per country in different forms; only the "
             "EU publishes a free time series (Eurostat). Others: tariff publisher below - enter the monthly rate in the yellow row.")
    pw = [r for r in app["rates"] if r["category"] == "power"]
    el.head(["A. The tool's power rate", "Unit", "Value", "INR/kWh", "Month", "Status", "Source"])
    for r in pw:
        el.put(1, r["item"])
        el.put(2, r["unit"])
        el.put(3, r["value"], EXAMPLE_FILL if r["is_example"] else APP_FILL, "#,##0.0000")
        el.put(4, f'=IFERROR(C{el.row}*{inr_now},"")', None, "#,##0.0000")
        el.put(5, r["month"])
        el.put(6, "EXAMPLE" if r["is_example"] else r["status"])
        el.put(7, r["source"])
        el.row += 1
    el.row += 1
    pub = COUNTRY_SOURCES.get(country_code, ("", None, "", ""))
    el.put(1, "Official tariff publisher", bold=True)
    el.put(2, pub[2])
    el.row += 1
    el.put(1, "Link")
    el.put(2, pub[3] or "-")
    el.row += 2
    geo = pub[1]
    if geo:
        sem = sorted({p for g in (geo, "EU27_2020") for p in series.get(f"elec_eurostat_{g}", {}).get("values", {})})[-5:]
        el.head(["B. Eurostat half-yearly", "Unit"] + sem)
        for g, lab in ((geo, name), ("EU27_2020", "EU-27 average")):
            vals = series.get(f"elec_eurostat_{g}", {}).get("values", {})
            el.put(1, f"{lab}: 2-20 GWh/yr, excl. VAT", bold=True)
            el.put(2, "EUR/kWh")
            for i, p in enumerate(sem):
                el.put(3 + i, vals.get(p), MARKET_FILL if vals.get(p) is not None else None, "#,##0.0000")
            el.row += 1
            el.put(1, f"{lab} in INR/kWh")
            el.put(2, "INR/kWh")
            eur = app_fx.get("EUR")
            for i, p in enumerate(sem):
                yr, half = p[:4], p[-2:]
                mlist = [f"{yr}-{mm:02d}" for mm in (range(1, 7) if half == "S1" else range(7, 13))]
                eurs = [series.get("fx_EUR", {}).get("values", {}).get(x) for x in mlist]
                inrs = [series.get("fx_INR", {}).get("values", {}).get(x) for x in mlist]
                pairs = [(a, b) for a, b in zip(eurs, inrs) if a and b]
                if pairs and vals.get(p) is not None:
                    rate = sum(a * b for a, b in pairs) / len(pairs)
                    el.put(3 + i, f"={L(3 + i)}{el.row - 1}*{rate:.4f}", None, "#,##0.00",
                           comment=f"× INR per EUR, mean of {p} (FRED EXUSEU × EXINUS) = {rate:.4f}")
                elif eur and vals.get(p) is not None:
                    el.put(3 + i, f"={L(3 + i)}{el.row - 1}*{eur['value']}", EXAMPLE_FILL, "#,##0.00")
                else:
                    el.put(3 + i, None)
            el.row += 1
        el.row += 1
        for g in (geo, "EU27_2020"):
            s = series.get(f"elec_eurostat_{g}")
            if s:
                src(s["meta"]["name"], s["meta"]["publisher"], s["meta"]["url"], "half-yearly", "EUR/kWh",
                    max(s["values"]) if s["values"] else "", "MARKET")
    else:
        src(f"Industrial electricity tariff, {name}", pub[2], pub[3], "as revised", f"{cur}/kWh", "", "GAP",
            "no free machine-readable series: enter the tariff in the yellow row")
    el.head(["C. Industrial tariff - your entry", "Unit"] + [_mlabel(m) for m in ms])
    el.put(1, "Energy charge (enter from the tariff order)", bold=True)
    el.put(2, f"{cur}/kWh")
    for m in ms:
        el.put(col_of[m], None, ENTRY_FILL, "#,##0.0000")
    el.row += 1
    el.put(1, "Demand charge (enter)")
    el.put(2, f"{cur}/kVA/month")
    for m in ms:
        el.put(col_of[m], None, ENTRY_FILL, "#,##0.00")
    el.row += 2
    el.head(["D. Energy market drivers", "Unit"] + [_mlabel(m) for m in ms])
    r_gas = mkt_row(el, ENERGY["gas_eu"][1], "gas_eu", "USD/MMBtu")
    mkt_row(el, ENERGY["coal_au"][1], "coal_au", "USD/t")
    mkt_row(el, ENERGY["ppi_power"][1], "ppi_power", "index", "#,##0.0")
    _widths(el.ws, 44, 10, last_col, {"B": 14, "G": 44})
    _chart(el.ws, "Energy drivers", "", r_gas, r_gas + 1, first_col, last_col, f"C{el.row + 2}")

    # ---------------- Transport
    tr = sheets["Transport"]
    tr.title(f"{name} - Transportation", "A: freight rates of the tool (to India, per kg). B: market drivers, monthly. "
             "C: your entries (container quote, local diesel).")
    tr.head(["A. The tool's freight rate", "Unit", "Value", "Month", "Status", "Source"])
    for r in app["rates"]:
        if r["category"] in ("freight", "import"):
            tr.put(1, f"{r['category']}: {r['item']}")
            tr.put(2, r["unit"])
            tr.put(3, r["value"], EXAMPLE_FILL if r["is_example"] else APP_FILL, "#,##0.00")
            tr.put(4, r["month"])
            tr.put(5, "EXAMPLE" if r["is_example"] else r["status"])
            tr.put(6, r["source"])
            tr.row += 1
    src("Freight rates to India", "This tool: rate library (freight)", "", "monthly", "INR/kg", app["as_of"], "APP")
    tr.row += 1
    tr.head(["B. Market drivers", "Unit"] + [_mlabel(m) for m in ms])
    r_brent = mkt_row(tr, TRANSPORT["brent"][1], "brent", "USD/bbl")
    r_dsl = mkt_row(tr, TRANSPORT["diesel_us"][1], "diesel_us", "USD/gal")
    tr.put(1, "US diesel in INR / litre")
    tr.put(2, "INR/l")
    for m in ms:
        c = f"{L(col_of[m])}{r_dsl}"
        tr.put(col_of[m], f'=IF(ISNUMBER({c}),{c}/3.785411784*{fxref(m)},"")', None, "#,##0.00",
               comment=None if m != ms[0] else "1 US gallon = 3.785411784 litres")
    tr.row += 1
    mkt_row(tr, TRANSPORT["ppi_sea"][1], "ppi_sea", "index", "#,##0.0")
    mkt_row(tr, TRANSPORT["ppi_truck"][1], "ppi_truck", "index", "#,##0.0")
    tr.row += 1
    tr.head(["C. Your entries", "Unit"] + [_mlabel(m) for m in ms])
    for lab, unit in ((f"Container 40ft {name} → Nhava Sheva / Chennai (quote)", "USD/FEU"),
                      (f"Local diesel price, {name}", f"{cur}/l"), ("Truck rate, local", f"{cur}/km")):
        tr.put(1, lab)
        tr.put(2, unit)
        for m in ms:
            tr.put(col_of[m], None, ENTRY_FILL, "#,##0.00")
        tr.row += 1
    tr.note("Container indices (Drewry WCI, Freightos FBX, SCFI) are free to read but not free to download: enter your forwarder's quotes.")
    _widths(tr.ws, 50, 10, last_col, {"F": 44})
    _chart(tr.ws, "Brent USD/bbl", "USD", r_brent, r_brent, first_col, last_col, f"C{tr.row + 2}")

    # ---------------- Summary
    sm = sheets["Summary"]
    sm.title(f"Country rate book - {name} ({country_code}, {cur})",
             f"Built {t.isoformat()} · months {ms[0]} to {ms[-1]} · INR first · Green = downloaded market data · "
             "Blue = approved rate of the tool · Orange = EXAMPLE / fallback · Yellow = your entry")
    sm.head(["Key figure", "Unit", "Latest", "Month", "12 months before", "Δ 12 m", "First month", "Δ since first",
             "Where"])

    def kpi(label, unit, sheet, row, where, fmt="#,##0.00"):
        rng = f"{sheet}!$C${row}:${L(last_col)}${row}"
        p = last_pos(rng)
        sm.put(1, label, bold=True)
        sm.put(2, unit)
        sm.put(3, f'=IFERROR(INDEX({rng},{p}),"")', None, fmt)
        sm.put(4, f'=IFERROR(INDEX({hdr_row(sheet, row)},{p}),"")')
        sm.put(5, f'=IFERROR(INDEX({rng},{p}-12),"")', None, fmt)
        sm.put(6, "=" + delta(rng, 12), None, "0.0%")
        sm.put(7, f'=IFERROR(INDEX({rng},MATCH(TRUE,INDEX(ISNUMBER({rng}),0),0)),"")', None, fmt)
        sm.put(8, "=" + delta(rng, None), None, "0.0%")
        sm.put(9, where)
        sm.row += 1

    def hdr_row(sheet, row):
        """The month-label row above a market row (the nearest table head above it)."""
        ws = wb[sheet]
        r = row
        while r > 1 and not (isinstance(ws.cell(r, first_col).value, str) and re.fullmatch(r"[A-Z][a-z]{2}-\d{2}", ws.cell(r, first_col).value)):
            r -= 1
        return f"{sheet}!$C${r}:${L(last_col)}${r}"
    kpi("INR per USD", "INR", "Forex", r_inr_usd, "Forex")
    if cur != "INR":
        kpi(f"INR per {cur}", "INR", "Forex", r_inr_lcu, "Forex", "#,##0.0000")
    for k in ("aluminium", "copper", "nickel", "zinc", "iron_ore"):
        if k in inr_rows:
            kpi(COMMODITIES[k][1].split(" (")[0], "INR/kg", "RM_Price", inr_rows[k], "RM_Price A2")
    for k in ("ppi_steel", "ppi_resins"):
        kpi(INDICES[k][1], "index", "RM_Price", idx_rows[k], "RM_Price A4 (trend)", "#,##0.0")
    kpi("Crude oil Brent", "USD/bbl", "Transport", r_brent, "Transport B")
    sm.row += 1
    sm.note("Labour (yearly, ILOSTAT), machine hour rates, process and power rates: see their sheets. Δ 12 m = latest month with "
            f"data against exactly 12 months before it; Δ since first = against the first month with data ({_mlabel(ms[0])} or later).")
    sm.row += 1
    gaps = [s for s in sources if s[1] == "GAP"]
    ex = sum(1 for r in app["rates"] if r["is_example"])
    sm.put(1, "Rates of the tool still EXAMPLE", bold=True)
    sm.put(3, ex, EXAMPLE_FILL if ex else None, "#,##0")
    sm.row += 1
    sm.put(1, "Data gaps (no free source)", bold=True)
    sm.put(3, len(gaps), None, "#,##0")
    sm.row += 1
    for g in gaps:
        sm.put(1, f"  {g[0]}")
        sm.put(2, g[7])
        sm.row += 1
    _widths(sm.ws, 46, 13, 9, {"B": 30, "I": 22})

    # ---------------- Sources
    so = sheets["Sources"]
    so.title("Sources", "MARKET = downloaded from the publisher by the refresh script · APP = approved rates of this tool · "
             "GAP = no free machine-readable source")
    so.head(["Data", "Kind", "Publisher", "Link", "Frequency", "Unit", "Latest period", "Note"])
    seen = set()
    for s in sources:
        if tuple(s[:4]) in seen:
            continue
        seen.add(tuple(s[:4]))
        for i, v in enumerate(s):
            so.put(1 + i, v, MARKET_FILL if s[1] == "MARKET" else APP_FILL if s[1] == "APP" else EXAMPLE_FILL if i == 1 else None)
        so.row += 1
    so.row += 1
    last_run = (hist.get("runs") or [{}])[-1]
    so.put(1, "Last refresh", bold=True)
    so.put(2, last_run.get("at", "never"))
    so.row += 1
    for line in last_run.get("log", [])[:40]:
        so.note(line)
    so.row += 1
    so.note("Refresh monthly: python -m backend.app.country_rate_book (or DTC_Country_Rates.bat on the Windows kit). "
            "History is kept in country_rate_book_history.json next to the workbooks.")
    _widths(so.ws, 50, 14, 8, {"C": 46, "D": 58, "H": 50})
    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
    return wb


def default_out() -> Path:
    if os.environ.get("DTC_DATA_FOLDER"):
        return Path(os.environ["DTC_DATA_FOLDER"]) / "country_rates"
    return Path(__file__).resolve().parents[2] / "data" / "country_rates"


def run(countries: list[str] | None = None, out_dir: Path | None = None, offline: bool = False, http=_http,
        today: date | None = None, ilo_files: list[Path] | None = None) -> list[Path]:
    from . import costing_setup
    out_dir = Path(out_dir or default_out())
    out_dir.mkdir(parents=True, exist_ok=True)
    allc = costing_setup.tables()["countries"]
    chosen = [c for c in allc if not countries or c["code"] in countries]
    if not offline:
        fetch(out_dir, chosen, http, today)
    if ilo_files:
        import_ilo(out_dir, ilo_files, today)
    hist = load_history(out_dir)
    paths = []
    for c in chosen:
        wb = build(c["code"], hist, app_data(c["code"]), today=today)
        last = wb["RM_Price"].cell(4, 2 + MONTHS).value                              # last month column, e.g. Oct-26
        tag = datetime.strptime(last, "%b-%y").strftime("%Y-%m")
        p = out_dir / f"Country_Rates_{c['name'].replace(' ', '_')}_{tag}.xlsx"
        wb.save(p)
        paths.append(p)
    return paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Country rate book: one Excel per country, 24 months, with sources.")
    ap.add_argument("--countries", help="comma-separated country codes (default: all of Master data → Countries)")
    ap.add_argument("--out", help="output folder (default: DTC_Data/country_rates or data/country_rates)")
    ap.add_argument("--offline", action="store_true", help="no download; build from the saved history")
    ap.add_argument("--ilo-file", action="append", default=[],
                    help="ILOSTAT SDMX-CSV downloaded by hand (EAR_EHRA_SEX_OCU_CUR_NB / EAR_EMTA_SEX_ECO_CUR_NB); repeatable")
    a = ap.parse_args(argv)
    codes = [c.strip().upper() for c in a.countries.split(",")] if a.countries else None
    paths = run(codes, Path(a.out) if a.out else None, a.offline, ilo_files=[Path(f) for f in a.ilo_file])
    hist = load_history(paths[0].parent) if paths else {"runs": []}
    for line in (hist.get("runs") or [{}])[-1].get("log", []):
        print(line)
    for p in paths:
        print(f"Written: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
