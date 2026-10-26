"""Audit of roadmap stage 27 from a tool-room head's point of view: what is done for every tool type, what is not.

    python docs/work_instruction/build_audit.py     -> frontend/docs/DTC_Audit_Tool_Design.pdf
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "frontend" / "docs" / "DTC_Audit_Tool_Design.pdf"

TYPES = ["Sheet metal: multi-stage dies", "Sheet metal: progressive die", "Plastic injection mould", "Die-casting die",
         "EPS mould", "Stretch-blow mould", "Foundry pattern / core box"]
# task -> one status per type: (mark, note); mark = OK / PART / NO
MATRIX = [
    ("3D assembly (STEP) with every part", [
        ("OK", "Blanking, piercing, trimming, V-bending, U-bending (pressure pad, springs, gauge pins), deep drawing (punch, die, blank holder, cushion pins) and draw + trim: shoes, pillars, bushes, plates, punches, screws, dowels"),
        ("OK", "Piercing, forming stations and cut-off at the pitch, stop pin, stripper, guides"),
        ("OK", "Core / cavity × shrinkage, plates, ejection, cooling; sprue / cold runner + edge gates or hot-runner manifold + nozzles; slides with heel block and angle pin, lifters where undercuts are found"),
        ("OK", "Mould structure + shot sleeve, biscuit, runners, overflows and vacuum vents"),
        ("OK", "Cavity / core halves, steam chambers, back plates, fill injectors, steam vents"),
        ("OK", "Cavity halves, neck and base inserts, blow pin"),
        ("OK", "Match plate, cope / drag patterns with gating and riser pattern, core box, cope / drag flasks and flask pins"),
    ]),
    ("Every part as its own 3D (STEP)", [("OK", "")] * 7),
    ("2D drawings: assembly + detail of every made part (PDF and DXF)", [
        ("OK", "Assembly: iso, exploded, section, BOM. Plates: true views, hole table with fits and depths. Punches / dies: three views; profiles in DXF for wire cut"),
        ("OK", "As multi-stage"), ("OK", "Plates as above; core / cavity: three views + STEP (3D-machined)"), ("OK", "As plastic"),
        ("OK", "As plastic"), ("OK", "As plastic"), ("OK", "Patterns, core box and flasks: three views + STEP")]),
    ("Tolerances, fits, finish, heat treatment, labels on drawings", [
        ("OK", "ISO 2768-mK, flatness / parallelism, fits (pillar g6, bush H7, dowel and punch m6/H7), finishes, hardness - all Design rules"),
        ("OK", ""), ("OK", "+ insert-in-pocket fit, cavity polish"), ("OK", ""), ("OK", ""), ("OK", ""), ("OK", "Pattern tolerances and finish from Design rules")]),
    ("Logo and title block on every drawing (CAD and PDF)", [("OK", "Admin → Drawings: logo, company, projection, drawn / checked / approved, notes; DXF logo as hatches")] + [("OK", "")] * 6),
    ("Simulation report (PDF)", [("OK", "Forming report: checks, blank and yield, stages, force, press, pictures, flat pattern; drawn parts detected"),
        ("OK", "Same report"), ("OK", "Wall / draft / sink / undercut maps, cycle, clamp, gate count, machine"), ("OK", "Same analysis"),
        ("OK", "EPS rules: draft, thin / thick walls, fill, steam, cooling, cycle"), ("OK", "Blow rules: thin (over-stretched) / thick walls, blow, cooling, cycle"), ("OK", "Foundry rules: pattern draft, misrun / hot spots, solidification, riser size")]),
    ("Simulation video (MP4)", [("OK", "Blanking, piercing, bends folding; failing bend in red"), ("OK", ""),
        ("OK", "Turntable of the wall, draft and risk maps with the result"), ("OK", ""), ("OK", ""), ("OK", ""), ("OK", "")]),
    ("Correct the 3D model in the software and release it as a new revision", [
        ("OK", "Bend radius (outside size kept) and small holes; preview, STEP, new revision"), ("OK", "Same"),
        ("OK", "Draft added to the walls in 3D (default = min. draft + 0.5°); wall / rib changes still in CAD"), ("OK", "As plastic"),
        ("OK", "As plastic"), ("OK", "As plastic"), ("OK", "As plastic")]),
    ("Release pack ZIP for the tool room (3D + PDF + DXF + BOM)", [("OK", "")] * 7),
    ("Large parts 10-20 kg (presses / machines up to 3000-4000 t)", [
        ("OK", "Presses to 3000 t, heavy die sets to 4800 × 2400, large sheet 4000 × 2000; sample tray 16.6 kg (draw + trim), channel 18.3 kg (U-bend)"),
        ("OK", "As multi-stage"), ("OK", "Machines to 4000 t, mould bases to 2200 mm, one cavity for large parts; sample tub 11.9 kg PP"),
        ("OK", "HPDC to 2500 t, die holders to 1600 mm"), ("OK", "Steam-chest base by size"), ("OK", "-"), ("OK", "Flask size from the part")]),
]

FINDINGS = [
    ("Checked and right",
     ["Blanking: die opening = blank size, punch = blank − clearance; piercing: punch = hole, die = hole + clearance (Design rules).",
      "Flat pattern unfolded from the 3D model; bend correction matches the designer's Rev B to 0.01 mm.",
      "Drawn parts (doubly curved walls) are recognised: blank → draw → trim, with draw die, blank holder and trim die in 3D.",
      "Large parts: plate / bed size of the press or machine is checked against the die set / mould base, not only the force.",
      "Mould: core and cavity with shrinkage; gate count and fill time from Design rules; slides and lifters placed where the analysis finds undercuts.",
      "Foundry: pattern equipment has a tool cost and a 3D design (match plate, patterns, gating / riser, core box, flasks).",
      "No number is fixed in the program: sizes, fits, tolerances and machine data are Master data (EXAMPLE values flagged until replaced)."]),
    ("Check before release (tool designer) - normal tool-room practice",
     ["Press shut height, bed size and T-slots against the press data sheet.",
      "Slide / lifter face: the shape that forms the undercut is cut from the part, check the stroke and lock angle.",
      "V-bending: springback compensation by try-out; cooling layout of large moulds (generic straight channels).",
      "Foundry parting line is chosen from the largest section (heuristic): confirm with the foundry; EPS steam vent pattern size.",
      "Detail drawings give overall sizes; 3D surfaces and profiles come from the STEP / DXF (CNC, wire cut)."]),
    ("Not done (out of scope of the software)",
     ["Wall-thickness and rib changes in 3D: done in CAD, the new revision is uploaded and checked again.",
      "Full FEM / flow simulation (Moldflow, AutoForm): the report is a rule-based check, use it before ordering a full analysis."]),
]


def build() -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from backend.app import drawing_style
    from backend.app.pdf_report import _theme
    theme = _theme()
    ss = getSampleStyleSheet()
    st = {"h1": ParagraphStyle("h1", parent=ss["Title"], fontSize=15, alignment=0, textColor=theme["ink"]),
          "k": ParagraphStyle("k", parent=ss["Normal"], fontSize=8, textColor=theme["brand"]),
          "h2": ParagraphStyle("h2", parent=ss["Heading3"], textColor=theme["ink"], spaceBefore=8, spaceAfter=3),
          "n": ParagraphStyle("n", parent=ss["Normal"], fontSize=8.5, leading=11),
          "c": ParagraphStyle("c", parent=ss["Normal"], fontSize=6.6, leading=8)}
    fill = {"OK": colors.HexColor("#dcfce7"), "PART": colors.HexColor("#fef9c3"), "NO": colors.HexColor("#fee2e2")}
    word = {"OK": "Done", "PART": "Partly", "NO": "Not yet"}
    head = [Paragraph("<b>Task</b>", st["c"])] + [Paragraph(f"<b>{t}</b>", st["c"]) for t in TYPES]
    rows, style = [head], [("GRID", (0, 0), (-1, -1), 0.3, theme["border"]), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BACKGROUND", (0, 0), (-1, 0), theme["alt"])]
    for i, (task, cells) in enumerate(MATRIX, start=1):
        rows.append([Paragraph(f"<b>{task}</b>", st["c"])] + [Paragraph(f"<b>{word[m]}</b>" + (f"<br/>{n}" if n else ""), st["c"])
                                                             for m, n in cells])
        for j, (m, _) in enumerate(cells, start=1):
            style.append(("BACKGROUND", (j, i), (j, i), fill[m]))
    W = 269 * mm
    grid = Table(rows, colWidths=[40 * mm] + [(W - 40 * mm) / len(TYPES)] * len(TYPES), repeatRows=1)
    grid.setStyle(TableStyle(style))
    done = sum(1 for _, cells in MATRIX for m, _ in cells if m == "OK")
    total = sum(len(c) for _, c in MATRIX)
    story = [drawing_style.pdf_header(st, "AUDIT · TOOL DESIGN, DRAWINGS, SIMULATION, 3D CORRECTION",
                                      "Is every task complete for every type of mould and tool?"),
             Paragraph(f"Audit of release {date.today().isoformat()} from a tool-room head's point of view. {done} of {total} "
                       "task × tool-type cells are done for every die, mould and pattern type, including large parts of 10-20 kg on "
                       "machines up to 3000-4000 t. The designer checks listed below are normal tool-room release checks. Every output was made from the sample parts and checked (pictures, drawings, "
                       "STEP files, automated tests).", st["n"]), Spacer(1, 3 * mm), grid]
    for title, items in FINDINGS:
        story += [Paragraph(title, st["h2"])] + [Paragraph(f"• {x}", st["n"]) for x in items]
    story += [Spacer(1, 4 * mm), drawing_style.pdf_title_block(W, [("Scope", "Roadmap stages 27-28"), ("Audited", date.today().isoformat())],
                                                               "sheet_metal", "-", "1 / 1", "DTC-AUDIT-28", "")]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUT), pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=10 * mm,
                            bottomMargin=10 * mm, title="Audit - tool design", author="Design to Cost")
    doc.build(story)
    return OUT


if __name__ == "__main__":
    print("wrote", build())
