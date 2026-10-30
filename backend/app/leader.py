"""Project leader view (roadmap stage 13): BOM cost vs target, CAPEX (tools, machines, other), CAPEX plan, open corrections.

    BOM cost of a variant = Σ total quantity × part cost per piece (latest stored part cost, stage 8) for the parts we make,
                            + bought-out price per piece for the parts we buy; moulded-in inserts are already inside the
                            part cost of their body and are not added twice
    Tool CAPEX            = Σ stored tool CAPEX of the parts (stage 4)
    Machine CAPEX         = machines needed × machine price: annual hours per machine type from the stored part costs
                            (volume ÷ parts per hour ÷ OEE) over the hours one machine runs (Parameters), rounded up per type
    CAPEX plan            = lines by supplier and country with payment milestones (master data: CAPEX payment milestones)
                            hung on each line's need-by date (the project's SOP date unless the line has its own)
"""

from __future__ import annotations

import io
import math
from collections import defaultdict
from datetime import date, datetime, timedelta

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import and_, select

from . import master_data, rates, register, register_setup
from . import projects_db as db
from .table_set import HEADER_FILL

KINDS = ("tool", "machine", "other")


def _fx(cur: str, as_of: str) -> float:
    return 1.0 if not cur or cur == "INR" else rates.lookup("forex", cur, "", as_of)["value"]


def _part_costs(project_id: int) -> dict:
    """{part_id: row with the latest stored piece cost trace (or None)}: the parts the logged-in user may see (stage 39)."""
    from . import scope
    with db.engine().connect() as conn:
        sv = scope.project_view(conn, project_id)
        parts = {r["id"]: dict(r) for r in conn.execute(select(db.parts).where(db.parts.c.project_id == project_id)).mappings()
                 if sv["visible"] is None or r["id"] in sv["visible"]}
        for pid in parts:
            last = conn.execute(select(db.piece_costs.c.trace, db.piece_costs.c.country, db.piece_costs.c.as_of, db.piece_costs.c.version)
                                .where(db.piece_costs.c.part_id == pid).order_by(db.piece_costs.c.version.desc()).limit(1)).mappings().first()
            parts[pid]["piece"] = dict(last) if last else None
    return parts


def variant_costs(variant: dict, parts: dict, visible: set | None = None) -> dict:
    """visible: the part ids the user may see (None = all); lines of other tool groups are left out (stage 39)."""
    lines, total, missing, example = [], 0.0, 0, False
    for b in register.variant_bom(variant["id"]):
        if b["kind"] != "bom" or b["is_assembly"]:
            continue
        if visible is not None and b["child_part_id"] not in visible:
            continue
        p = parts.get(b["child_part_id"], {})
        unit, basis, ex = None, "", False
        if p.get("piece_cost_inr") is not None:
            unit, basis, ex = p["piece_cost_inr"], "part cost", bool((p.get("piece") or {}).get("trace", {}).get("is_example"))
        elif p.get("unit_price") is not None:
            try:
                unit = p["unit_price"] * _fx(p.get("price_currency") or "INR", p.get("price_month") or rates.current_month())
                basis, ex = "bought-out price", bool(p.get("price_is_example"))
            except rates.RateError:
                unit = None
        cost = unit * b["total_quantity"] if unit is not None else None
        missing += cost is None
        total += cost or 0.0
        example = example or ex
        lines.append({"part_id": b["child_part_id"], "part_code": b["part_code"], "name": b["name"], "quantity": b["total_quantity"],
                      "unit_cost_inr": unit, "cost_inr": cost, "basis": basis or "no cost yet", "is_example": ex})
    tgt = variant.get("target_bom_cost_inr")
    costed = [l for l in lines if l["cost_inr"] is not None]
    delta = total - tgt if tgt and costed else None
    return {"id": variant["id"], "code": variant["code"], "name": variant["name"], "annual_volume": variant["annual_volume"],
            "target_inr": tgt, "bom_cost_inr": total if costed else None, "delta_inr": delta,
            "delta_pct": 100 * delta / tgt if delta is not None else None, "lines": lines, "parts_missing": missing,
            "state": "no target" if not tgt else "no cost yet" if not costed else "over target" if delta > 0 else "within target",
            "is_example": example}


