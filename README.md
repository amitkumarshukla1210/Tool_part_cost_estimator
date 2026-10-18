# Tool & Part Cost Estimator

A web tool that estimates **part cost, tool cost and machine size** straight from a 3D CAD model (STEP file).
It covers four manufacturing routes:

| Part type | Process examples |
|---|---|
| Plastic | Injection moulding |
| Die casting | High-pressure die casting (Al, Zn, Mg) |
| Foundry | Sand / gravity / low-pressure casting (iron, steel, Al) |
| Sheet metal | Blanking, piercing, bending, drawing |

It's built in stages. **Stage A** reads the 3D model and works out the geometry and net weight.
**Stage B** turns net weight into gross weight, material yield and raw-material (RM) cost per part.
Later stages build on these numbers to produce cavities, BOM, tool cost and press tonnage.

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

## Full roadmap

| Stage | Adds | Main inputs | Main outputs |
|---|---|---|---|
| **A ✅** | Geometry & net weight | STEP file, part type, density | Volume, net weight, bounding box, projected area |
| **B ✅** | Gross weight & RM cost | Runner/feeder/overflow % (plastic, die casting), gating & riser yield (foundry), blank nesting and scrap (sheet metal) | Gross (shot/pour/blank) weight, material yield %, raw-material cost per part (from ₹/kg or $/kg) |
| **C** | Number of cavities / tools | Annual volume, working days & shifts, cycle time, OEE, machine platen / bed size | Recommended cavities per tool, number of tools (or dies) needed, tool life check |
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
6. **Open** http://127.0.0.1:8000 in your browser. Upload a STEP file and click **Analyse part**.
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
backend/app/main.py           FastAPI web server: /api/analyze and /api/gross-weight + serves the page
frontend/index.html           Web page (form + results + 3D viewer)
frontend/app.js               Page logic and three.js viewer
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
Interactive API docs are at http://127.0.0.1:8000/docs while the server runs.
