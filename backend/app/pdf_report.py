"""PDF exports in the Design to Cost style (ReportLab; colours read from the theme file)."""

from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .trace import EXAMPLE_WARNING

ROOT = Path(__file__).resolve().parents[2]


def _theme() -> dict:
    css = (ROOT / "theme" / "dtc-theme.css").read_text(encoding="utf-8")
    get = lambda n: colors.HexColor(re.search(rf"--{n}:\s*(#[0-9a-fA-F]{{6}})", css).group(1))
    return {k: get(v) for k, v in {"ink": "ink", "brand": "brand-dark", "head": "table-head-dark",
                                   "head_text": "table-head-dark-text", "alt": "table-row-alt",
                                   "calc": "calc-cell-bg", "grey": "grey", "border": "grey-border"}.items()}


def _example_banner(ss, detail: str = "") -> Table:
    """Red warning box for a cost that uses EXAMPLE rates."""
    text = f"<font color='#ffffff'><b>{EXAMPLE_WARNING}</b></font>" + (f"<br/><font color='#ffffff' size=7>{detail}</font>" if detail else "")
    t = Table([[Paragraph(text, ss["Normal"])]], colWidths=[None])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#b91c1c")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def _table(rows, theme, widths=None, total_rows=()):
    t = Table(rows, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), theme["head"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), theme["head_text"]),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("GRID", (0, 0), (-1, -1), 0.25, theme["border"]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), theme["alt"]))
    for i in total_rows:
        style += [("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"), ("LINEABOVE", (0, i), (-1, i), 1, theme["head"])]
    t.setStyle(TableStyle(style))
    return t


def _money(v):
    return "—" if v is None else f"INR {v:,.0f}"


def dashboard_pdf(d: dict) -> bytes:
    theme = _theme()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Design to Cost — {d['project']['code']} project summary", author="Design to Cost")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=18, alignment=0, spaceAfter=2)
    kicker = ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8, leading=10)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=11, spaceBefore=10, spaceAfter=4)
    note = ParagraphStyle("n", parent=ss["Normal"], textColor=theme["grey"], fontSize=7.5)
    p = d["project"]
    logo = ROOT / "theme" / "logo.png"
    head = Table([[Image(str(logo), 11 * mm, 11 * mm) if logo.exists() else "",
                   Paragraph("<b>Design to Cost</b><br/><font size=7 color='#6b7683'>PART COST ESTIMATOR</font>", ss["Normal"]),
                   Paragraph(f"<font size=7 color='#6b7683'>{date.today().isoformat()}</font>", ss["Normal"])]],
                 colWidths=[14 * mm, 120 * mm, None])
    story = [head, Spacer(1, 4 * mm), Paragraph("PROJECT SUMMARY", kicker),
             Paragraph(f"{p['code']} · {p['name']}", h1),
             Paragraph(f"Customer: {p.get('customer') or '—'} · CAPEX budget: {_money(p.get('capex_budget_inr'))}", note)]
    if any(v.get("rm_is_example") for v in d["variants"]) or d["capex"].get("tool_is_example"):
        what = [w for w, on in (("the RM cost of at least one variant", any(v.get("rm_is_example") for v in d["variants"])),
                                ("the tool CAPEX", d["capex"].get("tool_is_example"))) if on]
        story += [Spacer(1, 2 * mm), _example_banner(ss, " and ".join(what).capitalize() + " includes EXAMPLE values.")]

    story += [Paragraph("Parts", h2), _table([
        ["Parts", "File missing", "With target cost", "Open corrections"],
        [d["parts_total"], d["file_missing"], d["parts_with_target"], d["open_corrections"]]], theme)]
    story += [Paragraph("Status", h2), _table([["Status", "Parts"]] + [[s["name"], s["count"]] for s in d["status"]], theme,
                                              [80 * mm, 30 * mm])]
    story += [Paragraph("Variants", h2), _table(
        [["Variant", "Name", "Annual volume", "BOM lines", "Unique parts", "Target BOM cost", "RM cost (costed parts)",
          "Parts without RM", "BOM cost (costed)"]] +
        [[v["code"], v["name"], f"{v['annual_volume']:,}" if v["annual_volume"] else "—", v["bom_lines"], v["unique_parts"],
          _money(v["target_bom_cost_inr"]), _money(v.get("rm_cost_inr")), v.get("rm_parts_missing", 0),
          _money(v["bom_cost_inr"])] for v in d["variants"]], theme)]
    story += [Paragraph("CAPEX", h2), _table(
        [["", "INR"], ["Budget", _money(d["capex"]["budget_inr"])],
         [f"Tools & moulds ({d['capex'].get('tool_parts_costed', 0)} parts costed, "
          f"{d['capex'].get('tool_parts_missing', 0)} without tool cost)", _money(d["capex"]["tool_cost_inr"])],
         ["Tools as % of budget", "—" if d["capex"].get("tool_share_of_budget_pct") is None
          else f"{d['capex']['tool_share_of_budget_pct']} %"],
         ["Machines (costed)", _money(d["capex"]["machine_cost_inr"])]], theme, [110 * mm, 50 * mm])]
    if d["capex"].get("tool_note"):
        story += [Paragraph(d["capex"]["tool_note"], note)]
    story += [Spacer(1, 4 * mm), Paragraph(d["not_costed_note"], note), Spacer(1, 2 * mm),
              Paragraph("© Design to Cost", note)]
    doc.build(story)
    return buf.getvalue()


