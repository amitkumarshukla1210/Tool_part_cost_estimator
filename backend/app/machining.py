"""Machined parts (roadmap stage 37): bar stock, machining time, machine and fixture, fully traced.

    route       turned (CNC lathe) or milled (machining centre): from the 3D model (share of the surface turned about one
                axis ≥ Parameters → turned_min_round_share), or typed on the part
    stock       the smallest standard size of Mould & die database → Stock sizes that holds the part with the allowances of
                Parameters (dia_allowance_mm, mill_allowance_mm, face_allowance_mm, cut_off_mm): round bar for a turned part
                (hex if you choose it), the lightest of square bar, flat bar and plate for a milled part. Only this search
                is code; the RM cost of the stock is the formulas of scope rm_machined (weight, end loss, chips credit).
    time        the Cost formulas of scope "machining": removed volume ÷ removal rate (Machining data of the material),
                surface ÷ finish rate, drilled depth ÷ feed, tool changes, loading per set-up, set-up ÷ batch → cycle_s;
                machines needed from the annual volume; fixture cost per set (the final result) × machines = fixture CAPEX.
    machine     Parameters → machine_turned / machine_milled (Master data → Machines); its MHR is used by the part cost.

The fixture is stored like a tool cost version (part panel → Machining & fixture), so it shows in the tool CAPEX, the CAPEX
plan and the country comparison; the part cost uses the machining time and the machine. All seeded rows are EXAMPLE values.
"""

from __future__ import annotations

from contextlib import closing

from . import costing_setup, master_data, mould_db, rate_engine, rates, register_setup
from .costing_setup import MACHINING_SCOPE
from .trace import Trace

EXAMPLE = "EXAMPLE - typical value: replace with your supplier's data or shop experience"
ROUTES = ("turned", "milled")
FIXTURE_RATE = "Machining fixture (per set-up)"
SEED_SOURCE = "EXAMPLE seed (stage 37)"


class MachiningError(ValueError):
    pass


# ---------- master data (only added, never changed) ----------

# material, material type, recommended, density, INR/kg, scrap INR/kg, turn cm³/min, mill cm³/min, finish cm²/min, drill mm/min
SEED_MATERIALS = [
    ("Free-cutting steel EN1A (11SMnPb30)", "Free-cutting steel bar", "yes", 7.85, 85, 30, 60, 40, 40, 150),
    ("Carbon steel EN8 (C45) bar", "Carbon steel bar", "yes", 7.85, 75, 30, 45, 30, 30, 120),
    ("Alloy steel EN19 (42CrMo4) bar", "Alloy steel bar", "yes", 7.85, 110, 32, 30, 20, 22, 90),
    ("Stainless steel 304 bar", "Stainless steel bar", "yes", 7.93, 290, 120, 20, 14, 15, 60),
    ("Aluminium 6061-T6 bar", "Aluminium bar", "yes", 2.70, 340, 150, 150, 120, 80, 300),
    ("Brass CW614N (free-cutting) bar", "Brass bar", "yes", 8.47, 620, 430, 120, 90, 70, 250),
]
ROUND = (6, 8, 10, 12, 16, 20, 25, 30, 32, 36, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120, 130, 140, 150, 160, 180,
         200, 220, 250, 300)
HEX = (10, 13, 17, 19, 22, 24, 27, 30, 32, 36, 41, 46, 50, 55, 60)
SQUARE = (10, 12, 16, 20, 25, 30, 40, 50, 60, 70, 80, 100)
FLAT_T = (5, 6, 8, 10, 12, 16, 20, 25, 30, 40, 50)
FLAT_W = (20, 25, 30, 40, 50, 60, 80, 100, 120, 150)
PLATE_T = (6, 8, 10, 12, 16, 20, 25, 30, 35, 40, 50, 60, 70, 80, 100, 120, 150, 200)
SECTION = {"round": 0.7854, "hex": 0.866, "square": 1, "flat": 1, "plate": 1}

