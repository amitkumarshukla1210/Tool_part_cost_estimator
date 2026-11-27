"""Family tools (roadmap stage 68): one mould / die for 2-4 parts, fully traced.

    Same shot (moulds: plastic, die casting, EPS, blow, foundry; sheet metal "same stroke")
        every shot / stroke makes all parts. Each part keeps its own cavities (typed per part); the cavity blocks of
        the parts are laid side by side (every arrangement and turn is tried) and the smallest standard mould base /
        die set that takes them is chosen. Cavity inserts, cores, punches ... of every part are its own BOM lines
        (worked out by the part's own tool engine with the family cavities); the base is the family's. Clamp / press
        force = Σ of the parts, so the try-out machine and the part-cost machine are the family's.
    Swap inserts (sheet metal: stage or progressive dies)
        one common die set; the parts run one after another and only the inserts / changed stations are swapped.
        Every BOM line starts COMMON (counted once, at the largest part's value) and you tick the lines that belong to
        each part (counted for every part). Die set = the one that takes the largest part's die.

    Tool cost: the same Cost formulas "tool" (try-out, overhead, profit, packing, transport, warranty) as a single
    tool, applied to the family's steel, standard parts, processes and design. Tools over the programme = the most any
    part needs.
    Split back to the parts: share % per part = your % or, when blank, part weight × cavities ÷ Σ (the rest of 100 %
    after the parts you typed). Part share of the tool cost and CAPEX = family value × share %; in "same shot" the
    machine hour (MHR and crew) is shared the same way in the part cost.

No number is written here: sizes, gaps and rules come from Mould & die database → Sizing rules (insert_gap_mm for
moulds, family_gap_mm for sheet-metal dies), prices from the rate library and master data, as for any tool.
"""

from __future__ import annotations

import itertools

from . import die_cost, mould, mould_db, rate_engine, register_setup, tool_cost
from .tool_cost import ToolCostError, _ref
from .trace import Trace

MOULD_TYPES = ("plastic", "die_casting", "eps", "blow", "foundry")
MODES = {"same_shot": "Same shot / same stroke (all parts every shot)",
         "swap_inserts": "Common die set, swap inserts (parts run one after another)"}
MIN_PARTS, MAX_PARTS = 2, 4
SHEET_GAP = "family_gap_mm"
SEED_RULES = [  # (part_type, parameter, value, unit, description) - EXAMPLE, only added when missing
    ("sheet_metal", SHEET_GAP, 25.0, "mm",
     "Family die (same stroke): gap between the work areas of the parts on one die plate (stage 68)"),
]


class FamilyError(ValueError):
    pass


def seed() -> int:
    """Add the Sizing rules rows of family tools that are missing (existing rows are never changed)."""
    d = mould_db.tables()
    have = {(r["part_type"], r["parameter"]) for r in d["sizing_rules"]}
    new = [{"part_type": pt, "parameter": p, "value": v, "unit": u, "description": desc, "is_example": True}
           for pt, p, v, u, desc in SEED_RULES if (pt, p) not in have]
    if new:
        d["sizing_rules"] += new
        mould_db.write(d)
    return len(new)


def modes_for(part_type: str) -> list[str]:
    if part_type == "sheet_metal":
        return ["same_shot", "swap_inserts"]
    if part_type in MOULD_TYPES:
        return ["same_shot"]
    return []


# ---------- packing the parts' blocks on one base ----------