def rm_cost_pdf(part: dict, tr: dict) -> bytes:
    """RM cost sheet of one part: result, every step with its formula, every input with its source, rate versions."""
    from .trace import source_text
    theme = _theme()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Design to Cost — RM cost {part['part_code']}", author="Design to Cost")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=18, alignment=0, spaceAfter=2)
    kicker = ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8, leading=10)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=11, spaceBefore=10, spaceAfter=4)
    note = ParagraphStyle("n", parent=ss["Normal"], textColor=theme["grey"], fontSize=7.5)
    cell = ParagraphStyle("c", parent=ss["Normal"], fontSize=7.5, leading=9)
    wrap = lambda t: Paragraph(str(t).replace("&", "&amp;").replace("<", "&lt;"), cell)
    num = lambda v: f"{v:,.4f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}"
    cur = tr["currency"]
    example = any(x.get("is_example") for x in tr["rates_used"])
    logo = ROOT / "theme" / "logo.png"
    head = Table([[Image(str(logo), 11 * mm, 11 * mm) if logo.exists() else "",
                   Paragraph("<b>Design to Cost</b><br/><font size=7 color='#6b7683'>PART COST ESTIMATOR</font>", ss["Normal"]),
                   Paragraph(f"<font size=7 color='#6b7683'>{date.today().isoformat()}</font>", ss["Normal"])]],
                 colWidths=[14 * mm, 120 * mm, None])
    story = [head, Spacer(1, 4 * mm), Paragraph("RAW-MATERIAL COST SHEET", kicker),
             Paragraph(f"{part['part_code']} · {part['name']}", h1),
             Paragraph(f"Rev {tr.get('revision', {}).get('rev', '—')} · {tr['material']} · {tr['country']} · costing month "
                       f"{tr['as_of']} · " + (f"version {tr['version']}" if tr["version"] else "live preview, not stored"), note)]
    if example:
        story += [Spacer(1, 2 * mm), _example_banner(ss, "Replace the EXAMPLE rates marked below on the Rates page first.")]
    story += [Paragraph("Result", h2), _table([
        ["", cur, "INR"], ["Net RM cost per part", num(tr["value"]), num(tr["value_inr"])]], theme, [90 * mm, 40 * mm, 40 * mm], [1])]
    steps = [[wrap(n["label"]), wrap(n["formula"]), num(n["value"]), n["unit"]] for n in tr["nodes"].values()
             if n["kind"] == "calculated"]
    story += [Paragraph("Steps and formulas", h2), _table([["Step", "Formula", "Value", "Unit"]] + steps, theme,
                                                          [60 * mm, 110 * mm, 30 * mm, 25 * mm])]
    inputs = [[wrap(n["label"]), num(n["value"]), n["unit"], wrap(source_text(n))] for n in tr["nodes"].values()
              if n["kind"] == "input"]
    story += [Paragraph("Inputs and where each comes from", h2), _table([["Input", "Value", "Unit", "Comes from"]] + inputs,
                                                                          theme, [60 * mm, 25 * mm, 22 * mm, 118 * mm])]
    used = [[x["id"], f"{x['category']} / {x['item']}", x["country"], x["month"], num(x["value"]), x["unit"], x["status"],
             x["approved_by"], "EXAMPLE" if x.get("is_example") else ""] for x in tr["rates_used"]]
    story += [Paragraph("Rate versions used (the report can be reproduced with these)", h2), _table(
        [["Id", "Rate", "Country", "Month", "Value", "Unit", "Status", "Approved by", ""]] + used, theme)]
    story += [Spacer(1, 4 * mm), Paragraph("© Design to Cost", note)]
    doc.build(story)
    return buf.getvalue()


