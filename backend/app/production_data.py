"""Supplier production data of a tool design (roadmap stage 45): per made tool part what a supplier needs to buy the steel and quote.

    stock       finished size + 2 × stock_allowance_mm on every side, rounded up to stock_round_mm (Mould & die database →
                Design rules, per part type, EXAMPLE); weight = stock volume × density of the part's steel (Tool materials)
    operations  from the part's own features: saw cut and square the block, drill / ream / tap / counterbore by hole kind,
                deep-hole drilling of cooling lines, pocket or wire-cut openings, heat treatment and grinding when hardened,
                surface treatment from the drawing data
    cost        a split of the tool cost (same lines, same approved rates), so the parts add up exactly to the tool cost:
                  steel     a made BOM line (e.g. "Cavity insert (steel)") goes to the tool parts of that name, shared by stock weight;
                            the mould base / die set line goes to the made parts no other line covers (the plates), by stock weight
                  machining the process lines of the cost groups in *production_cost_groups* (Parameters, e.g. cutting, machining,
                            polishing, treatment) shared over all made parts by stock weight
                  standard  bought-out lines, listed as standard parts
                  tool      everything else (design, fitting, try-out, overhead, profit, packing, transport, warranty) stays at tool level
All money in INR (the tool cost's currency × its exchange rate).
"""

from __future__ import annotations

import io
import math

from . import mould_db

EXAMPLE = "EXAMPLE - replace with your toolroom's stock allowance and size steps"
SEED = (("stock_allowance_mm", 3.0, "mm", "Production data: stock allowance on every side of a made tool part (finished size + 2 × this)"),
        ("stock_round_mm", 5.0, "mm", "Production data: stock sizes rounded up to this step"),
        ("production_cost_groups", None, "", "Production data: tool-cost groups shared over the made parts by stock weight (comma separated)"))
GROUPS_TEXT = "cutting, machining, polishing, treatment"
PART_TYPES = ("plastic", "die_casting", "foundry", "eps", "blow", "sheet_metal")


class ProductionError(ValueError):
    pass


def seed() -> int:
    """Add the Design rules rows of the production data that are missing (existing rows are never changed)."""
    d = mould_db.tables()
    have = {(r["part_type"], r["parameter"]) for r in d["design_rules"]}
    new = []
    for pt in PART_TYPES:
        for name, value, unit, desc in SEED:
            if (pt, name) not in have:
                new.append({"part_type": pt, "parameter": name, "value": value, "text": GROUPS_TEXT if value is None else "",
                            "unit": unit, "description": desc, "is_example": True})
    if new:
        d["design_rules"] += new
        mould_db.write(d)
    return len(new)


def _rules(part_type: str) -> dict:
    r = mould_db.design_rules(part_type)
    missing = [k for k, *_ in SEED if k not in r]
    if missing:
        raise ProductionError(f"Mould & die database → Design rules has no {', '.join(missing)} for '{part_type}'.")
    groups = [g.strip() for g in str(r["production_cost_groups"].get("text") or "").split(",") if g.strip()]
    return {"allow": float(r["stock_allowance_mm"]["value"] or 0), "step": float(r["stock_round_mm"]["value"] or 0), "groups": groups,
            "is_example": any(bool(r[k].get("is_example")) for k, *_ in SEED)}


def _stock(size, allow: float, step: float) -> list[float]:
    out = []
    for v in size:
        s = v + 2 * allow
        out.append(round(math.ceil(s / step - 1e-9) * step, 1) if step > 0 else round(s, 1))
    return out


