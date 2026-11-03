"""Mould systems (roadmap stage 46): gate, runner and overflow (and later ejection and cooling) of a mould worked out by formulas
that live in master data, then built into the 3D mould design.

    Mould & die database → Mould systems   one row per value, in order: part type, system (gate, overflow, ejection,
                                           cooling), name, formula, unit, meaning, why; kind 'value' or 'check' (a check
                                           row is ok when its formula is true, else its meaning is the warning). A row may use
                                           the facts below, the numeric Design rules and Parameters of the part type, the
                                           material window (Process windows) and the flow material (Flow materials), and every
                                           row before it.
    facts of the design                    part size / volume / surface / weight / wall, cavities and layout, runner length,
                                           mould base plates; see FACTS
    typed value                            any value can be typed per part (Tool design → Mould systems); a typed value wins
                                           over the formula and is shown as "typed by you"

Every value is traced on screen and on the drawings: formula, the inputs with their values, the result and the source. All the
seeded rows and the Design rules they use are EXAMPLE values until you replace them with your toolroom's practice.
"""

from __future__ import annotations

from sqlalchemy import select

from . import formula, master_data, mould_db, register_setup
from . import projects_db as db

EXAMPLE = "EXAMPLE - typical engineering rule: replace with your toolroom's practice"
SYSTEMS = ("gate", "overflow", "ejection", "cooling")
KINDS = ("value", "check")
TYPES = ("plastic", "die_casting", "eps", "blow", "foundry")

FACTS = {
    "part_l": "Part length across the parting plane, with shrinkage (mm)", "part_w": "Part width across the parting plane (mm)",
    "part_h": "Part height along the opening direction (mm)", "part_volume_cm3": "Volume of one part (cm³)",
    "part_surface_cm2": "Surface of one part (cm²)", "projected_area_cm2": "Projected area of one part (cm²)",
    "part_weight_g": "Weight of one part (g)", "wall_mm": "Typical wall of the part (mm, from the 3D model)",
    "part_modulus_mm": "Casting modulus = volume / surface (mm)", "flow_len_mm": "Longest flow path in the part ≈ its diagonal (mm)",
    "cavities": "Cavities of the mould", "layout_rows": "Rows of cavities", "layout_cols": "Columns of cavities",
    "runner_len_mm": "Runner length from the sprue to the farthest gate (mm)", "hot_runner_on": "1 with a hot runner, else 0",
    "density_g_cm3": "Density of the part material (g/cm³)",
    "spacer_block_mm": "Spacer block height of the mould base (mm)", "ejector_plates_mm": "Ejector + retainer plates together (mm)",
    "cope_h_mm": "Foundry: cope flask height = sprue head (mm)", "fill_gun_bom": "EPS: fill guns in the tool BOM",
    "melt_c": "Melt / metal / pour temperature (Process windows, °C)", "mould_c": "Mould / die temperature (°C)",
    "eject_c": "Part temperature at ejection (°C)", "diffusivity_mm2_s": "Thermal diffusivity (Flow materials, mm²/s)",
    "no_flow_c": "No-flow / minimum flow temperature (Flow materials, °C)", "nadca_k_s_mm": "NADCA fill-time factor K (s/mm)",
    "nadca_z_c_pct": "NADCA Z (°C per % solid)", "chvorinov_s_mm2": "Chvorinov B (s/mm²); EPS: cooling s per mm² of wall",
    "cool_circuits": "Cooling circuits of the mould (EPS: the two steam-chamber spray circuits)",
    "circuit_len_mm": "Longest cooling circuit, plate + inserts + bridges (mm)",
}

