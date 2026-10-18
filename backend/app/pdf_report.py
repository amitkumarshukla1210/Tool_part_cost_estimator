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

ROOT = Path(__file__).resolve().parents[2]


def _theme() -> dict:
    css = (ROOT / "theme" / "dtc-theme.css").read_text(encoding="utf-8")
    get = lambda n: colors.HexColor(re.search(rf"--{n}:\s*(#[0-9a-fA-F]{{6}})", css).group(1))
    return {k: get(v) for k, v in {"ink": "ink", "brand": "brand-dark", "head": "table-head-dark",
                                   "head_text": "table-head-dark-text", "alt": "table-row-alt",
                                   "calc": "calc-cell-bg", "grey": "grey", "border": "grey-border"}.items()}


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

    story += [Paragraph("Parts", h2), _table([
        ["Parts", "File missing", "With target cost", "Open corrections"],
        [d["parts_total"], d["file_missing"], d["parts_with_target"], d["open_corrections"]]], theme)]
    story += [Paragraph("Status", h2), _table([["Status", "Parts"]] + [[s["name"], s["count"]] for s in d["status"]], theme,
                                              [80 * mm, 30 * mm])]
    story += [Paragraph("Variants", h2), _table(
        [["Variant", "Name", "Annual volume", "BOM lines", "Unique parts", "Target BOM cost", "BOM cost (costed)"]] +
        [[v["code"], v["name"], f"{v['annual_volume']:,}" if v["annual_volume"] else "—", v["bom_lines"], v["unique_parts"],
          _money(v["target_bom_cost_inr"]), _money(v["bom_cost_inr"])] for v in d["variants"]], theme)]
    story += [Paragraph("CAPEX", h2), _table(
        [["", "INR"], ["Budget", _money(d["capex"]["budget_inr"])], ["Tools & moulds (costed)", _money(d["capex"]["tool_cost_inr"])],
         ["Machines (costed)", _money(d["capex"]["machine_cost_inr"])]], theme, [80 * mm, 50 * mm])]
    story += [Spacer(1, 4 * mm), Paragraph(d["not_costed_note"], note), Spacer(1, 2 * mm),
              Paragraph("© Design to Cost", note)]
    doc.build(story)
    return buf.getvalue()
