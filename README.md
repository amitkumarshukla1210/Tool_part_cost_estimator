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
| Sheet metal | Thickness and flat blank L × W (**calculated** from the 3D model, can be typed over), gap between blanks (5 mm); sheet size (2500 × 1250) and edge trim (5 mm) for the nesting information | (Blank L + gap) × (blank W + gap) × thickness × density. Blanks per sheet and sheet utilisation are shown as information |

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

Sheet-metal dies are costed die by die (stages 9, 10 and 23), foundry patterns since stage 27 and machining fixtures since stage 37.

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
cost and annual volume). **Edit project → Delete project** removes a project with its variants, BOM, parts, revisions,
cost versions and CAPEX lines: type the project code to confirm. It is refused while one of its parts is used by another
project (in its BOM or moulded into its part), a backup ZIP `dtc-before-delete-<code>-<time>.zip` is made first (restore
it with `backup.py --restore` or `DTC_Restore.bat`), and in server mode only an admin may delete.

**Remove or delete a part** (Parts → open the part → bottom of the details form):
- **Remove from project BOM:** takes the part out of the BOM of every variant of its project. The part stays in the parts list with its files and costs.
- **Delete part:** removes it from the register: revisions, RM / tool / part cost versions, suppliers, BOM lines and its tool CAPEX line.
  - Type the part code to confirm.
  - A backup ZIP `dtc-before-delete-<code>-<time>.zip` is made first.
  - It is refused while the part is moulded into another part.
  - Who may do it: *Admin → Users, roles & permissions → Delete parts* (approver by default).

**Every table has column filters:** the ▾ in a column header opens a search box and the column's values as tick boxes
(multi-select, with Select all, Clear all and Reset). Filters on several columns combine; *Clear all filters* above the
table shows every row again. Then bring in the parts on **Import**:

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
parts get the RM of their bar stock (stage 37). A part without a material, a density, a 3D file or an approved rate shows
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
Large STEP files are tessellated once per server process and reused by the concept, simulation and process-parameter
cards. An unchanged simulation is also reused for its report, video and process settings; a new revision or changed
master-data input triggers a fresh calculation. The first run on a detailed model can still take a minute.

## Design loop (roadmap stage 7)

Each part's panel has a **Design loop** card: the status flow, *Move to* (the allowed next statuses, plus **↩ Back to** any
earlier status, e.g. a forgotten Concept tool step; a step back always needs a comment and shows as ↩ in the timeline) with a comment,
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

**Cycle time in the part cost (stage 39).** The cycle time is **the calculated one by default**, never the target of
Parameters → `cycle_time_s`. Moulds, dies, EPS and blow tools use the cycle of the part's simulation (fill + cooling + open / eject,
insert loading), the same number as on the Simulation card and the Process parameters sheet. Sheet metal uses strokes per part
÷ press speed: one stroke for a progressive die, one per operation for multi-stage dies, with the Design rules `press_spm`,
`press_spm_manual` and `press_spm_draw_factor` (slower for drawn parts; EXAMPLE values). Type your own cycle time on the part (or
change it from the traceability panel) to override it; clear it to go back to the calculated one. If the cycle cannot be
calculated (for example no simulation for the part), the target of Parameters is used and the trace says why. Stored part cost
versions never change: the part shows that inputs changed and you recalculate on purpose.

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


**Operations in order** (Sheet-metal tools block on the part): the current sequence is listed (the suggested one, or yours), with ↑ / ↓ to reorder, ✕ to remove, *Add operation* and *Reset to suggested*; *Save and recalculate* stores it.
## Sheet-metal tools II (roadmap stage 10)

The **Sheet-metal tools** block also shows the **blank** and the **progressive strip layout**. A flat part gets its real outline and
holes; a bent part the developed rectangle (the blank estimate: bend lines and hole positions need a real unfolder, e.g. the FreeCAD
SheetMetal workbench). The strip is worked out for the blank fed along its length and along its width; the better material
utilisation is shown: pitch = blank along the feed + bridge, strip width = blank across + 2 edge margins, stations = operations +
idle stations, pilots. The formulas are **Mould & die database → Strip rules** and sheet-metal Parameters (EXAMPLE values).
Downloads: **Blank DXF** and **Strip DXF** (CUT layer, dimensions) and the **Tool pack PDF** (dimensioned blank, strip layout, simplified
stage sketches, forces). The stage sketches show the flat blank (with holes once pierced), not formed shapes.

## Country comparison and landed cost (roadmap stage 11)

On a part's panel (plastic / die-cast / sheet-metal parts with a tool), **Country comparison and landed cost → Compare all countries**
costs the part **and its tool as if made in each country** (that country's approved material, machine, labour, power and process rates,
through the same RM, tool-cost and part-cost engines). The **ex-works** price (part cost without local logistics) is shown in the local
currency, USD and INR. For imports into India it adds **freight** (sea or air per kg × weight), **insurance** (% of ex-works + freight)
= CIF, **Basic Customs Duty** (by HS code and origin; the FTA / preferential rate of JP, KR, TH, VN is used when you keep the box
ticked), **SWS** (% of BCD), **IGST** (on CIF + BCD + SWS; the credit is shown separately when `igst_claimable` is 1), **clearance** and
**inland transport** → **landed cost in INR**. The forex effect (± `fx_scenario_pct`, 5 %), a stacked bar chart and the cheapest country are
shown; Excel and PDF carry the full data and the rate versions used. HS codes: **Mould & die database → HS codes**. Duty, freight and
import rates are approved versions in the rate library (categories `duty`, `freight`, `import`). All are EXAMPLE values;
check the tariff heading and rates with your customs broker.

## Monthly rate update (roadmap stage 12)

**Rates → Rate review → Fetch now**, or the GitHub Action *Monthly rate update* (1st of each month 05:17 UTC; also *Run workflow*), fetches:
- **Forex** from the ECB euro reference rates (USD, EUR, CNY, JPY, KRW, THB as INR per unit; TWD and VND are not published by the ECB and stay manual).
- **Price index** (World Bank WDI, consumer prices, annual; Taiwan is not published) and from it **index-based proposals**:
  new rate = last approved rate × (latest index ÷ index of the year it was approved). Which rate categories get proposals is
  **Mould & die database → Update rules**. Rates still marked EXAMPLE are left alone (replace them first, see *Replace example values*).

Everything arrives as a **Draft** with its source link and fetch date; nothing is approved automatically. If a source fails the
reason is written to the **Update log** (Rate review tab), the last approved values stay in use and costing is not affected.
The Action opens a pull request with the changed `costing_db.sqlite`; it needs *Settings → Actions → General → Allow GitHub Actions to create and approve pull requests*.
The same run works from the command line: `python -m backend.app.rate_update`.

## Project leader view (roadmap stage 13)

The project dashboard now starts with the **Project leader view**:
- **BOM cost vs target** per variant: Σ quantity × the part's latest stored part cost (parts we make) or its bought-out price; moulded-in
  inserts are inside their body's cost. *Recalculate part costs* refreshes every part after rates change.
- **CAPEX**: tool & mould CAPEX (stored tool costs), **machine CAPEX** (machine type chosen by each part's clamp force; hours = annual volume
  ÷ parts per hour ÷ OEE, divided by the hours one machine runs per year, rounded up per type; price from the rate library), other lines,
  total against the budget.
- **CAPEX plan**: *Add lines for costed tools and machines* creates one line per tool and machine type (amounts refresh, your supplier, dates and
  payments are kept); add other lines by hand. Set the project's **SOP date** (Edit project): each line's payment milestones
  (**Part register setup → CAPEX payment milestones**: share % and weeks before / after the need-by date) get due dates; tick a milestone when paid; overdue ones are flagged.
  Cash-out by month and totals by supplier and country follow.
- **Open corrections** from the design loop, and the consolidated **Excel and PDF** (summary, BOM cost, machines, plan, payments, timeline).

## Harness & PCB BOM extraction (roadmap stage 14)

