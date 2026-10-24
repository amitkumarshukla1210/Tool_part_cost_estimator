"""Process parameters for the best part quality (roadmap stage 27), worked out from the simulation result and the material.

    window   Master data → Process windows: melt / pour / preform temperature, mould or die temperature and drying of each material, with the range
    rules    Master data → Process parameters: one row per setting (formula, range, unit, why). The formulas use the simulation result of the part
             (fill and cooling time, flow ratio, injection pressure, clamp force …), the quality maps (thin, thick / sink-risk, low-draft areas),
             the material window and, for sheet metal, the stage forces, draw ratio and springback. `risk` rows (result above 0) become quality
             warnings with the remedy.
Nothing is written in the code but the plumbing: all numbers are EXAMPLE rows until you replace them with your own moulding / casting experience.
"""

from __future__ import annotations

import re

from . import formula, master_data, mould_db, register, register_setup

EXAMPLE = "EXAMPLE - typical value: replace with your own data sheet or shop experience"
WINDOW_FIELDS = ("melt_c", "melt_min_c", "melt_max_c", "mould_c", "mould_min_c", "mould_max_c", "eject_c", "dry_c", "dry_h")
KINDS = ("parameter", "risk")

# material, melt, min, max, mould, min, max, eject, dry °C, dry h
SEED_WINDOWS = [
    ("PP (polypropylene)", 230, 200, 260, 40, 20, 60, 90, 0, 0), ("ABS", 235, 210, 260, 60, 40, 80, 90, 80, 3), ("PC (polycarbonate)", 295, 270, 320, 90, 80, 110, 120, 120, 4),
    ("PC/ABS", 260, 240, 280, 70, 60, 90, 100, 100, 3), ("PA6", 260, 240, 290, 80, 60, 95, 120, 80, 4), ("PA66 GF30", 290, 275, 305, 85, 70, 100, 150, 80, 4),
    ("PBT GF30", 260, 245, 275, 80, 60, 100, 140, 120, 3), ("POM (acetal)", 205, 190, 230, 90, 80, 110, 140, 0, 0), ("PET preform grade", 280, 270, 295, 10, 5, 15, 70, 160, 4),
    ("Aluminium ADC12 / A383", 670, 650, 690, 220, 180, 260, 400, 0, 0), ("Aluminium A380", 670, 650, 690, 220, 180, 260, 400, 0, 0), ("Zinc Zamak 3", 420, 400, 440, 180, 150, 220, 250, 0, 0),
    ("Magnesium AZ91D", 650, 630, 670, 220, 180, 260, 350, 0, 0),
    ("Grey cast iron FG260", 1380, 1340, 1420, 20, 10, 40, 0, 0, 0), ("SG / ductile iron", 1400, 1360, 1440, 20, 10, 40, 0, 0, 0), ("Cast steel", 1580, 1540, 1620, 20, 10, 40, 0, 0, 0),
    ("Aluminium LM6 / A356", 720, 690, 750, 20, 10, 40, 0, 0, 0), ("Bronze", 1150, 1100, 1200, 20, 10, 40, 0, 0, 0),
    ("EPS bead grade S (20 kg/m3)", 115, 108, 125, 40, 30, 50, 0, 0, 0), ("EPS bead grade F, flame retardant (25 kg/m3)", 115, 108, 125, 40, 30, 50, 0, 0, 0),
    ("PET bottle grade (IV 0.80)", 105, 95, 115, 12, 8, 15, 60, 160, 4), ("rPET food grade", 105, 95, 115, 12, 8, 15, 60, 160, 4),
]
# part type, name, formula, min, max, unit, label, why, kind
P = "parameter"
SEED_RULES = [
    ("plastic", "thin_share", "thin_cm2 / max(surface_cm2, 1)", "", "", "", "Share of the surface that is thin (short-shot risk)", "from the wall-thickness map of the simulation", P),
    ("plastic", "sink_share", "sink_risk_cm2 / max(surface_cm2, 1)", "", "", "", "Share of the surface that is thick (sink-mark risk)", "from the wall-thickness map of the simulation", P),
    ("plastic", "melt_temp_c", "min(melt_max_c, max(melt_min_c, melt_c + 10 * (flow_ratio > 120) + 10 * (thin_share > 0.02) - 10 * (sink_share > 0.02) * (thin_share <= 0.02)))",
     "melt_min_c", "melt_max_c", "°C", "Melt temperature", "long flow path or thin walls: hotter melt fills; thick sections: cooler melt shrinks less", P),
    ("plastic", "mould_temp_c", "min(mould_max_c, max(mould_min_c, mould_c + 10 * (flow_ratio > 120) + 5 * (thin_share > 0.02) - 5 * (sink_share > 0.02)))",
     "mould_min_c", "mould_max_c", "°C", "Mould temperature", "warmer mould keeps thin, long flow open; cooler mould freezes thick sections sooner", P),
    ("plastic", "fill_time_s", "fill_s", "fill_s * 0.7", "fill_s * 1.3", "s", "Injection (fill) time", "fill time of the simulation for the shot weight", P),
    ("plastic", "shot_volume_cm3", "shot_weight_g / max(density_g_cm3, 0.1)", "", "", "cm³", "Shot volume of the parts", "shot weight / material density", P),
    ("plastic", "dosing_volume_cm3", "shot_volume_cm3 * (1 + runner_pct / 100)", "", "", "cm³", "Dosing volume with runner", "shot volume + runner share (Parameters → runner_pct)", P),
    ("plastic", "injection_rate_cm3_s", "shot_volume_cm3 / fill_s", "shot_volume_cm3 / fill_s * 0.7", "shot_volume_cm3 / fill_s * 1.3", "cm³/s", "Injection rate", "shot volume / fill time", P),
    ("plastic", "injection_pressure_bar", "injection_bar", "injection_bar * 0.8", "injection_bar * 1.2", "bar", "Injection pressure limit", "flow ratio of the simulation (flow length / wall)", P),
    ("plastic", "hold_pressure_bar", "injection_bar * (0.55 + min(0.2, 5 * sink_share))", "injection_bar * 0.4", "injection_bar * 0.85", "bar", "Hold (pack) pressure",
     "more packing where thick sections can sink", P),
    ("plastic", "hold_time_s", "cooling_s * (0.45 + min(0.25, 5 * sink_share))", "cooling_s * 0.3", "cooling_s * 0.8", "s", "Hold (pack) time", "until the gate freezes: longer for thick sections", P),
    ("plastic", "cooling_time_s", "cooling_s", "cooling_s * 0.9", "cooling_s * 1.3", "s", "Cooling time", "thickest wall cooled to the ejection temperature", P),
    ("plastic", "back_pressure_bar", "6", "3", "12", "bar", "Back pressure", "even melt without degrading the material", P),
    ("plastic", "clamp_force_t", "clamp_t", "clamp_t", "clamp_t * 1.3", "t", "Clamp force", "projected area × cavities × cavity pressure with the safety factor", P),
    ("plastic", "ejection_temp_c", "eject_c", "", "", "°C", "Part temperature at ejection", "rigid enough to eject without deforming", P),
    ("plastic", "drying_temp_c", "dry_c", "", "", "°C", "Drying temperature (0 = no drying)", "material window", P),
    ("plastic", "drying_time_h", "dry_h", "", "", "h", "Drying time", "material window", P),
    ("plastic", "cycle_time_s", "cycle_s", "", "", "s", "Cycle time", "fill + cooling + open / eject (+ insert loading)", P),
    ("plastic", "risk_sink", "sink_share > 0.02", "", "", "", "Sink marks likely on {sink_risk_cm2:.1f} cm²: core out the thick sections, raise hold pressure and time, cool the mould there.", "", "risk"),
    ("plastic", "risk_short", "thin_share > 0.02", "", "", "", "Short shot likely on {thin_cm2:.1f} cm² of thin wall: faster injection, hotter melt and mould, wider gate.", "", "risk"),
    ("plastic", "risk_flow", "flow_ratio > 250", "", "", "", "Flow ratio {flow_ratio:.0f} is very long: add a second gate or thicken the wall.", "", "risk"),
    ("plastic", "risk_draft", "draft_low_cm2 > 0", "", "", "", "{draft_low_cm2:.1f} cm² of wall has too little draft: scuffing and high ejection force, add draft.", "", "risk"),
    ("plastic", "risk_undercut", "undercut_cm2 > 0", "", "", "", "Undercuts ({undercut_cm2:.1f} cm²) need slides or lifters: watch for flash and witness lines.", "", "risk"),
    ("die_casting", "thin_share", "thin_cm2 / max(surface_cm2, 1)", "", "", "", "Share of the surface that is thin", "from the wall-thickness map", P),
    ("die_casting", "sink_share", "sink_risk_cm2 / max(surface_cm2, 1)", "", "", "", "Share of the surface that is thick (porosity risk)", "from the wall-thickness map", P),
    ("die_casting", "metal_temp_c", "min(melt_max_c, max(melt_min_c, melt_c + 10 * (thin_share > 0.02) - 10 * (sink_share > 0.02) * (thin_share <= 0.02)))", "melt_min_c", "melt_max_c", "°C",
     "Metal (holding furnace) temperature", "thin walls need hotter metal; thick sections shrink less when cooler", P),
    ("die_casting", "die_temp_c", "min(mould_max_c, max(mould_min_c, mould_c + 10 * (thin_share > 0.02) - 10 * (sink_share > 0.02)))", "mould_min_c", "mould_max_c", "°C", "Die temperature", "balance of fill and solidification", P),
    ("die_casting", "fast_shot_speed_m_s", "min(6, max(1.5, 4.5 - 0.7 * max_wall_mm))", "1.5", "6", "m/s", "Fast-shot plunger speed", "thinner walls need a faster fill", P),
    ("die_casting", "slow_shot_speed_m_s", "0.3", "0.2", "0.5", "m/s", "Slow-shot plunger speed", "pushes the metal to the gate without trapping air", P),
    ("die_casting", "fill_time_s", "fill_s", "fill_s * 0.7", "fill_s * 1.3", "s", "Cavity fill time", "simulation", P),
    ("die_casting", "intensification_pressure_bar", "cavity_pressure_bar * 1.0", "cavity_pressure_bar * 0.8", "cavity_pressure_bar * 1.25", "bar", "Intensification (squeeze) pressure", "cavity pressure of the part type (Parameters)", P),
    ("die_casting", "dwell_time_s", "solidify_s", "solidify_s * 0.8", "solidify_s * 1.3", "s", "Dwell (solidification) time", "thickest wall solidified before opening", P),
    ("die_casting", "spray_time_s", "spray_s", "", "", "s", "Die spray time", "die lubricant and cooling", P),
    ("die_casting", "clamp_force_t", "clamp_t", "clamp_t", "clamp_t * 1.3", "t", "Clamp force", "projected area with overflow × cavity pressure", P),
    ("die_casting", "cycle_time_s", "cycle_s", "", "", "s", "Cycle time", "ladle + fill + solidify + spray + open / eject", P),
    ("die_casting", "risk_porosity", "sink_share > 0.02", "", "", "", "Porosity likely in {sink_risk_cm2:.1f} cm² of thick section: core it out, raise intensification pressure, cool the die there.", "", "risk"),
    ("die_casting", "risk_cold_shut", "thin_share > 0.02", "", "", "", "Cold shuts / misruns likely on {thin_cm2:.1f} cm² of thin wall: faster shot, hotter die, better venting.", "", "risk"),
    ("die_casting", "risk_draft", "draft_low_cm2 > 0", "", "", "", "{draft_low_cm2:.1f} cm² of wall has too little draft: soldering and drag marks, add draft.", "", "risk"),
    ("sheet_metal", "press_tonnage_t", "force_t * press_safety_factor * (1 if progressive == 0 else 1)", "force_t * press_safety_factor", "force_t * press_safety_factor * 1.25", "t", "Press tonnage to set / needed",
     "biggest stage force (total of all stations for a progressive die) with the press safety factor", P),
    ("sheet_metal", "blank_holder_force_t", "0.3 * force_t if draw_depth > 0 else 0", "0.2 * force_t if draw_depth > 0 else 0", "0.4 * force_t if draw_depth > 0 else 0", "t", "Blank-holder (cushion) force",
     "about 30 % of the draw force: wrinkles below, tears above", P),
    ("sheet_metal", "strokes_per_min", "spm_progressive if progressive > 0 else spm_stage", "spm_progressive * 0.5 if progressive > 0 else spm_stage * 0.5", "spm_progressive * 1.2 if progressive > 0 else spm_stage * 1.2", "1/min",
     "Press speed", "from the line speeds in Parameters; slower for deep draws", P),
    ("sheet_metal", "die_clearance_mm", "clearance_mm", "clearance_mm * 0.8", "clearance_mm * 1.2", "mm/side", "Die clearance per side", "die-set rule: percent of thickness by shear strength", P),
    ("sheet_metal", "springback_comp_deg", "springback_deg", "springback_deg * 0.8", "springback_deg * 1.2", "°", "Overbend to compensate springback", "from the sheet-material rules", P),
    ("sheet_metal", "draw_speed_mm_s", "min(400, max(100, 600 / (1 + draw_ratio)))", "100", "400", "mm/s", "Draw speed at the punch", "deeper draws and higher draw ratios need slower speed", P),
    ("sheet_metal", "risk_draw", "draw_ratio > ldr", "", "", "", "Draw ratio {draw_ratio:.2f} is above the limit {ldr:.2f} of the material: use more draw stages or anneal.", "", "risk"),
    ("sheet_metal", "risk_springback", "springback_deg > max_springback_deg", "", "", "", "Springback {springback_deg:.1f}° is above the allowed {max_springback_deg:.1f}°: overbend or restrike.", "", "risk"),
    ("sheet_metal", "risk_force", "force_t * press_safety_factor > 0 and progressive_ok < 1 and progressive > 0", "", "", "", "A progressive die is not recommended for this part by the sheet rules: check the strip layout and feed.", "", "risk"),
    ("foundry", "pour_temp_c", "melt_c", "melt_min_c", "melt_max_c", "°C", "Pouring temperature", "material window (thin sections: upper half)", P),
    ("foundry", "poured_weight_kg", "poured_weight_kg", "", "", "kg", "Metal poured per mould", "casting plus gating and riser (Tool detail rules → poured_weight_kg)", P),
    ("foundry", "pour_time_s", "ceil(2.5 * sqrt(poured_weight_kg) * 10) / 10", "2 * sqrt(poured_weight_kg)", "3.5 * sqrt(poured_weight_kg)", "s", "Pouring time", "weight rule: fast enough to avoid cold laps, slow enough to avoid erosion", P),
    ("foundry", "solidification_min", "3 * (part_modulus_mm / 10) ** 2", "", "", "min", "Solidification time (Chvorinov)", "modulus (volume / surface) squared × mould constant", P),
    ("foundry", "shakeout_min", "ceil(1.5 * 3 * (part_modulus_mm / 10) ** 2)", "", "", "min", "Earliest shake-out after pouring", "casting solid and below the critical temperature", P),
    ("foundry", "mould_temp_c", "mould_c", "mould_min_c", "mould_max_c", "°C", "Sand / mould temperature", "material window", P),
    ("foundry", "risk_shrink", "part_modulus_mm > 8", "", "", "", "Heavy section (modulus {part_modulus_mm:.1f} mm): riser and chills are needed against shrinkage porosity.", "", "risk"),
    ("eps", "steam_pressure_bar", "min(1.3, max(0.7, 0.9 + 0.01 * (wall_mm - 20)))", "0.7", "1.3", "bar", "Steam pressure in the chest", "thicker walls need a little more steam to fuse the beads", P),
    ("eps", "steam_time_s", "8 + 0.5 * wall_mm", "6 + 0.4 * wall_mm", "10 + 0.6 * wall_mm", "s", "Steaming time", "fuse the beads through the wall", P),
    ("eps", "cooling_time_s", "15 + 0.04 * wall_mm ** 2", "10", "30 + 0.06 * wall_mm ** 2", "s", "Cooling (vacuum) time", "until the part holds its shape on ejection", P),
    ("eps", "bead_density_kg_m3", "density_g_cm3 * 1000", "", "", "kg/m³", "Pre-expanded bead density", "the material grade", P),
    ("eps", "risk_thick", "wall_mm > 60", "", "", "", "Wall {wall_mm:.0f} mm is thick: steam may not reach the core, use steam-through cores.", "", "risk"),
    ("blow", "preform_temp_c", "melt_c", "melt_min_c", "melt_max_c", "°C", "Preform temperature at the blow station", "material window", P),
    ("blow", "pre_blow_bar", "8", "5", "12", "bar", "Pre-blow pressure", "forms the bubble before the stretch rod bottoms", P),
    ("blow", "blow_pressure_bar", "min(40, 20 + 0.05 * part_h_mm)", "18", "40", "bar", "High blow pressure", "taller containers need more pressure to take the mould detail", P),
    ("blow", "mould_temp_c", "mould_c", "mould_min_c", "mould_max_c", "°C", "Blow-mould water temperature", "material window", P),
    ("blow", "mould_cooling_s", "1.2 + 4 * wall_mm", "1 + 3 * wall_mm", "2 + 5 * wall_mm", "s", "Cooling time in the mould", "thicker walls hold heat longer", P),
    ("blow", "risk_thin", "wall_mm < 0.3", "", "", "", "Wall {wall_mm:.2f} mm is very thin: top-load and burst strength are at risk.", "", "risk"),
]
SAMPLE = {"plastic": ("melt_c", "melt_min_c", "melt_max_c", "mould_c", "mould_min_c", "mould_max_c", "eject_c", "dry_c", "dry_h", "density_g_cm3", "flow_ratio", "thin_cm2", "sink_risk_cm2",
                      "surface_cm2", "draft_low_cm2", "undercut_cm2", "fill_s", "cooling_s", "cycle_s", "injection_bar", "cavity_bar", "clamp_t", "shot_weight_g", "wall_mm", "max_wall_mm",
                      "min_wall_mm", "cavities", "projected_area_cm2", "runner_pct"),
          "die_casting": ("melt_c", "melt_min_c", "melt_max_c", "mould_c", "mould_min_c", "mould_max_c", "eject_c", "density_g_cm3", "thin_cm2", "sink_risk_cm2", "surface_cm2", "draft_low_cm2",
                          "undercut_cm2", "fill_s", "solidify_s", "spray_s", "cycle_s", "clamp_t", "cavity_pressure_bar", "wall_mm", "max_wall_mm", "min_wall_mm", "cavities", "shot_weight_g"),
          "sheet_metal": ("t", "yield_mpa", "tensile_mpa", "shear_mpa", "ldr", "force_t", "total_force_t", "stages", "draw_ratio", "draw_depth", "draw_dia", "bend_radius", "springback_deg",
                          "max_springback_deg", "progressive", "progressive_ok", "press_safety_factor", "spm_progressive", "spm_stage", "clearance_mm", "hole_count", "blank_l", "blank_w"),
          "foundry": ("melt_c", "melt_min_c", "melt_max_c", "mould_c", "mould_min_c", "mould_max_c", "poured_weight_kg", "part_modulus_mm", "part_weight_kg", "part_volume_cm3", "part_h_mm"),
          "eps": ("melt_c", "melt_min_c", "melt_max_c", "mould_c", "mould_min_c", "mould_max_c", "density_g_cm3", "wall_mm", "part_h_mm", "volume_cm3"),
          "blow": ("melt_c", "melt_min_c", "melt_max_c", "mould_c", "mould_min_c", "mould_max_c", "eject_c", "dry_c", "dry_h", "density_g_cm3", "wall_mm", "part_h_mm", "volume_cm3")}
