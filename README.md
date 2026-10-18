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
**Stage C** works out cavities per tool and the number of tools. The **tool cost engine** (roadmap stage 4) then sizes the
mould or die, builds its BOM and prices it process by process with the MHR and labour rate of the tool country.
Later stages build on these numbers to produce the product BOM, part cost and press tonnage.

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

All part types also use a **material rate per kg** and a **scrap / regrind / returns value per kg**. Both are **approved rates of the
producing country** from the rate library (categories `material` and `material_scrap`, item = the material name), for the costing month.
The page has a *Producing country* and a *Costing month* box; the cost is shown in that country's currency (and in INR). Type a
rate only to replace the library rate; it is then traced as your input. Nothing is hard-coded: the steps below are rows in
**Master data → Countries, machines & formulas** (scopes `rm_plastic`, `rm_die_casting`, `rm_foundry`, `rm_sheet_metal`) and every
result on the page is clickable for its formula, inputs and sources. Only the sheet nesting search is done in code.

**Formulas**
- (These are the default formulas in master data; change a row there and every RM cost follows.)
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

## Tool cost: moulds and dies (roadmap stage 4)

For plastic moulds and die-casting dies, the section under Stage C on the Estimate page, and the **Tool cost** block of
every registered part, work out what the tool costs, process by process. Nothing is typed into the code: rules, machines,
formulas and rates all come from master data and the approved rate library of the **tool country**.

1. **Mould size** (mould & die database):
   - **Insert per cavity** = part L × W + 2 × `insert_wall_mm`. Height per half = part height ÷ 2 + `insert_backing_mm`.
   - **Cavity layout:** every rows × columns grid is tried. The winner needs the smallest standard mould base; ties go to
     fewer empty positions, then the squarer layout. Pocket = inserts + `insert_gap_mm` between them.
   - **Mould base** = the smallest base in *Mould bases* whose insert pocket takes the inserts (either way round). A warning
     shows if the insert is deeper than the A/B plate allows.
2. **BOM:** every *BOM element* row of the part type is evaluated with its rules (quantity, catalogue price each, steel weight
   each, hours each, amount each). Hour rules use the part's size, volume, surface area and the **Process time parameters**
   (removal rate in cm³/h, finishing and EDM rate in cm²/h, set-up hours, polished share …), for example
   CNC hours = `cnc_setup_h + part_box_cm3 / 2 / cnc_rough_cm3_per_h + part_surface_cm2 / 2 / cnc_finish_cm2_per_h`.
3. **Each line is priced** with the tool country's approved rates:

   | Part of a line | Cost |
   |---|---|
   | Steel | quantity × weight × steel rate (`tool_material`) |
   | Mould base, standard parts | quantity × catalogue price. Prices are kept in INR in master data and converted with that month's forex |
   | Machine hours (*Tool processes*: `machine_hour`) | hours × (**MHR** of the machine + operators × **labour rate** of their grade) |
   | Labour hours (`labour_hour`, e.g. design) | hours × designers × designer labour rate |
   | Per-unit processes (`unit`) | amount × rate per kg / cm² / mm / m², at least the **minimum charge per job** (cutting, heat treatment, nitriding, texture, …) |

   *Tool processes* (mould & die database) names, for each process, how it is priced, its machine, the labour grade and
   the operators per machine. Operators can be a fraction: 0.5 means one operator runs two machines. The MHR and labour
   rate are the rate engine's own traced results, so every hour opens to depreciation, interest, power, maintenance,
   floor space, consumables, overhead and labour.
4. **Try-out:** the clamp force (formula scope `tool_clamp`: projected area × cavities × cavity pressure × safety factor ÷ 1000)
   picks the **smallest machine** of the process named in Parameters → `trial_machine_process` whose tonnage takes it.
   Trial cost = trials × hours per trial × (its MHR + try-out crew) + trials × shots × shot weight × part material rate.
5. **Tool cost per tool** (formula scope `tool`, all editable):
   - manufacturing cost = steel + mould base & standard parts + processes + design + try-out
   - \+ toolmaker overhead % and profit % (on cost + overhead)
   - \+ packing % and warranty / spares % of the tool price (warranty can be switched off per tool)
   - \+ transport = tool weight × transport rate per kg
   - **Tool CAPEX** = tool cost × tools over the programme (Stage C).

   Overhead, profit, packing and warranty % are per-country library rates (category `tool_commercial`, seeded as EXAMPLE values).