P = lambda v, u, d: (v, u, d)  # noqa: E731
SEED_PARAMETERS = {
    "machine_turned": P("CNC-LATHE", "", "EXAMPLE: machine of turned parts (Master data → Machines)"),
    "machine_milled": P("VMC-850", "", "EXAMPLE: machine of milled parts (Master data → Machines)"),
    "turned_min_round_share": P(0.8, "share", "EXAMPLE: a part is turned when at least this share of its surface turns about one axis"),
    "hole_max_dia_mm": P(20, "mm", "EXAMPLE: holes up to this diameter are drilled; bigger bores are machined"),
    "dia_allowance_mm": P(3, "mm", "EXAMPLE: bar diameter above the largest turned diameter"),
    "face_allowance_mm": P(1.5, "mm", "EXAMPLE: facing allowance at each end of a turned part"),
    "mill_allowance_mm": P(2, "mm/side", "EXAMPLE: stock on every side of a milled part"),
    "cut_off_mm": P(3, "mm", "EXAMPLE: parting-off tool or saw kerf per part"),
    "bar_end_loss_pct": P(3, "%", "EXAMPLE: bar remnant and chucking loss on the stock weight"),
    "chip_recovery_pct": P(90, "%", "EXAMPLE: share of chips and remnant sold as scrap"),
    "setups_turned": P(2, "set-ups", "EXAMPLE: clampings of a turned part (both ends)"),
    "setups_milled": P(2, "set-ups", "EXAMPLE: clampings of a milled part"),
    "load_unload_s": P(30, "s", "EXAMPLE: load, clamp and unload per set-up"),
    "setup_h": P(1.5, "h", "EXAMPLE: machine set-up per set-up and batch"),
    "batch_size": P(500, "parts", "EXAMPLE: parts per batch (set-up shared by the batch)"),
    "tool_change_pct": P(15, "% of cutting", "EXAMPLE: tool changes, rapid moves and measuring on top of the cutting time"),
    "drill_retract_s": P(5, "s/hole", "EXAMPLE: approach, peck and retract per drilled hole"),
    "fixture_factor_turned": P(0.3, "", "EXAMPLE: turned parts need soft jaws only: share of the fixture rate"),
    "fixture_factor_milled": P(1, "", "EXAMPLE: share of the fixture rate for a milled part"),
    "fixture_kg_per_setup": P(10, "kg", "EXAMPLE: fixture weight per set-up (freight and duty of the fixture)"),
    "oee_pct": P(75, "%", "EXAMPLE: OEE of the CNC machines"),
}
FORMULAS = [  # scope, name, label, formula, unit, result, description
    ("rm_machined", "stock_volume_cm3", "Stock volume per part", "section_factor * stock_size_mm * stock_width_mm * stock_length_mm / 1000", "cm³", 0,
     "Cross-section of the standard stock size × cut length"),
    ("rm_machined", "stock_g", "Stock weight per part", "stock_volume_cm3 * density_g_cm3", "g", 0, "Stock volume × density"),
    ("rm_machined", "gross_g", "Gross weight", "stock_g * (1 + bar_end_loss_pct / 100)", "g", 0, "Stock plus the bar remnant and chucking loss"),
    ("rm_machined", "returns_g", "Chips and remnant", "gross_g - net_weight_g", "g", 0, "Everything machined away"),
    ("rm_machined", "input_g", "Material used per part", "gross_g", "g", 0, ""),
    ("rm_machined", "material_yield_pct", "Material yield", "100 * net_weight_g / gross_g", "%", 0, ""),
    ("rm_machined", "rm_cost", "RM cost", "gross_g / 1000 * material_rate", "{cur}", 0, "Gross weight × bar rate"),
    ("rm_machined", "scrap_credit", "Chips credit", "0 - returns_g / 1000 * scrap_rate * chip_recovery_pct / 100", "{cur}", 0,
     "Chips sold as scrap"),
    ("rm_machined", "net_rm_cost", "Net RM cost per part", "rm_cost + scrap_credit", "{cur}", 1, ""),
    (MACHINING_SCOPE, "removed_cm3", "Volume machined away", "max(stock_volume_cm3 - part_volume_cm3, 0)", "cm³", 0, "Stock − part"),
    (MACHINING_SCOPE, "rough_rate_cm3_min", "Rough removal rate", "turn_rough_cm3_min if is_turned > 0 else mill_rough_cm3_min", "cm³/min", 0,
     "Turning or milling rate of the material"),
    (MACHINING_SCOPE, "rough_min", "Roughing time", "removed_cm3 / rough_rate_cm3_min", "min", 0, ""),
    (MACHINING_SCOPE, "finish_min", "Finishing time", "surface_cm2 / finish_cm2_min", "min", 0, "Whole surface finished once"),
    (MACHINING_SCOPE, "drill_min", "Drilling time", "hole_depth_mm / drill_mm_min + hole_count * drill_retract_s / 60", "min", 0, ""),
    (MACHINING_SCOPE, "cutting_min", "Cutting time", "rough_min + finish_min + drill_min", "min", 0, ""),
    (MACHINING_SCOPE, "idle_min", "Tool changes and rapids", "cutting_min * tool_change_pct / 100", "min", 0, ""),
    (MACHINING_SCOPE, "handling_s", "Loading per part", "setups * load_unload_s", "s", 0, "Load, clamp, unload per set-up"),
    (MACHINING_SCOPE, "setup_share_s", "Set-up per part", "setups * setup_h * 3600 / batch_size", "s", 0, "Set-up shared by the batch"),
    (MACHINING_SCOPE, "cycle_s", "Machining time per part", "(cutting_min + idle_min) * 60 + handling_s + setup_share_s", "s", 0,
     "The cycle time of the part cost"),
    (MACHINING_SCOPE, "hours_per_year", "Machine hours per year", "annual_volume * cycle_s / 3600 / (oee_pct / 100)", "h", 0, ""),
    (MACHINING_SCOPE, "available_h", "Hours one machine runs per year", "working_days * shifts_per_day * hours_per_shift", "h", 0, ""),
    (MACHINING_SCOPE, "machines_needed", "Machines (and fixture sets) needed", "max(1, ceil(hours_per_year / available_h))", "machines", 0, ""),
    (MACHINING_SCOPE, "fixture_factor", "Fixture share", "fixture_factor_turned if is_turned > 0 else fixture_factor_milled", "", 0,
     "Soft jaws for turned parts, a fixture for milled parts"),
    (MACHINING_SCOPE, "fixture_cost", "Fixture cost per set", "setups * fixture_factor * fixture_rate", "{cur}", 1, "One fixture per set-up"),
    (MACHINING_SCOPE, "fixture_capex", "Fixture CAPEX", "fixture_cost * machines_needed", "{cur}", 0, "One fixture set per machine"),
    (MACHINING_SCOPE, "fixture_weight_kg", "Fixture weight per set", "setups * fixture_kg_per_setup", "kg", 0, ""),
]
INPUTS = [  # scope, variable, label, source, category, item, money, unit
    ("rm_machined", "net_weight_g", "Net part weight", "part", "", "net_weight_g", 0, "g"),
    ("rm_machined", "density_g_cm3", "Density", "part", "", "density_g_cm3", 0, "g/cm³"),
    ("rm_machined", "stock_size_mm", "Stock size (Ø / across flats / thickness)", "part", "", "stock_size_mm", 0, "mm"),
    ("rm_machined", "stock_width_mm", "Stock width", "part", "", "stock_width_mm", 0, "mm"),
    ("rm_machined", "stock_length_mm", "Stock cut length per part", "part", "", "stock_length_mm", 0, "mm"),
    ("rm_machined", "section_factor", "Section factor of the stock shape", "part", "", "section_factor", 0, ""),
    ("rm_machined", "bar_end_loss_pct", "Bar end loss", "parameter", "", "bar_end_loss_pct", 0, "%"),
    ("rm_machined", "chip_recovery_pct", "Chips sold as scrap", "parameter", "", "chip_recovery_pct", 0, "%"),
    ("rm_machined", "material_rate", "Bar rate", "rate", "material", "{material}", 1, ""),
    ("rm_machined", "scrap_rate", "Chips scrap rate", "rate", "material_scrap", "{material}", 1, ""),
] + [(MACHINING_SCOPE, k, label, "machining", "", k, 0, unit) for k, label, unit in (
    ("is_turned", "Turned (1) or milled (0)", ""), ("stock_volume_cm3", "Stock volume per part", "cm³"),
    ("part_volume_cm3", "Part volume", "cm³"), ("surface_cm2", "Part surface", "cm²"), ("hole_count", "Drilled holes", "holes"),
    ("hole_depth_mm", "Drilled depth (all holes)", "mm"), ("setups", "Set-ups per part", "set-ups"),
    ("turn_rough_cm3_min", "Rough turning removal", "cm³/min"), ("mill_rough_cm3_min", "Rough milling removal", "cm³/min"),
    ("finish_cm2_min", "Finish machining rate", "cm²/min"), ("drill_mm_min", "Drilling feed", "mm/min"),
    ("annual_volume", "Annual volume", "parts/yr"))] + [
    (MACHINING_SCOPE, k, label, "parameter", "", k, 0, unit) for k, label, unit in (
        ("tool_change_pct", "Tool changes and rapids", "%"), ("load_unload_s", "Load / unload per set-up", "s"),
        ("setup_h", "Set-up per set-up", "h"), ("batch_size", "Batch size", "parts"), ("drill_retract_s", "Approach and retract per hole", "s"),
        ("oee_pct", "OEE", "%"), ("working_days", "Working days", "days/yr"), ("shifts_per_day", "Shifts per day", "shifts"),
        ("hours_per_shift", "Hours per shift", "h"), ("fixture_factor_turned", "Fixture share, turned", ""),
        ("fixture_factor_milled", "Fixture share, milled", ""), ("fixture_kg_per_setup", "Fixture weight per set-up", "kg"))] + [
    (MACHINING_SCOPE, "fixture_rate", "Fixture rate per set-up", "rate", "process_unit", FIXTURE_RATE, 1, ""),
]
HS = [("part", "8487", "Machinery parts, not elsewhere specified (machined parts)"),
      ("tool", "8466", "Work holders and fixtures for machine tools")]


