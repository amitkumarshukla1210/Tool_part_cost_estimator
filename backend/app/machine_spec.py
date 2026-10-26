"""The machine the tool will run on in production (roadmap stage 33): asked before the tool design, checked against it,
or recommended when it is skipped.

    moulding (plastic, die casting, EPS, blow)   clamp tonnage, tie-bar clear distance (H × V), smallest / largest mould height,
                                                 opening stroke, ejector stroke, locating ring diameter
    press (sheet metal)                          tonnage, bolster (L × W), smallest / largest shut height, stroke
    foundry                                      flask (L × W × H)
The values can also be taken from a machine of Master data → Machines (tonnage and platen / bed size). The check compares each tool
of the design (its force from the tool cost, its base / die-set size and its shut height from the 3D tool design) with the machine:
tool needs / machine has / ok, and says what to do (a riser plate when the tool is lower than the machine takes, a bigger machine …).
Skipped: the software gives the machine the tool needs (margins: Design rules rec_*) and the nearest machine of the list.
Nothing here changes the tool cost or the try-out machine of stage 4 / 28.
"""

from __future__ import annotations

from sqlalchemy import select

from . import auth, costing_setup, master_data, mould_db, register_setup
from . import projects_db as db

FAMILY = {"plastic": "moulding", "die_casting": "moulding", "eps": "moulding", "blow": "moulding", "sheet_metal": "press", "foundry": "flask"}
FIELDS = {
    "moulding": [("tonnage_t", "Clamp tonnage (t)"), ("tie_bar_h_mm", "Tie-bar clear distance, horizontal (mm)"),
                 ("tie_bar_v_mm", "Tie-bar clear distance, vertical (mm)"), ("min_height_mm", "Smallest mould height (mm)"),
                 ("max_height_mm", "Largest mould height (mm)"), ("opening_stroke_mm", "Opening stroke (mm)"),
                 ("ejector_stroke_mm", "Ejector stroke (mm)"), ("locating_ring_mm", "Locating ring diameter (mm)")],
    "press": [("tonnage_t", "Press tonnage (t)"), ("bolster_l_mm", "Bolster length (mm)"), ("bolster_w_mm", "Bolster width (mm)"),
              ("min_height_mm", "Smallest shut height (mm)"), ("max_height_mm", "Largest shut height (mm)"), ("stroke_mm", "Stroke (mm)")],
    "flask": [("flask_l_mm", "Flask length (mm)"), ("flask_w_mm", "Flask width (mm)"), ("flask_h_mm", "Flask height, cope + drag (mm)")],
}
RULES = {  # new Design rules rows (part type, parameter): (value, unit, description)
    "rec_tonnage_margin_pct": (15, "%", "Recommended machine: tonnage above the tool's force by this share (stage 33)"),
    "rec_platen_margin_mm": (50, "mm", "Recommended machine: tie-bar / bolster clear distance larger than the tool by this (each side together)"),
    "rec_height_margin_mm": (50, "mm", "Recommended machine: mould / shut height range reaches this far below and above the tool height"),
    "rec_stroke_factor": (2, "-", "Recommended machine: opening (press) stroke = factor × part height + rec_stroke_extra_mm"),
    "rec_stroke_extra_mm": (50, "mm", "Recommended machine: extra stroke for removing the part"),
}


def family(part_type: str) -> str | None:
    return FAMILY.get(part_type or "")


def seed() -> int:
    """Add the rec_* Design rules rows that are missing (existing rows are never changed)."""
    d = mould_db.tables()
    types = sorted({r["part_type"] for r in d["design_rules"]})
    have = {(r["part_type"], r["parameter"]) for r in d["design_rules"]}
    add = [{"part_type": pt, "parameter": k, "value": v, "text": "", "unit": u, "description": desc, "is_example": True}
           for pt in types for k, (v, u, desc) in RULES.items() if (pt, k) not in have]
    if add:
        d["design_rules"] += add
        mould_db.write(d)
    return len(add)


def _rule(part_type: str, key: str) -> float:
    r = mould_db.design_rules(part_type).get(key)
    return float(r["value"]) if r and r["value"] is not None else float(RULES[key][0])