def machine_need(parts: dict) -> dict:
    """Machines needed per machine type from the stored part costs, and what they cost."""
    hours = defaultdict(float)
    info: dict = {}
    for p in parts.values():
        pc = p.get("piece")
        if not pc or p["is_assembly"]:
            continue
        tr = pc["trace"]
        part_type = tr["part_type"]
        params = master_data.parameters(part_type)
        vol, _ = register._annual_volume(register.part_detail(p["id"], with_rm=False))
        vol = vol or params.get("annual_volume")            # as the tool and part cost do: the master-data default
        pph = tr["nodes"]["calc:parts_per_h"]["value"]
        if not vol or not pph:
            continue
        oee = (params.get("oee_pct") or 100) / 100
        hours[tr["machine"]] += vol / pph / oee
        info[tr["machine"]] = {"country": pc["country"], "as_of": pc["as_of"],
                               "available_h": params["working_days"] * params["shifts_per_day"] * params["hours_per_shift"]}
    out, total, example = [], 0.0, False
    for mid, h in sorted(hours.items()):
        i = info[mid]
        n = max(1, math.ceil(h / i["available_h"] - 1e-9))
        try:
            r = rates.lookup("machine_price", mid, i["country"], i["as_of"])
            price = r["value"] * _fx(r["currency"], i["as_of"])
            ex = bool(r["is_example"])
        except rates.RateError:
            price, ex = None, False
        out.append({"machine_id": mid, "country": i["country"], "hours_needed": h, "hours_per_machine": i["available_h"], "machines": n,
                    "utilisation_pct": 100 * h / (n * i["available_h"]), "price_inr": price,
                    "capex_inr": price * n if price is not None else None, "is_example": ex})
        total += price * n if price is not None else 0.0
        example = example or ex
    return {"rows": out, "capex_inr": total if out else None, "is_example": example}


# ---------- CAPEX plan ----------

def _items(project_id: int) -> list[dict]:
    with db.engine().connect() as conn:
        return [register._plain(r) for r in conn.execute(select(db.capex_items).where(db.capex_items.c.project_id == project_id)
                                                          .order_by(db.capex_items.c.kind, db.capex_items.c.id)).mappings()]


def plan(project: dict, keep=None) -> dict:
    """keep(item) -> bool: the CAPEX lines the user may see (stage 39); None = all."""
    ms = register_setup.capex_milestones()
    sop = project.get("sop_date") or ""
    items, by_month, by_supplier, by_country = [], defaultdict(float), defaultdict(float), defaultdict(float)
    for it in _items(project["id"]):
        if keep is not None and not keep(it):
            continue
        need = it["need_by"] or sop
        rows = []
        for m in ms:
            due = None
            if need:
                d = datetime.strptime(need, "%Y-%m-%d").date()
                due = (d + timedelta(weeks=m["weeks"] if m["is_after"] else -m["weeks"])).isoformat()
            paid = (it["payments"] or {}).get(m["name"], "")
            amount = it["amount_inr"] * m["pct"] / 100
            rows.append({"milestone": m["name"], "pct": m["pct"], "due": due, "amount_inr": amount, "paid_date": paid,
                         "overdue": bool(due and not paid and due < date.today().isoformat())})
            by_month[(due or "no date")[:7]] += amount
        by_supplier[it["supplier"] or "(no supplier yet)"] += it["amount_inr"]
        by_country[it["country"] or "(no country)"] += it["amount_inr"]
        items.append(it | {"need_by_effective": need, "milestones": rows,
                           "paid_inr": sum(r["amount_inr"] for r in rows if r["paid_date"])})
    return {"sop_date": sop, "items": items, "total_inr": sum(i["amount_inr"] for i in items),
            "paid_inr": sum(i["paid_inr"] for i in items), "by_month": sorted(by_month.items()),
            "by_supplier": sorted(by_supplier.items()), "by_country": sorted(by_country.items()), "milestones": ms}