def _stock_rows() -> list[dict]:
    rows = [("round", s, 0) for s in ROUND] + [("hex", s, 0) for s in HEX] + [("square", s, 0) for s in SQUARE]
    rows += [("flat", t, w) for t in FLAT_T for w in FLAT_W if w >= t] + [("plate", t, 0) for t in PLATE_T]
    return [{"shape": sh, "size_mm": s, "width_mm": w, "section_factor": SECTION[sh], "is_example": True, "notes": EXAMPLE}
            for sh, s, w in rows]


def seed(month: str | None = None) -> dict:
    """Add the machined-part master data that is missing; existing rows are never changed.

    The process 'machined' gets the part type 'machined' only when its part type is still empty."""
    from . import country_rates
    out = {"materials": 0, "parameters": 0, "stock_sizes": 0, "machining_data": 0, "hs_codes": 0, "formulas": 0, "inputs": 0,
           "process": 0, "rates": 0}
    md = master_data.tables()
    sheets = {k: [dict(r) for r in v] for k, v in md.items()}
    have = {(r["part_type"], r["material"]) for r in sheets["Materials"]}
    for m, mtype, rec, dens, *_ in SEED_MATERIALS:
        if ("machined", m) not in have:
            sheets["Materials"].append({"part_type": "machined", "material": m, "material_type": mtype, "recommended": rec,
                                        "density_g_cm3": dens, "notes": "EXAMPLE density and rates. Rates: Rates page (material / material_scrap)"})
            out["materials"] += 1
    have = {(r["part_type"], r["parameter"]) for r in sheets["Parameters"]}
    for k, (v, u, d) in SEED_PARAMETERS.items():
        if ("machined", k) not in have:
            sheets["Parameters"].append({"part_type": "machined", "parameter": k, "value": v, "unit": u, "description": d})
            out["parameters"] += 1
    if out["materials"] or out["parameters"]:
        master_data.write(sheets)

    d = mould_db.tables()
    have = {(r["shape"], r["size_mm"], r["width_mm"]) for r in d["stock_sizes"]}
    for r in _stock_rows():
        if (r["shape"], r["size_mm"], r["width_mm"]) not in have:
            d["stock_sizes"].append(r)
            out["stock_sizes"] += 1
    have = {r["material"] for r in d["machining_data"]}
    for m, _, _, _, _, _, turn, mill, fin, drill in SEED_MATERIALS:
        if m not in have:
            d["machining_data"].append({"material": m, "turn_rough_cm3_min": turn, "mill_rough_cm3_min": mill, "finish_cm2_min": fin,
                                        "drill_mm_min": drill, "is_example": True, "notes": EXAMPLE})
            out["machining_data"] += 1
    have = {(r["scope"], r["part_type"]) for r in d["hs_codes"]}
    for scope, code, desc in HS:
        if (scope, "machined") not in have:
            d["hs_codes"].append({"scope": scope, "part_type": "machined", "hs_code": code, "description": desc, "is_example": True,
                                  "notes": "EXAMPLE - check the tariff heading with your customs broker"})
            out["hs_codes"] += 1
    if out["stock_sizes"] or out["machining_data"] or out["hs_codes"]:
        mould_db.write(d)

    s = costing_setup.tables()
    have = {(r["scope"], r["name"]) for r in s["cost_formulas"]}
    for scope, name, label, f, unit, res, desc in FORMULAS:
        if (scope, name) not in have:
            s["cost_formulas"].append({"scope": scope, "name": name, "label": label, "formula": f, "unit": unit, "is_result": bool(res),
                                       "description": desc})
            out["formulas"] += 1
    have = {(r["scope"], r["variable"]) for r in s["formula_inputs"]}
    for scope, var, label, source, cat, item, money, unit in INPUTS:
        if (scope, var) not in have:
            s["formula_inputs"].append({"scope": scope, "variable": var, "label": label, "source": source, "category": cat,
                                        "item": item, "is_money": bool(money), "unit": unit})
            out["inputs"] += 1
    if out["formulas"] or out["inputs"]:
        costing_setup.write(s)

    r = register_setup.tables()
    proc = next((p for p in r["processes"] if p["code"] == "machined"), None)
    if proc and not proc["part_type"]:
        proc["part_type"] = "machined"
        register_setup.write(r)
        out["process"] = 1

    out["rates"] = _seed_rates(month, country_rates) + _seed_duty(month, country_rates)
    return out


