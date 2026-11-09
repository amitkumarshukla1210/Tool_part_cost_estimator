"""Country comparison and landed cost in India (roadmap stage 11), for the part and its tool.

For every country the part is costed as if part AND tool were made there (the same engines as the part panel: RM,
tool cost, part cost, each with that country's approved rates). The ex-works price is the part cost without the local
logistics; imports to India then add

    freight (sea / air, per kg) + insurance (% of ex-works + freight) = CIF (assessable value)
    + Basic Customs Duty (HS code and origin, preferential FTA rate when you tick it) + SWS (% of BCD)
    + IGST (% of CIF + BCD + SWS; credit shown separately when claimable) + clearance + inland transport (per kg)

Every rate is an approved version in the rate library (categories freight, duty, import, process_unit); the HS codes
are master data (Mould & die database → HS codes). Nothing is calculated that is not a rate times a quantity.
"""

from __future__ import annotations

from . import costing_setup, master_data, mould_db, piece_cost, rates, register_setup

HOME = "IN"


def _hs(scope: str, part_type: str) -> str:
    row = next((r for r in mould_db.tables()["hs_codes"] if r["scope"] == scope and r["part_type"] == part_type), None)
    if not row:
        raise ValueError(f"Mould & die database → HS codes has no row for {scope} / {part_type}.")
    return row["hs_code"]


def _rate(used: dict, cat: str, item: str, country: str, as_of: str, optional: bool = False):
    try:
        r = rates.lookup(cat, item, country, as_of)
    except rates.RateMissing:
        if optional:
            return None
        raise
    used[r["id"]] = r
    return r["value"]


def import_cost(exw: float, weight_kg: float, origin: str, hs: str, as_of: str, mode: str, use_fta: bool, used: dict) -> dict:
    """Landed cost in India of one item (INR) with every step."""
    inland = _rate(used, "process_unit", "Transport (per kg)", HOME, as_of) * weight_kg
    if origin == HOME:
        return {"exw": exw, "freight": 0.0, "insurance": 0.0, "cif": exw, "bcd_pct": 0.0, "bcd": 0.0, "sws": 0.0, "igst_pct": 0.0, "igst": 0.0,
                "clearance": 0.0, "inland": inland, "landed_with_igst": exw + inland, "igst_credit": 0.0, "landed": exw + inland,
                "duty_basis": "domestic: no import duty", "hs": hs}
    freight = _rate(used, "freight", f"{mode}_per_kg", origin, as_of) * weight_kg
    insurance = _rate(used, "import", "insurance_pct", "", as_of) / 100 * (exw + freight)
    cif = exw + freight + insurance
    fta = _rate(used, "duty", f"bcd_pct_fta:{hs}", origin, as_of, optional=True) if use_fta else None
    bcd_pct = fta if fta is not None else _rate(used, "duty", f"bcd_pct:{hs}", origin, as_of)
    bcd = cif * bcd_pct / 100
    sws = bcd * _rate(used, "duty", "sws_pct", HOME, as_of) / 100
    igst_pct = _rate(used, "duty", f"igst_pct:{hs}", HOME, as_of)
    igst = (cif + bcd + sws) * igst_pct / 100
    clearance = cif * _rate(used, "import", "clearance_pct", HOME, as_of) / 100
    claim = bool(master_data.parameters("all").get("igst_claimable"))
    gross = cif + bcd + sws + igst + clearance + inland
    return {"exw": exw, "freight": freight, "insurance": insurance, "cif": cif, "bcd_pct": bcd_pct, "bcd": bcd, "sws": sws,
            "igst_pct": igst_pct, "igst": igst, "clearance": clearance, "inland": inland, "landed_with_igst": gross,
            "igst_credit": igst if claim else 0.0, "landed": gross - (igst if claim else 0.0), "hs": hs,
            "duty_basis": ("FTA preferential rate" if fta is not None else "standard rate")}