**Tool country.** Each part has a *tool country*. Blank means its producing country. A mould for an Indian part can be costed
with China's rates, for example. Results are shown in that country's currency and in INR.

**On the part register.** A part you make by moulding or die casting gets a numbered **tool cost version**, just like the RM cost:
- **Cavities** follow Stage C, using the part's annual volume. Blank means Σ variant annual volume × quantity in that variant.
- **Tools over the programme** come from Stage C (capacity and tool life).
- In **Tool features and tool country** you can type over cavities, hot runner, slides, lifters, small inserts and warranty.
- A new version is made when the revision, material, process, tool country, month, features, volume or programme life change.
- Newer approved rates never change a stored version. The part says *Newer approved rates exist*: recalculate the part,
  or use **Recalculate tools** on the Dashboard for the whole project.
- The Parts list has a *Tool cost (INR)* column, filters (*Tool cost from / to*, *No tool cost yet*) and a sort.
- The **Dashboard** shows the tool & mould CAPEX against the CAPEX budget.
- The **tool cost sheet** (Excel: Summary, Cost build-up, BOM & processes, Steps, Inputs, Rates used, Example values; and PDF) is on
  the part and on the Estimate page.

Sheet-metal dies come with stages 9 and 10, and foundry patterns later. Those parts say so instead of showing a cost.

**Example warning.** Every tool cost shown carries the red **"Uses example rates – not for negotiation"** warning while any
rate **or** master-data row it uses (machine, BOM element, tool process, time parameter, mould base, sizing rule) is still an
EXAMPLE. The warning says how many of each are left. It is on the Estimate page, the part panel, the Parts list, the
Dashboard, the first row of every sheet of the Excel exports, and a red box on the PDFs.

---

## Replace example values (roadmap stage 4b)

**Master data → Replace example values** (`/master-data/examples`) is your checklist for getting rid of every EXAMPLE value,
step by step:

- **Tiles at the top:** example rates left (of all approved rates), how many of them a stored RM or tool cost uses, example
  master-data rows left, and the % replaced so far.
- **Rates in the rate library, by category** (part materials, scrap values, tool steels, process rates per hour / per unit,
  minimum charges, machine prices, consumables, salaries, electricity, rent, interest, hours, overhead, profit, toolmaker terms,
  forex): how many are still EXAMPLE, of how many, a progress bar and the count per country. Click a category for its list: item,
  country, current value, month and *used by* (parts whose latest stored cost uses it; those come first).
  - **Replace:** type the real value. It is saved as a new **approved** version, and the old version is kept.
  - **Keep:** the example value is right; it is approved again as a real value.
  - You need your approver name once (asked on the page).
- **Master-data rows, by table** (BOM elements, mould bases, machines, time parameters, tool processes, process rates, tool
  materials, country index, sizing rules, insert rules and materials). Tables with one value (sizing rules, time parameters,
  mould base cost, densities, insert rules) are replaced right there. **Edit** opens the others in the Master data editor on
  that sheet with *Examples only* ticked. **Keep** clears the row's Example flag. Every save goes through the table's normal checks.
- Filter by country, search, or show only the rates used in stored costs. **Export checklist (Excel)** has Summary, Example
  rates and Example rows sheets.

Stored costs never change by themselves: recalculate them (part panel or Dashboard) to use the replaced values. The
*"Uses example rates – not for negotiation"* warning goes away once every value a cost uses is replaced.

---

## Master data

Open **Master data** in the page header. It has two data sets, each with a table editor, **Save**, **Undo**,
**Download Excel** and **Upload Excel**. Every save or upload is checked first. A bad value is rejected with its sheet
and row number (e.g. *"Parameters row 18, cycle_time_s: 'abc' is not a number"*), the row is highlighted, and the file
stays unchanged.

