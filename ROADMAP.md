# Design to Cost: architecture & roadmap

Design to Cost is the Project Leader's end-to-end tool for planning **BOM cost** and **CAPEX** (tools, moulds, dies,
machines) during new product development. The two briefs it is built from are kept in `docs/`:

- `docs/MASTER_FLOW_PROMPT.txt`: the end-to-end flow (R&D input → tool concept → simulation → design loop → tool
  and part costing → history → downloads → harness & PCB → project leader view)
- `docs/ROADMAP_PROMPT.txt`: requirement sets A–E (sheet-metal tools, tool cost, country rate library, country
  comparison, monthly rate update with approval)

## Rules that apply to every stage
1. **No hard-coded values.** Every number comes from master data or from a formula stored in master data.
2. **Traceability.** Every value on screen is clickable. It shows the formula, its inputs, where each input comes
   from (master-data row, your input, rate version and month, CAD file and revision, or calculated), approval status
   and the full breakup.
3. **Approved-rate library.** Only approved rate versions are used, and every result records the versions it used.
4. **Design to Cost theme** on every page and every export.
5. **Excel + PDF export** with the full backup data.
6. **"My PC now, server later".** It runs on one PC today. The design (database layer, file storage, who-did-what in
   every history record) allows a shared server with PostgreSQL and logins later, without changing the data.

---

## Architecture

```
Browser (HTML + JS, three.js viewer, Design to Cost theme)
   │  Estimate · Projects/Dashboard · Parts · Import · Rates · Master data · Help
   ▼
FastAPI web server (Python) ──────────────────────────────────────────────┐
   │                                                                       │
   ├── Geometry & CAD     CadQuery / OpenCascade (OCP): STEP read, XCAF assembly tree, volumes,
   │                      projected areas, wall thickness, drafts, undercuts, unfolding (later)
   ├── Costing engines    gross weight, cavities, MHR & labour (rate engine), tool cost, part cost,
   │                      all driven by formulas in master data and producing traces
   ├── Trace engine       every result = nodes {formula, inputs, source}; drives the traceability panel
   ├── Rate library       versioned country rates with approval; forex; monthly fetch (later)
   ├── Part register      projects, variants, BOM tree, parts, revisions, files, history, search
   └── Exports            Excel (openpyxl), PDF (ReportLab), DXF (ezdxf), pictures (matplotlib)
   │
   ▼
Storage
   ├── master_data/master_data.xlsx      general parameters & part materials (Excel, editable)
   ├── master_data/costing_db.sqlite     mould & die tables, countries, machines, formulas, rate library
   ├── data/projects.sqlite              projects, parts, revisions, BOM, history   (DATABASE_URL → PostgreSQL later)
   └── storage/  (folder set in master data)   CAD files and thumbnails, stored by checksum
```

- **Master data vs project data.** Master data (rates, formulas, machines) ships with the app and is versioned in
  git. Project data (your parts, CAD files, costs) lives in `data/` and `storage/`, which are **never** committed to
  GitHub. Back them up like any company data.
- **Database layer.** New project tables use SQLAlchemy, so the same code runs on SQLite now and PostgreSQL later
  (set `DATABASE_URL`). The master-data tables move to the same layer when the server stage comes.
- **Files.** Each uploaded or extracted file is stored once under its SHA-256 checksum (no duplicates). The database
  keeps name, size, checksum and path. The storage folder is a setting in master data.
- **History.** Every change writes a history record (what, old → new, who, when). Revisions are never overwritten.

---

## How automatic is each feature? (honest view)

**Auto** = fully automatic. **Auto + review** = an automatic first proposal that an engineer checks or edits.
**External** = needs software or data outside this app.