def compare(part_id: int, countries: list[str] | None = None, mode: str = "sea", use_fta: bool = True, keep: bool = False) -> dict:
    from . import register
    d = register.part_detail(part_id, with_rm=False)
    if register.tool_eligibility(d):
        raise ValueError(register.tool_eligibility(d))
    part_type = register_setup.processes()[d["process"]]["part_type"]
    setup = costing_setup.tables()
    cmap = {c["code"]: c for c in setup["countries"]}
    wanted = [c.upper() for c in (countries or list(cmap))]
    unknown = [c for c in wanted if c not in cmap]
    if unknown:
        raise ValueError(f"Country '{unknown[0]}' is not in Master data → Countries.")
    pct = float(master_data.parameters("all").get("fx_scenario_pct", 5))
    rows = []
    for c in wanted:
        used: dict = {}
        row = {"country": c, "name": cmap[c]["name"], "currency": cmap[c]["currency"], "error": ""}
        try:
            pc = piece_cost.run(part_id, c)
            as_of = pc["as_of"]
            n = pc["nodes"]
            k = pc["value_inr"] / pc["value"]                                   # INR per unit of the country's currency
            usd = rates.lookup("forex", "USD", "", as_of)["value"]
            used |= {r["id"]: r for r in pc["rates_used"]}
            comp = lambda *names: sum(n[f"calc:{x}"]["value"] for x in names) * k
            exw_local = pc["value"] - n["calc:logistics"]["value"]
            exw = exw_local * k
            parts = {"rm": n["in:rm_cost"]["value"] * k, "process": comp("process_cost", "secondary_cost"),
                     "tool": comp("amortisation"), "packing": comp("packing")}
            parts["other"] = exw - sum(parts.values())
            wkg = n["in:total_weight_kg"]["value"]
            tl = pc["tool_summary"]
            land = import_cost(exw, wkg, c, _hs("part", part_type), as_of, mode, use_fta, used)
            tool_land = import_cost(tl["value_inr"], tl["weight_kg"], c, _hs("tool", part_type), as_of, mode, use_fta, used)
            scen = {}
            for sign in (-1, 1):
                u: dict = {}
                scen[f"{sign * pct:+g}%"] = import_cost(exw * (1 + sign * pct / 100), wkg, c, _hs("part", part_type), as_of, mode, use_fta, u)["landed"] \
                    if cmap[c]["currency"] != "INR" else land["landed"]
            row |= {"as_of": as_of, "exw_local": exw_local, "exw_inr": exw, "exw_usd": exw / usd, "components_inr": parts, "weight_kg": wkg,
                    "landed": land, "tool": {"cost_local": tl["value"], "cost_inr": tl["value_inr"], "cost_usd": tl["value_inr"] / usd,
                                             "weight_kg": tl["weight_kg"], "landed": tool_land},
                    "forex": {"usd_inr": usd, "fx_inr_per_unit": k, "scenario": scen | {"0%": land["landed"]}},
                    "piece_machine": pc["machine"], "is_example": pc["is_example"] or any(r.get("is_example") for r in used.values()),
                    "rates_used": [{"id": r["id"], "category": r["category"], "item": r["item"], "country": r["country"], "month": r["month"],
                                    "value": r["value"], "unit": r["unit"], "is_example": r["is_example"]} for r in sorted(used.values(), key=lambda r: r["id"])]}
            if keep:                                                            # versus(): the whole part and tool trace
                row["_piece"] = pc
        except (piece_cost.PieceError, rates.RateError, ValueError) as exc:
            row["error"] = str(exc)
        rows.append(row)
    ok = [r for r in rows if not r["error"]]
    cheapest = min(ok, key=lambda r: r["landed"]["landed"])["country"] if ok else None
    cheapest_tool = min(ok, key=lambda r: r["tool"]["landed"]["landed"])["country"] if ok else None
    return {"part_id": part_id, "part_code": d["part_code"], "mode": mode, "use_fta": use_fta, "fx_pct": pct, "rows": rows,
            "cheapest": cheapest, "cheapest_tool": cheapest_tool, "home": HOME}