### 1. General master data: `master_data/master_data.xlsx`
| Sheet | Contents |
|---|---|
| Parameters | All Stage B / C defaults and rules per part type (`all` = every type): runner %, yields, melt/process loss, sheet size, working days, shifts, OEE, cycle time, max cavities, plate size, spacing, tool life, `standard_cavities`, plastic cycle rule, the tonnage factors (cavity pressure, safety factors) and the try-out (`trial_machine_process`, `trials`, `trial_hours_each`, `trial_shots_each`) |
| Materials | Part materials with their density and part type (family). These are the presets on the estimator and the choices on the register. **Material rates are approved rates in the rate library** (see Part RM cost) |

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
| BOM elements | Guide pillars, bushes, ejector/return pins, sprue bush, locating ring, hot runner, cooling, slides, lifters, inserts, steel cutting, machining, grinding, polishing, heat treatment, nitriding, design, assembly. Each has a **category** (made / bought_out / process), a **material** and a **tool process**, and five **rules**: quantity, bought-out cost each (INR), weight each (kg), hours each and amount each (in the process unit, e.g. kg for heat treatment) |
| Process rates | CNC milling, EDM, wire cut, grinding, deep-hole drilling, polishing, heat treatment, fitting & assembly, design, tryout: India rate/hour (the all-in rates of the library grid) |
| Sizing rules | `insert_wall_mm`, `insert_gap_mm`, `insert_backing_mm`, `plate_floor_mm` per part type |
| Tool processes | How each tool process is priced: `machine_hour` (machine + labour grade + operators), `labour_hour` (design) or `unit` (a *Process rates by unit* row), and its cost group (cutting, machining, polishing, treatment, assembly, design, trial). The `trial` row's machine is `by tonnage` |
| Process time parameters | Per part type: CNC set-up and removal rates, EDM share and rate, grinding and polishing rates, steel density. The BOM rules use them by name |

**Every seeded row is an EXAMPLE placeholder** (`is_example` = yes, shaded yellow in Excel). Replace them with your
catalogue, supplier and toolroom values. Editing a row on the page clears its Example flag, and the *Examples only*
filter shows what is still left to replace.

**Rules** are one-line formulas, for example `max(4, ceil(cavities * projected_area_cm2 / 8))` or
`cavities if hot_runner else 0`. Allowed: numbers, + − * / ( ), comparisons, `a if condition else b`, `and / or / not`,
`ceil, floor, round, min, max, abs, sqrt`, and these variables: `cavities`, `layout_rows`, `layout_cols`, `part_l`,
`part_w`, `part_h`, `projected_area_cm2`, `part_weight_g`, `part_volume_cm3`, `part_surface_cm2`, `part_box_cm3`,
`insert_each_l`, `insert_each_w`, `insert_half_h`, `pocket_l`, `pocket_w`, `base_l`, `base_w`, `base_stack_h`,
`base_weight_kg`, `hot_runner`, `slides_per_cavity`, `lifters_per_cavity`, `inserts_per_cavity`, `density`, plus every
name in *Process time parameters* of the part type. The exported Excel file has a *Formula help* sheet listing them.
Rules are checked when you save, and they cannot run any other code.

#### Countries, machines & formulas (the rate engine's logic)
| Table | Contents |
|---|---|
| Countries | Code, name and currency. India, China, Korea, Japan, Taiwan, Thailand, Vietnam, Germany and USA to start with; add more as rows |
| Machines | Technical data only: connected kW, power load factor, floor area, life, residual %, maintenance % per year, plus tonnage and tie-bar/bed size for presses. **Prices and consumables are country rates** |
| Labour grades | Operator, skilled machinist, toolmaker, designer |
| Cost formulas | Every step of the MHR, labour rate, RM cost and tool cost as a formula, e.g. `depreciation = depreciation_per_year / annual_hours`. Exactly one row per scope is the final result. Tool scopes: `tool_clamp` (clamp force for the try-out machine) and `tool` (try-out, overhead, profit, packing, transport, warranty, tool cost, CAPEX) |
| Formula inputs | Where each variable comes from: a country rate (category + item; `{machine}` / `{grade}` / `{material}` are filled in), a machine field, a Parameters row, a part value (RM) or a tool engine value (`source = tool`: steel, bought-out, process and design cost, tool weight, shot weight, try-out MHR and crew, …). Money inputs are converted to the costing country's currency with that month's forex rates |

Change a formula here and every MHR changes with it. Saves are checked first: unknown names, a formula that depends on
itself, or a missing final result are refused with the row number.

**Back up your data:** both files are in the `master_data/` folder. Copy that folder, or use *Download Excel*, before
big changes.

---

## Part register & project dashboard (roadmap stage 1)