| Area | Feature | Level | How / open-source library |
|---|---|---|---|
| Register | Upload single part (STEP), geometry, thumbnail | Auto | CadQuery/OCP; thumbnail with matplotlib |
| Register | Split an assembly STEP into parts with tree and quantities | Auto + review | OCP XCAF (STEPCAFControl). Repeats grouped by shared definition; look-alikes flagged for you |
| Register | Excel bulk upload with files / ZIP | Auto | openpyxl, zipfile |
| Register | Process suggestion with its reason: material family first, then geometry rules (wall, constant-wall share, bends, fill, size), then inserts | Auto + review | Materials sheet + formula rules in Part register setup. Geometry alone cannot tell a thin plastic shell from a sheet-metal box, so the material decides |
| Register | Detect moulded-in inserts in a 3D assembly (metal part fully / partly enclosed by a plastic or die-cast body) | Auto + review | OCP solid classifier on points just outside the insert surface; overlap volume by boolean common. The engineer confirms each insert. Material is not in the STEP file, so "metal" is your confirmation |
| Register | Assemblies from other formats (Parasolid, CATIA, NX native) | External | Export STEP from the CAD system first |
| Mould concept | Opening direction, parting line proposal | Auto + review | Projected-area / undercut minimisation on the tessellated part (OCP + numpy) |
| Mould concept | Undercut detection → slides / lifters | Auto + review | Ray casting along the opening direction; complex undercuts need the engineer |
| Mould concept | Cavities, insert size, standard mould base | Auto + review | Existing rules + mould & die database |
| Mould concept | Gate / runner type, cooling concept, ejection | Auto + review | Rule tables in master data (proposal only) |
| Mould concept | Concept 3D blocks + dimensioned 2D/PDF layout | Auto | CadQuery solids, ReportLab / ezdxf drawings |
| Mould concept | Final detailed tool design | External | Engineer's CAD; uploaded to replace the concept |
| Simulation | Wall-thickness map, draft-angle check, undercut map | Auto | Ray casting / face normals on the tessellation, coloured pictures with matplotlib |
| Simulation | Sink / stress-mark risk areas | Auto + review | Rule: thick sections and rib-to-wall ratio from the thickness map |
| Simulation | Fill / pack / cooling time → cycle time | Auto + review | Analytical cooling-time and flow-length formulas (stored in master data). **Not** Moldflow accuracy |
| Simulation | Injection pressure → clamp tonnage → machine | Auto + review | Empirical pressure formulas × projected area; machine-selection rules in master data |
| Simulation | Real 3D flow / warpage simulation | External | Commercial tools (Moldflow, Moldex3D). Open-source research solvers (OpenFOAM-based, e.g. openInjMoldSim) are limited and not production-grade |
| Simulation | Structural FEA (optional) | External | CalculiX + Gmsh (open source); needs meshing and setup by an engineer |
| Sheet metal | Operation sequence (blank, draw, trim, pierce, form, fold) | Auto + review | Rules from part features (holes, bends, draw depth); you edit, add or remove stages |
| Sheet metal | Flat pattern of simple bent parts | Auto + review | Current estimate (thickness + developed length); K-factor in master data |
| Sheet metal | Flat pattern of complex / drawn parts | External | FreeCAD SheetMetal workbench (open source, LGPL) as an optional helper, or the engineer's CAD |
| Sheet metal | Forces, tonnage, press selection per stage | Auto | Formulas in master data, press list in master data |
| Sheet metal | Formability (bend radius, hole-to-edge, LDR, springback) | Auto + review | Empirical rules in master data |
| Sheet metal | Blank / strip layout DXF + dimensioned PDF | Auto | ezdxf + ReportLab |
| Tool cost | Process-wise tool cost with MHR, labour, trial, design, overhead, profit | Auto + review | Rate engine + formulas in master data; process times from volume removed, area, features |
| Part cost | RM, process, rejection, overhead, profit, packing, amortisation, logistics | Auto | Formulas in master data; machine-selection rules visible and editable |
| Country | Country comparison and landed cost in India | Auto | Rate library + duty table per HS code and country (rates must be kept up to date by you) |
| Rates | Monthly fetch of forex, metal indices, labour and inflation data | Auto + review | Free official APIs only (ECB, World Bank, ILOSTAT, …); every value arrives as a Draft for your approval |
| Rates | Exact steel-grade prices, MHR inputs, process rates | Auto + review | Index-based proposals (last approved × index change); supplier quotes are the real source |
| Harness | BOM from KBL / VEC XML | Auto | Python XML parser (KBL and VEC are open VDA/ProSTEP formats) |
| Harness | BOM table from a text PDF drawing | Auto + review | pdfplumber; low-confidence cells marked |
| Harness | BOM from a scanned PDF | Auto + review | Tesseract OCR (open source); accuracy depends on scan quality |
| Harness | DWG drawings | External | Convert to DXF with ODA File Converter (free, proprietary licence) or LibreDWG (GPL); then ezdxf |
| PCB | BOM / CPL from KiCad, Altium and other CSV/Excel exports | Auto | CSV/Excel parsers; Gerber layer and board size via a Gerber parser (e.g. pygerber, open source) |
| PCB | Component prices from distributors | External | Optional APIs with a free key (e.g. Nexar/Octopart, Mouser, Digi-Key), subject to their terms; otherwise your own part library |
| Leader view | Dashboard, CAPEX plan, management export | Auto | From the register and costing results |