def _flat(res: dict) -> list[list]:
    out = []
    for r in res["rows"]:
        if r["error"]:
            out.append([r["country"], r["name"], r["error"]] + [""] * 17)
            continue
        c, l, t = r["components_inr"], r["landed"], r["tool"]["landed"]
        out.append([r["country"], r["name"], "", r["currency"], r["exw_local"], r["exw_usd"], r["exw_inr"], c["rm"], c["process"], c["tool"],
                    c["packing"], c["other"], l["freight"], l["insurance"], l["bcd"], l["sws"], l["igst"], l["clearance"], l["inland"],
                    l["landed_with_igst"], l["igst_credit"], l["landed"], r["tool"]["cost_inr"], t["landed"]])
    return out


HEAD = ["Country", "Name", "Error", "Currency", "Ex-works (local)", "Ex-works (USD)", "Ex-works (INR)", "RM", "Process", "Tool amortisation",
        "Packing", "Overhead, rejection, profit, other", "Freight", "Insurance", "BCD", "SWS", "IGST", "Clearance", "Inland transport",
        "Landed incl. IGST", "IGST credit", "Landed (net of credit)", "Tool ex-works (INR)", "Tool landed (INR)"]


def to_excel(res: dict) -> bytes:
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from .table_set import HEADER_FILL
    wb = Workbook()
    sheets = [("Comparison (INR)", HEAD, _flat(res)),
              ("Forex scenario", ["Country", "Currency"] + list(next((r["forex"]["scenario"] for r in res["rows"] if not r["error"]), {})),
               [[r["country"], r["currency"]] + list(r["forex"]["scenario"].values()) for r in res["rows"] if not r["error"]]),
              ("Duty basis", ["Country", "Part HS", "Part BCD %", "Basis", "IGST %", "Tool HS", "Tool BCD %"],
               [[r["country"], r["landed"]["hs"], r["landed"]["bcd_pct"], r["landed"]["duty_basis"], r["landed"]["igst_pct"],
                 r["tool"]["landed"]["hs"], r["tool"]["landed"]["bcd_pct"]] for r in res["rows"] if not r["error"]]),
              ("Rates used", ["Rate #", "Country", "Category", "Item", "Month", "Value", "Unit", "Example"],
               [[x["id"], r["country"], x["category"], x["item"], x["month"], x["value"], x["unit"], "EXAMPLE" if x["is_example"] else ""]
                for r in res["rows"] if not r["error"] for x in r["rates_used"]])]
    for i, (name, head, rows) in enumerate(sheets):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = name
        ws.append(head)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def chart_png(res: dict) -> bytes:
    import io
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    ok = [r for r in res["rows"] if not r["error"]]
    keys = [("RM", lambda r: r["components_inr"]["rm"]), ("Process", lambda r: r["components_inr"]["process"]),
            ("Tool", lambda r: r["components_inr"]["tool"]), ("Packing", lambda r: r["components_inr"]["packing"]),
            ("Other", lambda r: r["components_inr"]["other"]), ("Freight + insurance", lambda r: r["landed"]["freight"] + r["landed"]["insurance"]),
            ("Duty (BCD + SWS + IGST net)", lambda r: r["landed"]["bcd"] + r["landed"]["sws"] + r["landed"]["igst"] - r["landed"]["igst_credit"]),
            ("Clearance + inland", lambda r: r["landed"]["clearance"] + r["landed"]["inland"])]
    colours = ["#1f6feb", "#2da44e", "#bf8700", "#8250df", "#8b949e", "#0969da", "#cf222e", "#6e7781"]
    fig, ax = plt.subplots(figsize=(8, 4), dpi=110)
    bottom = [0.0] * len(ok)
    for (label, f), col in zip(keys, colours):
        vals = [f(r) for r in ok]
        ax.bar([r["country"] for r in ok], vals, bottom=bottom, label=label, color=col)
        bottom = [b + v for b, v in zip(bottom, vals)]
    for i, r in enumerate(ok):
        if r["country"] == res["cheapest"]:
            ax.annotate("cheapest", (i, bottom[i]), ha="center", va="bottom", fontsize=8, color="#2da44e")
    ax.set_ylabel("INR per part, landed in India")
    ax.legend(fontsize=7, ncol=2)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def to_pdf(res: dict, part: dict) -> bytes:
    import io
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer
    from .pdf_report import _example_banner, _table, _theme
    theme, ss = _theme(), getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=18, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=11, spaceBefore=8, spaceAfter=4)
    note = ParagraphStyle("n", parent=ss["Normal"], textColor=theme["grey"], fontSize=7.5)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Design to Cost — Country comparison {part['part_code']}", author="Design to Cost")
    ok = [r for r in res["rows"] if not r["error"]]
    f0 = lambda v: f"{v:,.2f}"
    story = [Paragraph("COUNTRY COMPARISON AND LANDED COST IN INDIA", ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8)),
             Paragraph(f"{part['part_code']} · {part['name']}", h1),
             Paragraph(f"{'Sea' if res['mode'] == 'sea' else 'Air'} freight · {'FTA rates used where available' if res['use_fta'] else 'standard duty rates'} · "
                       f"all amounts INR per part unless stated · cheapest landed: {res['cheapest']}", note)]
    if any(r["is_example"] for r in ok):
        story += [Spacer(1, 2 * mm), _example_banner(ss, "Rates and duties are EXAMPLE values.")]
    story += [Spacer(1, 3 * mm), Image(io.BytesIO(chart_png(res)), 190 * mm, 95 * mm), Paragraph("Landed cost per part", h2),
              _table([["Country", "Ex-works", "USD", "Freight+ins.", "BCD+SWS", "IGST", "Clear.+inland", "IGST credit", "Landed", "Tool landed"]] +
                     [[r["country"], f0(r["exw_inr"]), f0(r["exw_usd"]), f0(r["landed"]["freight"] + r["landed"]["insurance"]),
                       f0(r["landed"]["bcd"] + r["landed"]["sws"]), f0(r["landed"]["igst"]), f0(r["landed"]["clearance"] + r["landed"]["inland"]),
                       f0(r["landed"]["igst_credit"]), f0(r["landed"]["landed"]), f"{r['tool']['landed']['landed']:,.0f}"] for r in ok], theme),
              Paragraph(f"Forex ±{res['fx_pct']:g} %", h2),
              _table([["Country"] + list(ok[0]["forex"]["scenario"])] + [[r["country"]] + [f0(v) for v in r["forex"]["scenario"].values()] for r in ok], theme)
              if ok else Spacer(1, 1)]
    for r in res["rows"]:
        if r["error"]:
            story.append(Paragraph(f"<font color='#b91c1c'>■</font> {r['country']}: {r['error']}", ss["Normal"]))
    doc.build(story)
    return buf.getvalue()


