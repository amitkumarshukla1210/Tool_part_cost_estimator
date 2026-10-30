# Prompt to paste into a new chat (memory + working rules)

Copy everything between the two lines below into a new Claude Code chat on this repository. The same text is the project skill
`.claude/skills/design-to-cost-dev/SKILL.md`, which a Claude Code session on this repository finds by itself.

---

Project: **Design to Cost — Part Cost Estimator**, repository `amitkumarshukla1210/Tool_part_cost_estimator`.
I am Amit, Head of Operations / costing at an OEM (supply chain, production, strategic sourcing, projects; RM, part and tool cost,
BOM cost and CAPEX, EBITDA, digital transformation). Answer simply, **INR first**.

**State (30 Oct 2026):** stages 1–41 are built (38 = per-user admin permissions, PR 48; 39 = flow simulation, PR 50; 40 = project
totals per tool group, PR 49; 41 = progressive vs stage dies and tool life); the next stage is **42** (first free number in `ROADMAP.md`).
To save tokens, do not read the whole README (1350+ lines): read the stage table in `ROADMAP.md` and only the README section of the topic I ask about.
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
- 36: AI assistant (Ask AI) on every page, read only, through the user's own login; Admin → AI assistant (`bot.py`).
- 37: machined parts end to end: turned / milled from the 3D model, bar stock from Stock sizes, machining time and fixture (scope `machining`), part cost on the lathe / VMC (`machining.py`).
- 38: admin user permissions: per-user allow / deny overrides on top of the role, update started from Admin (PR 48).
- 39: flow simulation (`flow_sim.py`): dual-domain solver on the 3D model for plastic, die casting, foundry, EPS, blow — fill,
  pressure, clamp, front temperature, cooling / solidification, weld lines / cold shuts, air traps / blow holes, sinks / shrinkage
  porosity (feeding), stress areas, machine; tables *Flow materials*, *Flow rules*; background jobs with progress (`sim_jobs.py`),
  saved runs with PDF + video (`sim_runs`), external reports attached; video 10× faster (`render3d.face_view` / `paint`).
- 40: project totals per tool group (`scope.project_view`): a user limited to tool groups sees dashboard / leader view / exports of their parts only; tool group *Machining*.
- 41: progressive die vs stage dies on the sheet-metal part page (`sheet_compare.py`, scope `sheet_compare`): part cost, die life, die sets, CAPEX,
  amortisation and break-even volume, live and traced; part cost amortisation is life-based: one tool ÷ min(tool_life_shots × cavities, programme ÷ tools for capacity).
- Audit (PR 45): `python scripts/audit_e2e.py` drives the whole tool (14 cases, 829 calls), 0 findings; report `docs/audit_e2e_report.md`.
  Run it before every release. Many costs still use EXAMPLE rates (Master data → checklist) until I replace them.

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

Start with `git log --oneline -5` and the ROADMAP stage table only, confirm in 3 lines what is new since this memory, and wait for my request.
When a stage is merged, update this memory (stage list, State line) in `.claude/skills/design-to-cost-dev/SKILL.md` and `docs/HANDOFF_PROMPT.md`.

---
