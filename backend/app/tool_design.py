"""Tool design (roadmap stage 20): mould concept in 3D and stage-wise sheet-metal tool design.

Sheet metal (every stage of the sequence, multi-stage dies or one progressive die):
    sequence       sheet_tools.run (blank, pierce, draw, bend, trim) with draws expanded by the material's limiting draw ratio
    stage size     master-data rows `Stage tool rules` (clearance, plate thicknesses, margin, die set size, pillars, shut
                   height, draw radii, V opening …). Nothing is typed into the code.
    press          smallest press (any tonnage up to the largest in Machines) whose force AND bolster take the die set
    3D + 2D        every stage die set as solids (lower shoe, die, workpiece, stripper, punch plate, punches, upper shoe,
                   guide pillars) and a plan drawing; forming surfaces of draw / bend stages are concept blocks sized to the
                   workpiece (the detailed forming surface is for the engineer's CAD)

Moulds and dies (plastic, die casting): `mould_3d` builds the concept from the sized base: plates, pillars, core and cavity
inserts cut from the corrected part along the proposed parting plane. A concept, not a final tool design.
"""

from __future__ import annotations

import math

import cadquery as cq
from shapely.geometry import Polygon

from . import corrections, costing_setup, formula, master_data, mould_db, rates

STAGE_VARS = ("t", "shear_mpa", "tensile_mpa", "yield_mpa", "force_t", "work_l", "work_w", "work_h", "blank_l", "blank_w",
              "stations", "pitch_mm", "strip_width_mm", "bend_radius", "draw_dia", "draw_depth", "hole_count", "bends",
              "stage_n", "stage_count", "part_l", "part_w", "part_h")
EXAMPLE = "EXAMPLE rule - replace with your die-shop practice"
FIRST_DRAW_NOTE = "draw stages after the first take the later-draw reduction (Parameters → later_draw_ratio)"

SEED_RULES = [
    # op, name, formula, unit, meaning
    ("all", "clearance_pct", "4 + shear_mpa / 100", "%", "Die clearance per side, % of thickness (harder material → more)"),
    ("all", "clearance_mm", "clearance_pct / 100 * t", "mm", "Die clearance per side"),
    ("all", "die_block_t_mm", "max(25, 12 + 3 * sqrt(force_t))", "mm", "Die block thickness (grows with the force)"),
    ("all", "punch_plate_t_mm", "0.8 * die_block_t_mm", "mm", "Punch plate thickness"),
    ("all", "stripper_t_mm", "max(20, 0.6 * die_block_t_mm)", "mm", "Stripper plate thickness"),
    ("all", "backing_t_mm", "max(12, 0.3 * die_block_t_mm)", "mm", "Backing plate thickness"),
    ("all", "shoe_t_mm", "max(35, 0.9 * die_block_t_mm + 0.02 * max(work_l, work_w))", "mm", "Upper and lower shoe thickness"),
    ("all", "margin_mm", "60 + 0.05 * max(work_l, work_w)", "mm", "Die set margin around the work area, each side"),
    ("all", "die_set_l_mm", "work_l + 2 * margin_mm", "mm", "Die set length"),
    ("all", "die_set_w_mm", "work_w + 2 * margin_mm", "mm", "Die set width"),
    ("all", "pillar_dia_mm", "max(25, round(25 + 0.012 * max(die_set_l_mm, die_set_w_mm)))", "mm", "Guide pillar diameter"),
    ("all", "pillars", "4", "pcs", "Guide pillars (4 diagonal / corner)"),
    ("all", "strip_force_t", "stripping_pct / 100 * force_t", "t", "Stripping force"),
    ("all", "shut_height_mm", "2 * shoe_t_mm + die_block_t_mm + punch_plate_t_mm + stripper_t_mm + backing_t_mm + 30", "mm",
     "Shut height of the closed die set"),
    ("all", "open_gap_mm", "max(40, 2 * work_h + 20)", "mm", "Daylight between the halves when open (shown in the 3D model)"),
    ("draw", "draw_die_radius_mm", "8 * t", "mm", "Die entry radius (4–10 × t)"),
    ("draw", "draw_punch_radius_mm", "5 * t", "mm", "Punch nose radius"),
    ("draw", "draw_clearance_mm", "1.1 * t", "mm", "Gap between punch and die ring, per side"),
    ("draw", "blank_holder_force_t", "0.3 * force_t", "t", "Blank holder force"),
    ("bend", "v_opening_mm", "max(8 * t, 6 * t + 2 * bend_radius)", "mm", "V-die opening"),
    ("bend", "bend_punch_radius_mm", "bend_radius", "mm", "Bend punch nose radius"),
    ("bend", "bend_punch_angle_deg", "max(30, bend_angle_deg - springback_deg)", "°", "Bend punch / die angle: overbent by the springback allowance"),
    ("trim", "trim_clearance_mm", "clearance_mm", "mm", "Trim steel clearance per side"),
    ("pierce", "punch_relief_mm", "0.5", "mm", "Slug relief below the die button"),
]
SEED_PARAMS = {"later_draw_ratio": 1.3}   # Parameters (sheet_metal)

DIE_STEEL = "D2 (1.2379)"
PLATE_STEEL = "Mould base steel (4140 / 1.7225)"


class DesignError(ValueError):
    pass


# ------------------------------------------------------------ master data

def seed(month: str | None = None) -> dict:
    """Add the Stage tool rules rows (EXAMPLE values) and the later_draw_ratio parameter if missing. Idempotent."""
    out = {"rules": 0, "parameters": 0}
    db = mould_db.tables()
    have = {(r["op"], r["name"]) for r in db["stage_rules"]}
    rows = [{"op": op, "step": float(i), "name": n, "formula": f, "unit": u, "label": lab, "is_example": 1, "notes": EXAMPLE}
            for i, (op, n, f, u, lab) in enumerate(SEED_RULES, start=1) if (op, n) not in have]
    if rows:
        db["stage_rules"] = db["stage_rules"] + rows
        mould_db.write(db)
        out["rules"] = len(rows)
    md = master_data.tables()
    have_p = {(r["part_type"], r["parameter"]) for r in md["Parameters"]}
    new = [{"part_type": "sheet_metal", "parameter": k, "value": v, "unit": "x",
            "description": "Reduction ratio of every draw after the first (EXAMPLE)", "notes": "EXAMPLE"}
           for k, v in SEED_PARAMS.items() if ("sheet_metal", k) not in have_p]
    if new:
        cols = md["Parameters"][0].keys() if md["Parameters"] else ()
        md["Parameters"] = md["Parameters"] + [{c: r.get(c, "") for c in cols} for r in new]
        master_data.write(md)
        out["parameters"] = len(new)
    return out


