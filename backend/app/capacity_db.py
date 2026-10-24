"""Machine and mould / die database up to 3000 t (roadmap stage 20).

`extend()` adds the missing rungs of the machine ladders (injection moulding, die casting, presses) and the standard mould
bases / die holders that go with them, plus the machine prices and consumables of all countries. It never changes a row that
already exists, so it is safe to run again. Every value it adds is an EXAMPLE placeholder (scaled from the rows already in the
database) to be replaced on Master data → Replace example values.

`coverage()` is the validation: for every process and every tonnage step from 0 to 3000 t it checks that a machine, a mould
base or die holder that fits its tie bars, and an approved rate for the machine exist in every country.
"""

from __future__ import annotations

import math
from contextlib import closing

from . import costing_setup, master_data, mould_db, rates

MAX_T = 3000.0
EXAMPLE_NOTE = "EXAMPLE machine data - scaled from the existing machines, replace with your machine"
BASE_NOTE = "EXAMPLE placeholder - replace with your supplier / catalogue value"

# process -> (machine id prefix, name, tonnages that must exist)
LADDERS = {
    "Injection moulding": ("IMM", "Injection moulding machine {t} t",
                           [80, 120, 150, 200, 250, 350, 450, 550, 650, 800, 1000, 1300, 1600, 2000, 2500, 3000]),
    "Die casting": ("HPDC", "Cold-chamber die casting machine {t} t",
                    [250, 400, 630, 800, 1000, 1250, 1600, 2000, 2500, 3000]),
    "Press": ("PRESS", "Mechanical / servo press {t} t",
              [63, 100, 160, 200, 250, 315, 400, 630, 800, 1000, 1250, 1600, 2000, 2500, 3000]),
}
# existing reference machine used to scale price, power, floor area, life (price follows tonnage^0.75)
REFERENCE = {"Injection moulding": ("IMM-450", 450), "Die casting": ("HPDC-800", 800), "Press": ("PRESS-400", 400)}

# New standard bases: (part_type, series, W cm, L cm). Existing sizes are not touched.
NEW_BASES = (
    [("plastic", "Standard 2-plate", w, l) for w, l in
     [(70, 70), (70, 80), (80, 80), (80, 90), (90, 90), (90, 100), (100, 100), (100, 120), (120, 120), (120, 140),
      (140, 160), (160, 180), (180, 200)]]
    + [("die_casting", "Die holder", w, l) for w, l in
       [(100, 100), (100, 120), (120, 120), (120, 140), (140, 150), (150, 160), (160, 170)]]
)
# Blow-mould holders and EPS steam chests for large containers / boxes: (part_type, series, length mm, width mm, insert length, insert width, plate mm, stack mm)
EXTRA_BASES = [("blow", "Blow mould holder", 600, 300, 520, 240, 80, 200), ("blow", "Blow mould holder", 800, 400, 700, 340, 100, 240),
               ("blow", "Blow mould holder", 1000, 500, 900, 440, 120, 280), ("blow", "Blow mould holder", 1200, 600, 1100, 540, 140, 320)]
KG_COST = {"plastic": 260.0, "die_casting": 300.0}   # same INR per kg as the seeded bases


def _tiebar(tonnage: float) -> float:
    """Tie-bar spacing (mm), fitted to the seeded machines (80 t 320 mm … 800 t 1000 mm), rounded to 10 mm."""
    return round(36.0 * math.sqrt(tonnage) / 10.0) * 10.0


def _code(w_cm: int, l_cm: int) -> str:
    return f"{w_cm}{l_cm}"


def _base_row(part_type: str, series: str, w_cm: int, l_cm: int) -> dict:
    length, width = l_cm * 10.0, w_cm * 10.0
    die = part_type == "die_casting"
    plate = round(width * (0.29 if die else 0.19) / 5) * 5
    clamp = 60.0 if die else 30.0
    support = 80.0 if die else 50.0 if width < 1000 else 60.0
    spacer = round(width * (0.2 if die else 0.2) / 10) * 10
    ejector = 70.0 if die else 55.0 if width < 1000 else 70.0
    stack = plate * 2 + support + spacer + ejector
    return {
        "part_type": part_type, "series": series, "size_code": _code(w_cm, l_cm), "length_mm": length, "width_mm": width,
        "max_insert_length_mm": round(length * (0.66 if length < 800 else 0.74) / 10) * 10.0,
        "max_insert_width_mm": round(width * (0.63 if width < 800 else 0.72) / 10) * 10.0,
        "a_plate_mm": plate, "b_plate_mm": plate, "clamp_plates_mm": clamp, "support_plate_mm": support,
        "spacer_block_mm": spacer, "ejector_plates_mm": ejector, "stack_height_mm": stack,
        "weight_kg": round(length * width * stack * 7.85e-6 * 0.89, 1),
        "cost": round(length * width * stack * 7.85e-6 * 0.89 * KG_COST[part_type], -2),
        "is_example": 1, "notes": BASE_NOTE,
    }