**Dashboard → + New project** (code, name, customer, CAPEX budget) and **+ Variant** (e.g. STD, with target BOM
cost and annual volume). Then bring in the parts on **Import**:

- **3D file (part or assembly):** upload a STEP file. An assembly is split into its parts automatically:
  - The tree shows every part with a thumbnail, its quantity in the parent and its total quantity.
  - Repeated parts (4 identical pins) become **one part with quantity 4**.
  - Parts that only look identical (same volume, area and size, different name) are **flagged as look-alikes** and
    kept separate, for you to decide.
  - Tick the parts to register. For each one, set the code (blank = generated from the pattern in master data, e.g.
    `SCT26-0001`), name, material, process and sourcing (Make / Bought-out / Existing / Not required).
  - The process is **suggested, with its reason** (click *why?*):
    1. **Material first.** Its part type in Master data → Materials sets the family: plastics → moulding,
       ADC12 / aluminium alloys → die casting, cast iron → foundry, steel / aluminium sheet grades → sheet metal.
    2. **Then geometry**, by rules in Part register setup: main wall, how much of the surface is at that constant
       wall, bends, fill ratio, size.
    3. **Then inserts:** moulded-in inserts turn it into *insert moulding* or *insert die casting*.

    Choose the material in the tree and the suggestion updates. It is a proposal, so please check it.
  - **Moulded-in inserts are detected.** A smaller part that is largely enclosed by a bigger one in the same
    assembly (e.g. brass threaded inserts in plastic bosses) is listed under its body for you to confirm. A
    confirmed insert becomes its own part (bought-out by default) linked to the body with its quantity. It is not
    a BOM child, because the body is one moulded part.

  Each part's own STEP file and thumbnail are stored, and the BOM tree is added to the chosen variant.
  Re-importing an unchanged assembly creates no new revisions.
- **Excel bulk upload:** download the template, fill one row per part (code, name, rev, file name, material,
  process, sourcing, volume, programme life, target cost, variant, parent part, quantity, what changed), then upload
  it together with the STEP files or a ZIP. Files are matched by name.
  - Rows without a file are registered as **File missing**.
  - Every row is checked first, so nothing is saved if any row is wrong. The error names the row.
  - Insert rows name their moulded part in `insert_of_part_code`, with `insert_quantity` and the bought-out price
    (`unit_price`, `price_currency`, `price_source`, `price_month`).

**Parts** is the register: search by code, name or material and filter by project, process, status, sourcing, rev,
target cost range or *file missing*, with paging and Excel export. Click a part to:
- edit its details (every change goes into its **history**: old → new, who, when)
- see the current revision's geometry. **Volume**, **net weight** (volume × material density from master data) and
  **projected area** are clickable for their trace.
- see the **suggested process and why**, and use it with one click
- **link moulded-in inserts:** an existing part code, or a new insert part with its material, its own 3D file or a
  simple shape with dimensions (pin, bush / threaded insert, hex nut, strip), and its price, source and month.
  The weight is then shown as **body weight + insert weight = total weight**, each with its full trace.
- set the **bought-out price** of any BOP part (price, currency, source, month, example flag)
- download each revision's STEP file
- **compare two revisions side by side**
- upload a **new revision** (old revisions are kept)
- see where the part is used

The insert-moulding rules for the later stages are already in **Master data → Part register setup → Insert
moulding rules** (all EXAMPLE values):
- loading time, manual and robot
- shuttle / rotary-table share
- pre-heat limit
- vertical machine and robot thresholds
- inserts per shot, which caps the cavities
- locating pin, magnet and pocket costs
- weld-line, stress and insert-shift risk limits
- extra rejection
- insert handling %

The mould concept (stage 5), simulation (stage 6) and part costing (stage 8) will use them.

**Dashboard** shows, per project:
- parts, file missing, open corrections, CAPEX budget and targets
- variants with target BOM cost
- the BOM tree
- parts by status, process and sourcing
- **Export PDF** (project summary) and **Export Excel** (part register)

The RM cost (stage 2) and the tool & mould CAPEX against the budget (stage 4) are on the dashboard; the full BOM cost comes with part costing (stage 8).

