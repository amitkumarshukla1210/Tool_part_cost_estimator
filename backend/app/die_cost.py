"""Sheet-metal dies, stage-wise (roadmap stage 23): which dies, their BOM with grade / make / price, and their cost.

    sheet-metal tools (stage 9)   operations in order, force of each, die type (progressive / multi-stage)
    strip layout (stage 10)       pitch, strip width, stations
        -> the dies the part needs:
             multi-stage   one die per operation (Die 1 Blanking, Die 2 Piercing, Die 3 Bending, ...)
             progressive   one die with every operation as a station
        -> each die is sized (Sizing rules, sheet_metal), gets the smallest die set that takes its die plate
           (Mould bases, sheet_metal) and the BOM elements of its operations (BOM elements → operations), with
           the steel grade suggested by Grade rules and the make of the element, then it is priced by the tool
           cost engine exactly like a mould: steel rates, processes with MHR and labour, try-out on the press
           that takes the die's force, overhead, profit, packing, transport, warranty.
        -> the die set total = Σ dies; CAPEX = Σ dies × tools over the programme.

Your changes per BOM line (grade, make, quantity, price each) come in `bom`, keyed "<die key>|<element>", and are
traced as your input. No number or rule is written here: the die plate size is die work area + 2 × die_wall_mm,
the die plate height max(die_plate_min_mm, die_plate_t_factor × thickness), everything else is a rule in master data.
"""

from __future__ import annotations

from . import mould_db, rate_engine, register_setup
from .rm_cost import _parameter_row
from .tool_cost import ToolCostError, ToolInput, _ref, _Run, examples
from .trace import Trace

SIZING = ("die_wall_mm", "die_plate_min_mm", "die_plate_t_factor")
FEATURES = {
    "t": ("Sheet thickness", "mm"), "blank_l": ("Blank length", "mm"), "blank_w": ("Blank width", "mm"),
    "blank_perimeter": ("Blank perimeter", "mm"), "hole_count": ("Pierced holes", "pcs"),
    "hole_perimeter": ("Total hole perimeter", "mm"), "bends": ("Bends", "pcs"), "bend_len": ("Total bend length", "mm"),
    "draw_depth": ("Draw depth", "mm"), "draw_dia": ("Equivalent draw punch diameter", "mm"),
}
# Which sheet features each cutting operation cuts (perimeter) and how many punches it needs.
CUTS = {"blank": ("blank_perimeter", "1"), "pierce": ("hole_perimeter", "hole_count"), "trim": ("blank_perimeter", "1")}


def plan(sheet: dict, layout: dict | None) -> list[dict]:
    """The dies of the part: one per operation (multi-stage) or one progressive die."""
    ops = sheet["operations"]
    if not ops:
        raise ToolCostError("The part has no sheet operation: set the operations in order (Sheet-metal tools) first.")
    feat = sheet["features"]
    if sheet["mode"] == "progressive":
        v = ((layout or {}).get("strip") or {}).get("best", {}).get("values") or {}
        stations = v.get("stations") or len(ops)
        pitch = v.get("pitch_mm") or feat["blank_l"]
        width = v.get("strip_width_mm") or feat["blank_w"]
        return [{"key": "progressive", "name": f"Progressive die ({stations:g} stations)", "ops": [o["code"] for o in ops],
                 "op_names": [o["name"] for o in ops], "force_t": sum(o["force_t"] for o in ops),
                 "work_l": pitch * stations, "work_w": width, "stations": stations, "pitch": pitch, "strip_w": width,
                 "progressive": 1,
                 "work_note": f"strip: pitch {pitch:.1f} mm × {stations:g} stations, strip width {width:.1f} mm (stage 10)"}]
    dies, seen = [], {}
    for i, o in enumerate(ops, start=1):
        seen[o["code"]] = seen.get(o["code"], 0) + 1
        key = o["code"] + (str(seen[o["code"]]) if seen[o["code"]] > 1 else "")
        # blank and formed part compared long side with long side (they may lie either way round)
        bl, bw = sorted((feat["blank_l"], feat["blank_w"]), reverse=True)
        pl_, pw_ = sorted((feat.get("part_l") or 0, feat.get("part_w") or 0), reverse=True)
        work_l, work_w = max(bl, pl_), max(bw, pw_)
        dies.append({"key": key, "name": f"Die {i}: {o['name']}", "ops": [o["code"]], "op_names": [o["name"]],
                     "force_t": o["force_t"], "work_l": work_l, "work_w": work_w, "stations": 1,
                     "pitch": feat["blank_l"], "strip_w": feat["blank_w"], "progressive": 0,
                     "work_note": f"blank / part envelope {work_l:.1f} × {work_w:.1f} mm"})
    return dies


