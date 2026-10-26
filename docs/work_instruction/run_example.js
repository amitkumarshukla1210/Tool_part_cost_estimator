// Runs the work-instruction example in the real app and keeps the screenshots and the downloads.
//   node docs/work_instruction/run_example.js <base url> <out dir> <repo dir>
// Used by build_work_instruction.py (which starts the app on an empty data folder first).
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const [B, OUT, REPO] = process.argv.slice(2);
const shots = [];
const PW = "Example password 2026";

(async () => {
  fs.mkdirSync(path.join(OUT, "shots"), { recursive: true });
  fs.mkdirSync(path.join(OUT, "outputs"), { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const p = await ctx.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  const wait = (ms) => p.waitForTimeout(ms);
  const shot = async (name, caption, target) => {
    const file = path.join(OUT, "shots", `${String(shots.length + 1).padStart(2, "0")}_${name}.jpg`);
    if (target) await target.scrollIntoViewIfNeeded().catch(() => {});
    await wait(400);
    await p.screenshot({ path: file, type: "jpeg", quality: 72 });
    shots.push({ file: path.basename(file), caption });
  };
  const top = async (sel) => {                 // scroll the part panel so that `sel` is at the top
    await p.locator(sel).first().evaluate((e) => e.scrollIntoView({ block: "start" }));
    await wait(300);
  };
  const save = async (url, name) => {
    const r = await p.request.get(B + url, { timeout: 300000 });
    if (!r.ok()) throw new Error(`${url}: ${r.status()} ${await r.text()}`);
    fs.writeFileSync(path.join(OUT, "outputs", name), await r.body());
    return name;
  };
  const api = async (method, url, data) => {
    const r = await p.request.fetch(B + url, { method, data });
    if (!r.ok()) throw new Error(`${method} ${url}: ${r.status()} ${await r.text()}`);
    return r.json();
  };

  // 1 · first start: the admin
  await p.goto(B + "/dashboard");
  await p.fill("[name=name]", "Amit Shukla");
  await p.fill("[name=password]", PW);
  await p.fill("[name=password2]", PW);
  await shot("setup", "First start: create the admin ID (only once).");
  await p.click("button[type=submit]");
  await p.waitForURL("**/admin**");
  await p.fill("#newUser [name=username]", "ravi.engineer");
  await p.fill("#newUser [name=name]", "Ravi (engineer)");
  await p.fill("#newUser [name=password]", "Engineer password 1");
  await p.click("#newUser button[type=submit]");
  await wait(800);
  await shot("admin_users", "Admin → Users & roles: create a login ID for each team member.");

  // 2 · project and variant
  await p.goto(B + "/dashboard");
  await wait(800);
  await p.click("#emptyNew");
  await p.fill("#projectForm [name=code]", "EX26");
  await p.fill("#projectForm [name=name]", "Example bracket programme");
  await p.fill("#projectForm [name=customer]", "Internal");
  await p.fill("#projectForm [name=capex_budget_inr]", "1500000");
  await p.fill("#projectForm [name=sop_date]", "2027-06-01");
  await shot("project", "Dashboard → + New project: code, name, customer, CAPEX budget, SOP date.");
  await p.click("#projectForm button[type=submit]");
  await wait(1200);
  await p.click("#newVariant");
  await p.fill("#variantForm [name=code]", "STD");
  await p.fill("#variantForm [name=name]", "Standard");
  await p.fill("#variantForm [name=target_bom_cost_inr]", "120");
  await p.fill("#variantForm [name=annual_volume]", "200000");
  await p.click("#variantForm button[type=submit]");
  await wait(1200);

  // 3 · import Rev A
  await p.goto(B + "/import");
  await wait(1000);
  await p.setInputFiles("#stepForm [name=file]", path.join(REPO, "samples", "example_bracket_revA.step"));
  await p.click("#stepForm button[type=submit]");
  await p.waitForSelector("#tree tr[data-key]", { timeout: 60000 });
  await p.selectOption("#tree select[name=material]", "Galvanised steel GI");
  await wait(600);
  await p.fill("#tree input[name=part_code]", "EX26-0001").catch(() => {});
  await p.fill("#tree input[name=name]", "L mounting bracket").catch(() => {});
  await shot("import", "Import → STEP file: read the 3D model, choose the material; the process is suggested with its reason.");
  await p.click("#commitForm button[type=submit]");
  await p.waitForSelector("#commitStatus a", { timeout: 120000 });
  const parts = await api("GET", "/api/parts?q=EX26");
  const pid = parts.rows[0].id;
  await save(`/api/parts/${pid}`, "_part.json");

  // 4 · the part
  await p.goto(B + `/parts?part=${pid}`);
  await wait(6000);
  await shot("parts", "Parts: the register with status, process, material, volume, RM and tool cost.");
  await p.click("#panelFull").catch(() => {});
  await wait(500);
  await top("#panelBody h3.block-title");
  await shot("part_geometry", "The part: details, suggested process, geometry from the 3D model and the Part drawing (PDF · DXF).");
  await save(`/api/parts/${pid}/drawing.pdf`, "EX26-0001_part_drawing_revA.pdf");

  // 5 · design loop: concept tool → simulation → corrections required
  await top('h3:has-text("Design loop")');
  await shot("loop_uploaded", "Design loop at Uploaded: the forming simulation result is already shown (Rev A: bend radius too tight).");
  const move = async (status, comment = "") => {
    await p.selectOption("#loopForm select[name=status]", status);
    await p.fill("#loopComment", comment);
    await p.click("#loopForm button[type=submit]");
    await wait(5000);
  };
  await move("concept_tool", "Concept tool proposed by the software (dies per stage)");
  await top('h4:has-text("Dies suggested")');
  await shot("dies", "Tool cost: the dies suggested stage-wise (die set, die plate, press, cost) with drawing and cost downloads per die.");
  await top('h3:has-text("Sheet-metal tools")');
  await shot("sheet_tools", "Sheet-metal tools: operations in order with forces and presses, and the developed blank with its material yield.");
  await top('h3:has-text("Design loop")');
  await move("simulation", "Forming simulation run");
  await top('h3:has-text("Design loop")');
  await p.click("#simToLoop");
  await wait(500);
  await shot("loop_correction", "Simulation: 1 correction required → “Put this result in the Design loop form” fills Corrections required and the comment.");
  await p.click("#loopForm button[type=submit]");
  await wait(5000);
  await save(`/api/parts/${pid}/forming-simulation.pdf`, "EX26-0001_revA_forming_simulation.pdf");
  await save(`/api/parts/${pid}/forming-simulation.video`, "EX26-0001_revA_forming_simulation.mp4");
  await top('.sim-result');
  await p.click("#fixOpen");
  await p.waitForSelector("#fixOut img", { timeout: 60000 });
  await wait(4000);
  await top("#fixForm");
  await shot("fix_3d", "Correct the 3D model in the software: new bend radius, before / after with the bend profile, corrected STEP; release as a new revision.");
  await save(`/api/parts/${pid}/correction.png`, "EX26-0001_revA_correction_preview.png");
  await save(`/api/parts/${pid}/correction.step`, "EX26-0001_corrected_from_revA.step");

  // 6 · Rev B uploaded → revised → simulation OK → frozen
  await top('h3:has-text("Upload a new revision")');
  await p.setInputFiles("#revForm [name=file]", path.join(REPO, "samples", "example_bracket_revB.step"));
  await p.fill("#revForm [name=rev]", "B");
  await p.fill("#revForm [name=change_note]", "Inside bend radius 0.5 → 2 mm (forming simulation)");
  await shot("revision", "Upload the corrected model as Rev B with what changed; the status moves to Revised by itself.");
  await p.click("#revForm button[type=submit]");
  await wait(9000);
  await top('h3:has-text("Design loop")');
  await move("simulation", "Rev B re-simulated");
  await top('h3:has-text("Design loop")');
  await shot("loop_ok", "Rev B: No corrections required → Simulation OK, then Tool design frozen.");
  await p.click("#simToLoop");
  await wait(300);
  await p.click("#loopForm button[type=submit]");
  await wait(5000);
  await move("tool_design_frozen", "Concept frozen for quotation");
  await top('h3:has-text("Design loop")');
  await p.locator('summary:has-text("What changed, who, when")').first().click();
  await wait(500);
  await shot("loop_frozen", "Tool design frozen: the timeline keeps every status change and revision with who, when and why.");

  // 6b · detailed tool design: every die stage in 3D with drawings
  await top("#tdBox");
  await p.click("#tdBox summary");
  await p.click("#tdRun");
  await p.waitForSelector("#tdOut .card img", { timeout: 180000 });
  await wait(9000);
  await top("#tdBox");
  await shot("tool_design", "Tool design: each die stage in 3D with every part (material, hardness, standard parts), assembly STEP, drawing set and release pack.");
  await save(`/api/parts/${pid}/tool-design.zip`, "EX26-0001_tool_design_release_pack.zip");
  await save(`/api/parts/${pid}/tool-design.pdf?die=blank`, "EX26-0001_T01_blanking_die_drawing_set.pdf");
  await save(`/api/parts/${pid}/tool-design.step?die=blank`, "EX26-0001_T01_blanking_die_assembly.step");
  await save(`/api/parts/${pid}/forming-simulation.pdf`, "EX26-0001_revB_forming_simulation.pdf");

  // 7 · traceability and correcting a value / grade / base
  const tr = await api("GET", `/api/parts/${pid}/tool-cost/trace`);
  const baseNode = Object.keys(tr.nodes).find((k) => k.endsWith("__base__:cost_inr"));
  await p.evaluate(([t, n]) => window.TracePanel.open(t, n, traceCtx("tool")), [tr, baseNode]);
  await wait(1800);
  await shot("trace_base", "Traceability: click any value. Die set price: pick another die set for this part or add a row to master data.");
  const steel = Object.keys(tr.nodes).find((k) => /:steel:D2/.test(k));
  await p.evaluate(([t, n]) => window.TracePanel.open(t, n, traceCtx("tool")), [tr, steel]);
  await wait(1800);
  await shot("trace_grade", "Steel grade: why it was chosen, the grade drop-down with the price per kg, change it for the ticked lines.");
  const ovh = Object.keys(tr.nodes).find((k) => tr.nodes[k].source?.rate?.item === "tool_overhead_pct");
  await p.evaluate(([t, n]) => window.TracePanel.open(t, n, traceCtx("tool")), [tr, ovh]);
  await wait(1200);
  await shot("trace_value", "Any default value: “For this part only” or “Save for the future” (rate library / master data); reset any time.");
  await p.click(".trace-close");

  // 8 · supplier and quote
  await api("POST", "/api/suppliers", { name: "Precision Press Tools Pvt Ltd", country: "IN", city: "Pune", commodities: "press tools, stamping",
    contact_person: "Mr. Patil", email: "sales@example.com", certifications: "IATF 16949", quality_score: 85, delivery_score: 80, cost_score: 75 });
  const sups = await api("GET", "/api/suppliers");
  await api("POST", `/api/parts/${pid}/suppliers`, { supplier_id: sups.suppliers[0].id, piece_price: 32, tool_price: 950000, quote_ref: "Q-2026-118", quote_date: "2026-10-20" });
  await p.goto(B + "/suppliers");
  await wait(1200);
  await shot("suppliers", "Suppliers: supplier master with automatic codes, status, capability and rating.");
  await p.goto(B + `/parts?part=${pid}`);
  await wait(6000);
  await top('h3:has-text("Suppliers & quotes")');
  await shot("quotes", "On the part: the supplier's quoted piece and tool price against our should-cost.");

  // 9 · country comparison
  await top('h3:has-text("Country comparison")');
  await p.click('[data-cmpall="0"]');
  for (const c of ["IN", "CN", "TH", "VN"]) await p.check(`#cmpForm input[name=country][value=${c}]`);
  await p.click("#cmpForm button[type=submit]");
  await p.waitForSelector("#cmpOut table", { timeout: 120000 });
  await top('h3:has-text("Country comparison")');
  await shot("countries", "Country comparison: tick the countries; part and tool cost ex-works and landed in India, cheapest marked.");

  // 10 · downloads for the PO
  const t2 = await api("GET", `/api/parts/${pid}/tool-cost/trace`);
  for (const [k, d] of t2.dies.entries()) {
    await save(`/api/parts/${pid}/tool-drawing.pdf?die=${d.key}`, `EX26-0001_stage${k + 1}_${d.key}_tool_drawing.pdf`);
    await save(`/api/parts/${pid}/tool-drawing.dxf?die=${d.key}`, `EX26-0001_stage${k + 1}_${d.key}_tool_drawing.dxf`);
    await save(`/api/parts/${pid}/tool-cost/export.pdf?die=${d.key}`, `EX26-0001_stage${k + 1}_${d.key}_tool_cost.pdf`);
  }
  await save(`/api/parts/${pid}/drawing.pdf`, "EX26-0001_part_drawing_revB.pdf");
  await save(`/api/parts/${pid}/drawing.dxf`, "EX26-0001_part_drawing_revB.dxf");
  await save(`/api/parts/${pid}/tool-cost/export.pdf`, "EX26-0001_tool_cost_all_stages.pdf");
  await save(`/api/parts/${pid}/rm-cost/export.pdf`, "EX26-0001_rm_cost.pdf");
  await save(`/api/parts/${pid}/sheet-layout/tool-pack.pdf`, "EX26-0001_tool_pack.pdf");
  await save(`/api/parts/${pid}/sheet-layout/blank.dxf`, "EX26-0001_blank.dxf");
  await save(`/api/parts/${pid}/po-pack.zip`, "EX26-0001_PO_pack.zip");
  await top("p.downloads a.btn");
  await shot("po_pack", "Downloads: tool drawings per stage, cost sheets and the PO pack (ZIP) with everything for the toolmaker.");

  // 11 · a plastic part: mould
  await p.goto(B + "/import");
  await wait(1000);
  await p.setInputFiles("#stepForm [name=file]", path.join(REPO, "samples", "plastic_cover.step"));
  await p.click("#stepForm button[type=submit]");
  await p.waitForSelector("#tree tr[data-key]", { timeout: 60000 });
  await p.selectOption("#tree select[name=material]", "ABS");
  await wait(500);
  await p.fill("#tree input[name=part_code]", "EX26-0002").catch(() => {});
  await p.click("#commitForm button[type=submit]");
  await p.waitForSelector("#commitStatus a", { timeout: 120000 });
  const pl = (await api("GET", "/api/parts?q=EX26-0002")).rows[0].id;
  await p.goto(B + `/parts?part=${pl}`);
  await wait(6000);
  await top('h3:has-text("Tool cost")');
  await shot("mould", "Plastic part: mould tool cost with mould base, steel grades from Grade rules, and the mould concept drawing.");
  await save(`/api/parts/${pl}/tool-drawing.pdf`, "EX26-0002_mould_drawing.pdf");
  await save(`/api/parts/${pl}/drawing.pdf`, "EX26-0002_part_drawing.pdf");
  await top("#tdBox");
  await p.click("#tdBox summary");
  await p.click("#tdRun");
  await p.waitForSelector("#tdOut .card img", { timeout: 180000 });
  await wait(9000);
  await top("#tdBox");
  await shot("mould_design", "Mould design: core and cavity cut from the part with shrinkage, plates, ejection, cooling, standard parts - 3D and drawings.");
  await save(`/api/parts/${pl}/tool-design.pdf`, "EX26-0002_mould_drawing_set.pdf");
  await save(`/api/parts/${pl}/tool-design.zip`, "EX26-0002_mould_release_pack.zip");
  await save(`/api/parts/${pl}/simulation/report.pdf`, "EX26-0002_simulation.pdf");
  await save(`/api/parts/${pl}/simulation/video`, "EX26-0002_simulation.mp4");

  // 12 · project view and activity
  await p.goto(B + "/dashboard");
  await wait(2500);
  await shot("dashboard", "Dashboard: BOM cost vs target, tool CAPEX vs budget, status of parts, CAPEX plan.");
  await p.goto(B + "/admin?tab=activity");
  await wait(1500);
  await shot("activity", "Admin → Activity log: who changed what and when (Excel export).");
  await p.goto(B + "/admin?tab=drawings");
  await wait(1500);
  await shot("admin_drawings", "Admin → Drawings: your logo, company, projection, checked / approved by and notes on every drawing.");

  fs.writeFileSync(path.join(OUT, "shots.json"), JSON.stringify({ shots, errors }, null, 1));
  await browser.close();
  console.log(`${shots.length} screenshots, ${fs.readdirSync(path.join(OUT, "outputs")).length} outputs, errors: ${errors.length}`);
})().catch((e) => { console.error(e); process.exit(1); });