def _item_values(data: dict) -> dict:
    out = {}
    if "kind" in data:
        if data["kind"] not in KINDS:
            raise register.RegisterError(f"CAPEX line: kind must be one of {', '.join(KINDS)}.")
        out["kind"] = data["kind"]
    for k in ("description", "supplier", "country", "notes"):
        if k in data:
            out[k] = str(data[k] or "").strip()
    if "supplier_id" in data:  # from the supplier master: its name (and country, when none is given) go on the line
        sid = register._num(data["supplier_id"], "CAPEX line: supplier", int)
        out["supplier_id"] = sid
        if sid:
            with db.engine().connect() as conn:
                sup = conn.execute(select(db.suppliers).where(db.suppliers.c.id == sid)).mappings().first()
            if not sup:
                raise register.RegisterError(f"CAPEX line: supplier {sid} is not in the supplier master.")
            out["supplier"] = sup["name"]
            if not out.get("country"):
                out["country"] = sup["country"]
    if "amount_inr" in data:
        out["amount_inr"] = register._num(data["amount_inr"], "CAPEX line: amount", required=True)
        if out["amount_inr"] < 0:
            raise register.RegisterError("CAPEX line: amount must not be negative.")
    if "need_by" in data:
        v = str(data["need_by"] or "").strip()
        if v:
            try:
                datetime.strptime(v, "%Y-%m-%d")
            except ValueError:
                raise register.RegisterError(f"CAPEX line: need-by date '{v}' must look like 2027-01-31.") from None
        out["need_by"] = v
    if "payments" in data:
        names = {m["name"] for m in register_setup.capex_milestones()}
        bad = [k for k in (data["payments"] or {}) if k not in names]
        if bad:
            raise register.RegisterError(f"CAPEX line: '{bad[0]}' is not a payment milestone ({', '.join(sorted(names))}).")
        out["payments"] = {k: str(v) for k, v in (data["payments"] or {}).items() if v}
    return out


def add_item(project_id: int, data: dict) -> dict:
    vals = _item_values(data)
    for k in ("kind", "description", "amount_inr"):
        if k not in vals or vals[k] in ("", None):
            raise register.RegisterError(f"CAPEX line: {k.replace('_', ' ')} must not be empty.")
    with db.engine().begin() as conn:
        iid = conn.execute(db.capex_items.insert().values(project_id=project_id, created_by=register.user(), **vals)).inserted_primary_key[0]
        register._log(conn, "project", project_id, "capex_line_added", {"line": vals["description"], "amount (INR)": vals["amount_inr"]})
    return {"id": iid}


def update_item(item_id: int, data: dict) -> dict:
    vals = _item_values(data)
    with db.engine().begin() as conn:
        old = conn.execute(select(db.capex_items).where(db.capex_items.c.id == item_id)).mappings().first()
        if not old:
            raise register.RegisterError(f"CAPEX line {item_id} does not exist.")
        changes = {k: {"old": old[k], "new": v} for k, v in vals.items() if old[k] != v}
        if changes:
            conn.execute(db.capex_items.update().where(db.capex_items.c.id == item_id).values(**vals))
            register._log(conn, "project", old["project_id"], "capex_line_updated", {"line": old["description"]} | changes)
    return {"id": item_id}


def delete_item(item_id: int) -> dict:
    with db.engine().begin() as conn:
        old = conn.execute(select(db.capex_items).where(db.capex_items.c.id == item_id)).mappings().first()
        if not old:
            raise register.RegisterError(f"CAPEX line {item_id} does not exist.")
        conn.execute(db.capex_items.delete().where(db.capex_items.c.id == item_id))
        register._log(conn, "project", old["project_id"], "capex_line_removed", {"line": old["description"]})
    return {"deleted": item_id}


