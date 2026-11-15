"""Oil and air system of the fin die (roadmap stage 62): mist oil on the punches and air blow for the slugs, as your fin die spec asks
(4-4 draw stage oil, 4-5 pierce oil and air blow, 4-7 edge trim, 4-12 a-c forced oiling, quick couplers, evaporative oil mist).

    oil stations   draw steps + ironing stations + fin_oil_fixed_stations (pierce, edge trim)
    oil nozzles    oil stations × ceil(foil width ÷ fin_oil_nozzle_pitch_mm)     mist nozzles over the punches, pulsed per stroke
    air nozzles    fin_air_stations × ceil(foil width ÷ fin_air_nozzle_pitch_mm)  air blow of the pierce / edge-trim slugs
    piping         2 × (die length + 2 × die width) ÷ 1000 m (an oil line and an air line along the die)
    BOM            nozzles, oil / air manifold blocks (one per station), piping per metre, solenoid valves (oil, air), stroke
                   timer, quick couplers (oil, air, each two halves), oil tank & mist regulator, fitting hours - each a BOM element
                   of part type fin (replaces the stage 57 lump sum 'Auto oiling & air-blow system')
    checks         air use = air nozzles × fin_air_nl_per_pulse × SPM ≤ fin_air_supply_nl_min; mist oil per pack (oil nozzles ×
                   fin_oil_ml_per_pulse × strokes per pack) ≤ the oil per pack of the part cost (1 L per 4 AC sets)

All values are master-data rows (EXAMPLE until you replace them with your die maker's practice); seed() only adds rows, and changes
the old lump-sum row only while it is still the text the software shipped.
"""

from __future__ import annotations

import math

from . import fin_die, mould_db

PT = fin_die.PART_TYPE
NOTE = "EXAMPLE fin die oil & air system rule (stage 62) - replace with your die maker's practice"
SIZING = [
    ("fin_oil_fixed_stations", 2, "stations", "Stations with mist oil besides the draw / ironing steps: pierce, edge trim"),
    ("fin_oil_nozzle_pitch_mm", 150, "mm", "Mist oil nozzles: one per this width of the foil, per oiled station"),
    ("fin_air_stations", 2, "stations", "Stations with air blow for the slugs: pierce, edge trim"),
    ("fin_air_nozzle_pitch_mm", 100, "mm", "Air blow nozzles: one per this width of the foil, per air-blow station"),
]
TIMES = [("oil_air_fit_h_base", 12, "h", "Fitting the oil & air system of one fin die"),
         ("oil_air_fit_h_per_nozzle", 0.25, "h", "Fitting per oil / air nozzle (bore, thread, hose)")]
DESIGN = [
    ("fin_air_nl_per_pulse", 0.05, "Nl", "Air blow: free air per nozzle per stroke"),
    ("fin_air_supply_nl_min", 1500, "Nl/min", "Compressed air the press line gives the die (check of the air blow)"),
    ("fin_oil_ml_per_pulse", 0.0005, "ml", "Mist oil per nozzle per stroke"),
]
LUMP = "Auto oiling & air-blow system"
LUMP_SHIPPED = {"quantity_rule": "1", "unit_cost_rule": "85000"}
# element, category, quantity rule, unit cost rule (INR), process, hours rule, make
BOM = [
    ("Mist oil nozzle", "bought_out", "oil_nozzles", "1800", "", "0", "Lubrication supplier"),
    ("Air blow nozzle", "bought_out", "air_nozzles", "900", "", "0", "Pneumatics supplier"),
    ("Oil manifold block (per oiled station)", "bought_out", "oil_stations", "6500", "", "0", "Die maker"),
    ("Air manifold block (per air-blow station)", "bought_out", "air_stations", "4500", "", "0", "Die maker"),
    ("Oil / air piping & fittings (per m)", "bought_out", "ceil(pipe_m)", "1200", "", "0", "Pneumatics supplier"),
    ("Solenoid valve (oil, air)", "bought_out", "2", "9500", "", "0", "Pneumatics supplier"),
    ("Stroke timer / oil-air controller", "bought_out", "1", "25000", "", "0", "Die maker"),
    ("Quick coupler halves (oil, air)", "bought_out", "4", "3500", "", "0", "Pneumatics supplier"),
    ("Oil tank & mist regulator", "bought_out", "1", "18000", "", "0", "Lubrication supplier"),
    ("Oil & air system fitting", "process", "1", "0", "Fitting & assembly", "oil_air_fit_h_base + oil_air_fit_h_per_nozzle * (oil_nozzles + air_nozzles)", ""),
]
VARS = fin_die.OIL_VARS