**Where your data lives:**
- `data/projects.sqlite` holds projects, parts, revisions, BOM and history.
- The storage folder holds the CAD files and thumbnails, each stored once by checksum. It is `storage/` by default;
  change `storage_folder` in Master data → Part register setup → Register settings, e.g. to a network drive.

Both are **your company data**: they are not committed to GitHub, so back them up. The project tables also run on
PostgreSQL later: set `DATABASE_URL`, e.g. `postgresql+psycopg://user:password@server/dtc`.

---

## Part RM cost on the register (roadmap stage 2)

Every part of the register that you **make** (moulding, die casting, foundry, sheet metal) and that has a material gets a
**raw-material (RM) cost**. It is the Stage B calculation, run on the part's current revision:

1. **Net weight** = CAD volume × material density (body only for an insert-moulded part; inserts are costed in stage 8).
2. **Gross weight, returns, material used, yield, RM cost, scrap credit, net RM cost** from the `rm_<family>` formulas in master data.
3. **Inputs** come from three places, each shown in the trace:
   - the **rate library**: the approved material rate and scrap value of the part's producing country for the costing month;
   - **Master data → Parameters** of the family (runner %, yield %, losses, sheet size, gap, edge);
   - the **3D file**: net weight, sheet thickness and flat blank (estimated; check them against the drawing).

   Type any of them over in the part panel (**RM inputs, country and month**); it is then traced as your input.
4. The result is stored as a numbered **RM cost version** with its full trace and the rate versions it used.

**When a new version is made.** Automatically, when something the result depends on changes: a new revision, the material, process,
sourcing, producing country, costing month, your typed inputs, or the inserts. If nothing changed, no version is made. Versions are
never overwritten.

**New rates do not change old costs.** Approving a newer rate leaves every stored cost as it was. The part then shows *Newer approved
rates exist* with the old and new value of each rate, and you click **Recalculate with latest rates** (the Dashboard has
**Recalculate RM** for a whole project). The same notice appears when you change a formula in master data.

**Who gets an RM cost.** Not assemblies, and not bought-out / existing / not-required parts (those show their bought-out price). Machined
parts say that their RM (bar stock) comes in a later stage. A part without a material, a density, a 3D file or an approved rate shows
exactly what is missing; the weights are still shown, and nothing wrong is stored.

**Where it appears.**
- **Parts:** *Net RM cost (INR)* column, filters *RM cost from / to* and *No RM cost yet*, sort by highest RM cost, and in the part
  panel the full RM block (clickable values, versions, Excel and PDF cost sheet).
- **Dashboard:** *RM cost* per variant = Σ (total quantity × net RM cost) over the BOM, its share of the target BOM cost, and the
  number of parts still without an RM cost. It is labelled **raw material only**: process cost comes in stage 8.
- **Estimate page:** *Open in Estimate* on a part loads its STEP file, material, country and typed inputs without uploading again;
  **Save to part** stores the inputs you changed and makes a new version.
- **Exports:** the **RM cost sheet** of a part (Excel with Summary, Steps, Inputs and Rates used sheets, and PDF) and RM columns in the
  Parts Excel export and in the project PDF.

**Producing country.** Each part has an optional producing country; blank means the default in **Master data → Part register setup
→ Register settings → default_country** (India). Material rates are seeded for India only (EXAMPLE values). Rates for the other countries
are seeded in stage 3 (see below); a part set to a country with a missing rate says which rate is missing.

**Material rates moved.** `rate_per_kg` and `scrap_rate_per_kg` are no longer in the *Materials* sheet. Their values became EXAMPLE
approved rates for India (month 2026-10, approved as "Example seed"). Set your own on the **Rates** page, or import them from Excel. An older
`master_data.xlsx` that still has the two columns can be uploaded; the columns are ignored and the upload tells you so.

---

## Material & process rates by country (roadmap stage 3)

Open **Rates → Material & process rates**. It is a grid of item × country (India, China, Korea, Japan, Taiwan,
Thailand, Vietnam, Germany, USA) for the costing month. Choose what to see, in the country's currency or in INR:

