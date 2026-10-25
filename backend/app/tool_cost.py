"""Tool cost engine (roadmap stage 4): process-wise cost of a mould or die, fully traced.

    part + cavities          ->  mould size: layout, inserts, standard base (mould.py)
    BOM elements (rules)     ->  per line: quantity, steel weight, catalogue price, hours or amount
    Tool processes           ->  how each process is priced, with country rates:
                                   machine_hour   hours × (MHR of the machine + operators × labour rate)
                                   labour_hour    hours × operators × labour rate (design)
                                   unit           amount × rate per kg / cm² / ..., at least the minimum charge
    Cost formulas "tool_clamp"   clamp force -> smallest try-out machine that takes it
    Cost formulas "tool"         trial, overhead, profit, packing, transport, warranty -> tool cost and CAPEX

No number and no formula is written here: rules, rates, machines and formulas all come from master data or the
rate library (latest APPROVED version up to the costing month, in the tool country). The MHR and labour rate are
the rate engine's own traces, so every hour opens to depreciation, power, labour and the rest. Catalogue prices
(mould bases, standard parts) are kept in INR in master data and converted with that month's forex.

A missing rate does not stop the calculation: it is shown as missing (value 0) and the result is marked as not priced.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import Field

from . import costing_setup, formula, master_data, mould, mould_db, rate_engine, rates, register_setup
from .rm_cost import _parameter_row
from .trace import EXAMPLE_WARNING, Trace

PART_TYPES = ("plastic", "die_casting", "eps", "blow")
LATER = {"sheet_metal": "Sheet-metal dies are costed die by die on the part: Parts → the part → Tool cost.",
         "foundry": "Tool cost of foundry patterns and core boxes comes in a later stage."}
GROUP_LABEL = {"cutting": "Raw material cutting", "machining": "Machining (CNC, EDM, wire cut, grinding, drilling)",
               "polishing": "Polishing", "treatment": "Heat & surface treatment", "assembly": "Fitting & assembly",
               "design": "Design", "trial": "Try-out"}
PART_VARS = {
    "part_l": ("Part length across the parting plane", "mm"),
    "part_w": ("Part width across the parting plane", "mm"),
    "part_h": ("Part height along the opening direction", "mm"),
    "projected_area_cm2": ("Projected area of one part", "cm²"),
    "part_weight_g": ("Net weight of one part", "g"),
    "part_volume_cm3": ("Volume of one part", "cm³"),
    "part_surface_cm2": ("Surface area of one part", "cm²"),
}
FEATURE_VARS = {
    "cavities": ("Cavities per tool", "pcs"),
    "hot_runner": ("Hot runner (1 = yes)", ""),
    "slides_per_cavity": ("Slides per cavity", "pcs"),
    "lifters_per_cavity": ("Lifters per cavity", "pcs"),
    "inserts_per_cavity": ("Small inserts per cavity", "pcs"),
}
SUM_CHUNK = 30  # terms per sum formula (formulas are limited to 500 characters)


class ToolCostError(ValueError):
    pass


def _ref(store: str, table: str, match: dict, column: str, **extra) -> dict:
    """Where a master-data value lives, so the traceability panel can correct it there ("Save for the future")."""
    return {"store": store, "table": table, "match": match, "column": column} | extra


class ToolInput(mould.MouldInput):
    country: Optional[str] = None
    as_of: Optional[str] = None
    material: str = ""
    part_volume_cm3: float = Field(0, ge=0)
    part_surface_cm2: float = Field(0, ge=0)
    warranty: bool = True
    tools_count: int = Field(1, ge=1, le=1000)
    annual_volume: float = Field(0, ge=0)          # for the grade rules (0 = Parameters default)
    programme_years: float = Field(0, ge=0)
    bom: dict = Field(default_factory=dict)        # your changes per BOM line: {line key: {grade, make, qty, price_each, std_part}}
    learned: dict = Field(default_factory=dict)    # learned from your earlier parts: {element: {grade, make, std_part, note}}
    overrides: dict = Field(default_factory=dict)  # your changes of traced values for this part: {node id: {value | formula}}


def default_country() -> str:
    return (register_setup.settings().get("default_country") or "IN").upper()


class _Run:
    def __init__(self, inp: ToolInput, sources: dict | None):
        self.inp = inp
        self.sources = sources or {}
        self.setup = costing_setup.tables()
        countries = {c["code"]: c for c in self.setup["countries"]}
        self.country = (inp.country or default_country()).upper()
        if self.country not in countries:
            raise ToolCostError(f"Country '{self.country}' is not in Master data → Countries.")
        self.cur = countries[self.country]["currency"]
        self.as_of = inp.as_of or rates.current_month()
        self.trace = Trace(self.cur, inp.overrides)
        self.missing: list[str] = []
        self.db = mould_db.tables()
        self.time = mould_db.time_parameters(inp.part_type)
        self.machines = {m["machine_id"]: m for m in self.setup["machines"]}
        self.processes = {p["code"]: p for p in self.db["tool_processes"]}
        self.cache: dict = {}

    # ---------- inputs ----------

    def money_unit(self, per: str = "") -> str:
        return self.cur + (f"/{per}" if per else "")

    def miss(self, nid: str, label: str, note: str, unit: str = "", money: bool = False) -> str:
        self.missing.append(note)
        self.trace.add_input(nid, label, 0, unit, {"type": "missing", "note": note}, money=money)
        return nid

    def rate(self, nid: str, label: str, category: str, item: str, money: bool = True, optional: bool = False):
        """Node of an approved country rate, converted to the tool country's currency; None if optional and missing."""
        key = ("rate", category, item, money)
        if key in self.cache:
            return self.cache[key]
        try:
            r = rates.lookup(category, item, self.country, self.as_of)
        except rates.RateMissing as exc:
            if optional:
                self.cache[key] = None
                return None
            self.cache[key] = self.miss(nid, label, str(exc), money=money)
            return self.cache[key]
        self.trace.add_rate(nid, label, r, money=money)
        out = nid
        if money:
            try:
                out = rate_engine._convert(self.trace, nid, label, r["currency"], self.cur, self.as_of)
            except rates.RateMissing as exc:
                out = self.miss(f"{nid}:fx", f"{label} (currency)", str(exc), money=True)
        self.cache[key] = out
        return out

    def from_inr(self, nid: str, label: str) -> str:
        """A catalogue price in INR, converted to the tool country's currency."""
        try:
            return rate_engine._convert(self.trace, nid, label, rates.BASE_CURRENCY, self.cur, self.as_of)
        except rates.RateMissing as exc:
            return self.miss(f"{nid}:fx", f"{label} (currency)", str(exc), money=True)

    def master(self, nid: str, label: str, value, unit: str, sheet: str, row: str, example: bool = False,
               ref: dict | None = None) -> str:
        if nid not in self.trace.nodes:
            src = {"type": "master", "sheet": sheet, "row": row, "is_example": bool(example)}
            if ref:
                src["ref"] = ref
            self.trace.add_input(nid, label, value, unit, src)
        return nid

    def sub_overrides(self, prefix: str) -> dict:
        return {k[len(prefix):]: v for k, v in (self.inp.overrides or {}).items() if k.startswith(prefix)}

    def embed(self, sub: dict, prefix: str, label: str) -> str:
        """Copy a rate-engine trace (MHR, labour rate) into this one; returns the node of its result."""
        for nid, n in sub["nodes"].items():
            m = dict(n, id=prefix + nid)
            if "inputs" in m:
                m["inputs"] = [{"name": i["name"], "node": prefix + i["node"]} for i in m["inputs"]]
            self.trace.nodes[prefix + nid] = m
        for r in sub["rates_used"]:
            self.trace.rates_used[r["id"]] = r
        root = prefix + sub["root"]
        self.trace.nodes[root]["label"] = label
        return root

    def mhr(self, machine_id: str) -> str:
        key = ("mhr", machine_id)
        if key not in self.cache:
            m = self.machines.get(machine_id)
            label = f"MHR {machine_id}" + (f" · {m['name']}" if m else "")
            try:
                self.cache[key] = self.embed(rate_engine.mhr(machine_id, self.country, self.as_of, self.sub_overrides(f"mhr:{machine_id}:")),
                                             f"mhr:{machine_id}:", label)
            except (rates.RateError, rate_engine.EngineError, formula.FormulaError) as exc:
                self.cache[key] = self.miss(f"mhr:{machine_id}", label, str(exc), self.money_unit("h"), True)
        return self.cache[key]

    def labour(self, grade: str) -> str:
        key = ("labour", grade)
        if key not in self.cache:
            label = f"Labour rate · {grade}"
            try:
                self.cache[key] = self.embed(rate_engine.labour_rate(grade, self.country, self.as_of, self.sub_overrides(f"lab:{grade}:")),
                                             f"lab:{grade}:", label)
            except (rates.RateError, rate_engine.EngineError, formula.FormulaError) as exc:
                self.cache[key] = self.miss(f"lab:{grade}", label, str(exc), self.money_unit("h"), True)
        return self.cache[key]

    def crew(self, tp: dict, nid: str, mhr_node: str | None) -> str:
        """Cost per hour of a process: MHR (if any) + operators × labour rate of their grade."""
        names, terms = {}, []
        if mhr_node:
            names["mhr"] = mhr_node
            terms.append("mhr")
        if tp["operators"]:
            names["operators"] = self.master(f"ops:{tp['code']}", f"Operators · {tp['code']}", tp["operators"], "persons",
                                             "Mould & die database → Tool processes", tp["code"], tp["is_example"],
                                             ref=_ref("mould_db", "tool_processes", {"code": tp["code"]}, "operators"))
            names["labour"] = self.labour(tp["labour_grade"])
            terms.append("operators * labour")
        if not terms:
            return self.master(f"{nid}:none", f"{tp['code']}: no machine or operators", 0, self.money_unit("h"),
                               "Mould & die database → Tool processes", tp["code"], tp["is_example"])
        self.trace.compute(nid, f"{tp['code']}: cost per hour", " + ".join(terms), self.money_unit("h"), money=True,
                           names=names, description=f"Priced by {tp['pricing'].replace('_', ' ')} (Tool processes row "
                                                    f"'{tp['code']}'), with the {self.country} rates of {self.as_of}.")
        return nid

    def per_hour(self, tp: dict) -> str:
        key = ("per_hour", tp["code"])
        if key not in self.cache:
            mhr_node = self.mhr(tp["machine_id"]) if tp["pricing"] == "machine_hour" else None
            self.cache[key] = self.crew(tp, f"ph:{tp['code']}", mhr_node)
        return self.cache[key]

    # ---------- rule variables ----------

    def var(self, name: str) -> str:
        """Node of a rule variable, created the first time a rule uses it."""
        nid = f"v:{name}"
        if nid in self.trace.nodes:
            return nid
        i, t = self.inp, self.trace
        sz = self.sized
        if name in PART_VARS:
            label, unit = PART_VARS[name]
            src = self.sources.get(name) or {"type": "user", "note": "Estimate page"}
            t.add_input(nid, label, float(getattr(i, {"part_l": "part_length_mm", "part_w": "part_width_mm",
                                                      "part_h": "part_height_mm"}.get(name, name))), unit, src)
        elif name in FEATURE_VARS:
            label, unit = FEATURE_VARS[name]
            src = self.sources.get(name) or {"type": "user", "note": "Tool features"}
            t.add_input(nid, label, float(getattr(i, name)), unit, src)
        elif name in mould.SIZING_KEYS:
            r = sz["rules"][name]
            self.master(nid, r["description"] or name, r["value"], r["unit"], "Mould & die database → Sizing rules",
                        f"{i.part_type} / {name}", r["is_example"],
                        ref=_ref("mould_db", "sizing_rules", {"part_type": i.part_type, "parameter": name}, "value"))
        elif name == "insert_each_l":
            t.compute(nid, "Insert length per cavity", "part_l + 2 * insert_wall_mm", "mm",
                      names={"part_l": self.var("part_l"), "insert_wall_mm": self.var("insert_wall_mm")})
        elif name == "insert_each_w":
            t.compute(nid, "Insert width per cavity", "part_w + 2 * insert_wall_mm", "mm",
                      names={"part_w": self.var("part_w"), "insert_wall_mm": self.var("insert_wall_mm")})
        elif name == "insert_half_h":
            t.compute(nid, "Insert height per half (core or cavity)", "part_h / 2 + insert_backing_mm", "mm",
                      names={"part_h": self.var("part_h"), "insert_backing_mm": self.var("insert_backing_mm")})
        elif name in ("layout_rows", "layout_cols"):
            lay = sz["layout"]
            t.add_derived(nid, "Cavity layout rows" if name == "layout_rows" else "Cavity layout columns",
                          lay["rows" if name == "layout_rows" else "cols"], "",
                          "every rows × columns grid of the inserts is tried; the one that needs the smallest standard "
                          "mould base wins (ties: fewer empty positions, then the squarer pocket)",
                          {k: self.var(k) for k in ("cavities", "insert_each_l", "insert_each_w", "insert_gap_mm")},
                          description=f"{lay['rows']} × {lay['cols']}" + (f", {lay['empty']} empty" if lay["empty"] else ""))
        elif name == "pocket_l":
            t.compute(nid, "Insert pocket length", "layout_cols * insert_each_l + (layout_cols - 1) * insert_gap_mm", "mm",
                      names={k: self.var(k) for k in ("layout_cols", "insert_each_l", "insert_gap_mm")})
        elif name == "pocket_w":
            t.compute(nid, "Insert pocket width", "layout_rows * insert_each_w + (layout_rows - 1) * insert_gap_mm", "mm",
                      names={k: self.var(k) for k in ("layout_rows", "insert_each_w", "insert_gap_mm")})
        elif name in ("base_l", "base_w", "base_stack_h", "base_weight_kg"):
            b = sz["base"]
            field, label, unit = {"base_l": ("length_mm", "Mould base length", "mm"),
                                  "base_w": ("width_mm", "Mould base width", "mm"),
                                  "base_stack_h": ("stack_height_mm", "Mould base stack height", "mm"),
                                  "base_weight_kg": ("weight_kg", "Mould base weight", "kg")}[name]
            self.master(nid, label, b[field], unit, "Mould & die database → Mould bases",
                        f"{b['series']} {b['size_code']}", b["is_example"],
                        ref=_ref("mould_db", "mould_bases", {"part_type": b["part_type"], "series": b["series"],
                                                             "size_code": b["size_code"]}, field))
        elif name == "part_box_cm3":
            t.compute(nid, "Part bounding box", "part_l * part_w * part_h / 1000", "cm³",
                      names={k: self.var(k) for k in ("part_l", "part_w", "part_h")},
                      description="Basis of the steel removed to form one cavity")
        elif name in ("annual_volume", "programme_years"):
            v = getattr(i, name)
            if v:
                t.add_input(nid, "Annual volume" if name == "annual_volume" else "Programme years", v,
                            "parts/yr" if name == "annual_volume" else "years",
                            self.sources.get(name) or {"type": "user", "note": "Tool features"})
            else:
                row = _parameter_row(i.part_type, name)
                self.master(nid, row["description"] if row else name, (row or {}).get("value") or 0,
                            (row or {}).get("unit") or "", "Parameters", f"{(row or {}).get('part_type', 'all')} / {name}",
                            ref=_ref("master_data", "Parameters", {"part_type": (row or {}).get("part_type", "all"),
                                                                   "parameter": name}, "value") if row else None)
        elif name == "programme_shots":
            t.compute(nid, "Shots (strokes) over the programme per tool", "annual_volume * programme_years / cavities", "shots",
                      names={k: self.var(k) for k in ("annual_volume", "programme_years", "cavities")},
                      description="Basis of the grade rules (Mould & die database → Grade rules)")
        elif name in self.time:
            r = self.time[name]
            self.master(nid, r["description"] or name, r["value"], r["unit"],
                        "Mould & die database → Process time parameters", f"{i.part_type} / {name}", r["is_example"],
                        ref=_ref("mould_db", "time_parameters", {"part_type": i.part_type, "parameter": name}, "value"))
        else:
            raise ToolCostError(f"'{name}' is not a rule variable, and not a Process time parameter for {i.part_type}.")
        return nid

    def rule(self, nid: str, label: str, text: str, unit: str, element: str, column: str, density: str | None = None,
             money: bool = False) -> float:
        el = next((e for e in self.db["bom_elements"] if e["part_type"] == self.inp.part_type and e["element"] == element), {})
        names = {}
        try:
            for n in formula.names(text):
                if n == "density":
                    if not density:
                        raise ToolCostError(f"BOM element '{element}', {column}: 'density' needs a material on the row.")
                    names[n] = density
                else:
                    names[n] = self.var(n)
            v = self.trace.compute(nid, label, text, unit, money=money, names=names,
                                   description=f"Rule '{column}' of BOM element '{element}' (Mould & die database → BOM elements). "
                                               "The numbers written in the rule are its constants; every name is an input below."
                                               + (f" Notes: {el['notes']}" if el.get("notes") else ""))
            self.trace.nodes[nid]["ref"] = _ref("mould_db", "bom_elements", {"part_type": self.inp.part_type, "element": element}, column)
            return v
        except formula.FormulaError as exc:
            raise ToolCostError(f"BOM element '{element}', {column}: {exc}") from None

    # ---------- sums ----------

    def total(self, nid: str, label: str, nodes: list[str], unit: str, money: bool = True, description: str = "") -> str:
        if not nodes:
            self.trace.add_input(nid, label, 0, unit, {"type": "base", "note": "No BOM line in this group."}, money=money)
            return nid
        if len(nodes) > SUM_CHUNK:  # sub-totals, so no formula gets too long
            parts = [self.total(f"{nid}:{k}", f"{label} (part {k + 1})", nodes[s:s + SUM_CHUNK], unit, money)
                     for k, s in enumerate(range(0, len(nodes), SUM_CHUNK))]
            return self.total(nid, label, parts, unit, money, description)
        names = {f"x{k}": n for k, n in enumerate(nodes)}
        self.trace.compute(nid, label, " + ".join(names), unit, money=money, names=names, description=description)
        return nid

    # ---------- the calculation ----------

    # ---------- BOM: suggested grade and make, your changes ----------

    def elements(self) -> list[dict]:
        """BOM elements of this tool (the sheet-metal die engine keeps the ones of the die's operations)."""
        return [el for el in self.db["bom_elements"] if el["part_type"] == self.inp.part_type]

    def line_key(self, element: str) -> str:
        return element

    def base_label(self) -> str:
        b = self.sized["base"]
        return f"Mould base {b['series']} {b['size_code']}"

    def suggest_grade(self, el: dict) -> tuple[str, str, int | None]:
        """(grade, reason, grade rule row) from Grade rules: the first rule of the element that applies."""
        material = (self.inp.material or "").lower()
        tokens = set(re.split(r"[^a-z0-9]+", material))
        rules = sorted((r for r in self.db.get("grade_rules", []) if r["part_type"] == self.inp.part_type
                        and r["element"] == el["element"]), key=lambda r: r["step"])
        for r in rules:
            words = [w.strip().lower() for w in (r["material_contains"] or "").split(",") if w.strip()]
            # a short keyword (GF, PC) matches the start of a word of the material (GF30, PC/ABS); a longer one anywhere
            if words and not any(any(tok.startswith(w) for tok in tokens) if len(w) <= 3 else (w in material) for w in words):
                continue
            env = {}
            try:
                for n in formula.names(r["condition"]):
                    env[n] = self.trace.value(self.var(n))
                if not formula.evaluate(r["condition"], env):
                    continue
            except (formula.FormulaError, ToolCostError) as exc:
                raise ToolCostError(f"Grade rules, {el['element']} order {r['step']:g}: {exc}") from None
            return r["material_code"], r["reason"], r
        return el["material_code"], "BOM element default", None

    def override(self, key: str) -> dict:
        return (self.inp.bom or {}).get(key) or {}

    def bom(self) -> list[dict]:
        t, cur = self.trace, self.cur
        b = self.sized["base"]
        base_key = self.line_key("__base__")
        ov_base = self.override(base_key)
        base_label = self.base_label()
        if ov_base.get("price_each") is not None:
            base_inr = f"{base_key}:you"
            t.add_input(base_inr, f"{base_label} · your price", float(ov_base["price_each"]), "INR",
                        {"type": "user", "note": "Your price (Tool cost → BOM, changed by you)"}, money=True)
        else:
            base_inr = self.master(f"{base_key}:cost_inr", f"{base_label} · catalogue price", b["cost"], "INR",
                                   "Mould & die database → Mould bases", f"{b['series']} {b['size_code']}", b["is_example"],
                                   ref=_ref("mould_db", "mould_bases", {"part_type": b["part_type"], "series": b["series"],
                                                                        "size_code": b["size_code"]}, "cost",
                                            choose_base=True, line_key=base_key, part_type=b["part_type"]))
        self.trace.nodes[base_inr]["money"] = True
        base_cost = self.from_inr(base_inr, f"{base_label} price")
        lines = [{"key": base_key, "element": base_label, "category": "bought_out", "quantity": 1,
                  "material": "", "grade": "", "grade_reason": "", "suggested_grade": "",
                  "make": ov_base.get("make") or b.get("make") or "", "suggested_make": b.get("make") or "",
                  "weight_each_kg": b["weight_kg"], "material_cost": 0, "bought_out_cost": t.value(base_cost),
                  "process": "", "pricing": "", "cost_group": "", "hours": 0, "amount": 0, "process_cost": 0,
                  "total": t.value(base_cost), "is_example": bool(b["is_example"]), "is_base": True,
                  "std_part": "", "part_number": "", "learned": "",
                  "changed": sorted(k for k in ov_base if ov_base[k] not in (None, "")),
                  "nodes": {"bo": base_cost, "total": base_cost, "made_kg": None, "mat": None, "proc": None}}]
        materials = {m["code"]: m for m in self.db["tool_materials"]}
        k = 0
        for el in self.elements():
            k += 1
            tag, name = f"bom:{el['element']}", el["element"]   # by name, so your changes stay on the same line
            key = self.line_key(name)
            ov = self.override(key)
            if ov.get("qty") is not None:
                t.add_input(f"{tag}:qty", f"{name} · quantity", float(ov["qty"]), "pcs",
                            {"type": "user", "note": "Your quantity (Tool cost → BOM, changed by you)"})
                qty = float(ov["qty"])
            else:
                qty = self.rule(f"{tag}:qty", f"{name} · quantity", el["quantity_rule"], "pcs", name, "quantity_rule")
            if qty <= 0:
                del t.nodes[f"{tag}:qty"]
                continue
            q = f"{tag}:qty"
            grade, reason, _ = self.suggest_grade(el) if el["material_code"] else ("", "", None)
            learned = (self.inp.learned or {}).get(name) or {}
            if learned and not ov:
                ov = {k: learned[k] for k in ("grade", "make", "std_part") if learned.get(k)}
                if learned.get("grade") and learned["grade"] in materials:
                    grade, reason = learned["grade"], f"learned from your earlier parts ({learned.get('note', '')})".replace(" ()", "")
                ov.pop("grade", None)
                ov["_learned"] = learned.get("note") or "earlier parts"
            if not ov.get("std_part") and ov.get("price_each") is None:
                if el.get("std_part"):
                    ov = dict(ov, std_part=el["std_part"])
                elif el.get("price_each_inr"):          # blank / 0 in master data = not set: the line is calculated
                    ov = dict(ov, price_each=el["price_each_inr"], _price_from="master")
            suggested = grade
            if ov.get("grade"):
                if ov["grade"] not in materials:
                    raise ToolCostError(f"BOM line '{name}': grade '{ov['grade']}' is not in Tool materials.")
                grade, reason = ov["grade"], "your choice"
            mat = materials.get(grade)
            line = {"key": key, "element": name, "category": el["category"], "quantity": qty, "material": grade,
                    "grade": grade, "grade_reason": reason, "suggested_grade": suggested,
                    "make": ov.get("make") or el.get("make") or (mat or {}).get("make") or "",
                    "suggested_make": el.get("make") or (mat or {}).get("make") or "",
                    "weight_each_kg": 0, "material_cost": 0, "bought_out_cost": 0, "process": el["process_code"],
                    "pricing": "", "cost_group": "", "hours": 0, "amount": 0, "process_cost": 0,
                    "is_example": bool(el["is_example"]),
                    "changed": sorted(k2 for k2 in (self.override(key)) if self.override(key)[k2] not in (None, "")),
                    "learned": ov.get("_learned") or "", "std_part": "", "part_number": "", "nodes": {"qty": q}}
            parts = []
            density = None
            if mat:
                density = self.master(f"den:{mat['code']}", f"Density of {mat['code']}", mat["density_g_cm3"], "g/cm³",
                                      "Mould & die database → Tool materials", mat["code"], mat["is_example"],
                                      ref=_ref("mould_db", "tool_materials", {"code": mat["code"]}, "density_g_cm3"))
                line["weight_each_kg"] = self.rule(f"{tag}:wt", f"{name} · weight each", el["weight_rule"], "kg", name,
                                                   "weight_rule", density)
                t.compute(f"{tag}:kg", f"{name} · steel weight", "qty * weight", "kg", names={"qty": q, "weight": f"{tag}:wt"})
                line["nodes"]["made_kg"] = f"{tag}:kg"
            sp = None
            if ov.get("std_part") and ov.get("price_each") is None:
                sp = next((x for x in self.db.get("standard_parts", []) if x["code"] == ov["std_part"]), None)
                if not sp:
                    raise ToolCostError(f"BOM line '{name}': standard part '{ov['std_part']}' is not in Standard parts.")
                line["std_part"], line["make"] = sp["code"], ov.get("make") or sp["make"]
                line["part_number"] = sp.get("part_number") or ""
                node = self.master(f"{tag}:sp", f"{name} · {sp['make']} {sp.get('part_number') or sp['code']} · {sp['description']}", sp["price"],
                                   sp["currency"], "Mould & die database → Standard parts", sp["code"], sp["is_example"],
                                   ref=_ref("mould_db", "standard_parts", {"code": sp["code"]}, "price"))
                t.nodes[node]["money"] = True
                try:
                    each = rate_engine._convert(t, node, f"{name} · {sp['code']}", sp["currency"], cur, self.as_of)
                except rates.RateMissing as exc:
                    each = self.miss(f"{tag}:sp:fx", f"{name} · {sp['code']} (currency)", str(exc), money=True)
                line["bought_out_cost"] = t.compute(f"{tag}:bo", f"{name} · {sp['code']}", "qty * each", cur, money=True,
                                                    names={"qty": q, "each": each})
                line["nodes"]["bo"] = f"{tag}:bo"
                line["is_example"] = bool(sp["is_example"])
                self.total(tag, name, [f"{tag}:bo"], cur)
                line["nodes"]["total"] = tag
                lines.append(line)
                continue
            if ov.get("price_each") is not None:
                # your price per piece replaces the calculated cost of the whole line (steel, bought-out and processes)
                if ov.get("_price_from") == "master":
                    self.master(f"{tag}:you", f"{name} · price each (BOM element default)", float(ov["price_each"]), "INR",
                                "Mould & die database → BOM elements", f"{self.inp.part_type} / {name} · price each", el["is_example"],
                                ref=_ref("mould_db", "bom_elements", {"part_type": el["part_type"], "element": name}, "price_each_inr"))
                    t.nodes[f"{tag}:you"]["money"] = True
                else:
                    t.add_input(f"{tag}:you", f"{name} · your price each", float(ov["price_each"]), "INR",
                                {"type": "user", "note": "Your price per piece in INR (Tool cost → BOM, changed by you)"}, money=True)
                each = self.from_inr(f"{tag}:you", f"{name} · your price each")
                line["bought_out_cost"] = t.compute(f"{tag}:bo", f"{name} · your price", "qty * each", cur, money=True,
                                                    names={"qty": q, "each": each})
                line["nodes"]["bo"] = f"{tag}:bo"
                line["price_each_inr"] = float(ov["price_each"])
                self.total(tag, name, [f"{tag}:bo"], cur)
                line["nodes"]["total"] = tag
                lines.append(line)
                continue
            if mat:
                steel = self.rate(f"steel:{mat['code']}", f"Steel rate · {mat['code']}", "tool_material", mat["code"])
                line["material_cost"] = t.compute(f"{tag}:mat", f"{name} · steel", "qty * weight * rate", cur, money=True,
                                                  names={"qty": q, "weight": f"{tag}:wt", "rate": steel})
                line["nodes"]["mat"] = f"{tag}:mat"
                parts.append(f"{tag}:mat")
            if el["unit_cost_rule"] not in ("", "0"):
                self.rule(f"{tag}:each", f"{name} · catalogue price each", el["unit_cost_rule"], "INR", name,
                          "unit_cost_rule", density, money=True)
                each = self.from_inr(f"{tag}:each", f"{name} · price each")
                line["bought_out_cost"] = t.compute(f"{tag}:bo", f"{name} · bought-out", "qty * each", cur, money=True,
                                                    names={"qty": q, "each": each})
                line["nodes"]["bo"] = f"{tag}:bo"
                parts.append(f"{tag}:bo")
            if el["process_code"]:
                tp = self.processes.get(el["process_code"])
                if not tp:
                    raise ToolCostError(f"BOM element '{name}': process '{el['process_code']}' is not in Tool processes.")
                line["pricing"], line["cost_group"] = tp["pricing"], tp["cost_group"]
                if tp["pricing"] == "unit":
                    line["amount"] = self.rule(f"{tag}:amt", f"{name} · amount each", el["amount_rule"], "", name,
                                               "amount_rule", density)
                    unit_rate = self.rate(f"pu:{tp['code']}", f"Rate · {tp['code']}", "process_unit", tp["code"])
                    basis = t.nodes[unit_rate]["unit"].split("/", 1)[-1]
                    t.nodes[f"{tag}:amt"]["unit"] = basis
                    names = {"qty": q, "amount": f"{tag}:amt", "rate": unit_rate}
                    minimum = self.rate(f"pmin:{tp['code']}", f"Minimum charge per job · {tp['code']}",
                                        "process_min_charge", tp["code"], optional=True)
                    text = "qty * amount * rate"
                    if minimum:
                        names["min_charge"] = minimum
                        text = "max(min_charge, qty * amount * rate)"
                    line["process_cost"] = t.compute(f"{tag}:proc", f"{name} · {tp['code']}", text, cur, money=True,
                                                     names=names, description="Amount × rate by unit of the tool country"
                                                     + (", at least the minimum charge per job" if minimum else ""))
                    line["nodes"]["amount"] = f"{tag}:amt"
                else:
                    self.rule(f"{tag}:h", f"{name} · hours each", el["hours_rule"], "h", name, "hours_rule", density)
                    line["hours"] = t.compute(f"{tag}:hrs", f"{name} · hours", "qty * hours", "h",
                                              names={"qty": q, "hours": f"{tag}:h"})
                    per_hour = self.per_hour(tp)
                    line["process_cost"] = t.compute(f"{tag}:proc", f"{name} · {tp['code']}", "hours * cost_per_hour", cur,
                                                     money=True, names={"hours": f"{tag}:hrs", "cost_per_hour": per_hour})
                    line["nodes"]["hours"] = f"{tag}:hrs"
                line["nodes"]["proc"] = f"{tag}:proc"
                parts.append(f"{tag}:proc")
            if parts:
                self.total(tag, name, parts, cur)
            else:
                self.master(tag, name, 0, cur, "Mould & die database → BOM elements", name, el["is_example"])
            line["nodes"]["total"] = tag
            lines.append(line)
        return lines

    def size(self) -> dict:
        return mould.size(self.inp)

    def trial(self) -> dict:
        """Clamp force (formulas of tool_clamp) -> try-out machine -> its MHR and the try-out crew per hour."""
        names = self.scope_inputs("tool_clamp")
        try:
            force_node, _, _ = rate_engine.evaluate_scope(self.trace, self.setup, "tool_clamp", names, self.cur, self.as_of, inr=False)
        except (rate_engine.EngineError, formula.FormulaError) as exc:
            raise ToolCostError(str(exc)) from None
        return self.trial_machine(force_node, "clamp force")

    def trial_machine(self, force_node: str, what: str) -> dict:
        """Smallest try-out machine (Parameters → trial_machine_process) whose tonnage takes the force; its MHR and crew."""
        t, part_type = self.trace, self.inp.part_type
        force = t.value(force_node)
        process = master_data.parameters(part_type).get("trial_machine_process")
        out = {"force_node": force_node, "force_t": force, "process": process, "machine": None}
        trial = next((p for p in self.db["tool_processes"] if p["cost_group"] == "trial"), None)
        if not process:
            self.miss("trial:machine", "Try-out machine", f"Master data → Parameters has no 'trial_machine_process' for {part_type}.", "t")
            mhr_node = "trial:machine"
        else:
            fits = sorted((m for m in self.machines.values() if m["process"] == process and (m["tonnage_t"] or 0) >= force),
                          key=lambda m: m["tonnage_t"])
            if not fits:
                biggest = max((m["tonnage_t"] or 0 for m in self.machines.values() if m["process"] == process), default=0)
                self.miss("trial:machine", "Try-out machine",
                          f"No '{process}' machine in Master data → Machines takes {force:.0f} t (largest: {biggest:g} t). "
                          "Add a bigger machine or use fewer cavities.", "t")
                mhr_node = "trial:machine"
            else:
                m = fits[0]
                out["machine"] = m
                t.add_derived("trial:machine", f"Try-out machine: {m['machine_id']} · {m['name']}", m["tonnage_t"], "t",
                              f"smallest '{process}' machine in Master data → Machines whose tonnage ≥ the {what}",
                              {what.replace(" ", "_"): force_node},
                              description=f"{m['tonnage_t']:g} t ≥ {force:.1f} t. Rule: Parameters → trial_machine_process.")
                mhr_node = self.mhr(m["machine_id"])
        if trial:
            crew = self.crew(trial | {"pricing": "labour_hour"}, "trial:crew", None) if trial["operators"] else \
                self.master("trial:crew", "Try-out crew per hour", 0, self.money_unit("h"),
                            "Mould & die database → Tool processes", trial["code"], trial["is_example"])
            t.nodes[crew]["label"] = "Try-out crew per hour (operators × labour rate)"
        else:
            crew = self.miss("trial:crew", "Try-out crew per hour",
                             "Mould & die database → Tool processes has no row of cost group 'trial' (the try-out).",
                             self.money_unit("h"), True)
        out |= {"mhr_node": mhr_node, "crew_node": crew}
        return out

    def scope_inputs(self, scope: str) -> dict:
        names = {}
        rows = [r for r in self.setup["formula_inputs"] if r["scope"] == scope]
        if not rows:
            raise ToolCostError(f"Master data has no formula inputs for the scope '{scope}' (Countries, machines & formulas).")
        for inp in rows:
            var, label = inp["variable"], inp["label"] or inp["variable"]
            nid = f"{scope}:in:{var}"
            if inp["source"] == "rate":
                if "{material}" in inp["item"] and not self.inp.material:
                    names[var] = self.miss(nid, label, f"{label}: set the part material first.", inp["unit"], bool(inp["is_money"]))
                    continue
                item = inp["item"].format(material=self.inp.material, machine="", grade="")
                names[var] = self.rate(nid, label, inp["category"], item, money=bool(inp["is_money"]))
            elif inp["source"] == "parameter":
                row = _parameter_row(self.inp.part_type, inp["item"])
                if row is None or not isinstance(row["value"], (int, float)):
                    raise ToolCostError(f"{label}: Master data → Parameters has no number '{inp['item']}' for {self.inp.part_type}.")
                names[var] = self.master(nid, label, row["value"], inp["unit"] or row["unit"] or "", "Parameters",
                                         f"{row['part_type']} / {inp['item']}",
                                         ref=_ref("master_data", "Parameters", {"part_type": row["part_type"], "parameter": inp["item"]}, "value"))
            elif inp["source"] == "tool":
                if inp["item"] not in self.tool_items:
                    raise ToolCostError(f"{label}: '{inp['item']}' is not a tool engine value.")
                names[var] = self.tool_items[inp["item"]]
            else:
                raise ToolCostError(f"Formula input '{var}' of {scope} has source '{inp['source']}', which the tool engine "
                                    "cannot use.")
        return names

    def run(self) -> dict:
        inp, t, cur = self.inp, self.trace, self.cur
        try:
            self.sized = self.size()
        except ValueError as exc:
            raise ToolCostError(str(exc)) from None
        chosen = self.override(self.line_key("__base__")).get("base")
        if chosen:  # the mould base / die set you picked for this part instead of the smallest that fits
            row = next((b for b in self.db["mould_bases"] if b["part_type"] == inp.part_type and b["size_code"] == chosen), None)
            if not row:
                raise ToolCostError(f"Mould base / die set '{chosen}' is not in Mould bases for {inp.part_type}.")
            auto = self.sized["base"]
            if row["max_insert_length_mm"] * row["max_insert_width_mm"] < auto["max_insert_length_mm"] * auto["max_insert_width_mm"]:
                self.sized["warnings"] = list(self.sized.get("warnings") or []) + [
                    f"Your base {row['size_code']} is smaller than the one that fits ({auto['size_code']}): check it."]
            self.sized["base"] = row
        lines = self.bom()

        mats = [l["nodes"]["mat"] for l in lines if l["nodes"].get("mat")]
        bos = [l["nodes"]["bo"] for l in lines if l["nodes"].get("bo")]
        groups = []
        for g in mould_db.COST_GROUPS:
            procs = [l["nodes"]["proc"] for l in lines if l["nodes"].get("proc") and l["cost_group"] == g]
            if procs:
                groups.append({"group": g, "label": GROUP_LABEL.get(g, g),
                               "node": self.total(f"group:{g}", GROUP_LABEL.get(g, g), procs, cur)})
        self.total("sum:material", "Tool steel", mats, cur, description="Σ quantity × weight × steel rate")
        self.total("sum:bought_out", "Mould base & standard parts", bos, cur,
                   description="Σ quantity × catalogue price (INR), converted to the tool country's currency")
        self.total("sum:process", "Processes (design excluded)", [g["node"] for g in groups if g["group"] != "design"], cur,
                   description="Σ of the process cost groups")
        self.total("sum:design", "Design", [g["node"] for g in groups if g["group"] == "design"], cur)
        self.var("base_weight_kg")
        self.total("tool_weight", "Tool weight", ["v:base_weight_kg"] + [l["nodes"]["made_kg"] for l in lines
                                                                         if l["nodes"].get("made_kg")], "kg", money=False,
                   description="Mould base + steel of the made BOM elements")
        t.compute("shot_weight", "Shot weight (net)", "cavities * part_weight_g / 1000", "kg",
                  names={"cavities": self.var("cavities"), "part_weight_g": self.var("part_weight_g")})
        t.add_input("warranty_on", "Warranty / spares included (1 = yes)", 1 if inp.warranty else 0, "",
                    self.sources.get("warranty_on") or {"type": "user", "note": "Tool features"})
        t.add_input("tools_count", "Tools over the programme", inp.tools_count, "tools",
                    self.sources.get("tools_count") or {"type": "user", "note": "Tool features"})
        self.tool_items = {"cavities": self.var("cavities"), "projected_area_cm2": self.var("projected_area_cm2"),
                           "shot_weight_kg": "shot_weight", "material_cost": "sum:material",
                           "bought_out_cost": "sum:bought_out", "process_cost": "sum:process", "design_cost": "sum:design",
                           "tool_weight_kg": "tool_weight", "warranty_on": "warranty_on", "tools_count": "tools_count"}
        trial = self.trial()
        self.tool_items |= {"trial_mhr": trial["mhr_node"], "trial_labour_per_h": trial["crew_node"]}

        names = self.scope_inputs("tool")
        try:
            result, components, order = rate_engine.evaluate_scope(t, self.setup, "tool", names, cur, self.as_of)
        except rates.RateMissing as exc:
            self.missing.append(str(exc))
            raise ToolCostError(str(exc)) from None
        except (rate_engine.EngineError, formula.FormulaError) as exc:
            raise ToolCostError(str(exc)) from None
        capex = capex_inr = None
        if "calc:tool_capex" in t.nodes:
            capex = t.value("calc:tool_capex")
            capex_inr = t.compute("capex:inr", "Tool CAPEX in INR", "value * fx", "INR", money=True,
                                  names={"value": "calc:tool_capex", "fx": rate_engine.fx_to_inr(t, cur, self.as_of)},
                                  description=f"Converted with the INR per {cur} forex rate of {self.as_of}.")

        out = t.to_dict(result)
        for line in lines:  # values of the nodes, for the table
            line["total"] = t.value(line["nodes"]["total"])
        example = examples(out, lines)
        out |= {
            "part_type": inp.part_type, "country": self.country, "currency": cur, "as_of": self.as_of,
            "material": inp.material, "value": t.value(result), "value_inr": t.value("result:inr"),
            "capex": capex, "capex_inr": capex_inr, "capex_node": "calc:tool_capex" if capex is not None else None,
            "tools_count": inp.tools_count, "cavities": inp.cavities, "components": components,
            "layout": self.sized["layout"], "base": self.sized["base"], "base_turned": self.sized["base_turned"],
            "sizing_rules_are_examples": self.sized["sizing_rules_are_examples"],
            "lines": lines, "groups": groups,
            "totals": {"material_cost": "sum:material", "bought_out_cost": "sum:bought_out", "process_cost": "sum:process",
                       "design_cost": "sum:design", "tool_weight_kg": "tool_weight"},
            "steps": [{"name": r["name"], "node": f"calc:{r['name']}", "is_result": bool(r["is_result"])} for r in order],
            "trial": {"force_node": trial["force_node"], "force_t": trial["force_t"], "process": trial["process"],
                      "machine": trial["machine"], "machine_node": "trial:machine"},
            "missing": self.missing, "priced": not self.missing, "warnings": self.sized["warnings"], "example": example,
        }
        return out