def arrangements(blocks: list[tuple[float, float]], gap: float) -> list[dict]:
    """Every way to put the blocks (length × width) in one row or one column, each block straight or turned."""
    out = []
    for turns in itertools.product((False, True), repeat=len(blocks)):
        sizes = [(w, l) if t else (l, w) for (l, w), t in zip(blocks, turns)]
        for along in ("length", "width"):
            places, pos = [], 0.0
            for l, w in sizes:
                places.append({"x": pos, "y": 0.0, "l": l, "w": w} if along == "length" else {"x": 0.0, "y": pos, "l": l, "w": w})
                pos += (l if along == "length" else w) + gap
            if along == "length":
                L, W = sum(s[0] for s in sizes) + gap * (len(sizes) - 1), max(s[1] for s in sizes)
            else:
                L, W = max(s[0] for s in sizes), sum(s[1] for s in sizes) + gap * (len(sizes) - 1)
            for p in places:   # centre the blocks across the row / column
                if along == "length":
                    p["y"] = (W - p["w"]) / 2
                else:
                    p["x"] = (L - p["l"]) / 2
            out.append({"pocket_l": L, "pocket_w": W, "along": along, "turns": list(turns), "places": places})
    return out


def _pack_note(a: dict, labels: list[str], gap: float, gap_name: str) -> str:
    parts = [f"{lab} {p['l']:.0f} × {p['w']:.0f}" + (" (turned)" if t else "") for lab, p, t in zip(labels, a["places"], a["turns"])]
    return (f"side by side along the {a['along']}: " + " | ".join(parts) + f", {gap:g} mm {gap_name} between")


# ---------- family engine runs (the single-tool engines with the family's base, values and lines) ----------

class _FamilyMixin:
    """Builds only the family base in its own trace, then adds the parts' BOM lines (embedded traces)."""
    fam: dict

    def elements(self):
        return []

    def bom(self):
        lines = super().bom()             # the family base / die set only
        for line in lines:
            line |= {"member": "Family", "part_id": None, "common": True, "family_base": True}
        common = self.fam.get("common") or {}
        by_key: dict[str, list[dict]] = {}
        for m in self.fam["members"]:
            for line in m["lines"]:
                if line.get("is_base"):
                    continue
                key = self.common_key(line)
                by_key.setdefault(key, []).append(line | {"member": m["label"], "part_id": m["part_id"]})
        for key, group in by_key.items():
            is_common = bool(common.get(key, self.fam["mode"] == "swap_inserts")) and len(group) > 1
            if not is_common:
                lines += [g | {"common": False, "family_key": key} for g in group]
                continue
            win = max(group, key=lambda g: g["total"])
            self.trace.nodes[win["nodes"]["total"]]["description"] = (
                (self.trace.nodes[win["nodes"]["total"]].get("description") or "")
                + f" COMMON line of the family tool: counted once, at the largest part's value ({win['member']}); "
                  f"not counted again for {', '.join(g['member'] for g in group if g is not win)}.")
            lines.append(win | {"common": True, "family_key": key,
                                "dropped": [{"member": g["member"], "total": g["total"]} for g in group if g is not win]})
        return lines

    def common_key(self, line: dict) -> str:
        return line["element"]