Open **Harness & PCB** in the header and upload a file:
- **Harness**: a KBL or VEC **XML** export (wires are grouped by part, colour and cross-section with their count and total length; connectors, terminals,
  seals, sleeves, tapes, clips, grommets and labels are counted), or a **text PDF** drawing with a BOM table (the header row must name a quantity or part number
  column). Scanned PDFs, scan images and DWG/DXF drawings are described in the next section.
- **PCB**: a BOM **CSV or Excel** from KiCad, Altium or any tool (designator column plus two of value, footprint, quantity, part number), an optional **pick-and-place
  (CPL) CSV** (placement count, board extents, cross-check with the BOM) and the bare-board data you type (layers, thickness, width, height). SMT / THT is
  taken from the BOM column or guessed from the package name (guesses are marked).
- **Review**: every line has a confidence and the reason it is lower (no part number, quantity differs from the designators, category guessed, ...). Lines under 0.8 are
  yellow; editing a line sets it to 1. Add or remove lines, *Mark reviewed* (reopened by any later edit), export to Excel. Changes are in the history.

The XML reader follows the KBL / VEC structure by element names and was built and tested with small hand-made samples, not with your real exports:
check the first real file and tell me what differs. Costing is in the next section.

## EPS (thermocole) moulds and PET stretch blow moulding (roadmap stages 18 and 19)

Two more part types run through the same stages as injection moulding; pick the material and the process follows (*Master data → Materials*, part type `eps` or `blow`):

- **EPS shape moulding (thermocole)**, process `eps_moulding`: foam weight = CAD volume × foam density (e.g. 20 kg/m³ = 0.020 g/cm³); bead cost per kg with trim and fines;
  **tool** = aluminium cavity and core blocks in a steam chest (Mould bases series *Steam chest*), steam vents (count from the surface area), fill guns, ejectors, valves and fittings; the
  **steam pressure** times the projected area sets the locking force that picks the EPS moulding machine; **steam** per kg of part is added to the part cost (Parameters `steam_kg_per_kg_part`, rate `utility / steam_per_kg`).
- **PET stretch blow moulding (bottles)**, process `stretch_blow_moulding`: bottle weight = **outer surface × average wall × density** (a bottle is a thin shell, so the CAD volume is not used; wall = Parameters `blow_wall_mm`, or type `wall_mm` under RM inputs for the part);
  **tool** = blow mould (aluminium cavity halves, base and neck inserts, vents, cooling, stretch rod and blow nozzle per cavity) in a blow-mould holder; blow pressure × projected area picks the stretch blow machine; the
  **preform** is an ordinary plastic part (*PET preform grade*, injection moulding, high cavity count) and its injection conversion is added to the bottle's cost as a share of the resin cost (Parameters `preform_conversion_pct`, example 28 %):
  cost the preform as its own part to replace that share by your real preform price.

All new rows are EXAMPLE values (machines EPS-1000/1400/1800 and ISBM-2C/4C/6C/8C, materials, aluminium 7075 / 6061, bases, BOM rules, cycle times, steam and resin rates for 9 countries, HS 3923). The country comparison and landed cost, the part cost and the project view work
for them unchanged. The concept and simulation cards (opening direction, undercuts, wall and draft maps) are for plastic injection and die casting only.

## Developed blank for the best material yield, and the simulation result in the design loop (roadmap stage 25)

**Blank of a bent sheet-metal part.** The blank is worked out from the 3D model for the best material yield. Material
yield = flat part area ÷ blank area; holes are added back, because they are punched out of the blank.

| Part | Blank |
|---|---|
| Flat part | Its own length × width |
| Bends all running the same way (L, U, Z, channel, angle bracket) | A **developed straight strip**: width = the part's size along the bend line, length = flat area ÷ width. The L / U shape is then formed in a **bending stage**, which the operations include. |
| Bends both ways (tray / box) | (L + 2·H) × (W + 2·H), corners notched |
| Mostly one way (≥ 90 % of the sheet area) with small tabs, ribs or embossings the other way | Still the developed straight strip |

Before, a bent part kept its formed width. For an L bracket 300 × 100 mm made from a 20 mm strip, that gave a 300 × 100
blank at 26.5 % yield; the developed strip is 398 × 20 at about 100 % (gross weight then adds only the gap between blanks).

**How the bend line is found:**
- Rounded bends: coaxial cylinder pairs one thickness apart (hole walls are not bends).
- Sharp-cornered models: where two sheet faces with different normals meet. A sheet face is one with a twin face one thickness away; edge and side faces don't count.

The *Sheet-metal tools* block shows the options with their yield, the chosen one ticked. The gross weight, RM cost, nesting,
strip layout and dies use the chosen blank, and the RM / tool cost asks for a recalculation when it changes. Other sizes can
still be typed under RM inputs.

**Downloads, stage-wise (sheet-metal dies).** The *Dies suggested* table has **PDF · Excel** per die: the die (operations,
work area, die plate L × W × H, die set and plate material, press and force, cost) and its full bill of material with grade,
make and standard part numbers. The *All dies* row (and *Tool cost → Excel / PDF*) gives a dies summary plus one page / sheet
per die (Stage 1 of N, …). Blank DXF, strip DXF and the tool pack PDF stay under *Sheet-metal tools → Blank and strip layout*.

**Comparing countries.** *Country comparison and landed cost* on the part: tick the countries (or **All** / **None**) and
**Compare the ticked countries**. Each row has the part ex-works and landed in India, plus the **tool cost in the country's
currency, ex-works in INR and landed in INR** (cheapest marked). Excel and PDF keep the same countries. The *Tool country*
of the part (Tool features) is still one country: the one its stored tool cost is calculated for.

**Base material of moulds and dies.** *Mould bases* now have a **plate material** (grade from Tool materials; C45 / S50C for
the example bases, EN8 (080M40) added with an example price in every country) and a **make**. The traceability of the base
shows the material, the base weight and the plate steel value (weight × steel rate); the steel grade drop-down changes it for
this part. A base with no catalogue price (cost 0) is priced by weight: plate steel value × `base_make_factor` (Sizing rules,
2.2 = machining, pillars, bushes, screws; EXAMPLE).

**Tool BOM table on the part** is now a closed section (*Tool BOM table · optional*): grade, price and base are normally
changed in the traceability window; the table and *+ New grade / + New standard part* are inside it.

**Simulation result in the Design loop.** The Design loop card now shows the simulation result for the part:
- **Plastic / die casting:** *Run simulation & show result* opens *Tool cost → Simulation & analysis* (wall, draft, sink and undercut maps, cycle time, clamp force, machine) and runs it.
- **Sheet metal:** the forming result, from the Sheet-metal tools:
  - the blank and its yield;
  - every stage with its force and press;
  - the formability checks (bend radius, holes, draw ratio, springback), as "No corrections required" or the list of corrections.

**Put this result in the Design loop form** fills *Move to* (Simulation OK / Corrections required) and the comment when that move is
allowed from the current status. Moving from *Simulation* to *Simulation OK* then records the result in the timeline.

## Correct any value from the traceability panel (roadmap stage 24)

Click any value of a part's RM cost, tool cost or part cost: the **traceability** window opens. **⤢ Full screen** works there
and on the part window, and the choice is remembered on the PC. Below the formula or source there is **Change this value** or
**Change this formula**, with these choices:

| Button | What it does |
|---|---|
| **For this part only** | The new value or formula replaces the rate-library or master-data one **in this part's cost only**. The cost is recalculated and stored as a new version; the part cost follows. The value shows *changed for this part* with who, when and what it was. **Reset to master data** removes it. Other parts are not touched. |
| **Save for the future** | Corrects the source: a **rate** gets a new rate-library version this month (approved when you may approve rates, else a draft for the approver); a **master-data value** (Parameters, Sizing rules, Process time parameters, Tool materials, Tool processes, Machines, Mould bases, Standard parts) or a **rule / formula** (BOM element rules, Cost formulas) is changed in its master-data row and loses its EXAMPLE flag. New and recalculated costs use it; stored costs show "master data changed" until you recalculate. |