# HS code: (basic customs duty %, preferential FTA duty % by origin), and IGST % in India (stage 11 rows of the same shape)
DUTY = {"8487": (7.5, {"JP": 0, "KR": 0, "TH": 5, "VN": 5}), "8466": (7.5, {"JP": 0, "KR": 0, "TH": 5, "VN": 5})}
IGST_PCT = 18


def _seed_duty(month, country_rates) -> int:
    """Duty rates (category duty) for the HS codes of machined parts and fixtures, where none exist yet. EXAMPLE values."""
    month = month or rates.current_month()
    base = country_rates.base_country()["code"]
    others = [c["code"] for c in costing_setup.tables()["countries"] if c["code"] != base]
    wanted = []
    for hs, (bcd, fta) in DUTY.items():
        wanted += [(f"bcd_pct:{hs}", c, bcd, SEED_SOURCE) for c in others]
        wanted += [(f"bcd_pct_fta:{hs}", c, v, "Preferential rate (JP/KR CEPA, ASEAN AIFTA); needs a certificate of origin")
                   for c, v in fta.items() if c in others]
        wanted.append((f"igst_pct:{hs}", base, IGST_PCT, SEED_SOURCE))
    made = 0
    for item, c, v, note in wanted:
        with closing(rates._connect()) as con:
            if country_rates._exists(con, "duty", item, c):
                continue
        rates.create({"category": "duty", "item": item, "country": c, "value": v, "unit": "%", "currency": "INR", "month": month,
                      "source": "EXAMPLE placeholder - replace with your market rate", "comment": note, "is_example": True},
                     approve=True, origin="seed", approver="Example seed", system=True)
        made += 1
    return made