| Group | Items | Charged per |
|---|---|---|
| Part materials, and their scrap value | ABS, PP, PA66 GF30, ADC12, CRCA, SS 304, aluminium, copper, … (22) | kg |
| Tool steels | P20, 2738, S136, H13, 1.2343 ESR, D2, SKD11, mould base steel, C45 / S50C, BeCu | kg |
| Processes per hour | CNC milling, EDM, wire cut, grinding, deep-hole drilling, polishing, heat treatment, fitting, design, try-out | hour |
| Processes per unit | heat treatment and vacuum heat treatment, cutting | kg |
| | wire cut | cm² or mm of cut |
| | polishing, mirror polishing, texture / etching, nitriding, hard chrome | cm² |
| | painting | m² or unit |
| | transport | kg |
| Minimum charge per job | for the per-unit processes that have one | job |

- These are **ordinary rates in the rate library**: approved, versioned by month, with source, history and trend.
  Click a value to see all of that. Small grey text under a value is the INR value and the difference against India.
- **Master data holds the list, the unit and the India value**; the other countries are derived:
  - *Tool materials* and *Process rates* (India rate per kg / per hour) and the new *Process rates by unit*
    (what it is charged per, India rate, minimum charge per job) are in **Master data → Mould & die database**.
  - *Country rate index* is in **Master data → Countries, machines & formulas**. It gives each country's price level
    against India (India = 1) for part materials, tool steels and processes.
- **Proposing rates.** A country's rate = India rate × index ÷ forex (INR per unit of its currency), rounded to 3
  significant digits. *Propose missing rates from India × index* saves **drafts** for review, only where a country has no
  version of that rate yet. It never changes an existing rate. If a country has no index row or forex rate, it is skipped
  and the message says why.