**How a number in a rule is arrived at:** a rule such as `1500 + die_l * die_w / 100` (screws, dowels & bolts) is the BOM
element's rule in master data. The numbers in it are its constants (here a base price of 1500 INR plus 1 INR per cm² of die
plate), the names are the inputs listed below it, and the notes of the element are shown. Change it for this part, or save it
for every tool.

**Steel grade from the trace:** clicking a steel rate (e.g. *Steel rate · D2*) or a line's steel cost shows at the top
**why this grade** for every BOM line using it (Grade rule with its reason, learned from your earlier parts, your choice or the
element default) and a **grade drop-down with the approved price per kg** of each grade in the tool country, showing the
difference (e.g. 520 INR/kg instead of 500, +4 %) and the make. Tick the lines, click **Use this grade for the ticked lines**:
the tool cost is recalculated and stored and the choice is learned for the next parts. Works for every mould and die.

**Mould base / die set:** clicking the mould base or die set price shows every base of that part type (size, usable area,
stack height, weight, price) with **Use for this part** (instead of the smallest that fits; a smaller one is warned) and
**+ Add a row** (saved to Master data → Mould bases, then selectable).

**Default grade, make, standard part and price per BOM element:** *Mould & die database → BOM elements* has the columns
*Material* (grade), *Make*, *Standard part* and *Price each, INR* next to the rules. Every costing recalls them as the default
of the line, unless you change it on the part. Ticking **my default** on a part's BOM line saves all four there. A blank or 0
price means the line is calculated.

## Sheet-metal dies and the tool BOM: grade, make, standard parts, learning (roadmap stage 23)

**Sheet-metal dies, stage-wise.** A sheet-metal part's tool cost (Parts → the part → Tool cost) suggests its dies from
the operations in order and the die type (Sheet-metal tools):
- **Multi-stage**: one die per operation (*Die 1: Blanking*, *Die 2: Piercing*, *Die 3: Bending (V)*…).
- **Progressive**: one die holding every station.

Each die is sized as follows:

| Value | Rule |
|---|---|
| Die plate length / width | Work area (blank, or strip pitch × stations) + 2 × `die_wall_mm` |
| Die plate height | max(`die_plate_min_mm`, `die_plate_t_factor` × thickness) |
| Die set | The smallest one in *Mould bases* (part type `sheet_metal`) that takes the die plate |

Each die then gets the BOM elements of its operations (*BOM elements → operations*):
- die plate and blanking punch (D2, from *Grade rules*);
- piercing punches (standard), punch holder, stripper and hardened backing plates;
- bending punch and V-block, pressure pad, draw punch, draw ring and blank holder;
- pilots (progressive), springs, screws and dowels;
- wire cut of the die profile and the punches, CNC, grinding, heat treatment, fitting and design.

Each die is priced like a mould: steel rates, machine hour rate (MHR) + labour, try-out on the smallest *Press* that takes the die's force × `press_safety_factor`, then overhead, profit, packing, transport and warranty. The part shows a table of the dies (operations, die set, die plate, press, cost each) and the total. CAPEX = Σ dies × tools over the programme.

**Tool BOM on the part** (every mould and die). Each line shows:
- **Grade**, suggested in this order:
  1. your change on the part;
  2. **learned from your earlier parts**;
  3. *Grade rules*;
  4. the element default.
- **Make** (from the element, the grade or the standard part).
- **Standard part** with the maker's **part number**.
- **Price each** and the line cost.

Change any of them and click **Save**: the tool cost is recalculated and stored as a new version, and the line is marked *changed by you*. *Price each* (INR) replaces the calculated cost of the line; *Reset* goes back to the suggestion. Tick **my default** to make the grade and make the master-data default of that element for every new tool (needs *Edit master data*).

**Learning.**
- Every grade, make or standard part you choose on a line is remembered per part type and element, the same part material first.
- The **next new parts** get it as their suggestion, shown as *learned · 2× · last on RF220CRLRL002*.
- A part that already has a tool cost keeps the choices it was costed with, so its cost does not move on its own.

**New grade / new standard part** (on the BOM):
- **+ New grade**: name, make / mill, price per kg and its country, density, hardness. This adds a *Tool materials* row and its price as a rate of that country. The rate is approved when you may approve rates; otherwise it is a draft for the approver.
- **+ New standard part**: code, **part number**, description, make, BOM element it fits, price and country. This adds a *Standard parts* row.

From then on both are in the drop-downs.

**Grade rules** (*Mould & die database → Grade rules*): per part type and BOM element, the first rule that applies (by order) gives the grade and the reason shown. Each rule has a condition on e.g. `programme_shots`, `annual_volume` or `t`, plus *part material contains* keywords. Examples:

| Element | Material / condition | Grade |
|---|---|---|
| Cavity / core insert | PVC, or PC / PMMA / clear | S136 ESR |
| Cavity / core insert | Glass-filled (GF) | H13 |
| Cavity / core insert | Over 1 million shots | H13 |
| Die-casting inserts | Over 150,000 shots | 1.2343 ESR |
| Die plate, blanking punch | Thickness ≥ 3 mm or over 2 million strokes | SKD11 |

Otherwise an element keeps its default grade (2738 for plastic inserts, D2 for cutting steels). All of these are EXAMPLE values to replace with your tooling standard.

## Logins, admin control and suppliers (roadmap stage 22)

**Logins are always on.** Everybody uses their own login ID; every change, approval and backup is recorded under that ID.

- **First start.** With no user yet, the app opens **First start: create the admin** (`/setup`): admin ID, full name and a
  password of 10+ characters. This page works only once; after it, everyone uses **Log in**.