def _seed_rates(month, country_rates) -> int:
    """Bar, chips and fixture rates: the base country (INR) as approved EXAMPLE rates, the other countries from the country
    index × forex (as country_rates.propose does), only where a country has no version of that rate yet."""
    month = month or rates.current_month()
    base = country_rates.base_country()
    wanted = [("material", m, inr, "kg") for m, _, _, _, inr, *_ in SEED_MATERIALS]
    wanted += [("material_scrap", m, scrap, "kg") for m, _, _, _, _, scrap, *_ in SEED_MATERIALS]
    wanted += [("process_unit", FIXTURE_RATE, 20000, "set-up")]
    tables = costing_setup.tables()
    index = {r["country"]: r for r in tables["country_index"]}
    made = 0
    for cat, item, value, per in wanted:
        for c in tables["countries"]:
            with closing(rates._connect()) as con:
                if country_rates._exists(con, cat, item, c["code"]):
                    continue
            if c["code"] == base["code"]:
                v, src, note = value, SEED_SOURCE, f"{base['code']} value. EXAMPLE: replace with a supplier quote or market rate."
            else:
                if c["code"] not in index:
                    continue
                try:
                    fx = rates.lookup("forex", c["currency"], "", month)["value"]
                except rates.RateMissing:
                    continue
                factor = index[c["code"]][country_rates.GROUPS[cat][1]]
                v = country_rates._round(value * factor / fx)
                src = SEED_SOURCE
                note = (f"{base['code']} {value} {base['currency']}/{per} × {country_rates.GROUPS[cat][1].replace('_', ' ')} {factor} ÷ "
                        f"{fx} INR per {c['currency']}. EXAMPLE: replace with a supplier quote or market rate.")
            rates.create({"category": cat, "item": item, "country": c["code"], "value": v, "unit": f"{c['currency']}/{per}",
                          "currency": c["currency"], "month": month, "source": src, "comment": note, "is_example": True},
                         approve=True, origin="seed", approver="Example seed", system=True)
            made += 1
    return made


# ---------- the part ----------

def params() -> dict:
    return master_data.parameters("machined")


def _num(p: dict, key: str) -> float:
    v = p.get(key)
    if not isinstance(v, (int, float)):
        raise MachiningError(f"Master data → Parameters has no number '{key}' for machined parts.")
    return float(v)


def route(features: dict, typed: dict) -> tuple[str, str]:
    """('turned' | 'milled', why)."""
    if typed.get("route") in ROUTES:
        return typed["route"], "typed on the part (Machining & fixture → inputs)"
    limit = _num(params(), "turned_min_round_share")
    share = features.get("round_share") or 0
    if share >= limit and features.get("turn_dia_mm"):
        return "turned", f"{100 * share:.0f} % of the surface turns about one axis (≥ {100 * limit:.0f} %, Parameters → turned_min_round_share)"
    return "milled", f"{100 * share:.0f} % of the surface turns about one axis (< {100 * limit:.0f} %, Parameters → turned_min_round_share)"