def build_plan(project_id: int) -> dict:
    """Lines for the costed tools and machines; existing lines keep supplier, dates and payments, only the amount is refreshed."""
    parts = _part_costs(project_id)
    wanted = {}
    for p in parts.values():
        if p["tool_capex_inr"] is not None and not p["is_assembly"]:
            tool_country = ((p.get("piece") or {}).get("trace", {}).get("tool_summary") and p["tool_country"]) or p["tool_country"] or p["country"]
            wanted[f"tool:{p['id']}"] = {"kind": "tool", "description": f"Tool / mould for {p['part_code']} {p['name']}", "part_id": p["id"],
                                         "country": (tool_country or register_setup.settings()["default_country"]).upper(), "amount_inr": p["tool_capex_inr"]}
    for m in machine_need(parts)["rows"]:
        if m["capex_inr"] is not None:
            wanted[f"machine:{m['machine_id']}"] = {"kind": "machine", "description": f"{m['machines']} × {m['machine_id']}", "country": m["country"],
                                                     "amount_inr": m["capex_inr"]}
    created = refreshed = 0
    with db.engine().begin() as conn:
        have = {r["source_key"]: r for r in conn.execute(select(db.capex_items).where(and_(db.capex_items.c.project_id == project_id,
                                                                                          db.capex_items.c.source_key != ""))).mappings()}
        for key, v in wanted.items():
            if key in have:
                if abs(have[key]["amount_inr"] - v["amount_inr"]) > 0.005:
                    conn.execute(db.capex_items.update().where(db.capex_items.c.id == have[key]["id"]).values(amount_inr=v["amount_inr"], description=v["description"]))
                    refreshed += 1
            else:
                conn.execute(db.capex_items.insert().values(project_id=project_id, source_key=key, created_by=register.user(), **v))
                created += 1
        register._log(conn, "project", project_id, "capex_plan_built", {"new lines": created, "amounts refreshed": refreshed})
    return {"created": created, "refreshed": refreshed}


# ---------- the view ----------

def view(project_id: int) -> dict:
    from . import scope
    project = register.get_project(project_id)
    with db.engine().connect() as conn:
        sv = scope.project_view(conn, project_id)
    parts = _part_costs(project_id)
    variants = [variant_costs(v, parts, sv["visible"]) for v in project["variants"]]
    machines = machine_need(parts)
    keep = None
    if sv["limited"]:                       # CAPEX plan: tool lines of the user's parts, machine lines of the machines they need
        need = {m["machine_id"] for m in machines["rows"]}
        keep = lambda i: (i["kind"] == "tool" and i.get("part_id") in parts) \
            or (i["kind"] == "machine" and str(i.get("source_key") or "").removeprefix("machine:") in need) or i["kind"] not in ("tool", "machine")
    pl = plan(project, keep)
    tool_capex = sum(p["tool_capex_inr"] for p in parts.values() if p["tool_capex_inr"] is not None and not p["is_assembly"]) \
        if any(p["tool_capex_inr"] is not None for p in parts.values()) else None
    other = sum(i["amount_inr"] for i in pl["items"] if i["kind"] == "other")
    capex = {"tool_inr": tool_capex, "machine_inr": machines["capex_inr"], "other_inr": other or None}
    capex["total_inr"] = sum(v for v in capex.values() if v) or None
    budget = project["capex_budget_inr"]
    capex |= {"budget_inr": budget, "left_inr": budget - capex["total_inr"] if budget and capex["total_inr"] is not None else None,
              "over_budget": bool(budget and capex["total_inr"] and capex["total_inr"] > budget)}
    open_codes = {s["code"]: s["name"] for s in register_setup.statuses() if s.get("is_open_correction")}
    corrections = [{"part_id": p["id"], "part_code": p["part_code"], "name": p["name"], "status": open_codes[p["status"]]}
                   for p in parts.values() if p["status"] in open_codes]
    return {"project": project, "variants": variants, "capex": capex, "machines": machines, "plan": pl, "corrections": corrections,
            "scope": {"limited": sv["limited"], "hidden_parts": sv["hidden"], "note": sv["note"]},
            "parts_without_piece_cost": sum(1 for p in parts.values() if not p["is_assembly"] and p["piece_cost_inr"] is None
                                            and register_setup.sourcing().get(p["sourcing"], {}).get("is_costed")),
            "is_example": any(v["is_example"] for v in variants) or machines["is_example"]}