def validate(clean: dict) -> None:
    env = {k: 1.0 for k in STAGE_VARS}
    env |= {k: 1.0 for k in ("springback_deg", "draw_ratio", "progressive_ok")} | {r["name"]: 1.0 for r in clean.get("sheet_rules", [])}
    env |= {k: float(v) for k, v in master_data.parameters("sheet_metal").items() if isinstance(v, (int, float))}
    for i, r in enumerate(sorted(clean.get("stage_rules", []), key=lambda r: (r["op"] != "all", r["step"])), start=2):
        if not r["name"].isidentifier():
            raise mould_db.MouldDbError(f"Stage tool rules '{r['name']}' must be one word (letters, digits and _).")
        try:
            env[r["name"]] = float(formula.evaluate(r["formula"], env))
        except formula.FormulaError as exc:
            raise mould_db.MouldDbError(f"Stage tool rules ({r['name']}): {exc}") from None
        except (ArithmeticError, ValueError):
            env[r["name"]] = 1.0


def rule_values(op: str, base: dict) -> tuple[dict, list[dict]]:
    """Run the 'all' rules and the rules of `op` in order. Returns the values and the steps (formula, value)."""
    env = {k: 0.0 for k in STAGE_VARS}
    env |= {k: float(v) for k, v in master_data.parameters("sheet_metal").items() if isinstance(v, (int, float))}
    env |= base
    steps = []
    rows = [r for r in mould_db.tables()["stage_rules"] if r["op"] in ("all", op)]
    for r in sorted(rows, key=lambda r: (r["op"] != "all", r["step"])):
        try:
            env[r["name"]] = float(formula.evaluate(r["formula"], env))
        except (ArithmeticError, ValueError, formula.FormulaError) as exc:
            raise DesignError(f"Stage tool rule '{r['name']}' ({r['formula']}): {exc}") from None
        steps.append({"name": r["name"], "label": r["label"], "formula": r["formula"], "unit": r["unit"],
                      "value": env[r["name"]], "is_example": r["is_example"]})
    return env, steps


# ------------------------------------------------------------ press and steel

def press_fit(force_t: float, die_l: float, die_w: float) -> dict:
    """Smallest press whose tonnage takes the force and whose bolster takes the die set (either way round)."""
    process = master_data.parameters("sheet_metal").get("press_machine_process")
    ms = sorted((m for m in costing_setup.tables()["machines"] if m["process"] == process), key=lambda m: m["tonnage_t"])
    short, tall = sorted((die_l, die_w))
    for m in ms:
        bed_s, bed_l = sorted((m["length_mm"] or 0, m["width_mm"] or 0))
        if m["tonnage_t"] >= force_t and (not bed_l or (short <= bed_s and tall <= bed_l)):
            return {"machine_id": m["machine_id"], "name": m["name"], "tonnage_t": m["tonnage_t"],
                    "bolster_mm": [m["length_mm"], m["width_mm"]], "fits": True}
    biggest = ms[-1] if ms else None
    return {"machine_id": None, "fits": False, "biggest_t": biggest["tonnage_t"] if biggest else 0,
            "reason": f"no '{process}' takes {force_t:.0f} t with a {die_l:.0f} × {die_w:.0f} mm die set"}


def _steel(code: str, country: str, month: str) -> tuple[float, float]:
    """(density g/cm³, rate per kg in the tool country's currency)."""
    row = next((r for r in mould_db.tables()["tool_materials"] if r["code"] == code), None)
    if not row:
        return 7.85, 0.0
    try:
        return row["density_g_cm3"], rates.lookup("tool_material", code, country, month)["value"]
    except Exception:
        return row["density_g_cm3"], 0.0


def _component(name, steel, l, w, t, qty, country, month, dia=None):
    dens, rate = _steel(steel, country, month)
    vol_cm3 = (math.pi / 4 * dia * dia * t if dia else l * w * t) / 1000
    kg = vol_cm3 * dens / 1000
    return {"name": name, "steel": steel, "length_mm": round(l, 1), "width_mm": round(w, 1), "thickness_mm": round(t, 1),
            "qty": qty, "weight_kg": round(kg * qty, 2), "steel_cost": round(kg * qty * rate, 0)}


# ------------------------------------------------------------ sheet-metal stages

def _sequence(res: dict, fp: dict, material_row: dict) -> list[dict]:
    """The operations with draws expanded to the number of draws the material's limiting draw ratio needs."""
    feat = res["features"]
    params = master_data.parameters("sheet_metal")
    later = float(params.get("later_draw_ratio", SEED_PARAMS["later_draw_ratio"]))
    stages = []
    for o in res["operations"]:
        if o["code"] != "draw" or feat["draw_dia"] <= 0:
            stages.append(dict(o, sub=""))
            continue
        total = max(feat["blank_dia"] / feat["draw_dia"], 1.0)
        first = material_row["ldr"] or 2.0
        n = 1 if total <= first else 1 + math.ceil(math.log(total / first) / math.log(later))
        d = feat["blank_dia"]
        for k in range(1, n + 1):
            beta = min(first if k == 1 else later, d / feat["draw_dia"]) if k < n else d / feat["draw_dia"]
            d_out = d / max(beta, 1.0)
            h = max((feat["blank_dia"] ** 2 - d_out ** 2) / (4 * d_out), 0.0)
            force = o["force_t"] * (1.0 if k == 1 else 0.6)
            stages.append(dict(o, sub=f"{k}/{n}", name=f"Drawing {k}/{n}", force_t=force, cup_dia=d_out, cup_height=h,
                               draw_ratio=beta, force_formula=o["force_formula"] + ("" if k == 1 else f" × 0.6 ({FIRST_DRAW_NOTE})")))
            d = d_out
    for i, s in enumerate(stages, start=1):
        s["n"] = i
    return stages


