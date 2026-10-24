"""The machine a tool will run on (roadmap stage 27): typed parameters, a fit check, and a recommendation when nothing is typed.

    typed      per part: tonnage, platen / bolster size, tie-bar clear distance, mould or shut height range, opening stroke, ejector stroke,
               locating ring … (fields per machine family). The tool design is made for that machine: the mould base must pass between the
               tie bars and fit the platen, the closed mould height is brought into the height range (a riser plate is added when the mould is
               too low), the locating ring has the machine's diameter, the press of a sheet-metal die is the typed press.
    skipped    the software works out the machine the finished tool needs (rules `rec_…` in Tool detail rules) and names the closest machine of
               Master data → Machines
    check      every typed parameter against what the finished tool needs: ok / not ok with the numbers, in the design summary and the review
No value is written in the code: margins and recommended values are Tool detail rules (EXAMPLE until you replace them).
"""

from __future__ import annotations

import math

from . import costing_setup, master_data, mould_db, register_setup
from . import projects_db as db

FAMILY = {"plastic": "moulding", "die_casting": "moulding", "eps": "moulding", "blow": "moulding", "sheet_metal": "press", "foundry": "foundry"}
GROUP = {"moulding": "mould", "press": "sheet_metal", "foundry": "foundry"}
FIELDS = {
    "moulding": [("tonnage_t", "Clamp tonnage", "t"), ("platen_l_mm", "Platen length", "mm"), ("platen_w_mm", "Platen width", "mm"),
                 ("tie_bar_h_mm", "Tie-bar clear distance, horizontal", "mm"), ("tie_bar_v_mm", "Tie-bar clear distance, vertical", "mm"),
                 ("min_mould_h_mm", "Smallest mould (shut) height", "mm"), ("max_mould_h_mm", "Largest mould (shut) height", "mm"),
                 ("opening_stroke_mm", "Opening stroke (daylight)", "mm"), ("ejector_stroke_mm", "Ejector stroke", "mm"),
                 ("locating_ring_dia_mm", "Locating ring diameter", "mm"), ("nozzle_radius_mm", "Nozzle / sprue radius SR", "mm")],
    "press": [("tonnage_t", "Press tonnage", "t"), ("bolster_l_mm", "Bolster length (left-right)", "mm"), ("bolster_w_mm", "Bolster width (front-back)", "mm"),
              ("shut_height_min_mm", "Shut height, smallest", "mm"), ("shut_height_max_mm", "Shut height, largest", "mm"),
              ("stroke_mm", "Slide stroke", "mm"), ("cushion_t", "Die cushion force", "t"), ("feed_height_mm", "Feed (pass) line height", "mm")],
    "foundry": [("flask_l_mm", "Flask inside length", "mm"), ("flask_w_mm", "Flask inside width", "mm"), ("cope_h_mm", "Cope height", "mm"), ("drag_h_mm", "Drag height", "mm")],
}
PROCESS_OF = {"plastic": "trial_machine_process", "die_casting": "trial_machine_process", "eps": "trial_machine_process", "blow": "trial_machine_process",
              "sheet_metal": "press_machine_process"}