LIST_PARAMS = {"progressive": "1 when the die is progressive"}


def seed() -> dict:
    d = mould_db.tables()
    out = {"windows": 0, "rules": 0}
    have = {r["material"] for r in d["process_windows"]}
    for m, *vals in SEED_WINDOWS:
        if m not in have:
            d["process_windows"].append(dict(zip(("material",) + WINDOW_FIELDS, (m, *vals))) | {"is_example": 1, "notes": EXAMPLE})
            out["windows"] += 1
    have = {(r["part_type"], r["name"]) for r in d["process_parameters"]}
    step = {}
    for pt, name, f, lo, hi, unit, label, why, kind in SEED_RULES:
        step[pt] = step.get(pt, 0) + 1
        if (pt, name) not in have:
            d["process_parameters"].append({"part_type": pt, "step": step[pt], "name": name, "formula": f, "min_formula": lo, "max_formula": hi, "unit": unit, "label": label, "why": why,
                                            "kind": kind, "is_example": 1, "notes": EXAMPLE})
            out["rules"] += 1
    out["simulation_rules"] = 0
    for r in d["simulation_rules"]:        # the simulation uses the material's window for melt, mould and ejection temperature (rows you edited are left alone)
        old = {"melt_c": "230", "mould_c": "50", "eject_c": "90"}.get(r["name"])
        if r["part_type"] == "plastic" and old and r["formula"] == old:
            r["formula"] = f"{r['name']}_material if {r['name']}_material > 0 else {old}"
            out["simulation_rules"] += 1
    if any(out.values()):
        mould_db.write(d)
    return out


