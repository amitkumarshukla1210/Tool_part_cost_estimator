"""Builds the user guide (PDF for Help → Documents, Word for editing) with fresh screenshots of the running app.

    python docs/user_guide/build_user_guide.py [--docx-out PATH] [--history PATH]

1. copies the shipped master data to a temporary folder and starts the app there (logins off),
2. adds a small demo through the API: project DEMO, a plastic cover (ABS Colour White) and a sheet-metal bracket
   (GI EDD), RM / tool / part cost, a price change and the one-click recalculation (Cost changes report),
   and - with --history (a country_rate_book_history.json) - the 24-month price history,
3. takes the screenshots with Playwright (Node.js + Chromium),
4. writes frontend/docs/DTC_User_Guide.pdf (served on the Help page) and the same guide as Word (.docx).
The content is in CONTENT below: change the text there and run the script again.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_PDF = ROOT / "frontend" / "docs" / "DTC_User_Guide.pdf"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").exists() else ""

# ---------------------------------------------------------------- content
# blocks: ("p", text) · ("b", [bullets]) · ("n", [numbered steps]) · ("t", [header], [[row], …]) · ("img", name, caption)
# ("note", text) · ("h", sub-heading)
CONTENT = [
    ("About this guide", [
        ("p", "Design to Cost (DTC) works out the should-cost of a part from its 3D model: raw material (RM), the tool or mould and its "
              "CAPEX, the part cost per piece, and the same in other countries with the landed cost in India. Every number can be clicked "
              "to see how it was made. Nothing is hard-coded: rates, rules and formulas are master data that you can change."),
        ("p", "This guide explains every page and the monthly routine. For a step-by-step worked example (L bracket, correction, Rev B, "
              "plastic cover with its mould) see the Work instruction on the Help page."),
        ("t", ["Flow of a part", "Where"], [
            ["1. Import the 3D model (STEP), choose main and sub material", "Import"],
            ["2. RM cost: gross weight × approved material rate − scrap credit", "Parts → part panel → RM cost"],
            ["3. Tool / mould cost, tool design, drawings, simulation", "Parts → part panel → Tool cost, Tool design"],
            ["4. Part cost per piece: RM + process + rejection + overhead + profit + packing + tool amortisation + logistics",
             "Parts → part panel → Part cost"],
            ["5. Project totals, BOM cost, CAPEX, cost changes", "Dashboard"],
        ]),
        ("note", "All amounts are shown INR first. Values marked EXAMPLE (orange) are placeholders shipped with the tool: replace them "
                 "with your own (Master data → Replace example values)."),
    ]),
    ("Install, start, update and back up (Windows)", [
        ("p", "The app runs on your PC at http://127.0.0.1:8100. The kit files live in the base folder, e.g. D:\\Project\\DTC Tool and mould:"),
        ("t", ["Double-click", "What it does"], [
            ["DTC_Start.bat", "Starts the app (a backup first if the last one is older than a day). Keep the black window open; close it to stop."],
            ["DTC_Update.bat", "Backup → new version from GitHub (1) or a ZIP (2) → libraries → your master data merged with the new rows → report."],
            ["DTC_Backup.bat", "Backup now into DTC_Backups (and the copy folder of dtc_settings.ini)."],
            ["DTC_Restore.bat", "Puts a backup back: everything, only projects + CAD files, or only master data."],
            ["DTC_Rollback.bat", "Back to the version before the last update, with the data of that moment."],
            ["DTC_ResetPassword.bat", "New password for a login ID (e.g. a forgotten admin password); only at this PC."],
            ["DTC_Country_Rates.bat", "Monthly rate update + country rate book (one Excel per country) into DTC_Data\\country_rates."],
            ["DTC_Install_FEA.bat", "Installs Gmsh for the strength check (FEA); CalculiX ccx.exe goes into DTC_Data\\tools\\calculix."],
        ]),
        ("h", "Where your data is"),
        ("b", ["DTC_Data\\master_data: rates, machines, formulas (costing_db.sqlite, master_data.xlsx).",
               "DTC_Data\\data: projects, parts and every cost version (projects.sqlite); DTC_Data\\storage: CAD files.",
               "An update never overwrites your data: new rows are added, rows you changed stay yours, rate versions are never changed.",
               "Set backup_copy_to in dtc_settings.ini to a OneDrive or network folder so every backup also leaves the PC."]),
        ("h", "Every update"),
        ("n", ["Close the app (its black window) and any open DTC Excel file.",
               "Double-click DTC_Update.bat, choose 1 (download from GitHub), wait for UPDATE DONE.",
               "Double-click DTC_Start.bat. Check one known part against its last cost."]),
    ]),
    ("Logins, roles and tool groups", [
        ("p", "Everybody logs in with an own ID; every change, approval and backup is recorded under it. The first start asks for the "
              "admin ID. Roles: viewer < engineer < approver < head < admin."),
        ("t", ["Role", "May"], [
            ["viewer", "read everything"],
            ["engineer", "projects, parts, costs, imports, master data, rate drafts"],
            ["approver", "+ approve rates, see the activity log, delete parts"],
            ["head", "sees and changes the data of every tool group and user (no user management)"],
            ["admin", "+ login IDs, permissions, backups, app updates, AI assistant, monthly rates"],
        ]),
        ("b", ["Admin → Users, roles & permissions: per-user Allow / Deny on top of the role, and tool groups (Plastic moulding, Die "
               "casting, Foundry, Sheet metal, EPS, Blow moulding, Machining). A user with groups sees only those parts.",
               "The permission Open traces (admin by default) lets a user click a value to see its full calculation."]),
    ]),
    ("Dashboard: the project", [
        ("img", "dashboard", "Dashboard: project tiles, variants, BOM cost and the recalculation buttons."),
        ("b", ["+ New project (code, name, customer, CAPEX budget, SOP date) and + Variant (target BOM cost, annual volume).",
               "Tiles: parts, files missing, open corrections, BOM cost against target, tool CAPEX against budget.",
               "Project leader view: BOM cost per variant, CAPEX plan with milestones, parts by status / process / sourcing.",
               "Export PDF (project summary) and Excel (part register); totals per tool group for limited users."]),
        ("h", "Recalculate"),
        ("t", ["Button", "What it does"], [
            ["Recalculate part costs (RM + tool + part)", "One click: RM cost, tool cost and part cost of every part with the latest approved "
             "rates. Only parts whose cost changed get a new version."],
            ["Recalculate RM / Recalculate tools", "Only that step, for every part."],
        ]),
        ("note", "Stored costs never change by themselves: a new price only reaches a part when you recalculate. Old versions are kept."),
    ]),
    ("Cost changes report", [
        ("img", "cost_changes", "Cost changes: part cost now against the cost valid on a date, with the cost lines that moved."),
        ("b", ["Pick a date (default: 30 days back, Parameters → cost_change_lookback_days) and press Show changes.",
               "Per part: cost on that date (version, date), cost now, change in ₹/part and %, status (changed, new since the date, "
               "unchanged, no part cost yet).",
               "⚑ marks a change of ±5 % or more (Parameters → cost_change_flag_pct); flagged parts come first.",
               "Why: the cost lines then / now / change (net RM, process, rejection, overhead, profit, packing, tool amortisation, logistics). "
               "They always add up to the part cost.",
               "Excel and PDF download the same report for the chosen date."]),
        ("note", "Typical use: after a price change in the Price master, click Recalculate part costs, then Show changes, and send the PDF."),
    ]),
    ("Import: bring in parts", [
        ("img", "import", "Import: a STEP file or an assembly; the tree shows every part with its thumbnail and quantity."),
        ("b", ["3D file (STEP): a part or an assembly. An assembly is split into its parts; identical parts become one part with a "
               "quantity; look-alikes are flagged for you to decide.",
               "For each part: code (blank = generated), name, main material → sub material (grade), process and sourcing "
               "(Make / Bought-out / Existing / Not required).",
               "The process is suggested with its reason (why?): material family first, then the geometry, then moulded-in inserts.",
               "Excel bulk upload: download the template, one row per part, upload with the STEP files or a ZIP. Nothing is saved if any row is wrong.",
               "Scanned drawings and DWG are read on the Estimate page."]),
    ]),
    ("Parts: the register and the part panel", [
        ("img", "parts", "Parts: search, filters (▾ in each column header), costs per part."),
        ("p", "Click a part to open its panel. The panel holds everything about the part, top to bottom:"),
        ("img", "part_top", "Part panel: details with main material → sub material (with its code), process, volume, country."),
        ("t", ["Block", "What you see and do"], [
            ["Details", "Name, main / sub material, process, sourcing, volume, programme life, tool life, producing country, Also cost in. Every change goes into the history."],
            ["Geometry", "Volume, net weight, projected area, size, wall, bends (click for the trace). Part drawing PDF / DXF."],
            ["Design loop", "Status flow (Uploaded → Concept tool → Simulation → … → Tool design frozen), comments, revisions, compare two revisions."],
            ["RM cost", "Gross weight, yield, rate, scrap credit, net RM cost per country; type over any input; Excel / PDF cost sheet."],
            ["Tool cost", "Cavities, mould base or die set, BOM, process hours × MHR, design, trial, overhead, profit; per die stage for sheet metal; progressive vs stage dies."],
            ["Tool design", "3D design, drawing set (one page per drawing), 3D viewer, STEP / STL, release ZIP, toolmaker review, strength check (FEA)."],
            ["Simulation", "Wall thickness, draft, undercuts, flow simulation (fill, pressure, cooling, weld lines, air traps), report PDF and video."],
            ["Part cost", "RM + process + rejection + overhead + profit + packing + tool amortisation + logistics, for every country; versions; Excel / PDF."],
            ["Country comparison", "The part and its tool made in each country, ex-works and landed cost in India (freight, insurance, duty, SWS, IGST)."],
            ["Saved files", "Every download is kept with a revision; an old one is served again until something it depends on changes."],
        ]),
        ("img", "part_cost", "Part cost of a part: each line can be clicked for its trace, down to the electricity rate in the MHR."),
        ("h", "Correct any value"),
        ("b", ["Click a value → the traceability panel shows the formula, every input and its source (rate version, month, approval).",
               "Change an input there (typed value) and save: a new version is made; the old one stays.",
               "A blocking toolmaker-review point stops Tool design frozen until it is solved or waived."]),
    ]),
    ("Master data", [
        ("img", "master_data", "Master data → General master data → Materials: unique code, main material (material type), sub material (grade) and the live price."),
        ("p", "Every value the estimator uses lives here. Change it on the page and click Save, or download the Excel file, change it, upload it."),
        ("t", ["Card", "What is in it"], [
            ["General master data", "Parameters of each part type, Materials (main material, grade, density, scrap reuse %)."],
            ["Mould & die database", "Mould bases, tool steels, BOM rules, design rules, sheet-metal and strip rules, flow materials, process windows, mould systems, review checklist."],
            ["Countries, machines & formulas", "Countries and currencies, machines, labour grades, every MHR / labour / RM / tool / part-cost formula and its inputs."],
            ["Part register setup", "Processes and their rules, part statuses, sourcing types, insert materials and shapes, part-code pattern, register settings."],
            ["Price master", "Month-wise prices per country: tool steels, part raw materials, scrap value."],
            ["Replace example values", "Checklist of every EXAMPLE rate and row still left, by category."],
        ]),
        ("h", "Unique codes and live prices"),
        ("b", ["Every row has a code that never changes or is reused: part materials by family (RM-STL carbon / alloy steel, RM-SHT sheet, "
               "RM-SS stainless, RM-ALC / RM-ALW aluminium cast / wrought, RM-ZN zinc, RM-CU copper / brass, RM-CI cast iron, RM-PLC / RM-PLE "
               "plastics), TS tool steels, MC machines, PR / PU process rates, others by table initials (e.g. DR design rules).",
               "Materials, tool steels, machines and process rates show a live Price column for the country and month you pick above the "
               "table. Prices are never copied: change one in the Price master and every page shows it at once. edit opens the Price master on that code.",
               "Main material → sub material: the material type is the main material (e.g. ABS) and the grade the sub material "
               "(e.g. ABS Colour White · RM-PLE-015). New grades start with the price of their main grade, marked EXAMPLE."]),
    ]),
    ("Price master", [
        ("img", "price_master", "Price master: part raw materials of India, 24 months; Code · main material, sub material."),
        ("b", ["Pick the group (tool materials, part raw materials, scrap value), the country and the months.",
               "A cell shows the approved price costing uses that month: yellow = a version starts there, grey = carried over.",
               "Type a price under a month: a new version from that month on (a draft; approvers can tick Save & approve).",
               "Excel: download the grid, change prices, upload: only changed cells become new versions.",
               "Months before your first price are filled from the market (24-month history, see Monthly rates); they say "
               "INDICATIVE and EXAMPLE. A month you enter yourself is never overwritten."]),
    ]),
    ("Rates", [
        ("img", "rates", "Rates: machine hour rates and labour rates of a country and month, with their traces."),
        ("b", ["Pick the producing country and costing month.",
               "Machine & labour rates: MHR of every machine and labour rate per skill level, in local currency and INR. Click a number for its trace.",
               "Rate library: every approved rate; new version (draft or Save & approve), Excel export with history, Excel import as drafts.",
               "Rate review: drafts next to the approved value, % change (highlighted above 5 %), approve / review / reject one by one or in bulk."]),
        ("t", ["Formula", ""], [
            ["MHR", "depreciation + interest + power + maintenance + floor space + consumables + overhead, per hour"],
            ["Labour rate", "monthly salary × 12 × (1 + employer %) ÷ (days × hours) × (1 + supervision %) ÷ productive %"],
        ]),
        ("note", "Costing uses only the latest APPROVED version up to the costing month. Approved versions are never changed or deleted."),
    ]),
    ("Monthly rates: automatic every month", [
        ("img", "admin_rates", "Admin → Monthly rates: last run, Update rates now, and the log."),
        ("p", "When the app starts in a new month it downloads the free official sources and writes new APPROVED rates for every country "
              "(user Auto monthly update). Admin → Monthly rates → Update rates now, or DTC_Country_Rates.bat, does the same at any time."),
        ("t", ["Rate", "How it is updated", "Source"], [
            ["Forex", "market monthly average", "FRED (Federal Reserve), World Bank for VND"],
            ["RM grades, tool steels, scrap values", "last rate × the grade's market index × forex change", "LME / IMF metals, US steel and resin price indices"],
            ["Electricity", "Germany: Eurostat; others: power price index", "Eurostat nrg_pc_205, US PPI"],
            ["Salaries", "× ILO yearly wage change when a new year is published", "ILOSTAT"],
            ["Machine hour and labour rates", "follow by formula", "—"],
        ]),
        ("b", ["You stay in charge: change any value on the Rates page or the Price master. A month that already has a value is never "
               "written again, and the next month starts from your value.",
               "24-month history: every run also fills the months still empty in the last 24 (forex and Germany power from the market; "
               "grades, salaries and other rates INDICATIVE by their index, others flat). They are marked EXAMPLE.",
               "Results built on EXAMPLE rates stay EXAMPLE until you replace the base value."]),
    ]),
    ("Country rate book (Excel per country)", [
        ("p", "DTC_Country_Rates.bat (or the monthly update) writes one workbook per country into DTC_Data\\country_rates, 24 months:"),
        ("t", ["Sheet", "What is in it"], [
            ["Summary", "Latest value, change over 12 months and since the first month, data gaps, EXAMPLE count."],
            ["RM_Price", "A: world metal prices in USD, INR/kg and local currency/kg; B: every grade of the tool by family; B2 / B3: indicative 24-month grade trend; C: more grades for your quotes."],
            ["Labour", "ILO hourly wage by skill level and manufacturing monthly wage; the tool's labour rates."],
            ["Process_Cost", "Machine hour rate of every machine, process rates, cost drivers."],
            ["Electricity", "The tool's power rate, Eurostat (EU), official tariff publisher, entry rows."],
            ["Transport", "Freight rates, Brent, diesel, freight indices, entry rows for your quotes."],
            ["Forex", "INR per USD and per local currency; check against the tool's forex."],
            ["Sources", "Publisher and link of every series, refresh log."],
        ]),
        ("b", ["Green = downloaded market data, blue = approved rate of the tool, orange = EXAMPLE, yellow = your entry, lilac = indicative.",
               "ILOSTAT refuses automatic downloads: download its two CSV files in the browser and run DTC_Country_Rates.bat --ilo-file "
               "\"C:\\Users\\<you>\\Downloads\" once a year.",
               "Close the workbooks in Excel before a refresh; an open one is skipped (NOT written, close it and run again)."]),
    ]),
    ("Estimate, Harness & PCB", [
        ("img", "estimate", "Estimate (start page): a quick RM, tool and part cost from a 3D file or a few inputs, without registering the part."),
        ("b", ["Estimate: upload a STEP (or a scanned drawing / DWG), choose material, process and country: Stage A (geometry, weight), "
               "Stage B (RM cost), Stage C (cavities, tools). Open in Estimate from a part loads its inputs; Save to part stores them.",
               "Harness & PCB: reads a harness or PCB BOM (Excel), groups wires, terminals, connectors and components, and costs them with "
               "the rate library (consumables, conversion, bare board)."]),
        ("img", "harness", "Harness & PCB: read a harness or PCB BOM and cost it with the rate library."),
    ]),
    ("Admin", [
        ("t", ["Tab", "What it does"], [
            ["Users, roles & permissions", "Login IDs, roles, per-user Allow / Deny, tool groups, block / unblock, new password (admin only)."],
            ["My password", "Change your own password."],
            ["Activity log", "Who changed what and when; filters; Excel export."],
            ["Backups & update", "Installed version, Backup now, download a backup, update reports, Update app."],
            ["Drawings (logo)", "Logo, company and title-block data on every drawing, Excel and PDF."],
            ["AI assistant", "Ask AI on every page (read only, with the user's own permissions); needs an Anthropic API key."],
            ["Monthly rates", "Last automatic update, Update rates now, the log of each run."],
        ]),
    ]),
    ("Monthly routine (checklist)", [
        ("n", ["Start the app in the new month: the rates of the month and any missing history are written by themselves "
               "(Admin → Monthly rates shows the result).",
               "Enter real supplier prices in the Price master where you have them (they replace the indicative / EXAMPLE values).",
               "Rates → Rate review: approve open drafts.",
               "Dashboard → Recalculate part costs (RM + tool + part) for each active project.",
               "Dashboard → Cost changes → Show changes; download the PDF for your team.",
               "Optional: DTC_Country_Rates.bat for the country workbooks; DTC_Backup.bat before big changes."]),
    ]),
    ("Troubleshooting", [
        ("t", ["What you see", "What to do"], [
            ["Permission denied …Country_Rates_….xlsx", "The workbook is open in Excel: close it and run again."],
            ["NO market index data downloaded yet", "The PC could not reach the sources (FRED, Eurostat, World Bank): check internet / proxy, then Update rates now."],
            ["FAILED ILOSTAT … 403", "Normal: ILOSTAT refuses automatic downloads; your saved wage data is used. New year: --ilo-file."],
            ["No approved rate '…' for …", "Add or approve that rate on the Rates page (or the Price master) for the country and month."],
            ["Recalculate says unchanged", "No input changed since the last version; check the costing month and the country of the part."],
            ["'No module named backend'", "Use the .bat files in the base folder, never python -m … from another folder."],
            ["Forgot the password", "DTC_ResetPassword.bat at the PC that runs the app."],
            ["Something wrong after an update", "DTC_Rollback.bat puts the previous version and its data back."],
        ]),
    ]),
    ("Words used", [
        ("t", ["Word", "Meaning"], [
            ["RM", "raw material; net RM cost = RM cost − scrap credit"],
            ["MHR", "machine hour rate (₹ per hour of a machine)"],
            ["CAPEX", "tool / mould and machine investment"],
            ["Approved / draft", "only approved rates are used; new prices start as drafts unless approved at once"],
            ["EXAMPLE", "placeholder value shipped with the tool, to be replaced with yours"],
            ["INDICATIVE", "a past month worked out from a market index, not a quote"],
            ["Version", "every stored cost is a numbered version; old versions never change"],
            ["Trace", "the full calculation behind a value: formula, inputs, sources"],
        ]),
    ]),
]

SHOTS = ["dashboard", "cost_changes", "import", "parts", "part_top", "part_cost", "master_data", "price_master", "rates",
         "admin_rates", "estimate", "harness"]


# ---------------------------------------------------------------- the running app
def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http(base, path, data=None, method=None, file=None, timeout=600):
    if file:
        b = uuid.uuid4().hex
        body = (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{file.name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n").encode() + file.read_bytes() + f"\r\n--{b}--\r\n".encode()
        req = urllib.request.Request(base + path, data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}"}, method="POST")
    else:
        req = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json"}, method=method or ("POST" if data is not None else "GET"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def demo(base: str, tmp: Path) -> dict:
    """A small project: plastic cover + sheet-metal bracket, costed, a price change and the one-click recalculation."""
    p = http(base, "/api/projects", {"code": "DEMO", "name": "Demo project", "customer": "Demo customer"})
    try:
        http(base, f"/api/projects/{p['id']}/variants", {"code": "STD", "name": "Standard", "annual_volume": 100000, "target_bom_cost": 60})
    except Exception:  # noqa: BLE001 - the variant is decoration only
        pass
    ids = []
    for f, mat, proc, code in (("plastic_cover.step", "ABS Colour White", "injection_moulding", "DEMO-0001"),
                               ("sheet_metal_bracket.step", "GI EDD (deep drawing, DX53D)", "sheet_metal_multistage", "DEMO-0002")):
        m = http(base, "/api/import/step", file=ROOT / "samples" / f)
        r = http(base, f"/api/import/{m['token']}/commit", {"project_id": p["id"], "items": {
            m["root"]: {"material": mat, "process": proc, "part_code": code}}})
        pid = r["part_ids"][0]
        http(base, f"/api/parts/{pid}/tool-cost", {})
        http(base, f"/api/parts/{pid}/piece-cost", {})
        ids.append(pid)
    con = sqlite3.connect(tmp / "projects.sqlite")
    old = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
    for t in ("piece_costs", "rm_costs", "tool_costs"):
        try:
            con.execute(f"UPDATE {t} SET created_at = ?", (old,))
        except sqlite3.Error:
            pass
    con.commit()
    con.close()
    http(base, "/api/settings", {"approver_name": "Guide"}, method="PUT")
    month = date.today().strftime("%Y-%m")
    grid = http(base, "/api/price-master/grid?group=part_material&country=IN&months=3")
    row = next(r for r in grid["rows"] if r["item"] == "ABS Colour White")
    now = [c for c in row["cells"].values() if c and c.get("value")]
    price = round((now[-1]["value"] if now else 180) * 1.25, 1)
    http(base, "/api/price-master/price", {"group": "part_material", "item": "ABS Colour White", "country": "IN", "month": month,
                                           "value": price, "approve": True})
    http(base, f"/api/projects/{p['id']}/piece-cost/recalculate", {})
    return {"project": p["id"], "parts": ids}


SHOT_JS = r"""
const { chromium } = require('playwright');
(async () => {
  const [base, out, part] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1.5 });
  const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  const go = async (u, wait = 2500) => { await p.goto(base + u); await p.waitForTimeout(wait); };
  const shot = async (name, el) => {
    if (el) { const h = await p.$(el); if (h) { await h.scrollIntoViewIfNeeded(); await p.waitForTimeout(400); await h.screenshot({ path: `${out}/${name}.png` }); return; } }
    await p.screenshot({ path: `${out}/${name}.png` });
  };
  await go('/dashboard', 4000); await shot('dashboard');
  const d = await p.$('#costChanges details'); if (d) await d.evaluate((x) => (x.open = true));
  await p.waitForTimeout(600); await shot('cost_changes', '#costChanges');
  await go('/import'); await shot('import');
  await go('/parts'); await shot('parts');
  await go(`/parts?part=${part}`, 6000); await shot('part_top');
  await p.evaluate(() => document.getElementById('pieceBox')?.scrollIntoView());
  await p.waitForTimeout(1500); await shot('part_cost', '#pieceBox');
  await go('/master-data?set=general&sheet=Materials', 3500); await p.fill('#search', 'ABS'); await p.waitForTimeout(500); await shot('master_data');
  await go('/master-data/prices?group=part_material&country=IN&code=RM-PLE', 3500); await shot('price_master');
  await go('/rates', 4000); await shot('rates');
  await go('/admin?tab=autorates', 3000); await shot('admin_rates');
  await go('/', 3000); await shot('estimate');
  await go('/bom-extract', 3000); await shot('harness');
  console.log(JSON.stringify(errs));
  await b.close();
})();
"""


def screenshots(out: Path, history: Path | None) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="dtc_guide_"))
    shutil.copy(ROOT / "master_data" / "costing_db.sqlite", tmp / "costing_db.sqlite")
    shutil.copy(ROOT / "master_data" / "master_data.xlsx", tmp / "master_data.xlsx")
    env = dict(os.environ, COSTING_DB_PATH=str(tmp / "costing_db.sqlite"), MASTER_DATA_PATH=str(tmp / "master_data.xlsx"),
               DATABASE_URL=f"sqlite:///{tmp / 'projects.sqlite'}", DTC_STORAGE_FOLDER=str(tmp / "storage"), DTC_MODE="local",
               DTC_DATA_FOLDER=str(tmp))
    if history and history.exists():                    # the 24-month history, so the Price master shows filled months
        (tmp / "country_rates").mkdir()
        shutil.copy(history, tmp / "country_rates" / "country_rate_book_history.json")
        subprocess.run([sys.executable, "-c", "from pathlib import Path; from backend.app import auto_rates, country_rate_book as c, "
                        "price_history as h; h.backfill(c.load_history(Path(r'%s'))); auto_rates.set_state('history_done', '1'); "
                        "auto_rates.set_state('last_month', __import__('backend.app.rates', fromlist=['x']).current_month()); "
                        "auto_rates.set_state('last_run', __import__('datetime').datetime.now().isoformat(timespec='seconds')); "
                        "auto_rates.set_state('last_message', 'Example for this guide: 24-month history filled'); "
                        "__import__('backend.app.rate_update', fromlist=['x'])._log('Auto monthly update', 'ok', "
                        "'Example for this guide: 24-month history filled', 0, 'guide')" % (tmp / "country_rates")],
                       cwd=ROOT, env=env, check=True)
    port = free_port()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                http(base, "/api/projects", timeout=5)
                break
            except Exception:  # noqa: BLE001
                time.sleep(1)
        d = demo(base, tmp)
        js = tmp / "shots.js"
        js.write_text(SHOT_JS, encoding="utf-8")
        r = subprocess.run(["node", str(js), base, str(out), str(d["parts"][0])], capture_output=True, text=True, timeout=900)
        if r.returncode:
            raise SystemExit("screenshots failed:\n" + r.stderr[-2000:])
        errs = json.loads(r.stdout.strip().splitlines()[-1] or "[]")
        if errs:
            print("page errors while taking screenshots:", errs)
    finally:
        srv.terminate()
        srv.wait(timeout=30)
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- PDF
def build_pdf(shots: Path, out: Path) -> None:
    from PIL import Image as PImage
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # a font with ₹, ⚑, →, ▾: DejaVu Sans (Linux) or Segoe UI / Arial (Windows); else the built-in Helvetica
    regular = bold = "Helvetica"
    for r, b in (("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                 ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"), ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf")):
        if Path(r).exists() and Path(b).exists():
            pdfmetrics.registerFont(TTFont("GuideSans", r))
            pdfmetrics.registerFont(TTFont("GuideSans-Bold", b))
            regular, bold = "GuideSans", "GuideSans-Bold"
            break
    navy, grey = colors.HexColor("#1F3864"), colors.HexColor("#555555")
    st = {"t": ParagraphStyle("t", fontName=bold, fontSize=26, leading=32, textColor=navy),
          "sub": ParagraphStyle("sub", fontName=regular, fontSize=12, leading=16, textColor=grey),
          "h1": ParagraphStyle("h1", fontName=bold, fontSize=16, leading=20, textColor=navy, spaceBefore=4, spaceAfter=8),
          "h2": ParagraphStyle("h2", fontName=bold, fontSize=11.5, leading=15, textColor=navy, spaceBefore=8, spaceAfter=4),
          "p": ParagraphStyle("p", fontName=regular, fontSize=9.6, leading=13.4, alignment=TA_LEFT, spaceAfter=5),
          "cell": ParagraphStyle("cell", fontName=regular, fontSize=8.6, leading=11),
          "head": ParagraphStyle("head", fontName=bold, fontSize=8.6, leading=11, textColor=colors.white),
          "cap": ParagraphStyle("cap", fontName=regular, fontSize=8.2, leading=10.5, textColor=grey, spaceAfter=8),
          "note": ParagraphStyle("note", fontName=regular, fontSize=9, leading=12.5, textColor=colors.HexColor("#7A4A00"),
                                 backColor=colors.HexColor("#FFF4E0"), borderPadding=6, spaceBefore=4, spaceAfter=8)}
    W = A4[0] - 36 * mm
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731

    def footer(c, d):
        c.saveState()
        c.setFont(regular, 7.5)
        c.setFillColor(grey)
        c.drawString(18 * mm, 10 * mm, f"Design to Cost - User guide {VERSION} · {date.today():%d %b %Y}")
        c.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {d.page}")
        c.restoreState()

    story = [Spacer(1, 50 * mm), Paragraph("Design to Cost", st["t"]), Paragraph("User guide", st["t"]), Spacer(1, 6 * mm),
             Paragraph("Part, raw material, tool and mould cost from the 3D model, by country, with every value traceable.", st["sub"]),
             Spacer(1, 4 * mm), Paragraph(f"Version {VERSION} · {date.today():%d %B %Y} · covers roadmap stages 1-56", st["sub"]),
             Spacer(1, 20 * mm), Paragraph("Contents", st["h2"])]
    story += [Paragraph(f"{i}. {esc(t)}", st["p"]) for i, (t, _) in enumerate(CONTENT, 1)]
    story.append(PageBreak())
    for i, (title, blocks) in enumerate(CONTENT, 1):
        part = [Paragraph(f"{i}. {esc(title)}", st["h1"])]
        for blk in blocks:
            kind = blk[0]
            if kind == "p":
                part.append(Paragraph(esc(blk[1]), st["p"]))
            elif kind == "h":
                part.append(Paragraph(esc(blk[1]), st["h2"]))
            elif kind == "note":
                part.append(Paragraph(esc(blk[1]), st["note"]))
            elif kind in ("b", "n"):
                part.append(ListFlowable([ListItem(Paragraph(esc(x), st["p"]), leftIndent=12) for x in blk[1]],
                                         bulletType="bullet" if kind == "b" else "1", leftIndent=14, bulletFontSize=8))
            elif kind == "t":
                head, rows = blk[1], blk[2]
                n = len(head)
                widths = [W * 0.32, W * 0.68] if n == 2 else [W * 0.24, W * 0.42, W * 0.34]
                data = [[Paragraph(esc(h), st["head"]) for h in head]] + [[Paragraph(esc(c), st["cell"]) for c in r] for r in rows]
                t = Table(data, colWidths=widths, repeatRows=1)
                t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), navy), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                       ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFBFBF")),
                                       ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5FA")]),
                                       ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
                part += [t, Spacer(1, 6)]
            elif kind == "img":
                f = shots / f"{blk[1]}.png"
                if not f.exists():
                    continue
                jpg = shots / f"{blk[1]}.jpg"
                if not jpg.exists():
                    PImage.open(f).convert("RGB").save(jpg, quality=82, optimize=True)
                w, h = PImage.open(jpg).size
                iw = W
                ih = iw * h / w
                if ih > 150 * mm:
                    ih = 150 * mm
                    iw = ih * w / h
                part += [KeepTogether([Image(str(jpg), width=iw, height=ih), Paragraph(esc(blk[2]), st["cap"])])]
        story += part + [Spacer(1, 4 * mm)]
        if i < len(CONTENT):
            story.append(PageBreak())
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title="Design to Cost - User guide", author="Design to Cost")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


# ---------------------------------------------------------------- Word
def build_docx(shots: Path, out: Path) -> None:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Cm(1.8))
    base = doc.styles["Normal"]
    base.font.name, base.font.size = "Arial", Pt(10)
    for name, size in (("Heading 1", 16), ("Heading 2", 12), ("Title", 26)):
        s = doc.styles[name]
        s.font.name, s.font.size, s.font.color.rgb = "Arial", Pt(size), RGBColor(0x1F, 0x38, 0x64)
    doc.add_paragraph("Design to Cost - User guide", style="Title")
    doc.add_paragraph(f"Version {VERSION} · {date.today():%d %B %Y} · covers roadmap stages 1-56")
    doc.add_paragraph("Part, raw material, tool and mould cost from the 3D model, by country, with every value traceable.")
    doc.add_heading("Contents", 2)
    for i, (t, _) in enumerate(CONTENT, 1):
        doc.add_paragraph(f"{i}. {t}")
    for i, (title, blocks) in enumerate(CONTENT, 1):
        doc.add_page_break()
        doc.add_heading(f"{i}. {title}", 1)
        for blk in blocks:
            kind = blk[0]
            if kind == "p":
                doc.add_paragraph(blk[1])
            elif kind == "h":
                doc.add_heading(blk[1], 2)
            elif kind == "note":
                p = doc.add_paragraph()
                r = p.add_run(blk[1])
                r.font.color.rgb = RGBColor(0x7A, 0x4A, 0x00)
                r.italic = True
            elif kind in ("b", "n"):
                for x in blk[1]:
                    doc.add_paragraph(x, style="List Bullet" if kind == "b" else "List Number")
            elif kind == "t":
                head, rows = blk[1], blk[2]
                t = doc.add_table(rows=1, cols=len(head))
                t.style = "Table Grid"
                t.alignment = WD_TABLE_ALIGNMENT.CENTER
                for c, h in zip(t.rows[0].cells, head):
                    c.text = h
                    c.paragraphs[0].runs[0].bold = True
                    c.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    shd = OxmlElement("w:shd")
                    shd.set(qn("w:val"), "clear")
                    shd.set(qn("w:fill"), "1F3864")
                    c._tc.get_or_add_tcPr().append(shd)
                for row in rows:
                    cells = t.add_row().cells
                    for c, v in zip(cells, row):
                        c.text = v
                for r in t.rows:
                    for c in r.cells:
                        for p in c.paragraphs:
                            for run in p.runs:
                                run.font.size = Pt(9)
                doc.add_paragraph()
            elif kind == "img":
                f = shots / f"{blk[1]}.jpg"
                if not f.exists():
                    f = shots / f"{blk[1]}.png"
                if f.exists():
                    doc.add_picture(str(f), width=Cm(17))
                    cap = doc.add_paragraph(blk[2])
                    cap.runs[0].italic = True
                    cap.runs[0].font.size = Pt(8.5)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the user guide (PDF + Word) with fresh screenshots.")
    ap.add_argument("--docx-out", default=str(ROOT / "data" / "DTC_User_Guide.docx"), help="where the Word file goes")
    ap.add_argument("--pdf-out", default=str(OUT_PDF))
    ap.add_argument("--history", help="country_rate_book_history.json: fill the 24-month history for the screenshots")
    ap.add_argument("--shots", help="use the screenshots already in this folder (no app run)")
    a = ap.parse_args(argv)
    shots = Path(a.shots) if a.shots else Path(tempfile.mkdtemp(prefix="dtc_guide_shots_"))
    if not a.shots:
        screenshots(shots, Path(a.history) if a.history else None)
    build_pdf(shots, Path(a.pdf_out))
    build_docx(shots, Path(a.docx_out))
    print(f"Written: {a.pdf_out}\nWritten: {a.docx_out}\nScreenshots: {shots}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
