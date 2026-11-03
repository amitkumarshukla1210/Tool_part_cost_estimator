---
name: design-to-cost-dev
description: Use for any work on the Design to Cost / Part Cost Estimator repository (part, RM and tool cost, tool design and drawings, master data, rates, releases). Holds the project memory (stages 1-45) and the working rules (master data only added, main wins, one PR).
---

Project: **Design to Cost — Part Cost Estimator**, repository `amitkumarshukla1210/Tool_part_cost_estimator`.
I am Amit, Head of Operations / costing at an OEM (supply chain, production, strategic sourcing, projects; RM, part and tool cost,
BOM cost and CAPEX, EBITDA, digital transformation). Answer simply, **INR first**.

**State (3 Nov 2026):** stages 1–46 are built (41 = progressive vs stage dies and tool life, PR 51; 42 = part-cost cycle time = the calculated
cycle, PR 53; 43 = toolmaker review, 44 = design skills, both PR 55; 45 = tool internals, production data, FEA, 3D outputs, PR 57; fixes PR 59, 61, 62;
46 = cavities, gate, overflow, ejection, cooling of the mould, PR 64); the next stage is **47** (first free number in `ROADMAP.md`). Everything of the old V4 branch is now on main (written new);
the 4 old unmerged branches are NOT to be merged.
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
- 42: part-cost cycle time is the calculated cycle by default (not the target `cycle_time_s`); tests run on a frozen clock (PR 54).
- 43: toolmaker review of the tool design (`tool_review.py`): table *Review checklist* (Mould & die database; check formula over design facts
  or signed by the toolmaker ok / issue / na / waived), sign-offs append only (`tool_reviews`); a blocking open point stops *Tool design frozen*.
- 44: design skills (`design_skills.py`): drawing-data corrections kept as events; same value on ≥ `skill_min_parts` parts (Design rules) becomes
  the starting value of new designs (typed value wins, switch off / on); skill values written into the drawing data at release.
- 45: tool internals (pins / cooling wanted vs placed, screws, dowels → review facts); supplier production data (`production_data.py`:
  stock = finished + 2 × `stock_allowance_mm` rounded to `stock_round_mm`, operations, cost = split of the tool cost that adds up exactly, Excel);
  real FEA with Gmsh + CalculiX (`fea.py`, `fea_*` Design rules, background job, `tool_fea_runs`, `DTC_Install_FEA.bat`; Gmsh runs in its own
  process); 3D outputs (`outputs3d.py`: offline WebGL viewer per tool, STL, STEP / STL / picture per part, all in the release ZIP).
  The full test suite takes ~19 min (real FEA); Gmsh needs libglu1 on Linux.
- After 45 (PR 59): `register.tool_designs` keeps the 3D design per part / die (fingerprint: part row, revisions, tool costs, inserts,
  drawing data, design skills, part history, master-data file stamps; one lock per part; callers get a copy). Never build the tool
  design outside it. Panel 56 s → ~1-4 s. CalculiX: the solver that answers `ccx -v` is used, static build first (Windows 2.22 zip:
  `ccx_dynamic.exe` needs mkl_rt.2.dll). Update copies every `windows/DTC_*.bat` (new .bat files are no longer missed).
- PR 61: 3D viewer explodes by stacking order (inserts come out of their plate pockets), camera pulls back with the explode,
  selected part solid and the others see-through. PR 62: the part panel asks for everything in parallel and opens at once; the part
  cost (simulated cycle, stage 42) fills in when ready (`#pieceBox`, `openPart` resolves after it); simulation results kept for the
  last 16 parts (`_SIMULATION_CACHE`). Keep panel requests parallel; never make the panel wait for a slow calculation.
- 46 (PR 64): cavities asked before the mould design (`cavity_spec.py`, parts.cavity_check; typed = tool input `cavities`), then the machine.
  New Mould & die table *Mould systems* (`mould_systems.py`): gate / overflow / ejection / cooling values by formula rows in order (facts of
  the design + Design rules + Process windows + Flow materials), typed per part wins (parts.mould_typed, PUT …/mould-systems), checks →
  review fact `systems_bad`. Ejector stroke = part h + `eject_extra_mm`; spacer blocks raised when the catalogue base is short (the cover
  had 20 mm for a 30 mm part); EPS pneumatic ejectors; machine check uses it; 3D viewer *Open & eject*. Cooling channels joined into
  circuits (`mould_features.cooling_plan` / `_cooling`: bridge tubes, U-turn cross channel Ø cd + `cooling_cross_extra_mm` — equal drills at
  90° make a tangent solid FEA cannot mesh — plugs, O-rings, IN / OUT nipples); coolant inlet / flow / Reynolds / outlet / pressure drop,
  dew-point check. Flow simulation runs on the designed gate (`register.design_gates`, `mould_design.to_model`), checks gate shear and freeze.
  Fixes: 2-cavity drawing set PDF overflow (`tool_drawings._holes_at_side`), cut labels per part only, FEA re-meshes on "nonpositive jacobian".
  New EXAMPLE values to replace: gate factors, `eject_extra_mm`, `stop_disc_mm`, coolant rows (`water_below_mould_c`, `water_dt_max_c`,
  `tcu_pressure_bar`, `dew_point_c` …), `cooling_cross_extra_mm`, `gate_freeze_share`. Full suite: ~25 min, 443 tests.
  Fingerprints: a cloud clone is shallow — `git fetch --unshallow` before `upgrade_tools fingerprints`, or old rows are lost.
- To open a STEP: his CAD, eDrawings Viewer (SOLIDWORKS free downloads; not "3DEXPERIENCE Exchange", that is a SOLIDWORKS add-in),
  CAD Assistant, FreeCAD, or the app's own 3D viewer. Windows 3D Viewer opens the STL, not STEP.
- Amit's PC: kit at `D:\Project\DTC Tool and mould`, app on port 8100, CalculiX 2.22 `ccx_static.exe` in
  `DTC_Data\tools\calculix\calculix_2.22_4win\calculix_2.22_4win`, Gmsh in the venv. FEA limits and `fea_mesh_mm` still EXAMPLE
  (large 1000 mm moulds: `fea_mesh_mm` 25-40).
- Audit (PR 45, re-run after stage 41 with its checks): `python scripts/audit_e2e.py` drives the whole tool (15 cases, 883 calls), 0 findings; report `docs/audit_e2e_report.md`.
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