def _machine_row(process: str, tonnage: int) -> dict:
    prefix, name, _ = LADDERS[process]
    ref_id, ref_t = REFERENCE[process]
    ref = next(m for m in costing_setup.tables()["machines"] if m["machine_id"] == ref_id)
    k = tonnage / ref_t
    tie = _tiebar(tonnage) if process != "Press" else None
    row = {
        "machine_id": f"{prefix}-{tonnage}", "name": name.format(t=tonnage), "process": process,
        "power_kw": round(ref["power_kw"] * k ** 0.95, 1), "load_factor_pct": ref["load_factor_pct"],
        "floor_area_m2": round(ref["floor_area_m2"] * k ** 0.7, 1), "life_years": ref["life_years"],
        "residual_pct": ref["residual_pct"], "maintenance_pct": ref["maintenance_pct"], "tonnage_t": float(tonnage),
        "length_mm": float(tie) if tie else round(1000 * (tonnage / 100) ** 0.45 / 50) * 50.0,
        "width_mm": float(tie) if tie else round(600 * (tonnage / 100) ** 0.45 / 50) * 50.0,
        "is_example": 1, "notes": EXAMPLE_NOTE,
    }
    return row


def _price_pairs(process: str, tonnage: int) -> tuple[float, float]:
    ref_id, ref_t = REFERENCE[process]
    with closing(rates._connect()) as con:
        got = {r["category"]: r["value"] for r in con.execute(
            "SELECT category, value FROM rates WHERE item=? AND country='IN' AND category IN ('machine_price','consumables') "
            "ORDER BY id", (ref_id,))}
    k = tonnage / ref_t
    return got["machine_price"] * k ** 0.75, got["consumables"] * k ** 0.8