# ---------- India vs the comparison country, line by line (roadmap stage 48) ----------
# Every line of the tool cost and the part cost next to the same line worked out in the comparison country (Part register
# setup -> Register settings `compare_country`, CN unless changed) with that country's approved rates, in its currency and
# in INR (approved forex), then the landed rows (freight, insurance, BCD, SWS, IGST with its credit, clearance, inland)
# up to the landed cost at the factory. Nothing new is calculated: the same engines and import_cost() as the comparison above.

LANDED_ROWS = [("exw", "Ex-works (part: cost without logistics; tool: tool cost)"), ("freight", "Freight"), ("insurance", "Insurance"),
               ("cif", "CIF (assessable value)"), ("bcd", "Basic customs duty (BCD)"), ("sws", "Social welfare surcharge (SWS)"),
               ("igst", "IGST"), ("igst_credit", "IGST credit taken (GST input)"), ("clearance", "Clearance"),
               ("inland", "Inland transport to the factory"), ("landed", "Landed cost at the factory")]


def seed() -> int:
    """Add the Register settings row compare_country (CN) when missing; an existing row is never changed."""
    data = register_setup.tables()
    if any(r["key"] == "compare_country" for r in data["register_settings"]):
        return 0
    data["register_settings"].append({"key": "compare_country", "value": "CN",
                                      "description": "Country compared with India on every tool and part cost line and in the "
                                                     "'India vs …' downloads (a code of Master data → Countries; stage 48)"})
    register_setup.write(data)
    return 1


