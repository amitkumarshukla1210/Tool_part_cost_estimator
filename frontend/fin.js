// Heat-exchanger fin dies (stage 57): fin spec -> fin die cost (BOM) and fin part cost per pack / fin / kg, traced.
const { $, esc, fmt, api, status } = window.DTC;
let opts = null, current = null, last = null, partFile = null, partRead = null;

const inr = (v, d = 0) => (v == null ? "—" : "₹ " + Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }));
const lakh = (v) => (v == null ? "—" : v >= 1e7 ? `₹ ${(v / 1e7).toFixed(2)} crore` : v >= 1e5 ? `₹ ${(v / 1e5).toFixed(2)} lakh` : inr(v));

async function init() {
  opts = await api("/api/fin-dies/options");
  $("fPattern").innerHTML = opts.patterns.map((p) => `<option value="${esc(p.pattern)}">${esc(p.name)}</option>`).join("");
  $("fMaterial").innerHTML = opts.materials.map((m) => `<option>${esc(m)}</option>`).join("");
  $("fCountry").innerHTML = '<option value="">Default country</option>' + opts.countries.map((c) => `<option value="${esc(c.code)}">${esc(c.name)} (${esc(c.currency)})</option>`).join("");
  $("fPress").innerHTML = `<option value="">Default press (${esc(opts.default_press)})</option><option value="auto">Smallest fin press that fits</option>` +
    opts.presses.map((p) => `<option value="${esc(p.machine_id)}">${esc(p.machine_id)} · ${fmt(p.line.capacity_kn / 10, 0)} t · foil ≤ ${fmt(p.line.max_foil_width_mm, 0)} mm · ${fmt(p.line.spm_min, 0)}-${fmt(p.line.spm_max, 0)} SPM</option>`).join("");
  $("fNums").innerHTML = Object.entries(opts.spec).map(([k, [label, unit, , lo, hi]]) =>
    `<label>${esc(label)} (${esc(unit)}) <input type="number" step="any" min="${lo}" max="${hi}" name="${k}" id="n_${k}" /></label>`).join("");
  const projects = await api("/api/projects").catch(() => []);
  $("fProject").innerHTML = '<option value="">None</option>' + projects.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  fill({ name: "", project_id: "", spec: opts.default });
  await loadList();
}

function fill(rec) {
  current = rec.id ? rec : null;
  partFile = rec.part_file || null; partRead = rec.read || null;
  $("partName").textContent = partFile ? `Part file: ${partFile.name}` : "";
  $("readOut").innerHTML = "";
  $("fName").value = rec.name || "";
  $("fProject").value = rec.project_id || "";
  const s = rec.spec;
  $("fPattern").value = s.pattern; $("fMaterial").value = s.material; $("fCountry").value = s.country || ""; $("fPress").value = s.press || ""; $("fStagger").checked = s.staggered !== false;
  Object.keys(opts.spec).forEach((k) => { $("n_" + k).value = s[k] ?? opts.default[k]; });   // fields added later: their default
  ["xlsx", "pdf", "delBtn"].forEach((id) => ($(id).hidden = !current));
  if (current) { $("xlsx").href = `/api/fin-dies/${current.id}/export.xlsx`; $("pdf").href = `/api/fin-dies/${current.id}/export.pdf`; }
}

function spec() {
  const s = { pattern: $("fPattern").value, material: $("fMaterial").value, country: $("fCountry").value, press: $("fPress").value, staggered: $("fStagger").checked };
  Object.keys(opts.spec).forEach((k) => { s[k] = Number($("n_" + k).value); });
  return s;
}

async function loadList(select) {
  const list = await api("/api/fin-dies");
  $("finList").innerHTML = '<option value="">— new fin die —</option>' + list.map((f) =>
    `<option value="${f.id}">#${f.id} · ${esc(f.name)}${f.result ? ` · pack ${inr(f.result.pack_cost_inr, 2)}` : ""}</option>`).join("");
  if (select) { $("finList").value = select; await openFin(select); }
}