def operations(c) -> list[str]:
    """What the toolmaker has to do on this part, from its own features (hole kinds, openings, hardness, drawing data)."""
    ops = ["Saw cut the stock", "Mill six faces square to size"]
    kinds = {}
    for h in c.holes or []:
        kinds[h.get("kind", "thru")] = kinds.get(h.get("kind", "thru"), 0) + 1
    names = {"thru": "Drill through holes", "fit": "Drill and ream fitted holes", "tap": "Drill and tap threaded holes",
             "cbore": "Drill and counterbore screw holes", "cooling": "Deep-hole drill cooling lines"}
    ops += [f"{names.get(k, 'Drill holes (' + k + ')')} × {n}" for k, n in sorted(kinds.items())]
    if c.openings:
        ops.append(f"Machine openings / pockets × {len(c.openings)} (CNC or wire cut)")
    if "insert" in c.name.lower() or c.drawing == "solid":
        ops.append("CNC / EDM the moulding or forming faces from the 3D model")
    hard = (c.hardness or "").lower()
    if "hrc" in hard and "pre" not in hard:
        ops += [f"Heat treatment to {c.hardness}", "Grind faces and fits after hardening"]
    tech = getattr(c, "tech", None) or {}
    st = str(tech.get("surface_treatment") or "").strip()
    if st and st.lower() not in ("none", "-"):
        ops.append(f"Surface treatment: {st}")
    ht = str(tech.get("heat_treatment") or "").strip()
    if ht and "hrc" not in hard and ht.lower() not in ("none", "none (as supplied)", "-"):
        ops.append(f"Heat treatment: {ht}")
    return ops


def _base_name(element: str) -> str:
    return element.split(" (")[0].strip().lower()


def tool_data(des: dict, lines: list[dict], value: float, fx: float, part_type: str) -> dict:
    """One tool: every made part with stock, weight, operations and its share of the tool cost; standard parts; tool-level rest."""
    R = _rules(part_type)
    dens = {m["code"]: float(m["density_g_cm3"] or 0) for m in mould_db.tables()["tool_materials"]}
    made = [c for c in des["components"] if c.kind == "made"]
    parts = []
    for c in made:
        st = _stock(c.size, R["allow"], R["step"])
        d = dens.get(c.material)
        kg = st[0] * st[1] * st[2] / 1e6 * d if d else None
        parts.append({"item": c.no, "name": c.name, "qty": c.qty, "material": c.material or "-", "hardness": c.hardness or "-",
                      "finished_mm": [round(v, 1) for v in c.size], "stock_mm": st, "kg_each": round(kg, 3) if kg else None,
                      "kg_total": round(kg * c.qty, 3) if kg else None, "density": d, "operations": operations(c),
                      "steel_inr": 0.0, "process_inr": 0.0, "_c": c})
    weight = lambda ps: sum(p["kg_total"] or 0 for p in ps)
    no_density = [p["name"] for p in parts if p["kg_total"] is None]

    def share(amount, ps, key):
        w = weight(ps)
        if not ps or amount == 0:
            return False
        for p in ps:
            p[key] += amount * ((p["kg_total"] or 0) / w if w else 1 / len(ps))
        return True

    standard, tool_level, covered = [], [], set()
    for ln in lines:
        if ln.get("category") == "made" and not ln.get("is_base"):
            ps = [p for p in parts if p["name"].lower() == _base_name(ln["element"]) or p["name"].lower().startswith(_base_name(ln["element"]))]
            covered |= {id(p) for p in ps}
    plates = [p for p in parts if id(p) not in covered]
    for ln in lines:
        amt = float(ln.get("total") or 0) * fx
        if ln.get("is_base"):
            if not share(amt, plates, "steel_inr"):
                standard.append({"element": ln["element"], "inr": amt})
        elif ln.get("category") == "made":
            ps = [p for p in parts if id(p) in covered and (p["name"].lower() == _base_name(ln["element"])
                                                          or p["name"].lower().startswith(_base_name(ln["element"])))]
            if not share(amt, ps, "steel_inr"):
                tool_level.append({"element": ln["element"], "inr": amt})
        elif ln.get("category") == "process" and ln.get("cost_group") in R["groups"]:
            if not share(amt, parts, "process_inr"):
                tool_level.append({"element": ln["element"], "inr": amt})
        elif ln.get("category") == "bought_out":
            standard.append({"element": ln["element"], "qty": ln.get("quantity"), "inr": amt})
        else:
            tool_level.append({"element": ln["element"], "inr": amt})
    lines_inr = sum(float(ln.get("total") or 0) for ln in lines) * fx
    rest = value * fx - lines_inr
    if abs(rest) > 0.005:
        tool_level.append({"element": "Try-out, overhead, profit, packing, transport, warranty (tool cost commercial terms)", "inr": rest})
    for p in parts:
        p.pop("_c")
        p["total_inr"] = p["steel_inr"] + p["process_inr"]
        p["each_inr"] = p["total_inr"] / p["qty"] if p["qty"] else p["total_inr"]
    sums = {"parts_inr": sum(p["total_inr"] for p in parts), "standard_inr": sum(s["inr"] for s in standard),
            "tool_level_inr": sum(t["inr"] for t in tool_level), "tool_cost_inr": value * fx}
    sums["check_inr"] = sums["parts_inr"] + sums["standard_inr"] + sums["tool_level_inr"]
    return {"key": des["key"], "name": des["name"], "parts": parts, "standard": standard, "tool_level": tool_level, "sums": sums,
            "steel_kg": round(weight(parts), 2), "no_density": no_density, "rules": {k: R[k] for k in ("allow", "step", "groups")},
            "is_example": R["is_example"]}