# new Design rules rows (part type, parameter): value, unit, description - added by seed(), never changed
RULES = [
    ("plastic", "gate_thk_factor", 0.6, "-", "Gate thickness = factor × wall (stage 46; 0.5 - 0.8 is usual)"),
    ("plastic", "gate_thk_min_mm", 0.8, "mm", "Smallest gate thickness (stage 46)"),
    ("plastic", "gate_n_factor", 0.7, "-", "Gate width W = n × √(part surface, mm²) / 30; n by material (PE/PS 0.6, PP/POM/PC 0.7, PA 0.8, PVC 0.9)"),
    ("plastic", "gate_land_mm", 1.0, "mm", "Gate land length (stage 46)"),
    ("plastic", "flow_ratio_max", 150, "-", "Longest flow length / wall that one gate fills; more gates above it (stage 46)"),
    ("plastic", "gates_max", 4, "-", "Most gates per cavity the gate design adds (stage 46)"),
    ("plastic", "gate_freeze_share", 0.3, "-", "Flow simulation: the gate must stay open this share of the part cooling time (packing) (stage 46)"),
    ("die_casting", "dc_solid_pct", 20, "%", "NADCA fill time: share of solid allowed at the end of the fill (stage 46)"),
    ("die_casting", "gate_velocity_m_s", 40, "m/s", "Metal speed through the gate (aluminium 30 - 50, zinc 35 - 50) (stage 46)"),
    ("die_casting", "gate_thk_factor", 0.5, "-", "Gate thickness = factor × wall (stage 46)"),
    ("die_casting", "gate_thk_min_mm", 0.8, "mm", "Smallest gate thickness (stage 46)"),
    ("die_casting", "gate_thk_max_mm", 3.5, "mm", "Largest gate thickness (stage 46)"),
    ("die_casting", "runner_area_factor", 1.2, "-", "Runner section = factor × gate area (the metal speeds up to the gate) (stage 46)"),
    ("die_casting", "overflow_pct", 15, "%", "Overflow volume, % of the part volume (stage 46)"),
    ("die_casting", "overflow_pitch_mm", 40, "mm", "One overflow per this length of the far side of the part (stage 46)"),
    ("eps", "eps_cm3_per_gun", 1500, "cm³", "Part volume one fill gun (injector) fills (stage 46)"),
    ("foundry", "gating_pct", 40, "%", "Gating and riser metal, % of the castings (yield) (stage 46)"),
    ("foundry", "pour_time_k", 2.5, "s/√kg", "Pouring time = k × √(poured kg) (stage 46)"),
    ("foundry", "discharge_c", 0.8, "-", "Discharge coefficient of the sprue (friction losses) (stage 46)"),
    ("foundry", "gating_ratio_runner", 2, "-", "Gating ratio sprue : runner : ingate = 1 : this : ingate ratio (unpressurised) (stage 46)"),
    ("foundry", "gating_ratio_ingate", 2, "-", "Gating ratio, ingate part (stage 46)"),
    ("foundry", "ingate_thk_factor", 0.5, "-", "Ingate thickness = factor × wall (stage 46)"),
    ("foundry", "ingate_thk_min_mm", 4, "mm", "Smallest ingate thickness (stage 46)"),
    ("foundry", "riser_modulus_factor", 1.2, "-", "Riser modulus = factor × casting modulus; riser Ø = 6 × riser modulus (H = Ø) (stage 46)"),
] + [(pt, "eject_extra_mm", 10, "mm", "Ejector stroke beyond the part height, so the part is clear of the core (stage 46)")
     for pt in ("plastic", "die_casting", "eps")] + [(pt, "stop_disc_mm", 5, "mm", "Stop discs under the ejector plate: stroke lost (stage 46)")
                                                    for pt in ("plastic", "die_casting")] + [
    ("eps", "eps_cm2_per_ejector", 150, "cm²", "Projected part area pushed off by one pneumatic ejector (stage 46)"),
    ("eps", "eps_ejector_stroke_mm", 100, "mm", "Stroke of the pneumatic ejectors of the EPS machine / mould (stage 46)"),
]
# cooling water (stage 46): part type → value; the coolant of die casting is thermal oil
_COOL = {
    "cycle_extra_s": ({"plastic": 8, "die_casting": 20, "blow": 6, "eps": 40}, "s", "Cycle = cooling time + this (open, eject, close, spray / fill)"),
    "runner_share_pct": ({"plastic": 10, "die_casting": 50, "blow": 0, "eps": 0}, "%", "Runner / biscuit / overflow metal or plastic cooled too, % of the parts"),
    "melt_cp_kj_kgk": ({"plastic": 2.0, "die_casting": 1.1, "blow": 1.6, "eps": 1.3}, "kJ/kg·K", "Specific heat of the part material (melt to ejection)"),
    "melt_latent_kj_kg": ({"plastic": 60, "die_casting": 390, "blow": 0, "eps": 0}, "kJ/kg", "Latent heat set free on freezing (amorphous plastics 0, PP / PA 100+, aluminium 390)"),
    "water_heat_share": ({"plastic": 0.9, "die_casting": 0.6, "blow": 0.9, "eps": 0.9}, "-", "Share of the heat the coolant takes (rest: air, spray, platens)"),
    "water_below_mould_c": ({"plastic": 5, "die_casting": 20, "blow": 3, "eps": 15}, "°C", "Coolant inlet = mould / die temperature − this"),
    "water_dt_max_c": ({"plastic": 3, "die_casting": 5, "blow": 3, "eps": 5}, "°C", "Largest rise of the coolant from IN to OUT (even mould temperature)"),
    "coolant_cp_kj_kgk": ({"plastic": 4.186, "die_casting": 2.1, "blow": 4.186, "eps": 4.186}, "kJ/kg·K", "Specific heat of the coolant (water 4.186, thermal oil about 2.1)"),
    "coolant_density_kg_l": ({"plastic": 1.0, "die_casting": 0.85, "blow": 1.0, "eps": 1.0}, "kg/L", "Density of the coolant"),
    "coolant_visc_mm2_s": ({"plastic": 0.7, "die_casting": 1.5, "blow": 1.1, "eps": 0.9}, "mm²/s", "Kinematic viscosity of the coolant at its temperature"),
    "reynolds_min": ({"plastic": 10000, "die_casting": 10000, "blow": 10000, "eps": 10000}, "-", "Smallest Reynolds number (turbulent flow takes the heat away)"),
    "fittings_loss_pct": ({"plastic": 50, "die_casting": 50, "blow": 50, "eps": 50}, "%", "Pressure drop of bends, plugs, nipples and hoses on top of the straight channel"),
    "tcu_pressure_bar": ({"plastic": 3, "die_casting": 3, "blow": 3, "eps": 3}, "bar", "Pressure the temperature-control unit / chiller pump gives"),
    "dew_point_c": ({"plastic": 15, "die_casting": 15, "blow": 15, "eps": 15}, "°C", "Dew point of the shop air: colder water makes the mould sweat"),
    "nipple_d_mm": ({"plastic": 13, "die_casting": 13, "blow": 13}, "mm", "Cooling nipple (quick coupling) diameter"),
    "nipple_len_mm": ({"plastic": 35, "die_casting": 35, "blow": 35}, "mm", "Cooling nipple length out of the plate"),
    "plug_len_mm": ({"plastic": 10, "die_casting": 10, "blow": 10}, "mm", "Pressure plug length"),
    "cooling_cross_extra_mm": ({"plastic": 1, "die_casting": 1, "blow": 1}, "mm",
                               "U-turn cross channel drilled this much larger than the cooling channels, so the drills meet cleanly"),
}
RULES += [(pt, k, v, unit, desc + " (stage 46)") for k, (vals, unit, desc) in _COOL.items() for pt, v in vals.items()]
TEXT_RULES = [("plastic", "coolant_medium", "Water, closed circuit with a temperature-control unit"),
              ("die_casting", "coolant_medium", "Thermal oil from the die temperature-control unit"),
              ("blow", "coolant_medium", "Chilled water"), ("eps", "coolant_medium", "Water sprayed in the steam chambers")]