def _part(part_id: int) -> tuple[dict, str]:
    from . import register
    d = register.part_detail(part_id, with_rm=False)
    pt = (register_setup.processes().get(d["process"]) or {}).get("part_type") or ""
    return d, pt


def catalog(part_type: str) -> list[dict]:
    """Machines of Master data → Machines for this part type (the try-out process): id, name, tonnage, platen / bed."""
    process = master_data.parameters(part_type).get("trial_machine_process") if part_type else None
    return [{"machine_id": m["machine_id"], "name": m["name"], "tonnage_t": m["tonnage_t"], "length_mm": m["length_mm"], "width_mm": m["width_mm"]}
            for m in costing_setup.tables()["machines"] if process and m["process"] == process]


def get(part_id: int) -> dict:
    d, pt = _part(part_id)
    fam = family(pt)
    if not fam:
        raise auth.AuthError(f"Process {d['process']} has no tool machine (moulding, die casting, sheet metal, EPS, blow moulding, foundry).", 400)
    with db.engine().connect() as conn:
        m = conn.execute(select(db.parts.c.machine).where(db.parts.c.id == part_id)).scalar() or {}
    return {"part_id": part_id, "part_type": pt, "family": fam, "fields": [{"key": k, "label": lab} for k, lab in FIELDS[fam]],
            "catalog": catalog(pt), "spec": m.get("spec"), "skipped": bool(m.get("skipped")), "asked": bool(m)}


def save(part_id: int, spec: dict | None, skipped: bool = False) -> dict:
    """spec: {field: number, machine_id?}; None + skipped = 'design without a machine, recommend one'."""
    d, pt = _part(part_id)
    fam = family(pt)
    if not fam:
        raise auth.AuthError("This part's process has no tool machine.", 400)
    clean = None
    if spec:
        clean = {}
        keys = dict(FIELDS[fam])
        for k, v in spec.items():
            if k == "machine_id":
                if v and v not in {m["machine_id"] for m in catalog(pt)}:
                    raise auth.AuthError(f"Machine '{v}' is not a {pt.replace('_', ' ')} machine of Master data → Machines.", 400)
                if v:
                    clean[k] = v
                continue
            if k not in keys:
                continue
            if v in (None, ""):
                continue
            try:
                n = float(v)
            except (TypeError, ValueError):
                raise auth.AuthError(f"{keys[k]}: '{v}' is not a number.", 400) from None
            if n <= 0:
                raise auth.AuthError(f"{keys[k]} must be more than 0.", 400)
            clean[k] = n
        if clean.get("min_height_mm") and clean.get("max_height_mm") and clean["min_height_mm"] > clean["max_height_mm"]:
            raise auth.AuthError("The smallest height is above the largest height.", 400)
        if "machine_id" in clean:                         # fill what the list knows
            m = next(x for x in catalog(pt) if x["machine_id"] == clean["machine_id"])
            clean.setdefault("tonnage_t", float(m["tonnage_t"] or 0) or None)
            a, b = ("tie_bar_h_mm", "tie_bar_v_mm") if fam == "moulding" else ("bolster_l_mm", "bolster_w_mm")
            if fam != "flask" and m["length_mm"]:
                clean.setdefault(a, float(m["length_mm"]))
                clean.setdefault(b, float(m["width_mm"]))
            clean = {k: v for k, v in clean.items() if v is not None}
    value = {"spec": clean, "skipped": bool(skipped) and not clean}
    with db.engine().begin() as conn:
        conn.execute(db.parts.update().where(db.parts.c.id == part_id).values(machine=value))
        auth.log(conn, "part", part_id, "machine_set", value)
    return get(part_id)


# ---------- needs of the tool, check, recommendation ----------