EXAMPLE = "EXAMPLE - replace with your machine-buying practice"
SEED_RULES = [
    ("mould", "rec_clamp_margin", "1.1", "", "Clamp force margin for the recommended machine"),
    ("mould", "rec_tie_clear_mm", "20", "mm", "Spare room per side between the mould and a tie bar"),
    ("mould", "rec_platen_margin_mm", "30", "mm", "Platen beyond the mould on each side (clamping straps)"),
    ("mould", "rec_height_headroom_pct", "15", "%", "Largest mould height of the recommended machine above the mould"),
    ("mould", "rec_sprue_allow_mm", "80", "mm", "Opening stroke beyond twice the part height (sprue, runner, take-out)"),
    ("mould", "rec_tonnage_t", "ceil(clamp_t * rec_clamp_margin / 10) * 10", "t", "Recommended clamp tonnage"),
    ("mould", "rec_tie_bar_mm", "ceil((min(base_l_mm, base_w_mm) + 2 * rec_tie_clear_mm) / 10) * 10", "mm", "Tie-bar clear distance the mould passes through (smaller side + clearance)"),
    ("mould", "rec_platen_l_mm", "ceil((max(base_l_mm, base_w_mm) + 2 * rec_platen_margin_mm) / 50) * 50", "mm", "Platen length"),
    ("mould", "rec_platen_w_mm", "ceil((min(base_l_mm, base_w_mm) + 2 * rec_platen_margin_mm) / 50) * 50", "mm", "Platen width"),
    ("mould", "rec_min_mould_h_mm", "ceil(mould_h_mm / 5) * 5", "mm", "Smallest mould height the machine must take"),
    ("mould", "rec_max_mould_h_mm", "ceil(mould_h_mm * (1 + rec_height_headroom_pct / 100) / 10) * 10", "mm", "Largest mould height of the machine"),
    ("mould", "rec_opening_stroke_mm", "ceil((2 * part_h_mm + rec_sprue_allow_mm) / 10) * 10", "mm", "Opening stroke (daylight)"),
    ("mould", "rec_ejector_stroke_mm", "ceil((part_h_mm + 10) / 5) * 5", "mm", "Ejector stroke"),
    ("mould", "rec_locating_ring_dia_mm", "100", "mm", "Locating ring diameter"),
    ("sheet_metal", "rec_press_margin", "1.0", "", "Tonnage margin of the recommended press on the design force"),
    ("sheet_metal", "rec_bolster_margin_mm", "100", "mm", "Bolster beyond the die set on each side (clamps, scrap chute)"),
    ("sheet_metal", "rec_shut_adjust_mm", "40", "mm", "Shut-height adjustment range of the recommended press"),
    ("sheet_metal", "rec_tonnage_t", "ceil(force_t * press_safety_factor * rec_press_margin / 10) * 10", "t", "Recommended press tonnage"),
    ("sheet_metal", "rec_bolster_l_mm", "ceil((die_set_l_mm + 2 * rec_bolster_margin_mm) / 50) * 50", "mm", "Bolster length"),
    ("sheet_metal", "rec_bolster_w_mm", "ceil((die_set_w_mm + 2 * rec_bolster_margin_mm) / 50) * 50", "mm", "Bolster width"),
    ("sheet_metal", "rec_shut_height_min_mm", "floor((shut_height_mm - rec_shut_adjust_mm) / 10) * 10", "mm", "Smallest shut height"),
    ("sheet_metal", "rec_shut_height_max_mm", "ceil((shut_height_mm + rec_shut_adjust_mm) / 10) * 10", "mm", "Largest shut height"),
    ("sheet_metal", "rec_stroke_mm", "ceil((2 * max(draw_depth, work_h) + 40) / 10) * 10", "mm", "Slide stroke (twice the work height plus feed clearance)"),
    ("sheet_metal", "rec_cushion_t", "ceil(force_t * 0.3 / 5) * 5 if draw_depth > 0 else 0", "t", "Die cushion force (blank holder) for draw stages"),
    ("foundry", "rec_flask_margin_mm", "0", "mm", "Extra sand room beyond the flask size worked out for the pattern"),
    ("foundry", "rec_flask_l_mm", "ceil((flask_l_mm + rec_flask_margin_mm) / 50) * 50", "mm", "Flask inside length"),
    ("foundry", "rec_flask_w_mm", "ceil((flask_w_mm + rec_flask_margin_mm) / 50) * 50", "mm", "Flask inside width"),
    ("foundry", "rec_cope_h_mm", "ceil((part_h_mm / 2 + 80) / 25) * 25", "mm", "Cope height (half the casting plus sand above)"),
    ("foundry", "rec_drag_h_mm", "ceil((part_h_mm / 2 + 80) / 25) * 25", "mm", "Drag height"),
]
MOULD_ENV_EXTRA = ("clamp_t", "stack_h_mm", "mould_h_mm")
FOUNDRY_ENV_EXTRA = ("flask_l_mm", "flask_w_mm")


def family_of(part_type: str) -> str | None:
    return FAMILY.get(part_type)


def seed() -> int:
    d = mould_db.tables()
    have = {(r["tool_group"], r["name"]) for r in d["detail_rules"]}
    top = max((r["step"] for r in d["detail_rules"]), default=0)
    n = 0
    for g, name, f, unit, label in SEED_RULES:
        if (g, name) not in have:
            n += 1
            d["detail_rules"].append({"tool_group": g, "step": top + n, "name": name, "formula": f, "unit": unit, "label": label, "is_example": 1, "notes": EXAMPLE})
    if n:
        mould_db.write(d)
    return n


# ---------- the typed spec of a part ----------

