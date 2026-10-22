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
            "stages": out_stages, "die_sets": sets, "warnings": warnings, "total_force_t": round(total_force, 1),
            "tool_weight_kg": round(total_weight, 1),
            "steel_cost": round(sum(s["steel_cost"] for s in (out_stages[:1] if progressive else out_stages))),
            "currency": rates.lookup("tool_material", DIE_STEEL, country, month)["currency"] if _steel(DIE_STEEL, country, month)[1] else "",
            "is_example": any(s["is_example"] for s in out_stages) or res["is_example"],
            "note": "Concept tool design: sizes follow the Stage tool rules; draw and bend forming surfaces are concept blocks. "
                    "Steel cost only (machining, heat treatment, design and try-out come with the sheet-metal tool cost stage)."}


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
    f = {"die": [], "strip": [], "punch": [], "work": None}
    sh = lambda wp: wp.translate((dx, 0, 0))
    code = stage["code"]
    if code in ("blank", "trim"):
        f["die"].append(sh(_prism(_offset(outline, clr), dieb, z_die)))
        f["strip"].append(sh(_prism(_offset(outline, clr * 0.5), strp, z_top + t + gap)))
        f["punch"].append(sh(_prism(outline, strp + t + 5 + gap, z_top - 5)))
        f["work"] = sh(_prism(outline, t, z_top - (t if code == "blank" else 0)))
    elif code == "pierce":
        work = _prism(outline, t, z_top)
        for h in holes:
            f["die"].append(sh(_prism(_offset(h, clr), dieb, z_die)))
            f["strip"].append(sh(_prism(h, strp, z_top + t + gap)))
            f["punch"].append(sh(_prism(h, strp + t + 5 + gap, z_top - 5)))
            work = work.cut(_prism(h, t, z_top))
        f["work"] = sh(work)
    elif code == "draw":
        d_out = stage["workpiece"]["cup_dia_mm"] or max(fp["length_mm"], fp["width_mm"])
        h_cup = stage["workpiece"]["cup_height_mm"] or 10.0
        bore = d_out + 2 * (v.get("draw_clearance_mm", t) - t)
        f["die"].append(sh(cq.Workplane("XY").circle(bore / 2).extrude(dieb).translate((0, 0, z_die))))
        f["strip"].append(sh(cq.Workplane("XY").circle(bore / 2 - t).extrude(strp).translate((0, 0, z_top + t + gap))))
        f["punch"].append(sh(cq.Workplane("XY").circle(bore / 2 - t).extrude(strp + h_cup + gap).translate((0, 0, z_top + t - h_cup))))
        f["work"] = sh(cq.Workplane("XY").circle(d_out / 2).circle(d_out / 2 - t).extrude(h_cup)
                       .union(cq.Workplane("XY").circle(d_out / 2).extrude(t)).translate((0, 0, z_top - h_cup)))
    elif code == "bend":
        vo = v.get("v_opening_mm", 8 * t)
        L = max(fp["length_mm"], fp["width_mm"])
        f["die"].append(sh(cq.Workplane("XZ").polyline([(-vo / 2, z_top), (vo / 2, z_top), (0, z_top - vo / 2)]).close().extrude(L / 2, both=True)))
        f["punch"].append(sh(cq.Workplane("XZ").polyline([(-vo / 3, z_top + t + strp + gap), (vo / 3, z_top + t + strp + gap),
                                                          (0, z_top + t - vo / 3 + gap)]).close().extrude(L / 2, both=True)))
        if final_shape is not None:
            bb = final_shape.BoundingBox()
            f["work"] = sh(cq.Workplane("XY").add(final_shape).translate((-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, z_top - bb.zmin)))
    return f


