"""Sheet-metal tools I (roadmap stage 9): operation sequence, die type, forces, tonnage, press, formability.

    3D model          -> thickness, blank, holes, bends (geometry.sheet_features)
    Sheet metal       -> material strengths and limits (Mould & die database → Sheet materials)
    Sheet operations  -> suggested operation sequence: which operations apply, and the force of each (formulas)
    Sheet rules       -> derived values and the progressive / multi-stage choice (formulas)
    Sheet checks      -> formability checks (bend radius, hole size, draw ratio, springback)
    Machines          -> the smallest press (Parameters → press_machine_process) that takes the tonnage

You can edit the sequence (add / remove operations from the library), the die type and the draw depth / bend radius per
part. Every formula is a master-data row; this is a proposal to check, not a die design.
"""

from __future__ import annotations

import math

from . import costing_setup, formula, master_data, mould_db, register_setup

N_PER_T = 9806.65
FEATURES = {
    "t": "Sheet thickness (mm)", "blank_l": "Blank length (mm)", "blank_w": "Blank width (mm)",
    "blank_perimeter": "Blank perimeter = 2 × (blank_l + blank_w) (mm)", "blank_dia": "Equivalent blank diameter (mm)",
    "hole_count": "Pierced holes", "hole_perimeter": "Total hole perimeter (mm)", "hole_area": "Total hole area (mm²)",
    "min_hole_d": "Smallest hole, equivalent diameter (mm)", "bends": "Bends", "bend_len": "Total bend length (mm)",
    "bend_radius": "Inside bend radius (mm)", "draw_depth": "Draw depth (mm), 0 = not drawn", "draw_dia": "Equivalent punch diameter (mm)",
    "part_l": "Part length (mm)", "part_w": "Part width (mm)", "part_h": "Part height (mm)", "weight_g": "Net part weight (g)",
    "annual_volume": "Annual volume (parts/yr)", "programme_years": "Programme years",
}
MATERIAL_VARS = ("shear_mpa", "tensile_mpa", "yield_mpa", "e_gpa", "min_bend_r_factor", "min_hole_factor", "ldr")


def sample_env() -> dict:
    return ({k: 1.0 for k in FEATURES | {m: 0 for m in MATERIAL_VARS}}
            | {k: float(v) for k, v in master_data.parameters("sheet_metal").items() if isinstance(v, (int, float))})


def _check_formula(text: str, env: dict) -> float:
    try:
        return float(formula.evaluate(text, env))
    except ArithmeticError:
        return 0.0


def validate(clean: dict) -> None:
    """Used by the Mould & die database check: formulas and messages must use known names."""
    env = sample_env()
    for i, r in enumerate(sorted(clean["sheet_rules"], key=lambda r: r["step"]), start=2):
        if not r["name"].isidentifier():
            raise mould_db.MouldDbError(f"Sheet rules '{r['name']}' must be one word (letters, digits and _).")
        try:
            env[r["name"]] = _check_formula(r["formula"], env)
        except formula.FormulaError as exc:
            raise mould_db.MouldDbError(f"Sheet rules ({r['name']}): {exc}") from None
    for i, r in enumerate(clean["sheet_operations"], start=2):
        for c in ("condition", "force_t"):
            try:
                formula.evaluate(r[c], env)
            except formula.FormulaError as exc:
                raise mould_db.MouldDbError(f"Sheet operations row {i}, {c}: {exc}") from None
            except ArithmeticError:
                pass
    for i, r in enumerate(clean["sheet_checks"], start=2):
        try:
            formula.evaluate(r["condition"], env)
            r["message"].format(**env)
        except formula.FormulaError as exc:
            raise mould_db.MouldDbError(f"Sheet checks row {i}, condition: {exc}") from None
        except (KeyError, IndexError, ValueError) as exc:
            raise mould_db.MouldDbError(f"Sheet checks row {i}, message: unknown name {exc} (use {{name}} of a feature, rule or material value).") from None
        except ArithmeticError:
            pass


def features(shape, geometry: dict, blank: dict, typed: dict, density: float, annual_volume, years) -> dict:
    from .geometry import sheet_features
    t = geometry.get("wall_mm") or 1.0
    f = sheet_features(shape, t)
    holes, bends = f["holes"], f["bends"]
    b = geometry["bbox_mm"]
    params = master_data.parameters("sheet_metal")
    radius = typed.get("bend_radius_mm")
    if radius is None:
        radius = min((x["inner_radius_mm"] for x in bends), default=None)
    if radius is None:
        radius = params.get("default_bend_radius_factor", 1.0) * t
    n_bends = max(len(bends), geometry.get("bend_count") or 0)
    bend_len = sum(x["length_mm"] for x in bends) or n_bends * b["width"]
    depth = typed.get("draw_depth_mm")
    if depth is None:
        depth = (b["height"] - t) if (b["height"] > params.get("draw_height_ratio", 5) * t and not n_bends) else 0.0
    foot = b["length"] * b["width"]
    hole_area = sum(h["area_mm2"] for h in holes)
    return {
        "t": t, "blank_l": blank["length"], "blank_w": blank["width"], "blank_perimeter": 2 * (blank["length"] + blank["width"]),
        "blank_dia": math.sqrt(4 * blank["length"] * blank["width"] / math.pi),
        "hole_count": len(holes), "hole_perimeter": sum(h["perimeter_mm"] for h in holes), "hole_area": hole_area,
        "min_hole_d": min((math.sqrt(4 * h["area_mm2"] / math.pi) for h in holes), default=0.0),
        "bends": n_bends, "bend_len": bend_len, "bend_radius": radius, "draw_depth": depth,
        "draw_dia": math.sqrt(4 * foot / math.pi) if depth else 0.0,
        "part_l": b["length"], "part_w": b["width"], "part_h": b["height"],
        "weight_g": geometry["volume_mm3"] / 1000 * density,
        "annual_volume": annual_volume or params.get("annual_volume", 0), "programme_years": years or params.get("programme_years", 0),
        "density": density,
    }