def schema(part_type: str) -> dict:
    fam = family_of(part_type)
    if not fam:
        raise ValueError(f"'{part_type}' parts have no tool that runs on a machine.")
    return {"family": fam, "fields": [{"key": k, "label": l, "unit": u} for k, l, u in FIELDS[fam]], "machines": catalog(part_type)}


def catalog(part_type: str) -> list[dict]:
    """The machines of Master data → Machines this tool can run on (to prefill the form)."""
    key = PROCESS_OF.get(part_type)
    process = master_data.parameters(part_type).get(key) if key else None
    out = []
    for m in costing_setup.tables()["machines"]:
        if process and m["process"] == process:
            out.append({"machine_id": m["machine_id"], "name": m["name"], "tonnage_t": m["tonnage_t"], "length_mm": m["length_mm"], "width_mm": m["width_mm"]})
    return sorted(out, key=lambda m: m["tonnage_t"] or 0)


def clean(part_type: str, spec: dict | None) -> dict | None:
    """Keep the numbers the form has; empty means 'not typed'."""
    if not spec:
        return None
    fam = family_of(part_type)
    if not fam:
        raise ValueError(f"'{part_type}' parts have no tool that runs on a machine.")
    out = {}
    if spec.get("machine_id"):
        ms = {m["machine_id"] for m in costing_setup.tables()["machines"]}
        if spec["machine_id"] not in ms:
            raise ValueError(f"Machine '{spec['machine_id']}' is not in Master data → Machines.")
        out["machine_id"] = spec["machine_id"]
    for k, label, unit in FIELDS[fam]:
        v = spec.get(k)
        if v in (None, ""):
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{label}: '{v}' is not a number.") from None
        if f < 0 or (f == 0 and k not in ("cushion_t",)):
            raise ValueError(f"{label} must be more than 0.")
        out[k] = f
    lo, hi = out.get("min_mould_h_mm"), out.get("max_mould_h_mm")
    if lo and hi and lo > hi:
        raise ValueError("Smallest mould height is larger than the largest.")
    lo, hi = out.get("shut_height_min_mm"), out.get("shut_height_max_mm")
    if lo and hi and lo > hi:
        raise ValueError("Smallest shut height is larger than the largest.")
    return out or None


def get(part_id: int) -> dict:
    from . import register
    d = register.part_detail(part_id, with_rm=False)
    pt = register_setup.processes().get(d["process"], {}).get("part_type")
    sch = schema(pt)
    return sch | {"part_id": part_id, "part_type": pt, "spec": d.get("machine") or None}


def save(part_id: int, spec: dict | None) -> dict:
    from . import register
    from sqlalchemy import update
    d = register.part_detail(part_id, with_rm=False)
    pt = register_setup.processes().get(d["process"], {}).get("part_type")
    new = clean(pt, spec)
    with db.engine().begin() as conn:
        conn.execute(update(db.parts).where(db.parts.c.id == part_id).values(machine=new))
        register._log(conn, "part", part_id, "machine_set", {"machine": new})
    return get(part_id)


# ---------- constraints for the tool design ----------

def rule_value(group: str, name: str) -> float:
    """A margin rule (rec_tie_clear_mm …) that does not depend on the design."""
    from . import design_skills, tool_internals
    env = tool_internals.env_names(group, mould_db.tables()) | {k: 1.0 for k in MOULD_ENV_EXTRA}
    with design_skills.off():
        return tool_internals.values(group, env)[name]


def base_constraint(spec: dict | None):
    """A function (base row) → bool telling whether the mould base suits the typed machine, or None when nothing limits it."""
    if not spec:
        return None
    tie_clear = rule_value("mould", "rec_tie_clear_mm")
    plat = rule_value("mould", "rec_platen_margin_mm")
    h, v = spec.get("tie_bar_h_mm"), spec.get("tie_bar_v_mm")
    pl, pw = spec.get("platen_l_mm"), spec.get("platen_w_mm")
    hmax = spec.get("max_mould_h_mm")
    if not (h or v or (pl and pw) or hmax):
        return None

    def ok(base: dict) -> bool:
        small, large = sorted((base["length_mm"], base["width_mm"]))
        tie = max(x for x in (h, v) if x) if (h or v) else None
        if tie and small + 2 * tie_clear > tie:
            return False
        if pl and pw:
            ps, pL = sorted((pl, pw))
            if small + 2 * plat > ps or large + 2 * plat > pL:
                return False
        if hmax and base["stack_height_mm"] > hmax:
            return False
        return True
    return ok


