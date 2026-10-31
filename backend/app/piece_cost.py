"""Part (piece) cost per part, fully traced (roadmap stage 8).

    piece cost = RM + process (cycle × MHR of the selected machine + operators × labour rate) + secondary operations
               + inserts (BOP price × quantity + handling) + rejection (incl. inserts lost with a reject)
               + overhead + profit + packing + tool amortisation + logistics

The steps are the Cost formulas of scope "piece" (Countries, machines & formulas). Their inputs are Formula inputs
of that scope: Parameters rows (source parameter), the rate library (source rate) or a value worked out here
(source piece, see costing_setup.PIECE_ITEMS): the stored RM and tool cost versions of the current revision, the
machine picked by the tool clamp force with its MHR and the operator labour rate (both grafted with their full
trace), the inserts and the Insert moulding rules. Every value you can type over per part is in PIECE_TYPED.
"""

from __future__ import annotations

from . import costing_setup, master_data, mould_db, rate_engine, rates, register_setup
from .trace import Trace

SCOPE = "piece"
PIECE_TYPED = {"cycle_s": "Cycle time (s)", "cavities": "Cavities per tool", "secondary_ops_pct": "Secondary operations (% of process)"}


# Press speed rules of sheet-metal parts (Design rules rows of part type sheet_metal, EXAMPLE until you replace them).
CYCLE_RULES = {
    "press_spm": (40, "1/min", "Press strokes per minute of a progressive die with automatic feed (part-cost cycle time, stage 39)"),
    "press_spm_manual": (20, "1/min", "Press strokes per minute of single-stage dies fed by hand or robot (multi-stage: one stroke per operation)"),
    "press_spm_draw_factor": (0.6, "-", "Press speed factor for a drawn part (deeper draws run slower)"),
}


class PieceError(ValueError):
    pass


def seed() -> int:
    """Add the press-speed Design rules rows that are missing (existing rows are never changed)."""
    d = mould_db.tables()
    have = {(r["part_type"], r["parameter"]) for r in d["design_rules"]}
    add = [{"part_type": "sheet_metal", "parameter": k, "value": v, "text": "", "unit": u, "description": desc, "is_example": True}
           for k, (v, u, desc) in CYCLE_RULES.items() if ("sheet_metal", k) not in have]
    if add:
        d["design_rules"] += add
        mould_db.write(d)
    return len(add)


def _cycle_rule(key: str) -> tuple[float, bool]:
    r = mould_db.design_rules("sheet_metal").get(key)
    if r and r["value"] is not None:
        return float(r["value"]), bool(r.get("is_example"))
    return float(CYCLE_RULES[key][0]), True


def calculated_cycle(part_id: int, part_type: str) -> tuple[float | None, str]:
    """The cycle time worked out for this part (s) and where it comes from; (None, reason) when it cannot be worked out.

    Moulds, dies, EPS and blow tools: the cycle of the simulation (fill + cooling + open / eject, insert loading).
    Sheet metal: strokes per part ÷ press speed (Design rules press_spm*), slower for drawn parts."""
    from . import register
    try:
        if part_type == "sheet_metal":
            res = register.sheet_tools_result(part_id)
            ops = res.get("operations") or []
            prog = res.get("mode") == "progressive"
            drawn = float((res.get("features") or {}).get("draw_depth") or 0) > 0
            spm, _ = _cycle_rule("press_spm" if prog else "press_spm_manual")
            strokes = 1 if prog else max(len(ops), 1)
            factor = _cycle_rule("press_spm_draw_factor")[0] if drawn else 1.0
            return strokes * 60 / (spm * factor), (
                f"Press speed rule: {strokes} stroke(s) per part ({'progressive die' if prog else 'one stroke per operation'}) at "
                f"{spm * factor:g} strokes/min{' (drawn part)' if drawn else ''}: Master data → Design rules press_spm*")
        _, _, res = register._simulate(part_id)
        cyc = res["results"].get("cycle_s")
        if cyc and cyc > 0:
            return float(cyc), "Cycle time of the part's simulation (fill + cooling + open / eject, insert loading), not the target"
        return None, "the simulation gave no cycle time"
    except (register.RegisterError, register.ToolNotApplicable, ValueError, KeyError) as exc:
        return None, str(exc)


def graft(t: Trace, sub: dict, prefix: str) -> str:
    """Copy another trace's nodes into t under a prefix; returns the copied root node id."""
    for nid, n in sub["nodes"].items():
        n = dict(n, id=prefix + nid)
        if "inputs" in n:
            n["inputs"] = [dict(i, node=prefix + i["node"]) for i in n["inputs"]]
        t.nodes[prefix + nid] = n
    for r in sub.get("rates_used", []):
        t.rates_used[r["id"]] = r
    return prefix + sub["root"]


