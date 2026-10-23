"""Purchase-order pack of a released tool design (roadmap stage 21).

Your plan: issue purchase orders to suppliers for raw material, for machining (job work on free-issue or supplier steel) and for bought-out
parts, then assemble the tool in your own factory. This module turns the stored design into

    Excel   Cover, BOM, PO-1 Raw material, PO-2 Machining, Machining detail, PO-3 Bought-out, Assembly, Inspection, Features, Cost summary
    PDF     three order documents (raw material, machining, bought-out) with the drawing list, and the tool assembly sheet is a separate PDF
    ZIP     everything for the supplier: STEP, PDF and DXF of every made part, assembly STEP and PDF, the Excel and the PDFs

A draft design can be previewed but its documents say DRAFT: only a released design is meant for orders. Rates and rules that are still
EXAMPLE values are flagged on every document.
"""

from __future__ import annotations

import io
import re
from datetime import date

from . import rates, tool_components

STEEL_DELIVERY = "Sawn block, stock size as stated (machining allowance included), certificate EN 10204 3.1"


def _fx(currency: str, month: str) -> float:
    if not currency or currency == "INR":
        return 1.0
    try:
        return float(rates.lookup("forex", currency, "", month)["value"])
    except Exception:
        return 1.0


def _facts(design: dict) -> dict:
    s, b = design["summary"], design["bill"]
    fx = _fx(b["currency"], design["as_of"])
    mat = b["totals"]["material_cost"]
    mach = b["totals"]["machining_cost"]
    std = b["totals"]["standard_cost_inr"]
    asm_hours = b["totals"]["assembly_hours"]
    asm = tool_components.process_price("Fitting & assembly", asm_hours, design["country"], design["as_of"])
    asm_cost = asm.get("cost") or 0
    total_local = mat + mach + asm_cost + std / fx
    return {"fx": fx, "currency": b["currency"] or "INR", "material": mat, "machining": mach, "standard_inr": std, "assembly_hours": asm_hours,
            "assembly": round(asm_cost), "total_local": round(total_local), "total_inr": round(total_local * fx),
            "engine": s.get("tool_cost") if s.get("tool_cost") is not None else None,
            "engine_note": ("Tool cost engine (whole tool incl. design and try-out)" if s.get("tool_cost") is not None
                            else "Sheet-metal tool cost engine comes later: steel only is estimated"),
            "example": bool(s.get("example")) or any(m["info"].get("is_example") for m in b["made"]) or any(l.get("is_example") for l in b["standard"])}


def _head(design: dict) -> dict:
    s = design["summary"]
    return {"part_code": s.get("part_code", ""), "status": design["status"], "rev": design["rev_label"], "version": design["version"],
            "country": design["country"], "month": design["as_of"], "date": date.today().isoformat(),
            "released": (design["released_at"] or "")[:10], "by": design["released_by"] or design["created_by"]}


def q_for(design: dict, kind: str, key: str):
    """The quoted value entered for a part number / item (latest quote wins), or an empty cell."""
    best = None
    for q in design.get("quotes", []):
        if q["kind"] == kind and q["key"] == key:
            best = q["value"]
    return best if best is not None else ""


def _ops_columns(m: dict) -> dict:
    cols = {}
    for o in m["info"]["operations"]:
        cols[o["process"]] = cols.get(o["process"], 0) + (o["amount"] if o["unit"] == "h" else 0)
    return cols


# ------------------------------------------------------------ Excel