# part type, system, name, formula, unit, meaning (or warning of a check), why, kind
V, C = "value", "check"
GATE_ROWS = [
    ("plastic", "gate", "gates", "1 if hot_runner_on else max(1, min(gates_max, ceil(flow_len_mm / (flow_ratio_max * max(wall_mm, 0.5)))))", "",
     "Gates per cavity", "one gate fills a flow length of flow_ratio_max × wall; a hot runner has one nozzle per cavity", V),
    ("plastic", "gate", "gate_thk", "max(gate_thk_min_mm, gate_thk_factor * wall_mm)", "mm", "Gate thickness",
     "freezes after the part is packed, before the wall", V),
    ("plastic", "gate", "gate_width", "max(gate_thk, gate_n_factor * sqrt(part_surface_cm2 * 100) / 30 / gates)", "mm", "Gate width",
     "W = n × √A / 30 (A = part surface, mm²) shared by the gates", V),
    ("plastic", "gate", "gate_land", "gate_land_mm", "mm", "Gate land", "Design rules", V),
    ("plastic", "gate", "runner_dia", "max(runner_d_mm, gate_thk + 1.5, sqrt(part_weight_g) * runner_len_mm ** 0.25 / 3.7)", "mm",
     "Runner diameter", "D = √W × ⁴√L / 3.7 (W = part g, L = runner mm), at least runner_d_mm and gate + 1.5", V),
    ("plastic", "gate", "chk_one_cavity", "gates <= 1 or cavities > 1 or hot_runner_on", "",
     "One cavity needs more than one gate: a direct sprue gate cannot do it - use a 3-plate (pin-point) or hot-runner mould.", "", C),
    ("plastic", "gate", "chk_gate", "gate_thk <= 0.9 * wall_mm", "",
     "The gate is as thick as the wall: it freezes late (sink and stress at the gate); check the wall or the gate factor.", "", C),
    ("die_casting", "gate", "fill_time", "nadca_k_s_mm * (melt_c - no_flow_c + dc_solid_pct * nadca_z_c_pct) / max(no_flow_c - mould_c, 1) * wall_mm",
     "s", "Cavity fill time", "NADCA: t = K × (Ti − Tf + S × Z) / (Tf − Td) × T", V),
    ("die_casting", "gate", "shot_cm3", "part_volume_cm3 * (1 + overflow_pct / 100)", "cm³", "Metal through the gate per cavity",
     "part + overflows", V),
    ("die_casting", "gate", "gate_area", "shot_cm3 / (fill_time * gate_velocity_m_s)", "mm²", "Gate area",
     "volume / (fill time × gate velocity)", V),
    ("die_casting", "gate", "gate_thk", "max(gate_thk_min_mm, min(gate_thk_factor * wall_mm, gate_thk_max_mm))", "mm", "Gate thickness",
     "share of the wall, between the smallest and largest gate", V),
    ("die_casting", "gate", "gate_width", "gate_area / gate_thk", "mm", "Gate width", "gate area / gate thickness", V),
    ("die_casting", "gate", "runner_dia", "max(runner_d_mm, sqrt(4 * runner_area_factor * gate_area / 3.1416))", "mm", "Runner diameter",
     "runner section = runner_area_factor × gate area", V),
    ("die_casting", "gate", "chk_gate", "gate_width <= 1.5 * part_l", "",
     "The gate is wider than the side of the part: use a fan / tangential gate or two gates.", "", C),
    ("die_casting", "overflow", "overflows", "max(1, ceil(part_w / overflow_pitch_mm))", "", "Overflows per cavity",
     "one per overflow_pitch_mm of the far side (last place to fill)", V),
    ("die_casting", "overflow", "overflow_vol", "overflow_pct / 100 * part_volume_cm3 / overflows", "cm³", "Volume of each overflow",
     "overflow_pct of the part volume shared", V),
    ("die_casting", "overflow", "overflow_len", "max(8, overflow_vol * 1000 / (overflow_w_mm * overflow_h_mm))", "mm", "Overflow length",
     "volume / (overflow_w_mm × overflow_h_mm)", V),
    ("eps", "gate", "fill_guns", "max(1, ceil(part_volume_cm3 / eps_cm3_per_gun))", "", "Fill guns (injectors) per cavity",
     "one per eps_cm3_per_gun of part volume", V),
    ("eps", "gate", "chk_guns", "fill_guns * cavities <= fill_gun_bom", "",
     "The tool BOM has fewer fill guns than the gate design places: correct the Fill gun line of the tool BOM.", "", C),
    ("foundry", "gate", "poured_kg", "part_weight_g / 1000 * cavities * (1 + gating_pct / 100)", "kg", "Metal poured per mould",
     "castings + gating and risers", V),
    ("foundry", "gate", "pour_time", "pour_time_k * sqrt(poured_kg)", "s", "Pouring time", "k × √(poured kg)", V),
    ("foundry", "gate", "choke_area", "poured_kg / (density_g_cm3 * 0.000001 * pour_time * discharge_c * sqrt(2 * 9810 * cope_h_mm))", "mm²",
     "Choke (sprue base) area", "Bernoulli: A = W / (ρ × t × c × √(2 g H))", V),
    ("foundry", "gate", "sprue_dia", "sqrt(4 * choke_area / 3.1416)", "mm", "Sprue diameter at the base", "from the choke area", V),
    ("foundry", "gate", "runner_side", "sqrt(choke_area * gating_ratio_runner / cavities)", "mm", "Runner bar (square) side",
     "gating ratio, per casting", V),
    ("foundry", "gate", "ingate_thk", "max(ingate_thk_min_mm, ingate_thk_factor * wall_mm)", "mm", "Ingate thickness", "share of the wall", V),
    ("foundry", "gate", "ingate_width", "choke_area * gating_ratio_ingate / cavities / ingate_thk", "mm", "Ingate width",
     "gating ratio, per casting", V),
    ("foundry", "gate", "riser_dia", "6 * riser_modulus_factor * part_modulus_mm", "mm", "Riser diameter (height = diameter)",
     "modulus method: riser modulus = factor × casting modulus", V),
]
EJECT_ROWS = [r for pt in ("plastic", "die_casting") for r in (
    (pt, "ejection", "eject_stroke", "part_h + eject_extra_mm", "mm", "Ejector stroke needed",
     "the part is pushed fully off the core: part height + eject_extra_mm", V),
    (pt, "ejection", "base_stroke", "spacer_block_mm - ejector_plates_mm - stop_disc_mm", "mm", "Ejector stroke of the catalogue mould base",
     "spacer block − ejector plates − stop discs", V),
    (pt, "ejection", "spacer_used", "max(spacer_block_mm, eject_stroke + ejector_plates_mm + stop_disc_mm)", "mm", "Spacer block height used",
     "raised above the catalogue size when the stroke is short (the mould gets higher)", V),
    (pt, "ejection", "opening_stroke", "rec_stroke_factor * part_h + rec_stroke_extra_mm", "mm", "Mould opening stroke needed",
     "the part is taken out between the halves (Design rules rec_stroke_*)", V),
    (pt, "ejection", "chk_stroke", "eject_stroke <= spacer_used - ejector_plates_mm - stop_disc_mm", "",
     "The ejector stroke ({eject_stroke:.0f} mm) is shorter than the part needs: it cannot come off the core. Raise the spacer blocks.", "", C),
    (pt, "ejection", "chk_base", "base_stroke >= eject_stroke", "",
     "The catalogue mould base gives {base_stroke:.0f} mm of ejector stroke; the part needs {eject_stroke:.0f} mm: spacer blocks raised from "
     "{spacer_block_mm:.0f} to {spacer_used:.0f} mm (special spacer blocks, the mould gets higher).", "", C))] + [
    ("eps", "ejection", "eps_ejectors", "max(2, ceil(projected_area_cm2 / eps_cm2_per_ejector))", "", "Pneumatic ejectors per cavity",
     "one per eps_cm2_per_ejector of projected area, at least 2; air ejection through the steam vents helps", V),
    ("eps", "ejection", "eject_stroke", "part_h + eject_extra_mm", "mm", "Ejector stroke needed", "part height + eject_extra_mm", V),
    ("eps", "ejection", "opening_stroke", "rec_stroke_factor * part_h + rec_stroke_extra_mm", "mm", "Mould opening stroke needed",
     "Design rules rec_stroke_*", V),
    ("eps", "ejection", "chk_stroke", "eject_stroke <= eps_ejector_stroke_mm", "",
     "The pneumatic ejectors ({eps_ejector_stroke_mm:.0f} mm) are shorter than the part needs ({eject_stroke:.0f} mm): longer-stroke ejectors.", "", C),
    ("blow", "ejection", "opening_stroke", "rec_stroke_factor * part_h + rec_stroke_extra_mm", "mm", "Mould opening stroke needed",
     "the bottle is taken out between the halves (no ejector pins)", V),
]
_COOL_TIME = {
    "plastic": ("wall_mm ** 2 / (3.1416 ** 2 * diffusivity_mm2_s) * log(4 / 3.1416 * (melt_c - mould_c) / max(eject_c - mould_c, 1))",
                "t = s² / (π² α) × ln(4/π × (Tm − Tw) / (Te − Tw)): the wall cooled to the ejection temperature"),
    "blow": ("wall_mm ** 2 / (3.1416 ** 2 * diffusivity_mm2_s) * log(4 / 3.1416 * (melt_c - mould_c) / max(eject_c - mould_c, 1))",
             "t = s² / (π² α) × ln(4/π × (Tpreform − Tw) / (Te − Tw))"),
    "die_casting": ("chvorinov_s_mm2 * (wall_mm / 2) ** 2", "Chvorinov: t = B × M², modulus of a wall M = wall / 2"),
    "eps": ("chvorinov_s_mm2 * wall_mm ** 2", "EPS: cooling s per mm² of wall (Flow materials)"),
}
COOL_ROWS = [r for pt in ("plastic", "die_casting", "blow", "eps") for r in (
    (pt, "cooling", "cool_time", _COOL_TIME[pt][0], "s", "Cooling time", _COOL_TIME[pt][1], V),
    (pt, "cooling", "cycle", "cool_time + cycle_extra_s", "s", "Cycle (for the heat load)", "cooling time + cycle_extra_s", V),
    (pt, "cooling", "heat_kj", "part_weight_g / 1000 * cavities * (1 + runner_share_pct / 100) * (melt_cp_kj_kgk * max(melt_c - eject_c, 0) + melt_latent_kj_kg)",
     "kJ", "Heat per shot", "mass × (cp × (melt − ejection temperature) + latent heat)", V),
    (pt, "cooling", "heat_kw", "heat_kj / cycle * water_heat_share", "kW", "Heat the coolant takes", "heat per shot / cycle × coolant share", V),
    (pt, "cooling", "water_in", "mould_c - water_below_mould_c", "°C", "Coolant inlet temperature to keep",
     "mould / die temperature of the material window − water_below_mould_c", V),
    (pt, "cooling", "flow_total", "heat_kw / (coolant_cp_kj_kgk * coolant_density_kg_l * water_dt_max_c) * 60", "L/min", "Coolant flow for the heat (whole mould)",
     "Q = P / (cp × ρ × ΔT)", V),
    (pt, "cooling", "flow_heat", "flow_total / max(cool_circuits, 1)", "L/min", "Flow per circuit for the heat", "shared by the circuits", V),
    (pt, "cooling", "flow_turb", "reynolds_min * coolant_visc_mm2_s * 3.1416 * cooling_d_mm / 4 * 0.00006", "L/min",
     "Flow per circuit for turbulent flow", "Q = Re × ν × π × d / 4", V),
    (pt, "cooling", "flow_set", "max(flow_heat, flow_turb)", "L/min", "Coolant flow to set per circuit", "the larger of heat and turbulence", V),
    (pt, "cooling", "velocity", "flow_set / 60000 / (3.1416 * (cooling_d_mm / 1000) ** 2 / 4)", "m/s", "Coolant speed in the channel", "Q / channel section", V),
    (pt, "cooling", "reynolds", "velocity * cooling_d_mm / 1000 / (coolant_visc_mm2_s * 0.000001)", "", "Reynolds number", "v × d / ν", V),
    (pt, "cooling", "water_out", "water_in + heat_kw / max(cool_circuits, 1) / (coolant_cp_kj_kgk * coolant_density_kg_l * flow_set / 60)", "°C",
     "Coolant outlet temperature", "inlet + heat per circuit / (cp × ρ × Q)", V),
    (pt, "cooling", "pressure_drop", "0.316 * max(reynolds, 1) ** -0.25 * circuit_len_mm / cooling_d_mm * coolant_density_kg_l * 1000 * velocity ** 2 / 2 / 100000 * (1 + fittings_loss_pct / 100)",
     "bar", "Pressure drop of the longest circuit", "Blasius friction × length / d × ρv²/2, + fittings", V),
    (pt, "cooling", "chk_circuits", "cool_circuits >= 1", "",
     "No cooling circuit could be placed clear of the part: baffles, bubblers or conformal cooling by the designer.", "", C),
    (pt, "cooling", "chk_dew", "water_in >= dew_point_c", "",
     "Coolant inlet {water_in:.0f} °C is below the dew point ({dew_point_c:.0f} °C): the mould sweats; dry the air or use warmer water.", "", C),
    (pt, "cooling", "chk_pressure", "pressure_drop <= tcu_pressure_bar", "",
     "Pressure drop {pressure_drop:.1f} bar is above the pump ({tcu_pressure_bar:.0f} bar): split the circuit or use a bigger channel.", "", C))]