def needs(part_id: int, designs: list | None = None, rev: dict | None = None) -> list[dict]:
    """Per tool: force (t), tool length × width (base / die set), height (shut / mould height), part height."""
    from . import register
    tr = register.tool_trace(part_id)
    if designs is None:
        _, rev, designs = register.tool_designs(part_id)
    bb = ((rev.get("geometry") or {}).get("bbox_mm") or {})
    part_h = float(bb.get("height") or 0)
    out = []
    dies = {x["key"]: x for x in tr.get("dies") or []}
    for k, des in designs:
        src = dies.get(des["key"]) or {}
        base = src.get("base") or tr.get("base") or {}
        force = src.get("force_t") if src else (tr.get("trial") or {}).get("force_t")
        out.append({"stage": k, "key": des["key"], "name": des["name"], "force_t": round(float(force or 0), 1),
                    "length_mm": float(base.get("length_mm") or 0), "width_mm": float(base.get("width_mm") or 0),
                    "height_mm": float(des.get("shut_height") or 0), "part_height_mm": part_h})
    return out


def recommend(part_type: str, tools: list[dict]) -> dict:
    """The machine every tool of the part needs, with the margins of the Design rules."""
    fam = family(part_type)
    m = lambda k: _rule(part_type, k)
    force = max((t["force_t"] for t in tools), default=0)
    L = max((max(t["length_mm"], t["width_mm"]) for t in tools), default=0)
    W = max((min(t["length_mm"], t["width_mm"]) for t in tools), default=0)
    hmin = min((t["height_mm"] for t in tools if t["height_mm"]), default=0)
    hmax = max((t["height_mm"] for t in tools), default=0)
    ph = max((t["part_height_mm"] for t in tools), default=0)
    stroke = round(m("rec_stroke_factor") * ph + m("rec_stroke_extra_mm"))
    if fam == "moulding":
        rec = {"tonnage_t": round(force * (1 + m("rec_tonnage_margin_pct") / 100), 1), "tie_bar_h_mm": round(L + m("rec_platen_margin_mm")),
               "tie_bar_v_mm": round(W + m("rec_platen_margin_mm")), "min_height_mm": max(round(hmin - m("rec_height_margin_mm")), 0),
               "max_height_mm": round(hmax + m("rec_height_margin_mm")), "opening_stroke_mm": stroke, "ejector_stroke_mm": round(ph + 10)}
    elif fam == "press":
        rec = {"tonnage_t": round(force * (1 + m("rec_tonnage_margin_pct") / 100), 1), "bolster_l_mm": round(L + m("rec_platen_margin_mm")),
               "bolster_w_mm": round(W + m("rec_platen_margin_mm")), "min_height_mm": max(round(hmin - m("rec_height_margin_mm")), 0),
               "max_height_mm": round(hmax + m("rec_height_margin_mm")), "stroke_mm": stroke}
    else:
        rec = {"flask_l_mm": round(L + m("rec_platen_margin_mm")), "flask_w_mm": round(W + m("rec_platen_margin_mm")),
               "flask_h_mm": round(hmax + m("rec_height_margin_mm"))}
    near = None
    if fam != "flask":
        a, b = (rec.get("tie_bar_h_mm") or rec.get("bolster_l_mm")), (rec.get("tie_bar_v_mm") or rec.get("bolster_w_mm"))
        ok = [x for x in catalog(part_type) if (x["tonnage_t"] or 0) >= rec["tonnage_t"]
              and (not x["length_mm"] or (max(x["length_mm"], x["width_mm"]) >= a and min(x["length_mm"], x["width_mm"]) >= b))]
        near = min(ok, key=lambda x: x["tonnage_t"]) if ok else None
    return {"values": rec, "nearest": near, "is_example": True}