def library() -> list[dict]:
    return sorted(mould_db.tables()["sheet_operations"], key=lambda r: r["seq"])


def press_for(force_t: float) -> dict:
    process = master_data.parameters("sheet_metal").get("press_machine_process")
    ms = [m for m in costing_setup.tables()["machines"] if m["process"] == process]
    fits = sorted((m for m in ms if (m["tonnage_t"] or 0) >= force_t), key=lambda m: m["tonnage_t"])
    if fits:
        return {"machine_id": fits[0]["machine_id"], "name": fits[0]["name"], "tonnage_t": fits[0]["tonnage_t"]}
    return {"machine_id": None, "biggest_t": max((m["tonnage_t"] or 0 for m in ms), default=0), "process": process}


def run(feat: dict, material: str, typed: dict, default_mode: str = "") -> dict:
    mats = {r["material"]: r for r in mould_db.tables()["sheet_materials"]}
    if material not in mats:
        raise ValueError(f"Mould & die database → Sheet materials has no row for '{material or '(no material)'}'. Set the part's material.")
    m = mats[material]
    env = sample_env() | {k: 0.0 for k in FEATURES} | feat | {k: m[k] for k in MATERIAL_VARS}
    steps = []
    for r in sorted(mould_db.tables()["sheet_rules"], key=lambda r: r["step"]):
        env[r["name"]] = _check_formula(r["formula"], env)
        steps.append({"name": r["name"], "label": r["label"], "formula": r["formula"], "unit": r["unit"], "value": env[r["name"]],
                      "is_example": r["is_example"]})
    lib = library()
    codes = {r["code"] for r in lib}
    if typed.get("operations") is not None:
        bad = [c for c in typed["operations"] if c not in codes]
        if bad:
            raise ValueError(f"Operation '{bad[0]}' is not in Sheet operations ({', '.join(sorted(codes))}).")
        chosen = [next(r for r in lib if r["code"] == c) for c in typed["operations"]]
        source = "your sequence"
    else:
        chosen = [r for r in lib if formula.evaluate(r["condition"], env)]
        source = "suggested from the part features and Sheet operations"
    mode = typed.get("mode") or default_mode or ("progressive" if env.get("progressive_ok") else "multi_stage")
    safety = env.get("press_safety_factor", 1.0)
    slug_g = feat["hole_area"] * feat["t"] * feat["density"] / 1000
    weight, ops = feat["weight_g"], []
    for i, r in enumerate(chosen, start=1):
        force = _check_formula(r["force_t"], env)
        stage_g = weight + slug_g if r["code"] == "blank" else weight
        ops.append({"n": i, "code": r["code"], "name": r["name"], "force_t": force, "stage_weight_g": stage_g,
                    "scrap_g": slug_g if r["code"] == "pierce" else 0.0, "force_formula": r["force_t"]})
    if mode == "progressive":
        total = sum(o["force_t"] for o in ops)
        press = {"all stations": press_for(total * safety)}
        design = total * safety
    else:
        for o in ops:
            o["press"] = press_for(o["force_t"] * safety)
        total, design, press = sum(o["force_t"] for o in ops), max((o["force_t"] for o in ops), default=0) * safety, {}
    problems = []
    for r in mould_db.tables()["sheet_checks"]:
        if formula.evaluate(r["condition"], env):
            problems.append({"check": r["name"], "message": r["message"].format(**env), "is_example": r["is_example"]})
    biggest = [x for x in press.values() if not x["machine_id"]] + [o["press"] for o in ops if "press" in o and not o["press"]["machine_id"]]
    for x in biggest:
        problems.append({"check": "press", "message": f"No press takes this tonnage (largest {x['biggest_t']:g} t): split the operations or use a larger press.",
                         "is_example": False})
    return {"material": material, "mode": mode, "recommended": "progressive" if env.get("progressive_ok") else "multi_stage",
            "sequence_source": source, "features": feat, "values": {s["name"]: s["value"] for s in steps}, "steps": steps,
            "operations": ops, "available_operations": [{"code": r["code"], "name": r["name"]} for r in lib],
            "total_force_t": total, "design_force_t": design, "press": press, "problems": problems,
            "safety_factor": safety, "is_example": m["is_example"] or any(s["is_example"] for s in steps),
            "material_values": {k: m[k] for k in MATERIAL_VARS}}