- **Forgotten password** (also the admin's): at the PC that runs the app, double-click **`DTC_ResetPassword.bat`**
  (or `python -m backend.app.server_tools reset-password NAME`). The user is made active again and logged out everywhere.

**Admin** (menu, top right) shows tabs according to the signed-in user's permissions. **Users, roles & permissions** is visible only to admins; **My password** remains available to every signed-in user.

| Tab | What it does |
|---|---|
| **Users, roles & permissions** | Admin creates login IDs (user ID, full name, role, first password), changes name and role, blocks / unblocks a user and sets a new password. The last active admin cannot be removed or demoted. The same tab sets role defaults and per-user **Inherit / Allow / Deny** overrides; overrides are audited. |
| **My password** | Every user changes their own password after confirming the old one. Admins can set a new password for another user, but existing passwords are never displayed. |
| **Activity log** | Who changed what and when, newest first: projects, variants, parts (incl. status, revisions, costs, suppliers), suppliers, users, permissions, master-data and rate saves, rate approvals and backups. Filters (what, who, from, to, search), *Show more*, **Export Excel**. |
| **Backups & update** | Installed version and data folder, **Backup now**, every backup ZIP with *Download*, update reports, and—when the user has **Update the app** permission—an authenticated update action that stops and restarts the Windows kit after making a backup. |

Role defaults include project data and master-data changes (engineer), rate approval (approver), and backups / app updates (admin). A per-user Allow can grant an engineer extra authority; Deny removes an action even if the user's role normally allows it. **Managing login IDs and permissions stays admin-only.** On the Windows kit, the authenticated update button is permission-checked; `DTC_Update.bat` remains a local host-maintenance tool and is controlled by Windows access to the installation.

**Suppliers** (menu) is the supplier master:

- **Supplier code** is automatic from Master data → Part register setup → Register settings → `supplier_code_pattern` (`SUP-{seq:04d}` → SUP-0001, SUP-0002…), or typed.
- Each supplier holds:
  - name, status (`supplier_statuses`: approved / trial / blocked / inactive);
  - commodities / processes, country, city, address;
  - contact person, e-mail, phone;
  - GST / tax ID, payment terms, quote currency;
  - certifications (IATF 16949, ISO…), last audit date, capacity;
  - quality, delivery and cost scores (0–100), whose average is the **rating**.
- The list shows counts per status. Click a code to see its details, the parts it quotes for and its history. **Export Excel** gives two sheets: suppliers and part quotes.
- A supplier used by a part or a CAPEX line cannot be deleted; set it to *inactive*.
- **On a part** (Parts → part → **Suppliers & quotes vs should-cost**): add suppliers, one *main* and the others *alternate*. Each one gets its piece price, tool price, currency, quote reference and date. The quote is converted to INR with the approved forex of the quote month, and the gap to our should-cost (the part's stored part cost and tool cost) is shown in INR and %.
- **CAPEX plan** lines take the supplier from the master: type its code, e.g. SUP-0001. Its name and country go on the line, and the "by supplier" totals use it. A renamed supplier updates its lines.

## Server mode (roadmap stage 17)

Logins are on everywhere (stage 22). For a team, run the app once on a server instead of on each laptop:

```
pip install -r requirements.txt -r requirements-server.txt        # psycopg is only needed for PostgreSQL
export DTC_ADMIN_PASSWORD='a long first password'                 # optional: creates the first user "admin"; else /setup asks on first start
export DATABASE_URL='postgresql+psycopg://user:password@dbhost/dtc'
export DTC_STORAGE_FOLDER=/srv/dtc-files                          # shared folder for CAD files and thumbnails (or set it in Master data → Register settings)
export DTC_COOKIE_SECURE=1                                        # when served over HTTPS
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000           # put an HTTPS reverse proxy (nginx, Caddy, IIS) in front
```

- **Logins and roles**: everybody, including admins, logs in; the admin adds users and manages role defaults and per-user overrides on **Admin → Users, roles & permissions** (user ID, role, active, groups). **viewer** reads; **engineer** changes projects, parts, costs and master data; **approver** also approves rates; **admin** also manages users. The last admin cannot be removed. Admins can reset a password but cannot view one; passwords are stored as scrypt hashes, sessions expire after 12 hours,
  changing a password or deactivating a user ends their sessions.
- **Who did what**: every history record shows the logged-in user, and an approved rate shows the approver who clicked, never a typed name.
- **Move from the local PC**: `python -m backend.app.server_tools migrate-projects --from sqlite:///data/projects.sqlite --to postgresql+psycopg://...` copies all project data into an empty
  database (ids are kept); copy the `storage/` folder to the shared folder; `server_tools create-user NAME --role ...` and `server_tools check` help with set-up.
- **Not changed**: the costing database (rates, formulas, machines, mould and sheet tables, `master_data/costing_db.sqlite`) and `master_data.xlsx` stay files on the server (one web process, a few
  dozen users is fine; back them up with the database). `GET /api/server/health` reports mode, database kind and whether the storage folder is writable.

PostgreSQL was **not** available where this stage was built: the migration and the app were tested on SQLite only. Try the migration on a copy first.

## Scanned drawings and DWG (roadmap stage 16)

The Harness & PCB page also reads:
- **Scanned PDFs and images** (`.pdf` without text, `.png`, `.jpg`, `.tif`) with **Tesseract OCR** (open source). Pages are rendered at 300 dpi, Tesseract returns word boxes,
  the words are put into rows and cells, columns follow the header row (the same header words as a text PDF), and every cell keeps its OCR confidence: a line is as sure as its least
  sure word, so doubtful numbers turn yellow in the review table. Use straight, dark, 300 dpi scans; check every number in the yellow lines.
- **DXF** drawings: the text (TEXT, MTEXT, block attributes) is put into the same row / column grid.
- **DWG** drawings: converted to DXF first with **ODA File Converter** (free, proprietary licence) or **LibreDWG** (`dwg2dxf`, GPL), then read as DXF.

Nothing is bundled. Install Tesseract (Windows: the UB Mannheim installer; Linux: `apt install tesseract-ocr`) and/or a DWG converter, restart the app; the page shows what it found. If a tool is not on the PATH
set `DTC_TESSERACT` or `DTC_DWG_CONVERTER` to its full path. Without them, text PDFs, XML, DXF and CSV / Excel work as before.

## Harness & PCB costing (roadmap stage 15)

On the **Harness & PCB** page, below the BOM, choose the producing country and month and press **Calculate cost**:
- **Harness**: wires = total length × price per metre from the **Part library** (matched by part number), else copper content (cross-section × 8.96 g/cm³)
  × (copper rate + conversion rate per kg of copper) from the approved rates of the country; connectors, terminals, seals, sleeves, tapes, clips, ... = quantity ×
  Part library price; **processing** = driver (wires, crimps, connectors, wire length, sleeves, ...) × seconds ÷ 3600 × (MHR of the machine + operators × labour rate).
- **PCB**: components from the Part library, **bare board** = area (typed or from the pick-and-place extents) × rate per cm² of its layer count (rate category `pcb_board`) × (1 + panel waste),
  assembly processes (SMT placements, THT placements, test) with their machine MHR and labour.
- Then rejection, overhead, profit and packing (Cost formulas of scope `harness` / `pcb`). Click any value for its trace, down to the electricity rate in a machine hour rate.

Master data: **Part register setup → Part library** (price per piece or per metre, currency, source, month) and **Harness and PCB processes** (driver, seconds, machine, labour grade,
operators); new EXAMPLE machines (cut-and-strip, crimp press, SMT line, test bench) and rates for 9 countries. **A part that is not in the library is listed as "not priced" and
counts as 0** until you add it: nothing is guessed. Distributor price APIs (Octopart, Mouser, Digi-Key) are not used. A wire line's length is the total length of its wires.

## Price master and material types (roadmap stage 29)

**Master data → Price master** (`/master-data/prices`) shows the month-wise prices of the rate library as an item × month grid for
one country: **tool materials** (category `tool_material`), **part raw materials** (`material`) and their **scrap value**
(`material_scrap`); 24 months by default, plus next month.

- A cell shows the approved price costing uses in that month: yellow = a version starts that month, grey = carried over from an
  earlier month, empty = no rate yet. The grid starts from the rates you have and fills up as real months are entered; there is
  no made-up history.
- **Type a price** under a month: a new version from that month on, saved as a **draft** for Rates → Rate review. Only a
  user with the permission *Approve rates* sees *Save & approve* (unticked by default) and can approve at once. Old versions
  are never changed, so stored costs only change when you recalculate.
- **Excel**: download the grid, type prices under any month, upload: only changed cells become new versions (drafts, unless
  an approver ticks *Save & approve*).
- **New grades** are added where they always are: Tool BOM → *+ New grade* (stage 23), Master data → Tool materials or Materials.
  **Standard parts** keep their catalogue price (Mould & die database → Standard parts) and are not in this grid.

**Material type and recommended grade.** Tool materials and Materials have a *Material type* column (pre-hardened mould steel,
hot-work, cold-work, stainless, copper alloy, aluminium, plate steel; PP, ABS, aluminium die-cast alloy, carbon steel sheet, ...).
In Materials one grade per type and part type is marked *recommended*; the part panel shows it next to the material drop-down with
**Use it** (the drop-down still offers every grade). An older workbook without these columns still loads.

New EXAMPLE grades (EXAMPLE rates in all 9 countries, so the example warning shows wherever they are used): Beryllium copper C17200
and C17510, NAK80, 1.2316 ESR; PP copolymer (impact), PP talc filled 20 %, ABS flame retardant V0, PA66 GF30 heat stabilised,
CRCA D513 EDD, Stainless steel 430, Aluminium AlSi10Mg.

**Release name V0**: the `VERSION` file; shown in the page footer, the API docs (`/docs`), Admin → Backups & update and
`dtc_manager.py status`.

API: `GET /api/price-master/meta`, `GET /api/price-master/grid?group=&country=&months=`, `POST /api/price-master/price`
(`group, item, country, month, value, approve`), `GET /api/price-master/export.xlsx`, `POST /api/price-master/upload`
(permission *Edit rates*; `approve` defaults to false, and `approve: true` needs *Approve rates*, as everywhere: every
approved rate version, on the Rates page too, is checked in `rates.create`).

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

## Update, correct and back up (read this before every update)

**Where your work lives.** Your projects, parts and costs are in `data/` and your CAD files in `storage/`; both are **never** in GitHub. Your rates, machines, formulas and other master data are in
`master_data/` **and are in GitHub**, so a new download would replace your edits with the example values. Always back up first.

```
python backup.py                         # zips master_data/, data/ and the CAD storage folder into backups/dtc-backup-<time>.zip (keep a copy elsewhere too)
python backup.py --restore latest        # puts the newest backup back (what is there now is zipped first as dtc-before-restore-<time>.zip)
python backup.py --restore latest --only data,storage     # only part of it: master_data, data, storage
python update.py                         # backup, then git pull
```

**The correction workflow.**
1. Report the problem (page, what you did, what you expected, what you saw; the exact error text or a screenshot).
2. The fix arrives as a pull request on GitHub with the tests that were run; after you merge it, update your PC.
3. **If you cloned the project with git** (recommended): `python update.py`. It backs up, fetches, and pulls. If you changed `master_data/` and the new version leaves it alone, yours is kept. If **both** changed
   it, `update.py` stops without changing anything and tells you why: choose `--keep-mine` (your master data stays; the new example rows are missing) or `--take-new` (the new master data is used; yours is in the backup), or send the backup
   to have the new rows merged into your file. Then `pip install -r requirements.txt` and restart the app.
4. **If you use ZIP downloads on Windows**: use the update kit below (`DTC_Update.bat`). It does the backup, the new version and the master-data merge for you.
5. Check one known part (compare with its last cost) before you rely on the new version.

There is no limit on the number of corrections; each one is a new pull request. With PostgreSQL (server mode) back up the database with `pg_dump` as well.

## Install and update on Windows (ZIP download, local http://127.0.0.1:8000)

The `windows/` folder holds an update kit: `dtc_manager.py` and six double-click files. They live in the folder **above**
the app (the *base folder*, e.g. `D:\DTC\`). Your data is kept **outside** the app folder, so the app folder can be
deleted and replaced by every new version without losing anything.

```
D:\DTC\                           base folder (any name)
  Tool_part_cost_estimator\       the app            replaced by every update (old one moved to DTC_Old\)
  DTC_Data\                       YOUR DATA          never replaced
     master_data\                   rates, machines, formulas (costing_db.sqlite, master_data.xlsx)
     data\                          projects, parts, cost versions (projects.sqlite)
     storage\                       CAD files and thumbnails
     logs\                          one report per update (what was merged)
  DTC_Backups\                    backup ZIPs        (+ a copy to OneDrive / a pen drive: backup_copy_to)
  DTC_Downloads\                  new version ZIPs
  DTC_Old\                        the last 3 app versions, for DTC_Rollback.bat
  venv\                           Python libraries   kept, so CadQuery is not downloaded again each time
  dtc_settings.ini                port, GitHub, backup copy folder, ...
  dtc_manager.py  DTC_Start.bat  DTC_Update.bat  DTC_Backup.bat  DTC_Restore.bat  DTC_Rollback.bat  DTC_ResetPassword.bat
```

| Double-click | What it does |
|---|---|
| `DTC_Start.bat` | Backup if the last one is older than a day, then the app on **http://127.0.0.1:8000** (the browser opens). Keep the window open; close it to stop the app. |
| `DTC_Update.bat` | 1) checks the app is stopped, 2) **backup**, 3) new version: **download from GitHub** or **a ZIP you downloaded**, 4) installs the libraries and test-starts the new version: if that fails, nothing is changed, 5) old app folder → `DTC_Old\`, new one in place, 6) **merges the new master data into yours** (below), 7) writes a report to `DTC_Data\logs\`. Each update uses a fresh `_dtc_new_*` staging folder, so a leftover `_dtc_new` from an older update cannot block it; stale staging folders can be deleted later after closing Explorer or other programs using them. |
| `DTC_Backup.bat` | Backup now (`DTC_Backups\dtc-backup-<time>.zip`, plus the copy folder if set). |
| `DTC_Restore.bat` | Lists the backups; pick one and choose: everything, only projects + CAD files, or only master data. What is there now is backed up first. Backups made by `backup.py` work too. |
| `DTC_Rollback.bat` | Back to the version before the last update **with the data of that moment** (data changed after the update stays in the safety backup). |
| `DTC_ResetPassword.bat` | New password for a login ID (e.g. a forgotten admin password). Only possible at this PC. |

**First time (moving from your current installation).** Your current app folder keeps working until the end of step 4.
1. Stop the running app (close its window).
2. Download the new version: GitHub → **Code → Download ZIP**. Save it in the base folder (the folder that holds your current `Tool_part_cost_estimator…` folder) or in your Downloads folder.
3. Open the ZIP, go into its `windows` folder and copy `dtc_manager.py` and the six `DTC_*.bat` files into the base folder.
4. Double-click `DTC_Update.bat`, answer **2** (the ZIP). It finds your old app folder (also a double-unzipped `…-main\…-main`), backs up its data
   (`DTC_Backups\dtc-before-migration-*.zip`, never deleted), copies `master_data`, `data`, `storage` and your old `backups` into `DTC_Data` / `DTC_Backups`,
   installs the new version and moves the old folder to `DTC_Old\`. You do not delete anything by hand.
5. Double-click `DTC_Start.bat`. The first start asks you to create the admin ID (see *Logins, admin control and suppliers*).
   Check one known part against its last cost. Your old start file is no longer needed.

**Every next update.** Double-click `DTC_Update.bat` → **1** (download from GitHub) or **2** (a ZIP you downloaded) → `DTC_Start.bat`. The kit updates itself from the new ZIP.

**Your master data is merged, not overwritten** (`backend/app/upgrade_tools.py`): new tables, columns and rows of the new version are added;
rows you never changed take the new version's values; **rows you changed stay yours** (the report lists any of them the new version also changed);
your rate versions are never changed (only rate rows you do not have are added). "Never changed" means the row is identical to a row some released
version shipped: `backend/app/shipped_rows.json` holds a fingerprint of every row ever shipped (developers: after changing `master_data/`, run
`python -m backend.app.upgrade_tools fingerprints`; a test fails until you do).

**Backup plan.** Automatic: before every update, before every restore and once a day at start. By hand: `DTC_Backup.bat`. The 30 newest are kept
(`keep_backups`). Set `backup_copy_to` in `dtc_settings.ini` to a OneDrive / Google Drive / network folder so every backup also leaves the laptop.
To move to a new laptop: copy the base folder, or set up the kit there and restore the newest backup with `DTC_Restore.bat`.

**Settings (`dtc_settings.ini`, created on first use).** `port` (8000), `github_repo` and `branch` (main), `github_token` (only if the repository is
private: a fine-grained token for this repository with *Contents: read-only*; otherwise download the ZIP in the browser and choose 2), `backup_copy_to`,
`keep_backups`, `auto_backup_days`, `storage_folder` (empty = `DTC_Data\storage`), `python` (the Python that creates `venv\`; CadQuery needs 3.10–3.12,
the kit prefers 3.12 → 3.11 → 3.10 through the `py` launcher).

The app finds the data through environment variables the kit sets (`COSTING_DB_PATH`, `MASTER_DATA_PATH`, `DATABASE_URL`, `DTC_STORAGE_FOLDER`,
`DTC_BACKUP_FOLDER`), so `backup.py` inside the app backs up `DTC_Data` as well. Start the app only with `DTC_Start.bat`: started any other way it
would use the example data inside the app folder.

## Full roadmap

All planned stages are built: Stages A–C, the rate library and MHR engine, the part register (stages 1 and 1b), RM cost
(2), rates by country (3), tool cost (4, 4b), mould concept (5), simulation (6), design loop (7), part cost (8),
sheet-metal tools (9, 10), country comparison (11), monthly rate update (12), project leader view (13), harness & PCB
(14–16), server mode (17), EPS and PET blow moulding (18, 19), backup and the Windows update kit (20), the corrections
from use (21), logins with admin control and the supplier master (22), and sheet-metal dies stage-wise with the
editable, learning tool BOM (23), correcting any traced value for one part or for the future (24), the developed blank with the simulation result in
the design loop (25), the work instruction, drawings and PO pack (26), tool design in 3D with drawings, simulation report and
video (27), large parts with the audit gaps closed (28), and the price master with material types and the V0 release name (29). The original requirement sets **A** sheet-metal tools, **B** tool / mould / die cost, **C** country
rate library, **D** country comparison and **E** monthly rate update with approval are all covered.

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
is checked again before its fetcher is switched on. **Switched on in stage 12:** the ECB euro reference rates (forex) and the
World Bank WDI consumer price index (indexation). The others in the table are not fetched yet: their rates stay manual or index-based.

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

## Work instruction, drawings and the PO pack

- **Help page → Start here → Work instruction (PDF)**: a step-by-step guide for a new user, made from a real example (L bracket
  EX26-0001: Rev A, simulation asks for a correction, Rev B, tool design frozen; plastic cover EX26-0002 with its mould). The
  sample STEP files and every output of the example (drawings, cost sheets, PO pack) can be downloaded there.
- **Part drawing**: part panel → Geometry → *Part drawing PDF / DXF* (three views, overall dimensions, title block, revision).
- **Tool drawing per stage**: Dies table → *Drawing PDF · DXF* per die (plan with pillars, die plate / work area, plate stack, main
  BOM); plastic / die-cast parts: *Mould concept drawing*. Concept layouts for quotation and PO reference; the 3D model is the master.
- **PO pack (ZIP)**: Tool cost → *⬇ PO pack*: `01_part` (STEP, drawing), `02_tool` (per stage drawing, cost PDF, BOM Excel; all
  stages; blank / strip DXF, tool pack), `03_cost` (RM and part cost), `README.txt`.
- Rebuild the PDF after a change of screens: `python docs/work_instruction/build_work_instruction.py` (needs Node.js with
  Playwright, and pdftoppm).

## Tool design in 3D, drawings, simulation report and video, 3D correction (stage 27)

- **Flat pattern of bent parts** (`unfold.py`): the part is unfolded from its 3D model (both rounded and sharp bends): real outline,
  holes with their positions, bend lines with angle, inside radius and direction. Developed length = angle × (inside radius +
  k-factor × t), k-factor in Mould & die database → Design rules. Used by the blank / strip DXF, the dies and the forming report.
- **Tool design** (Tool cost → *Tool design*): `tool_design.py` designs every die stage in 3D (bottom / top shoe, guide pillars and
  bushes, die plate with the blank outline or the holes + clearance, backing plates, stock guides or nest, fixed stripper, punch
  holder, blanking punch = outline − clearance, round piercing punches with heads, V-die and blade for bending, screws, dowels);
  `mould_design.py` the mould (core and cavity = blocks − part × (1 + shrinkage), parting plane at the open side (blow: middle),
  A / B plates with pockets, clamp and support plates, spacer blocks, ejector plates, ejector pins up to the core surface, return pins,
  sprue bush, locating ring, cooling channels kept clear of the part). Every size comes from the tool cost (die set / mould base,
  inserts) and **Design rules** (clearance %, fits, plate and pillar sizes, screw / dowel sizes, tolerances, finishes, shrinkage).
- **Drawings** (`tool_drawings.py`): drawing set PDF (assembly sheet with iso, exploded and section views and the BOM; a detail sheet
  per made part with views, overall dimensions, hole table from the datum corner with fits and depths, tolerances, material,
  hardness, heat treatment, finish) and DXF of every sheet at 1:1. **Release pack** ZIP: assembly STEP, STEP per part, PDF, DXF, BOM.
- **Drawing frame** (`drawing_style.py`): logo, company, drawing number, revision, general tolerance, projection symbol, scale,
  sheet, drawn / checked / approved and notes on every drawing (part, tool concept, tool design, blank and strip DXF). Set on
  **Admin → Drawings** (upload your logo); in DXF the logo is drawn as hatches so it stays inside the file.
- **Simulation report and video** (`sim_report.py`): sheet metal - PDF with every formability check OK / FAIL, blank and yield,
  stages with force and press, a picture after every stage, flat pattern with bend lines; MP4 video of blanking, piercing and the
  bends folding (a failing bend in red). Plastic / die casting - MP4 of the wall, draft and risk maps. Videos need ffmpeg:
  `imageio-ffmpeg` (in requirements) brings it; without it an animated GIF is made.
- **Correct the 3D model** (`part_fix.py`): a bend whose inside radius is below the minimum gets the new radius with the outside
  size kept (new bend axis, corner rebuilt; checked: one solid, volume close); holes below the minimum are opened up. Preview
  (before / after and the bend profile), corrected STEP, and **Release as new revision** (old revisions stay, costs recalculated).
- All results are first-cut designs and analytical estimates by rules: the tool designer checks and completes them before release
  (see the audit PDF in Help → Documents).

## Large parts and the remaining tool types (stage 28)

- **Large parts (10-20 kg):** Master data → Machines has moulding machines to 4000 t (IMM-650 … IMM-4000), presses to 3000 t
  (PRESS-630 … PRESS-3000) and HPDC to 2500 t, with prices and consumables in every country (EXAMPLE). Mould bases to 2200 mm,
  heavy die sets to 4800 × 2400 and die-casting holders to 1600 mm are "made to order" (cost 0 → priced by weight). When no base
  takes more than one part, Stage C gives one cavity ("large part"); a blank larger than every sheet uses the large sheet in
  Parameters (`large_sheet_length_mm` × `large_sheet_width_mm`, 4000 × 2000). The try-out press / machine must fit by **force and
  bed / platen size**. Samples: `large_plastic_tub.step` (11.9 kg PP), `large_sheet_tray.step` (16.6 kg drawn tray),
  `large_sheet_channel.step` (18.3 kg U channel).
- **Sheet metal:** drawn parts (doubly curved walls) are recognised: blank → draw → trim; 3D **draw die** (punch, die, blank holder,
  cushion pins), **trim die**, **U-bending die** (pressure pad, springs, gauge pins), forming stations in progressive dies.
- **Moulds** (`mould_features.py`): sprue gate, cold runner with edge gates or hot-runner manifold and nozzles; **slides** (heel
  block, angle pin) and **lifters** where the analysis finds undercuts; die casting **shot sleeve, biscuit, runners, overflows and
  vacuum vents**; EPS **steam chambers, back plates, fill injectors, steam vents**; blow **neck and base inserts, blow pin**.
- **Foundry:** tool cost of the pattern equipment and its 3D design (match plate, cope / drag patterns with gating and riser,
  core box, flasks and pins). Simulation PDF + video for **EPS, blow moulding and foundry** (rules in Simulation rules).
- **Draft correction:** moulded parts get the draft added to the walls in 3D (default = minimum draft + 0.5°) and are released as a
  new revision; wall and rib changes stay in CAD.

## Head of department and data access by tool group (stage 30)

- **Roles:** viewer < engineer < approver < **head** < admin. *Head* (head of department) sees and changes the data of every tool group and
  every user, like an admin, but does not manage login IDs (role defaults and per-user overrides are managed by admins).
- **Tool groups:** Admin → Users, roles & permissions has check boxes per login ID: *Plastic moulding, Die casting, Foundry, Sheet metal, EPS, Blow moulding*.
  A viewer, engineer or approver with groups ticked sees only the parts whose process belongs to those groups, and the projects that hold
  such parts, that they created themselves, or that have no tool-group part yet; opening another group's part or project gives "not your tool
  group". They can give a part only a process of their own groups. Parts without a tool group (assemblies, bought-out, machined) are seen by all.
- **Change of responsibility:** example: today *user1* has Sheet metal and EPS, *user2* Die casting and Plastic; in six months the admin ticks
  Die casting and EPS for user1 and Sheet metal and Plastic for user2. The data stays where it is; each user now sees the other groups.
- An ID with no group ticked sees everything (as before this stage), so existing IDs keep working until the admin sets their groups.
  The project dashboard totals still include all parts of an open project. With logins off (`DTC_MODE=local`) there are no limits.
- Code: `backend/app/scope.py`; `users.groups` (added to an existing database automatically). Tests: `tests/test_scope.py`.

## Technical data, release and revision history on the tool drawings (stage 31)

- **On every detail drawing** of the tool design (PDF drawing set and DXF): a *Technical data* block with material grade and hardness
  (from the tool BOM, change them there), **heat treatment** (hardened grades: the Design rules note), **surface treatment**,
  **surface roughness Ra** (Design rules `finish_general`), the **ISO 2768 general tolerance class** with its **linear and angular tables**
  (new master-data table *Mould & die database → General tolerances*, EXAMPLE values: check against your copy of ISO 2768-1) and your
  **note points**. The tool BOM Excel gets the same columns.
- **Review and change:** part panel → Tool design → *Drawing data*: one row per made part of every tool (heat and surface treatment, class,
  Ra, note points; *Save drawing data*), or *Drawing data sheet (Excel)*: change the coloured columns and upload it again.
  API: `GET / PUT /api/parts/{id}/drawing-data`, `GET …/drawing-data.xlsx`, `POST …/drawing-data/upload`.
- **Release date and approved by** come from the **design loop**: the drawings are released when the part reaches the last status
  (*Tool design frozen*): the date and the user who set it are printed (*Released*, *Approved*). Before that the title block says
  **NOT RELEASED** with the current status; *Approved* keeps the name from Admin → Drawings. Released data is locked: step the design loop
  back to change it.
- **Revision history** under the title block (PDF) and above it (DXF): part revisions, releases and every technical-data change of that
  drawing (date, change, by). The part drawing, tool concept drawing, blank and strip-layout DXF and the tool pack PDF get the release and
  the history of the part too.
- Code: `backend/app/drawing_data.py`, `drawing_style.py` (title block), `tool_drawings.py`; tables `tool_drawing_data`, `tool_drawing_edits`.
  Tests: `tests/test_drawing_data.py`.

## A tolerance on every dimension of the tool drawings (stage 32)

- Every dimension of a detail drawing (PDF and DXF) carries its tolerance, taken from what the design already assumes
  (Mould & die database → Design rules of the part type):
  overall length and width: **ISO 2768** of the drawing's class by size (`397.4 ±0.5`); plate thickness: `plate_thk_tol` (`±0.02`);
  fitted holes: the hole fit in their label (`Ø10 m6 / H7 dowel` → `H7 +0.015/0`) with **position** `position_tol` (`±0.01`);
  tapped holes: `thread_class` (`M10 … 6H`); other holes: `hole_clear_tol` (general by the diameter) and position general by the coordinate;
  openings: their own tolerance (`die_opening_tol`, `+0.01/0`). The hole table gets the columns *Ø tol.* and *Pos. ±*.
- Fit limits come from the new master-data table **Fit tolerances** (ISO 286: H6, H7, H8, h6, h7, g6, f7, k6, m6 by size range;
  EXAMPLE values from memory: check them against your copy of the standard). New Design rules rows: `thread_class`, `hole_clear_tol`.
- **mm or µm** per part (`H7 +15/0 µm`, `±20 µm`): *Drawing data* → *Dimension tolerances* → *Shown in*.
- **Change any tolerance** on the part panel (*Drawing data* → *Dimension tolerances*: L, W, H, H1, H1@pos, O1 …) or in the Excel sheet
  *Dimension tolerances*: `general`, `class`, a fit (`H7`, `g6`, `k6` …), `±0.02`, `+0.02/-0.01` or a thread class (`6H`); empty = as drawn.
  Each change is in the revision history. Code: `backend/app/dim_tolerances.py`. Tests: `tests/test_dim_tolerances.py`.

## The production machine of the tool (stage 33)

- **Asked first:** part panel → Tool design → *Make the tool design* opens *Which machine will this tool run on in production?* the first time
  (later: *Production machine…*). Moulding (plastic, die casting, EPS, blow): clamp tonnage, tie-bar clear distance H × V, smallest and largest
  mould height, opening stroke, ejector stroke, locating ring; press (sheet metal): tonnage, bolster L × W, smallest and largest shut height, stroke;
  foundry: flask L × W × H. Or pick a machine of Master data → Machines (its tonnage and platen / bed are filled in). Empty = not checked.
- **Checked:** every tool of the design (its force from the tool cost, its base / die set from the tool cost, its shut / mould height from the
  3D tool design, the part height for the strokes) against the machine: *tool needs / machine has / ok*, with what to do: a **riser / parallel of
  x mm** when the tool is lower than the machine takes, a bigger machine, fewer cavities, a longer stroke.
- **Skipped:** the software gives the machine the tool needs (tonnage + margin, tie bars / bolster, height range, strokes; margins in the new
  Design rules rows `rec_tonnage_margin_pct`, `rec_platen_margin_mm`, `rec_height_margin_mm`, `rec_stroke_factor`, `rec_stroke_extra_mm`, EXAMPLE)
  and the **nearest machine** of Master data → Machines.
- The result is one line in the notes of the drawing set and the release pack. The tool cost and its try-out machine (stages 4 and 28) are not
  changed, and the 3D design is not re-shaped by the machine (the advice says what to add). API: `GET / PUT /api/parts/{id}/machine`,
  `GET /api/parts/{id}/machine-check`. Code: `backend/app/machine_spec.py`. Tests: `tests/test_machine_spec.py`.

## Process parameters for the best part quality (stage 34)

- **Part panel → Process parameters → Work out** (also *Excel* and *PDF*): the machine settings for the first trial, each with its value,
  range and why: injection moulding (melt and mould temperature, fill time, injection rate, injection pressure, hold pressure and time,
  cooling time, back pressure, clamp force, ejection temperature, drying, cycle), die casting (metal and die temperature, slow and fast shot speed,
  fill time, intensification pressure, dwell, spray, clamp force), sheet metal (press tonnage, blank-holder force, strokes per minute, die
  clearance, overbend, draw speed), foundry (pouring temperature, poured weight, pouring time, solidification, shake-out), EPS (steam pressure,
  steaming and cooling time) and blow moulding (preform temperature, pre-blow and blow pressure, mould temperature and cooling).
- Worked out from the **simulation of the part** (fill, cooling and solidification time, flow ratio, injection pressure, clamp force and the thin /
  sink-risk / low-draft / undercut maps) or the **sheet-metal forces** (stages, draw ratio, springback), and the **material window**.
  Thin walls, sink-risk sections, long flow, low draft, undercuts, draw ratio and springback become **quality warnings with the remedy**.
- New master-data tables (Mould & die database): **Process windows** (temperatures and drying per material) and **Process parameters**
  (one formula row per setting, with min and max; `risk` rows for the warnings). All EXAMPLE values until you replace them with your shop's.
  The simulation (its rules and results) is not changed: the setting sheet uses the material window on top of it.
- API: `GET /api/parts/{id}/process-parameters` (`.xlsx`, `.pdf`). Code: `backend/app/process_params.py`. Tests: `tests/test_process_params.py`.

## Logo and name on every Excel and PDF download (stage 35)

- Every Excel the software hands out gets a picture with the **logo and the company name** (Admin → Drawings: your logo and company; default
  *Design to Cost*) to the right of the used cells of the first sheet, and the name in the **print header** of every sheet. No cell is moved or
  written, so the layout and values stay as each exporter made them (on paper the picture is on the page right of the data).
- PDFs that do not show the name yet get the logo and name in the top margin of every page (drawings and reports that already have the title
  block / header are left as they are). ZIP packs: the same for the Excel and PDF files inside.
- Files meant to be uploaded again stay plain: master-data, mould & die, costing setup, rates and register setup downloads, the import template
  and the price master export. Code: `backend/app/branding.py` (middleware in `main.py`). Tests: `tests/test_branding.py`.

## AI assistant: Ask AI (stage 37)

- **Ask AI** (bottom right of every page) answers questions in plain language, for example *What is the part cost of 1023 and what
  drives it?*, *Compare the tool cost of 1023 in India and China*, *Which parts of project X are over their target?*, *Send me the tool
  drawing and the PO pack of 1023*. It looks the numbers up in your projects, costs, traces and rates, says where they come from (rate and
  month, EXAMPLE rates, outdated costs) and gives files as **download links** (cost PDF / Excel, drawings PDF / DXF, tool design ZIP / STEP,
  simulation report and video, PO pack).
- **Who:** everyone who is logged in. The assistant sees **only what that user may see**: it reads through the app's own GET routes with the
  user's own login, so role and tool groups (stage 30) apply exactly as on the screens. A part of another tool group is refused the same way.
- **Read only:** it can never approve, change, recalculate or delete anything; for that it tells you which page and button to use.
- **Admin → AI assistant** (admin only): switch it on for all users, choose the model (*Claude Opus 5.5*, recommended; *Sonnet 5.5*, faster
  and about half the cost; *Haiku 5.5*, lowest cost for simple questions), enter the **Anthropic API key** (from console.anthropic.com; usage
  is billed to that account) and *Test the key*. The key is kept in the project database (`data/`, never in GitHub) and only its last 4
  characters are shown again. Backups contain it, so keep backup files safe. Without a saved key, `ANTHROPIC_API_KEY` on the server is used.
- **What leaves the PC:** the question and the data the assistant looks up for it are sent to Anthropic to write the answer. Every question
  (not the answer) is written to the **Activity log** (what: *bot*).
- The chat stays in the browser tab; *New chat* clears it. Code: `backend/app/bot.py`, `frontend/bot.js`, `frontend/bot.css`.
  Tests: `tests/test_bot.py` (a stand-in for Claude, so no key or internet is needed).

## End-to-end audit (run before every release)

`python scripts/audit_e2e.py` drives the whole tool through its API like a user, on temporary copies of the master data (your data is not touched):
upload → register → RM cost → tool cost → simulation → tool design and drawings → drawing data → machine → process parameters → part cost →
country comparison → PO pack → project dashboard and leader view, for every tool group at low and high volume, large parts, insert moulding and a
machined part; then the exports, master-data round trips, wrong input (robustness) and logins with roles and tool groups. Every file is opened
(PDF, Excel, DXF, STEP, ZIP), every cost must be positive, no NaN, nothing slower than 60 s. Report: `docs/audit_e2e_report.md`.
`--only plastic` runs the cases whose name contains the word; `--robust` only the wrong-input checks.

## Machined parts: bar stock, machining time, machine and fixture (stage 37)

Parts with the process **Machined** (shafts, pins, bushes, blocks, brackets cut from bar or plate) are now costed end to end, like the
moulded and pressed parts: RM → machining & fixture → part cost → country comparison → project leader view → Excel / PDF.

- **Turned or milled** is read from the 3D model: the share of the surface that turns about one axis (cylinders, cones, shoulders and end
  faces) ≥ *Parameters → turned_min_round_share* (0.8) → **turned on the CNC lathe**, else **milled on the machining centre** (machines:
  *Parameters → machine_turned / machine_milled*). Drilled holes (up to *hole_max_dia_mm*) are found in the model; bores on the turning
  axis are turned, not drilled. You can type the route over on the part.
- **Bar stock** = the smallest standard size of *Mould & die database → Stock sizes* that holds the part with the allowances of
  Parameters: round bar (or hex) above the largest turned Ø + *dia_allowance_mm*; for a milled part the lightest of square bar, flat bar
  or plate (cut to width) above the part + 2 × *mill_allowance_mm*; cut length = part length + facing allowances + *cut_off_mm*.
  Example: a Ø40 × 110 shaft → round bar Ø45 × 116.
- **RM cost** (scope `rm_machined`): stock volume × density → + bar end loss → gross weight × bar rate − chips × scrap rate × chips sold %.
  Six bar grades seeded (EN1A free-cutting, EN8 / C45, EN19 / 42CrMo4, SS304, Al 6061-T6, brass CW614N) with rates for all 9 countries.
- **Machining time** (scope `machining`, *Countries, machines & formulas*): volume machined away ÷ rough removal rate + surface ÷ finish rate
  + drilled depth ÷ feed (rates per material in *Mould & die database → Machining data*) + tool changes and rapids + loading per set-up +
  set-up ÷ batch. The part cost uses this time as its cycle and the MHR of the lathe / machining centre.
- **Fixture**: set-ups × fixture rate (rate library *process_unit / Machining fixture (per set-up)*; soft jaws for turned parts = 0.3 of it),
  one set per machine needed for the annual volume → **fixture CAPEX**. It is stored as a version like a tool cost (part panel →
  *Machining & fixture*), so it is in the tool CAPEX, the CAPEX plan, the dashboard and the country comparison (HS 8487 part, 8466 fixture).
  The lathes and machining centres needed appear in the **machine CAPEX** of the project leader view.
- **Part panel → Machining & fixture**: route and machine with the reason, bar stock, holes, roughing / finishing / drilling time, machining
  time per part, machines needed, fixture cost and CAPEX; every value clickable to its formula and source. *Machining inputs*: route,
  stock shape (round, hex, square, flat, plate) and set-ups per part; they change the RM cost too. Excel and PDF sheet with all steps,
  inputs and rate versions.
- Everything new is added, nothing changed: the process *Machined* got the part type `machined` (it was empty), new Materials and
  Parameters rows, the tables *Stock sizes* and *Machining data*, the formulas of `rm_machined` and `machining`, and EXAMPLE rates
  (bar, chips, fixture, duty). All EXAMPLE until you replace them. Samples: `samples/machined_shaft.step`, `samples/machined_block.step`.
- Code: `backend/app/machining.py` (seed, stock search, machining & fixture), `geometry.machining_features`. Tests: `tests/test_machining.py`.

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
backend/app/machining.py      Machined parts (stage 37): bar stock search, machining time, machine, fixture
backend/app/rm_cost.py        RM engine: gross weight, yield, RM cost, scrap credit from master-data formulas, fully traced
backend/app/capacity.py       Stage C: cavities, tools, tool life, machine hours
backend/app/master_data.py    Reads, checks and saves master_data.xlsx
backend/app/mould_db.py       Mould & die tables in the costing database
backend/app/mould.py          Mould sizing (layout, insert, base) from the database
backend/app/example_values.py Replace example values checklist: counts by category, replace / keep rates and rows
backend/app/price_master.py   Price master: month-wise price grid by country (tool materials, part materials, scrap), Excel
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
backend/app/bot.py            AI assistant (Ask AI): read-only tools over the app's own GET routes, Claude API, settings
backend/app/main.py           FastAPI web server: all /api endpoints + serves the pages
master_data/                  master_data.xlsx and costing_db.sqlite (your editable data)
frontend/index.html           Estimator page (form + results + 3D viewer)
frontend/app.js               Estimator logic and three.js viewer
frontend/master-data.*        Master data page (editor for both data sets)
frontend/help.*               Help page
frontend/examples.*           Replace example values checklist (Master data)
frontend/prices.*             Price master (Master data): month-wise prices by country
frontend/rates.*              Rates page (MHR & labour, rate library, rate review)
frontend/dashboard.*          Project dashboard
frontend/parts.*              Part register (search, part details, revisions, history)
frontend/import.*             Import: STEP part / assembly split, Excel bulk upload
frontend/common.js, register.css  Shared helpers and layout of the register pages
frontend/trace.js             Traceability panel used by every page
frontend/bot.js, bot.css      AI assistant chat panel on every page (loaded by auth.js when switched on)
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