def pick_stock(features: dict, way: str, shape: str | None = None) -> dict:
    """The smallest standard stock (Stock sizes) that holds the part with the allowances of Parameters."""
    p = params()
    rows = mould_db.tables()["stock_sizes"]
    cut = _num(p, "cut_off_mm")
    cands = []
    if way == "turned":
        need = features["turn_dia_mm"] + _num(p, "dia_allowance_mm")
        length = features["turn_length_mm"] + 2 * _num(p, "face_allowance_mm") + cut
        shapes = (shape,) if shape else ("round",)
        if set(shapes) - {"round", "hex"}:
            raise MachiningError("A turned part is made from round or hex bar.")
        for r in rows:
            if r["shape"] in shapes and r["size_mm"] >= need:
                cands.append((r, r["size_mm"], length))
        what = f"Ø{need:g} mm (largest Ø {features['turn_dia_mm']:g} + dia_allowance_mm)"
    else:
        allow = 2 * _num(p, "mill_allowance_mm")
        a, b, c = (x + allow for x in features["sizes_mm"])
        length = a + cut
        shapes = (shape,) if shape else ("square", "flat", "plate")
        for r in rows:
            if r["shape"] not in shapes:
                continue
            if r["shape"] == "square" and r["size_mm"] >= b:
                cands.append((r, r["size_mm"], length))
            elif r["shape"] == "flat" and r["size_mm"] >= c and r["width_mm"] >= b:
                cands.append((r, r["width_mm"], length))
            elif r["shape"] == "plate" and r["size_mm"] >= c:
                cands.append((r, b, length))
            elif r["shape"] in ("round", "hex") and r["size_mm"] * (1 if r["shape"] == "hex" else 1) >= (b * b + c * c) ** 0.5:
                cands.append((r, r["size_mm"], length))
        what = f"{b:g} × {c:g} mm section (box {' × '.join(f'{x:g}' for x in features['sizes_mm'][1:])} + 2 × mill_allowance_mm)"
    if not cands:
        raise MachiningError(f"No size in Mould & die database → Stock sizes{' (' + shape + ')' if shape else ''} takes {what}: "
                             "add a bigger size there.")
    r, width, length = min(cands, key=lambda x: (x[0]["section_factor"] * x[0]["size_mm"] * x[1] * x[2], x[0]["size_mm"]))
    width = r["size_mm"] if r["shape"] in ("round", "hex", "square") else width
    label = {"round": f"Round bar Ø{r['size_mm']:g}", "hex": f"Hex bar {r['size_mm']:g} AF", "square": f"Square bar {r['size_mm']:g}",
             "flat": f"Flat bar {r['size_mm']:g} × {r['width_mm']:g}", "plate": f"Plate {r['size_mm']:g} thick, cut {width:g} wide"}[r["shape"]]
    return {"shape": r["shape"], "size_mm": r["size_mm"], "width_mm": width, "length_mm": round(length, 3),
            "section_factor": r["section_factor"], "is_example": r["is_example"], "label": f"{label} × {length:g} long",
            "needed": what, "row": f"{r['shape']} {r['size_mm']:g}" + (f" × {r['width_mm']:g}" if r["width_mm"] else "")}


def features_of(rev: dict) -> dict:
    """Machining features of a revision (geometry.machining_features), worked out once and kept in its geometry."""
    from sqlalchemy import select

    from . import file_store
    from . import projects_db as db
    from .geometry import load_step, machining_features
    g = rev["geometry"] or {}
    hole_max = _num(params(), "hole_max_dia_mm")
    key = f"v1:{hole_max:g}"
    cached = (g.get("machining") or {}).get(key)
    if cached:
        return cached
    with db.engine().connect() as conn:
        row = conn.execute(select(db.files).where(db.files.c.id == rev["file_id"])).mappings().first()
    path = file_store.path_of(dict(row)) if row else None
    if not path or not path.exists():
        raise MachiningError("The 3D file of this revision is not in the storage folder, so the part cannot be measured for machining.")
    f = machining_features(load_step(str(path)), hole_max)
    geo = dict(g)
    geo["machining"] = dict(g.get("machining") or {}) | {key: f}
    with db.engine().begin() as conn:
        conn.execute(db.revisions.update().where(db.revisions.c.id == rev["id"]).values(geometry=geo))
    return f


def stock_for(rev: dict, typed: dict) -> tuple[dict, dict, str, str]:
    """(features, stock, route, why) of a revision with the inputs typed on the part."""
    f = features_of(rev)
    way, why = route(f, typed)
    if way == "turned" and not f.get("turn_dia_mm"):
        raise MachiningError("The 3D model has no turned surface, so it cannot be turned: choose 'milled'.")
    return f, pick_stock(f, way, typed.get("stock_shape") or None), way, why