VERSUS_PIECE_INPUTS = ("rm_cost", "cycle_s", "mhr", "labour_rate", "tool_cost")   # inputs shown before the part-cost steps


def compare_country() -> str:
    code = (register_setup.settings().get("compare_country") or "").strip().upper()
    if not code:
        raise ValueError("Part register setup → Register settings has no compare_country row (run the master-data update to add it).")
    if code == HOME:
        raise ValueError(f"Part register setup → Register settings compare_country is {HOME}, the home country: choose another country.")
    return code


def _nodes(tr: dict, k: float) -> dict:
    return {nid: {"value": n["value"], "unit": n.get("unit", ""), "money": bool(n.get("money")), "label": n.get("label", nid),
                  "inr": (n["value"] if str(n.get("unit", "")).startswith("INR") else n["value"] * k) if n.get("money") else None}
            for nid, n in tr["nodes"].items() if isinstance(n.get("value"), (int, float)) and not isinstance(n.get("value"), bool)}


def _landed_lines(land: dict, k_rev: float = 1.0) -> list[dict]:
    """The landed rows of one item; INR (and the comparison currency = INR ÷ forex when k_rev is given)."""
    sign = {"igst_credit": -1}
    val = lambda key: (sign.get(key, 1) * float(land.get(key) or 0.0)) or 0.0
    return [{"key": key, "label": label, "inr": val(key), "local": val(key) / k_rev if k_rev else None,
             "pct": land.get("bcd_pct") if key == "bcd" else land.get("igst_pct") if key == "igst" else None}
            for key, label in LANDED_ROWS]


def selected(d: dict) -> tuple[str, list[str]]:
    """(producing country, the countries costed next to it) of a part (stage 50): the part's compare_countries, else the
    Register settings compare_country; the producing country itself is never repeated."""
    own = (d.get("effective_country") or d.get("country") or register_setup.settings().get("default_country") or HOME).upper()
    others = d.get("compare_countries")
    if others is None:
        try:
            others = [compare_country()]
        except ValueError:
            others = []
    return own, [c for c in others if c and c.upper() != own]


def _k(tr: dict) -> float:
    return tr["value_inr"] / tr["value"] if tr.get("value") else 1.0


