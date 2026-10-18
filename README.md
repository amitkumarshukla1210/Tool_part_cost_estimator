<img src="theme/logo.png" alt="Design to Cost logo" height="42" />

# Design to Cost

**Part Cost Estimator** is the Design to Cost module that estimates **part cost, tool cost and machine size** straight
from a 3D CAD model (STEP file).
It covers four manufacturing routes:

| Part type | Process examples |
|---|---|
| Plastic | Injection moulding |
| Die casting | High-pressure die casting (Al, Zn, Mg) |
| Foundry | Sand / gravity / low-pressure casting (iron, steel, Al) |
| Sheet metal | Blanking, piercing, bending, drawing |

It's built in stages. **Stage A** reads the 3D model and works out the geometry and net weight.
**Stage B** turns net weight into gross weight, material yield and raw-material (RM) cost per part.
**Stage C** works out cavities per tool and the number of tools. A **mould / die preview** then sizes the mould and
builds its BOM from the mould & die database.
Later stages build on these numbers to produce the product BOM, tool cost and press tonnage.

**No rates or rules are written in the code.** They all live in two editable data files, which you change on the
**Master data** page (see [Master data](#master-data)).


---

## Stage A: what it does today

Upload a STEP file, choose the part type and enter (or pick) the material density. The page shows:

| Output | How it is calculated |
|---|---|
| **Volume** (cm³, mm³) | Exact solid volume from the CAD kernel (OpenCascade via CadQuery) |
| **Net part weight** (g / kg) | Volume (cm³) × density (g/cm³) |
| **Bounding box L × W × H** (mm) | Tight axis-aligned box around the part. L ≥ W ≥ H |
| **Projected area** (cm²) | "Shadow" area of the part seen along X, Y and Z, with through-holes removed. The largest one is taken as the mould/die opening direction |
| Surface area (cm²) | Extra: useful later for painting, plating and coating cost |
| 3D viewer | Rotate / zoom / pan the part, with its bounding box shown |

**Assumptions**
- CAD units are **millimetres** (the STEP default in almost all CAD systems).
- The bounding box follows the model's own X/Y/Z axes. Export the part in its moulding/casting orientation for best results.
- If a STEP file has several solid bodies, they are added together.

Material presets (PP, ABS, PA66 GF30, ADC12, Zamak, grey iron, CRCA, SS304 and more) fill in typical densities.
Always check against your material datasheet.

---

## Stage B: gross weight & RM cost

After a part is analysed, a **Stage B** section appears under the results. It shows only the inputs that apply to the
chosen part type, with typical starting values filled in, and recalculates as you type.

| Part type | Inputs (default) | Gross weight |
|---|---|---|
| Plastic | Runner weight % of net (15 %), purge / start-up loss (2 %) | Net × (1 + runner %) |
| Die casting | Casting yield % (60 %): biscuit, runners, overflows. Melt loss (3 %) | Net ÷ yield % |
| Foundry | Casting yield % (65 %): gating, risers. Melt loss (4 %) | Net ÷ yield % |
| Sheet metal | Thickness and flat blank L × W (estimated from the 3D model), sheet size (2500 × 1250), gap between blanks (5 mm), sheet edge trim (5 mm) | Sheet weight ÷ blanks per sheet |

All part types also take a **material rate per kg**, a **scrap / regrind / returns value per kg** and a currency (INR by default).

**Formulas**
- Returns / scrap = gross − net (runners, biscuit, overflows, risers, or the sheet skeleton and punched holes)
- Material used per part = gross × (1 + process or melt loss %). For sheet metal it equals gross.
- Material yield = net ÷ material used
- RM cost = material used (kg) × material rate
- Scrap credit = returns / scrap (kg) × scrap value
- **Net RM cost per part = RM cost − scrap credit**

**Sheet metal nesting.** Blanks are laid out in a straight grid on the sheet, and both blank orientations are tried.
The page shows blanks per sheet (e.g. 45 × 10 = 450) and the % of the sheet that ends up in parts.
Thickness is found from the most common distance between opposite flat faces of the model. The blank is the part's
L × W for a flat part. For a bent part, the developed length is (volume ÷ thickness) ÷ width.
Both are estimates, so check them against the drawing or flat pattern, especially for parts with large cut-outs or deep draws.

---

## Stage C: cavities & number of tools

The Stage C section appears after Stage B. The defaults come from master data, and the annual volume and shift pattern
are kept when you analyse the next part.

| Step | Formula |
|---|---|
| Planned hours / year | working days × shifts × hours per shift |
| Productive hours / year | planned hours × OEE. **OEE is applied once, here** |
| Cavities needed | (annual volume ÷ productive hours) × cycle time (s) ÷ 3600 |
| Fit on plate | straight-grid layout of the part footprint (across the parting plane) on the mould plate / die / flask / press bed, with spacing |
| Cavities per tool | needed, rounded up to an allowed count (`standard_cavities`, e.g. 1, 2, 4, 6, 8…), capped by what fits and by `max_cavities` |
| Tools in parallel | ceil(cavities needed ÷ cavities per tool) |
| Tools over programme | max(tools in parallel, ceil(shots over programme ÷ tool life)) |
| Machine utilisation | (shots × cycle ÷ 3600 ÷ OEE) ÷ (planned hours × tools in parallel) |

- **Plastic cycle time** is estimated from the main wall thickness: `cycle_base_s + cooling_factor × wall²` (8 s + 2 × wall² by default). Replace it with your own process or mould-flow figure.
- **Sheet metal:** a "cavity" is a part per stroke, the layout uses the Stage B flat blank, and total dies = die sets × operations.

A test checks that OEE is used only once. Halving OEE must exactly double the cavities needed, and
utilisation × machines × cavities must equal cavities needed.

---

## Mould / die size & BOM (preview)

For plastic and die-cast parts, a section under Stage C sizes the mould and builds its BOM. It uses only the
**mould & die database**:

1. **Insert per cavity** = part L × W + 2 × `insert_wall_mm`. Height per half = part height ÷ 2 + `insert_backing_mm`.
2. **Cavity layout:** every rows × columns grid is tried. The winner needs the smallest standard mould base; ties go to
   fewer empty positions, then the squarer layout. Pocket = inserts + `insert_gap_mm` between them.
3. **Mould base** = the smallest base in *Mould bases* whose insert pocket takes the inserts (either way round). A warning
   shows if the insert is deeper than the A/B plate allows.
4. **BOM:** every *BOM element* row for that part type is evaluated with its rules:
   `line cost = quantity × (bought-out cost + weight × material rate/kg + hours × process rate/h)`.

You can set a hot runner, slides, lifters and small inserts per cavity. Lines that still use placeholder values are
marked • and counted in a yellow warning.

---

## Master data

Open **Master data** in the page header. It has two data sets, each with a table editor, **Save**, **Undo**,
**Download Excel** and **Upload Excel**. Every save or upload is checked first. A bad value is rejected with its sheet
and row number (e.g. *"Parameters row 18, cycle_time_s: 'abc' is not a number"*), the row is highlighted, and the file
stays unchanged.

### 1. General master data: `master_data/master_data.xlsx`
| Sheet | Contents |
|---|---|
| Parameters | All Stage B / C defaults and rules per part type (`all` = every type): runner %, yields, melt/process loss, sheet size, working days, shifts, OEE, cycle time, max cavities, plate size, spacing, tool life, `standard_cavities`, plastic cycle rule, and the Stage F tonnage factors (cavity pressure, safety factors) |
| Materials | Part materials with density, RM rate/kg and scrap value/kg. These are the presets on the estimator, and choosing one fills its rates in Stage B |

You can also edit this file directly in Excel while the server runs. It is re-read when it changes.
Write lists like `standard_cavities` as `1, 2, 4, 8`, with spaces, so Excel keeps them as text.

### 2. Costing database: `master_data/costing_db.sqlite`
One SQLite file holds the mould & die tables, the rate engine set-up and the country rate library. The Master data
page edits the first two; country rates are edited on the **Rates** page (see below).

#### Mould & die tables
| Table | Contents |
|---|---|
| Mould bases | Standard sizes: L × W, insert pocket L × W, A / B / clamp / support / spacer / ejector plate thicknesses, stack height, weight, cost |
| Tool materials | Core/cavity and plate steels (P20, 2738, S136, H13, 1.2343 ESR, C45, D2, BeCu): density, rate/kg, hardness |
| BOM elements | Guide pillars, bushes, ejector/return pins, sprue bush, locating ring, hot runner, cooling, slides, lifters, inserts, machining, design, assembly, tryout. Each has a **category** (made / bought_out / process), a **material** and **process**, and four **rules**: quantity, bought-out cost each, weight each (kg) and hours each |
| Process rates | CNC milling, EDM, wire cut, grinding, deep-hole drilling, polishing, heat treatment, fitting & assembly, design, tryout: rate/hour |
| Sizing rules | `insert_wall_mm`, `insert_gap_mm`, `insert_backing_mm`, `plate_floor_mm` per part type |

**Every seeded row is an EXAMPLE placeholder** (`is_example` = yes, shaded yellow in Excel). Replace them with your
catalogue, supplier and toolroom values. Editing a row on the page clears its Example flag, and the *Examples only*
filter shows what is still left to replace.

**Rules** are one-line formulas, for example `max(4, ceil(cavities * projected_area_cm2 / 8))` or
`cavities if hot_runner else 0`. Allowed: numbers, + − * / ( ), comparisons, `a if condition else b`, `and / or / not`,
`ceil, floor, round, min, max, abs, sqrt`, and these variables: `cavities`, `layout_rows`, `layout_cols`, `part_l`,
`part_w`, `part_h`, `projected_area_cm2`, `part_weight_g`, `insert_each_l`, `insert_each_w`, `insert_half_h`,
`pocket_l`, `pocket_w`, `base_l`, `base_w`, `base_stack_h`, `base_weight_kg`, `hot_runner`, `slides_per_cavity`,
`lifters_per_cavity`, `inserts_per_cavity`, `density`. The exported Excel file has a *Formula help* sheet listing them.
Rules are checked when you save, and they cannot run any other code.

#### Countries, machines & formulas (the rate engine's logic)
| Table | Contents |
|---|---|
| Countries | Code, name and currency. India, China, Korea, Japan, Taiwan, Thailand, Vietnam, Germany and USA to start with; add more as rows |
| Machines | Technical data only: connected kW, power load factor, floor area, life, residual %, maintenance % per year, plus tonnage and tie-bar/bed size for presses. **Prices and consumables are country rates** |
| Labour grades | Operator, skilled machinist, toolmaker, designer |
| Cost formulas | Every step of the MHR and the labour rate as a formula, e.g. `depreciation = depreciation_per_year / annual_hours`. Exactly one row per scope is the final result |
| Formula inputs | Where each variable comes from: a country rate (category + item; `{machine}` / `{grade}` are filled in) or a machine field. Money inputs are converted to the producing country's currency with that month's forex rates |

Change a formula here and every MHR changes with it. Saves are checked first: unknown names, a formula that depends on
itself, or a missing final result are refused with the row number.

**Back up your data:** both files are in the `master_data/` folder. Copy that folder, or use *Download Excel*, before
big changes.

---

## Rates page: country rate library, MHR & labour rates

Open **Rates** in the header. Pick the **producing country** and the **costing month**.

- **Machine & labour rates:** the MHR of every machine and the labour rate of every skill level, in the country's
  currency and in INR. **Click any number** to open the traceability panel, which shows:
  - the formula, and each input with its value and source (rate version, month, approval, source URL, EXAMPLE flag)
  - the full breakup with each component's share
  - the list of rate versions used, so a report can be reproduced later

  Click an input to drill down further (MHR → Power → Electricity rate → its history and trend chart).
- **Rate library:** the approved value of every rate for the chosen month. A rate can be:
  - **New version:** saved as a Draft for review, or with **Save & approve** in one step
  - downloaded with its full history to Excel
  - **imported from Excel**, where every row becomes a Draft and nothing existing is changed
- **Rate review:** every Draft or Reviewed version next to the approved value it would replace. It shows:
  - % change, highlighted above your threshold (5 % by default)
  - source link and comment

  You can edit the proposed value, then Approve, Mark reviewed or Reject, one by one or in bulk.
  Your name for approvals is asked once and remembered.

Rules: approved versions are never changed or deleted, and costing uses only the latest **approved** version up to the
costing month. A missing rate shows a clear message on that row and does not break the rest of the page.

**MHR** = depreciation + interest + power + maintenance + floor space + consumables + overhead (per hour), with:
- annual hours = working days × shifts × hours per shift × utilisation %
- depreciation = (price − residual) ÷ life ÷ annual hours
- interest = (price + residual) ÷ 2 × interest % ÷ annual hours
- power = kW × load factor × electricity rate
- floor space = m² × rent per m² per month × 12 ÷ annual hours
- overhead = overhead % × machine cost subtotal

**Labour rate** = (monthly salary × 12 × (1 + employer %)) ÷ (working days × hours per shift) × (1 + supervision %) ÷ productive %.

All seeded country rates, machine prices and machine data are **EXAMPLE values** (approved as "Example seed", 2026-10).
Use *Examples only* in the Rate library to work through them.

---

## Full roadmap

Stages A–C are done. Next come five requirement sets, built one PR at a time:
**A** sheet-metal tools, **B** tool / mould / die cost, **C** country rate library,
**D** country comparison for parts, and **E** dynamic rate library with monthly update and approval.

### Ground rules for everything that follows
- **No hard-coded values.** Every number comes from master data or from a formula stored in master data.
- **Traceability.** Every value on screen can be clicked. It opens a panel showing:
  - the formula
  - every input and where it came from (master-data sheet/row, rate version and month, your input, or calculated)
  - approval status and history, and the full breakup.
- **Only approved rates are used in costing.** Every result records which rate versions it used, so old reports stay reproducible.
- **Example values** are clearly marked until you replace them with market rates.
- All results are shown in **INR and in the producing country's currency**.

### Decisions taken (from your answers)
| Topic | Decision |
|---|---|
| Users | Runs on your PC for one user, no login. Approvals record a name that is asked once and remembered. |
| MHR vs labour | **Separate.** MHR = machine cost only. Process cost = hours × (MHR + operators × labour rate of the skill level). |
| Depreciation / interest | Straight line: (price − residual) ÷ life years. Interest on average investment: (price + residual) ÷ 2 × interest %. |
| Hours basis | Fixed machine costs are spread over working days × shifts × hours per shift × utilisation %. |
| Overhead | Overhead % × machine cost subtotal (depreciation + interest + power + maintenance + space + consumables). |
| Labour rate | Monthly salary/CTC × 12 × (1 + employer extra-cost %) ÷ paid hours per year × (1 + supervision %) ÷ productive-time %. Employer % is per country (0 % if the CTC is all-inclusive). |
| Rate versions | One version per **month**. A costing "as of" a month uses the latest **approved** version up to that month. |
| Your own edits | Saved as a new version (old values never overwritten). By default it is a Draft for review; **Save & approve** approves it in one step. |
| Data home | **Costing database** (SQLite, `master_data/costing_db.sqlite`) with Excel import/export and editing in the app. |

### PR plan
| PR | Contents | Requirements |
|---|---|---|
| **4 (this)** | This roadmap. **Versioned country rate library**: history, Draft → Reviewed → Approved, Rate review page, approved-only lookup. Countries and forex. Machines with price per country. **MHR & labour-rate engine** with all formulas in data. **Traceability panel.** | B3, B5, B6, C1–C3, C5, E1, E4–E6 |
| 5 | Material rates by grade and process rates by country (₹/kg, ₹/h, ₹/mm, ₹/cm², ₹/m², per unit). **Tool cost engine:** process list (raw-material cutting, CNC, wire cut/EDM, grinding, polishing, heat treatment, surface treatment, assembly, try-out); process time from logic (volume removed, area, feature count…); machine, MHR, labour skill and operators per process; trial, design, overhead & profit, packing & transport, warranty/spares. The mould BOM becomes fully traced. **Tool cost sheet** exported to Excel and PDF. | B1, B2, B4, B7, C2 |
| 6 | **Country comparison** for tools and parts side by side: RM, process, tool amortisation, overhead, rejection, profit, packing. Ex-works in local currency, USD and INR. **Landed cost in India:** freight, insurance, BCD, SWS, IGST (credit shown separately), clearance & port charges, inland transport. Duty per HS code and country incl. FTA rates. Forex sensitivity (e.g. USD ±5 %). Stacked bar chart with the cheapest country highlighted. Excel/PDF export. Traceability added to Stages A–C. | C4, D1–D7 |
| 7 | **Monthly auto-update:** a GitHub Actions job on the 1st of each month plus a **Fetch now** button. It uses only free, official, legally usable sources (list below). Index-based proposals for rates with no free source: new = last approved × (index now ÷ index at approval), with the formula editable. New values arrive as Drafts with change % and a threshold highlight. A failed fetch keeps the last approved value and shows a warning. Trend chart per rate. | E1–E3, E7 |
| 8 | **Sheet-metal tools:** multi-stage or progressive. Operation sequence auto-suggested from part features (editable). Per stage: weight incl. scrap removed, cutting / forming / drawing force and tonnage (formula shown), press selected from your machine list. Drawings: blank / flat pattern as DXF + dimensioned PDF, per-stage CAD upload or simplified sketch, and one PDF pack. Progressive strip layout: pitch, strip width, bridge/web, stations, pilots, utilisation %, as DXF + PDF. | A1–A5 |
| later | Stage D product BOM (multi-part assemblies) and the full should-cost report and dashboard. | |

### Free official data sources planned for the monthly update (PR 7)
Only sources that publish free data for reuse are used, and nothing is scraped from sites that forbid it. Each licence
is checked again before its fetcher is switched on. Until then every rate stays a manually approved value.

| Data | Source | URL | Frequency | Licence / terms |
|---|---|---|---|---|
| Forex (EUR base: USD, INR, CNY, JPY, KRW, THB…) | European Central Bank euro reference rates | https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html | Daily (working days) | Free reuse with source attribution (to confirm) |
| Forex INR reference rate | Financial Benchmarks India (FBIL) | https://www.fbil.org.in | Daily | Terms to confirm |
| Forex TWD, VND | Central Bank of the Republic of China (Taiwan); State Bank of Vietnam | https://www.cbc.gov.tw · https://www.sbv.gov.vn | Daily | Terms to confirm |
| Metal commodity prices (aluminium, copper, nickel, zinc, iron ore…) | World Bank Commodity Price Data ("Pink Sheet") | https://www.worldbank.org/en/research/commodity-markets | Monthly | CC BY 4.0 (to confirm) |
| Labour earnings by occupation and country | ILO ILOSTAT | https://ilostat.ilo.org | Annual | Free reuse with attribution (to confirm) |
| Inflation / producer price indices (for index-based proposals) | World Bank World Development Indicators; national statistics offices | https://data.worldbank.org | Annual / monthly | CC BY 4.0 for WDI (to confirm) |
| Electricity, Germany (non-household) | Eurostat | https://ec.europa.eu/eurostat | Half-yearly | Free reuse with attribution (to confirm) |
| Electricity, USA (industrial) | US Energy Information Administration | https://www.eia.gov/electricity/data.php | Monthly | US government public data (to confirm) |
| Electricity, other countries | National regulators / utility tariff orders (e.g. Indian state commissions, KEPCO, TEPCO, Taipower, EGAT, EVN) | per country | When tariffs change | Manual entry unless an open API with clear terms exists |
| Steel grades, MHR, process rates, freight, duty | No free official API | — | — | Index-based proposals or manual entry, always approved by you |

### Key formulas
- **MHR** = depreciation + interest + power + maintenance + floor space + consumables + overhead, all per hour. The formula for each component is stored in master data.
- **Labour rate** = salary × 12 × (1 + employer %) ÷ paid hours/yr × (1 + supervision %) ÷ productive %.
- **Clamping force (plastic / die casting)**: `F (t) = projected area (cm²) × cavities × cavity pressure (bar) × safety factor ÷ 1000`.
- **Sheet-metal cutting force**: `F (t) = cut perimeter (mm) × thickness (mm) × shear strength (N/mm²) ÷ 9810`.
- **Gross weight** = net weight ÷ material yield.

---

## Look & feel: Design to Cost theme

Every page uses the company theme in `theme/`, following `theme/THEME.md`:

- `theme/dtc-theme.css` holds the colours (navy `#152238` text, blue `#1f5fa8` primary, orange `#e07b1f` as a small
  accent), the Segoe UI font, the header, buttons, cards, form fields and costing tables.
- `theme/logo.png` is the DC logo, shown in the header and used as the browser-tab icon.
- Header: logo, **Design to Cost**, tagline *Part Cost Estimator*, and links Estimate · Master data · Help.
  Footer: *© Design to Cost*.
- Costing tables: dark navy sticky header and alternating light-blue rows. Cells you type into are yellow, calculated
  cells are grey italic, and totals rows are bold with a dark line above.
- `frontend/style.css`, `master-data.css` and `help.css` hold only page layout and use the theme's colour variables.
  To change a colour or font, edit `theme/dtc-theme.css`.
- The Excel exports have "Design to Cost" as their title and author, and use the theme's header and input-cell colours.

---

## How to run it on your computer (step by step)

You need **Python 3.10 or newer**. Check it by typing `python --version` in a terminal.
On Windows, use *Command Prompt* or *PowerShell*.

1. **Download the code**: on the GitHub page click **Code → Download ZIP** and unzip it.
   Or, if you have Git installed: `git clone https://github.com/amitkumarshukla1210/Tool_part_cost_estimator.git`
2. **Open a terminal in the project folder**: `cd Tool_part_cost_estimator`
3. **Create a private Python environment** (this keeps the libraries for this project separate):
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS / Linux:
   source .venv/bin/activate
   ```
4. **Install the libraries** (CadQuery is large, about 200 MB, so the first install takes a few minutes):
   ```bash
   pip install -r requirements.txt
   ```
5. **Start the server**:
   ```bash
   uvicorn backend.app.main:app --reload
   ```
6. **Open** http://127.0.0.1:8000 in your browser (the tab shows "Design to Cost — Part Cost Estimator"). Upload a STEP file and click **Analyse part**.
   Sample parts to try are in the `samples/` folder.
7. To stop the server, press `Ctrl + C` in the terminal.

The page needs no internet connection. three.js is included in the project, so it works on restricted factory networks.

### Running the automated tests (optional)
```bash
pip install -r requirements-dev.txt
python -m pytest
```
The tests use sample parts whose volume, weight, box and projected area can be checked by hand.

---

## Project layout

```
backend/app/geometry.py       STEP reading and all geometry calculations (CadQuery)
backend/app/gross_weight.py   Stage B: gross weight, yield, sheet nesting and RM cost
backend/app/capacity.py       Stage C: cavities, tools, tool life, machine hours
backend/app/master_data.py    Reads, checks and saves master_data.xlsx
backend/app/mould_db.py       Mould & die tables in the costing database
backend/app/mould.py          Mould sizing (layout, insert, base) and BOM from the database
backend/app/formula.py        Safe evaluation of the BOM rules and cost formulas
backend/app/costing_db.py     The shared SQLite file (costing_db.sqlite)
backend/app/table_set.py      Editable table sets: validation, Excel import/export
backend/app/costing_setup.py  Countries, machines, labour grades, cost formulas, formula inputs
backend/app/rates.py          Versioned country rate library with approval
backend/app/rate_engine.py    MHR and labour rate per country, fully traced
backend/app/trace.py          Traceable calculations (formula, inputs, sources)
backend/app/main.py           FastAPI web server: all /api endpoints + serves the pages
master_data/                  master_data.xlsx and costing_db.sqlite (your editable data)
frontend/index.html           Estimator page (form + results + 3D viewer)
frontend/app.js               Estimator logic and three.js viewer
frontend/master-data.*        Master data page (editor for both data sets)
frontend/help.*               Help page
frontend/rates.*              Rates page (MHR & labour, rate library, rate review)
frontend/trace.js             Traceability panel used by every page
theme/                        Design to Cost theme: dtc-theme.css, logo.png, THEME.md
frontend/style.css            Page styling
frontend/vendor/three/        three.js r160 (MIT licence), bundled for offline use
samples/                      Sample STEP parts + the script that makes them
tests/                        Automated tests (pytest)
```

### API (for later integration with ERP / PLM / dashboards)
`POST /api/analyze` takes a multipart form with `file` (.step/.stp), `part_type` (`plastic` | `die_casting` | `foundry` | `sheet_metal`) and `density` (g/cm³).
It returns JSON with `metrics` (all the numbers above) and `mesh` (triangles for the viewer).
`POST /api/gross-weight` takes JSON with `part_type`, `net_weight_g`, `density_g_cm3`, the rates, and the
Stage B inputs from the table above (any you leave out use the defaults). It returns gross weight, yield, nesting and
cost. `GET /api/gross-weight/defaults` lists the default values.
`POST /api/capacity` (Stage C) and `POST /api/mould/estimate` (mould size & BOM) work the same way.
`GET/PUT /api/master-data` and `GET/PUT /api/mould-db` read and save the data sets.
`…/download` and `…/upload` move them to and from Excel.
Interactive API docs are at http://127.0.0.1:8000/docs while the server runs.

---

© Design to Cost