---

## Stages (one PR each)

| Stage | Contents | Brief |
|---|---|---|
| ✅ done | Stages A–C estimator; master data (Excel); mould & die database; theme; **rate library with approval, MHR & labour engine, traceability panel** | earlier PRs 1–4 |
| ✅ 1 | **Database + part register:** projects, variants, BOM tree, parts, revisions, file storage, history. Single-part upload, **assembly split** (tree, thumbnails, quantities, tick what to cost: Make / Bought-out / Existing / Not required), **Excel bulk upload** with files or ZIP, part code / name / rev / material / process / volume / programme life, search and filters, **project dashboard skeleton** (status counts, targets), Excel + PDF export | Flow Step 1, 7 (part), 8 (part) |
| ✅ 1b | **Process suggestion & insert moulding in the register:** material-first suggestion with the reason shown everywhere; bends in the geometry; processes *insert moulding* and *insert die casting*; inserts as their own parts linked with quantity (code, material, own 3D or shape + dimensions, bought-out price, source, month); insert detection on assembly import, confirmed by you; inserts shown under their body in the BOM, not as children; body / insert / total weight traced; insert rules for later stages stored in master data | Your insert-moulding brief |
| ✅ 2 | **Part geometry & RM cost on the register:** Stages A–B run per revision and are stored with traces (weight from material density, gross weight, RM cost from approved rates). The RM formulas are rows in master data (scopes `rm_<family>`), the material rate and scrap value are approved rates per country (moved out of the Materials sheet), each result is a numbered version with the rate versions it used, new rates never change a stored cost (the part says "newer approved rates exist" and you recalculate), RM cost on the Parts list, filters and dashboard (per variant, raw material only), RM cost sheet in Excel + PDF, and the Estimate page opens a registered part and saves back to it | Step 6 (RM), rules 1–3 |
| **3 (this PR)** | **Material & process rates by country:** tool steels (P20, H13, 2738, D2, SKD11, S136, 1.2343 ESR, mould base steel, C45, BeCu), part materials (CRCA, SS, Al, plastics) and process rates (per hour; heat treatment /kg, wire cut /cm² or /mm, polishing /cm², painting /m² or /unit, nitriding, texture, plating, transport /kg, minimum charge per job) as approved rates for 9 countries in the rate library. The list, units and India values are master data (*Process rates by unit*, *Tool materials*); other countries are proposed from a *Country rate index* ÷ forex as drafts, or seeded as EXAMPLE values. Rates page grid: item × country, local / INR, % against India, traceable | C2 |
| 4 | **Tool cost engine:** process-wise tool cost (cutting, CNC, wire cut/EDM, grinding, polishing, heat treatment, surface treatment, assembly, try-out); process time logic; machine, MHR, labour skill and operators; trial, design, overhead & profit, packing, transport, warranty/spares. Mould BOM moves to traced MHR. Tool cost sheet in Excel + PDF | B1–B5, Step 5 |
| 5 | **Mould / die concept v1:** opening direction, undercut detection → slides/lifters, cavity layout, inserts, mould base, gate/runner/cooling/ejection proposals; concept 3D blocks + 2D PDF; upload of the final tool design. **Insert moulding:** insert locating / holding features per insert (pins, magnets, pockets) in the mould BOM, insert pre-heating if needed, vertical machine with shuttle / rotary table vs horizontal, manual vs robot loading, and the cap on cavities from inserts per shot | Step 2, insert brief |
| 6 | **Simulation & analysis page v1** (plastic, die casting): wall-thickness, draft and undercut maps, sink-risk areas, cooling/cycle time, injection pressure → clamp tonnage → machine selection (rules editable); coloured PDF report with "Corrections required". **Insert moulding:** insert loading time added to the cycle (less the share hidden by a shuttle / rotary table), shot weight without the insert volume, flow around the insert, weld-line and stress risk near inserts (wall around the insert), insert-shift risk | Step 3, insert brief |
| 7 | **Design loop:** status flow (Uploaded → Concept tool → Simulation → Corrections required → Revised → Simulation OK → Tool design frozen), what changed / who / when, compare two revisions side by side | Step 4 |
| 8 | **Part costing page:** process cost from cycle time × selected machine's MHR, labour, secondary operations, rejection, overhead, profit, packing, tool amortisation, logistics; per-part cost versions; part tool-cost and part-cost downloads with full backup. **Insert moulding:** insert cost (BOP price × quantity), loading labour or robot cost, extra rejection and the inserts lost with it, insert handling %; weight shown as body + inserts = total | Step 6, 8, insert brief |
| 9 | **Sheet-metal tools I:** multi-stage vs progressive, operation sequence (suggested, editable), stage weight, forces, tonnage, press selection, formability checks | A1–A3, Step 3 (sheet) |
| 10 | **Sheet-metal tools II:** blank/flat pattern DXF + dimensioned PDF, stage CAD upload or simplified sketches, PDF pack, progressive strip layout (pitch, width, bridge, stations, pilots, utilisation) | A4–A5 |
| 11 | **Country comparison & landed cost** for tools and parts: side by side for 9+ countries, ex-works in local currency / USD / INR, freight, insurance, BCD, SWS, IGST (credit shown separately), clearance, inland transport; duty per HS code & country incl. FTA; forex ±5 %; stacked bar chart; cheapest highlighted; Excel + PDF | C3–C4, D1–D6 |
| 12 | **Monthly rate update:** GitHub Actions on the 1st + "Fetch now", free official sources only, index-based proposals, drafts to review, failure keeps the last approved value | E2–E3, E6 |
| 13 | **Project leader view:** project/variant BOM cost vs target, tool & mould CAPEX, machine CAPEX need from capacity, open corrections, CAPEX plan by supplier/country with payment milestones and timeline, consolidated project Excel + PDF for management | Leader view, Step 8 (project) |
| 14 | **Harness & PCB BOM extraction (Page A):** KBL/VEC XML, text-PDF BOM tables, PCB BOM/CPL/KiCad/Altium exports; review and edit with low-confidence marks | Option 3 Page A |
| 15 | **Harness & PCB costing (Page B):** wire cost (length × rate per grade/size, copper index), connector/terminal library, processing times with MHR/labour; PCB components from your library (optional distributor APIs), bare board, SMT/THT, testing; Excel/PDF | Option 3 Page B |
| 16 | Scanned-PDF OCR (Tesseract), DWG via converter | Option 3 (later) |
| 17 | **Server mode:** PostgreSQL, logins and roles, shared file storage | "server later" |