def examples(tr: dict, lines: list[dict] | None = None) -> dict:
    """Which EXAMPLE values a traced result uses: library rates, and master-data rows (machines, BOM, ...)."""
    rate_ids = sorted(r["id"] for r in tr["rates_used"] if r.get("is_example"))
    rows = set()
    for n in tr["nodes"].values():
        s = n.get("source") or {}
        if s.get("is_example") and s.get("type") == "machine":
            rows.add(f"Machines · {s.get('machine_id')}")
        elif s.get("is_example") and s.get("type") == "master":
            rows.add(f"{s.get('sheet', '').split('→')[-1].strip()} · {s.get('row')}")
    for line in lines or tr.get("lines") or []:
        if line.get("is_example") and not line.get("is_base"):  # the base row is counted by its node above
            rows.add(f"BOM elements · {line['element']}")
    rows = sorted(rows)
    parts = []
    if rate_ids:
        parts.append(f"{len(rate_ids)} EXAMPLE rate{'s' if len(rate_ids) != 1 else ''} (Rates page)")
    if rows:
        parts.append(f"{len(rows)} EXAMPLE master-data row{'s' if len(rows) != 1 else ''} (Master data)")
    return {"any": bool(rate_ids or rows), "rates": len(rate_ids), "rate_ids": rate_ids, "rows": rows,
            "warning": EXAMPLE_WARNING if (rate_ids or rows) else "",
            "detail": ("Uses " + " and ".join(parts) + ". Replace them with real values.") if parts else ""}


def run(inp: ToolInput, sources: dict | None = None) -> dict:
    """Tool cost of one mould / die. `sources` gives the source of part values (e.g. the 3D file of a revision)."""
    if inp.part_type not in PART_TYPES:
        raise ToolCostError(LATER.get(inp.part_type, f"There is no tool cost for '{inp.part_type}' yet."))
    return _Run(inp, sources).run()