def window(material: str) -> dict:
    row = next((r for r in mould_db.tables()["process_windows"] if r["material"] == material), None)
    return {k: float(row[k] or 0) for k in WINDOW_FIELDS} if row else {}


def sample_env(part_type: str) -> dict:
    env = {k: 1.0 for k in SAMPLE.get(part_type, ())} | {k: 1.0 for k in LIST_PARAMS}
    env |= {k: float(v) for k, v in master_data.parameters(part_type).items() if isinstance(v, (int, float))}
    return env


def validate(clean: dict) -> None:
    rows = clean.get("process_parameters", [])
    for pt in {r["part_type"] for r in rows}:
        env = sample_env(pt)
        for i, r in enumerate(sorted((x for x in rows if x["part_type"] == pt), key=lambda x: x["step"]), start=1):
            if not r["name"].isidentifier():
                raise mould_db.MouldDbError(f"Process parameters '{r['name']}' must be one word (letters, digits and _).")
            if r["kind"] not in KINDS:
                raise mould_db.MouldDbError(f"Process parameters ({r['name']}): kind must be parameter or risk.")
            for col in ("formula", "min_formula", "max_formula"):
                if r.get(col):
                    try:
                        v = formula.evaluate(r[col], env)
                        if col == "formula":
                            env[r["name"]] = v
                    except formula.FormulaError as exc:
                        raise mould_db.MouldDbError(f"Process parameters ({r['name']}, {col}): {exc}") from None
                    except (ArithmeticError, ValueError):
                        env[r["name"]] = 1.0


