"""Builds the work instruction PDF with a real worked example (roadmap stage 26).

    python docs/work_instruction/build_work_instruction.py

1. starts the app on an empty copy of the example master data (logins on),
2. runs docs/work_instruction/run_example.js in a browser (Playwright): first admin, project, import of the sample
   L bracket Rev A, the whole design loop with a correction and Rev B, traceability, suppliers, country comparison,
   downloads (part drawing, tool drawings per stage, cost sheets, PO pack), a plastic part with its mould,
3. writes frontend/docs/DTC_Work_Instruction.pdf (served on the Help page) and copies the example outputs and the
   sample STEP files to frontend/docs/example/.
Needs Node.js with Playwright and Chromium, and pdftoppm (poppler) for the drawing thumbnails.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT_PDF = ROOT / "frontend" / "docs" / "DTC_Work_Instruction.pdf"
EXAMPLE = ROOT / "frontend" / "docs" / "example"

# step texts: screenshot name -> (title, what you do, what you get / download)
STEPS = {
    "setup": ("First start: create the admin", ["Start the app with DTC_Start.bat; the browser opens http://127.0.0.1:8000.",
              "With no user yet the app shows “First start”: enter the admin ID, full name and a password (10+ characters).",
              "Keep the password safe. A forgotten password is reset at the PC with DTC_ResetPassword.bat."], "Admin login."),
    "admin_users": ("Create the team's login IDs", ["Admin (menu, top right) → Users & roles → Create a login ID: user ID, name, role, first password.",
                    "Roles: viewer (reads), engineer (changes data), approver (+ approves rates), admin (+ users, permissions, backups).",
                    "Admin → Permissions sets the lowest role for each action."], "One login per person; every change is recorded under it."),
    "project": ("Create the project and its variant", ["Dashboard → + New project: code, name, customer, CAPEX budget, SOP date → Save.",
                "+ Variant: code (e.g. STD), name, target BOM cost, annual volume → Save."], "Project EX26 with variant STD (200,000 parts / year)."),
    "import": ("Import the 3D model (Rev A)", ["Import → 3D file → choose the STEP file → Read file (sample: example_bracket_revA.step).",
               "Choose the material (Galvanised steel GI); the process is suggested with its reason (why?). Give the part code and name.",
               "Register parts. The geometry, net weight, RM cost and tool cost are worked out automatically."], "Part EX26-0001 rev A in the register and in the BOM of STD."),
    "parts": ("Find the part in the register", ["Parts → filter by project, process, status; ▾ in a column header filters any column.",
              "Click a part to open its panel; ⤢ Full screen gives the whole window."], "—"),
    "part_geometry": ("Check the part and download its drawing", ["Check name, material, process, sourcing, volume; Save changes if needed.",
                      "Geometry from the 3D model: volume, net weight, size, thickness, bends.",
                      "Part drawing PDF / DXF: three views, overall dimensions, title block."], "EX26-0001_part_drawing_revA.pdf"),
    "loop_uploaded": ("Design loop: start", ["The Design loop card shows the stages and the simulation result of the current model.",
                      "Move to → Concept tool → Change status (the software proposes the tool concept)."], "Status Concept tool."),
    "dies": ("Stage tools: the dies suggested", ["Tool cost (mould / die): one die per operation (Blanking, Piercing, Bending) or one progressive die.",
             "Each die: die set, die plate L × W × H, press for its force, cost. Click any value for its traceability.",
             "Download per die: tool drawing PDF / DXF and cost PDF / Excel; All dies: one page per stage."],
             "EX26-0001_stage1…3_tool_drawing.pdf / .dxf, …_tool_cost.pdf"),
    "sheet_tools": ("Sheet-metal tools and the blank", ["Operations in order (↑ ↓ ✕, + Add, Reset to suggested), die type, forces, presses.",
                    "Blank developed for the best material yield (L shape → straight strip + bending stage).",
                    "Blank DXF, strip DXF and tool pack PDF under Blank and strip layout."], "EX26-0001_blank.dxf, EX26-0001_tool_pack.pdf"),
    "loop_correction": ("Design loop: simulation and correction", ["Move to → Simulation → Change status.",
                        "Forming simulation: 1 correction required (bend radius 0.5 mm < 1 × thickness).",
                        "Put this result in the Design loop form → Corrections required with the comment → Change status.",
                        "Send the comment to the product designer for a corrected model."], "Status Corrections required, comment in the timeline."),
    "revision": ("Upload the corrected model (Rev B)", ["Part panel → Upload a new revision: STEP file, Rev no. B, what changed → Upload revision.",
                 "Rev A, its files and costs stay; the status moves to Revised by itself and all costs are recalculated."], "Rev B, status Revised."),
    "loop_ok": ("Design loop: simulation OK", ["Move to → Simulation → Change status: No corrections required.",
                "Put this result in the Design loop form → Simulation OK → Change status."], "Status Simulation OK."),
    "loop_frozen": ("Design loop: tool design frozen", ["Move to → Tool design frozen (comment: concept frozen for quotation) → Change status.",
                    "What changed, who, when: every move, revision and comment."], "Status Tool design frozen: ready for RFQ / PO."),
    "trace_base": ("Traceability: die set / mould base", ["Click the die set or mould base price: every base of that type with size, weight, price.",
                   "Use for this part, or + Add a row (saved to master data, then selectable)."], "—"),
    "trace_grade": ("Traceability: steel grade", ["Click a steel rate (e.g. Steel rate · D2): why this grade (Grade rule / learned / your choice).",
                    "Choose another grade (price per kg and % difference shown), tick the lines → Use this grade."], "New tool cost version; the choice is learned for the next parts."),
    "trace_value": ("Traceability: any value", ["Change this value: For this part only (this part's cost) or Save for the future (rate library / master data).",
                    "Reset to master data removes your part-only change. Formulas can be changed the same way."], "—"),
    "suppliers": ("Supplier master", ["Suppliers → + New supplier: code automatic (SUP-0001), status, capability, contacts, certifications, scores."], "suppliers.xlsx (Export Excel)"),
    "quotes": ("Supplier quotes against should-cost", ["Part → Suppliers & quotes: add the supplier, piece price, tool price, quote ref and date.",
               "The gap to our should-cost is shown in INR and %."], "—"),
    "countries": ("Compare countries", ["Country comparison and landed cost: tick the countries (All / None) → Compare the ticked countries.",
                  "Part and tool ex-works and landed in India; cheapest marked; Excel / PDF."], "country_comparison_….xlsx / .pdf"),
    "po_pack": ("Download for RFQ / PO", ["Tool cost → ⬇ PO pack (ZIP): part STEP and drawing, tool drawing and cost per stage, BOM per stage,",
                "blank / strip DXF, tool pack, RM and part cost. Send it with the RFQ; attach it to the PO."], "EX26-0001_PO_pack.zip"),
    "mould": ("A plastic part: the mould", ["Import plastic_cover.step with material ABS: the mould is sized (cavities, base, inserts) and costed.",
              "Mould concept drawing PDF / DXF and the PO pack, the same way."], "EX26-0002_mould_drawing.pdf"),
    "dashboard": ("Project view", ["Dashboard: BOM cost vs target per variant, tool CAPEX vs budget, part status, CAPEX plan with suppliers.",
                  "Recalculate RM / tools / part costs with the latest approved rates."], "Dashboard PDF, parts Excel"),
    "activity": ("Who changed what", ["Admin → Activity log: filter by what / who / dates; Export Excel."], "activity_log.xlsx"),
}

LOOP = [
    ("Uploaded", "Import the STEP (Rev A).", "Geometry, weight, RM, tool and part cost; process suggestion.", "Part drawing PDF / DXF"),
    ("Concept tool", "Check the dies / mould proposed; change grades, base, operations if needed.", "Dies per stage / mould with BOM and cost.",
     "Tool drawing and cost per stage (PDF / DXF / Excel)"),
    ("Simulation", "Move to Simulation; read the result.", "Sheet metal: forming result; plastic / die casting: wall, draft, sink, cycle, clamp.",
     "Simulation PDF (plastic / die casting), tool pack"),
    ("Corrections required", "Put the result in the form → Change status; send the comment to the designer.", "The correction kept in the timeline.", "—"),
    ("Revised", "Upload the corrected model as a new revision.", "All costs recalculated on the new revision.", "Part drawing of the new revision"),
    ("Simulation OK", "Simulation again → Put this result → Simulation OK.", "No corrections required.", "—"),
    ("Tool design frozen", "Move to Tool design frozen.", "Concept frozen for quotation.", "PO pack (ZIP) for RFQ / PO"),
]

CORRECTIONS = [
    ("Part name, material, process, sourcing, volume, programme life", "Parts → part → details form → Save changes", "History keeps old → new"),
    ("Wrong or changed 3D model", "Part → Upload a new revision (old revisions stay)", "Design loop → Revised"),
    ("Part not needed in a project / not needed at all", "Part → Remove from project BOM / Delete part (type the code)", "Backup ZIP made first"),
    ("Project data (budget, SOP, name) / whole project", "Dashboard → Edit project / Delete project", "Delete: type the code, backup first"),
    ("Design-loop status or a forgotten step", "Design loop → Move to → ↩ Back to … with a comment", "Shown as step back"),
    ("Sheet-metal operations or die type", "Sheet-metal tools → Operations in order (↑ ↓ ✕ + Add, Reset) / Die type → Save", "Dies follow"),
    ("Blank size, thickness, sheet size, gap", "RM inputs on the part, or traceability → For this part only", "Or Save for the future"),
    ("Cavities, hot runner, slides, lifters, tool country", "Tool cost → Tool features and tool country → Save and calculate", "—"),
    ("Steel grade of a BOM line or of the base", "Traceability on the steel → grade drop-down → Use this grade", "Learned for the next parts"),
    ("Grade / make for every new tool", "Tool BOM table → my default, or Master data → Grade rules / BOM elements", "Master data"),
    ("Mould base / die set", "Traceability on the base price → Use for this part / + Add a row", "Add row = master data"),
    ("Standard part, make, quantity or price of a BOM line", "Tool BOM table (optional) → change → Save; + New standard part", "Part number kept"),
    ("New steel grade", "Tool BOM table → + New grade (price per kg, country, make)", "Rate approved or draft"),
    ("Any rate (material, scrap, steel, process, MHR input, labour, overhead %)", "Traceability → For this part only / Save for the future; Rates page", "New rate version"),
    ("A rule or formula (BOM rule, cost formula)", "Traceability on the formula → change → For this part only / Save for the future", "Master data"),
    ("Machines, countries, labour grades", "Master data → Countries, machines & formulas", "Approved rates on Rates"),
    ("Supplier data or a quote", "Suppliers page / Part → Suppliers & quotes", "History kept"),
    ("Users, roles, permissions", "Admin → Users & roles / Permissions", "Admin only"),
    ("A stored cost looks old", "Part → Recalculate, or Dashboard → Recalculate RM / tools / part costs", "Old versions are never changed"),
    ("Something wrong after an update", "DTC_Rollback.bat (old version and data); DTC_Restore.bat (a backup)", "Backups in DTC_Backups"),
]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_example(work: Path) -> dict:
    data = work / "data"
    (data / "master_data").mkdir(parents=True)
    for f in ("costing_db.sqlite", "master_data.xlsx"):
        shutil.copy(ROOT / "master_data" / f, data / "master_data" / f)
    port = free_port()
    env = dict(os.environ, COSTING_DB_PATH=str(data / "master_data" / "costing_db.sqlite"),
               MASTER_DATA_PATH=str(data / "master_data" / "master_data.xlsx"),
               DATABASE_URL="sqlite:///" + (data / "projects.sqlite").as_posix(), DTC_STORAGE_FOLDER=str(data / "storage"),
               DTC_BACKUP_FOLDER=str(data / "backups"), DTC_MODE="server")
    env.pop("DTC_ADMIN_PASSWORD", None)
    app = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", port), 0.5).close()
                break
            except OSError:
                time.sleep(0.5)
        subprocess.run(["node", str(HERE / "run_example.js"), f"http://127.0.0.1:{port}", str(work / "out"), str(ROOT)],
                       cwd=ROOT, check=True)
    finally:
        app.terminate()
        app.wait(10)
    return json.loads((work / "out" / "shots.json").read_text())


def thumbnail(pdf: Path, work: Path) -> Path | None:
    stem = work / f"thumb_{pdf.stem}"
    try:
        subprocess.run(["pdftoppm", "-r", "55", "-f", "1", "-l", "1", "-jpeg", str(pdf), str(stem)], check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    found = sorted(work.glob(f"thumb_{pdf.stem}*.jpg"))
    return found[0] if found else None


def shrink(src: Path, dst: Path, width: int = 1150) -> Path:
    try:
        from PIL import Image as PImage
        im = PImage.open(src)
        if im.width > width:
            im = im.resize((width, int(im.height * width / im.width)))
        im.convert("RGB").save(dst, "JPEG", quality=66, optimize=True)
        return dst
    except Exception:
        return src


def build_pdf(work: Path, run: dict) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    sys.path.insert(0, str(ROOT))
    from backend.app.pdf_report import _table, _theme
    theme = _theme()
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=22, alignment=0, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=13, spaceBefore=10, spaceAfter=4)
    h3 = ParagraphStyle("h3", parent=ss["Heading3"], textColor=theme["brand"], fontSize=11, spaceBefore=6, spaceAfter=3)
    body = ParagraphStyle("b", parent=ss["Normal"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=ss["Normal"], fontSize=8, leading=10, textColor=theme["grey"])
    cell = ParagraphStyle("c", parent=ss["Normal"], fontSize=8, leading=10)
    P = lambda t, st=body: Paragraph(t, st)
    W = 182 * mm
    shots_dir = work / "out" / "shots"
    outputs = work / "out" / "outputs"

    story = [Spacer(1, 30 * mm), P("DESIGN TO COST · PART COST ESTIMATOR", h3),
             P("Work instruction<br/>with a worked example", h1),
             P(f"From the 3D model to the tool drawings and the PO pack: the complete design loop, step by step. Version {date.today().isoformat()}.", body),
             Spacer(1, 8 * mm), P("<b>Example:</b> L mounting bracket EX26-0001, 2 mm galvanised steel, 40 mm wide, legs 250 and 80 mm, "
                                  "6 holes. Rev A has a 0.5 mm bend radius (the simulation asks for a correction), Rev B has 2 mm. "
                                  "Also a plastic cover EX26-0002 with its mould.", body),
             Spacer(1, 4 * mm), P("<b>Sample files</b> (Help page → Work instruction): example_bracket_revA.step, example_bracket_revB.step, "
                                  "plastic_cover.step, and every output of this example.", body),
             Spacer(1, 10 * mm), P("Contents", h2)]
    contents = ["1 · Start: install, first login, users", "2 · The worked example, step by step", "3 · The design loop at a glance",
                "4 · Downloads for RFQ and purchase order", "5 · Corrections: what to change where (every category)",
                "6 · The example outputs (drawings and cost sheets)", "7 · Updates, backups and help"]
    story += [P(c) for c in contents] + [PageBreak()]

    story += [P("1 · Start", h2),
              P("<b>Install / update</b> (Windows): the update kit in the base folder (e.g. D:\\DTC). <b>DTC_Update.bat</b> makes a backup, "
                "installs the new version and merges your master data; <b>DTC_Start.bat</b> starts the app and opens the browser. "
                "<b>DTC_Backup.bat</b>, <b>DTC_Restore.bat</b>, <b>DTC_Rollback.bat</b>, <b>DTC_ResetPassword.bat</b> do what their names say."),
              P("<b>Menu:</b> Dashboard (projects) · Parts (register, part panel) · Suppliers · Import (STEP / Excel) · Harness &amp; PCB · "
                "Estimate (quick costing of a STEP without registering) · Rates (approved rates by country, review) · Master data "
                "(rules, machines, steels, bases, formulas) · Help · Admin (users, permissions, activity, backups)."),
              P("<b>Rules of the software:</b> no number is hard-coded (everything comes from master data or the rate library); every value "
                "can be clicked to see how it is made; only approved rates are used; stored cost versions never change by themselves; "
                "EXAMPLE values are flagged in red until you replace them.", body), Spacer(1, 3 * mm)]

    story += [P("2 · The worked example, step by step", h2)]
    for n, s in enumerate(run["shots"], start=1):
        key = s["file"].split("_", 1)[1].rsplit(".", 1)[0]
        title, do, out = STEPS.get(key, (s["caption"], [], "—"))
        img = shrink(shots_dir / s["file"], work / f"small_{s['file']}")
        block = [P(f"Step {n} · {title}", h3)] + [P(f"• {t}", body) for t in do]
        if out and out != "—":
            block.append(P(f"<b>Output:</b> {out}", small))
        block += [Spacer(1, 2 * mm), Image(str(img), W, W * 900 / 1440), P(s["caption"], small), Spacer(1, 3 * mm)]
        story.append(KeepTogether(block))

    story += [PageBreak(), P("3 · The design loop at a glance", h2),
              _table([["Stage", "What you do", "What the software gives", "Download"]] +
                     [[Paragraph(a, cell), Paragraph(b, cell), Paragraph(c, cell), Paragraph(d, cell)] for a, b, c, d in LOOP],
                     theme, [30 * mm, 55 * mm, 55 * mm, 42 * mm]),
              P("A step back (e.g. a forgotten Concept tool) is allowed with a comment: Move to → ↩ Back to …", small)]

    story += [P("4 · Downloads for RFQ and purchase order", h2),
              P("Tool cost → <b>⬇ PO pack (ZIP)</b> holds everything the toolmaker needs; send it with the RFQ and attach it to the PO:"),
              _table([["Folder / file", "Content"],
                      ["README.txt", "What is in the pack, and anything that could not be made"],
                      ["01_part / …step", "The 3D model of the current revision (the master for all geometry)"],
                      ["01_part / …part_drawing.pdf / .dxf", "Three views, overall dimensions, title block"],
                      ["02_tool / stageN_…_drawing.pdf / .dxf", "Concept drawing of each die stage (or the mould): plan, plate stack, main BOM"],
                      ["02_tool / stageN_…_cost.pdf, …_bom.xlsx", "Cost sheet and BOM (grade, make, part numbers) of each stage"],
                      ["02_tool / …tool_cost_all.pdf / .xlsx", "All stages: summary and one page / sheet per stage"],
                      ["02_tool / …blank.dxf, strip.dxf, tool_pack.pdf", "Blank, strip layout and stage sketches (sheet metal)"],
                      ["03_cost / …rm_cost.pdf, part_cost.pdf", "Should-cost of material and of the part"]], theme, [70 * mm, 112 * mm]),
              P("The drawings are CONCEPT layouts for quotation and PO reference; the 3D model is the master. Replace EXAMPLE rates and "
                "master-data values before using costs for negotiation.", small)]

    story += [PageBreak(), P("5 · Corrections: what to change where", h2),
              P("Nothing is lost when you correct: old revisions, cost versions and history stay; deletes make a backup first."),
              _table([["What is wrong", "Where to correct it", "Note"]] +
                     [[Paragraph(a, cell), Paragraph(b, cell), Paragraph(c, cell)] for a, b, c in CORRECTIONS],
                     theme, [62 * mm, 88 * mm, 32 * mm])]

    story += [PageBreak(), P("6 · The example outputs", h2)]
    thumbs = []
    for name, label in (("EX26-0001_part_drawing_revB.pdf", "Part drawing (Rev B)"),
                        ("EX26-0001_stage1_blank_tool_drawing.pdf", "Stage 1 · blanking die drawing"),
                        ("EX26-0001_stage2_pierce_tool_drawing.pdf", "Stage 2 · piercing die drawing"),
                        ("EX26-0001_stage3_bend_tool_drawing.pdf", "Stage 3 · bending die drawing"),
                        ("EX26-0001_tool_cost_all_stages.pdf", "Tool cost, all stages"),
                        ("EX26-0002_mould_drawing.pdf", "Mould concept drawing (plastic cover)")):
        f = outputs / name
        t = thumbnail(f, work) if f.exists() else None
        if t:
            thumbs.append([Image(str(t), 88 * mm, 88 * mm * 0.707), Paragraph(f"<b>{label}</b><br/>{name}", cell)])
    rows = []
    for i in range(0, len(thumbs), 2):
        pair = thumbs[i:i + 2]
        rows.append([pair[0][0], pair[1][0] if len(pair) > 1 else ""])
        rows.append([pair[0][1], pair[1][1] if len(pair) > 1 else ""])
    if rows:
        t = Table(rows, colWidths=[91 * mm, 91 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(t)
    story += [P("All files of this example: Help page → Work instruction → example outputs.", small)]

    story += [P("7 · Updates, backups and help", h2),
              P("• Before an update nothing is needed: DTC_Update.bat backs up first. Check one known part after the update."),
              P("• Backups: DTC_Backups (copy them to OneDrive / a pen drive: backup_copy_to in dtc_settings.ini); Admin → Backups."),
              P("• Something wrong after an update: DTC_Rollback.bat. Lost data: DTC_Restore.bat."),
              P("• Help page: how every calculation works; README in the app folder: every feature in detail.")]

    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(theme["grey"])
        canvas.drawString(14 * mm, 8 * mm, "Design to Cost · Work instruction")
        canvas.drawRightString(196 * mm, 8 * mm, f"page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(OUT_PDF), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
                            title="Design to Cost — Work instruction", author="Design to Cost")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def copy_example(work: Path) -> None:
    if EXAMPLE.exists():
        shutil.rmtree(EXAMPLE)
    EXAMPLE.mkdir(parents=True)
    for f in (work / "out" / "outputs").iterdir():
        if not f.name.startswith("_") and f.suffix in (".pdf", ".dxf", ".zip"):
            shutil.copy(f, EXAMPLE / f.name)
    for f in ("example_bracket_revA.step", "example_bracket_revB.step", "plastic_cover.step"):
        shutil.copy(ROOT / "samples" / f, EXAMPLE / f)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        run = run_example(work)
        if run["errors"]:
            print("page errors:", run["errors"])
        build_pdf(work, run)
        copy_example(work)
    print("wrote", OUT_PDF, f"({OUT_PDF.stat().st_size / 1e6:.1f} MB) and", EXAMPLE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