def _assemble(design: dict, stages: list[dict], offsets: list[float], fp: dict, final_shape, open_state: bool) -> list[dict]:
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
    for st, dx in zip(stages, offsets):
        f = _features(design, st, fp, final_shape, z_die, z_top, dx, gap)
        for c in f["die"]:
            die = die.cut(c)
        for c in f["strip"]:
            stripper = stripper.cut(c)
        punches += [(st, p) for p in f["punch"]]
        if f["work"] is not None:
            works.append((st, f["work"]))
    z_pp = z_top + t + strp + gap
    parts = [("Lower shoe", "lower", _box(sl_, sw_, shoe), (0.55, 0.57, 0.60)),
             ("Die block", "lower", die, (0.20, 0.35, 0.75)),
             ("Stripper plate", "upper", stripper, (0.85, 0.55, 0.15)),
             ("Punch plate", "upper", _box(inner_l, inner_w, pun, z=z_pp), (0.55, 0.57, 0.60)),
             ("Backing plate", "upper", _box(inner_l * 0.8, inner_w * 0.8, back, z=z_pp + pun), (0.35, 0.37, 0.40)),
             ("Upper shoe", "upper", _box(sl_, sw_, shoe, z=z_pp + pun + back), (0.55, 0.57, 0.60))]
    for i, (st, p) in enumerate(punches, start=1):
        parts.append((f"Punch {i} (stage {st['n']})" if len(punches) > 1 else "Punch", "upper", p, (0.80, 0.15, 0.15)))
    pil = v["pillar_dia_mm"]
    for i, (sx, sy) in enumerate([(1, 1), (-1, -1), (1, -1), (-1, 1)][:int(v["pillars"])], start=1):
        parts.append((f"Guide pillar {i}", "lower", cq.Workplane("XY").circle(pil / 2).extrude(v["shut_height_mm"] - shoe)
                      .translate((sx * (sl_ / 2 - mg * 0.5), sy * (sw_ / 2 - mg * 0.5), shoe)), (0.75, 0.75, 0.78)))
    for st, w in works:
        parts.append((f"Workpiece after {st['name'].lower()}", "work", w, (0.95, 0.80, 0.25)))
    return [{"name": n, "group": g, "shape": (w.val() if hasattr(w, "val") else w), "color": c} for n, g, w, c in parts]


def stage_solids(design: dict, stage: dict, fp: dict, final_shape, open_state: bool = True) -> list[dict]:
    """Solids of one stage die set: [{name, group: lower|upper|work, shape, color}] (z up, die closed or open)."""
    return _assemble(design, [stage], [0.0], fp, final_shape, open_state)


def progressive_solids(design: dict, fp: dict, final_shape, open_state: bool = True) -> list[dict]:
    """One progressive die set with every station (the stages side by side at the strip pitch)."""
    stages = design["stages"]
    pitch = design.get("pitch_mm") or max(fp["length_mm"], fp["width_mm"]) * 1.1
    offsets = [(i - (len(stages) - 1) / 2) * pitch for i in range(len(stages))]
    return _assemble(design, stages, offsets, fp, final_shape, open_state)


# ------------------------------------------------------------ mould concept in 3D

MAX_FACES_FOR_BOOLEAN = 4000