class _FamilyMould(_FamilyMixin, tool_cost._Run):
    def __init__(self, inp, sources, fam):
        super().__init__(inp, sources)
        self.fam = fam
        for m in fam["members"]:
            die_cost._embed(self.trace, m["r"], m["prefix"])
            m["lines"] = [line | {"nodes": {a: (m["prefix"] + b if b else b) for a, b in line["nodes"].items()}}
                          for line in m["r"]["lines"]]

    def size(self) -> dict:
        rules = mould_db.sizing_rules(self.inp.part_type)
        if "insert_gap_mm" not in rules:
            raise ValueError(f"Sizing rules for {self.inp.part_type} have no insert_gap_mm.")
        gap = rules["insert_gap_mm"]["value"]
        blocks = [(m["r"]["layout"]["pocket_l"], m["r"]["layout"]["pocket_w"]) for m in self.fam["members"]]
        options = []
        for a in arrangements(blocks, gap):
            try:
                base, turned = mould.select_base(self.inp.part_type, a["pocket_l"], a["pocket_w"])
            except ValueError:
                continue
            aspect = max(a["pocket_l"], a["pocket_w"]) / min(a["pocket_l"], a["pocket_w"])
            options.append(((base["length_mm"] * base["width_mm"], base["cost"], aspect), a, base, turned))
        if not options:
            small = min(arrangements(blocks, gap), key=lambda a: max(a["pocket_l"], a["pocket_w"]))
            mould.select_base(self.inp.part_type, small["pocket_l"], small["pocket_w"])   # raises with a clear message
        _, a, base, turned = min(options, key=lambda o: o[0])
        warnings = []
        plate = min(base["a_plate_mm"], base["b_plate_mm"])
        floor = rules.get("plate_floor_mm", {}).get("value", 0)
        for m in self.fam["members"]:
            half_h = m["r"]["layout"].get("half_h") or 0
            if half_h + floor > plate:
                warnings.append(f"{m['label']}: insert height {half_h:.0f} mm + {floor:.0f} mm floor is more than the "
                                f"{plate:.0f} mm A/B plate of base {base['size_code']}. Choose thicker plates for this base.")
        self.pack = a
        return {"layout": {"rows": 1 if a["along"] == "length" else len(blocks), "cols": len(blocks) if a["along"] == "length" else 1,
                           "empty": 0, "pocket_l": a["pocket_l"], "pocket_w": a["pocket_w"], "family": a, "gap": gap},
                "base": base, "base_turned": turned, "rules": rules,
                "sizing_rules_are_examples": any(r["is_example"] for r in rules.values()), "warnings": warnings}

    def var(self, name: str) -> str:
        nid = f"v:{name}"
        if nid in self.trace.nodes:
            return nid
        t, ms = self.trace, self.fam["members"]
        if name == "cavities":
            t.compute(nid, "Cavities of the family mould (Σ of the parts)", " + ".join(f"n{k}" for k in range(len(ms))), "pcs",
                      names={f"n{k}": m["prefix"] + "v:cavities" for k, m in enumerate(ms)})
        elif name in ("part_weight_g", "projected_area_cm2"):
            label = "Net weight per cavity (family average)" if name == "part_weight_g" else "Projected area per cavity (family average)"
            for m in ms:
                _member_node(self, m, name)
            names = {f"n{k}": m["prefix"] + "v:cavities" for k, m in enumerate(ms)} | \
                    {f"x{k}": m["prefix"] + f"v:{name}" for k, m in enumerate(ms)}
            t.compute(nid, label, "(" + " + ".join(f"n{k} * x{k}" for k in range(len(ms))) + ") / ("
                      + " + ".join(f"n{k}" for k in range(len(ms))) + ")", "g" if name == "part_weight_g" else "cm²", names=names,
                      description="Σ cavities × value of each part ÷ Σ cavities, so cavities × this = the family total "
                                  "(shot weight, projected area for the clamp force).")
        elif name in ("pocket_l", "pocket_w"):
            a = self.sized["layout"]["family"]
            gap = self.var("insert_gap_mm")
            names = {"insert_gap_mm": gap} | {f"part{k + 1}_cavities": m["prefix"] + "v:cavities" for k, m in enumerate(ms)}
            t.add_derived(nid, "Family insert pocket length" if name == "pocket_l" else "Family insert pocket width",
                          a[name], "mm", _pack_note(a, [m["label"] for m in ms], self.sized["layout"]["gap"], "insert_gap_mm")
                          + "; the arrangement that needs the smallest standard mould base wins", names,
                          description=f"{a['pocket_l']:.0f} × {a['pocket_w']:.0f} mm")
        elif name in ("layout_rows", "layout_cols"):
            lay = self.sized["layout"]
            t.add_input(nid, "Part blocks across" if name == "layout_rows" else "Part blocks along", lay["rows" if name == "layout_rows" else "cols"],
                        "", {"type": "register", "note": "Family tool: one block of cavities per part"})
        else:
            return super().var(name)
        return nid


def _member_node(run, m, name) -> None:
    """The part's own value node (weight, projected area) in its embedded trace, if its tool run did not need it."""
    if m["prefix"] + f"v:{name}" not in run.trace.nodes:
        label, unit = tool_cost.PART_VARS[name]
        run.trace.add_input(m["prefix"] + f"v:{name}", f"{m['label']} · {label}", float(getattr(m["inp"], name)), unit,
                            (m["sources"] or {}).get(name) or {"type": "register", "note": m["label"]})