def part(part_id: int, made: tuple | None = None) -> dict:
    """made = (part, revision, designs) of register.tool_designs when the caller has them already (saves designing again)."""
    from . import register
    d, rev, designs = made or register.tool_designs(part_id)
    tr = register.tool_trace(part_id)
    out = []
    for k, des in designs:
        pt = des.get("part_type", tr.get("part_type", ""))
        if tr.get("dies"):
            die = next((x for x in tr["dies"] if x["key"] == des["key"]), None)
            if not die:
                continue
            lines = [ln for ln in tr["lines"] if ln.get("die_key") == die["key"]]
            value, fx = die["value"], (die["value_inr"] / die["value"] if die["value"] else 1.0)
        else:
            lines, value = tr["lines"], tr["value"]
            fx = tr["value_inr"] / tr["value"] if tr["value"] else 1.0
        out.append({"stage": k} | tool_data(des, lines, value, fx, pt))
    return {"part_id": part_id, "part_code": d["part_code"], "rev": rev["rev"], "currency": "INR", "tools": out,
            "tool_cost_example": bool(tr.get("example"))}


def xlsx(part_id: int) -> tuple[bytes, str]:
    """Steel purchase and RFQ sheet: one row per made tool part, standard parts and tool-level costs below."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    data = part(part_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "Production data"
    ws.append([f"Production data · {data['part_code']} rev {data['rev']} · money in INR"])
    ws["A1"].font = Font(bold=True, size=12)
    if data["tool_cost_example"] or any(t["is_example"] for t in data["tools"]):
        ws.append(["EXAMPLE values are used (tool cost rates or the stock rules): replace them in Master data before sending to suppliers."])
    for t in data["tools"]:
        ws.append([])
        ws.append([f"Tool {t['stage']}: {t['name']}"])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
        ws.append(["Item", "Part", "Qty", "Material", "Hardness", "Finished L×W×H (mm)", "Stock L×W×H (mm)", "kg each", "kg total",
                   "Operations", "Steel (INR)", "Machining share (INR)", "Total (INR)", "Each (INR)"])
        for p in t["parts"]:
            ws.append([p["item"], p["name"], p["qty"], p["material"], p["hardness"], " × ".join(f"{v:g}" for v in p["finished_mm"]),
                       " × ".join(f"{v:g}" for v in p["stock_mm"]), p["kg_each"], p["kg_total"], "; ".join(p["operations"]),
                       round(p["steel_inr"], 2), round(p["process_inr"], 2), round(p["total_inr"], 2), round(p["each_inr"], 2)])
        ws.append(["", "Standard parts and bought-out"])
        for s in t["standard"]:
            ws.append(["", s["element"], s.get("qty")] + [""] * 9 + [round(s["inr"], 2)])
        ws.append(["", "Tool level (not per part)"])
        for x in t["tool_level"]:
            ws.append(["", x["element"]] + [""] * 10 + [round(x["inr"], 2)])
        ws.append(["", "Tool cost (= Σ parts + standard + tool level)"] + [""] * 10 + [round(t["sums"]["tool_cost_inr"], 2)])
    for col, w in zip("ABCDEFGHIJKLMN", (6, 28, 5, 18, 18, 18, 18, 9, 9, 70, 12, 14, 12, 12)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), f"{data['part_code']}_production_data.xlsx"