# ---------- recommendation and fit ----------

MARGINS = ("rec_clamp_margin", "rec_tie_clear_mm", "rec_platen_margin_mm", "rec_height_headroom_pct", "rec_sprue_allow_mm", "rec_press_margin",
           "rec_bolster_margin_mm", "rec_shut_adjust_mm", "rec_flask_margin_mm")


def recommend(part_type: str, rules: list[dict]) -> dict:
    """Machine parameters the finished tool needs: the `rec_` rule values of the design (one dict per stage for a sheet-metal die: the biggest need wins)."""
    group = GROUP[family_of(part_type)]
    keys = [k for k in rules[0] if k.startswith("rec_") and k not in MARGINS]
    lows = ("rec_shut_height_min_mm",)
    vals = {k: (min(r[k] for r in rules) if k in lows else max(r[k] for r in rules)) for k in keys}
    labels = {r["name"]: (r["label"], r["unit"]) for r in mould_db.tables()["detail_rules"] if r["tool_group"] == group}
    return {"values": {k: round(v, 1) for k, v in vals.items()}, "labels": {k: {"label": labels[k][0], "unit": labels[k][1]} for k in vals if k in labels},
            "margins": {k: rules[0][k] for k in MARGINS if k in rules[0]}}


def nearest_machine(part_type: str, tonnage_t: float) -> dict | None:
    """Smallest catalogue machine of the tool's process that takes the tonnage."""
    ms = catalog(part_type)
    fits = [m for m in ms if (m["tonnage_t"] or 0) >= tonnage_t]
    return fits[0] if fits else None


def _pair(a, b):
    return sorted((a or 0, b or 0))