async function openFin(id) {
  if (!id) { fill({ name: "", project_id: "", spec: opts.default }); $("out").innerHTML = ""; $("designOut").innerHTML = ""; return; }
  fill(await api(`/api/fin-dies/${id}`));
  await run(() => api(`/api/fin-dies/${id}/cost`));
  await showDesign(id);
}

async function run(call) {
  status($("status"), "Calculating…");
  try {
    last = await call();
    status($("status"), "");
    render(last);
  } catch (err) {
    status($("status"), err.message, "error");
  }
}

function render(r) {
  const d = r.die, p = r.part, sm = r.summary;
  const tv = (src, k, digits = 2) => {
    const n = (src === "die" ? d : p).nodes[k];
    return n ? `<span class="clickable calc" data-src="${src}" data-trace="${esc(k)}">${fmt(n.value, digits)}</span>` : "—";
  };
  const warn = [...d.warnings, ...d.missing, ...p.missing];
  const g = d.die;
  $("out").innerHTML = `
    ${sm.example ? '<p class="note"><span class="badge badge-example">EXAMPLE</span> Uses EXAMPLE rates or master-data rows – not for negotiation. ' + esc(d.example.detail || p.example.detail || "") + "</p>" : ""}
    ${warn.length ? `<div class="warn"><ul>${warn.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
    <div class="fin-kpis">
      <div class="card"><div class="k">Fin die cost (one die)</div><div class="v">${lakh(sm.die_cost_inr)}</div><div class="s">${esc(d.currency)} ${tv("die", d.root, 0)}</div></div>
      <div class="card"><div class="k">Fin pack cost</div><div class="v">${inr(sm.pack_cost_inr, 2)}</div><div class="s">${esc(p.currency)} ${tv("part", p.root, 2)} · ${fmt(p.nodes["calc:fins_per_pack"].value, 0)} fins</div></div>
      <div class="card"><div class="k">Cost per fin</div><div class="v">${inr(sm.per_fin_inr, 4)}</div><div class="s">${esc(p.currency)} ${tv("part", "calc:cost_per_fin", 4)}</div></div>
      <div class="card"><div class="k">Cost per kg of fin</div><div class="v">${inr(sm.per_kg_inr, 2)}</div><div class="s">${esc(p.currency)} ${tv("part", "calc:cost_per_kg", 2)}</div></div>
      <div class="card"><div class="k">Fin press</div><div class="v">${esc(sm.press)}</div><div class="s">needs ${tv("die", d.trial.force_node, 1)} t · ${esc(sm.country)} · ${esc(sm.as_of)}</div></div>
    </div>
    <p class="note">Fin die ${fmt(g.length_mm, 0)} × ${fmt(g.width_mm, 0)} mm, ${fmt(g.stations, 0)} stations, ${fmt(g.holes_per_stroke, 0)} holes per stroke,
      feed ${fmt(g.feed_mm, 1)} mm, foil ${fmt(g.foil_width_mm, 1)} mm (${esc(g.foil_width_note)}), die set ${esc(d.base.size_code)} · pattern ${esc(d.pattern.name)}.
      Click a value for its formula, inputs and rate versions.</p>
    <h3 class="block-title">Fin part cost per pack</h3>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th>Step</th><th>Formula</th><th class="num">Value</th><th>Unit</th></tr></thead><tbody>
      ${p.steps.map((x) => `<tr class="${x.is_result ? "total" : ""}"><td>${esc(p.nodes[x.node].label)}</td><td><code>${esc(p.nodes[x.node].formula || "")}</code></td>
        <td class="num">${tv("part", x.node, 4)}</td><td>${esc(p.nodes[x.node].unit)}</td></tr>`).join("")}
      <tr class="total"><td>Fin pack cost in INR</td><td></td><td class="num">${tv("part", "result:inr", 2)}</td><td>INR</td></tr></tbody></table></div>
    <h3 class="block-title">Fin die BOM</h3>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th>Element</th><th class="num">Qty</th><th>Grade</th><th>Make</th><th class="num">Hours</th><th class="num">Total (${esc(d.currency)})</th></tr></thead><tbody>
      ${d.lines.map((l) => `<tr><td>${esc(l.element)}${l.is_example ? ' <span class="badge badge-example">EX</span>' : ""}</td><td class="num">${fmt(l.quantity, 0)}</td>
        <td>${esc(l.grade)}</td><td>${esc(l.make)}</td><td class="num">${l.nodes.hours ? tv("die", l.nodes.hours, 1) : ""}</td><td class="num">${tv("die", l.nodes.total, 0)}</td></tr>`).join("")}
    </tbody></table></div>
    <h3 class="block-title">Fin die cost</h3>
    <div class="table-wrap"><table class="cost-table"><tbody>
      ${d.steps.map((x) => `<tr class="${x.is_result ? "total" : ""}"><td>${esc(d.nodes[x.node].label)}</td><td class="num">${tv("die", x.node, 0)} ${esc(d.nodes[x.node].unit)}</td></tr>`).join("")}
      <tr class="total"><td>Fin die cost in INR</td><td class="num">${tv("die", "result:inr", 0)} INR</td></tr></tbody></table></div>`;
}

$("finList").addEventListener("change", (e) => openFin(Number(e.target.value) || null));
$("newBtn").addEventListener("click", () => { $("finList").value = ""; openFin(null); });
$("calcBtn").addEventListener("click", () => run(() => api("/api/fin-dies/calculate", { method: "POST", body: JSON.stringify({ spec: spec() }) })));
$("finForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = JSON.stringify({ name: $("fName").value, project_id: Number($("fProject").value) || null, spec: spec(),
    ...(partFile ? { part_file: partFile, read: partRead } : {}) });
  try {
    const rec = current ? await api(`/api/fin-dies/${current.id}`, { method: "PUT", body }) : await api("/api/fin-dies", { method: "POST", body });
    await loadList(rec.id);
  } catch (err) {
    status($("status"), err.message, "error");
  }
});
$("delBtn").addEventListener("click", async () => {
  if (!current || !confirm(`Delete fin die "${current.name}"?`)) return;
  await api(`/api/fin-dies/${current.id}`, { method: "DELETE" });
  await loadList();
  openFin(null);
});
document.addEventListener("click", (e) => {
  const t = e.target.closest("#out [data-trace]");
  if (t && last) window.TracePanel.open(t.dataset.src === "die" ? last.die : last.part, t.dataset.trace);
});
// ---------- stage 58: read the fin from the part file, then the fin die design ----------
const READ_LABELS = { tube_od_mm: "Tube Ø (mm)", hole_d_mm: "Collar / hole Ø (mm)", row_pitch_mm: "Row pitch (mm)", hole_pitch_mm: "Hole pitch (mm)",
  fin_rows: "Fin rows", fin_holes: "Holes per fin", staggered: "Staggered", foil_t_mm: "Foil thickness (mm)", fpi: "FPI", pattern: "Pattern",
  fin_l_mm: "Fin length (mm)", fin_w_mm: "Fin width (mm)" };
$("readBtn").addEventListener("click", async () => {
  const f = $("partFile").files[0];
  if (!f) { status($("status"), "Choose the fin part file (STEP, DXF or PDF) first.", "error"); return; }
  const fd = new FormData();
  fd.append("file", f);
  fd.append("spec", JSON.stringify(spec()));
  status($("status"), "Reading the part file…");
  try {
    const r = await api("/api/fin-dies/read-part", { method: "POST", body: fd });
    partFile = r.file; partRead = r.read;
    fill({ ...(current || {}), id: current && current.id, name: $("fName").value || f.name.replace(/\.[^.]+$/, ""), project_id: $("fProject").value, spec: r.spec, part_file: r.file, read: r.read });
    $("partName").textContent = `Part file: ${r.file.name}`;
    const chk = new Set(r.read.check || []);
    $("readOut").innerHTML = `<div class="note"><b>Read from ${esc(r.read.source)}</b> (${fmt(r.read.holes || 0, 0)} holes) – check the values marked ⚠ and correct them below before you save:
      <div class="table-wrap"><table class="cost-table"><tbody>${Object.entries(READ_LABELS).filter(([k]) => k in r.read).map(([k, l]) =>
        `<tr><td>${chk.has(k) ? "⚠ " : ""}${esc(l)}</td><td class="num">${r.read[k] == null ? "not found – type it" : esc(String(r.read[k]))}</td></tr>`).join("")}</tbody></table></div>
      <p><b>Die size proposed:</b> ${esc(r.proposal.how)}.</p></div>`;
    status($("status"), "Fin read: check the values, then Save & calculate.", "ok");
  } catch (err) {
    status($("status"), err.message, "error");
  }
});

const DESIGN_FILES = [["po-pack.pdf", "PO pack (PDF)"], ["drawings.pdf", "All drawings (PDF)"], ["strip.pdf", "Strip layout (PDF)"], ["strip.dxf", "Strip layout (DXF)"],
  ["fin.pdf", "Fin drawing (PDF)"], ["fin.dxf", "Fin (DXF)"], ["fin.step", "Fin (STEP)"], ["drawings-dxf.zip", "Die part drawings (DXF, ZIP)"],
  ["die.step", "3D fin die (STEP)"], ["die.stl", "3D fin die (STL)"], ["viewer.html", "3D viewer"], ["bom.xlsx", "Die BOM (Excel)"], ["all.zip", "Everything (ZIP)"]];

async function showDesign(id) {
  $("designOut").innerHTML = '<p class="note">Designing the fin die…</p>';
  try {
    const d = await api(`/api/fin-dies/${id}/design`);
    const u = (k) => `/api/fin-dies/${id}/design/${k}`;
    $("designOut").innerHTML = `<h3 class="block-title">Fin die design · ${esc(d.prefix)}</h3>
      ${d.example ? '<p class="note"><span class="badge badge-example">EXAMPLE</span> Sizes come from EXAMPLE rules: a design proposal for your die maker to check.</p>' : ""}
      <div class="card toolbar">${DESIGN_FILES.map(([k, l]) => `<a class="btn btn-outline" href="${u(k)}" ${k === "viewer.html" ? 'target="_blank"' : ""}>${esc(l)}</a>`).join("")}</div>
      <p class="note">Die ${fmt(d.dims.die_l, 0)} × ${fmt(d.dims.die_w, 0)} mm on die set ${fmt(d.dims.base_l, 0)} × ${fmt(d.dims.base_w, 0)} mm, shut height ≈ ${fmt(d.dims.shut_h, 0)} mm,
        ${d.stations.length} stations of ${fmt(d.dims.station_len, 0)} mm, press ${esc(d.press || "-")}.</p>
      <div class="table-wrap"><table class="cost-table"><thead><tr><th>Station</th><th>Operation</th><th class="num">From die entry (mm)</th></tr></thead><tbody>
        ${d.stations.map((s) => `<tr><td>${s.no}</td><td>${esc(s.name)}</td><td class="num">${fmt(s.x0, 0)}</td></tr>`).join("")}</tbody></table></div>
      <div id="feaOut"></div>
      <h4>Die parts and drawings</h4>
      <div class="table-wrap"><table class="cost-table"><thead><tr><th>Drawing</th><th>Part</th><th class="num">Qty</th><th>Material</th><th>Hardness</th><th>Size (mm)</th></tr></thead><tbody>
        ${d.parts.map((p) => `<tr><td>${esc(p.drawing)}</td><td>${esc(p.name)}</td><td class="num">${fmt(p.qty, 0)}</td><td>${esc(p.material)}</td><td>${esc(p.hardness)}</td>
          <td>${p.dims.map((x) => fmt(x, 2)).join(" × ")}</td></tr>`).join("")}</tbody></table></div>`;
    await showFea(id);
  } catch (err) {
    $("designOut").innerHTML = `<div class="warn">Fin die design: ${esc(err.message)}</div>`;
  }
}

// ---------- stage 59: FEA of the fin die at the full press capacity ----------
async function showFea(id, msg) {
  const f = await api(`/api/fin-dies/${id}/fea`);
  const plates = f.runs.filter((r) => r.kind === "plate");
  const punch = (f.runs.find((r) => r.kind === "punches") || {}).result;
  const punches = punch ? punch.punches : f.punches_now;
  const okb = (ok) => ok ? '<span class="badge badge-approved">OK</span>' : '<span class="badge badge-rejected">FAIL</span>';
  $("feaOut").innerHTML = `<h4>FEA at the full press capacity</h4>
    <div class="card toolbar"><button type="button" class="btn btn-primary" id="feaBtn" ${f.available.available ? "" : "disabled"}>Run FEA</button>
      <span class="note" id="feaStatus">${esc(msg || (f.available.available ? (f.out_of_date ? "The fin spec changed since the last FEA: run it again." : plates.length ? `Last run ${esc(plates[0].at)} by ${esc(plates[0].by || "-")}` : "Not run yet (a few minutes in the background).") : f.available.message))}</span></div>
    ${plates.length ? `<p class="note">${esc(plates[0].result.force_how)}</p><div class="table-wrap"><table class="cost-table"><thead><tr><th>Part</th><th>Support</th><th class="num">Deflection mm (limit)</th><th class="num">von Mises MPa (limit)</th><th>Result</th><th>Suggestion</th><th>Picture</th></tr></thead><tbody>
      ${plates.map((r) => `<tr><td>${esc(r.name)}${r.result.slice ? `<br><span class="note">${esc(r.result.slice)}</span>` : ""}</td><td>${esc(r.result.support)}</td>
        <td class="num">${fmt(r.result.max_deflection_mm, 4)} (${fmt(r.result.limit_deflection_mm, 3)})</td><td class="num">${fmt(r.result.max_von_mises_mpa, 1)} (${fmt(r.result.limit_stress_mpa, 0)})</td>
        <td>${okb(r.result.ok)}</td><td>${esc((r.result.suggest || {}).text || "")}</td><td><a href="/api/fin-dies/${id}/fea/${r.id}.png" target="_blank">picture</a></td></tr>`).join("")}</tbody></table></div>` : ""}
    ${punches && punches.length ? `<p class="note">Punch buckling (formula): ${esc(punches[0].formula)}; ${esc(punches[0].load_how)}.</p>
      <div class="table-wrap"><table class="cost-table"><thead><tr><th>Punch</th><th class="num">Ø × free length mm</th><th class="num">Load N</th><th>Method</th><th class="num">Buckling N</th><th class="num">Safety (min)</th><th class="num">Stress MPa</th><th>Result</th><th>Suggestion</th></tr></thead><tbody>
      ${punches.map((x) => `<tr><td>${esc(x.name)}</td><td class="num">${fmt(x.d_mm, 2)} × ${fmt(x.free_mm, 1)}</td><td class="num">${fmt(x.load_n, 0)}</td><td>${esc(x.method)}</td>
        <td class="num">${fmt(x.buckling_n, 0)}</td><td class="num">${fmt(x.safety, 1)} (${fmt(x.limits.sf_min, 0)})</td><td class="num">${fmt(x.stress_mpa, 0)}</td><td>${okb(x.ok)}</td><td>${esc(x.suggest || "")}</td></tr>`).join("")}</tbody></table></div>` : ""}`;
  const btn = $("feaBtn");
  if (btn) btn.addEventListener("click", () => runFea(id));
}

async function runFea(id) {
  try {
    let job = await api(`/api/fin-dies/${id}/fea`, { method: "POST" });
    $("feaBtn").disabled = true;
    while (job.status === "queued" || job.status === "running") {
      $("feaStatus").textContent = `${job.pct}% · ${job.text}`;
      await new Promise((r) => setTimeout(r, 1500));
      job = await api(`/api/fin-dies/${id}/fea-jobs/${job.id}`);
    }
    await showFea(id, job.status === "failed" ? `FEA failed: ${job.error}` : `FEA done in ${fmt(job.elapsed_s, 0)} s.`);
  } catch (err) {
    $("feaStatus").textContent = err.message;
  }
}
init().catch((err) => status($("status"), err.message, "error"));
