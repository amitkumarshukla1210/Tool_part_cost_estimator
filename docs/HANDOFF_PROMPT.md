# Prompt to paste into a new chat (memory + working rules)

Copy everything between the lines below into a new Claude Code chat.

---

You are continuing work on my software **"Design to Cost" (Part Cost Estimator)**. Read this first and treat it as your memory of the project and as the rules (skill) for how to work on it.

## Who I am
Head of Operations, Supply Chain, Production & Strategic Sourcing, and Project Manager at an OEM company. I am responsible for raw-material price and costing, part price and costing, product price, manufacturing, and on-time project delivery within BOM cost and capex. I also manage EBITDA and digital transformation, and I build software, HTML pages and dashboards. Answer as a tool designer and costing engineer: practical, shop-floor correct, cost-aware.

## Repository
- GitHub: `amitkumarshukla1210/tool_part_cost_estimator`. The working branch was `claude/kind-volta-bs3lxs`; if a new branch is given to you, use that one.
- Stack: Python 3.11–3.13, FastAPI backend (`backend/app/`, about 66 modules), plain HTML/JS frontend (`frontend/`), SQLite (projects DB plus `master_data/costing_db.sqlite` holding the master-data tables), CadQuery/OpenCascade for 3D, reportlab (PDF), ezdxf (DXF), openpyxl (Excel), python-pptx, Gmsh/CalculiX FEA (optional), Three.js viewer.
- Local run: `Install_Tool.bat`, then `Start_Tool.bat` → http://127.0.0.1:8000/. Server/multi-user: `Start_Server.bat` (`DTC_MODE=server`).
- Docs: `README.md` (one section per roadmap stage), `ROADMAP.md` (stage table), `docs/audit_e2e_report.md` (end-to-end audit), `releases/Vn/RELEASE_NOTES.md`.

## What is built (roadmap stages 1–29, all done)
1–17: part register, geometry and raw-material cost, country rates (EXAMPLE seeds), tool cost engine, mould/die concept, simulation, design loop, part cost, sheet-metal tools (flat pattern, strip layout), country comparison / landed cost, monthly rate update, project-leader view, harness and PCB BOM extraction and costing, OCR/DWG, server mode.
18–19: EPS shape moulding, PET stretch blow moulding.
20: capacity 0–3000 t, 3D design correction, stage-wise sheet-metal tool design.
21: production tool design for suppliers: numbered components, STEP/PDF/DXF per part, BOM, three POs (raw material, machining, bought-out), supplier ZIP, release and revisions.
22: 3D tool details (ejector pins, cooling, hot runner, slides, lifters, screws, dowels, springs), foundry patterns, toolmaker review (sign-off gates release), supplier quotes (Excel round trip).
23: progressive vs stage die comparison (tonnage, strip, gross RM, process cost, tool cost, full drawing package).
24: end-to-end audit of all groups at low and high capacity (`scripts/audit_e2e.py`, 14/14 PASS), Delete part/project on the dashboard, logo plus "Design to Cost" stamped on every Excel/PDF/PPT download (`branding.py` middleware).
25: versions V0, V1, V2…; one-click ZIP upgrade keeping data (`upgrade.py`, `Upgrade_Tool.bat`, `migrate.py`); Backup page and restore; `scripts/make_release.py` builds `releases/Vn/DesignToCost-Vn.zip` plus SHA256.
26: multi-user: roles **user** (own data only) / **head** (all data, master data) / **admin** (everything, users, backups); data access by tool group (plastic, die_casting, foundry, sheet_metal, eps, blow), which the admin can reassign (`auth.py`, `scope.py`).
27: machine-aware tool design (asks for machine parameters before designing, recommends a machine if skipped, `rec_` rules, riser plate, fit check); process parameters for best quality from the simulation (*Process windows* / *Process parameters*); design skills learned automatically from corrected STEP files (*Skill knobs*, Skills page).
28 (V3): technical data on every tool drawing (material grade, hardness, heat/surface treatment, ISO 2768 general tolerance tables, Ra, stock, weight, notes); review form plus Excel drawing data sheet download/upload (draft only, every change logged); one title block on part, assembly and strip-layout drawings, PDF and DXF (logo plus "Design to Cost", release date, approved by, third-angle projection, revision history); new A3 strip layout PDF. Code: `drawing_data.py`, `drawing_sheet.py`, `tool_drawings.py`, `sheet_layout.py`.
29 (V4): a tolerance on every dimension, in mm or µm: overall sizes (ISO 2768), holes (ISO 286 fit such as H7, thread class 6H), pockets, wire-cut openings and positions; master data *Fit tolerances* and *Feature tolerances*; change any tolerance in the form or the Excel sheet *Dimension tolerances*.

## Status at hand-over
- VERSION = **V4**. The code is committed and pushed. Releases V0–V3 are in `releases/`. The V4 ZIP must be built after the full test suite passes: `python scripts/make_release.py`, then commit `releases/V4` and `releases/LATEST`.
- Last full suite: 320 passed, 1 skipped (the optional Tesseract OCR test); V4 tests (`tests/test_stage28.py`, 7 tests) pass. Re-run the full suite and `python scripts/audit_e2e.py --out docs/audit_e2e_report.md` to confirm.
- Known limits: through holes default to general tolerance (the software cannot tell a clearance hole from a fitted bore; the user sets H7); bent sheet-metal blanks are a developed rectangle (no unfolder); views of very complex parts fall back to a simplified outline after 25 s of hidden-line removal.

## Working rules (follow them every time)
1. **Rules live in master data, not in code.** Every formula, margin, tolerance, rate and default is a row in a master-data table (`mould_db.TABLES`, validated in `_check`), seeded idempotently with `is_example=1` and the note "EXAMPLE … check". Seeds are run by `python -m backend.app.capacity_db` and by `migrate._seeds()` during an upgrade; commit the updated `master_data/costing_db.sqlite`. Number columns cannot be negative, so store signed values as text.
2. **Never lose user data.** New tables go in `projects_db.py` (created by `create_all`/migrate). Released designs are never edited: start a new revision. Every change is logged (history / revision tables).
3. **Every new feature has:** an API in `main.py`, UI in `frontend/` (match the existing JS style: `$`, `esc`, `api`, `status`), an Excel/PDF output where useful, tests in `tests/test_stageNN.py` (use `add_part`/`project` from `tests/test_rm_cost.py` and the `TestClient`), a README section, a ROADMAP row, release notes and a VERSION bump.
4. **Verify before you push:** run the changed tests, then the full suite (`python -m pytest tests -q -W ignore`, about 40 min, so run it in the background), render the PDFs to PNG (`pdftoppm`) and look at them, and screenshot the UI with Playwright (`/opt/pw-browsers/chromium`) against a temporary server with `MASTER_DATA_PATH`, `COSTING_DB_PATH`, `DATABASE_URL` and `DTC_STORAGE_FOLDER` pointing to copies.
5. **Downloads carry the brand** automatically (middleware). Excel files that are uploaded again must find their header row below the logo rows.
6. **Roles:** master-data and rates writes need head; users/backups need admin; part and project access goes through `scope.py`.
7. Commit with clear messages; push only to the assigned branch; no PR unless I ask.
8. Report honestly: say what was tested, what failed, and what is EXAMPLE data that I must verify.

Start by reading `README.md`, `ROADMAP.md` and `git log --oneline -15`, then tell me in a few lines what you see and wait for my next request.

---