# ---------- the inputs of a part ----------

def _material_env(material: str) -> dict:
    win = window(material)
    density, _ = register._density(material)
    return win | {"density_g_cm3": density or 1.0}


def _env(part_id: int) -> tuple[str, dict, str]:
    """(part type, rule environment, where the numbers come from) of the part's current revision."""
    d = register.part_detail(part_id, with_rm=False)
    pt = register_setup.processes().get(d["process"], {}).get("part_type")
    if pt not in SAMPLE:
        raise register.ToolNotApplicable("Process parameters are worked out for moulded, cast, sheet-metal, EPS and blow parts.")
    env = _material_env(d["material"]) | {k: float(v) for k, v in master_data.parameters(pt).items() if isinstance(v, (int, float))}
    g = (d["revisions"][0]["geometry"] if d["revisions"] else None) or {}
    if pt in ("plastic", "die_casting"):
        _, _, res = register._simulate(part_id)
        env |= {k: float(v) for k, v in res["results"].items() if isinstance(v, (int, float))} | {k: float(v) for k, v in res["maps"].items()}
        env |= {"cavities": float(res["results"].get("cavities", 1))}
        return pt, env, "simulation of the part (wall thickness, flow, cooling, clamp force) and the material window"
    if pt == "sheet_metal":
        from . import design_pack
        P = design_pack.sheet_prepare(part_id)
        res, design = P["res"], P["design"]
        big = max(design["stages"], key=lambda s: s["force_t"])
        env |= {k: float(v) for k, v in res["features"].items() if isinstance(v, (int, float))} | {k: float(v) for k, v in res["values"].items() if isinstance(v, (int, float))}
        env |= {k: float(v) for k, v in res.get("material_values", {}).items()} | {k: float(v) for k, v in big["values"].items() if isinstance(v, (int, float))}
        prog = design["mode"] == "progressive"
        env |= {"force_t": float(design["total_force_t"] if prog else big["force_t"]), "total_force_t": float(design["total_force_t"]), "stages": float(len(design["stages"])),
                "progressive": 1.0 if prog else 0.0, "progressive_ok": 1.0 if res.get("recommended") == "progressive" else 0.0,
                "draw_ratio": float(max((s["workpiece"]["draw_ratio"] for s in design["stages"]), default=0)), "t": float(design["thickness_mm"])}
        return pt, env, "stage forces, draw ratio and springback of the sheet-metal tool design and the sheet material"
    geo = {"volume_cm3": g.get("volume_cm3") or 0.0, "wall_mm": g.get("wall_mm") or 0.0, "surface_cm2": (g.get("surface_area_mm2") or 0.0) / 100,
           "part_h_mm": max((g.get("bbox_axes_mm") or {"x": 0}).values()), "part_weight_kg": (g.get("volume_cm3") or 0.0) * env["density_g_cm3"] / 1000}
    env |= {k: float(v) for k, v in geo.items()}
    if pt == "foundry":
        from . import foundry_design, tool_internals
        env["part_modulus_mm"] = geo["volume_cm3"] * 1000 / max(geo["surface_cm2"] * 100, 1.0)
        fm = foundry_design.material_row(d["material"])
        bb = g.get("bbox_axes_mm") or {"x": 1, "y": 1, "z": 1}
        denv = {"part_weight_kg": geo["part_weight_kg"], "part_volume_cm3": geo["volume_cm3"], "part_surface_cm2": geo["surface_cm2"], "part_modulus_mm": env["part_modulus_mm"],
                "riser_modulus_factor": fm["riser_modulus_factor"], "part_l_mm": max(bb.values()), "part_w_mm": sorted(bb.values())[1], "part_h_mm": min(bb.values()),
                "flask_l_mm": 0.0, "flask_w_mm": 0.0}
        env["poured_weight_kg"] = tool_internals.values("foundry", denv)["poured_weight_kg"]
        return pt, env, "casting weight and modulus (the pattern design rules) and the material window"
    return pt, env, "the 3D model (wall, volume, height) and the material window"