class _FamilyDie(_FamilyMixin, die_cost._DieRun):
    def __init__(self, inp, sources, die, sheet, fam):
        super().__init__(inp, sources, die, sheet)
        self.fam = fam


# ---------- the family ----------

def _members(family: dict, country: str | None) -> list[dict]:
    from . import register
    out = []
    for k, mem in enumerate(family["members"]):
        cap: dict = {}
        cav = int(mem.get("cavities") or 0) or None
        try:
            r = register._tool_compute(int(mem["part_id"]), country, cavities=cav if family["part_type"] != "sheet_metal" else None,
                                       capture=cap)
        except (register.ToolNotApplicable, register.RegisterError) as exc:
            raise FamilyError(f"Part {mem.get('part_code') or mem['part_id']}: {exc}") from None
        d = cap["part"]
        out.append({"k": k, "part_id": int(mem["part_id"]), "part_code": d["part_code"], "label": d["part_code"],
                    "name": d.get("name") or "", "r": r, "inp": cap["inp"], "sources": cap["sources"], "cap": cap,
                    "prefix": f"m{k + 1}:", "share_typed": mem.get("share_pct"), "use_family": mem.get("use_family", True),
                    "material": d["material"]})
    return out


def validate(family: dict) -> None:
    ms = family.get("members") or []
    if not MIN_PARTS <= len(ms) <= MAX_PARTS:
        raise FamilyError(f"A family tool has {MIN_PARTS} to {MAX_PARTS} parts (it has {len(ms)}).")
    ids = [int(m["part_id"]) for m in ms]
    if len(set(ids)) != len(ids):
        raise FamilyError("A part is in the family twice.")
    if family.get("mode") not in modes_for(family.get("part_type") or ""):
        allowed = ", ".join(modes_for(family.get("part_type") or "")) or "none"
        raise FamilyError(f"Mode '{family.get('mode')}' is not possible for {family.get('part_type')} (possible: {allowed}).")
    typed = [float(m["share_pct"]) for m in ms if m.get("share_pct") not in (None, "")]
    if any(x < 0 for x in typed):
        raise FamilyError("A share % cannot be negative.")
    if sum(typed) > 100.0001:
        raise FamilyError(f"The share % you typed add up to {sum(typed):g} %: they must not be more than 100 %.")
    if len(typed) == len(ms) and abs(sum(typed) - 100) > 0.01:
        raise FamilyError(f"The share % of all parts must add up to 100 % (they add up to {sum(typed):g} %).")


def run(family: dict, country: str | None = None) -> dict:
    """Traced cost of the family tool and the share of each part. `family`: part_type, mode, members, common, country."""
    validate(family)
    pt = family["part_type"]
    country = (country or family.get("country") or None)
    members = _members(family, country)
    types = {m["r"]["part_type"] for m in members}
    if types != {pt}:
        raise FamilyError(f"Every part of a {pt} family tool must be a {pt} part (found: {', '.join(sorted(types))}).")
    countries = {m["r"]["country"] for m in members}
    if len(countries) > 1:
        raise FamilyError("The parts have different tool countries (" + ", ".join(sorted(countries)) + "): "
                          "choose the family's tool country.")
    if any(m["r"]["missing"] for m in members):
        miss = [f"{m['label']}: {x}" for m in members for x in m["r"]["missing"]]
        raise FamilyError("A part's tool cannot be priced: " + " ".join(miss))
    lead = max(members, key=lambda m: (m["r"]["value"], -m["k"]))
    tools_count = max(m["r"]["tools_count"] for m in members)
    upd = {"bom": family.get("bom") or {}, "overrides": {}, "learned": {}, "tools_count": tools_count}
    sources = dict(lead["sources"])
    sources["tools_count"] = {"type": "register", "note": "Family tool: the most tools over the programme any part needs ("
                              + ", ".join(f"{m['label']} {m['r']['tools_count']}" for m in members) + ")"}
    fam = {"members": members, "mode": family["mode"], "common": family.get("common") or {}}
    if pt == "sheet_metal":
        out = _run_sheet(family, members, lead, upd, sources, fam)
    else:
        inp = lead["inp"].model_copy(update=upd | {"cavities": sum(m["r"]["cavities"] for m in members)})
        runner = _FamilyMould(inp, sources, fam)
        for m in members:
            for name in ("part_weight_g", "projected_area_cm2"):
                _member_node(runner, m, name)
        try:
            out = runner.run()
        except ValueError as exc:
            raise ToolCostError(str(exc)) from None
        out["family_layout"] = {"base": out["base"], "turned": out["base_turned"], "pack": runner.pack,
                                "blocks": [{"label": m["label"], "cavities": m["r"]["cavities"], "layout": m["r"]["layout"]}
                                           for m in members]}
    return _shares(out, family, members)