def rm_part_items(rev: dict, typed: dict) -> tuple[dict, dict]:
    """The part values of the RM formulas (rm_machined) and the stock picked."""
    _, st, way, why = stock_for(rev, typed)
    src = {"type": "master", "sheet": "Mould & die database → Stock sizes", "row": st["row"], "is_example": st["is_example"],
           "note": f"{way} ({why}); needs {st['needed']}; smallest standard size that holds it: {st['label']}"}
    p = lambda k: {"type": "master", "sheet": "Parameters", "row": f"machined / {k}"}  # noqa: E731
    items = {
        "stock_size_mm": {"value": st["size_mm"], "unit": "mm", "source": src},
        "stock_width_mm": {"value": st["width_mm"], "unit": "mm", "source": src | (
            {"note": f"Part width + 2 × mill_allowance_mm, cut from the plate ({st['label']})"} if st["shape"] == "plate" else {})},
        "stock_length_mm": {"value": st["length_mm"], "unit": "mm", "source": p("face_allowance_mm, cut_off_mm") | {
            "note": ("turned length + 2 × face_allowance_mm + cut_off_mm" if way == "turned" else "longest size + 2 × mill_allowance_mm + cut_off_mm")}},
        "section_factor": {"value": st["section_factor"], "unit": "", "source": src | {"note": f"Section factor of {st['shape']} stock"}},
    }
    return items, st | {"route": way, "why": why}