def compute(part_id: int) -> dict:
    pt, env, source = _env(part_id)
    rows = sorted((r for r in mould_db.tables()["process_parameters"] if r["part_type"] == pt), key=lambda r: r["step"])
    if not rows:
        raise register.ToolNotApplicable(f"Mould & die database → Process parameters has no rows for '{pt}'.")
    params, risks, derived = [], [], dict(env)
    for r in rows:
        try:
            v = float(formula.evaluate(r["formula"], derived))
            lo = float(formula.evaluate(r["min_formula"], derived)) if r["min_formula"] else None
            hi = float(formula.evaluate(r["max_formula"], derived)) if r["max_formula"] else None
        except (formula.FormulaError, ArithmeticError, ValueError) as exc:
            raise register.RegisterError(f"Process parameter '{r['name']}': {exc}") from None
        derived[r["name"]] = v
        if r["kind"] == "risk":
            if v > 0:
                try:
                    risks.append(r["label"].format(**{k: x for k, x in derived.items()}))
                except (KeyError, ValueError):
                    risks.append(r["label"])
            continue
        if r["unit"] == "" and not r["min_formula"] and r["name"].endswith("_share"):
            continue                       # helper values that only feed other rows
        params.append({"name": r["name"], "label": r["label"], "value": round(v, 3), "min": None if lo is None else round(lo, 3), "max": None if hi is None else round(hi, 3),
                       "unit": r["unit"], "why": r["why"], "is_example": bool(r["is_example"])})
    d = register.part_detail(part_id, with_rm=False)
    return {"part_id": part_id, "part_code": d["part_code"], "part_type": pt, "material": d["material"], "source": source, "parameters": params, "risks": risks,
            "window": window(d["material"]), "is_example": any(p["is_example"] for p in params),
            "note": "Starting values for the first trial, worked out from the simulation of the part. Confirm them in the try-out and keep what works in the rows above."}


# ---------- documents ----------

def section(res: dict) -> dict:
    rows = [[p["label"], p["value"], "" if p["min"] is None else f"{p['min']:g} – {p['max']:g}", p["unit"], p["why"]] for p in res["parameters"]]
    text = [f"Worked out from {res['source']}. {res['note']}"] + [f"WARNING: {r}" for r in res["risks"]]
    return {"title": "Process parameters for the best part quality", "text": text, "table": {"headers": ["Setting", "Value", "Range", "Unit", "Why"], "rows": rows}}


def report(part_id: int) -> dict:
    res = compute(part_id)
    d = register.part_detail(part_id, with_rm=False)
    return {"title": f"{d['part_code']} - {d['name']}: process parameters", "subtitle": f"{d['material']} · {d['process']} · {res['source']}", "example": res["is_example"],
            "kpis": [("Part", f"{d['part_code']} - {d['name']}"), ("Material", d["material"]), ("Process", d["process"]), ("Settings", len(res["parameters"])), ("Quality warnings", len(res["risks"]))],
            "sections": [section(res)]}