def _run_sheet(family, members, lead, upd, sources, fam) -> dict:
    plans = []
    for m in members:
        cap = m["cap"]
        plans.append(die_cost.plan(cap["sheet"], cap["layout"]))
    rules = mould_db.sizing_rules("sheet_metal")
    same = family["mode"] == "same_shot"
    if same and SHEET_GAP not in rules:
        raise FamilyError(f"Mould & die database → Sizing rules has no sheet_metal / {SHEET_GAP} row (run the master-data update).")
    gap = rules[SHEET_GAP]["value"] if same else 0
    n_units = max(len(p) for p in plans)
    results, units = [], []
    for k in range(n_units):
        here = [(m, p[k]) for m, p in zip(members, plans) if k < len(p)]
        lm, ld = max(here, key=lambda x: (x[1]["work_l"] * x[1]["work_w"], -x[0]["k"]))
        die = dict(ld)
        names = " + ".join(f"{m['label']} {d['name']}" for m, d in here)
        if same:
            a = min(arrangements([(d["work_l"], d["work_w"]) for _, d in here], gap),
                    key=lambda a: (a["pocket_l"] * a["pocket_w"], max(a["pocket_l"], a["pocket_w"])))
            die |= {"work_l": a["pocket_l"], "work_w": a["pocket_w"], "force_t": sum(d["force_t"] for _, d in here),
                    "work_note": f"family die, same stroke: {_pack_note(a, [m['label'] for m, _ in here], gap, SHEET_GAP)}",
                    "pack": a}
        else:
            die |= {"work_l": max(d["work_l"] for _, d in here), "work_w": max(d["work_w"] for _, d in here),
                    "force_t": max(d["force_t"] for _, d in here),
                    "work_note": "family die set, swap inserts: largest work area and force of " + names}
        die |= {"key": f"F{k + 1}", "name": f"Family die {k + 1}: " + " / ".join(sorted({d['name'].split(': ', 1)[-1] for _, d in here})),
                "ops": sorted({o for _, d in here for o in d["ops"]}), "op_names": ld["op_names"]}
        unit_members = []
        for m, d in here:
            lines = [ln for ln in m["r"]["lines"] if ln.get("die_key") == d["key"]]
            pre = m["prefix"]
            unit_members.append({"label": m["label"], "part_id": m["part_id"], "prefix": pre, "k": m["k"],
                                 "lines": [ln | {"nodes": {a: (pre + b if b else b) for a, b in ln["nodes"].items()}} for ln in lines]})
        sub_fam = {"members": unit_members, "mode": fam["mode"], "common": {
            key.split("|", 1)[1]: v for key, v in fam["common"].items() if key.split("|", 1)[0] == die["key"]}}
        inp = lead["inp"].model_copy(update=upd)
        runner = _FamilyDie(inp, sources, die, lm["cap"]["sheet"], sub_fam)
        for m, d in here:   # the nodes of the part's own die at this position
            sub = {"nodes": {nid: n for nid, n in m["r"]["nodes"].items() if nid.startswith(f"{d['key']}:")},
                   "rates_used": m["r"]["rates_used"]}
            die_cost._embed(runner.trace, sub, m["prefix"])
        try:
            r = runner.run()
        except (ToolCostError, ValueError) as exc:
            raise ToolCostError(f"{die['name']}: {exc}") from None
        results.append(r)
        units.append({"die": die, "here": [(m["label"], d) for m, d in here], "base": r["base"], "die_plate": r["die_plate"]})
    # the family die set = Σ family dies (same composition as a part's die set)
    cur, as_of = results[0]["currency"], results[0]["as_of"]
    t = Trace(cur)
    lines, out_dies, missing = [], [], []
    for u, r in zip(units, results):
        die = u["die"]
        p = f"{die['key']}:"
        die_cost._embed(t, r, p)
        t.nodes[p + r["root"]]["label"] = f"{die['name']} · tool cost"
        for line in r["lines"]:
            lines.append(line | {"die": die["name"], "die_key": die["key"], "line_key": f"{die['key']}|{line.get('family_key') or line['key']}",
                                 "nodes": {a: (p + b if b else b) for a, b in line["nodes"].items()}})
        missing += [f"{die['name']}: {x}" for x in r["missing"]]
        out_dies.append({"key": die["key"], "name": die["name"], "ops": die["ops"], "op_names": die["op_names"],
                         "node": p + r["root"], "capex_node": p + r["capex_node"] if r.get("capex_node") else None,
                         "value": r["value"], "value_inr": r["value_inr"], "capex": r["capex"], "capex_inr": r["capex_inr"],
                         "force_t": r["trial"]["force_t"], "press": r["trial"]["machine"], "force_node": p + r["trial"]["force_node"],
                         "machine_node": p + "trial:machine", "base": r["base"], "die_plate": r["die_plate"],
                         "weight_node": p + "tool_weight", "work_note": die["work_note"], "pack": die.get("pack"),
                         "parts": [{"label": lab, "die": d["name"], "work_l": d["work_l"], "work_w": d["work_w"]} for lab, d in u["here"]],
                         "groups": [g | {"node": p + g["node"]} for g in r["groups"]]})
    total = die_cost._sum(t, "calc:tool_cost", "Family die set: tool cost of all family dies", [d["node"] for d in out_dies], cur,
                          description="Σ tool cost of every family die")
    capex = None
    if all(d["capex_node"] for d in out_dies):
        capex = die_cost._sum(t, "calc:tool_capex", "Tool CAPEX: all family dies × tools over the programme",
                              [d["capex_node"] for d in out_dies], cur)
    fx = rate_engine.fx_to_inr(t, cur, as_of)
    t.compute("result:inr", "Family die set tool cost in INR", "value * fx", "INR", money=True, names={"value": total, "fx": fx})
    capex_inr = t.compute("capex:inr", "Tool CAPEX in INR", "value * fx", "INR", money=True,
                          names={"value": capex, "fx": fx}) if capex else None   # the value
    groups = []
    for g in mould_db.COST_GROUPS:
        nodes = [x["node"] for d in out_dies for x in d["groups"] if x["group"] == g]
        if nodes:
            label = next(x["label"] for d in out_dies for x in d["groups"] if x["group"] == g)
            groups.append({"group": g, "label": label, "node": die_cost._sum(t, f"group:{g}", f"{label} (all family dies)", nodes, cur)})
    totals = {}
    for key, sub, label in (("material_cost", "sum:material", "Tool steel"), ("bought_out_cost", "sum:bought_out", "Die sets & standard parts"),
                            ("process_cost", "sum:process", "Processes (design excluded)"), ("design_cost", "sum:design", "Design")):
        totals[key] = die_cost._sum(t, f"sum:{key}", f"{label} (all family dies)", [f"{d['key']}:{sub}" for d in out_dies], cur)
    totals["tool_weight_kg"] = die_cost._sum(t, "tool_weight", "Weight of all family dies", [d["weight_node"] for d in out_dies],
                                             "kg", money=False)
    out = t.to_dict(total)
    first = results[0]
    out |= {"part_type": "sheet_metal", "mode": family["mode"], "country": first["country"], "currency": cur, "as_of": as_of,
            "material": lead["material"], "value": t.value(total), "value_inr": t.value("result:inr"),
            "capex": t.value(capex) if capex else None, "capex_inr": capex_inr,
            "capex_node": capex, "tools_count": upd["tools_count"], "cavities": 1, "dies": out_dies, "lines": lines,
            "groups": groups, "totals": totals,
            "base": first["base"] | {"series": f"{len(out_dies)} family die set(s)", "size_code": first["base"]["size_code"]},
            "trial": {"force_node": out_dies[0]["force_node"], "force_t": out_dies[0]["force_t"], "process": first["trial"]["process"],
                      "machine": out_dies[0]["press"], "machine_node": out_dies[0]["machine_node"]},
            "steps": [{"name": "tool_cost", "node": total, "is_result": True}]
                     + ([{"name": "tool_capex", "node": capex, "is_result": False}] if capex else []),
            "missing": missing, "priced": not missing, "warnings": [w for r in results for w in r["warnings"]],
            "layout": {"rows": 1, "cols": 1, "empty": 0}, "base_turned": False,
            "sizing_rules_are_examples": any(r["sizing_rules_are_examples"] for r in results)}
    out["example"] = tool_cost.examples(out, lines)
    out["family_layout"] = {"dies": [{"key": d["key"], "name": d["name"], "base": d["base"], "die_plate": d["die_plate"],
                                      "pack": d["pack"], "parts": d["parts"]} for d in out_dies]}
    return out