class _DieRun(_Run):
    def __init__(self, inp: ToolInput, sources: dict | None, die: dict, sheet: dict):
        super().__init__(inp, sources)
        self.die, self.sheet, self.feat = die, sheet, sheet["features"]
        self.op_codes = [r["code"] for r in self.db["sheet_operations"]]

    # ---------- the die and its die set ----------

    def size(self) -> dict:
        rules = mould_db.sizing_rules("sheet_metal")
        missing = [k for k in SIZING if k not in rules]
        if missing:
            raise ValueError(f"Mould & die database → Sizing rules has no sheet_metal row for {', '.join(missing)}.")
        wall, hmin, hfac = (rules[k]["value"] for k in SIZING)
        die_l, die_w = self.die["work_l"] + 2 * wall, self.die["work_w"] + 2 * wall
        sets = sorted((b for b in self.db["mould_bases"] if b["part_type"] == "sheet_metal"),
                      key=lambda b: (b["length_mm"] * b["width_mm"], b["cost"]))
        if not sets:
            raise ValueError("Mould & die database → Mould bases has no sheet_metal die set yet.")
        for b in sets:
            for turned in (False, True):
                L, W = (die_w, die_l) if turned else (die_l, die_w)
                if b["max_insert_length_mm"] >= L and b["max_insert_width_mm"] >= W:
                    return {"base": b, "base_turned": turned, "layout": {"rows": 1, "cols": 1, "empty": 0},
                            "rules": rules, "die": {"die_l": die_l, "die_w": die_w, "die_h": max(hmin, hfac * self.feat["t"])},
                            "warnings": [], "sizing_rules_are_examples": any(r["is_example"] for r in rules.values())}
        big = sets[-1]
        raise ValueError(f"{self.die['name']}: no die set in Mould bases (sheet_metal) takes a die plate of "
                         f"{die_l:.0f} × {die_w:.0f} mm (largest usable area {big['max_insert_length_mm']:g} × "
                         f"{big['max_insert_width_mm']:g} mm). Add a bigger die set.")

    def base_label(self) -> str:
        b = self.sized["base"]
        return f"Die set {b['series']} {b['size_code']}"

    def line_key(self, element: str) -> str:
        return f"{self.die['key']}|{element}"

    def elements(self) -> list[dict]:
        ops = set(self.die["ops"])
        out = []
        for el in self.db["bom_elements"]:
            if el["part_type"] != "sheet_metal":
                continue
            wanted = {c.strip() for c in (el.get("operations") or "").split(",") if c.strip()}
            if not wanted or wanted & ops:
                out.append(el)
        return out

    # ---------- rule variables of a die ----------

    def var(self, name: str) -> str:
        nid = f"v:{name}"
        if nid in self.trace.nodes:
            return nid
        t, d = self.trace, self.die
        sheet_src = {"type": "register", "note": "Sheet-metal tools (stage 9) from the 3D model"}
        if name in FEATURES:
            label, unit = FEATURES[name]
            t.add_input(nid, label, float(self.feat.get(name) or 0), unit, self.sources.get(name) or sheet_src)
        elif name.startswith("op_") and name[3:] in self.op_codes:
            t.add_input(nid, f"{name[3:]} operations in this die", float(d["ops"].count(name[3:])), "",
                        {"type": "register", "note": f"{d['name']}: operations {', '.join(d['ops'])} (suggested die split)"})
        elif name in ("die_ops", "progressive", "stations", "pitch", "strip_w", "die_force_t"):
            label, unit, value = {"die_ops": ("Operations in this die", "", len(d["ops"])),
                                  "progressive": ("Progressive die (1 = yes)", "", d["progressive"]),
                                  "stations": ("Stations", "", d["stations"]),
                                  "pitch": ("Pitch (feed per stroke)", "mm", d["pitch"]),
                                  "strip_w": ("Strip / blank width", "mm", d["strip_w"]),
                                  "die_force_t": ("Force of this die (Σ its operations)", "t", d["force_t"])}[name]
            t.add_input(nid, label, float(value), unit, {"type": "register", "note": f"{d['name']}: {d['work_note']}"})
        elif name in ("work_l", "work_w"):
            t.add_input(nid, "Die work area length" if name == "work_l" else "Die work area width", float(d[name]), "mm",
                        {"type": "register", "note": f"{d['name']}: {d['work_note']}"})
        elif name in SIZING or name in self.sized["rules"]:
            r = self.sized["rules"][name]
            self.master(nid, r["description"] or name, r["value"], r["unit"], "Mould & die database → Sizing rules",
                        f"sheet_metal / {name}", r["is_example"],
                        ref=_ref("mould_db", "sizing_rules", {"part_type": "sheet_metal", "parameter": name}, "value"))
        elif name in ("die_l", "die_w"):
            work = "work_l" if name == "die_l" else "work_w"
            t.compute(nid, "Die plate length" if name == "die_l" else "Die plate width", f"{work} + 2 * die_wall_mm", "mm",
                      names={work: self.var(work), "die_wall_mm": self.var("die_wall_mm")})
        elif name == "die_h":
            t.compute(nid, "Die plate height", "max(die_plate_min_mm, die_plate_t_factor * t)", "mm",
                      names={k: self.var(k) for k in ("die_plate_min_mm", "die_plate_t_factor", "t")})
        elif name in ("cut_len", "punches"):
            names, terms = {}, []
            for code, (perim, count) in CUTS.items():
                if code not in self.op_codes:
                    continue
                names[f"op_{code}"] = self.var(f"op_{code}")
                k = perim if name == "cut_len" else count
                if k != "1":
                    names[k] = self.var(k)
                terms.append(f"op_{code} * {k}")
            text = " + ".join(terms) or "0"
            t.compute(nid, "Cutting length in this die" if name == "cut_len" else "Cutting punches in this die", text,
                      "mm" if name == "cut_len" else "pcs", names=names,
                      description="Blanking and trimming cut the blank outline, piercing cuts every hole.")
        else:
            return super().var(name)
        return nid

    def run(self) -> dict:
        out = super().run()
        return out | {"die_plate": self.sized["die"]}

    def trial(self) -> dict:
        t = self.trace
        row = _parameter_row("sheet_metal", "press_safety_factor")
        sf = self.master("trial:sf", "Press safety factor", (row or {}).get("value") or 1.0, "×", "Parameters",
                         "sheet_metal / press_safety_factor",
                         ref=_ref("master_data", "Parameters", {"part_type": "sheet_metal", "parameter": "press_safety_factor"}, "value"))
        t.compute("trial:force", "Press force needed for this die", "die_force_t * safety", "t",
                  names={"die_force_t": self.var("die_force_t"), "safety": sf})
        return self.trial_machine("trial:force", "press force")