def extend(month: str | None = None) -> dict:
    """Add the missing machines, mould bases and machine rates. Returns what was added."""
    month = month or rates.current_month()
    added = {"machines": [], "mould_bases": [], "rates": 0}
    data = costing_setup.tables()
    have = {m["machine_id"] for m in data["machines"]}
    new_machines = [(p, t) for p, (_, _, ts) in LADDERS.items() for t in ts if f"{LADDERS[p][0]}-{t}" not in have]
    rows = [_machine_row(p, t) for p, t in new_machines]
    if rows:
        data["machines"] = data["machines"] + rows
        costing_setup.write(data)
        added["machines"] = [r["machine_id"] for r in rows]

    db = mould_db.tables()
    have_b = {(b["part_type"], b["size_code"]) for b in db["mould_bases"]}
    new_b = [_base_row(*b) for b in NEW_BASES if (b[0], _code(b[2], b[3])) not in have_b]
    for pt, series, length, width, il, iw, plate, stack in EXTRA_BASES:
        code = f"{round(length / 10)}{round(width / 10)}"
        if (pt, code) not in have_b:
            wt = round(length * width * stack * 7.85e-6 * 0.6, 1)
            new_b.append({"part_type": pt, "series": series, "size_code": code, "length_mm": float(length), "width_mm": float(width),
                          "max_insert_length_mm": float(il), "max_insert_width_mm": float(iw), "a_plate_mm": float(plate), "b_plate_mm": float(plate),
                          "clamp_plates_mm": 0.0, "support_plate_mm": 0.0, "spacer_block_mm": 0.0, "ejector_plates_mm": 0.0, "stack_height_mm": float(stack),
                          "weight_kg": wt, "cost": round(wt * 300.0, -2), "is_example": 1, "notes": BASE_NOTE})
    if new_b:
        db["mould_bases"] = db["mould_bases"] + new_b
        mould_db.write(db)
        added["mould_bases"] = [f"{b['part_type']} {b['size_code']}" for b in new_b]

    # machine price + consumables per country: India value scaled from the reference machine, other countries by the
    # same ratio the reference machine already has against India.
    countries = {c["code"]: c for c in costing_setup.tables()["countries"]}
    with closing(rates._connect()) as con:
        ratio = {}
        for cc in countries:
            for cat in ("machine_price", "consumables"):
                for ref_id, _ in REFERENCE.values():
                    a = con.execute("SELECT value FROM rates WHERE category=? AND item=? AND country='IN' ORDER BY id DESC",
                                    (cat, ref_id)).fetchone()
                    b = con.execute("SELECT value, unit, currency FROM rates WHERE category=? AND item=? AND country=? ORDER BY id DESC",
                                    (cat, ref_id, cc)).fetchone()
                    if a and b:
                        ratio[(cat, cc)] = (b["value"] / a["value"], b["unit"], b["currency"])
                        break
        missing = []
        for process, (prefix, _, ts) in LADDERS.items():
            for t in ts:
                mid = f"{prefix}-{t}"
                price, cons = _price_pairs(process, t)
                for cc in countries:
                    for cat, base in (("machine_price", price), ("consumables", cons)):
                        if cc not in {c for c in countries} or (cat, cc) not in ratio:
                            continue
                        if con.execute("SELECT 1 FROM rates WHERE category=? AND item=? AND country=?", (cat, mid, cc)).fetchone():
                            continue
                        f, unit, cur = ratio[(cat, cc)]
                        missing.append((cat, mid, cc, base * f, unit, cur))
    for cat, mid, cc, value, unit, cur in missing:
        value = float(f"{value:.3g}") if value < 1000 else round(value, -3 if value > 1e5 else 0)
        rates.create({"category": cat, "item": mid, "country": cc, "value": value, "unit": unit, "currency": cur,
                      "month": month, "source": "Scaled from the existing machines (stage 20)", "comment": "",
                      "is_example": True}, approve=True, origin="seed", approver="Example seed")
    added["rates"] = len(missing)
    return added


# ---------------------------------------------------------------- validation

def _base_for_tiebar(part_type: str, tie_mm: float) -> dict | None:
    """Largest standard base whose plates still fit between the tie bars (either way round)."""
    fits = [b for b in mould_db.tables()["mould_bases"]
            if b["part_type"] == part_type and min(b["length_mm"], b["width_mm"]) <= tie_mm * 0.95
            and max(b["length_mm"], b["width_mm"]) <= tie_mm * 1.35]
    return max(fits, key=lambda b: b["length_mm"] * b["width_mm"], default=None)


def coverage(step_t: float = 250.0, as_of: str | None = None) -> dict:
    """Machine / mould-base / rate coverage for 0…3000 t per process. Every gap is listed; `ok` = no gaps."""
    as_of = as_of or rates.current_month()
    machines = costing_setup.tables()["machines"]
    countries = [c["code"] for c in costing_setup.tables()["countries"]]
    process_part = {"Injection moulding": "plastic", "Die casting": "die_casting", "Press": None}
    steps = [min(MAX_T, step_t * i) for i in range(1, int(math.ceil(MAX_T / step_t)) + 1)]
    out, gaps = [], []
    for process, part_type in process_part.items():
        ms = sorted((m for m in machines if m["process"] == process), key=lambda m: m["tonnage_t"])
        for t in steps:
            fit = next((m for m in ms if m["tonnage_t"] >= t), None)
            row = {"process": process, "required_t": t, "machine": fit["machine_id"] if fit else None,
                   "machine_t": fit["tonnage_t"] if fit else None, "base": None, "rate_countries": 0}
            if not fit:
                gaps.append(f"{process}: no machine of {t:g} t or more")
            else:
                if part_type:
                    base = _base_for_tiebar(part_type, min(fit["length_mm"], fit["width_mm"]))
                    row["base"] = f"{base['size_code']} ({base['length_mm']:g}×{base['width_mm']:g})" if base else None
                    if not base:
                        gaps.append(f"{process} {t:g} t: no mould base / die holder for tie bars {fit['length_mm']:g} mm")
                have = 0
                for cc in countries:
                    try:
                        rates.lookup("machine_price", fit["machine_id"], cc, as_of)
                        have += 1
                    except Exception:
                        gaps.append(f"{fit['machine_id']}: no approved machine price for {cc}")
                row["rate_countries"] = have
            out.append(row)
    return {"max_t": MAX_T, "rows": out, "gaps": gaps, "ok": not gaps,
            "machine_count": len([m for m in machines if m["process"] in process_part]),
            "mould_base_count": len(mould_db.tables()["mould_bases"])}