def _country_block(part_id: int, c: str, cmap: dict, part_type: str, mode: str, use_fta: bool) -> dict:
    """RM, tool and part cost of the part made in country c (live, that country's approved rates), with its landed rows."""
    from . import register
    out = {"country": c, "name": cmap[c]["name"], "currency": cmap[c]["currency"], "error": ""}
    try:
        rm = register._rm_compute(part_id, c)
    except Exception as exc:                     # RM may not apply (e.g. bought-out); the other blocks still show
        rm, out["rm_error"] = None, str(exc)
    res = compare(part_id, [c], mode, use_fta, keep=True)["rows"][0]
    if res["error"]:
        out["error"] = res["error"]
        if rm:
            k = rates.lookup("forex", cmap[c]["currency"], "", rm["as_of"])["value"] if cmap[c]["currency"] != "INR" else 1.0
            out |= {"fx_inr_per_unit": k, "rm": {"nodes": _nodes(rm, k)}, "traces": {"rm": rm}}
        return out
    pc = res.pop("_piece")
    tl = pc.pop("_tool_trace")
    k, k_tool = res["forex"]["fx_inr_per_unit"], _k(tl)
    out |= {"as_of": res["as_of"], "fx_inr_per_unit": k, "is_example": res["is_example"], "rates_used": res["rates_used"],
            "rm": {"nodes": _nodes(rm, k)} if rm else None,
            "tool": {"nodes": _nodes(tl, k_tool), "currency": tl["currency"], "fx_inr_per_unit": k_tool, "value_inr": tl["value_inr"]},
            "piece": {"nodes": _nodes(pc, k), "value_inr": pc["value_inr"]},
            "landed": {"piece": _landed_lines(res["landed"], k), "tool": _landed_lines(res["tool"]["landed"], k_tool)},
            "landed_inr": {"piece": res["landed"]["landed"], "tool": res["tool"]["landed"]["landed"]},
            "traces": {"rm": rm, "tool": tl, "piece": pc}}
    return out


def versus(part_id: int, mode: str = "sea", use_fta: bool = True, countries: list[str] | None = None) -> dict:
    """The RM, tool and part cost lines of the part (producing country, as the panel shows them) next to the same lines in
    each selected country, in its currency and INR, with a forex row and all landed at the factory in INR (stage 48 / 50)."""
    from . import register
    d = register.part_detail(part_id, with_rm=False)
    own, others = selected(d)
    if countries:
        others = [c.upper() for c in countries if c.upper() != own]
    cmap = {c["code"]: c for c in costing_setup.tables()["countries"]}
    for c in [own] + others:
        if c not in cmap:
            raise ValueError(f"Country '{c}' is not in Master data → Countries.")
    part_type = register_setup.processes()[d["process"]]["part_type"]
    out = {"part_id": part_id, "part_code": d["part_code"], "home": HOME, "mode": mode, "use_fta": use_fta,
           "own": {"country": own, "name": cmap[own]["name"], "currency": cmap[own]["currency"]}, "countries": []}
    # the producing country as the panel shows it: stored RM / tool versions, live part cost
    o = out["own"]
    try:
        rt = register.rm_trace(part_id)
        o["rm"] = {"nodes": _nodes(rt, _k(rt)) if rt.get("value") else {}, "fx_inr_per_unit": _k(rt)}
    except Exception as exc:
        o["rm"] = {"error": str(exc)}
    try:
        ht = register.tool_trace(part_id)
        wkg = ht["nodes"]["tool_weight"]["value"] if "tool_weight" in ht["nodes"] else 0.0
        tland = import_cost(ht["value_inr"], wkg, ht.get("country") or own, _hs("tool", part_type), ht.get("as_of") or rates.current_month(),
                            mode, use_fta, {})
        o["tool"] = {"nodes": _nodes(ht, _k(ht)), "currency": ht["currency"], "fx_inr_per_unit": _k(ht), "steps": ht.get("steps", []),
                     "groups": ht.get("groups", []), "totals": ht.get("totals", {}), "landed": _landed_lines(tland, _k(ht)),
                     "landed_inr": tland["landed"]}
    except Exception as exc:
        o["tool"] = {"error": str(exc)}
    try:
        hp = piece_cost.run(part_id)
        exw = (hp["value"] - hp["nodes"]["calc:logistics"]["value"]) * _k(hp)
        pland = import_cost(exw, hp["nodes"]["in:total_weight_kg"]["value"], own, _hs("part", part_type), hp["as_of"], mode, use_fta, {})
        o["piece"] = {"nodes": _nodes(hp, _k(hp)), "fx_inr_per_unit": _k(hp), "steps": hp["steps"], "inputs": hp.get("inputs", []),
                      "landed": _landed_lines(pland, _k(hp)), "landed_inr": pland["landed"]}
    except (piece_cost.PieceError, rates.RateError, ValueError, KeyError) as exc:
        o["piece"] = {"error": str(exc)}
    for c in others:
        b = _country_block(part_id, c, cmap, part_type, mode, use_fta)
        for w in ("piece", "tool"):
            if b.get("landed_inr") and o.get(w, {}).get("landed_inr") is not None:
                b.setdefault("saving_inr", {})[w] = b["landed_inr"][w] - o[w]["landed_inr"]
        out["countries"].append(b)
    out["is_example"] = any(b.get("is_example") for b in out["countries"])
    return out