def run(part_id: int, country: str | None = None) -> dict:
    from . import register
    d = register.part_detail(part_id, with_rm=False)
    if register.tool_eligibility(d):
        raise PieceError(register.tool_eligibility(d))
    part_type = register_setup.processes()[d["process"]]["part_type"]
    rev_id = d["current_revision_id"]
    if country:   # country comparison: RM and tool worked out live in that country
        from .tool_cost import ToolCostError
        from .rm_cost import RMError
        try:
            rl, tl = register._rm_compute(part_id, country), register._tool_compute(part_id, country)
        except (register.RegisterError, register.RMNotApplicable, register.ToolNotApplicable, RMError, ToolCostError) as exc:
            raise PieceError(str(exc)) from None
        if rl["missing"] or tl["missing"]:
            raise PieceError(" ".join(rl["missing"] + tl["missing"]))
        rm = {"net_rm_cost": rl["value"], "version": "live", "rev": d["rev"], "country": rl["country"], "currency": rl["currency"],
              "as_of": rl["as_of"], "revision_id": rev_id}
        tool = {"cavities": tl["cavities"], "tool_capex_inr": tl["capex_inr"], "tool_cost_inr": tl["value_inr"], "version": "live",
                "trace": tl}
    else:
        rm = next((v for v in register.rm_versions(part_id) if v["revision_id"] == rev_id), None)
        tool = next((v for v in register.tool_versions(part_id) if v["revision_id"] == rev_id), None)
    if not rm:
        raise PieceError("Calculate the RM cost of the current revision first.")
    if not tool:
        raise PieceError("Calculate the tool cost of the current revision first (it selects the machine).")
    country, as_of, cur = rm["country"], rm["as_of"], rm["currency"]
    setup = costing_setup.tables()
    t = Trace(cur, (d.get("trace_overrides") or {}).get("piece"))
    typed = d.get("piece_inputs") or {}
    you = {"type": "user", "note": f"Typed in the part register for {d['part_code']}"}
    reg = lambda note: {"type": "register", "note": note}
    params = master_data.parameters(part_type)
    tool_tr = tool["trace"] if "trace" in tool else register.tool_trace(part_id, tool["version"])
    machine = (tool_tr.get("trial") or {}).get("machine")
    if not machine:
        raise PieceError("The tool cost has no moulding / casting machine (clamp force). Check Master data → Machines.")
    grade = params.get("operator_grade")
    if not grade:
        raise PieceError(f"Master data → Parameters has no 'operator_grade' for {part_type}.")
    try:
        mhr = graft(t, rate_engine.mhr(machine["machine_id"], country, as_of), "mhr:")
        lab = graft(t, rate_engine.labour_rate(grade, country, as_of), "lab:")
    except (rate_engine.EngineError, rates.RateError) as exc:
        raise PieceError(str(exc)) from None
    volume, vnote = register._annual_volume(d)
    volume = volume or params.get("annual_volume")
    years = d["programme_life_years"] or params.get("programme_years")
    gt = register._geometry_trace(part_id)[0]
    if "total_weight" not in gt.nodes and "weight" not in gt.nodes:
        raise PieceError(f"'{d['material'] or '(no material)'}' has no density in Master data → Materials: set the part's material "
                         "(with a density there) to cost the part.")
    weight_g = gt.value("total_weight") if "total_weight" in gt.nodes else gt.value("weight")
    ins_cost, notes = 0.0, []
    for i in d["inserts"]:
        x = i["insert"]
        if x["unit_price"] is None:
            raise PieceError(f"Insert {x['part_code']} has no price per piece.")
        fx = 1.0
        if (x["price_currency"] or cur) != cur:
            try:
                f_in = rates.lookup("forex", x["price_currency"], "", as_of)["value"] if x["price_currency"] != "INR" else 1.0
                f_out = rates.lookup("forex", cur, "", as_of)["value"] if cur != "INR" else 1.0
            except rates.RateMissing as exc:
                raise PieceError(str(exc)) from None
            fx = f_in / f_out
        ins_cost += i["quantity"] * x["unit_price"] * fx
        notes.append(f"{i['quantity']:g} × {x['part_code']} {x['unit_price']:g} {x['price_currency']}")
    rules = register_setup.insert_rules()
    capex_inr = tool["tool_capex_inr"] or tool["tool_cost_inr"]
    fx_cur = 1.0 if cur == "INR" else rates.lookup("forex", cur, "", as_of)["value"]
    if tool_tr.get("cycle_node") and "cycle_s" not in typed:   # machined (stage 37): the traced machining time
        cycle = graft(t, tool_tr, "mc:") and "mc:" + tool_tr["cycle_node"]
    elif "cycle_s" in typed:
        cycle = (typed["cycle_s"], "s", you, False)
    else:
        calc, why = calculated_cycle(part_id, part_type)
        if calc:   # the cycle worked out for the part, not the target of Parameters (editable per part)
            cycle = (round(calc, 3), "s", reg(why), False)
        else:
            cycle = (params.get("cycle_time_s"), "s", {"type": "master", "sheet": "Parameters", "row": f"{part_type} / cycle_time_s",
                                                       "note": f"Target cycle used because the cycle could not be calculated: {why}"}, False)
    items = {
        "rm_cost": (rm["net_rm_cost"], cur, reg(f"RM cost version {rm['version']} (rev {rm['rev']})"), True),
        "cycle_s": cycle,
        "cavities": (typed.get("cavities", tool["cavities"]), "pcs", you if "cavities" in typed else reg(f"Tool cost version {tool['version']}"), False),
        "mhr": mhr, "labour_rate": lab,
        "secondary_ops_pct": (typed.get("secondary_ops_pct", params.get("secondary_ops_pct")), "%",
                              you if "secondary_ops_pct" in typed else {"type": "master", "sheet": "Parameters", "row": f"{part_type} / secondary_ops_pct"}, False),
        "insert_cost": (ins_cost, cur, reg(" + ".join(notes) or "no moulded-in inserts"), True),
        "inserts_per_part": (float(d["insert_count"]), "pcs", reg("Inserts linked to the part"), False),
        "tool_capex": (capex_inr / fx_cur, cur, reg(f"Tool CAPEX of tool cost version {tool['version']}: INR {capex_inr:,.0f} at the {as_of} forex rate"), True),
        "lifetime_volume": ((volume or 0) * (years or 0), "pcs", reg(f"{vnote} × {years} programme years"), False),
        "total_weight_kg": (weight_g / 1000, "kg", reg("Body + inserts weight from the 3D model"), False),
    }
    items |= {k: (r["value"], r["unit"], {"type": "master", "sheet": "Insert moulding rules", "row": k,
                                          "is_example": r.get("is_example")}, False) for k, r in rules.items()}
    names, missing = {}, []
    inputs = [r for r in setup["formula_inputs"] if r["scope"] == SCOPE]
    if not inputs:
        raise PieceError("Master data has no Formula inputs for scope 'piece'.")
    for inp in inputs:
        var, label, nid = inp["variable"], inp["label"] or inp["variable"], f"in:{inp['variable']}"
        if inp["source"] == "piece":
            v = items.get(inp["item"])
            if v is None:
                raise PieceError(f"{label}: '{inp['item']}' is not a piece value.")
            if isinstance(v, str):
                nid = v
            else:
                if v[0] is None:
                    raise PieceError(f"{label}: no value (Master data → Parameters or the part).")
                t.add_input(nid, label, float(v[0]), v[1], v[2], money=v[3])
        elif inp["source"] == "parameter":
            if not isinstance(params.get(inp["item"]), (int, float)):
                raise PieceError(f"{label}: Master data → Parameters has no number '{inp['item']}' for {part_type}.")
            t.add_input(nid, label, params[inp["item"]], inp["unit"], {"type": "master", "sheet": "Parameters", "row": f"{part_type} / {inp['item']}"})
        elif inp["source"] == "rate":
            try:
                rate = rates.lookup(inp["category"], inp["item"], country, as_of)
            except rates.RateMissing as exc:
                missing.append(str(exc))
                t.add_input(nid, label, 0, inp["unit"], {"type": "missing", "note": str(exc)}, money=bool(inp["is_money"]))
            else:
                t.add_rate(nid, label, rate, money=bool(inp["is_money"]))
                if inp["is_money"]:
                    nid = rate_engine._convert(t, nid, label, rate["currency"], cur, as_of)
        else:
            raise PieceError(f"Formula input '{var}' of scope piece has source '{inp['source']}', which it cannot use.")
        names[var] = nid
    try:
        result, components, order = rate_engine.evaluate_scope(t, setup, SCOPE, names, cur, as_of)
    except (rate_engine.EngineError, rates.RateMissing) as exc:
        raise PieceError(str(exc)) from None
    except ZeroDivisionError:
        raise PieceError("A piece-cost formula divides by zero: check cycle time, cavities and the programme volume.") from None
    out = t.to_dict(result)
    out |= {"part_type": part_type, "country": country, "currency": cur, "as_of": as_of, "value": t.value(result),
            "value_inr": t.value("result:inr"), "missing": missing, "machine": machine["machine_id"], "grade": grade,
            "revision": {"id": rev_id, "rev": d["rev"]}, "rm_version": rm["version"], "tool_version": tool["version"],
            "steps": [{"name": r["name"], "node": f"calc:{r['name']}", "is_result": bool(r["is_result"])} for r in order],
            "inputs": [{"variable": k, "node": v} for k, v in names.items()]}
    out["tool_summary"] = {"value": tool_tr["value"], "value_inr": tool_tr["value_inr"], "capex_inr": tool_tr.get("capex_inr"),
                           "currency": tool_tr["currency"], "weight_kg": tool_tr["nodes"]["tool_weight"]["value"]
                           if "tool_weight" in tool_tr["nodes"] else 0.0}
    out["key"] = {"revision_id": rev_id, "rm": rm["version"], "tool": tool["version"], "inputs": typed,
                  "cycle_s": t.value(names["cycle_s"]) if "cycle_s" in names else None,
                  "overrides": (d.get("trace_overrides") or {}).get("piece") or {},
                  "rates": sorted(x["id"] for x in out["rates_used"]), "as_of": as_of}
    out["is_example"] = any(x.get("is_example") for x in out["rates_used"])
    return out