def recalculate_pieces(project_id: int) -> dict:
    from . import scope
    with db.engine().connect() as conn:
        sv = scope.project_view(conn, project_id)
        ids = [r for (r,) in conn.execute(select(db.parts.c.id).where(and_(db.parts.c.project_id == project_id, db.parts.c.is_assembly.is_(False))))
               if sv["visible"] is None or r in sv["visible"]]
    done = same = 0
    skipped = []
    for pid in ids:
        try:
            res = register.compute_piece(pid, "recalculated with the latest approved rates")
        except register.RegisterError as exc:
            if not register.tool_eligibility(register.part_detail(pid, with_rm=False)):
                skipped.append({"part_id": pid, "why": str(exc)})
            continue
        done += res["stored"]
        same += not res["stored"]
    return {"new_versions": done, "unchanged": same, "problems": skipped}


def to_excel(project_id: int) -> bytes:
    v = view(project_id)
    p, cap = v["project"], v["capex"]
    wb = Workbook()
    sheets = [
        ("Summary", ["Item", "Value"], [["Project", f"{p['code']} · {p['name']}"]] + ([["Covers", v["scope"]["note"]]] if v["scope"]["limited"] else [])
         + [["Customer", p["customer"]], ["SOP date", p.get("sop_date") or ""],
                                          ["CAPEX budget (INR)", cap["budget_inr"]], ["Tool & mould CAPEX (INR)", cap["tool_inr"]],
                                          ["Machine CAPEX (INR)", cap["machine_inr"]], ["Other CAPEX (INR)", cap["other_inr"]],
                                          ["Total CAPEX (INR)", cap["total_inr"]], ["Budget left (INR)", cap["left_inr"]],
                                          ["Open corrections", len(v["corrections"])],
                                          ["Example values", "yes: not for negotiation" if v["is_example"] else "no"]]),
        ("BOM cost vs target", ["Variant", "Name", "Annual volume", "Target (INR)", "BOM cost (INR)", "Difference (INR)", "Difference (%)", "State", "Parts without cost"],
         [[x["code"], x["name"], x["annual_volume"], x["target_inr"], x["bom_cost_inr"], x["delta_inr"], x["delta_pct"], x["state"], x["parts_missing"]] for x in v["variants"]]),
        ("BOM lines", ["Variant", "Part", "Name", "Quantity", "Unit cost (INR)", "Cost (INR)", "Basis"],
         [[x["code"], l["part_code"], l["name"], l["quantity"], l["unit_cost_inr"], l["cost_inr"], l["basis"]] for x in v["variants"] for l in x["lines"]]),
        ("Machines", ["Machine", "Country", "Hours needed/yr", "Hours per machine", "Machines", "Utilisation (%)", "Price (INR)", "CAPEX (INR)"],
         [[m["machine_id"], m["country"], m["hours_needed"], m["hours_per_machine"], m["machines"], m["utilisation_pct"], m["price_inr"], m["capex_inr"]] for m in v["machines"]["rows"]]),
        ("CAPEX plan", ["Kind", "Line", "Supplier", "Country", "Amount (INR)", "Need by", "Paid (INR)"],
         [[i["kind"], i["description"], i["supplier"], i["country"], i["amount_inr"], i["need_by_effective"], i["paid_inr"]] for i in v["plan"]["items"]]),
        ("Payments", ["Line", "Supplier", "Milestone", "Share (%)", "Due", "Amount (INR)", "Paid on", "Overdue"],
         [[i["description"], i["supplier"], m["milestone"], m["pct"], m["due"], m["amount_inr"], m["paid_date"], "yes" if m["overdue"] else ""]
          for i in v["plan"]["items"] for m in i["milestones"]]),
        ("Cash-out by month", ["Month", "Amount (INR)"], [list(x) for x in v["plan"]["by_month"]]),
        ("By supplier and country", ["Group", "Name", "Amount (INR)"], [["Supplier", k, a] for k, a in v["plan"]["by_supplier"]] + [["Country", k, a] for k, a in v["plan"]["by_country"]]),
        ("Open corrections", ["Part", "Name", "Status"], [[c["part_code"], c["name"], c["status"]] for c in v["corrections"]]),
    ]
    for i, (name, head, rows) in enumerate(sheets):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = name[:31]
        ws.append(head)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_pdf(project_id: int) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, SimpleDocTemplate
    from .pdf_report import _example_banner, _table, _theme
    v = view(project_id)
    p, cap = v["project"], v["capex"]
    theme, ss = _theme(), getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=18, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=11, spaceBefore=8, spaceAfter=4)
    note = ParagraphStyle("n", parent=ss["Normal"], textColor=theme["grey"], fontSize=7.5)
    f = lambda x, d=0: "—" if x is None else f"{x:,.{d}f}"
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Design to Cost — Project leader view {p['code']}", author="Design to Cost")
    story = [Paragraph("PROJECT LEADER VIEW", ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8)),
             Paragraph(f"{p['code']} · {p['name']}", h1),
             Paragraph(f"{p['customer'] or ''} · SOP {p.get('sop_date') or 'not set'} · {date.today().isoformat()}", note)]
    if v["scope"]["limited"]:                                     # stage 39: only the user's tool groups
        story.append(Paragraph(f"<b>{v['scope']['note']}</b>", note))
    if v["is_example"]:
        story += [Spacer(1, 2 * mm), _example_banner(ss)]
    story += [Paragraph("BOM cost vs target (INR per vehicle / unit)", h2),
              _table([["Variant", "Target", "BOM cost", "Difference", "%", "State", "Parts without cost"]] +
                     [[x["code"], f(x["target_inr"], 2), f(x["bom_cost_inr"], 2), f(x["delta_inr"], 2), f(x["delta_pct"], 1), x["state"], x["parts_missing"]] for x in v["variants"]], theme),
              Paragraph("CAPEX (INR)", h2),
              _table([["Budget", "Tools & moulds", "Machines", "Other", "Total", "Left", ""],
                      [f(cap["budget_inr"]), f(cap["tool_inr"]), f(cap["machine_inr"]), f(cap["other_inr"]), f(cap["total_inr"]), f(cap["left_inr"]),
                       "OVER BUDGET" if cap["over_budget"] else ""]], theme),
              Paragraph("Machines needed", h2),
              _table([["Machine", "Hours/yr", "Per machine", "Machines", "Utilisation %", "CAPEX"]] +
                     [[m["machine_id"], f(m["hours_needed"]), f(m["hours_per_machine"]), m["machines"], f(m["utilisation_pct"], 1), f(m["capex_inr"])] for m in v["machines"]["rows"]], theme),
              Paragraph("CAPEX plan", h2),
              _table([["Kind", "Line", "Supplier", "Country", "Amount", "Need by", "Paid"]] +
                     [[i["kind"], i["description"][:48], i["supplier"], i["country"], f(i["amount_inr"]), i["need_by_effective"], f(i["paid_inr"])] for i in v["plan"]["items"]], theme),
              Paragraph("Cash-out timeline by month", h2),
              _table([["Month", "Amount (INR)"]] + [[m, f(a)] for m, a in v["plan"]["by_month"]], theme, [50 * mm, 50 * mm]),
              Paragraph(f"Open corrections: {len(v['corrections'])}", h2),
              _table([["Part", "Name", "Status"]] + [[c["part_code"], c["name"], c["status"]] for c in v["corrections"]], theme) if v["corrections"] else Spacer(1, 1)]
    doc.build(story)
    return buf.getvalue()