def mould_3d(shape: cq.Shape, axis: str, parting_z: float, tool: dict, open_gap: float = 60.0) -> dict:
    """Concept 3D of a mould / die: plates, pillars, core and cavity inserts cut from the part along the parting plane.

    `shape` is the (corrected) part, `tool` the tool_cost.run result (cavity layout and mould base). Returns components."""
    base, layout = tool["base"], tool["layout"]
    z = corrections.to_z(shape, axis)
    bb = z.BoundingBox()
    cx, cy = (bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2
    n = layout["rows"] * layout["cols"] - layout["empty"]
    cavs = min(n, 8)                                  # the picture shows at most 8 cavities; the BOM has them all
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
    comps = []

    def add(name, group, wp, color):
        comps.append({"name": name, "group": group, "shape": wp.val() if hasattr(wp, "val") else wp, "color": color})

    gap = open_gap
    # parting plane at z=0. B side below, A side above.
    z_b_top = 0.0
    add("B plate (core plate)", "lower", _box(L, W, b_).cut(_box(pocket_l, pocket_w, b_)).translate((0, 0, -b_)), (0.30, 0.45, 0.80))
    add("Support plate", "lower", _box(L, W, support, z=-b_ - support), (0.45, 0.50, 0.58))
    add("Spacer blocks", "lower", _box(L * 0.12, W, spacer, x=-L * 0.38, z=-b_ - support - spacer).union(
        _box(L * 0.12, W, spacer, x=L * 0.38, z=-b_ - support - spacer)), (0.40, 0.42, 0.45))
    add("Ejector plates", "lower", _box(L * 0.64, W * 0.8, ej, z=-b_ - support - spacer + 5), (0.80, 0.55, 0.15))
    add("Bottom clamp plate", "lower", _box(L, W, clamp, z=-b_ - support - spacer - clamp), (0.55, 0.57, 0.60))
    add("A plate (cavity plate)", "upper", _box(L, W, a).cut(_box(pocket_l, pocket_w, a)).translate((0, 0, gap)), (0.30, 0.45, 0.80))
    add("Top clamp plate", "upper", _box(L, W, clamp, z=a + gap), (0.55, 0.57, 0.60))
    add("Locating ring", "upper", cq.Workplane("XY").circle(50).extrude(10).translate((0, 0, a + clamp + gap)), (0.8, 0.2, 0.2))
    add("Sprue bush", "upper", cq.Workplane("XY").circle(14).extrude(a + clamp).translate((0, 0, gap)), (0.8, 0.2, 0.2))
    pil = max(20.0, round(min(L, W) / 25.0))
    for i, (sx, sy) in enumerate([(1, 1), (-1, -1), (1, -1), (-1, 1)], start=1):
        add(f"Guide pillar {i}", "lower",
            cq.Workplane("XY").circle(pil / 2).extrude(a + b_ * 0.6).translate((sx * (L / 2 - pil * 1.3), sy * (W / 2 - pil * 1.3), -b_ * 0.6)),
            (0.78, 0.78, 0.80))
    # core / cavity inserts cut from the part
    top, bot = bb.zmax - parting_z, parting_z - bb.zmin
    h_up, h_dn = top + 15, bot + 15
    exact = len(z.Faces()) <= MAX_FACES_FOR_BOOLEAN
    placed = None
    for i, (px, py) in enumerate(pos, start=1):
        moved = z.translate(cq.Vector(px - cx, py - cy, -parting_z))
        placed = moved if placed is None else placed.fuse(moved)
    note = ""
    lower_block = _box(pocket_l, pocket_w, h_dn, z=-h_dn)
    upper_block = _box(pocket_l, pocket_w, h_up, z=0)
    try:
        if not exact or placed is None:
            raise ValueError("part has too many faces for the boolean cut")
        low = lower_block.cut(placed)
        up = upper_block.cut(placed)
        low_solids = sorted(low.val().Solids(), key=lambda s: -s.Volume())
        up_solids = sorted(up.val().Solids(), key=lambda s: -s.Volume())
        add("Core insert (B side)", "lower", cq.Workplane("XY").add(low_solids[0]), (0.85, 0.30, 0.25))
        for k, s in enumerate(low_solids[1:], start=1):
            add(f"Core pin / island {k}", "upper", cq.Workplane("XY").add(s).translate((0, 0, gap)), (0.85, 0.30, 0.25))
        add("Cavity insert (A side)", "upper", cq.Workplane("XY").add(up_solids[0]).translate((0, 0, gap)), (0.25, 0.65, 0.35))
        for k, s in enumerate(up_solids[1:], start=1):
            add(f"Cavity island {k}", "upper", cq.Workplane("XY").add(s).translate((0, 0, gap)), (0.25, 0.65, 0.35))
    except Exception as exc:
        note = f"Insert shapes not cut from the part ({str(exc)[:80]}): plain blocks shown."
        add("Core insert (B side)", "lower", lower_block, (0.85, 0.30, 0.25))
        add("Cavity insert (A side)", "upper", upper_block.translate((0, 0, gap)), (0.25, 0.65, 0.35))
    if placed is not None:
        add("Part (corrected)", "part", placed.translate(cq.Vector(0, 0, gap / 2)) if hasattr(placed, "translate") else placed, (0.95, 0.80, 0.25))
    return {"components": comps, "cavities_shown": cavs, "cavities_total": n, "base": base["size_code"],
            "parting_z_mm": parting_z, "note": note, "base_mm": [L, W], "open_gap_mm": gap}