def _row_ids(v: dict, which: str) -> list[tuple[str, str]]:
    """(node id, label) of the lines of the RM, tool or part cost, in the order of the panel."""
    o = v["own"].get(which) or {}
    first = next((b[which] for b in v["countries"] if b.get(which)), None) or {}
    nodes = {**(first.get("nodes") or {}), **(o.get("nodes") or {})}
    if which == "tool":
        tot = o.get("totals") or {}
        ids = ["tool_weight"] + [g["node"] for g in o.get("groups") or []]
        ids += [tot[k] for k in ("material_cost", "bought_out_cost") if k in tot]
        ids += [x["node"] for x in o.get("steps") or []]
    elif which == "piece":
        ids = [x["node"] for x in o.get("inputs") or [] if x["variable"] in VERSUS_PIECE_INPUTS] + [x["node"] for x in o.get("steps") or []]
    else:
        ids = [n for n in nodes if n.startswith(("weight", "calc:", "in:material_rate", "in:scrap"))]
    seen, out = set(), []
    for nid in ids:
        if nid not in seen and nid in nodes:
            seen.add(nid)
            out.append((nid, nodes[nid]["label"]))
    return out


def versus_rows(v: dict, which: str) -> list[list]:
    """Rows: line | own (local) | own (INR) | each country (local) | (INR); a forex row; the landed rows (tool, part)."""
    o = v["own"].get(which) or {}
    rows = []
    cell = lambda n: [n.get("value"), n.get("inr") if n.get("money") else None] if n else [None, None]
    fx = lambda b: (b.get("tool") or {}).get("fx_inr_per_unit") if which == "tool" and b.get("tool") else b.get("fx_inr_per_unit")
    rows.append(["Forex: INR per 1 unit of the currency", o.get("fx_inr_per_unit"), None]
                + [x for b in v["countries"] for x in (fx(b), None)])
    for nid, label in _row_ids(v, which):
        n = (o.get("nodes") or {}).get(nid) or {}
        unit = "INR" if n.get("money") else n.get("unit", "")
        rows.append([f"{label}" + (f" ({unit})" if unit and unit != "INR" else "")] + cell(n)
                    + [x for b in v["countries"] for x in cell(((b.get(which) or {}).get("nodes") or {}).get(nid))])
    if which in ("piece", "tool"):
        own_l = o.get("landed") or [None] * len(LANDED_ROWS)
        for i, (key, label) in enumerate(LANDED_ROWS):
            hl = own_l[i]
            r = [label, hl["local"] if hl else None, hl["inr"] if hl else None]
            for b in v["countries"]:
                bl = (b.get("landed") or {}).get(which)
                r += [bl[i]["local"], bl[i]["inr"]] if bl else [None, None]
            rows.append(r)
    return rows


def versus_head(v: dict) -> list[str]:
    o = v["own"]
    head = ["Line", f"{o['name']} ({o['currency']})", f"{o['name']} (INR)"]
    for b in v["countries"]:
        head += [f"{b['name']} ({b['currency']})", f"{b['name']} (INR)"]
    return head


def versus_filename(v: dict, ext: str) -> str:
    names = "_".join(b["name"] for b in v["countries"]) or "only"
    return f"{v['part_code']}_cost_{v['own']['name']}_vs_{names}.{ext}".replace(" ", "_")