def workbook(design: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from .report_render import _hex
    f, h, b = _facts(design), _head(design), design["bill"]
    wb = Workbook()
    head_fill, head_font = PatternFill("solid", fgColor=_hex("table-head-dark")), Font(bold=True, color=_hex("table-head-dark-text"))
    red = PatternFill("solid", fgColor="B91C1C")

    def sheet(name, headers, rows, widths=None, first=False):
        ws = wb.active if first else wb.create_sheet(name)
        ws.title = name
        r0 = 1
        if h["status"] != "released":
            ws.cell(1, 1, f"DRAFT design (version {h['version']}): not released, not for orders").font = Font(bold=True, color="FFFFFF")
            ws.cell(1, 1).fill = red
            r0 = 2
        if f["example"]:
            ws.cell(r0, 1, "Uses example rates – not for negotiation").font = Font(bold=True, color="FFFFFF")
            ws.cell(r0, 1).fill = red
            r0 += 1
        ws.append([]) if r0 > 1 else None
        start = ws.max_row + 1
        for j, hd in enumerate(headers, start=1):
            c = ws.cell(start, j, hd)
            c.fill, c.font = head_fill, head_font
            c.alignment = Alignment(wrap_text=True, vertical="top")
        for row in rows:
            ws.append([round(x, 3) if isinstance(x, float) else x for x in row])
        for j, w in enumerate(widths or [], start=1):
            ws.column_dimensions[ws.cell(1, j).column_letter].width = w
        ws.freeze_panes = ws.cell(start + 1, 1)
        return ws

    made = b["made"]
    # Cover
    ws = wb.active
    ws.title = "Cover"
    r = 1
    if h["status"] != "released":
        ws.cell(r, 1, f"DRAFT design (version {h['version']}): not released, not for orders").font = Font(bold=True, color="FFFFFF"); ws.cell(r, 1).fill = red; r += 1
    if f["example"]:
        ws.cell(r, 1, "Uses example rates – not for negotiation").font = Font(bold=True, color="FFFFFF"); ws.cell(r, 1).fill = red; r += 1
    ws.cell(r + 1, 1, f"Tool purchase pack: {h['part_code']}").font = Font(bold=True, size=14, color=_hex("brand-dark"))
    rows = [("Design version / drawing revision", f"{h['version']} / {h['rev']}"), ("Status", h["status"]), ("Released", f"{h['released']} by {h['by']}" if h["released"] else "not released"),
            ("Tool", design["kind"].replace("_", " ") + " · " + design["part_type"].replace("_", " ")), ("Tool country / rate month", f"{h['country']} / {h['month']}"),
            ("Made parts (part numbers / pieces)", f"{b['totals']['made_parts']} / {b['totals']['made_qty']}"), ("Raw steel to buy (kg)", b["totals"]["steel_kg"]),
            ("Bought-out items", len(b["standard"])), ("Assembly in your factory (hours)", f["assembly_hours"]),
            (f"Raw material ({f['currency']})", f["material"]), (f"Machining job work ({f['currency']})", f["machining"]),
            ("Bought-out parts (INR)", f["standard_inr"]), (f"Assembly ({f['currency']})", f["assembly"]),
            (f"Estimated total ({f['currency']})", f["total_local"]), ("Estimated total (INR)", f["total_inr"])]
    if f["engine"] is not None:
        rows.append((f"{f['engine_note']} ({f['currency']})", f["engine"]))
    rows += [("Notes", design["summary"].get("notes") or "")]
    for i, (k, v) in enumerate(rows, start=r + 3):
        ws.cell(i, 1, k).font = Font(bold=True)
        ws.cell(i, 2, v)
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 60
    # BOM
    sheet("BOM", ["Item", "Part no.", "Rev", "Name", "Class", "Stage", "Qty", "Steel / spec", "Finished L × W × T (mm)", "Stock L × W × T (mm)", "Weight each (kg)", "Drawing"],
          [[i, m["part_no"], m["rev"], m["name"], m["cls"], m["stage_no"] or "", m["qty"], m["info"]["steel"], " × ".join(f"{x:g}" for x in m["info"]["bbox_mm"]),
            " × ".join(f"{x:g}" for x in m["info"]["stock"]["size_mm"]), m["info"]["stock"]["finished_weight_kg"], f"{m['part_no']}_rev{m['rev']}.pdf"]
           for i, m in enumerate(made, start=1)]
          + [[f"S{i}", "", "", l["item"], "bought-out", "", l["quantity"], l["spec"], "", "", "", ""] for i, l in enumerate(b["standard"], start=1)],
          [6, 16, 6, 36, 14, 7, 6, 36, 24, 24, 12, 26])
    # PO-1
    rows, total_kg, total_amt = [], 0.0, 0.0
    for i, m in enumerate(made, start=1):
        st = m["info"]["stock"]
        kg = st["weight_kg"] * m["qty"]
        amt = (m["info"]["material_cost"] or 0) * m["qty"]
        total_kg += kg
        total_amt += amt
        rows.append([i, m["part_no"], m["name"], m["info"]["steel"], f"{st['size_mm'][0]:g} × {st['size_mm'][1]:g} × {st['size_mm'][2]:g}", m["qty"], st["weight_kg"], round(kg, 2),
                     m["info"]["steel_rate"] or "", round(amt), m["info"]["hardness"], STEEL_DELIVERY, q_for(design, "material", m["part_no"])])
    rows.append(["", "", "TOTAL", "", "", sum(m["qty"] for m in made), "", round(total_kg, 1), "", round(total_amt), "", "", ""])
    by_steel = {}
    for m in made:
        d = by_steel.setdefault(m["info"]["steel"], [0.0, 0.0])
        d[0] += m["info"]["stock"]["weight_kg"] * m["qty"]
        d[1] += (m["info"]["material_cost"] or 0) * m["qty"]
    rows += [["", "", "Steel summary", s, "", "", "", round(v[0], 1), "", round(v[1]), "", "", ""] for s, v in sorted(by_steel.items())]
    sheet("PO-1 Raw material", ["Item", "Part no.", "Name", "Steel grade", "Stock L × W × T (mm)", "Qty", "kg each", "kg total", f"Rate per kg ({f['currency']})",
                                f"Amount ({f['currency']})", "Supply hardness", "Delivery condition", f"Quoted rate per kg ({f['currency']})"], rows, [6, 16, 32, 32, 22, 6, 9, 10, 12, 14, 22, 60, 16])
    # PO-2
    proc_cols = ["Cutting (per kg)", "CNC milling", "Grinding", "EDM", "Wire cut (per cm²)", "Polishing"]
    rows, tot = [], 0
    for i, m in enumerate(made, start=1):
        oc = _ops_columns(m)
        cost = m["info"]["machining_cost"] * m["qty"]
        tot += cost
        rows.append([i, m["part_no"], m["rev"], m["name"], m["qty"], m["info"]["steel"], m["info"]["route"], m["info"]["hardness"], m["info"]["tolerance"],
                     m["info"]["finish_ra"] or "", round(oc.get("CNC milling", 0), 1), round(oc.get("Grinding", 0), 1), round(oc.get("EDM", 0), 1),
                     round(oc.get("Polishing", 0), 1), m["info"]["machining_cost"], round(cost), q_for(design, "machining", m["part_no"])])
    rows.append(["", "", "", "TOTAL", "", "", "", "", "", "", "", "", "", "", "", round(tot), ""])
    sheet("PO-2 Machining", ["Item", "Part no.", "Rev", "Name", "Qty", "Steel", "Route", "Hardness", "Tolerances", "Ra", "Milling / drilling h", "Grinding h", "EDM h",
                             "Polishing h", f"Estimate each ({f['currency']})", f"Estimate total ({f['currency']})", f"Quoted price each ({f['currency']})"], rows,
          [6, 16, 5, 30, 5, 28, 60, 22, 44, 6, 12, 10, 8, 10, 14, 16, 16])
    rows = []
    for m in made:
        for o in m["info"]["operations"]:
            rows.append([m["part_no"], m["name"], m["qty"], o["label"], o["process"], o["amount"], o["unit"], o["cost"] if o["cost"] is not None else "no rate", o["note"]])
    sheet("Machining detail", ["Part no.", "Name", "Qty", "Operation", "Process (rate)", "Amount", "Unit", f"Cost each ({f['currency']})", "Note"], rows,
          [16, 30, 5, 42, 30, 10, 6, 14, 30])
    # PO-3
    rows = [[i, l["item"], l["spec"], l["quantity"], l["unit"], l["unit_cost_inr"], l["amount_inr"], l["source"], q_for(design, "bought_out", l["item"])]
            for i, l in enumerate(b["standard"], start=1)]
    rows.append(["", "TOTAL", "", "", "", "", sum(l["amount_inr"] for l in b["standard"]), "", ""])
    cb = design["summary"].get("catalogue_base")
    if cb:
        rows.append(["", f"Alternative: {cb['item']}", "Buy the catalogue mould base instead of making plates A, B, clamp, support, spacer and ejector plates; "
                     "pockets and holes still to be machined", 1, "set", "", cb["price"], "Tool cost BOM (not in the total)"])
    sheet("PO-3 Bought-out", ["Item", "Description", "Specification", "Qty", "Unit", "Unit cost (INR)", "Amount (INR)", "Source", "Quoted unit price (INR)"], rows,
          [6, 44, 70, 6, 6, 14, 14, 30, 18])
    # Assembly
    rows = [[a["step"], a["text"], a["hours"]] for a in b["assembly"]] + [["", "TOTAL hours", round(sum(a["hours"] for a in b["assembly"]), 1)]]
    sheet("Assembly", ["Step", "Work in your factory", "Hours"], rows, [6, 120, 8])
    # Inspection
    rows = []
    for m in made:
        feats = m["info"]["features"]
        L, W, T = m["info"]["bbox_mm"]
        rows.append([m["part_no"], m["name"], "Overall size", f"{L:g} × {W:g} × {T:g}", m["info"]["tolerance"], "caliper / CMM"])
        for hh in feats["holes"]:
            rows.append([m["part_no"], m["name"], f"{hh['count']} × hole Ø{hh['dia_mm']:g}, depth {hh['depth_mm']:g}{' thru' if hh['through'] else ''}", f"Ø{hh['dia_mm']:g}",
                         "H7 where marked", "pin gauge / CMM"])
        for o in feats["openings"]:
            rows.append([m["part_no"], m["name"], f"Opening {o['length_mm']:g} × {o['width_mm']:g}", f"{o['length_mm']:g} × {o['width_mm']:g}", "per drawing", "CMM"])
        for p in feats["pockets"]:
            rows.append([m["part_no"], m["name"], f"Pocket {p['length_mm']:g} × {p['width_mm']:g} depth {p['depth_mm']:g}", f"depth {p['depth_mm']:g}", "per drawing", "CMM"])
        rows.append([m["part_no"], m["name"], f"Hardness {m['info']['hardness']}", m["info"]["hardness"], "HRC check", "hardness tester"])
    sheet("Inspection", ["Part no.", "Name", "Check", "Nominal", "Tolerance", "Method"], rows, [16, 30, 52, 20, 40, 18])
    # Features
    rows = []
    for m in made:
        for hh in m["info"]["features"]["holes"]:
            for pos in hh["positions_mm"]:
                rows.append([m["part_no"], "hole", hh["dia_mm"], hh["depth_mm"], hh["axis"], "yes" if hh["through"] else "no", *pos])
    sheet("Features", ["Part no.", "Type", "Ø (mm)", "Depth (mm)", "Axis", "Through", "X from datum", "Y from datum", "Z from datum"], rows, [16, 8, 8, 10, 6, 8, 12, 12, 12])
    # Quote comparison
    qrows = []
    for m in made:
        qm, qa = q_for(design, "material", m["part_no"]), q_for(design, "machining", m["part_no"])
        est_m, est_a = (m["info"]["material_cost"] or 0) * m["qty"], m["info"]["machining_cost"] * m["qty"]
        if qm != "":
            qrows.append([m["part_no"], "raw material", est_m, round(qm * m["info"]["stock"]["weight_kg"] * m["qty"]), round(qm * m["info"]["stock"]["weight_kg"] * m["qty"] - est_m), f"{qm:g} per kg"])
        if qa != "":
            qrows.append([m["part_no"], "machining", est_a, round(qa * m["qty"]), round(qa * m["qty"] - est_a), f"{qa:g} each"])
    for l in b["standard"]:
        qs = q_for(design, "bought_out", l["item"])
        if qs != "":
            qrows.append([l["item"], "bought-out (INR)", l["amount_inr"], round(qs * l["quantity"]), round(qs * l["quantity"] - l["amount_inr"]), f"{qs:g} each"])
    qrows.append(["TOTAL", "", sum(r[2] for r in qrows), sum(r[3] for r in qrows), sum(r[4] for r in qrows), ""])
    sheet("Quote comparison", ["Part / item", "Kind", "Estimate", "Quoted", "Quoted − estimate", "Quote"], qrows, [30, 18, 14, 14, 16, 22])
    # Cost summary
    rows = [[f"Raw material ({f['currency']})", f["material"]], [f"Machining job work ({f['currency']})", f["machining"]], [f"Bought-out parts ({f['currency']})", round(f["standard_inr"] / f["fx"])],
            [f"Assembly in your factory ({f['currency']})", f["assembly"]], [f"Total ({f['currency']})", f["total_local"]], ["Total (INR)", f["total_inr"]], ["INR per " + f["currency"], f["fx"]]]
    if f["engine"] is not None:
        rows += [[f"{f['engine_note']} ({f['currency']})", f["engine"]], ["Build-up minus engine", f["total_local"] - f["engine"]]]
    sheet("Cost summary", ["Item", "Value"], rows, [60, 20])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ------------------------------------------------------------ PDF purchase orders

def po_pdf(design: dict, kind: str) -> bytes:
    """kind: material | machining | bought_out. Blank supplier / buyer fields to fill in; lines from the design; drawing list."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from .pdf_report import _example_banner, _table, _theme
    theme = _theme()
    f, h, b = _facts(design), _head(design), design["bill"]
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=17, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=10.5, spaceBefore=8, spaceAfter=3)
    note = ParagraphStyle("n", parent=ss["Normal"], textColor=theme["grey"], fontSize=7.5, leading=9.5)
    body = ParagraphStyle("b", parent=ss["Normal"], fontSize=8.5, leading=11)
    cell = ParagraphStyle("c", parent=ss["Normal"], fontSize=7, leading=8)
    C = lambda text: Paragraph(str(text), cell)

    def banner(text):
        t = Table([[Paragraph(f"<font color='#ffffff'><b>{text}</b></font>", ss["Normal"])]], colWidths=[None])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#b91c1c")), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        return t
    title = {"material": "PURCHASE ORDER · RAW MATERIAL (tool steel)", "machining": "PURCHASE ORDER · MACHINING (job work)",
             "bought_out": "PURCHASE ORDER · BOUGHT-OUT PARTS"}[kind]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=10 * mm, bottomMargin=10 * mm,
                            title=f"{title} {h['part_code']}")
    story = [Paragraph("DESIGN TO COST", ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8)), Paragraph(title, h1),
             Paragraph(f"Tool: {h['part_code']} · design version {h['version']}, drawing revision {h['rev']}, {h['status']} · rate month {h['month']} · {h['date']}", note)]
    if h["status"] != "released":
        story += [Spacer(1, 2 * mm), banner("DRAFT design: not released. Do not place orders from this document.")]
    if f["example"]:
        story += [Spacer(1, 2 * mm), _example_banner(ss)]
    fields = Table([["PO no.:  ____________________", "Date:  ____________", "Supplier:  ______________________________________________"],
                    ["Buyer:  ______________________________________", "Delivery to:  ____________________________", "Delivery date:  ____________"],
                    ["Payment terms:  ________________", "Currency:  " + (f["currency"] if kind != "bought_out" else "INR"), "Contact:  ____________________________"]],
                   colWidths=[85 * mm, 85 * mm, 105 * mm], rowHeights=7 * mm)
    fields.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8.5)]))
    story += [Spacer(1, 3 * mm), fields, Spacer(1, 2 * mm)]
    made = b["made"]
    if kind == "material":
        rows = [["#", "Part no.", "Name", "Steel grade", "Stock L × W × T (mm)", "Qty", "kg each", "kg total", "Hardness as supplied", "Rate / kg", "Amount"]]
        tk = ta = 0
        for i, m in enumerate(made, start=1):
            st = m["info"]["stock"]
            kg = st["weight_kg"] * m["qty"]
            amt = (m["info"]["material_cost"] or 0) * m["qty"]
            tk += kg
            ta += amt
            rows.append([str(i), m["part_no"], C(m["name"]), C(m["info"]["steel"]), " × ".join(f"{x:g}" for x in st["size_mm"]), str(m["qty"]), f"{st['weight_kg']:g}", f"{kg:.1f}",
                         C(m["info"]["hardness"]), f"{m['info']['steel_rate'] or 0:g}", f"{amt:,.0f}"])
        rows.append(["", "", "TOTAL", "", "", "", "", f"{tk:.1f}", "", "", f"{ta:,.0f}"])
        story.append(_table(rows, theme, [8 * mm, 30 * mm, 48 * mm, 52 * mm, 38 * mm, 10 * mm, 15 * mm, 17 * mm, 30 * mm, 14 * mm, 18 * mm], total_rows=(len(rows) - 1,)))
        story += [Paragraph("Terms", h2), Paragraph(
            "Supply as sawn blocks of the stock size stated (machining allowance is included; tolerance +5 / 0 mm). Material certificate EN 10204 3.1 with every steel, "
            "heat number marked on each block. Pre-hardened grades to the hardness stated. Amounts are estimates from the approved tool-steel rates of the tool country: "
            "the order value is as agreed with the supplier.", body)]
    elif kind == "machining":
        rows = [["#", "Part no.", "Rev", "Name", "Qty", "Steel", "Route", "Hardness", "Tolerances", f"Est. each ({f['currency']})", "Est. total"]]
        tot = 0
        for i, m in enumerate(made, start=1):
            cost = m["info"]["machining_cost"] * m["qty"]
            tot += cost
            rows.append([str(i), m["part_no"], m["rev"], C(m["name"]), str(m["qty"]), C(m["info"]["steel"]), C(m["info"]["route"]), C(m["info"]["hardness"]), C(m["info"]["tolerance"]),
                         f"{m['info']['machining_cost']:,.0f}", f"{cost:,.0f}"])
        rows.append(["", "", "", "TOTAL", "", "", "", "", "", "", f"{tot:,.0f}"])
        story.append(_table(rows, theme, [7 * mm, 27 * mm, 8 * mm, 36 * mm, 8 * mm, 28 * mm, 50 * mm, 22 * mm, 42 * mm, 18 * mm, 18 * mm], total_rows=(len(rows) - 1,)))
        story += [Paragraph("Terms", h2), Paragraph(
            "Machine every part to the attached drawing and STEP file of the revision stated; the 3D file governs when it differs from the drawing. Steel is supplied by the buyer "
            "(free issue) unless the raw-material order says otherwise. Hardening, grinding and wire cutting in the sequence of the route. Final inspection report with the key "
            "dimensions of the inspection list for every part. Estimates come from the approved process rates of the tool country and the process time parameters.", body)]
    else:
        rows = [["#", "Description", "Specification", "Qty", "Unit", "Unit cost (INR)", "Amount (INR)"]]
        for i, l in enumerate(b["standard"], start=1):
            rows.append([str(i), C(l["item"]), C(l["spec"]), str(l["quantity"]), l["unit"], f"{l['unit_cost_inr']:,.0f}", f"{l['amount_inr']:,.0f}"])
        rows.append(["", "TOTAL", "", "", "", "", f"{sum(l['amount_inr'] for l in b['standard']):,.0f}"])
        story.append(_table(rows, theme, [8 * mm, 60 * mm, 110 * mm, 12 * mm, 12 * mm, 30 * mm, 30 * mm], total_rows=(len(rows) - 1,)))
        story += [Paragraph("Terms", h2), Paragraph("Catalogue parts to the specification stated, with the supplier's certificate of conformity where applicable. Unit costs are catalogue "
                                                      "prices from master data (EXAMPLE until replaced).", body)]
    story += [Paragraph("Drawings attached", h2), Paragraph(", ".join(f"{m['part_no']} rev {m['rev']}" for m in made) or "none", note)]
    doc.build(story)
    return buf.getvalue()