TARGETS_T = [50, 100, 250, 500, 800, 1000, 1500, 2000, 2500, 3000]
SHAPE = {"plastic": (1.6, 80.0), "die_casting": (1.4, 60.0)}   # length ÷ width, part height (mm)


def validate_designs(targets=None, as_of: str | None = None) -> dict:
    """Run the real mould sizing and tool-cost engines for every material of plastic moulds and die-casting dies at each
    target clamp force (0…3000 t), and check the chosen try-out machine takes the tool between its tie bars."""
    from . import master_data, tool_cost
    as_of = as_of or rates.current_month()
    mats = master_data.tables()["Materials"]
    rows = []
    for part_type in ("plastic", "die_casting"):
        p = master_data.parameters(part_type)
        per_cm2 = p["cavity_pressure_bar"] * p["clamp_safety_factor"] / 1000.0
        ratio, height = SHAPE[part_type]
        for t in (targets or TARGETS_T):
            area = 0.95 * t / per_cm2                                   # projected area of one part, cm²
            width = math.sqrt(area * 100 / (0.8 * ratio))
            length = ratio * width
            for m in (x for x in mats if x["part_type"] == part_type):
                vol = area * height / 10 * 0.35
                row = {"part_type": part_type, "material": m["material"], "target_t": t, "length_mm": round(length),
                       "width_mm": round(width), "height_mm": height, "projected_area_cm2": round(area, 1),
                       "ok": False, "problem": ""}
                try:
                    r = tool_cost.run(tool_cost.ToolInput(
                        part_type=part_type, part_length_mm=length, part_width_mm=width, part_height_mm=height,
                        projected_area_cm2=area, part_weight_g=vol * m["density_g_cm3"], part_volume_cm3=vol,
                        part_surface_cm2=area * 2.2, material=m["material"], cavities=1, as_of=as_of))
                except Exception as exc:  # a gap is a finding, not a crash
                    row["problem"] = str(exc)[:160]
                    rows.append(row)
                    continue
                trial = r["trial"]
                mach = trial.get("machine") or None
                mid = mach["machine_id"] if mach else None
                row.update(base=r["base"]["size_code"], base_l=r["base"]["length_mm"], base_w=r["base"]["width_mm"],
                           tool_cost_inr=round(r["value_inr"]), machine=mid, machine_t=mach["tonnage_t"] if mach else None,
                           clamp_t=round(trial.get("force_t", 0), 1))
                if not mach:
                    row["problem"] = "no try-out machine takes the clamp force"
                else:
                    tie = min(mach["length_mm"], mach["width_mm"])
                    short = min(r["base"]["length_mm"], r["base"]["width_mm"])
                    row["tie_bar_mm"] = tie
                    if short > tie * 0.95:
                        row["problem"] = f"mould base {short:g} mm does not fit between {tie:g} mm tie bars"
                    else:
                        row["ok"] = True
                rows.append(row)
    bad = [r for r in rows if not r["ok"]]
    return {"rows": rows, "total": len(rows), "failed": len(bad), "ok": not bad, "problems": bad}