def check(part_type: str, spec: dict | None, rec: dict, facts: dict) -> list[dict]:
    """Typed machine against what the finished tool needs. facts: mould_h_mm, base_l_mm, base_w_mm / die_set_l_mm, die_set_w_mm, shut_height_mm …"""
    if not spec:
        return []
    fam = family_of(part_type)
    r = rec["values"]
    m = rec["margins"]
    rows = []

    def add(item, need, have, ok, unit="", note=""):
        rows.append({"item": item, "need": need, "have": have, "ok": bool(ok), "unit": unit, "note": note})
    if fam == "moulding":
        if spec.get("tonnage_t"):
            add("Clamp tonnage", facts["clamp_t"], spec["tonnage_t"], spec["tonnage_t"] >= facts["clamp_t"], "t", "clamp force of the tool must be below the machine tonnage")
        tie = [x for x in (spec.get("tie_bar_h_mm"), spec.get("tie_bar_v_mm")) if x]
        if tie:
            need = min(facts["base_l_mm"], facts["base_w_mm"]) + 2 * m["rec_tie_clear_mm"]
            add("Tie-bar clear distance", round(need), max(tie), max(tie) >= need, "mm", "smaller side of the mould base + room each side; the mould passes through the wider gap")
        if spec.get("platen_l_mm") and spec.get("platen_w_mm"):
            ps, pL = _pair(spec["platen_l_mm"], spec["platen_w_mm"])
            ns = min(facts["base_l_mm"], facts["base_w_mm"]) + 2 * m["rec_platen_margin_mm"]
            nL = max(facts["base_l_mm"], facts["base_w_mm"]) + 2 * m["rec_platen_margin_mm"]
            add("Platen size", f"{nL:.0f} × {ns:.0f}", f"{pL:.0f} × {ps:.0f}", ps >= ns and pL >= nL, "mm", "mould base + clamping margin each side")
        h = facts["mould_h_mm"]
        if spec.get("max_mould_h_mm"):
            add("Largest mould height", round(h), spec["max_mould_h_mm"], spec["max_mould_h_mm"] >= h, "mm", "closed mould height of the tool")
        if spec.get("min_mould_h_mm"):
            low = h >= spec["min_mould_h_mm"]
            add("Smallest mould height", round(h), spec["min_mould_h_mm"], low or facts.get("riser_mm", 0) > 0, "mm",
                "" if low else f"the mould is lower than the machine takes: a {facts.get('riser_mm', 0):.0f} mm riser plate is added under the bottom clamp plate")
        if spec.get("opening_stroke_mm"):
            add("Opening stroke", r["rec_opening_stroke_mm"], spec["opening_stroke_mm"], spec["opening_stroke_mm"] >= r["rec_opening_stroke_mm"], "mm", "twice the part height + sprue and take-out room")
        if spec.get("ejector_stroke_mm"):
            add("Ejector stroke", r["rec_ejector_stroke_mm"], spec["ejector_stroke_mm"], spec["ejector_stroke_mm"] >= r["rec_ejector_stroke_mm"], "mm", "part height + 10 mm")
        if spec.get("locating_ring_dia_mm"):
            add("Locating ring", spec["locating_ring_dia_mm"], spec["locating_ring_dia_mm"], True, "mm", "the locating ring of the tool is made to this diameter")
    elif fam == "press":
        if spec.get("tonnage_t"):
            add("Press tonnage", round(facts["design_force_t"], 1), spec["tonnage_t"], spec["tonnage_t"] >= facts["design_force_t"], "t",
                "the biggest stage force with the press safety factor" if not facts.get("progressive") else "total force of all stations with the press safety factor")
        if spec.get("bolster_l_mm") and spec.get("bolster_w_mm"):
            bs, bL = _pair(spec["bolster_l_mm"], spec["bolster_w_mm"])
            ds, dL = _pair(facts["die_set_l_mm"], facts["die_set_w_mm"])
            add("Bolster size", f"{dL:.0f} × {ds:.0f}", f"{bL:.0f} × {bs:.0f}", bs >= ds and bL >= dL, "mm", "die set (largest stage) on the bolster, either way round")
        sh = facts["shut_height_mm"]
        sh_lo = facts.get("shut_height_low_mm", sh)
        if spec.get("shut_height_max_mm"):
            add("Largest shut height", round(sh), spec["shut_height_max_mm"], spec["shut_height_max_mm"] >= sh, "mm", "shut height of the die")
        if spec.get("shut_height_min_mm"):
            low = sh_lo >= spec["shut_height_min_mm"]
            add("Smallest shut height", round(sh_lo), spec["shut_height_min_mm"], low or facts.get("riser_mm", 0) > 0, "mm",
                "" if low else f"the die is lower than the press takes: a {facts.get('riser_mm', 0):.0f} mm riser (parallels) is added under the lower shoe")
        if spec.get("stroke_mm"):
            add("Slide stroke", r["rec_stroke_mm"], spec["stroke_mm"], spec["stroke_mm"] >= r["rec_stroke_mm"], "mm", "twice the work height + feed clearance")
        if spec.get("cushion_t") is not None and r.get("rec_cushion_t"):
            add("Die cushion", r["rec_cushion_t"], spec["cushion_t"], spec["cushion_t"] >= r["rec_cushion_t"], "t", "blank-holder force of the draw stage")
    else:
        if spec.get("flask_l_mm") and spec.get("flask_w_mm"):
            fs, fL = _pair(spec["flask_l_mm"], spec["flask_w_mm"])
            ns, nL = _pair(r["rec_flask_l_mm"], r["rec_flask_w_mm"])
            add("Flask size", f"{nL:.0f} × {ns:.0f}", f"{fL:.0f} × {fs:.0f}", fs >= ns and fL >= nL, "mm", "match plate with gating and the sand wall")
        if spec.get("cope_h_mm"):
            add("Cope height", r["rec_cope_h_mm"], spec["cope_h_mm"], spec["cope_h_mm"] >= r["rec_cope_h_mm"], "mm")
        if spec.get("drag_h_mm"):
            add("Drag height", r["rec_drag_h_mm"], spec["drag_h_mm"], spec["drag_h_mm"] >= r["rec_drag_h_mm"], "mm")
    return rows


def summary(part_type: str, spec: dict | None, rec: dict, facts: dict) -> dict:
    """What goes into the design summary: source, typed spec, recommended, the fit rows and one flag for the review."""
    rows = check(part_type, spec, rec, facts)
    tonnage = rec["values"].get("rec_tonnage_t")
    near = nearest_machine(part_type, tonnage) if tonnage else None
    return {"source": "typed" if spec else "recommended", "spec": spec, "recommended": rec["values"], "labels": rec["labels"], "fit": rows,
            "fit_ok": (1 if all(r["ok"] for r in rows) else 0) if rows else -1, "nearest_machine": near, "note": (
                "The tool was designed for the machine you typed." if spec else
                "No machine was typed: these are the machine parameters the finished tool needs. Buy or choose a machine at least this big, or type your machine and design again.")}