def sheet_design(fp: dict, sl: dict, res: dict, geometry: dict, country: str = "IN", month: str | None = None) -> dict:
    """Stage-wise tool design of a sheet-metal part. `fp` flat pattern, `sl` strip layout, `res` sheet_tools.run result."""
    month = month or rates.current_month()
    feat = res["features"]
    mats = {r["material"]: r for r in mould_db.tables()["sheet_materials"]}
    mat = mats[res["material"]]
    stages = _sequence(res, fp, mat)
    progressive = res["mode"] == "progressive"
    safety = res["safety_factor"]
    b = geometry["bbox_mm"]
    base = {"t": feat["t"], "shear_mpa": mat["shear_mpa"], "tensile_mpa": mat["tensile_mpa"], "yield_mpa": mat["yield_mpa"],
            "blank_l": fp["length_mm"], "blank_w": fp["width_mm"], "work_l": fp["length_mm"], "work_w": fp["width_mm"],
            "work_h": b["height"], "bend_radius": feat["bend_radius"], "draw_dia": feat["draw_dia"], "draw_depth": feat["draw_depth"],
            "hole_count": feat["hole_count"], "bends": feat["bends"], "stage_count": len(stages),
            "part_l": b["length"], "part_w": b["width"], "part_h": b["height"]}
    base |= {k: float(v) for k, v in res.get("values", {}).items() if isinstance(v, (int, float))}
    sv = sl["best"]["values"] if progressive else {}
    if progressive:
        base |= {"stations": sv["stations"], "pitch_mm": sv["pitch_mm"], "strip_width_mm": sv["strip_width_mm"],
                 "work_l": sv["stations"] * sv["pitch_mm"], "work_w": sv["strip_width_mm"]}
    total_force = sum(s["force_t"] for s in stages)
    out_stages, warnings = [], []
    for s in stages:
        force = (total_force if progressive else s["force_t"])
        vals, steps = rule_values(s["code"], base | {"force_t": force, "stage_n": s["n"]})
        l, w, t = vals["die_set_l_mm"], vals["die_set_w_mm"], base["t"]
        press = press_fit(force * safety, l, w)
        comps = [
            _component("Lower shoe", PLATE_STEEL, l, w, vals["shoe_t_mm"], 1, country, month),
            _component("Die block / buttons", DIE_STEEL, l - 2 * vals["margin_mm"] * 0.4, w - 2 * vals["margin_mm"] * 0.4,
                       vals["die_block_t_mm"], 1, country, month),
            _component("Stripper plate", PLATE_STEEL, l - 2 * vals["margin_mm"] * 0.4, w - 2 * vals["margin_mm"] * 0.4,
                       vals["stripper_t_mm"], 1, country, month),
            _component("Punch plate", PLATE_STEEL, l - 2 * vals["margin_mm"] * 0.4, w - 2 * vals["margin_mm"] * 0.4,
                       vals["punch_plate_t_mm"], 1, country, month),
            _component("Backing plate", DIE_STEEL, l - 2 * vals["margin_mm"] * 0.6, w - 2 * vals["margin_mm"] * 0.6,
                       vals["backing_t_mm"], 1, country, month),
            _component("Upper shoe", PLATE_STEEL, l, w, vals["shoe_t_mm"], 1, country, month),
            _component("Guide pillar", PLATE_STEEL, 0, 0, vals["shut_height_mm"] - vals["shoe_t_mm"], int(vals["pillars"]),
                       country, month, dia=vals["pillar_dia_mm"]),
        ]
        if s["code"] in ("blank", "pierce", "trim") or progressive:
            per = max(feat["hole_count"], 1) if s["code"] == "pierce" else 1
            comps.append(_component("Punch(es) / cutting steel", DIE_STEEL, 40, 40, vals["die_block_t_mm"] + vals["stripper_t_mm"],
                                    per, country, month))
        if s["code"] in ("draw", "bend"):
            comps.append(_component("Forming punch", DIE_STEEL, max(s.get("cup_dia", b["length"]) - 2 * t, 20),
                                    max(s.get("cup_dia", b["width"]) - 2 * t, 20), vals["die_block_t_mm"], 1, country, month))
        out_stages.append({
            "n": s["n"], "code": s["code"], "name": s["name"], "force_t": round(s["force_t"], 2),
            "design_force_t": round(force * safety, 2), "force_formula": s["force_formula"],
            "stage_weight_g": round(s["stage_weight_g"], 1), "scrap_g": round(s.get("scrap_g", 0.0), 1),
            "workpiece": {"kind": "cup" if "cup_dia" in s else "formed" if s["code"] in ("draw", "bend") else "flat",
                          "cup_dia_mm": round(s.get("cup_dia", 0), 1), "cup_height_mm": round(s.get("cup_height", 0), 1),
                          "draw_ratio": round(s.get("draw_ratio", 0), 2)},
            "values": {k: round(vals[k], 2) for k in [x["name"] for x in steps]}, "steps": steps,
            "press": press, "components": comps,
            "weight_kg": round(sum(c["weight_kg"] for c in comps), 1), "steel_cost": round(sum(c["steel_cost"] for c in comps)),
            "is_example": any(x["is_example"] for x in steps),
        })
        if not press["fits"]:
            warnings.append(f"Stage {s['n']} {s['name']}: {press['reason']}.")
    forming = [o for o in out_stages if o["code"] in ("draw", "bend")]
    if forming:
        forming[-1]["real_form"] = True
        for o in out_stages:
            o["after_forming"] = o["n"] > forming[-1]["n"] and o["code"] == "trim"
    if progressive:
        for o in out_stages[1:]:
            o["shared_die_set"] = True
    sets = ([{"name": "Progressive die set", "stages": [s["n"] for s in out_stages], "die_set_mm": [out_stages[0]["values"]["die_set_l_mm"],
             out_stages[0]["values"]["die_set_w_mm"]], "shut_height_mm": out_stages[0]["values"]["shut_height_mm"],
             "press": out_stages[0]["press"]}] if progressive and out_stages else
            [{"name": f"Stage {s['n']} {s['name']}", "stages": [s["n"]], "die_set_mm": [s["values"]["die_set_l_mm"], s["values"]["die_set_w_mm"]],
              "shut_height_mm": s["values"]["shut_height_mm"], "press": s["press"]} for s in out_stages])
    total_weight = sum(s["weight_kg"] for s in (out_stages[:1] if progressive else out_stages))
    return {"mode": res["mode"], "material": res["material"], "thickness_mm": base["t"], "pitch_mm": sv.get("pitch_mm", 0), "country": country, "month": month,
            "stages": out_stages, "die_sets": sets, "rotate": bool(progressive and sl.get("best", {}).get("feed", "").endswith("width")), "warnings": warnings, "total_force_t": round(total_force, 1),
            "tool_weight_kg": round(total_weight, 1),
            "steel_cost": round(sum(s["steel_cost"] for s in (out_stages[:1] if progressive else out_stages))),
            "currency": rates.lookup("tool_material", DIE_STEEL, country, month)["currency"] if _steel(DIE_STEEL, country, month)[1] else "",
            "is_example": any(s["is_example"] for s in out_stages) or res["is_example"],
            "note": "Concept tool design: sizes follow the Stage tool rules; draw and bend forming surfaces are concept blocks. "
                    "Steel cost only (machining, heat treatment, design and try-out come with the sheet-metal tool cost stage)."}



# ------------------------------------------------------------ tool surfaces from the part (sweeps along the press / opening direction)