def seed() -> dict:
    """Add the oil & air rows; retire the stage 57 lump sum while it is still the shipped text. Idempotent."""
    d = mould_db.tables()
    out = {"rows": 0, "lump_retired": 0}
    for table, rows in (("sizing_rules", SIZING), ("time_parameters", TIMES)):
        have = {(r["part_type"], r["parameter"]) for r in d[table]}
        for k, v, unit, desc in rows:
            if (PT, k) not in have:
                d[table].append({"part_type": PT, "parameter": k, "value": v, "unit": unit, "description": f"{desc} (stage 62)", "is_example": True})
                out["rows"] += 1
    have = {(r["part_type"], r["parameter"]) for r in d["design_rules"]}
    for k, v, unit, desc in DESIGN:
        if (PT, k) not in have:
            d["design_rules"].append({"part_type": PT, "parameter": k, "value": v, "text": "", "unit": unit, "description": f"{desc} (stage 62)",
                                      "is_example": True})
            out["rows"] += 1
    have = {(r["part_type"], r["element"]) for r in d["bom_elements"]}
    for el, cat, qty, cost, proc, hrs, make in BOM:
        if (PT, el) not in have:
            d["bom_elements"].append({"part_type": PT, "element": el, "category": cat, "quantity_rule": qty, "unit_cost_rule": cost,
                                      "material_code": "", "weight_rule": "0", "process_code": proc, "hours_rule": hrs, "amount_rule": "0",
                                      "make": make, "std_part": "", "price_each_inr": 0, "operations": "", "is_example": True, "notes": NOTE})
            out["rows"] += 1
    lump = next((r for r in d["bom_elements"] if r["part_type"] == PT and r["element"] == LUMP), None)
    if lump and all(str(lump[k]) == v for k, v in LUMP_SHIPPED.items()):
        lump["quantity_rule"] = "0"
        lump["notes"] = "Replaced by the oil & air system lines of stage 62 (nozzles, manifolds, piping, valves, timer, couplers, tank)"
        out["lump_retired"] = 1
    if any(out.values()):
        mould_db.write(d)
    return out


def counts(die: dict) -> dict:
    """The traced oil / air quantities of a fin die cost result (nodes v:oil_nozzles …)."""
    n = die["nodes"]
    return {k: n[f"v:{k}"]["value"] for k in VARS if f"v:{k}" in n}


def design_rule(name: str) -> float:
    r = mould_db.design_rules(PT).get(name)
    if r is None:
        raise ValueError(f"Mould & die database → Design rules has no {name} for fin (run the stage 62 seed).")
    return float(r["value"])


def checks(des: dict, spm: float, strokes_per_pack: float | None = None, oil_l_per_pack: float | None = None) -> list[dict]:
    c = counts(des["die"])
    out = []
    if not c:
        return out
    air = c["air_nozzles"] * design_rule("fin_air_nl_per_pulse") * spm
    supply = design_rule("fin_air_supply_nl_min")
    out.append({"name": "Air blow use vs air supply", "value": round(air, 1), "limit": f"≤ {supply:g}", "unit": "Nl/min", "ok": air <= supply,
                "formula": "air nozzles × fin_air_nl_per_pulse × SPM", "note": f"{c['air_nozzles']:g} air nozzles at {spm:g} SPM"})
    if strokes_per_pack and oil_l_per_pack:
        mist = c["oil_nozzles"] * design_rule("fin_oil_ml_per_pulse") * strokes_per_pack / 1000
        out.append({"name": "Mist oil per pack vs oil of the part cost", "value": round(mist, 5), "limit": f"≤ {oil_l_per_pack:.4f}", "unit": "L",
                    "ok": mist <= oil_l_per_pack, "formula": "oil nozzles × fin_oil_ml_per_pulse × strokes per pack",
                    "note": f"{c['oil_nozzles']:g} mist nozzles; the rest of the oil is the roll oiler of the press line"})
    return out


def layout(des: dict) -> dict:
    """Where the nozzles, manifolds, valves and couplers sit (die coordinates, mm): for the 3D die, strip layout and schematic."""
    dd, s = des["dims"], des["spec"]
    c = counts(des["die"])
    sts = des["stations"]
    oil_kinds, air_kinds = {"draw", "iron", "pierce", "trim"}, {"pierce", "trim"}
    fy0 = (dd["die_w"] - dd["foil_w"]) / 2
    pitch_o = mould_db.sizing_rules(PT)["fin_oil_nozzle_pitch_mm"]["value"]
    pitch_a = mould_db.sizing_rules(PT)["fin_air_nozzle_pitch_mm"]["value"]
    noz = []
    for st in sts:
        x = st["x0"] + dd["station_len"] / 2
        for kind, kinds, pitch in (("oil", oil_kinds, pitch_o), ("air", air_kinds, pitch_a)):
            if st["kind"] in kinds:
                n = math.ceil(dd["foil_w"] / pitch)
                for i in range(n):
                    noz.append({"kind": kind, "station": st["no"], "x": x + (6 if kind == "air" else -6), "y": fy0 + (i + 0.5) * dd["foil_w"] / n})
    return {"nozzles": noz, "counts": c, "manifold_y": {"oil": -25.0, "air": dd["die_w"] + 25.0},
            "valves": [{"kind": "oil", "x": -60.0}, {"kind": "air", "x": -60.0}], "couplers": [{"kind": "oil"}, {"kind": "air"}]}