def run(part_id: int, country: str | None = None) -> dict:
    """Machining time, machine and fixture of a machined part, traced; shaped like a tool cost result so it is stored as one."""
    from . import register
    from .piece_cost import graft
    from .tool_cost import examples
    d = register.part_detail(part_id, with_rm=False)
    rev = d["revisions"][0] if d["revisions"] else None
    if not rev or not rev["file_id"]:
        raise MachiningError("This part has no 3D file yet. Upload a revision.")
    typed = d["tool_inputs"] or {}
    try:
        rm = register._rm_compute(part_id, (country or d["tool_country"] or None))
    except (register.RegisterError, register.RMNotApplicable) as exc:
        raise MachiningError(str(exc)) from None
    f, st, way, why = stock_for(rev, typed)
    p = params()
    country = (country or d["tool_country"] or d["country"] or register_setup.settings()["default_country"]).upper()
    as_of = d["costing_month"] or rates.current_month()
    setup = costing_setup.tables()
    cur = {c["code"]: c for c in setup["countries"]}[country]["currency"]
    t = Trace(cur, (d.get("trace_overrides") or {}).get("tool"))
    you = {"type": "user", "note": f"Typed in the part register for {d['part_code']}"}
    cad = {"type": "cad", "file": rev["original_name"], "rev": rev["rev"], "sha256": rev["sha256"]}
    g = rev["geometry"]
    data = mould_db.machining_data(d["material"])
    if not data:
        raise MachiningError(f"Mould & die database → Machining data has no row for '{d['material']}'. Add its removal rates there.")
    msrc = lambda col: {"type": "master", "sheet": "Mould & die database → Machining data", "row": f"{d['material']} / {col}",  # noqa: E731
                        "is_example": data["is_example"]}
    drilled = [h for h in f["holes"] if not (way == "turned" and h["on_turn_axis"])]
    setups_key = "setups_turned" if way == "turned" else "setups_milled"
    volume, vnote = register._annual_volume(d)
    stock_node = graft(t, rm, "rm:") and "rm:calc:stock_volume_cm3"
    items = {
        "is_turned": (1 if way == "turned" else 0, "", you if typed.get("route") else cad | {"note": f"{way}: {why}"}),
        "stock_volume_cm3": stock_node,
        "part_volume_cm3": (g["volume_cm3"], "cm³", cad | {"note": "Measured from the STEP file"}),
        "surface_cm2": (g["surface_area_mm2"] / 100, "cm²", cad | {"note": "Measured from the STEP file"}),
        "hole_count": (len(drilled), "holes", cad | {"note": ", ".join(f"Ø{h['dia_mm']:g} × {h['depth_mm']:g}" for h in drilled) or "no drilled holes"}),
        "hole_depth_mm": (sum(h["depth_mm"] for h in drilled), "mm", cad | {"note": "Σ depth of the drilled holes"}),
        "setups": (typed.get("setups") or _num(p, setups_key), "set-ups",
                   you if typed.get("setups") else {"type": "master", "sheet": "Parameters", "row": f"machined / {setups_key}"}),
        "turn_rough_cm3_min": (data["turn_rough_cm3_min"], "cm³/min", msrc("turn_rough_cm3_min")),
        "mill_rough_cm3_min": (data["mill_rough_cm3_min"], "cm³/min", msrc("mill_rough_cm3_min")),
        "finish_cm2_min": (data["finish_cm2_min"], "cm²/min", msrc("finish_cm2_min")),
        "drill_mm_min": (data["drill_mm_min"], "mm/min", msrc("drill_mm_min")),
        "annual_volume": ((volume or p.get("annual_volume") or 0), "parts/yr", {"type": "register", "note": vnote}),
    }
    names, missing = {}, []
    inputs = [r for r in setup["formula_inputs"] if r["scope"] == MACHINING_SCOPE]
    if not inputs:
        raise MachiningError("Master data has no Formula inputs for scope 'machining'.")
    for inp in inputs:
        var, label, nid = inp["variable"], inp["label"] or inp["variable"], f"in:{inp['variable']}"
        if inp["source"] == "machining":
            v = items.get(inp["item"])
            if isinstance(v, str):
                nid = v
            else:
                t.add_input(nid, label, float(v[0]), v[1], v[2])
        elif inp["source"] == "parameter":
            if not isinstance(p.get(inp["item"]), (int, float)):
                raise MachiningError(f"{label}: Master data → Parameters has no number '{inp['item']}' for machined parts.")
            t.add_input(nid, label, p[inp["item"]], inp["unit"], {"type": "master", "sheet": "Parameters", "row": f"machined / {inp['item']}"})
        elif inp["source"] == "rate":
            try:
                rate = rates.lookup(inp["category"], inp["item"], country, as_of)
            except rates.RateMissing as exc:
                missing.append(str(exc))
                t.add_input(nid, label, 0, inp["unit"], {"type": "missing", "note": str(exc)}, money=bool(inp["is_money"]))
            else:
                t.add_rate(nid, label, rate, money=bool(inp["is_money"]))
                if inp["is_money"]:
                    nid = rate_engine._convert(t, nid, label, rate["currency"], cur, as_of)
        names[var] = nid
    try:
        result, components, order = rate_engine.evaluate_scope(t, setup, MACHINING_SCOPE, names, cur, as_of)
    except (rate_engine.EngineError, rates.RateMissing) as exc:
        raise MachiningError(str(exc)) from None
    except ZeroDivisionError:
        raise MachiningError("A machining formula divides by zero: check the Machining data and Parameters (batch size, OEE).") from None
    named = {r["name"]: t.value(f"calc:{r['name']}") for r in order}
    capex_node = "calc:fixture_capex" if "calc:fixture_capex" in t.nodes else None
    capex_inr = None
    if capex_node:
        capex_inr = t.compute("capex:inr", "Fixture CAPEX in INR", "value * fx", "INR", money=True,
                              names={"value": capex_node, "fx": rate_engine.fx_to_inr(t, cur, as_of)},
                              description=f"Converted with the INR per {cur} forex rate of {as_of}.")
    if "calc:fixture_weight_kg" in t.nodes:
        t.compute("tool_weight", "Fixture weight", "value", "kg", names={"value": "calc:fixture_weight_kg"})
    mid = p.get("machine_turned" if way == "turned" else "machine_milled")
    machine = next((m for m in setup["machines"] if m["machine_id"] == mid), None)
    if not machine:
        raise MachiningError(f"Parameters → {'machine_turned' if way == 'turned' else 'machine_milled'} ('{mid}') is not in Master data → Machines.")
    out = t.to_dict(result)
    machines = int(round(named.get("machines_needed", 1)))
    out |= {"part_type": "machined", "country": country, "currency": cur, "as_of": as_of, "material": d["material"],
            "value": t.value(result), "value_inr": t.value("result:inr"), "capex": t.value(capex_node) if capex_node else None,
            "capex_inr": capex_inr, "capex_node": capex_node, "tools_count": machines, "cavities": 1, "components": components,
            "named": named, "route": way, "route_why": why, "stock": st, "holes": f["holes"], "round_share": f["round_share"],
            "cycle_node": "calc:cycle_s", "steps": [{"name": r["name"], "node": f"calc:{r['name']}", "is_result": bool(r["is_result"])} for r in order],
            "inputs": [{"variable": k, "node": v} for k, v in names.items()],
            "trial": {"machine": machine, "machine_node": None, "force_node": None, "force_t": 0, "process": machine["process"]},
            "missing": missing + rm["missing"], "priced": not (missing or rm["missing"]), "warnings": []}
    out["example"] = examples(out)
    return out