def _shares(out: dict, family: dict, members: list[dict]) -> dict:
    """Share % of each part (yours, else by weight × cavities), its share of the tool cost and CAPEX, and own-tool saving."""
    from . import register
    t = Trace(out["currency"])
    t.nodes, t.rates_used = out["nodes"], {r["id"]: r for r in out["rates_used"]}
    typed = {m["k"]: float(m["share_typed"]) for m in members if m["share_typed"] not in (None, "")}
    for m in members:
        p = m["prefix"]
        t.add_input(f"share:w:{p}", f"{m['label']} · net weight", float(m["inp"].part_weight_g), "g",
                    {"type": "register", "note": "Net weight = CAD volume × material density (Materials)"})
        cav = m["r"]["cavities"] if out["part_type"] != "sheet_metal" else 1
        t.add_input(f"share:n:{p}", f"{m['label']} · cavities in the family tool", float(cav), "pcs",
                    {"type": "user", "note": "Family tool page"} if out["part_type"] != "sheet_metal"
                    else {"type": "register", "note": "Sheet-metal die: 1 part per stroke"})
        t.compute(f"share:basis:{p}", f"{m['label']} · weight × cavities", "w * n", "g",
                  names={"w": f"share:w:{p}", "n": f"share:n:{p}"})
    free = [m for m in members if m["k"] not in typed]
    rest = 100 - sum(typed.values())
    t.add_input("share:rest", "Share % left for the parts without a typed %", rest, "%",
                {"type": "user", "note": "100 % − the % you typed on the family tool page"})
    for m in members:
        p = m["prefix"]
        if m["k"] in typed:
            t.add_input(f"share:pct:{p}", f"{m['label']} · share %", typed[m["k"]], "%", {"type": "user", "note": "Typed on the family tool page"})
        else:
            names = {"rest": "share:rest", "b": f"share:basis:{p}"} | {f"b{j}": f"share:basis:{f['prefix']}" for j, f in enumerate(free)}
            t.compute(f"share:pct:{p}", f"{m['label']} · share %", "rest * b / (" + " + ".join(f"b{j}" for j in range(len(free))) + ")",
                      "%", names=names, description="By weight × cavities of the parts without a typed %")
        t.compute(f"share:cost:{p}", f"{m['label']} · share of the family tool cost", "tool * pct / 100", out["currency"], money=True,
                  names={"tool": out["root"], "pct": f"share:pct:{p}"})
        t.compute(f"share:cost_inr:{p}", f"{m['label']} · share of the family tool cost (INR)", "tool * pct / 100", "INR", money=True,
                  names={"tool": "result:inr", "pct": f"share:pct:{p}"})
        if out.get("capex_inr") is not None:
            t.compute(f"share:capex_inr:{p}", f"{m['label']} · share of the family tool CAPEX (INR)", "capex * pct / 100", "INR",
                      money=True, names={"capex": "capex:inr", "pct": f"share:pct:{p}"})
    # own single tools (each part's own cavities), for the saving
    own_nodes = []
    for m in members:
        p = m["prefix"]
        try:
            own = m["r"] if out["part_type"] == "sheet_metal" else register._tool_compute(m["part_id"], out["country"])
        except Exception:   # noqa: BLE001 - the comparison is information only
            own = None
        if own and own.get("capex_inr") is not None:
            t.add_input(f"own:capex_inr:{p}", f"{m['label']} · own tool CAPEX (INR)", own["capex_inr"], "INR",
                        {"type": "register", "note": f"Own single tool of the part, {own['cavities']} cavities, live in {own['country']}"},
                        money=True)
            m["own"] = {"cavities": own["cavities"], "value_inr": own["value_inr"], "capex_inr": own["capex_inr"]}
            own_nodes.append(f"own:capex_inr:{p}")
    saving = None
    if own_nodes and len(own_nodes) == len(members) and out.get("capex_inr") is not None:
        names = {f"o{k}": n for k, n in enumerate(own_nodes)} | {"fam": "capex:inr"}
        t.compute("saving:capex_inr", "CAPEX saving: own tools − family tool (INR)", " + ".join(f"o{k}" for k in range(len(own_nodes)))
                  + " - fam", "INR", money=True, names=names,
                  description="Positive = the family tool needs less CAPEX than one own tool per part.")
        saving = t.value("saving:capex_inr")
    out["nodes"] = t.nodes
    out["shares"] = [{"part_id": m["part_id"], "part_code": m["part_code"], "name": m["name"], "prefix": m["prefix"],
                      "cavities": m["r"]["cavities"] if out["part_type"] != "sheet_metal" else 1,
                      "weight_g": float(m["inp"].part_weight_g), "typed": m["k"] in typed,
                      "pct": t.value(f"share:pct:{m['prefix']}"), "pct_node": f"share:pct:{m['prefix']}",
                      "cost": t.value(f"share:cost:{m['prefix']}"), "cost_inr": t.value(f"share:cost_inr:{m['prefix']}"),
                      "capex_inr": t.value(f"share:capex_inr:{m['prefix']}") if out.get("capex_inr") is not None else None,
                      "own": m.get("own"), "use_family": bool(m["use_family"]), "tools_count": m["r"]["tools_count"],
                      "revision_id": m["r"]["revision"]["id"], "rev": m["r"]["revision"]["rev"],
                      "material": m["material"]} for m in members]
    out["saving_capex_inr"] = saving
    out["family_mode"] = family["mode"]
    out["mode_label"] = MODES[family["mode"]]
    out["common"] = {ln.get("line_key") or ln.get("family_key"): bool(ln.get("common")) for ln in out["lines"]
                     if not ln.get("family_base") and (ln.get("line_key") or ln.get("family_key"))}
    out["key"] = {"members": [{"part_id": m["part_id"], "key": m["r"].get("key")} for m in members],
                  "mode": family["mode"], "common": family.get("common") or {}, "bom": family.get("bom") or {},
                  "shares": {str(m["part_id"]): m["share_typed"] for m in members},
                  "rates": sorted(x["id"] for x in out["rates_used"])}
    return out