def sweep(shape: cq.Shape, dz: float) -> cq.Shape | None:
    """The volume swept by `shape` along Z by dz: the region above (dz > 0) or below (dz < 0) every material point.
    Vertical faces sweep to nothing and are skipped; every other face is swept with its orientation fixed and fused."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    out = []
    for f in shape.Faces():
        n = f.normalAt(corrections.sample_point(f))
        if abs(n.z) < 0.02 and f.geomType() in ("PLANE", "CYLINDER", "CONE"):
            continue
        w = f.wrapped.Reversed() if n.z * dz < 0 else f.wrapped
        p = cq.Shape.cast(BRepPrimAPI_MakePrism(w, gp_Vec(0, 0, dz)).Shape())
        if p.Volume() < -1e-9:
            p = cq.Shape.cast(p.wrapped.Reversed())
        if p.Volume() > 1e-6:
            out.append(p)
    if not out:
        return None
    return out[0].fuse(*out[1:]) if len(out) > 1 else out[0]


def sweep_vec(shape: cq.Shape, vec: tuple) -> cq.Shape | None:
    """Volume swept by `shape` along any vector (faces swept with their orientation fixed, then fused)."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    v = cq.Vector(*vec)
    unit = v.normalized()
    out = []
    for f in shape.Faces():
        n = f.normalAt(corrections.sample_point(f))
        if abs(n.dot(unit)) < 0.02 and f.geomType() in ("PLANE", "CYLINDER", "CONE"):
            continue
        w = f.wrapped.Reversed() if n.dot(v) < 0 else f.wrapped
        p = cq.Shape.cast(BRepPrimAPI_MakePrism(w, gp_Vec(*vec)).Shape())
        if p.Volume() < -1e-9:
            p = cq.Shape.cast(p.wrapped.Reversed())
        if p.Volume() > 1e-6:
            out.append(p)
    if not out:
        return None
    return out[0].fuse(*out[1:]) if len(out) > 1 else out[0]


def flange_level(shape: cq.Shape) -> float:
    """Z of the underside of the sheet where it is still flat: the highest downward-facing planar face (a flange or a
    flat leg). Falls back to the lowest point of the part."""
    bb = shape.BoundingBox()
    levels = [f.Center().z for f in shape.Faces() if f.geomType() == "PLANE" and f.normalAt().z < -0.999]
    return max(levels) if levels else bb.zmin


def place_formed(shape: cq.Shape, z_top: float) -> cq.Shape:
    """The formed part centred in XY, turned (if needed) so that its formed features point DOWN into the die, with the
    flat sheet level at z_top."""
    best = None
    for turned in (False, True):
        cand = shape.rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), 180) if turned else shape
        level = flange_level(cand)
        depth = level - cand.BoundingBox().zmin
        if best is None or depth > best[0] + 1e-6:
            best = (depth, cand, level)
    _, cand, level = best
    bb = cand.BoundingBox()
    return cand.translate(cq.Vector(-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, z_top - level))


def forming_parts(part: cq.Shape, z_top: float, t: float, box_l: float, box_w: float, height: float) -> dict:
    """Surfaces of a forming die and punch taken from the placed part (sheet level at z_top, no undercuts):
        die_cut   volume removed from the die block (everything above the part's lower envelope)
        core      the punch body: material above the part's upper envelope, from the part up to z_top + t
        pocket    clearance for the part where it stands taller than the punch plate level (cut from stripper and plate)"""
    bb = part.BoundingBox()
    big = (bb.zlen + height) * 2 + 20
    up, dn = sweep(part, big), sweep(part, -big)
    if up is None or dn is None:
        raise ValueError("the part has no surface facing the press direction")
    zlo = min(bb.zmin, z_top - t)
    sil = up.fuse(dn)
    core = _box(box_l, box_w, (z_top + t) - zlo, z=zlo).val().intersect(sil).cut(dn)
    pocket = None
    if bb.zmax > z_top + t + 0.1:
        above = part.intersect(_box(bb.xlen + 20, bb.ylen + 20, bb.zmax - (z_top + t) + 5, x=(bb.xmin + bb.xmax) / 2,
                                    y=(bb.ymin + bb.ymax) / 2, z=z_top + t).val())
        pocket = sweep(above, big) if above.Volume() > 1e-6 else None
    # undercut test: material column with air between the envelopes that is neither part nor tool
    try:
        fp_box = _box(bb.xlen + 4, bb.ylen + 4, bb.zlen + height + 4, x=(bb.xmin + bb.xmax) / 2, y=(bb.ymin + bb.ymax) / 2,
                      z=bb.zmin - 2).val().intersect(sil)
        void = fp_box.cut(up.cut(part) if False else fp_box.cut(dn)).cut(fp_box.cut(up)).cut(part)
        void_mm3 = void.Volume()
    except Exception:
        void_mm3 = 0.0
    return {"die_cut": up, "core": core, "pocket": pocket, "void_mm3": void_mm3}