SEED_ROWS = GATE_ROWS + EJECT_ROWS + COOL_ROWS


def seed() -> dict:
    """Add the Design rules and Mould systems rows that are missing (existing rows are never changed)."""
    d = mould_db.tables()
    out = {"rules": 0, "rows": 0}
    have = {(r["part_type"], r["parameter"]) for r in d["design_rules"]}
    for pt, k, v, u, desc in RULES:
        if (pt, k) not in have:
            d["design_rules"].append({"part_type": pt, "parameter": k, "value": v, "text": "", "unit": u, "description": desc, "is_example": True})
            out["rules"] += 1
    for pt, k, text in TEXT_RULES:
        if (pt, k) not in have:
            d["design_rules"].append({"part_type": pt, "parameter": k, "value": None, "text": text, "unit": "", "is_example": True,
                                      "description": "Coolant of the mould (stage 46)"})
            out["rules"] += 1
    have = {(r["part_type"], r["name"]) for r in d["mould_systems"]}
    step = {}
    for pt, system, name, f, unit, label, why, kind in SEED_ROWS:
        step[pt] = step.get(pt, 0) + 1
        if (pt, name) not in have:
            d["mould_systems"].append({"part_type": pt, "step": step[pt] * 10, "system": system, "name": name, "formula": f, "unit": unit,
                                       "label": label, "why": why, "kind": kind, "is_example": True, "notes": EXAMPLE})
            out["rows"] += 1
    if any(out.values()):
        mould_db.write(d)
    return out


