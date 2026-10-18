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
| Machines | Machines with tonnage, tie-bar / bed size and MHR, for the tool-cost and tonnage stages |

You can also edit this file directly in Excel while the server runs. It is re-read when it changes.
Write lists like `standard_cavities` as `1, 2, 4, 8`, with spaces, so Excel keeps them as text.

### 2. Mould & die database: `master_data/mould_db.sqlite`
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

**Back up your data:** both files are in the `master_data/` folder. Copy that folder, or use *Download Excel*, before
big changes.

---

## Full roadmap

| Stage | Adds | Main inputs | Main outputs |
|---|---|---|---|
| **A ✅** | Geometry & net weight | STEP file, part type, density | Volume, net weight, bounding box, projected area |
| **B ✅** | Gross weight & RM cost | Runner/feeder/overflow % (plastic, die casting), gating & riser yield (foundry), blank nesting and scrap (sheet metal) | Gross (shot/pour/blank) weight, material yield %, raw-material cost per part (from ₹/kg or $/kg) |
| **C ✅** | Number of cavities / tools | Annual volume, working days & shifts, cycle time, OEE, machine platen / bed size | Recommended cavities per tool, number of tools (or dies) needed, tool life check |
| **D** | Bill of Materials (BOM) | Multi-part assemblies (STEP with several bodies or several files), bought-out items | Structured BOM with weight and cost for each line, roll-up to product cost |
| **E** | Tool cost | Cavities, part size, complexity (slides, lifters, cores), tool steel grade, region rate | Mould / die / pattern / press-tool cost estimate and cost per part (amortised over volume) |
| **F** | Machine / press tonnage | Projected area × cavities, cavity pressure (plastic ~300–600 bar, die casting ~400–1000 bar), shear length × thickness × shear strength (sheet metal) | Clamping force / press tonnage, suggested machine class, machine-hour rate |
| **G** | Should-cost report | All the above + conversion cost, overheads, margin | Part should-cost breakdown, export to Excel/PDF, dashboard for comparing suppliers |

### Key formulas planned for later stages
- **Clamping force (plastic / die casting)**: `F (tonnes) = projected area (cm²) × number of cavities × cavity pressure (bar) × safety factor / 1000`. The safety factor is usually 1.1–1.2.
- **Sheet-metal blanking force**: `F (tonnes) = cut perimeter (mm) × thickness (mm) × shear strength (N/mm²) / 9810`
- **Gross weight**: `net weight / material yield`
- **Cavities**: limited by the smallest of: volume needed, machine platen size, shot capacity and tool budget.

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
backend/app/mould_db.py       Mould & die SQLite database: tables, checks, Excel import/export
backend/app/mould.py          Mould sizing (layout, insert, base) and BOM from the database
backend/app/formula.py        Safe evaluation of the BOM rules
backend/app/main.py           FastAPI web server: all /api endpoints + serves the pages
master_data/                  master_data.xlsx and mould_db.sqlite (your editable data)
frontend/index.html           Estimator page (form + results + 3D viewer)
frontend/app.js               Estimator logic and three.js viewer
frontend/master-data.*        Master data page (editor for both data sets)
frontend/help.*               Help page
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