def wipers(placed: cq.Shape, z_top: float, t: float, strp: float, v: dict, gap: float) -> dict:
    """Wiper steels for flanges that hang below the flat sheet: a steel on the outside of each flange, from the flange bottom up to the punch
    plate, so that the descending punch wipes the flange down against the die. Returns the solids (to be added to the punch side)."""
    out, note = [], ""
    bb = placed.BoundingBox()
    try:
        below = placed.intersect(_box(bb.xlen + 20, bb.ylen + 20, bb.zlen + 20, x=(bb.xmin + bb.xmax) / 2, y=(bb.ymin + bb.ymax) / 2, z=bb.zmin - 10).val().cut(
            _box(bb.xlen + 40, bb.ylen + 40, 100, x=(bb.xmin + bb.xmax) / 2, y=(bb.ymin + bb.ymax) / 2, z=z_top - 0.01).val()))
    except Exception:
        return {"solids": [], "note": ""}
    cx, cy = (bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2
    wt = v.get("wiper_thickness_mm", max(10, 4 * t))
    z_plate = z_top + t + strp
    for leg in below.Solids():
        lb = leg.BoundingBox()
        if leg.Volume() < 4 * t * t * t or lb.zlen < 1.5 * t:
            continue
        lc = ((lb.xmin + lb.xmax) / 2 - cx, (lb.ymin + lb.ymax) / 2 - cy)
        if abs(lc[0]) < 0.2 * bb.xlen and abs(lc[1]) < 0.2 * bb.ylen:
            continue                                         # a leg in the middle (a boss or a rib): the die and the pad handle it
        if abs(lc[0]) >= abs(lc[1]):
            sgn = 1 if lc[0] >= 0 else -1
            x0 = lb.xmax if sgn > 0 else lb.xmin - wt
            blk = _box(wt, lb.ylen + 2, z_plate - lb.zmin + 2, x=x0 + wt / 2, y=(lb.ymin + lb.ymax) / 2, z=lb.zmin - 2).val()
        else:
            sgn = 1 if lc[1] >= 0 else -1
            y0 = lb.ymax if sgn > 0 else lb.ymin - wt
            blk = _box(lb.xlen + 2, wt, z_plate - lb.zmin + 2, x=(lb.xmin + lb.xmax) / 2, y=y0 + wt / 2, z=lb.zmin - 2).val()
        out.append(blk.cut(placed).translate(cq.Vector(0, 0, gap)))
    if len(out) > 4:
        note = f"{len(out)} flanges need wiper steels; the picture shows them all: check the stripper pockets."
    return {"solids": out, "note": note}


# ------------------------------------------------------------ 3D solids

def _box(l, w, h, x=0.0, y=0.0, z=0.0):
    return cq.Workplane("XY").box(l, w, h, centered=(True, True, False)).translate((x, y, z))


def _prism(poly, h, z=0.0, dx=0.0, dy=0.0):
    pts = [(x + dx, y + dy) for x, y in poly]
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    return cq.Workplane("XY").polyline(pts).close().extrude(h).translate((0, 0, z))


def _offset(poly, d):
    p = Polygon(poly).buffer(d, join_style=2)
    return [list(c) for c in p.exterior.coords] if not p.is_empty else poly


def _centred(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return [[x - (max(xs) + min(xs)) / 2, y - (max(ys) + min(ys)) / 2] for x, y in poly], (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2


def _features(design: dict, stage: dict, fp: dict, final_shape, z_die: float, z_top: float, dx: float, gap: float) -> dict:
    """What one stage cuts into the die set: die cuts, stripper cuts, punches and the workpiece after the stage (all shifted by dx)."""
    v = stage["values"]
    t = design["thickness_mm"]
    dieb, strp = v["die_block_t_mm"], v["stripper_t_mm"]
    clr = v["clearance_mm"]
    outline, ox, oy = _centred(fp["outline"])
    holes = [[[x - ox, y - oy] for x, y in h] for h in fp["holes"]]
    turn = bool(design.get("rotate"))                           # progressive strip fed along the blank width: blank turned 90°
    if turn:
        outline = [[y, x] for x, y in outline]
        holes = [[[y, x] for x, y in h] for h in holes]
    f = {"die": [], "strip": [], "punch": [], "plate_cut": [], "work": None}
    place = (lambda shp: place_formed(shp, z_top).rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), 90)) if turn else (lambda shp: place_formed(shp, z_top))
    sh = lambda wp: wp.translate((dx, 0, 0))
    code = stage["code"]
    if code == "trim" and stage.get("after_forming") and final_shape is not None:
        f["work"] = sh(place(final_shape))
    if code in ("blank", "trim"):
        f["die"].append(sh(_prism(_offset(outline, clr), dieb + z_die, 0)))
        f["strip"].append(sh(_prism(_offset(outline, clr * 0.5), strp, z_top + t + gap)))
        f["punch"].append(sh(_prism(outline, strp + t + 5 + gap, z_top - 5)))
        if f["work"] is None:
            f["work"] = sh(_prism(outline, t, z_top - (t if code == "blank" else 0)))
    elif code == "pierce":
        work = _prism(outline, t, z_top)
        for h in holes:
            f["die"].append(sh(_prism(_offset(h, clr), dieb + z_die, 0)))
            f["strip"].append(sh(_prism(h, strp, z_top + t + gap)))
            f["punch"].append(sh(_prism(h, strp + t + 5 + gap, z_top - 5)))
            work = work.cut(_prism(h, t, z_top))
        f["work"] = sh(work)
    elif code in ("draw", "bend") and stage.get("real_form") and final_shape is not None:
        try:
            placed = place(final_shape)
            fp_ = forming_parts(placed, z_top, t, v["die_set_l_mm"] - 2 * v["margin_mm"] * 0.4, v["die_set_w_mm"] - 2 * v["margin_mm"] * 0.4,
                                strp + v["punch_plate_t_mm"])
            f["die"].append(sh(fp_["die_cut"]))
            if fp_["core"].Volume() > 1e-6:
                f["punch"].append(sh(fp_["core"].translate(cq.Vector(0, 0, gap))))
            if fp_["pocket"] is not None:
                f["plate_cut"].append(sh(fp_["pocket"].translate(cq.Vector(0, 0, gap))))
            f["work"] = sh(placed)
            f["real"] = True
            wp = wipers(placed, z_top, t, strp, v, gap)
            for w in wp["solids"]:
                f["punch"].append(sh(w))
                f["plate_cut"].append(sh(w))
                f["die"].append(sh(w.translate(cq.Vector(0, 0, -gap))))
            if fp_.get("void_mm3", 0) > 5:
                design.setdefault("form_notes", []).append(
                    f"Stage {stage['n']}: the part has an undercut of {fp_['void_mm3'] / 1000:.1f} cm³ against the forming direction: it needs a cam or a pad-and-wipe tool, not shown.")
            if wp["note"]:
                design.setdefault("form_notes", []).append(f"Stage {stage['n']}: {wp['note']}")
            return f
        except Exception as exc:  # concept blocks instead
            f["note"] = f"forming surface from the part failed ({str(exc)[:60]}): concept blocks shown"
    if code == "draw":
        d_out = stage["workpiece"]["cup_dia_mm"] or max(fp["length_mm"], fp["width_mm"])
        h_cup = stage["workpiece"]["cup_height_mm"] or 10.0
        bore = d_out + 2 * (v.get("draw_clearance_mm", t) - t)
        f["die"].append(sh(cq.Workplane("XY").circle(bore / 2).extrude(dieb + z_die)))
        f["strip"].append(sh(cq.Workplane("XY").circle(bore / 2 - t).extrude(strp).translate((0, 0, z_top + t + gap))))
        f["punch"].append(sh(cq.Workplane("XY").circle(bore / 2 - t).extrude(strp + h_cup + gap).translate((0, 0, z_top + t - h_cup))))
        f["work"] = sh(cq.Workplane("XY").circle(d_out / 2).circle(d_out / 2 - t).extrude(h_cup)
                       .union(cq.Workplane("XY").circle(d_out / 2).extrude(t)).translate((0, 0, z_top - h_cup)))
    elif code == "bend":
        vo = v.get("v_opening_mm", 8 * t)
        L = max(fp["length_mm"], fp["width_mm"])
        half = math.radians(v.get("bend_punch_angle_deg", 90.0)) / 2
        depth = (vo / 2) / math.tan(half)
        pd = (vo / 3) / math.tan(half)
        f["die"].append(sh(cq.Workplane("XZ").polyline([(-vo / 2, z_top), (vo / 2, z_top), (0, z_top - depth)]).close().extrude(L / 2, both=True)))
        f["punch"].append(sh(cq.Workplane("XZ").polyline([(-vo / 3, z_top + t + strp + gap), (vo / 3, z_top + t + strp + gap),
                                                          (0, z_top + t - pd + gap)]).close().extrude(L / 2, both=True)))
        if final_shape is not None:
            bb = final_shape.BoundingBox()
            f["work"] = sh(cq.Workplane("XY").add(final_shape).translate((-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, z_top - bb.zmin)))
    return f


def _assemble(design: dict, stages: list[dict], offsets: list[float], fp: dict, final_shape, open_state: bool, details: bool = False) -> list[dict]:
    v = stages[0]["values"]
    t = design["thickness_mm"]
    sl_, sw_ = v["die_set_l_mm"], v["die_set_w_mm"]
    shoe, dieb, strp, pun, back = v["shoe_t_mm"], v["die_block_t_mm"], v["stripper_t_mm"], v["punch_plate_t_mm"], v["backing_t_mm"]
    mg = v["margin_mm"] * 0.4
    inner_l, inner_w = sl_ - 2 * mg, sw_ - 2 * mg
    z_die, z_top = shoe, shoe + dieb
    gap = v["open_gap_mm"] if open_state else 0.0
    die = _box(inner_l, inner_w, dieb, z=z_die)
    stripper = _box(inner_l, inner_w, strp, z=z_top + t + gap)
    punches, works = [], []
    plate = _box(inner_l, inner_w, pun, z=z_top + t + strp + gap)
    shoe_cuts = []
    for st, dx in zip(stages, offsets):
        f = _features(design, st, fp, final_shape, z_die, z_top, dx, gap)
        shoe_cuts += f["die"] + f.get("wipe_cut", [])
        for c in f["plate_cut"]:
            plate = plate.cut(c)
            stripper = stripper.cut(c)
        for c in f["die"]:
            die = die.cut(c)
        for c in f["strip"]:
            stripper = stripper.cut(c)
        punches += [(st, p) for p in f["punch"]]
        if f["work"] is not None:
            works.append((st, f["work"]))
    z_pp = z_top + t + strp + gap
    pil = v["pillar_dia_mm"]
    bush_od = pil + 16
    pillars = [(sx * (sl_ / 2 - mg * 0.5), sy * (sw_ / 2 - mg * 0.5)) for sx, sy in [(1, 1), (-1, -1), (1, -1), (-1, 1)][:int(v["pillars"])]]
    lower_shoe, upper_shoe = _box(sl_, sw_, shoe), _box(sl_, sw_, shoe, z=z_pp + pun + back)
    for c in shoe_cuts:                  # openings, slots and wiper relief go on through the lower shoe (slugs, blanks and flanges fall / hang there)
        lower_shoe = lower_shoe.cut(c)
    for px, py in pillars:
        lower_shoe = lower_shoe.cut(cq.Workplane("XY").circle(pil / 2).extrude(shoe * 0.6).translate((px, py, shoe * 0.4)))
        upper_shoe = upper_shoe.cut(cq.Workplane("XY").circle(bush_od / 2).extrude(shoe).translate((px, py, z_pp + pun + back)))
    us_closed = z_top + t + strp + pun + back
    parts = [("Lower shoe", "lower", lower_shoe, (0.55, 0.57, 0.60), "shoe", False),
             ("Die block", "lower", die, (0.20, 0.35, 0.75), "die_block", False),
             ("Stripper plate", "upper", stripper, (0.85, 0.55, 0.15), "stripper", False),
             ("Punch plate", "upper", plate, (0.55, 0.57, 0.60), "punch_plate", False),
             ("Backing plate", "upper", _box(inner_l, inner_w, back, z=z_pp + pun), (0.35, 0.37, 0.40), "backing_plate", False),
             ("Upper shoe", "upper", upper_shoe, (0.55, 0.57, 0.60), "shoe", False)]
    for i, (st, p) in enumerate(punches, start=1):
        parts.append((f"Punch {i} (stage {st['n']})" if len(punches) > 1 else "Punch", "upper", p, (0.80, 0.15, 0.15), "punch", False))
    for i, (px, py) in enumerate(pillars, start=1):
        parts.append((f"Guide pillar {i}", "lower", cq.Workplane("XY").circle(pil / 2).extrude(us_closed + shoe * 0.6 - shoe * 0.4)
                      .translate((px, py, shoe * 0.4)), (0.75, 0.75, 0.78), "guide_pillar", True))
        parts.append((f"Guide bush {i}", "upper", _tube(bush_od, pil + 0.04, shoe, px, py, z_pp + pun + back), (0.70, 0.55, 0.20), "guide_bush", True))
    for st, w in works:
        parts.append((f"Workpiece after {st['name'].lower()}", "work", w, (0.95, 0.80, 0.25), "work", False))
    out = []
    for n, g, w, c, cls, std in parts:
        shp = w.val() if hasattr(w, "val") else w
        try:
            if shp.Volume() > 1e-6:
                out.append({"name": n, "group": g, "shape": shp, "color": c, "cls": cls, "standard": std})
        except Exception:
            pass                                   # an empty result of a boolean: nothing to show
    if details and not open_state:
        from . import tool_internals
        env = {k: float(x) for k, x in stages[0]["values"].items()}
        env |= {k: float(x) for k, x in master_data.parameters("sheet_metal").items() if isinstance(x, (int, float))}
        env["force_t"] = sum(st["force_t"] for st in stages) if design.get("mode") == "progressive" else stages[0]["force_t"]
        env["t"] = t
        vals = tool_internals.values("sheet_metal", env)
        res = tool_internals.die_details(out, {"sl": sl_, "sw": sw_, "bush_od": bush_od, "pillars": pillars}, vals)
        key = "progressive" if design.get("mode") == "progressive" else stages[0]["n"]
        design.setdefault("_details", {})[key] = {"counts": res["counts"], "notes": res["notes"],
                                                   "rules": {k: round(x, 3) for k, x in vals.items() if k in {r["name"] for r in mould_db.tables()["detail_rules"] if r["tool_group"] == "sheet_metal"}}}
    return out


def stage_solids(design: dict, stage: dict, fp: dict, final_shape, open_state: bool = True, details: bool = False) -> list[dict]:
    """Solids of one stage die set: [{name, group: lower|upper|work, shape, color}] (z up, die closed or open)."""
    return _assemble(design, [stage], [0.0], fp, final_shape, open_state, details)


def progressive_solids(design: dict, fp: dict, final_shape, open_state: bool = True, details: bool = False) -> list[dict]:
    """One progressive die set with every station (the stages side by side at the strip pitch)."""
    stages = design["stages"]
    pitch = design.get("pitch_mm") or max(fp["length_mm"], fp["width_mm"]) * 1.1
    offsets = [(i - (len(stages) - 1) / 2) * pitch for i in range(len(stages))]
    return _assemble(design, stages, offsets, fp, final_shape, open_state, details)


# ------------------------------------------------------------ mould concept in 3D

MAX_FACES_FOR_BOOLEAN = 4000
PICTURE_CAVITIES = 8          # pictures show at most this many cavities; a production design has all of them
MAX_PRODUCTION_CAVITIES = 64


def _tube(od: float, idia: float, h: float, x: float, y: float, z: float):
    return cq.Workplane("XY").circle(od / 2).circle(idia / 2).extrude(h).translate((x, y, z))


def mould_3d(shape: cq.Shape, axis: str, parting_z: float, tool: dict, open_gap: float = 60.0, regions: list | None = None,
             production: bool = False, bom: dict | None = None, part_h: float = 0.0, part_area_cm2: float = 0.0) -> dict:
    """3D of a mould / die: plates with pillar and bush holes, guide pillars and bushes, sprue bush, locating ring, and the core and
    cavity inserts cut from the part along the parting plane.

    `shape` is the (corrected) part, `tool` the tool_cost.run result (cavity layout and mould base). With `production` all
    cavities are modelled and the tool is closed (open_gap ignored); plates are thickened where the insert is deeper than the
    catalogue plate. Each component carries `cls` (its class in Component classes) and `standard` (bought-out)."""
    base, layout = tool["base"], tool["layout"]
    z = corrections.to_z(shape, axis)
    bb = z.BoundingBox()
    cx, cy = (bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2
    n = layout["rows"] * layout["cols"] - layout["empty"]
    cavs = min(n, MAX_PRODUCTION_CAVITIES if production else PICTURE_CAVITIES)
    pitch_x, pitch_y = layout["each_l"] + 10, layout["each_w"] + 10
    pos = []
    for r in range(layout["rows"]):
        for c in range(layout["cols"]):
            if len(pos) < cavs:
                pos.append(((c - (layout["cols"] - 1) / 2) * pitch_x, (r - (layout["rows"] - 1) / 2) * pitch_y))
    L, W = base["length_mm"], base["width_mm"]
    a, b_, clamp, support, spacer, ej = (base["a_plate_mm"], base["b_plate_mm"], base["clamp_plates_mm"], base["support_plate_mm"],
                                         base["spacer_block_mm"], base["ejector_plates_mm"])
    pocket_l, pocket_w = layout["pocket_l"], layout["pocket_w"]
    if cavs < n:
        pocket_l, pocket_w = (max(p[0] for p in pos) - min(p[0] for p in pos)) + layout["each_l"], (max(p[1] for p in pos) - min(p[1] for p in pos)) + layout["each_w"]
    top, bot = bb.zmax - parting_z, parting_z - bb.zmin
    h_up, h_dn = top + 15, bot + 15
    notes = []
    if production:
        a_eff, b_eff = max(a, math.ceil(h_up / 5) * 5), max(b_, math.ceil(h_dn / 5) * 5)
        if a_eff > a or b_eff > b_:
            notes.append(f"Plates thickened for the insert depth: A {a:g} → {a_eff:g} mm, B {b_:g} → {b_eff:g} mm (catalogue base {base['size_code']}).")
        a, b_ = a_eff, b_eff
    gap = 0.0 if production else open_gap
    comps = []

    def add(name, group, wp, color, cls, standard=False):
        comps.append({"name": name, "group": group, "shape": wp.val() if hasattr(wp, "val") else wp, "color": color, "cls": cls,
                      "standard": standard})

    pil = max(20.0, round(min(L, W) / 25.0))
    bush_od = pil + 16
    pil_xy = [(sx * (L / 2 - bush_od / 2 - 6), sy * (W / 2 - bush_od / 2 - 6)) for sx, sy in ((1, 1), (-1, -1), (1, -1), (-1, 1))]
    sprue_d, ring_d = 28.0, 100.0
    hot = bool(production and (bom or {}).get("hot_runner"))
    # parting plane at z=0. B side below, A side above.
    bplate = _box(L, W, b_).cut(_box(pocket_l, pocket_w, b_)).translate((0, 0, -b_))
    aplate = _box(L, W, a).cut(_box(pocket_l, pocket_w, a)).translate((0, 0, gap))
    for px, py in pil_xy:
        bplate = bplate.cut(cq.Workplane("XY").circle(pil / 2).extrude(b_ * 0.6).translate((px, py, -b_ * 0.6)))
        aplate = aplate.cut(cq.Workplane("XY").circle(bush_od / 2).extrude(a).translate((px, py, gap)))
    clamp_top = _box(L, W, clamp, z=a + gap).cut(cq.Workplane("XY").circle(sprue_d / 2).extrude(clamp).translate((0, 0, a + gap)))
    add("B plate (core plate)", "lower", bplate, (0.30, 0.45, 0.80), "base_plate")
    add("Support plate", "lower", _box(L, W, support, z=-b_ - support), (0.45, 0.50, 0.58), "support_plate")
    for k, sx in enumerate((-1, 1), start=1):
        add(f"Spacer block {k}", "lower", _box(L * 0.12, W, spacer, x=sx * L * 0.38, z=-b_ - support - spacer), (0.40, 0.42, 0.45), "spacer_block")
    add("Ejector plate", "lower", _box(L * 0.64, W * 0.8, ej, z=-b_ - support - spacer + 5), (0.80, 0.55, 0.15), "ejector_plate")
    add("Bottom clamp plate", "lower", _box(L, W, clamp, z=-b_ - support - spacer - clamp), (0.55, 0.57, 0.60), "clamp_plate")
    add("A plate (cavity plate)", "upper", aplate, (0.30, 0.45, 0.80), "base_plate")
    add("Top clamp plate", "upper", clamp_top, (0.55, 0.57, 0.60), "clamp_plate")
    add("Locating ring", "upper", cq.Workplane("XY").circle(ring_d / 2).circle(sprue_d / 2).extrude(10).translate((0, 0, a + clamp + gap)),
        (0.8, 0.2, 0.2), "locating_ring", True)
    if not hot:
        add("Sprue bush", "upper", cq.Workplane("XY").circle(sprue_d / 2).circle(sprue_d / 2 - 8).extrude(a + clamp).translate((0, 0, gap)),
            (0.8, 0.2, 0.2), "sprue_bush", True)
    for i, (px, py) in enumerate(pil_xy, start=1):
        add(f"Guide pillar {i}", "lower", cq.Workplane("XY").circle(pil / 2).extrude(a * 0.55 + b_ * 0.6).translate((px, py, -b_ * 0.6)),
            (0.78, 0.78, 0.80), "guide_pillar", True)
        add(f"Guide bush {i}", "upper", _tube(bush_od, pil + 0.04, a, px, py, gap), (0.70, 0.55, 0.20), "guide_bush", True)
    # core / cavity inserts cut from the part
    exact = len(z.Faces()) <= MAX_FACES_FOR_BOOLEAN
    placed, gap_solids = None, []
    for i, (px, py) in enumerate(pos, start=1):
        moved = z.translate(cq.Vector(px - cx, py - cy, -parting_z))
        placed = moved if placed is None else placed.fuse(moved)
    note = ""
    ins_up, ins_dn = (a if production else h_up), (b_ if production else h_dn)
    lower_block = _box(pocket_l, pocket_w, ins_dn, z=-ins_dn)
    upper_block = _box(pocket_l, pocket_w, ins_up, z=0)
    try:
        if not exact or placed is None:
            raise ValueError("part has too many faces for the boolean cut")
        # Split by the part's own envelopes along the opening direction (valid where there is no undercut):
        #   A side = everything above the part's UPPER envelope inside its footprint (cores of open shells come from here)
        #            and above the parting plane outside it
        #   B side = everything below the LOWER envelope inside the footprint and below the parting plane outside it
        # Anything left between the envelopes is a window or an undercut: it stays empty and needs a slide or lifter.
        big = (bb.zlen + ins_up + ins_dn) * 2 + 20
        up, dn = sweep(placed, big), sweep(placed, -big)
        if up is None or dn is None:
            raise ValueError("no surface faces the opening direction")
        sil = up.fuse(dn)
        full = _box(pocket_l, pocket_w, ins_up + ins_dn, z=-ins_dn).val()
        a_side = upper_block.val().cut(sil).fuse(full.intersect(sil).cut(dn))
        b_side = lower_block.val().cut(sil).fuse(full.intersect(sil).cut(up))
        if not hot:
            a_side = a_side.cut(cq.Workplane("XY").circle(sprue_d / 2).extrude(a).val())       # the sprue bush passes through the A insert
        for tag, solid, group, color, lift, cls in (("A side insert", a_side, "upper", (0.25, 0.65, 0.35), gap, "insert_a"),
                                                    ("B side insert", b_side, "lower", (0.85, 0.30, 0.25), 0.0, "insert_b")):
            parts = sorted(solid.Solids(), key=lambda x: -x.Volume())
            for k, sd in enumerate(parts):
                if sd.Volume() < 1.0:
                    continue
                add(tag if k == 0 else f"{tag}: island {k}", group, cq.Workplane("XY").add(sd).translate((0, 0, lift)), color, cls)
        gaps = full.intersect(sil).cut(a_side).cut(b_side).cut(placed)
        if not hot:
            gaps = gaps.cut(cq.Workplane("XY").circle(sprue_d / 2).extrude(a).val())
        gap_solids = [x for x in gaps.Solids() if x.Volume() > 1.0]
        if gaps.Volume() > 1.0:
            note = f"Voids between the part's envelopes ({gaps.Volume() / 1000:.1f} cm³) are undercuts or windows: they need slides, lifters or shut-offs."
    except Exception as exc:
        note = f"Insert shapes not cut from the part ({str(exc)[:80]}): plain blocks shown."
        add("B side insert", "lower", lower_block, (0.85, 0.30, 0.25), "insert_b")
        add("A side insert", "upper", upper_block.cut(cq.Workplane("XY").circle(sprue_d / 2).extrude(a)).translate((0, 0, gap)), (0.25, 0.65, 0.35), "insert_a")
    for k, r in enumerate(regions or [], start=1):
        # proposal markers: a slide / lifter block at each undercut region of the concept, on the first cavity
        c = corrections.to_z_point(r["centre_mm"], axis)
        side = max(r["area_mm2"] ** 0.5, 6.0)
        mk = _box(side, side, side, x=c[0] - cx + pos[0][0], y=c[1] - cy + pos[0][1], z=c[2] - parting_z - side / 2).val()
        add(f"{r['kind'].capitalize()} {k} (proposal)", "proposal", mk, (0.55, 0.25, 0.75), "proposal")
    if placed is not None:
        add("Part (corrected)", "part", placed.translate(cq.Vector(0, 0, gap / 2)) if hasattr(placed, "translate") else placed,
            (0.95, 0.80, 0.25), "part")
    if cavs < n:
        notes.append(f"Only {cavs} of {n} cavities are modelled (limit {MAX_PRODUCTION_CAVITIES}); the BOM quantities cover all of them.")
    if note:
        notes.append(note)
    details = None
    if production and placed is not None:
        from . import tool_internals
        b = bom or {}
        env = {"base_l_mm": L, "base_w_mm": W, "plate_a_mm": a, "plate_b_mm": b_, "clamp_mm": clamp, "support_mm": support, "spacer_mm": spacer,
               "ejector_mm": ej, "pocket_l_mm": pocket_l, "pocket_w_mm": pocket_w, "cavities": float(n), "part_h_mm": part_h or bb.zlen,
               "projected_area_cm2": part_area_cm2, "pillar_dia_mm": pil, "bush_od_mm": bush_od, "bom_ejector_pins": b.get("ejector_pins", 0),
               "bom_return_pins": b.get("return_pins", 4), "bom_cooling_connectors": b.get("cooling_connectors", 0),
               "hot_runner": 1.0 if b.get("hot_runner") else 0.0, "slides": b.get("slides", 0), "lifters": b.get("lifters", 0)}
        env |= {k: float(x) for k, x in master_data.parameters(tool.get("part_type", "plastic")).items() if isinstance(x, (int, float))}
        v = tool_internals.values("mould", env)
        ctx = {"L": L, "W": W, "a": a, "b": b_, "pocket_l": pocket_l, "pocket_w": pocket_w, "pil_xy": pil_xy, "bush_od": bush_od, "placed": placed,
               "pos": pos, "sprue_d": sprue_d, "clamp": clamp, "support": support, "ej": ej, "gaps": gap_solids, "regions": regions or [],
               "axis": axis, "cx": cx, "cy": cy, "parting_z": parting_z, "hot": hot, "cavs": cavs}
        details = tool_internals.mould_details(comps, ctx, v)
        notes += details["notes"]
        details["rules"] = {k: round(x, 3) for k, x in v.items() if k in {r["name"] for r in mould_db.tables()["detail_rules"] if r["tool_group"] == "mould"}}
    return {"components": comps, "details": details, "cavities_shown": cavs, "cavities_total": n, "base": base["size_code"],
            "parting_z_mm": parting_z, "note": " ".join(notes), "base_mm": [L, W], "open_gap_mm": gap,
            "plate_a_mm": a, "plate_b_mm": b_, "pillar_dia_mm": pil, "bush_od_mm": bush_od, "sprue_dia_mm": sprue_d}