def _embed(t: Trace, sub: dict, prefix: str) -> None:
    for nid, n in sub["nodes"].items():
        m = dict(n, id=prefix + nid)
        if "inputs" in m:
            m["inputs"] = [{"name": i["name"], "node": prefix + i["node"]} for i in m["inputs"]]
        t.nodes[prefix + nid] = m
    for r in sub["rates_used"]:
        t.rates_used[r["id"]] = r


def _sum(t: Trace, nid: str, label: str, nodes: list[str], unit: str, money: bool = True, description: str = "") -> str:
    if not nodes:
        t.add_input(nid, label, 0, unit, {"type": "base", "note": "Nothing in this group."}, money=money)
        return nid
    names = {f"d{k}": n for k, n in enumerate(nodes)}
    t.compute(nid, label, " + ".join(names), unit, money=money, names=names, description=description)
    return nid


def run(inp: ToolInput, sheet: dict, layout: dict | None, sources: dict | None = None) -> dict:
    """Every die of a sheet-metal part, each fully costed, and the die set total. `inp` holds the part values."""
    dies = plan(sheet, layout)
    results = []
    for die in dies:
        pre = f"{die['key']}:"
        die_inp = inp.model_copy(update={"overrides": {k[len(pre):]: v for k, v in (inp.overrides or {}).items() if k.startswith(pre)}})
        try:
            results.append(_DieRun(die_inp, sources, die, sheet).run())
        except ToolCostError as exc:
            msg = str(exc)
            raise ToolCostError(msg if msg.startswith(f"{die['name']}:") else f"{die['name']}: {msg}") from None
    cur, as_of = results[0]["currency"], results[0]["as_of"]
    t = Trace(cur)
    lines, out_dies, missing = [], [], []
    for k, (die, r) in enumerate(zip(dies, results), start=1):
        p = f"{die['key']}:"
        _embed(t, r, p)
        t.nodes[p + r["root"]]["label"] = f"{die['name']} · tool cost"
        if r.get("capex_node"):
            t.nodes[p + r["capex_node"]]["label"] = f"{die['name']} · tool CAPEX"
        for line in r["lines"]:
            lines.append(line | {"die": die["name"], "die_key": die["key"],
                                 "nodes": {a: (p + b if b else b) for a, b in line["nodes"].items()}})
        missing += [f"{die['name']}: {m}" for m in r["missing"]]
        out_dies.append({"key": die["key"], "name": die["name"], "ops": die["ops"], "op_names": die["op_names"],
                         "node": p + r["root"], "capex_node": p + r["capex_node"] if r.get("capex_node") else None,
                         "value": r["value"], "value_inr": r["value_inr"], "capex": r["capex"], "capex_inr": r["capex_inr"],
                         "force_t": r["trial"]["force_t"], "press": r["trial"]["machine"], "force_node": p + r["trial"]["force_node"],
                         "machine_node": p + "trial:machine", "base": r["base"], "die_plate": r["die_plate"],
                         "weight_node": p + "tool_weight", "work_note": die["work_note"],
                         "groups": [g | {"node": p + g["node"]} for g in r["groups"]]})
    total = _sum(t, "calc:tool_cost", "Die set: tool cost of all dies", [d["node"] for d in out_dies], cur,
                 description="Σ tool cost of every die (each: steel + standard parts + processes + design + try-out, "
                             "overhead, profit, packing, transport, warranty)")
    capex = None
    if all(d["capex_node"] for d in out_dies):
        capex = _sum(t, "calc:tool_capex", "Tool CAPEX: all dies × tools over the programme",
                     [d["capex_node"] for d in out_dies], cur)
    fx = rate_engine.fx_to_inr(t, cur, as_of)
    t.compute("result:inr", "Die set tool cost in INR", "value * fx", "INR", money=True, names={"value": total, "fx": fx})
    capex_inr = None
    if capex:
        capex_inr = t.compute("capex:inr", "Tool CAPEX in INR", "value * fx", "INR", money=True, names={"value": capex, "fx": fx})
    groups = []
    for g in mould_db.COST_GROUPS:
        nodes = [x["node"] for d in out_dies for x in d["groups"] if x["group"] == g]
        if nodes:
            label = next(x["label"] for d in out_dies for x in d["groups"] if x["group"] == g)
            groups.append({"group": g, "label": label, "node": _sum(t, f"group:{g}", f"{label} (all dies)", nodes, cur)})
    totals = {}
    for key, label in (("material_cost", "Tool steel"), ("bought_out_cost", "Die sets & standard parts"),
                       ("process_cost", "Processes (design excluded)"), ("design_cost", "Design")):
        sub = {"material_cost": "sum:material", "bought_out_cost": "sum:bought_out", "process_cost": "sum:process",
               "design_cost": "sum:design"}[key]
        totals[key] = _sum(t, f"sum:{key}", f"{label} (all dies)", [f"{d['key']}:{sub}" for d in dies], cur)
    totals["tool_weight_kg"] = _sum(t, "tool_weight", "Weight of all dies", [d["weight_node"] for d in out_dies], "kg", money=False)
    out = t.to_dict(total)
    first = results[0]
    out |= {
        "part_type": "sheet_metal", "mode": sheet["mode"], "country": first["country"], "currency": cur, "as_of": as_of,
        "material": inp.material, "value": t.value(total), "value_inr": t.value("result:inr"),
        "capex": t.value(capex) if capex else None, "capex_inr": capex_inr, "capex_node": capex,
        "tools_count": inp.tools_count, "cavities": inp.cavities, "dies": out_dies, "lines": lines, "groups": groups,
        "totals": totals, "base": first["base"] | {"series": f"{len(dies)} die set(s)", "size_code": first["base"]["size_code"]},
        "trial": {"force_node": out_dies[0]["force_node"], "force_t": out_dies[0]["force_t"], "process": first["trial"]["process"],
                  "machine": out_dies[0]["press"], "machine_node": out_dies[0]["machine_node"]},
        "steps": [{"name": "tool_cost", "node": total, "is_result": True}]
                 + ([{"name": "tool_capex", "node": capex, "is_result": False}] if capex else []),
        "missing": missing, "priced": not missing, "warnings": [w for r in results for w in r["warnings"]],
        "layout": {"rows": 1, "cols": 1, "empty": 0}, "base_turned": False,
        "sizing_rules_are_examples": any(r["sizing_rules_are_examples"] for r in results),
    }
    out["example"] = examples(out, lines)
    return out