def tool_cost_pdf(tr: dict, part: dict | None = None) -> bytes:
    """Tool cost sheet of one mould / die: result, cost build-up, BOM & processes, steps, inputs with sources, rates."""
    from .tool_cost import examples
    from .trace import source_text
    theme = _theme()
    buf = io.BytesIO()
    title = part["part_code"] if part else "Estimate"
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Design to Cost — Tool cost {title}", author="Design to Cost")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=18, alignment=0, spaceAfter=2)
    kicker = ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8, leading=10)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=11, spaceBefore=10, spaceAfter=4)
    note = ParagraphStyle("n", parent=ss["Normal"], textColor=theme["grey"], fontSize=7.5)
    cell = ParagraphStyle("c", parent=ss["Normal"], fontSize=7.5, leading=9)
    wrap = lambda t: Paragraph(str(t).replace("&", "&amp;").replace("<", "&lt;"), cell)
    num = lambda v: "—" if v is None else (f"{v:,.4f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}")
    cur, nodes = tr["currency"], tr["nodes"]
    ex = tr.get("example") or examples(tr)
    logo = ROOT / "theme" / "logo.png"
    head = Table([[Image(str(logo), 11 * mm, 11 * mm) if logo.exists() else "",
                   Paragraph("<b>Design to Cost</b><br/><font size=7 color='#6b7683'>PART COST ESTIMATOR</font>", ss["Normal"]),
                   Paragraph(f"<font size=7 color='#6b7683'>{date.today().isoformat()}</font>", ss["Normal"])]],
                 colWidths=[14 * mm, 120 * mm, None])
    b = tr["base"]
    machine = (tr["trial"]["machine"] or {}).get("machine_id", "missing")
    story = [head, Spacer(1, 4 * mm), Paragraph("TOOL COST SHEET", kicker),
             Paragraph(f"{part['part_code']} · {part['name']}" if part else "Tool cost estimate", h1),
             Paragraph((f"Rev {tr.get('revision', {}).get('rev', '—')} · " if part else "")
                       + f"{tr['part_type'].replace('_', ' ')} · {tr['cavities']} cavities · base {b['series']} {b['size_code']} · "
                       f"try-out on {machine} · tool country {tr['country']} · costing month {tr['as_of']} · "
                       + (f"version {tr['version']}" if tr.get("version") else "live preview, not stored"), note)]
    if ex["any"]:
        story += [Spacer(1, 2 * mm), _example_banner(ss, ex["detail"])]
    story += [Paragraph("Result", h2), _table([
        ["", cur, "INR"], ["Tool cost per tool", num(tr["value"]), num(tr["value_inr"])],
        [f"Tool CAPEX ({tr['tools_count']} tools over the programme)", num(tr.get("capex")), num(tr.get("capex_inr"))]],
        theme, [110 * mm, 40 * mm, 40 * mm], [1])]
    build = [[wrap(nodes[g["node"]]["label"]), "Σ BOM lines of the group", num(nodes[g["node"]]["value"]), cur] for g in tr["groups"]]
    build += [[wrap(nodes[s["node"]]["label"]), wrap(nodes[s["node"]]["formula"]), num(nodes[s["node"]]["value"]),
               nodes[s["node"]]["unit"]] for s in tr["steps"]]
    story += [Paragraph("Cost build-up (process-wise, then trial, overhead, profit, packing, transport, warranty)", h2),
              _table([["Step", "Formula", "Value", "Unit"]] + build, theme, [70 * mm, 110 * mm, 30 * mm, 25 * mm],
                     [1 + len(tr["groups"]) + i for i, s in enumerate(tr["steps"]) if s["is_result"]])]
    bom = [[wrap(l["element"] + (" •" if l["is_example"] else "")), l["category"].replace("_", " "), num(l["quantity"]),
            wrap(l["material"]), num(l["material_cost"]) if l["material_cost"] else "", num(l["bought_out_cost"]) if l["bought_out_cost"] else "",
            wrap(l["process"]), num(l["hours"]) if l["hours"] else (num(l["amount"]) if l["amount"] else ""),
            num(l["process_cost"]) if l["process_cost"] else "", num(l["total"])] for l in tr["lines"]]
    story += [Paragraph(f"BOM & processes ({cur}; • = EXAMPLE master-data row)", h2), _table(
        [["Element", "Category", "Qty", "Steel", "Steel cost", "Bought-out", "Process", "Hours / amount", "Process cost",
          "Line total"]] + bom, theme, [52 * mm, 20 * mm, 14 * mm, 28 * mm, 22 * mm, 22 * mm, 38 * mm, 22 * mm, 22 * mm, 24 * mm])]
    steps = [[wrap(n["label"]), wrap(n["formula"]), num(n["value"]), n["unit"]] for n in nodes.values() if n["kind"] == "calculated"]
    story += [Paragraph("Every step and formula", h2), _table([["Step", "Formula", "Value", "Unit"]] + steps, theme,
                                                              [70 * mm, 110 * mm, 30 * mm, 25 * mm])]
    inputs = [[wrap(n["label"]), num(n["value"]), n["unit"], wrap(source_text(n))] for n in nodes.values() if n["kind"] == "input"]
    story += [Paragraph("Inputs and where each comes from", h2), _table([["Input", "Value", "Unit", "Comes from"]] + inputs,
                                                                          theme, [70 * mm, 25 * mm, 22 * mm, 118 * mm])]
    used = [[x["id"], f"{x['category']} / {x['item']}", x["country"], x["month"], num(x["value"]), x["unit"], x["status"],
             x["approved_by"], "EXAMPLE" if x.get("is_example") else ""] for x in tr["rates_used"]]
    story += [Paragraph("Rate versions used (the report can be reproduced with these)", h2), _table(
        [["Id", "Rate", "Country", "Month", "Value", "Unit", "Status", "Approved by", ""]] + used, theme)]
    if ex["rows"]:
        story += [Paragraph("Master-data rows still marked EXAMPLE", h2), Paragraph(", ".join(ex["rows"]), note)]
    story += [Spacer(1, 4 * mm), Paragraph("© Design to Cost", note)]
    doc.build(story)
    return buf.getvalue()