Stages are built in this order unless you change it. Each stage starts with questions on its key decisions.

---

## Decisions taken so far

| Topic | Decision |
|---|---|
| Users | Your PC, one user, no login. Every record stores who did it, so roles can be added for the server stage. |
| Structure | Project → Variant → Assembly → Part. A part can be used in several variants and assemblies. |
| Part codes | Your own codes (typed or imported). If blank, generated from a pattern in master data. Must be unique. |
| Assembly repeats | Identical definitions become one part with quantity = count. Look-alikes (same size and volume, different name) are flagged for you to confirm. |
| File storage | Folder set in master data (default `storage/` next to the app). Files are stored by checksum and never committed to GitHub. |
| New upload, same part code | New revision (you enter rev no. and what changed). Old revisions, files and history are kept. |
| Targets | Target BOM cost per variant, optional target piece cost per part, CAPEX budget per project (INR). |
| Excel bulk upload | Excel template together with STEP files or a ZIP, matched by file name. Rows without a file are kept as "File missing". |
| MHR / labour | Labour separate from MHR; straight-line depreciation; interest on average investment; fixed costs over days × shifts × hours × utilisation; overhead on the machine subtotal; labour from monthly CTC + employer % + supervision % + productive time. |
| Rates | Monthly versions; only approved ones used; Save & approve for your own edits; approver name remembered. |
| Process suggestion | Material first (its part type in Materials: plastic → moulding, ADC12 / Al alloys → die casting, cast iron → foundry, steel / aluminium sheet grades → sheet metal), then geometry (constant wall + bends → sheet metal), then inserts. The reason is shown with every suggestion. |
| Insert moulding scope | Register now (this PR). Mould design, simulation and costing effects are built inside Stages 5, 6 and 8; their rules are already in master data (Part register setup → Insert moulding rules, all EXAMPLE values). |
| Detected inserts | Confirmed inserts make the body ONE part (process insert moulding / insert die casting) with each insert as its own bought-out part linked with a quantity, not an assembly. An assembly holding only the body and its inserts is unticked by default. |
| Insert price | Stored on the insert part: price per piece, currency, source, month, example flag; changes kept in history. |
| Material rates | Approved rates in the rate library (categories `material`, `material_scrap`; item = material name; per country), no longer columns of the Materials sheet. Seeded as EXAMPLE values for India. |
| RM formulas | Cost formulas of scopes `rm_plastic`, `rm_die_casting`, `rm_foundry`, `rm_sheet_metal`; their inputs come from the rate library, Parameters or the part (`parameter` and `part` sources). Only the sheet nesting search is code. |
| RM versions | Calculated automatically when the revision, material, process, sourcing, country, month, typed inputs or inserts change. New approved rates or changed formulas never change a stored cost: you recalculate on purpose (per part or per project). |
| RM scope | Parts you make (moulding, casting, sheet metal). Bought-out parts show their price, assemblies none, machined parts (bar stock) later. Insert-moulded parts: body material only; inserts are costed in stage 8. |
| Producing country | Per part, default from Register settings (`default_country`, India). Cost shown in the country's currency and in INR. Other countries' material rates arrive in stage 3. |
| Rates by country | Part materials, tool steels and processes are library rates per country (categories `material`, `material_scrap`, `tool_material`, `process_hour`, `process_unit`, `process_min_charge`), in the country's own currency; INR and difference against India are computed with approved forex. |
| Country rate index | Master data table with a price level per country against India (part materials, tool steels, processes). Used only to PROPOSE missing rates as drafts (India × index ÷ forex, 3 significant digits); never overwrites a rate. Seeded values are EXAMPLE. |
| Process rate units | A process is charged per kg, cm², mm, m² or unit, with an optional minimum charge per job. One flat rate, no size bands yet. Wire cut exists per cm² and per mm. |
| Master data vs library | Master data keeps the list of steels / processes, density, hardness, unit and the India value. The library is the source of country rates from stage 4; the mould preview still reads the India table values until then. |
