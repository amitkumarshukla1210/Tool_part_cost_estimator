---
name: design-to-cost-dev
description: Use for any work on the Design to Cost / Part Cost Estimator repository (part, RM and tool cost, tool design and drawings, master data, rates, releases). Holds the project memory (stages 1-35) and the working rules (master data only added, main wins, one PR).
---

Project: **Design to Cost — Part Cost Estimator**, repository `amitkumarshukla1210/Tool_part_cost_estimator`.
I am Amit, Head of Operations / costing at an OEM (supply chain, production, strategic sourcing, projects; RM, part and tool cost,
BOM cost and CAPEX, EBITDA, digital transformation). Answer simply, **INR first**.

**Read `README.md` and `ROADMAP.md` first.** Stages 1–35 are built; the next stage is the first free number in `ROADMAP.md`.
Stack: Python / FastAPI (`backend/app/`), plain HTML / JS (`frontend/`), SQLite (`data/projects.sqlite` = my data, `master_data/costing_db.sqlite`
+ `master_data/master_data.xlsx` = master data), CadQuery for 3D, reportlab (PDF), ezdxf (DXF), openpyxl (Excel). Local: Windows kit `windows/`
(`DTC_Start.bat`, `DTC_Update.bat` with master-data merge, `DTC_Backup.bat`, `DTC_Restore.bat`, `DTC_Rollback.bat`) at http://127.0.0.1:8000/.
Version: the file `VERSION` (V0 …). Logins are always on (Admin page: users, roles viewer < engineer < approver < head < admin, permissions,
tool groups per user, activity log, backups, drawing logo and company).

What the later stages added (details in README):
- 20–28: backup / update kit, corrections, logins and Admin, sheet-metal dies stage-wise and the learning tool BOM, correct any traced value,
  developed blank, work instruction and PO pack, tool design in 3D with drawings and logo, simulation report and video, 3D correction, large parts.
- 29: price master, material types, recommended part grade, `VERSION` V0.
- 30: head of department role and data access by tool group (`scope.py`).
- 31: technical data, release (design loop: *Tool design frozen*) and revision history on the tool drawings; drawing data form and Excel (`drawing_data.py`).
- 32: a tolerance on every dimension, mm or µm; Fit tolerances (ISO 286) (`dim_tolerances.py`).
- 33: production machine asked before the tool design, checked, or recommended (`machine_spec.py`).
- 34: process parameters for the first trial from the simulation and the material window (`process_params.py`).
- 35: logo and name on every Excel and PDF download (`branding.py`).

**Rules (always):**
- No hard-coded rates or rules: every value comes from master data or a formula in master data and is traceable on screen.
- Rates are monthly and append-only; only approved rates are used; approving needs the permission *Approve rates*; new prices are drafts.
- EXAMPLE values stay flagged until replaced; never invent market data or history.
- Never overwrite `master_data/` or my data: only ADD rows (an idempotent `seed()`), never change or delete existing rows; then run
  `python -m backend.app.upgrade_tools fingerprints` and commit `backend/app/shipped_rows.json`.
- If main already has a feature, main wins; if unsure, ask me.
- No release ZIPs or big binaries in the repository.

**Workflow:** new branch from the latest `origin/main` → ask me the key decisions before coding → one commit per feature with tests
(`tests/`, helpers `add_part` / `project` in `tests/test_rm_cost.py`) → the full `python -m pytest tests -q` must pass → check the UI in a browser
(Playwright, Chromium at `/opt/pw-browsers/chromium`, or `run`) and look at the PDFs / drawings (`pdftoppm`) → README section + ROADMAP row →
push, open ONE PR, do not merge unless I say.

Start by reading README.md, ROADMAP.md and `git log --oneline -15`, tell me in a few lines what you see, and wait for my request.
