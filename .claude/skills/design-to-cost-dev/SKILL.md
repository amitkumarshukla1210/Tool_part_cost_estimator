---
name: design-to-cost-dev
description: Use for any work on the Design to Cost / Part Cost Estimator repository (part, RM and tool cost, tool design and drawings, master data, rates, releases). Holds the project memory (stages 1-50) and the working rules (master data only added, main wins, one PR).
---

Project: **Design to Cost — Part Cost Estimator**, repository `amitkumarshukla1210/Tool_part_cost_estimator`.
I am Amit, Head of Operations / costing at an OEM (supply chain, production, strategic sourcing, projects; RM, part and tool cost,
BOM cost and CAPEX, EBITDA, digital transformation). Answer simply, **INR first**.

**State (9 Nov 2026):** stages 1–55 are built (41 = progressive vs stage dies and tool life, PR 51; 42 = part-cost cycle time = the calculated
cycle, PR 53; 43 = toolmaker review, 44 = design skills, both PR 55; 45 = tool internals, production data, FEA, 3D outputs, PR 57; fixes PR 59, 61, 62;
46 = cavities, gate, overflow, ejection, cooling of the mould, PR 64; 47 = saved files with revisions, 48 = India vs China per cost line,
49 = scrap reuse and scrap rate % of RM, all PR 66; 50 = several countries per part, traces for admin, tool life per part,
suppliers removed, PR 68; 51 = country rate book, PR 70; 52 = monthly automatic country rates, PR 71; 53 = unique codes, live Price master link, main / sub materials, more grades, PR 72; 54 = 24-month history for every rate + more grades, PR 73; 55 = cost change report of a project (`cost_changes.py`)); the next stage is **56** (first free number in `ROADMAP.md`). Everything of the old V4 branch is now on main (written new);
the 4 old unmerged branches are NOT to be merged; neither is `rate-update-2026-11` (draft rates on an old main) as it is.
To save tokens, do not read the whole README (1650+ lines): read the stage table in `ROADMAP.md` and only the README section of the topic I ask about.
Stack: Python / FastAPI (`backend/app/`), plain HTML / JS (`frontend/`), SQLite (`data/projects.sqlite` = my data, `master_data/costing_db.sqlite`
+ `master_data/master_data.xlsx` = master data), CadQuery for 3D, reportlab (PDF), ezdxf (DXF), openpyxl (Excel). Local: Windows kit `windows/`
(`DTC_Start.bat`, `DTC_Update.bat` with master-data merge, `DTC_Backup.bat`, `DTC_Restore.bat`, `DTC_Rollback.bat`) at http://127.0.0.1:8100/.
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
- PR 66 (fixes): Windows kit default port **8100** (app, `dtc_settings.ini`, docs); drawing set **one page per drawing**
  (`tool_drawings._one_sheet`: title block at the foot, hole table under the views in up to 4 blocks `_hole_columns`, views /
  pictures take the height left, KeepInFrame shrink as last resort); faster downloads (`render3d._fill_rows` row-by-row fill of
  large triangles, 3× faster; meshes / pictures kept on the components `render3d.kept`; `register._kept_file` keeps finished
  files, ZIP reuses the PDF `_drawing_set`; `GET …/tool-design/prepare` makes PDF + ZIP in the background after the panel has
  loaded; links show "Preparing … n s"). **pypdf** was missing from requirements.txt (PDF logo stamp failed silently on Windows);
  test_requirements checks every import, test_branding_all checks every part PDF / Excel / ZIP carries logo + name.
- 47 (PR 66): saved files (`saved_files.py`, table `saved_files`): every GET file under /api/parts/{id}/ (pdf, xlsx, zip, dxf,
  step, stl, png, html, mp4 …) saved with a revision (bytes via file_store, in backups) and served again while `part_state`
  (hash per group: part, project, every part table, inserts, master data / rates files, drawing settings without drawn-by,
  software stamp) is unchanged; after a change *out of date*, next revision made when asked, old ones kept with what changed
  (part panel → Saved files; GET …/saved-files, …/saved-files/{id}; header X-DTC-Saved). Middleware `saved_part_files` sits
  outside the brand stamp and inside AuthMiddleware (now added last = runs first). 3D design and simulation also pickled on
  disk (`storage/kept`, `disk_get` / `disk_put`, keyed with the software stamp). Every part type.