def check(part_type: str, spec: dict, tools: list[dict]) -> list[dict]:
    """[{tool, what, needs, has, ok, advice}] for every tool against the typed machine (a value not typed is not checked)."""
    fam = family(part_type)
    rows = []

    def row(t, what, need, has, ok, advice=""):
        rows.append({"tool": t["name"], "what": what, "needs": need, "has": has, "ok": ok, "advice": advice if not ok else ""})
    for t in tools:
        L, W = max(t["length_mm"], t["width_mm"]), min(t["length_mm"], t["width_mm"])
        if spec.get("tonnage_t") and t["force_t"]:
            row(t, "Tonnage", f"{t['force_t']:g} t", f"{spec['tonnage_t']:g} t", spec["tonnage_t"] >= t["force_t"], "Use a bigger machine or fewer cavities.")
        a, b = ("tie_bar_h_mm", "tie_bar_v_mm") if fam == "moulding" else ("bolster_l_mm", "bolster_w_mm") if fam == "press" else ("flask_l_mm", "flask_w_mm")
        if spec.get(a) and spec.get(b) and L:
            ma, mb = max(spec[a], spec[b]), min(spec[a], spec[b])
            row(t, "Tie bars / bolster" if fam != "flask" else "Flask", f"{L:g} × {W:g} mm", f"{spec[a]:g} × {spec[b]:g} mm",
                L <= ma and W <= mb, "The tool does not pass between the tie bars / fit the bolster: a bigger machine, or a smaller base (fewer cavities).")
        if fam != "flask" and t["height_mm"]:
            if spec.get("min_height_mm"):
                ok = t["height_mm"] >= spec["min_height_mm"]
                row(t, "Smallest height", f"{t['height_mm']:g} mm", f"≥ {spec['min_height_mm']:g} mm", ok,
                    f"Add a riser / parallel of {spec['min_height_mm'] - t['height_mm']:g} mm (or thicker clamp plates).")
            if spec.get("max_height_mm"):
                row(t, "Largest height", f"{t['height_mm']:g} mm", f"≤ {spec['max_height_mm']:g} mm", t["height_mm"] <= spec["max_height_mm"],
                    "The tool is too high for the machine: thinner plates / spacers, or a bigger machine.")
        if fam == "flask" and spec.get("flask_h_mm") and t["height_mm"]:
            row(t, "Flask height", f"{t['height_mm']:g} mm", f"{spec['flask_h_mm']:g} mm", t["height_mm"] <= spec["flask_h_mm"], "A higher flask.")
        stroke_key = "opening_stroke_mm" if fam == "moulding" else "stroke_mm"
        if spec.get(stroke_key) and t["part_height_mm"]:
            need = round(_rule(part_type, "rec_stroke_factor") * t["part_height_mm"] + _rule(part_type, "rec_stroke_extra_mm"))
            row(t, "Stroke", f"{need:g} mm", f"{spec[stroke_key]:g} mm", spec[stroke_key] >= need, "A machine with a longer stroke.")
        if fam == "moulding" and spec.get("ejector_stroke_mm") and t["part_height_mm"]:
            need = round(t["part_height_mm"] + 10)
            row(t, "Ejector stroke", f"{need:g} mm", f"{spec['ejector_stroke_mm']:g} mm", spec["ejector_stroke_mm"] >= need, "A longer ejector stroke.")
    return rows


def evaluate(part_id: int, designs: list | None = None, rev: dict | None = None) -> dict:
    """What the Machine block of the tool design shows: typed spec checked, or the recommendation."""
    info = get(part_id)
    tools = needs(part_id, designs, rev)
    rec = recommend(info["part_type"], tools)
    spec = info["spec"] or {}
    rows = check(info["part_type"], spec, tools) if spec else []
    bad = [r for r in rows if not r["ok"]]
    if spec:
        note = ("Machine check: the tool(s) fit the typed machine." if not bad else
                f"Machine check: {len(bad)} point(s) do not fit the typed machine: " + "; ".join(f"{r['tool']} {r['what'].lower()} ({r['advice']})" for r in bad[:3]))
    else:
        v = rec["values"]
        note = ("No machine typed: the tool needs " + ", ".join(f"{dict(FIELDS[info['family']])[k].split(' (')[0].lower()} {v[k]:g}" for k in v)
                + (f"; nearest in Master data → Machines: {rec['nearest']['machine_id']}." if rec["nearest"] else "; no machine of the list takes it."))
    return info | {"tools": tools, "recommended": rec, "check": rows, "fits": bool(spec) and not bad, "note": note}


def note_for(part_id: int, designs: list, rev: dict) -> str | None:
    """One line for the notes of the tool design (assembly drawing, release pack), or None (no machine family, no data)."""
    try:
        return evaluate(part_id, designs, rev)["note"]
    except Exception:                    # the drawing must never fail because of the machine check
        return None
