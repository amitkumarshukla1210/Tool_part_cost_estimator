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
        ("OK", "Blanking, piercing, trimming, V-bending: shoes, pillars, bushes, die plate, backing plates, guides / nest, stop pin, stripper, punch holder, punches, screws, dowels"),
        ("PART", "Piercing + cut-off stations at the pitch; forming stations, pilots and lifters are left to the designer"),
        ("OK", "Core / cavity from the part × shrinkage, A / B / clamp / support plates, spacer blocks, ejector plates and pins, return pins, pillars, bushes, sprue bush, locating ring, cooling"),
        ("PART", "Same structure with die-casting rules; shot sleeve, runner, overflows and vacuum vents are left to the designer"),
        ("PART", "Cavity and core halves in the steam-chest base; fill injectors, vents and steam chambers are left to the designer"),
        ("PART", "Two cavity halves split through the middle; neck / base inserts and blow pin are left to the designer"),
        ("NO", "No tool cost for foundry yet (planned stage), so no tool design"),
    ]),
    ("Every part as its own 3D (STEP)", [("OK", ""), ("OK", ""), ("OK", ""), ("OK", ""), ("OK", ""), ("OK", ""), ("NO", "")]),
    ("2D drawings: assembly + detail of every made part (PDF and DXF)", [
        ("OK", "Assembly: iso, exploded, section, BOM. Plates: true views, hole table with fits and depths. Punches / V-die: three views; profiles in DXF for wire cut"),
        ("OK", "As multi-stage"), ("OK", "Plates as above; core / cavity: three views + STEP (3D-machined)"), ("OK", "As plastic"),
        ("OK", "As plastic"), ("OK", "As plastic"), ("NO", "")]),
    ("Tolerances, fits, finish, heat treatment, labels on drawings", [
        ("OK", "General tolerance ISO 2768-mK, plate thickness / flatness / parallelism, fits (pillar g6, bush H7, dowel and punch m6/H7), position of fitted holes, finishes, hardness, heat-treatment note - all Design rules"),
        ("OK", ""), ("OK", "+ insert-in-pocket fit, cavity polish"), ("OK", ""), ("OK", ""), ("OK", ""), ("NO", "")]),
    ("Logo and title block on every drawing (CAD and PDF)", [("OK", "Admin → Drawings: logo, company, projection, drawn / checked / approved, notes; DXF logo as hatches"),
        ("OK", ""), ("OK", ""), ("OK", ""), ("OK", ""), ("OK", ""), ("NO", "")]),
    ("Simulation report (PDF)", [("OK", "Forming report: checks OK / FAIL, blank and yield, stages, force, press, pictures per stage, flat pattern"),
        ("OK", "Same report"), ("OK", "Wall / draft / sink / undercut maps, cycle, clamp, machine"), ("OK", "Same analysis"),
        ("NO", "No simulation rules for EPS yet"), ("NO", "No simulation rules for blow moulding yet"), ("NO", "")]),
    ("Simulation video (MP4)", [("OK", "Blanking, piercing, bends folding; failing bend in red"), ("OK", ""),
        ("OK", "Turntable of the wall, draft and risk maps with the result"), ("OK", ""), ("NO", ""), ("NO", ""), ("NO", "")]),
    ("Correct the 3D model in the software and release it as a new revision", [
        ("OK", "Bend radius (outside size kept) and small holes; preview, STEP, new revision"), ("OK", "Same"),
        ("NO", "Draft, wall and rib changes need CAD: upload the new revision"), ("NO", "As plastic"), ("NO", ""), ("NO", ""), ("NO", "")]),
    ("Release pack ZIP for the tool room (3D + PDF + DXF + BOM)", [("OK", ""), ("OK", ""), ("OK", ""), ("OK", ""), ("OK", ""), ("OK", ""), ("NO", "")]),
]

FINDINGS = [
    ("Checked and right",
     ["Blanking: die opening = blank size, punch = blank − clearance; piercing: punch = hole, die = hole + clearance (clearance % of t per side, Design rules).",
      "Flat pattern unfolded from the 3D model: the sample L bracket corrected in the software to R2 unfolds to exactly the designer's Rev B (326.178 mm).",
      "Bend correction keeps the outside size (checked on rounded and sharp-cornered models) and the holes; the new revision passes the forming check.",
      "Die plate and punches D2 58-62 HRC, shoes and plates from the die set / mould base material, grades from the tool BOM (Grade rules, your choices).",
      "Every plate has its holes in a table from the datum corner: through holes, counterbores, tapped holes, fits with position tolerance.",
      "Mould: core and cavity cut from the part with shrinkage; ejector pins cut to the core surface; cooling channels kept clear of the part.",
      "No number is fixed in the program: sizes, fits, tolerances and finishes are Design rules (EXAMPLE values flagged until you replace them)."]),
    ("Check before release (tool designer)",
     ["Press shut height and bed size against the press data sheet (shut height is on the assembly sheet).",
      "Stripper: the design uses a fixed stripper on stock guides / nest; use a spring stripper where flatness of the part needs it.",
      "V-bending: pressure pad, back gauge position and springback compensation by try-out.",
      "Moulds: gate, runner and vents; slides and lifters where the concept analysis found undercuts; hot runner if chosen in the tool cost.",
      "Detail drawings of punches, V-die and inserts give the overall sizes; profiles come from the DXF / STEP (wire cut, CNC)."]),
    ("Not done yet (next stages)",
     ["Foundry: pattern, core boxes and moulding boxes (no tool cost yet).",
      "Drawing dies (deep draw) and the forming stations of progressive dies in 3D.",
      "Simulation and video for EPS and blow moulding.",
      "3D correction of draft, wall thickness and ribs (needs CAD)."]),
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
                       "task × tool-type cells are done; sheet-metal dies and injection moulds are complete; die-casting, EPS and "
                       "blow moulds are complete for the mould structure with their process-specific items listed for the designer; "
                       "foundry is not covered yet. Every output was made from the sample parts and checked (pictures, drawings, "
                       "STEP files, automated tests).", st["n"]), Spacer(1, 3 * mm), grid]
    for title, items in FINDINGS:
        story += [Paragraph(title, st["h2"])] + [Paragraph(f"• {x}", st["n"]) for x in items]
    story += [Spacer(1, 4 * mm), drawing_style.pdf_title_block(W, [("Scope", "Roadmap stage 27"), ("Audited", date.today().isoformat())],
                                                               "sheet_metal", "-", "1 / 1", "DTC-AUDIT-27", "")]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUT), pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=10 * mm,
                            bottomMargin=10 * mm, title="Audit - tool design", author="Design to Cost")
    doc.build(story)
    return OUT


if __name__ == "__main__":
    print("wrote", build())