- **First set-up.** The India values that were in Master data became the first approved version (source "Moved from
  Master data in Stage 3"). The other 8 countries are approved **EXAMPLE** values from the indices (all marked •).
  Replace them with supplier quotes or market rates (**New version** in the Rate library, or Excel import as drafts).
- **Example-rate warning.** Any cost that uses a rate still marked EXAMPLE shows a red banner
  **"Uses example rates – not for negotiation"**: on the Parts list and part panel, the Dashboard, the Estimate page
  (RM cost and tool cost) and the Rates page (machine & labour rates). The same banner is the first row of every sheet
  of the Excel exports (RM cost sheet, part register) and a red box on the PDFs (RM cost sheet, project summary). It goes
  away when every rate used has been replaced by a real approved rate.
- Because part-material rates now exist for every country, **a part set to another producing country gets its RM cost
  straight away** (stage 2), in that country's currency and in INR.
- The tool cost engine (stage 4, see *Tool cost* above) prices moulds and dies with these country rates.

---

## Mould concept v1 (roadmap stage 5)

On a part's panel (plastic / die casting) open **Mould concept** and press *Analyse*. The 3D model is ray-cast along X, Y and Z:
faces shadowed along the opening direction are undercuts. The axis with the least undercut is proposed; undercut regions
facing outward become **slides**, inward ones **lifters** (plastic only). *Use … in the tool cost* saves them as the part's
slides / lifters and recalculates. Gate, runner, cooling, ejection and insert proposals are the first matching row of
**Mould & die database → Concept rules**; thresholds are `undercut_*` rows of Sizing rules. All are EXAMPLE values and
all results are proposals to check.

## Simulation & analysis v1 (roadmap stage 6)

On a part's panel (plastic or die casting), open **Simulation & analysis** and press *Analyse*, or download the **PDF report with maps**.
- **Maps** (ray casting on the 3D model): wall thickness per face, draft angle to the opening direction, sink-risk
  (thicker than `sink_ratio` × wall), thin walls (below `thin_ratio` × wall) and undercuts.
- **Cycle time**: cooling (plastic: centre-line formula with diffusivity, melt / mould / eject temperature) or
  solidification (die casting) + fill + open / eject + insert loading (Insert moulding rules, less the share a shuttle hides).
- **Clamp force** = projected area × cavities × cavity pressure (from flow length ÷ wall) × safety factor. The smallest
  machine of `trial_machine_process` with enough tonnage is selected.
- **Corrections required**: low draft, sink risk, thin walls, undercuts, no machine large enough, cycle above plan.

Every formula is a row of **Mould & die database → Simulation rules**, evaluated in order (each may use the ones above
it, Parameters and Insert moulding rules; `log` and `exp` are allowed). All rows are EXAMPLE values. This is an analytical estimate, not Moldflow.

## Design loop (roadmap stage 7)

Each part's panel has a **Design loop** card: the status flow, *Move to* (only the allowed next statuses) with a comment,
and the timeline of status changes and revisions (who, when, why, days in each status). The rules are columns of
**Part register setup → Part statuses**: *Allowed next statuses*, *Comment required to enter* and *Status after a new
revision upload* (e.g. Corrections required → Revised when the corrected model is uploaded). In the Simulation card,
*Put this result in the Design loop form* proposes Corrections required (with the corrections as the comment) or
Simulation OK. Tick two revisions to compare them side by side, including their latest RM and tool cost.

## Part cost (roadmap stage 8)

On a part's panel, **Part cost** shows the piece cost once the RM and tool cost of the current revision exist:
RM + process cost ((MHR of the machine the tool's clamp force selects + operators × operator labour rate) ÷ parts
per hour) + secondary operations + inserts (BOP price × quantity + handling) + rejection (with the inserts lost) +
overhead + profit + packing + tool amortisation (tool CAPEX ÷ annual volume × programme years) + logistics
(weight × transport rate). Insert loading time per shot is added to the cycle. Click any value for its trace,
down to the electricity rate inside the MHR. Type over cycle time, cavities or secondary operations %, then
*Save and store* for a new numbered version (old versions never change); Excel and PDF carry the full backup.
The steps are Cost formulas of scope **piece**, their inputs Formula inputs of that scope (Parameters, the rate
library or values worked out by the app: see the Formula help sheet). All are EXAMPLE values.

## Sheet-metal tools I (roadmap stage 9)

For parts whose process is sheet metal, the **Sheet-metal tools** block on the part panel reads the 3D model (thickness, holes,
bends, blank) and proposes the **operation sequence** (blanking, piercing, drawing, bending, trimming), the **force of each
operation** (perimeter × thickness × shear strength, bend and draw formulas), the **tonnage** with the press safety factor, the
**smallest press** (Machines whose process is `press_machine_process`) and **formability checks** (bend radius, hole size,
draw ratio, springback). *Progressive* puts all operations in one die (one press); *multi-stage* gives each operation its own
press. The die type follows the part's process (progressive / multi-stage); the block also shows what the rules suggest
(volume, size, draw depth). Edit the die type, draw depth, bend radius or the operation list per part and save.
Everything is data in **Mould & die database → Sheet materials, Sheet operations, Sheet rules, Sheet checks** and the sheet-metal
Parameters; all rows are EXAMPLE values.

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

Stages A–C, the rate library and MHR engine, the part register (stages 1 and 1b), the RM cost on the register (stage 2), the material & process rates by country (stage 3) and the tool cost engine (stage 4) are done.
Next come five requirement sets, built one PR at a time:
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

### Stage plan
The full architecture, the honest "how automatic is each feature" table and the stage-by-stage plan (one PR per
stage) are in **[ROADMAP.md](ROADMAP.md)**. The two briefs it is built from are kept in `docs/`
(`MASTER_FLOW_PROMPT.txt`, `ROADMAP_PROMPT.txt`) so every future session works from the same requirements.

### Free official data sources planned for the monthly update (roadmap stage 12)
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
backend/app/gross_weight.py   Estimate page Stage B: request model around the RM engine
backend/app/rm_cost.py        RM engine: gross weight, yield, RM cost, scrap credit from master-data formulas, fully traced
backend/app/capacity.py       Stage C: cavities, tools, tool life, machine hours
backend/app/master_data.py    Reads, checks and saves master_data.xlsx
backend/app/mould_db.py       Mould & die tables in the costing database
backend/app/mould.py          Mould sizing (layout, insert, base) from the database
backend/app/example_values.py Replace example values checklist: counts by category, replace / keep rates and rows
backend/app/tool_cost.py      Tool cost engine: BOM, process-wise cost with MHR + labour, try-out, overhead, profit, ... fully traced
backend/app/formula.py        Safe evaluation of the BOM rules and cost formulas
backend/app/costing_db.py     The shared SQLite file (costing_db.sqlite)
backend/app/table_set.py      Editable table sets: validation, Excel import/export
backend/app/costing_setup.py  Countries, machines, labour grades, cost formulas, formula inputs
backend/app/rates.py          Versioned country rate library with approval
backend/app/country_rates.py  Material & process rates by country: base values, proposals from the country index, grid
backend/app/rate_engine.py    MHR and labour rate per country, fully traced
backend/app/trace.py          Traceable calculations (formula, inputs, sources)
backend/app/projects_db.py    Project database (SQLAlchemy: SQLite now, PostgreSQL later)
backend/app/register.py       Part register: projects, variants, parts, revisions, BOM, history, search, dashboard, RM cost versions
backend/app/register_setup.py Master data of the register (processes, statuses, sourcing, code pattern, storage folder)
backend/app/cad_import.py     STEP reading: assembly tree (XCAF), quantities, look-alikes, thumbnails
backend/app/file_store.py     CAD file storage by checksum
backend/app/pdf_report.py     PDF exports in the Design to Cost style
backend/app/main.py           FastAPI web server: all /api endpoints + serves the pages
master_data/                  master_data.xlsx and costing_db.sqlite (your editable data)
frontend/index.html           Estimator page (form + results + 3D viewer)
frontend/app.js               Estimator logic and three.js viewer
frontend/master-data.*        Master data page (editor for both data sets)
frontend/help.*               Help page
frontend/examples.*           Replace example values checklist (Master data)
frontend/rates.*              Rates page (MHR & labour, rate library, rate review)
frontend/dashboard.*          Project dashboard
frontend/parts.*              Part register (search, part details, revisions, history)
frontend/import.*             Import: STEP part / assembly split, Excel bulk upload
frontend/common.js, register.css  Shared helpers and layout of the register pages
frontend/trace.js             Traceability panel used by every page
theme/                        Design to Cost theme: dtc-theme.css, logo.png, THEME.md
docs/                         The requirement briefs (MASTER_FLOW_PROMPT.txt, ROADMAP_PROMPT.txt)
ROADMAP.md                    Architecture, automation levels and stage plan
data/, storage/               Your project data and CAD files (created on first use, not in git)
frontend/style.css            Page styling
frontend/vendor/three/        three.js r160 (MIT licence), bundled for offline use
samples/                      Sample STEP parts and an assembly (demo_assembly.step) + the script that makes them
tests/                        Automated tests (pytest)
```

### API (for later integration with ERP / PLM / dashboards)
`POST /api/analyze` takes a multipart form with `file` (.step/.stp), `part_type` (`plastic` | `die_casting` | `foundry` | `sheet_metal`) and `density` (g/cm³).
It returns JSON with `metrics` (all the numbers above) and `mesh` (triangles for the viewer).
`POST /api/gross-weight` takes JSON with `part_type`, `net_weight_g`, `density_g_cm3`, `material` and optionally `country`,
`as_of` and the Stage B inputs from the table above (any you leave out use master data; the material rate comes from the approved
rate library). It returns gross weight, yield, nesting, cost and the full `nodes` trace. `GET /api/gross-weight/defaults` lists
the default values and `GET /api/rm/meta` the countries and inputs.
RM cost of registered parts: `GET /api/parts/{id}/rm-cost` (versions), `POST /api/parts/{id}/rm-cost` (calculate; with `rm_inputs`,
`country`, `costing_month` it saves them first), `GET /api/parts/{id}/rm-cost/trace?version=`, `…/export.xlsx`, `…/export.pdf`
and `POST /api/projects/{id}/rm-cost/recalculate`.
`POST /api/capacity` (Stage C) and `POST /api/mould/estimate` (mould size) work the same way.
Tool cost: `POST /api/tool-cost` (Estimate page; `…/export.xlsx` and `…/export.pdf` give the tool cost sheet), `GET /api/tool-cost/meta`,
and for registered parts `GET/POST /api/parts/{id}/tool-cost` (versions / calculate; with `tool_inputs` or `tool_country` it saves
them first), `GET /api/parts/{id}/tool-cost/trace?version=`, `…/export.xlsx`, `…/export.pdf` and `POST /api/projects/{id}/tool-cost/recalculate`.
`GET/PUT /api/master-data` and `GET/PUT /api/mould-db` read and save the data sets.
Example checklist: `GET /api/examples`, `GET /api/examples/export.xlsx`, `POST /api/examples/rate` (`rate_id`, optional `value`)
and `POST /api/examples/row` (`set`, `table`, `key`, optional `value`).
`…/download` and `…/upload` move them to and from Excel.
Interactive API docs are at http://127.0.0.1:8000/docs while the server runs.

---

© Design to Cost