BLOCKS = (("rm", "RM cost"), ("tool", "Tool cost"), ("piece", "Part cost"))


def versus_excel(v: dict, labels: dict | None = None) -> bytes:
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from .table_set import EXAMPLE_FILL, HEADER_FILL
    wb = Workbook()
    head = versus_head(v)
    codes = " vs ".join([v["own"]["country"]] + [b["country"] for b in v["countries"]])
    for i, (which, title) in enumerate(BLOCKS):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = f"{title} {codes}"[:31]
        ws.append([f"{v['part_code']} · {title}: " + " vs ".join([v["own"]["name"]] + [b["name"] for b in v["countries"]])
                   + f" · {'sea' if v['mode'] == 'sea' else 'air'} freight · landed in India without IGST when its credit is taken"])
        if v.get("is_example"):
            ws.append(["Uses EXAMPLE rates – not for negotiation."])
            ws.cell(ws.max_row, 1).fill = EXAMPLE_FILL
        ws.append(head)
        for c in ws[ws.max_row]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
        for r in versus_rows(v, which):
            ws.append(r)
        ws.column_dimensions["A"].width = 46
        for col in range(2, len(head) + 1):
            ws.column_dimensions[chr(64 + col)].width = 18
    ws = wb.create_sheet("Rates used")
    ws.append(["Country", "Rate #", "Category", "Item", "Month", "Value", "Unit", "Example"])
    for b in v["countries"]:
        for x in b.get("rates_used", []):
            ws.append([b["country"], x["id"], x["category"], x["item"], x["month"], x["value"], x["unit"], "EXAMPLE" if x["is_example"] else ""])
    for b in v["countries"]:
        if b.get("error"):
            ws.append([b["country"], "", "error", b["error"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def versus_pdf(v: dict, labels: dict | None, part: dict) -> bytes:
    import io
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from . import drawing_style
    from .pdf_report import _example_banner, _table, _theme
    theme, ss = _theme(), getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=16, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=11, spaceBefore=8, spaceAfter=4)
    note = ParagraphStyle("n", parent=ss["Normal"], textColor=theme["grey"], fontSize=7.5)
    buf = io.BytesIO()
    names = [v["own"]["name"]] + [b["name"] for b in v["countries"]]
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm, bottomMargin=10 * mm,
                            title=f"{v['part_code']} cost {' vs '.join(names)}", author="Design to Cost")
    st = {"k": ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8), "h1": h1}
    fmt = lambda x: "—" if x is None else f"{x:,.4f}" if abs(x) < 1000 else f"{x:,.0f}"
    story = [drawing_style.pdf_header(st, "COST: " + " VS ".join(n.upper() for n in names), f"{part['part_code']} · {part['name']}"),
             Paragraph(f"Each country with its own approved rates · {'sea' if v['mode'] == 'sea' else 'air'} freight · "
                       f"{'FTA rate where available' if v['use_fta'] else 'standard duty'} · landed in India without IGST when its "
                       "credit is taken (Parameters igst_claimable).", note)]
    if v.get("is_example"):
        story += [Spacer(1, 2 * mm), _example_banner(ss, "Rates and duties are EXAMPLE values.")]
    head = versus_head(v)
    nval = len(head) - 1
    widths = [70 * mm] + [(277 - 70) * mm / nval] * nval
    for which, title in BLOCKS:
        rows = [[r[0]] + [fmt(x) for x in r[1:]] for r in versus_rows(v, which)]
        story += [Paragraph(title, h2), _table([head] + rows, theme, widths)]
    for b in v["countries"]:
        if b.get("error"):
            story.append(Paragraph(f"<font color='#b91c1c'>■</font> {b['name']}: {b['error']}", ss["Normal"]))
    doc.build(story)
    return buf.getvalue()