def validate_sheet(targets=None, as_of: str | None = None) -> dict:
    """Sheet-metal stage tool design for every sheet material at each target blanking force (0…3000 t): the sequence, the
    stage die set from the Stage tool rules, and a press whose tonnage AND bolster take the die set."""
    from . import sheet_tools, tool_design
    mats = [r for r in mould_db.tables()["sheet_materials"]]
    dens = {m["material"]: m["density_g_cm3"] for m in master_data.tables()["Materials"] if m["part_type"] == "sheet_metal"}
    safety = master_data.parameters("sheet_metal").get("press_safety_factor", 1.0)
    rows = []
    for mat in mats:
        for t_target in (targets or TARGETS_T):
            thick = max(1.5, min(15.0, t_target / 200.0))          # heavier plate for heavier presses
            perim = t_target * 9806.65 / (thick * mat["shear_mpa"] * 1.1 * safety) * 0.95
            length = perim / 2 * 0.62
            width = perim / 2 - length
            blank = {"length": length, "width": width}
            density = dens.get(mat["material"], 7.85)
            area = length * width
            feat = {"t": thick, "blank_l": length, "blank_w": width, "blank_perimeter": perim,
                    "blank_dia": math.sqrt(4 * area / math.pi), "hole_count": 4, "hole_perimeter": 4 * 3.1416 * 20, "hole_area": 4 * 314.0,
                    "min_hole_d": 20.0, "bends": 2, "bend_len": 2 * width, "bend_radius": 3.0, "draw_depth": 0.0, "draw_dia": 0.0,
                    "part_l": length, "part_w": width, "part_h": 40.0, "weight_g": area * thick * density / 1000,
                    "annual_volume": 20000, "programme_years": 5, "density": density}
            row = {"material": mat["material"], "target_t": t_target, "blank_mm": f"{length:.0f} × {width:.0f}", "ok": False, "problem": ""}
            try:
                res = sheet_tools.run(feat, mat["material"], {"mode": "multi_stage"})
                fp = {"length_mm": length, "width_mm": width, "outline": [[0, 0], [length, 0], [length, width], [0, width], [0, 0]],
                      "holes": [], "area_mm2": area, "method": "synthetic"}
                geom = {"bbox_mm": {"length": length, "width": width, "height": 40.0}}
                design = tool_design.sheet_design(fp, {"best": {"values": {}}}, res, geom, "IN", as_of)
                big = max(design["stages"], key=lambda s: s["force_t"])
                row.update(force_t=big["force_t"], stage=big["name"], press=big["press"].get("machine_id"),
                           press_t=big["press"].get("tonnage_t"), die_set_mm=f"{big['values']['die_set_l_mm']:.0f} × {big['values']['die_set_w_mm']:.0f}",
                           stages=len(design["stages"]))
                if design["warnings"]:
                    row["problem"] = design["warnings"][0][:160]
                else:
                    row["ok"] = True
            except Exception as exc:
                row["problem"] = str(exc)[:160]
            rows.append(row)
    bad = [r for r in rows if not r["ok"]]
    return {"rows": rows, "total": len(rows), "failed": len(bad), "ok": not bad, "problems": bad}


def process_limits() -> list[dict]:
    """Largest machine of every process: the real upper limit for tools of that process."""
    out = {}
    for m in costing_setup.tables()["machines"]:
        if (m["tonnage_t"] or 0) > 0:
            cur = out.get(m["process"])
            if not cur or m["tonnage_t"] > cur["max_t"]:
                out[m["process"]] = {"process": m["process"], "max_t": m["tonnage_t"], "machine": m["machine_id"]}
    for r in out.values():
        r["reaches_3000t"] = r["max_t"] >= MAX_T
        r["note"] = ("" if r["reaches_3000t"] else "A smaller range is the physical limit of this process (EPS steam moulding, "
                                                   "stretch blow moulding); foundry patterns have no clamp tonnage.")
    return sorted(out.values(), key=lambda r: r["process"])


def validate(step_t: float = 250.0, as_of: str | None = None) -> dict:
    """Everything: machine / base / rate coverage, mould and die designs for every material, sheet-metal stage dies."""
    cov, des, sheet = coverage(step_t, as_of), validate_designs(None, as_of), validate_sheet(None, as_of)
    return {"coverage": cov, "designs": des, "sheet": sheet, "limits": process_limits(),
            "ok": cov["ok"] and des["ok"] and sheet["ok"], "max_t": MAX_T,
            "totals": {"cases": cov["rows"].__len__() + des["total"] + sheet["total"],
                       "failed": len(cov["gaps"]) + des["failed"] + sheet["failed"]}}


if __name__ == "__main__":
    import json
    from . import drawing_data, fea, foundry_design, sheet_compare, tool_components, tool_design, tool_internals, tool_review
    print(json.dumps({"machines_and_bases": extend(), "stage_rules": tool_design.seed(), "fea_parameters": fea.seed(),
                      "components": tool_components.seed(), "details": tool_internals.seed(), "review": tool_review.seed(),
                      "foundry": foundry_design.seed(), "sheet_compare": sheet_compare.seed(), "drawing_data": drawing_data.seed()}, indent=1))