- 48 (PR 66): India vs comparison country (`landed.versus`, Register settings `compare_country` = CN, `landed.seed()`): tool and
  part cost tables get China CNY / INR columns (same engines, China approved rates, traces in the answer: click opens them),
  landed rows for both (exw, freight, insurance, CIF, BCD, SWS, IGST + credit taken, clearance, inland, landed); downloads
  `/vs-country/export.xlsx|pdf` = `<part>_cost_India_vs_China.*`.
- 49 (PR 66): scrap reuse (`rm_cost.seed_scrap_reuse`, plastic / die casting / foundry / EPS / blow): reused_g = scrap ×
  `scrap_reuse_pct`, virgin_g = input − reused (RM cost on virgin), sold_g sold at `scrap_value` = RM rate ×
  `scrap_rate_pct_of_rm` % when > 0, else the fixed scrap rate; part (RM inputs) > material (new optional Materials columns,
  `master_data.MATERIAL_PARAMETERS`) > family (Parameters); starting 0 = as before. EXAMPLE: both %, China rates / duties /
  freight. Full suite: ~26 min, 459 tests; audit 0 findings.
- 50 (PR 68): part fields `compare_countries` (JSON) and `tool_life_shots`. RM inputs block (above the RM table): producing country
  (stored, BOM / dashboard / PO) + *Also cost in* multi-select (default Register settings `compare_country` CN; `landed.selected`).
  `landed.versus` = own country as the panel shows it (stored versions) + every selected country live (`_country_block`: RM, tool,
  part, landed); RM / tool / part tables get two columns per country (currency, INR; INR country one), a forex row, landed rows;
  traces of each country in the answer. A China-produced part shows China as own (the old 'India' column showed China values).
  Downloads `<part>_cost_<own>_vs_<others>.*` (RM, tool, part sheets). Permission `open_traces` (admin): without it values are plain
  (trace.js `canTrace`, CSS `.no-trace`). Tool / mould life per part → Stage C and piece `tool_life_shots` (user source).
  Suppliers page / menu / help / panel block removed (`/suppliers` → /parts; data and API kept). Full suite 463 tests.
- 51 (PR 70): country rate book (`country_rate_book.py`, `python -m backend.app.country_rate_book [--countries] [--offline]
  [--ilo-file]`; kit `DTC_Country_Rates.bat` → `DTC_Data\country_rates`; monthly workflow artifact): one Excel per country, 24 months,
  sheets Summary / RM_Price (market A, grades of the tool by family B, ~60 catalogue grades for entry C) / Labour / Process_Cost /
  Electricity / Transport / Forex / Sources. MARKET from FRED, ILOSTAT (SDMX; refuses automatic download 403 → `--ilo-file`, never
  spoof user agents), Eurostat, World Bank, history `country_rate_book_history.json` append-only; APP = approved rates; empty months
  stay empty. FRED and ILO answer only some user agents: urllib default works for FRED. Environment allowed hosts added for these.
- 52 (PR 71): `auto_rates.py`: new approved rate versions each month (system user "Auto monthly update", origin
  `auto monthly`) for forex, RM / tool steel / scrap (index × forex ratio, tag `index A→B` in source), power (DE Eurostat, others
  PPI power), salaries (ILO yearly change, baseline in table `auto_rate_state`). Never writes a month that already has a version
  (admin values kept). Runs at app start when `DTC_AUTO_RATES=1` (kit sets it; tests do not), Admin → Monthly rates, and
  `DTC_Country_Rates.bat` (now `-m backend.app.auto_rates`). Workbooks B2 / B3 = indicative grade trend (user's choice).
  The user chose auto-approval for these monthly updates over the draft rule.
- 53 (PR 72): `item_codes.py` (tables `item_codes`, `code_prefixes`, created per installation, NOT shipped: codes are
  local, never reused); GET /api/master-codes/{general|mould|setup|register}?country&month → codes + live prices (PRICED
  tables); master-data.js Code + Price columns, Price master Code; part picker main (material_type) → sub (material);
  `material_grades.seed` (run on the shipped master data; reaches PCs by DTC_Update merge). Old rate copies in Tool materials /
  Process rates are labelled "not used". Fingerprints need `git fetch --unshallow` first (done).
- 54 (PR 73): `price_history.backfill(hist)` run once by `auto_rates.run` (state `history_done`): approved versions before
  each rate's first one, 24 months back (forex / DE power market, grades / scrap / tool steels by index, salaries ILO, rest flat;
  EXAMPLE, user "Indicative history", origin `history`, bulk insert, ~72k rows on the shipped data). Not run on the shipped
  master data (needs the FRED history on the PC). `material_grades` lists extended (stainless, EN steels, sheet, plastics,
  tool steels). `country_rate_book._norm` keeps word gaps.
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