def rows_for(part_type: str) -> list[dict]:
    return sorted((r for r in mould_db.tables()["mould_systems"] if r["part_type"] == part_type), key=lambda r: (r["step"], r["name"]))


def _rules_env(part_type: str, tables: dict | None = None) -> dict:
    """Numeric Parameters, Design rules and Sizing rules of the part type (tables = the rows being saved, else the stored ones)."""
    env = {k: float(v) for k, v in master_data.parameters(part_type).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if tables and "design_rules" in tables:
        design = {r["parameter"]: r for r in tables["design_rules"] if r["part_type"] == part_type}
    else:
        design = mould_db.design_rules(part_type)
    if tables and "sizing_rules" in tables:
        sizing = {r["parameter"]: r for r in tables["sizing_rules"] if r["part_type"] == part_type}
    else:
        sizing = mould_db.sizing_rules(part_type)
    env |= {k: float(r["value"]) for k, r in design.items() if r.get("value") not in (None, "")}
    env |= {k: float(r["value"]) for k, r in sizing.items() if r.get("value") not in (None, "") and k not in env}
    return env


def validate(clean: dict) -> None:
    """Check the Mould systems rows of an import / save: names, kinds, systems and that every formula works on sample facts."""
    rows = clean.get("mould_systems", [])
    for pt in {r["part_type"] for r in rows}:
        env = {k: 1.0 for k in FACTS} | {"cavities": 2.0, "wall_mm": 2.0, "mould_c": 40.0, "melt_c": 230.0, "eject_c": 90.0,
                                          "no_flow_c": 120.0} | _rules_env(pt, clean)
        for r in sorted((x for x in rows if x["part_type"] == pt), key=lambda x: (x["step"], x["name"])):
            if not str(r["name"]).isidentifier():
                raise mould_db.MouldDbError(f"Mould systems '{r['name']}' must be one word (letters, digits and _).")
            if r["kind"] not in KINDS:
                raise mould_db.MouldDbError(f"Mould systems ({r['name']}): kind must be value or check.")
            if r["system"] not in SYSTEMS:
                raise mould_db.MouldDbError(f"Mould systems ({r['name']}): system must be one of {', '.join(SYSTEMS)}.")
            try:
                env[r["name"]] = float(formula.evaluate(r["formula"], env))
            except formula.FormulaError as exc:
                raise mould_db.MouldDbError(f"Mould systems ({pt}, {r['name']}): {exc}") from None
            except (ArithmeticError, ValueError):
                env[r["name"]] = 1.0


# ---------- typed values per part ----------

def typed(part_id: int) -> dict:
    with db.engine().connect() as conn:
        return dict(conn.execute(select(db.parts.c.mould_typed).where(db.parts.c.id == part_id)).scalar() or {})


def save_typed(part_id: int, values: dict) -> dict:
    """values: {name: number | "" / None (= back to the formula)}; names must be value rows of the part's type."""
    from . import auth, register
    d = register.part_detail(part_id, with_rm=False)
    pt = (register_setup.processes().get(d["process"]) or {}).get("part_type")
    if pt not in TYPES:
        raise register.RegisterError("Mould systems are worked out for moulds and pattern equipment.")
    names = {r["name"]: r for r in rows_for(pt) if r["kind"] == "value"}
    cur = typed(part_id)
    for k, v in (values or {}).items():
        if k not in names:
            raise register.RegisterError(f"'{k}' is not a value of Mould & die database → Mould systems for {pt.replace('_', ' ')}.")
        if v in (None, ""):
            cur.pop(k, None)
            continue
        try:
            n = float(v)
        except (TypeError, ValueError):
            raise register.RegisterError(f"{names[k]['label']}: '{v}' is not a number.") from None
        if n < 0:
            raise register.RegisterError(f"{names[k]['label']} cannot be below 0.")
        cur[k] = n
    with db.engine().begin() as conn:
        conn.execute(db.parts.update().where(db.parts.c.id == part_id).values(mould_typed=cur or None))
        auth.log(conn, "part", part_id, "mould_systems_typed", cur)
    return cur


# ---------- work it out ----------

def design_facts(part: dict, shape, cells: list, rows: int, cols: int, val, base: dict, lines: list) -> dict:
    """The facts of a mould design the Mould systems formulas use (shape = the part as moulded: oriented, with shrinkage)."""
    import math
    bb = shape.BoundingBox()
    vol, area = shape.Volume(), shape.Area()
    reach = max((math.hypot(cx, cy) for cx, cy in cells), default=0.0)
    fill = next((x for x in lines if str(x.get("element", "")).lower().startswith("fill gun")), {}) if lines else {}
    weight = val("v:part_weight_g", 0.0)
    return {"part_l": bb.xlen, "part_w": bb.ylen, "part_h": bb.zlen, "part_volume_cm3": vol / 1000, "part_surface_cm2": area / 100,
            "projected_area_cm2": val("v:projected_area_cm2", bb.xlen * bb.ylen / 100), "part_weight_g": weight,
            "wall_mm": float(part.get("wall_mm") or 0) or 2.0, "part_modulus_mm": vol / max(area, 1e-6),
            "flow_len_mm": math.hypot(bb.xlen, bb.ylen), "cavities": float(len(cells)), "layout_rows": float(rows), "layout_cols": float(cols),
            "runner_len_mm": (reach + max(bb.xlen, bb.ylen) / 2) if len(cells) > 1 else 0.0,
            "hot_runner_on": 1.0 if val("v:hot_runner", 0) > 0 else 0.0,
            "density_g_cm3": float(part.get("density_g_cm3") or 0) or (weight / max(vol / 1000, 1e-6) if weight else 1.0),
            "spacer_block_mm": float(base.get("spacer_block_mm") or 0), "ejector_plates_mm": float(base.get("ejector_plates_mm") or 0),
            "fill_gun_bom": float(fill.get("quantity") or 0)}


def material_env(material: str) -> dict:
    """Material window (Process windows) and flow material (Flow materials) numbers of the part material."""
    from . import flow_sim, process_params
    env = {}
    fm = flow_sim.material(material) or {}
    for k in ("diffusivity_mm2_s", "no_flow_c", "nadca_k_s_mm", "nadca_z_c_pct", "chvorinov_s_mm2"):
        if fm.get(k) not in (None, ""):
            env[k] = float(fm[k])
    env |= process_params.window(material)
    return env


def compute(part_type: str, facts: dict, material: str = "", typed_values: dict | None = None) -> dict:
    """{rows, checks, values, is_example}: every Mould systems row of the part type in order, a typed value winning."""
    typed_values = typed_values or {}
    env = _rules_env(part_type) | material_env(material) | {k: float(v) for k, v in facts.items() if v is not None}
    base = dict(env)
    rows, checks = [], []
    for r in rows_for(part_type):
        used = sorted(n for n in formula.names(r["formula"]) if n in env)
        inputs = {n: round(env[n], 4) for n in used}
        if r["kind"] == "value" and r["name"] in typed_values:
            v, src = float(typed_values[r["name"]]), "typed by you"
        else:
            try:
                v = float(formula.evaluate(r["formula"], env))
            except (formula.FormulaError, ArithmeticError, ValueError) as exc:
                missing = sorted(n for n in formula.names(r["formula"]) if n not in env)
                why = f"needs {', '.join(missing)} (no data for this part / material)" if missing else str(exc)
                if r["kind"] == "check":
                    checks.append({"system": r["system"], "name": r["name"], "ok": None, "message": f"{r['label']} - not checked: {why}",
                                   "formula": r["formula"], "inputs": inputs, "is_example": bool(r["is_example"])})
                else:
                    rows.append({"system": r["system"], "name": r["name"], "label": r["label"], "value": None, "unit": r["unit"],
                                 "formula": r["formula"], "why": r["why"], "inputs": inputs, "source": f"not worked out: {why}",
                                 "is_example": bool(r["is_example"])})
                continue
            src = "formula (Mould & die database → Mould systems)"
        if r["kind"] == "check":
            msg = ""
            if not v:
                try:
                    msg = r["label"].format(**env)
                except (KeyError, ValueError, IndexError, AttributeError):
                    msg = r["label"]
            checks.append({"system": r["system"], "name": r["name"], "ok": bool(v), "message": msg,
                           "formula": r["formula"], "inputs": inputs, "is_example": bool(r["is_example"])})
            continue
        env[r["name"]] = v
        rows.append({"system": r["system"], "name": r["name"], "label": r["label"], "value": round(v, 6), "unit": r["unit"],
                     "formula": r["formula"], "why": r["why"], "inputs": inputs, "source": src, "is_example": bool(r["is_example"])})
    values = {x["name"]: x["value"] for x in rows if x["value"] is not None}
    medium = (mould_db.design_rules(part_type).get("coolant_medium") or {}).get("text") or ""
    return {"part_type": part_type, "rows": rows, "checks": checks, "values": values, "coolant": medium, "facts": {k: round(float(v), 4) for k, v in facts.items() if v is not None},
            "is_example": any(x["is_example"] for x in rows + checks), "material_known": bool(set(base) & {"melt_c", "diffusivity_mm2_s", "no_flow_c"})}


def value(systems: dict | None, name: str, default=None):
    v = ((systems or {}).get("values") or {}).get(name)
    return default if v is None else float(v)


def _num(v: float) -> str:
    """A value for a note: whole above 100, one decimal above 10, else two decimals."""
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.1f}" if abs(v) >= 10 else f"{v:.2f}"


NOTE_COOLING = ("water_in", "flow_set", "water_out", "heat_kw", "pressure_drop", "reynolds")


def notes(systems: dict | None) -> list[str]:
    """Short lines for the drawing notes: the gate / overflow values and the open checks."""
    if not systems:
        return []
    out = []
    for sysname in SYSTEMS:
        rows = [r for r in systems["rows"] if r["system"] == sysname and r["value"] is not None
                and (sysname != "cooling" or r["name"] in NOTE_COOLING)]
        if rows:
            head = sysname.capitalize() + (f" with {systems['coolant'].lower()}" if sysname == "cooling" and systems.get("coolant") else "")
            out.append(f"{head} (Mould systems{', EXAMPLE rules' if any(r['is_example'] for r in rows) else ''}): "
                       + ", ".join(f"{r['label'].lower()} {_num(r['value'])}{(' ' + r['unit']) if r['unit'] else ''}"
                                   + (" (typed)" if r["source"] == "typed by you" else "") for r in rows))
    out += [f"Check: {c['message']}" for c in systems["checks"] if c["ok"] is False]
    return out
