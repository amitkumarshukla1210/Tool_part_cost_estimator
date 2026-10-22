// Part register: search/filter, part panel with revisions, history and traced geometry.
const { $, esc, fmt, inr, api, registerMeta, options, status, thumb } = window.DTC;
const PAGE = 50;
let offset = 0;
let meta, projects, rmMeta;
let part = null;

const filters = () => {
  const f = new FormData($("filters"));
  const q = new URLSearchParams();
  for (const [k, v] of f.entries()) if (v !== "") q.set(k, v);
  return q;
};
const nameOf = (list, code) => list.find((x) => x.code === code)?.name ?? code ?? "";

async function init() {
  meta = await registerMeta();
  rmMeta = await api("/api/rm/meta");
  projects = await api("/api/projects");
  const f = $("filters").elements;
  f.namedItem("project_id").innerHTML = options(projects.map((p) => ({ code: p.id, name: `${p.code} · ${p.name}` })), "", "All projects");
  f.namedItem("process").innerHTML = options(meta.processes, "", "All");
  f.namedItem("status").innerHTML = options(meta.statuses, "", "All");
  f.namedItem("sourcing").innerHTML = options(meta.sourcing, "", "All");
  const url = new URLSearchParams(location.search);
  if (url.get("project")) f.namedItem("project_id").value = url.get("project");
  await search();
  if (url.get("part")) openPart(Number(url.get("part")));
}

let timer;
$("filters").addEventListener("input", () => {
  clearTimeout(timer);
  timer = setTimeout(() => ((offset = 0), search()), 250);
});
$("filters").addEventListener("submit", (e) => e.preventDefault());
$("prev").addEventListener("click", () => ((offset = Math.max(0, offset - PAGE)), search()));
$("next").addEventListener("click", () => ((offset += PAGE), search()));

async function search() {
  const q = filters();
  $("export").href = `/api/parts/export.xlsx?${q}`;
  q.set("limit", PAGE);
  q.set("offset", offset);
  let res;
  try {
    res = await api(`/api/parts?${q}`);
  } catch (err) {
    return status($("status"), err.message, "error");
  }
  status($("status"), "");
  $("count").textContent = res.total ? `${offset + 1}–${Math.min(offset + PAGE, res.total)} of ${fmt(res.total)} parts` : "No parts";
  $("prev").disabled = offset === 0;
  $("next").disabled = offset + PAGE >= res.total;
  $("exampleBanner").innerHTML = res.rows.some((r) => r.rm_is_example || r.tool_is_example)
    ? window.exampleBanner("Costs marked • use EXAMPLE rates or master-data values.") : "";
  const mark = (on) => (on ? ' <span class="example-mark" title="Uses example values">•</span>' : "");
  $("table").innerHTML = `<thead><tr><th></th><th>Part code</th><th>Name</th><th>Rev</th><th>Project</th><th>Process</th>
    <th>Material</th><th>Status</th><th>Sourcing</th><th class="num">Volume (cm³)</th><th class="num">Net RM cost (INR)</th>
    <th class="num">Tool cost (INR)</th><th>File</th></tr></thead><tbody>` +
    (res.rows.length ? res.rows.map((r) => `<tr class="clickable" data-id="${r.id}"><td>${thumb(r.thumbnail_file_id)}</td>
      <td><b>${esc(r.part_code)}</b></td><td>${esc(r.name)}${r.is_assembly ? ' <span class="badge assy">assembly</span>' : ""}</td>
      <td>${esc(r.rev ?? "")}</td><td>${esc(r.project_code)}</td><td>${esc(nameOf(meta.processes, r.process))}</td>
      <td>${esc(r.material)}</td><td><span class="badge status">${esc(nameOf(meta.statuses, r.status))}</span></td>
      <td>${esc(nameOf(meta.sourcing, r.sourcing))}</td>
      <td class="calc num">${r.geometry?.volume_cm3 != null ? fmt(r.geometry.volume_cm3, 2) : "—"}</td>
      <td class="calc num">${r.rm_cost_inr != null ? fmt(r.rm_cost_inr, 2) : "—"}${mark(r.rm_is_example)}</td>
      <td class="calc num" title="${r.tool_capex_inr != null ? `Tool CAPEX ${fmt(r.tool_capex_inr, 0)} INR` : ""}">${r.tool_cost_inr != null ? fmt(r.tool_cost_inr, 0) : "—"}${mark(r.tool_is_example)}</td>
      <td>${r.file_id ? "STEP" : '<span class="badge missing">File missing</span>'}</td></tr>`).join("")
      : '<tr><td colspan="13" class="empty">No parts match. Import parts on the Import page.</td></tr>') + "</tbody>";
}
$("table").addEventListener("click", (e) => {
  const row = e.target.closest("tr[data-id]");
  if (row) openPart(Number(row.dataset.id));
});

// ---------- part panel ----------
$("panelClose").addEventListener("click", () => {
  $("panel").hidden = true;
  history.replaceState(null, "", location.pathname);
});

async function openPart(id) {
  try {
    part = await api(`/api/parts/${id}`);
  } catch (err) {
    return status($("status"), err.message, "error");
  }
  history.replaceState(null, "", `?part=${id}`);
  part.trace = null;
  if (part.file_id && !part.is_assembly) part.trace = await api(`/api/parts/${id}/trace`).catch(() => null);
  part.rmTrace = part.rm?.applicable && !part.rm.problem ? await api(`/api/parts/${id}/rm-cost/trace`).catch(() => null) : null;
  part.rmVersions = part.rm?.versions ? await api(`/api/parts/${id}/rm-cost`).catch(() => []) : [];
  part.toolTrace = part.tool?.versions || (part.tool?.applicable && !part.tool.problem)
    ? await api(`/api/parts/${id}/tool-cost/trace`).catch(() => null) : null;
  part.toolVersions = part.tool?.versions ? await api(`/api/parts/${id}/tool-cost`).catch(() => []) : [];
  part.piece = part.is_assembly || !part.tool?.applicable ? null : await api(`/api/parts/${id}/piece-cost`).catch(() => null);
  part.sheet = null;
  if (!part.is_assembly && /sheet_metal/.test(part.process || "")) {
    part.sheet = await api(`/api/parts/${id}/sheet-tools`).catch((err) => ({ problem: err.message }));
    part.layout = part.sheet.problem ? null : await api(`/api/parts/${id}/sheet-layout`).catch(() => null);
  }
  part.loop = part.is_assembly ? null : await api(`/api/parts/${id}/design-loop`).catch(() => null);
  renderPart();
  $("panel").hidden = false;
}

function geometryRows(g) {
  if (!g || g.assembly) return g?.assembly ? `<tr><td>Structure</td><td class="calc">${g.children.map(([n, q]) => `${esc(n)} × ${q}`).join(", ")}</td></tr>` : "";
  const b = g.bbox_mm;
  return `<tr><td>Volume</td><td class="calc num"><button type="button" class="tv" data-trace="volume">${fmt(g.volume_cm3, 3)} cm³</button></td></tr>
    ${weightRows()}
    <tr><td>Bounding box L × W × H</td><td class="calc num">${fmt(b.length, 1)} × ${fmt(b.width, 1)} × ${fmt(b.height, 1)} mm</td></tr>
    <tr><td>Projected area (along ${esc(g.pull_direction.toUpperCase())})</td><td class="calc num"><button type="button" class="tv" data-trace="proj">${fmt(g.projected_area_mm2[g.pull_direction] / 100, 2)} cm²</button></td></tr>
    <tr><td>Main wall / sheet thickness</td><td class="calc num">${fmt(g.wall_mm, 2)} mm (${fmt(g.sheet_share * 100, 0)} % of the surface)${g.bend_count != null ? ` · ${g.bend_count} bend${g.bend_count === 1 ? "" : "s"}` : ""}</td></tr>`;
}

// Body (plastic / metal) weight, insert weight and total, each clickable to its trace.
function weightRows() {
  const n = part.trace?.nodes || {};
  const tv = (id, d = 2) => (n[id] ? `<button type="button" class="tv" data-trace="${id}">${fmt(n[id].value, d)} g</button>` : null);
  const warn = (part.trace?.warnings || []).map((w) => `<p class="note">${esc(w)}</p>`).join("");
  if (!part.inserts.length)
    return `<tr><td>Net weight</td><td class="calc num">${tv("weight") ?? "set a material to calculate"}</td></tr>`;
  return `<tr><td>Body weight (${esc(part.material || "material not set")}, without inserts)</td><td class="calc num">${tv("weight") ?? "set a material to calculate"}</td></tr>
    <tr><td>Insert weight (${fmt(part.insert_count)} insert${part.insert_count === 1 ? "" : "s"})</td><td class="calc num">${tv("insert_weight") ?? "—"}</td></tr>
    <tr class="total"><td>Total part weight</td><td class="calc num">${tv("total_weight") ?? "—"}${warn}</td></tr>`;
}

// Material choices: estimator materials, then bought-out insert materials.
function materialOptions(value) {
  const opt = (m) => `<option value="${esc(m)}" ${m === value ? "selected" : ""}>${esc(m)}</option>`;
  const known = meta.materials.includes(value) || meta.insert_materials.some((m) => m.name === value);
  return `<option value="">—</option>${value && !known ? opt(value) : ""}<optgroup label="Part materials">${meta.materials.map(opt).join("")}</optgroup>` +
    `<optgroup label="Insert materials">${meta.insert_materials.map((m) => opt(m.name)).join("")}</optgroup>`;
}

// Shape + dimension inputs (Part register setup → Insert shapes) for a part without a 3D file.
function dimsFields(dims, prefix = "") {
  const shape = meta.insert_shapes.find((s) => s.code === dims?.shape);
  return `<label>Shape <select name="${prefix}shape" data-dims="${prefix}">${options(meta.insert_shapes, dims?.shape, "— (use the 3D file)")}</select></label>
    <span class="dims" data-for="${prefix}">${shape ? shape.dims.map((d) => `<label>${esc(d)} <input type="number" min="0" step="any" name="${prefix}dim_${d}" value="${dims?.[d] ?? ""}" required /></label>`).join("") : ""}</span>`;
}

function readDims(f, prefix = "") {
  const shape = f.get(`${prefix}shape`);
  if (!shape) return null;
  const out = { shape };
  for (const [k, v] of f.entries()) if (k.startsWith(`${prefix}dim_`)) out[k.slice(prefix.length + 4)] = v;
  return out;
}

const priceFields = (p = {}, prefix = "") => `
  <label>Price per piece <input type="number" min="0" step="any" name="${prefix}unit_price" value="${p.unit_price ?? ""}" /></label>
  <label>Currency <input name="${prefix}price_currency" maxlength="10" value="${esc(p.price_currency ?? "INR")}" /></label>
  <label>Price source <input name="${prefix}price_source" placeholder="supplier quote, catalogue, estimate" value="${esc(p.price_source ?? "")}" /></label>
  <label>Price month <input name="${prefix}price_month" placeholder="2026-10" pattern="\\d{4}-\\d{2}" value="${esc(p.price_month ?? "")}" /></label>
  <label class="check span2"><input type="checkbox" name="${prefix}price_is_example" value="true" ${p.price_is_example ? "checked" : ""} /> Example price (replace later)</label>`;


// ---------- raw-material (RM) cost ----------
function rmBlock(p) {
  if (p.is_assembly) return "";
  const rm = p.rm, v = rm.latest, tr = p.rmTrace;
  const tv = (id, text) => `<button type="button" class="tv" data-rmtrace="${id}">${text}</button>`;
  const node = (id) => tr?.nodes[id];
  const amount = (id, unit, d = 2) => (node(id) ? tv(id, `${fmt(node(id).value, d)} ${unit}`) : "—");
  const example = v?.is_example ? ' <span class="badge badge-example" title="Some rates used are placeholders">EXAMPLE rates</span>' : "";
  let html = `<h3 class="block-title">Raw-material (RM) cost</h3>`;
  if (v?.is_example) html += window.exampleBanner("Replace the EXAMPLE rates on the Rates page before using this cost.");
  if (rm.problem) html += `<p class="warn">${esc(rm.problem)}</p>`;
  if (rm.outdated) {
    html += `<p class="warn">${esc(rm.outdated)}
      ${rm.rate_changes.map((c) => `<br/>${esc(c.rate)}: ${fmt(c.old_value, 2)} (${esc(c.old_month)}) → <b>${fmt(c.new_value, 2)}</b> (${esc(c.new_month)})`).join("")}
      <br/><button type="button" class="btn btn-primary small" id="rmRecalc">${rm.latest ? "Recalculate with latest rates" : "Calculate RM cost"}</button></p>`;
  }
  if (rm.weights && !v) html += `<p class="note">Weights are calculated; the cost needs the missing rate. Gross weight ${fmt(rm.weights.gross_g, 2)} g.</p>`;
  if (v && tr) {
    const cur = tr.currency;
    const has = (id) => node(id);
    html += `<div class="table-wrap"><table class="cost-table"><tbody>
      <tr><td>Net weight (body, from the 3D file × density)</td><td class="calc num">${amount("weight", "g")}</td></tr>
      <tr><td>Gross weight</td><td class="calc num">${amount("calc:gross_g", "g")}</td></tr>
      <tr><td>Returns / scrap</td><td class="calc num">${amount("calc:returns_g", "g")}</td></tr>
      <tr><td>Material used per part</td><td class="calc num">${amount("calc:input_g", "g")}</td></tr>
      <tr><td>Material yield</td><td class="calc num">${amount("calc:material_yield_pct", "%", 1)}</td></tr>
      ${has("in:blanks_per_sheet") ? `<tr><td>Blanks per sheet</td><td class="calc num">${amount("in:blanks_per_sheet", "pcs", 0)}</td></tr>` : ""}
      <tr><td>Material rate (${esc(tr.country)}, ${esc(tr.as_of)})</td><td class="calc num">${amount("in:material_rate", cur + "/kg")}</td></tr>
      <tr><td>RM cost (material used × rate)</td><td class="calc num">${amount("calc:rm_cost", cur)}</td></tr>
      <tr><td>Scrap credit</td><td class="calc num">${amount("calc:scrap_credit", cur)}</td></tr>
      <tr class="total"><td>Net RM cost per part · version ${v.version}${example}</td>
        <td class="calc num">${tv(tr.root, `${fmt(v.net_rm_cost, 2)} ${esc(cur)}`)}${cur !== "INR" ? `<div class="note">${fmt(v.net_rm_cost_inr, 2)} INR</div>` : ""}</td></tr>
    </tbody></table></div>
    <p class="note">Click any value for its formula, inputs, sources and rate versions (#${v.rates_used.map((r) => r.id).join(", #")}).
      Stored ${esc(v.created_at.slice(0, 16).replace("T", " "))} by ${esc(v.created_by)} · ${esc(v.reason)}.
      <a class="link" href="/api/parts/${p.id}/rm-cost/export.xlsx">Excel</a> · <a class="link" href="/api/parts/${p.id}/rm-cost/export.pdf">PDF</a>
      ${p.file_id ? ` · <a class="link" href="/?part=${p.id}">Open in Estimate</a>` : ""}</p>`;
  }
  if (rm.applicable) {
    const typed = p.rm_inputs || {};
    html += `<details class="card add-insert" ${Object.keys(typed).length || p.country || p.costing_month ? "open" : ""}>
      <summary class="btn btn-outline small">RM inputs, country and month</summary>
      <form id="rmForm" class="grid2">
        <label>Producing country <select name="country"><option value="">Default (${esc(p.effective_country)})</option>
          ${rmMeta.countries.map((c) => `<option value="${esc(c.code)}" ${c.code === p.country ? "selected" : ""}>${esc(c.name)} (${esc(c.currency)})</option>`).join("")}</select></label>
        <label>Costing month <input name="costing_month" placeholder="blank = ${esc(rmMeta.month)}" pattern="\\d{4}-\\d{2}" value="${esc(p.costing_month || "")}" /></label>
        <p class="note span2">Leave a box empty to use the default shown. A value you type replaces it and is traced as your input.
          Money values are in the producing country's currency.</p>
        ${rm.overridable.map((i) => `<label>${esc(i.label)} (${esc(i.unit)})
          <input type="number" min="0" step="any" name="in_${esc(i.variable)}" value="${typed[i.variable] ?? ""}"
            placeholder="${i.default != null ? esc(i.default) : i.source === "rate" ? "approved rate" : "from the 3D file"}" /></label>`).join("")}
        <div class="span2 dialog-actions"><button type="submit" class="btn btn-primary">Save and calculate</button></div>
        <p class="status span2" id="rmStatus"></p>
      </form></details>`;
  }
  if (rm.versions) {
    html += `<details class="card add-insert"><summary class="btn btn-outline small">RM cost versions (${rm.versions})</summary>
      <div class="table-wrap"><table class="cost-table" id="rmVersions"><thead><tr><th>Ver</th><th>Rev</th><th>Material</th><th>Country</th><th>Month</th>
        <th class="num">Net RM cost</th><th class="num">INR</th><th>Rates</th><th>Why</th><th>By / when</th></tr></thead><tbody>
        ${p.rmVersions.map((x) => `<tr class="clickable" data-rmversion="${x.version}"><td><b>${x.version}</b></td><td>${esc(x.rev)}</td><td>${esc(x.material)}</td>
          <td>${esc(x.country)}</td><td>${esc(x.as_of)}</td><td class="calc num">${fmt(x.net_rm_cost, 2)} ${esc(x.currency)}</td><td class="calc num">${fmt(x.net_rm_cost_inr, 2)}</td>
          <td>#${x.rates_used.map((r) => r.id).join(", #")}${x.is_example ? ' <span class="badge badge-example">EXAMPLE</span>' : ""}</td>
          <td>${esc(x.reason)}</td><td>${esc(x.created_by)} · ${esc(x.created_at.slice(0, 16).replace("T", " "))}</td></tr>`).join("")}</tbody></table></div>
      <p class="note">Old versions are never changed. Click a version to see its full trace.</p></details>`;
  }
  return html;
}

// ---------- tool cost (stage 4) ----------
function toolBlock(p) {
  if (p.is_assembly || !p.tool) return "";
  const t = p.tool, v = t.latest, tr = p.toolTrace;
  const stored = v && tr?.stored;
  const tv = (id, text) => (tr?.nodes[id] ? `<button type="button" class="tv" data-tooltrace="${id}">${text}</button>` : text);
  const money = (id, cur) => (tr?.nodes[id] ? tv(id, `${fmt(tr.nodes[id].value, 0)} ${esc(cur)}`) : "—");
  let html = `<h3 class="block-title">Tool cost (mould / die)</h3>`;
  if (!t.applicable) return html + `<p class="note">${esc(t.problem)}</p>`;
  // The warning goes with every tool cost shown that uses an EXAMPLE rate or master-data row.
  if (tr?.example?.any) html += window.exampleBanner(esc(tr.example.detail));
  if (t.problem) html += `<p class="warn">${esc(t.problem)}</p>`;
  if (t.outdated) {
    html += `<p class="warn">${esc(t.outdated)}
      ${t.rate_changes.map((c) => `<br/>${esc(c.rate)}: ${fmt(c.old_value, 2)} (${esc(c.old_month)}) → <b>${fmt(c.new_value, 2)}</b> (${esc(c.new_month)})`).join("")}
      <br/><button type="button" class="btn btn-primary small" id="toolRecalc">${v ? "Recalculate with latest rates" : "Calculate tool cost"}</button></p>`;
  }
  if (tr) {
    const cur = tr.currency;
    const b = tr.base;
    const steps = tr.steps.map((s) => ({ ...s, n: tr.nodes[s.node] })).filter((s) => s.n.unit.startsWith(cur));
    const result = steps.find((s) => s.is_result);
    const capex = steps.find((s) => s.name === "tool_capex");
    const inrNote = (v) => (cur !== "INR" && v != null ? `<div class="note">${fmt(v, 0)} INR</div>` : "");
    html += `<div class="table-wrap"><table class="cost-table"><tbody>
      ${result ? `<tr class="total"><td>${esc(result.n.label)}${stored ? ` · version ${v.version}` : ""}${tr.example?.any ? ' <span class="badge badge-example">EXAMPLE values</span>' : ""}</td>
        <td class="calc num">${money(result.node, cur)}${inrNote(tr.value_inr)}</td></tr>` : ""}
      ${capex ? `<tr class="total"><td>${esc(capex.n.label)} (× ${tr.tools_count} tool${tr.tools_count === 1 ? "" : "s"} over the programme)</td>
        <td class="calc num">${money(capex.node, cur)}${inrNote(tr.capex_inr)}</td></tr>` : ""}
    </tbody></table></div>
    <h4 class="block-title">Cost build-up</h4>
    <div class="table-wrap"><table class="cost-table"><tbody>
      <tr><td>Cavities · tools over the programme</td><td class="calc num">${tv("v:cavities", tr.cavities)} · ${tv("tools_count", tr.tools_count)}</td></tr>
      <tr><td>Mould base · tool weight</td><td class="calc num">${esc(b.series)} ${esc(b.size_code)} · ${tv("tool_weight", `${fmt(tr.nodes.tool_weight.value, 0)} kg`)}</td></tr>
      <tr><td>Try-out machine (clamp force)</td><td class="calc num">${tr.trial.machine ? tv("trial:machine", esc(tr.trial.machine.machine_id)) : "—"}
        (${tv(tr.trial.force_node, `${fmt(tr.trial.force_t, 0)} t`)})</td></tr>
      ${tr.groups.map((g) => `<tr><td>${esc(g.label)}</td><td class="calc num">${money(g.node, cur)}</td></tr>`).join("")}
      <tr><td>Tool steel</td><td class="calc num">${money(tr.totals.material_cost, cur)}</td></tr>
      <tr><td>Mould base &amp; standard parts</td><td class="calc num">${money(tr.totals.bought_out_cost, cur)}</td></tr>
      ${steps.map((s) => `<tr class="${s.is_result || s.name === "tool_capex" ? "total" : ""}"><td>${esc(s.n.label)}</td>
        <td class="calc num">${money(s.node, cur)}${s.is_result ? inrNote(tr.value_inr) : ""}${s.name === "tool_capex" ? inrNote(tr.capex_inr) : ""}</td></tr>`).join("")}
    </tbody></table></div>
    <p class="note">${stored ? "" : "<b>Live preview, not stored yet.</b> "}Tool country ${esc(tr.country)} · rates of ${esc(tr.as_of)}. Click any value for its formula,
      inputs, sources and rate versions.${stored ? ` Stored ${esc(v.created_at.slice(0, 16).replace("T", " "))} by ${esc(v.created_by)} · ${esc(v.reason)}.` : ""}
      ${stored ? `<a class="link" href="/api/parts/${p.id}/tool-cost/export.xlsx">Excel</a> · <a class="link" href="/api/parts/${p.id}/tool-cost/export.pdf">PDF</a>` : ""}
      ${p.file_id ? ` · <a class="link" href="/?part=${p.id}">Open in Estimate (full BOM)</a>` : ""}</p>`;
  }
  const typed = p.tool_inputs || {};
  const live = t.live || {};
  html += `<details class="card add-insert" ${Object.keys(typed).length || p.tool_country ? "open" : ""}>
    <summary class="btn btn-outline small">Tool features and tool country</summary>
    <form id="toolForm" class="grid2">
      <label>Tool country <select name="tool_country"><option value="">Same as producing country (${esc(p.effective_country)})</option>
        ${rmMeta.countries.map((c) => `<option value="${esc(c.code)}" ${c.code === p.tool_country ? "selected" : ""}>${esc(c.name)} (${esc(c.currency)})</option>`).join("")}</select></label>
      <label>Cavities per tool <input type="number" min="1" step="1" name="cavities" value="${typed.cavities ?? ""}"
        placeholder="Stage C: ${esc(live.stage_c?.cavities_per_tool ?? "")}" /></label>
      ${live.part_type === "plastic" ? `<label class="check"><input type="checkbox" name="hot_runner" ${typed.hot_runner ? "checked" : ""} /> Hot runner</label>` : ""}
      <label>Slides per cavity <input type="number" min="0" step="1" name="slides_per_cavity" value="${typed.slides_per_cavity ?? ""}" placeholder="0" /></label>
      ${live.part_type === "plastic" ? `<label>Lifters per cavity <input type="number" min="0" step="1" name="lifters_per_cavity" value="${typed.lifters_per_cavity ?? ""}" placeholder="0" /></label>` : ""}
      <label>Small inserts per cavity <input type="number" min="0" step="1" name="inserts_per_cavity" value="${typed.inserts_per_cavity ?? ""}" placeholder="0" /></label>
      <label class="check"><input type="checkbox" name="warranty" ${typed.warranty === false ? "" : "checked"} /> Warranty / spares</label>
      <p class="note span2">${esc(live.stage_c?.note ?? "")}. Leave cavities empty to follow Stage C.</p>
      <div class="span2 dialog-actions"><button type="submit" class="btn btn-primary">Save and calculate</button></div>
      <p class="status span2" id="toolStatus"></p>
    </form></details>`;
  if (live.part_type === "plastic" || live.part_type === "die_casting") {
    html += `<details class="card add-insert"><summary class="btn btn-outline small">Mould concept (opening direction, undercuts, proposals)</summary>
      <p class="note">A proposal from ray casting on the 3D model and the Concept rules in Master data. Check it before you use it.</p>
      <button type="button" class="btn btn-outline small" id="conceptRun">Analyse</button> <span class="status" id="conceptStatus"></span>
      <div id="conceptOut"></div></details>
      <details class="card add-insert"><summary class="btn btn-outline small">Simulation &amp; analysis (wall, draft, sink, cycle, clamp)</summary>
      <p class="note">Analytical estimate from the 3D model and the Simulation rules in Master data, not a flow simulation.</p>
      <button type="button" class="btn btn-outline small" id="simRun">Analyse</button>
      <a class="link" href="/api/parts/${p.id}/simulation/report.pdf">PDF report with maps</a> <span class="status" id="simStatus"></span>
      <div id="simOut"></div></details>`;
  }
  if (t.versions) {
    html += `<details class="card add-insert"><summary class="btn btn-outline small">Tool cost versions (${t.versions})</summary>
      <div class="table-wrap"><table class="cost-table"><thead><tr><th>Ver</th><th>Rev</th><th>Country</th><th>Month</th><th class="num">Cavities</th>
        <th class="num">Per tool</th><th class="num">INR</th><th class="num">CAPEX (INR)</th><th>Why</th><th>By / when</th></tr></thead><tbody>
        ${p.toolVersions.map((x) => `<tr class="clickable" data-toolversion="${x.version}"><td><b>${x.version}</b></td><td>${esc(x.rev)}</td>
          <td>${esc(x.country)}</td><td>${esc(x.as_of)}</td><td class="calc num">${x.cavities}</td>
          <td class="calc num">${fmt(x.tool_cost, 0)} ${esc(x.currency)}</td><td class="calc num">${fmt(x.tool_cost_inr, 0)}${x.is_example ? ' <span class="example-mark" title="Uses example values">•</span>' : ""}</td>
          <td class="calc num">${x.tool_capex_inr != null ? fmt(x.tool_capex_inr, 0) : "—"}</td>
          <td>${esc(x.reason)}</td><td>${esc(x.created_by)} · ${esc(x.created_at.slice(0, 16).replace("T", " "))}</td></tr>`).join("")}</tbody></table></div>
      <p class="note">Old versions are never changed. Click a version to see its full trace. • = uses EXAMPLE values.</p></details>`;
  }
  return html;
}

function suggestionBox(p) {
  const s = p.suggestion;
  if (!s?.process && !s?.steps?.length) return "";
  const same = s.process === p.process;
  return `<div class="suggest-box span2"><b>Suggested process: ${esc(nameOf(meta.processes, s.process) || "none")}</b>
    ${s.process && !same ? `<button type="button" class="btn btn-outline small" id="useSuggestion">Use it</button>` : same ? ' <span class="badge suggested">matches</span>' : ""}
    ${(s.steps || []).map((t) => `<p>${esc(t)}</p>`).join("")}</div>`;
}

function insertsBlock(p) {
  if (p.is_assembly) return "";
  const rows = p.inserts.map((x) => {
    const i = x.insert;
    const size = x.volume.method === "3d" ? "3D file" : x.volume.method === "dimensions"
      ? `${esc(x.volume.shape.name)} ${Object.values(x.volume.dims).map((v) => fmt(v, 1)).join(" × ")} mm` : '<span class="badge missing">no size</span>';
    return `<tr><td><button type="button" class="tv" data-open="${i.id}">${esc(i.part_code)}</button>${x.detected ? ' <span class="badge suggested" title="Found in the 3D assembly and confirmed">detected</span>' : ""}
        <div class="note">${esc(i.name)} · ${esc(i.material || "material not set")}</div></td>
      <td class="calc num">${fmt(x.quantity, 2)}</td><td>${size}</td>
      <td class="calc num">${x.weight_g != null ? `${fmt(x.weight_g, 2)}<div class="note">${fmt(x.weight_each_g, 2)} each</div>` : `<span class="note">${esc(x.missing)}</span>`}</td>
      <td class="calc num">${i.unit_price != null ? `${fmt(i.unit_price, 2)} ${esc(i.price_currency)}` : "—"}${i.price_is_example ? ' <span class="badge badge-example">EXAMPLE</span>' : ""}
        <div class="note">${esc([i.price_source, i.price_month].filter(Boolean).join(" · "))}</div></td>
      <td><button type="button" class="btn btn-outline small" data-unlink="${x.link_id}" aria-label="Remove insert ${esc(i.part_code)}">✕</button></td></tr>`;
  }).join("");
  return `<h3 class="block-title">Moulded-in inserts</h3>
    <p class="note">Bought-out parts moulded or cast into this part (threaded inserts, bushes, terminals, pins, nuts). They are separate parts in the
      register, not BOM children. Click a code to open the insert; set its price there or below.</p>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th>Insert</th><th class="num">Qty</th><th>Size from</th>
      <th class="num">Weight (g)</th><th class="num">Price / pc</th><th></th></tr></thead><tbody>
      ${rows || '<tr><td colspan="6" class="empty">No inserts linked.</td></tr>'}</tbody></table></div>
    <details class="card add-insert"><summary class="btn btn-outline small">+ Link an insert</summary>
      <form id="insertForm" class="grid2">
        <label>Insert part code <input name="insert_part_code" list="codeList" placeholder="existing code, or blank / new code" /></label>
        <label>Quantity in this part <input type="number" name="quantity" min="0" step="any" value="1" required /></label>
        <p class="note span2">For a new insert part, also fill in:</p>
        <label>Name <input name="name" placeholder="e.g. M3 brass threaded insert" /></label>
        <label>Material <select name="material">${materialOptions("")}</select></label>
        ${dimsFields(null, "n_")}
        ${priceFields({}, "n_")}
        <div class="span2 dialog-actions"><button type="submit" class="btn btn-primary">Link insert</button></div>
        <p class="status span2" id="insertStatus"></p>
      </form></details>
    <datalist id="codeList"></datalist>`;
}

function mouldedIntoBlock(p) {
  if (!p.moulded_into.length) return "";
  return `<h3 class="block-title">Moulded into</h3><div class="table-wrap"><table class="cost-table"><thead><tr><th>Part</th><th class="num">Qty</th></tr></thead><tbody>
    ${p.moulded_into.map((m) => `<tr class="clickable" data-open="${m.id}"><td>${esc(m.part_code)} · ${esc(m.name)}</td><td class="calc num">${fmt(m.quantity, 2)}</td></tr>`).join("")}</tbody></table></div>`;
}

function renderPart() {
  const p = part;
  const cur = p.revisions.find((r) => r.id === p.current_revision_id);
  const sel = (name, list, value) => `<select name="${name}">${options(list, value, "—")}</select>`;
  $("panelBody").innerHTML = `
    <div class="part-top">
      <div>${p.thumbnail_file_id ? `<img class="thumb-lg" src="/api/files/${p.thumbnail_file_id}" alt="" />` : '<span class="thumb-lg">no 3D file</span>'}
        ${p.file_id ? `<p class="note"><a class="link" href="/api/files/${p.file_id}">Download STEP (rev ${esc(p.rev)})</a></p>` : '<p class="note"><span class="badge missing">File missing</span></p>'}</div>
      <div><h3>${esc(p.part_code)} · ${esc(p.name)}</h3>
        <p class="note">Project ${esc(p.project_code)} · current rev <b>${esc(p.rev ?? "—")}</b> · created ${esc(p.created_at.slice(0, 10))} by ${esc(p.created_by)}</p>
        <form id="partForm" class="grid2">
          <label class="span2">Part name <input name="name" value="${esc(p.name)}" /></label>
          <label>Material <select name="material">${materialOptions(p.material)}</select></label>
          <label>Process ${sel("process", meta.processes, p.process)}</label>
          <label>Sourcing ${sel("sourcing", meta.sourcing, p.sourcing)}</label>
          <label>Status ${sel("status", meta.statuses, p.status)}</label>
          <label>Annual volume <input type="number" name="annual_volume" min="0" value="${p.annual_volume ?? ""}" /></label>
          <label>Programme life (years) <input type="number" name="programme_life_years" min="0" step="any" value="${p.programme_life_years ?? ""}" /></label>
          <label>Target piece cost (INR) <input type="number" name="target_piece_cost_inr" min="0" step="any" value="${p.target_piece_cost_inr ?? ""}" /></label>
          <label class="span2">Notes <input name="notes" value="${esc(p.notes)}" /></label>
          ${suggestionBox(p)}
          <details class="span2 bop" ${!meta.sourcing.find((x) => x.code === p.sourcing)?.is_costed || p.unit_price != null || p.dimensions ? "open" : ""}>
            <summary>Bought-out price and size without a 3D file (inserts, BOP parts)</summary>
            <fieldset class="sub grid2"><legend>Bought-out price</legend>${priceFields(p)}</fieldset>
            <fieldset class="sub grid2"><legend>Size without a 3D file</legend>${dimsFields(p.dimensions)}</fieldset>
          </details>
          <div class="span2 dialog-actions"><button type="submit" class="btn btn-primary">Save changes</button></div>
          <p class="status span2" id="partStatus"></p>
        </form></div>
    </div>

    <h3 class="block-title">Geometry · rev ${esc(cur?.rev ?? "—")}</h3>
    <div class="table-wrap"><table class="cost-table"><tbody>${geometryRows(cur?.geometry) || '<tr><td class="empty">No 3D file for this revision.</td></tr>'}</tbody></table></div>

    ${loopBlock(p)}
    ${rmBlock(p)}
    ${toolBlock(p)}
    ${pieceBlock(p)}
    ${sheetBlock(p)}
    ${designPackBlock(p)}
    ${compareBlock(p)}
    ${insertsBlock(p)}
    ${mouldedIntoBlock(p)}

    <h3 class="block-title">Revisions</h3>
    <div class="table-wrap"><table class="cost-table">
      <thead><tr><th>Compare</th><th>Rev</th><th>File</th><th>What changed</th><th>Source</th><th class="num">Volume (cm³)</th><th>By / when</th></tr></thead><tbody>
      ${p.revisions.map((r) => `<tr><td><input type="checkbox" class="cmp" value="${r.id}" aria-label="Compare" /></td><td><b>${esc(r.rev)}</b>${r.id === p.current_revision_id ? " (current)" : ""}</td>
        <td>${r.file_id ? `<a class="link" href="/api/files/${r.file_id}">${esc(r.original_name)}</a>` : '<span class="badge missing">File missing</span>'}</td>
        <td>${esc(r.change_note)}</td><td>${esc(r.source)}</td><td class="calc num">${r.geometry?.volume_cm3 != null ? fmt(r.geometry.volume_cm3, 3) : "—"}</td>
        <td>${esc(r.created_by)} · ${esc(r.created_at.slice(0, 16).replace("T", " "))}</td></tr>`).join("")}</tbody></table></div>
    <div id="compare"></div>

    <h3 class="block-title">Upload a new revision</h3>
    <form id="revForm" class="card grid2">
      <label class="span2">STEP file <input type="file" name="file" accept=".step,.stp" required /></label>
      <label>Rev no. (blank = next) <input name="rev" maxlength="20" /></label>
      <label>What changed <input name="change_note" /></label>
      <div class="span2 dialog-actions"><button type="submit" class="btn btn-primary">Upload revision</button></div>
      <p class="status span2" id="revStatus"></p>
    </form>

    <h3 class="block-title">Where used</h3>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th>Variant</th><th>Parent</th><th class="num">Qty</th></tr></thead><tbody>
      ${p.where_used.map((w) => `<tr><td>${esc(w.variant)}</td><td>${w.parent_code ? esc(w.parent_code + " · " + w.parent_name) : "top level"}</td><td class="calc num">${fmt(w.quantity, 2)}</td></tr>`).join("")
        || '<tr><td colspan="3" class="empty">Not in any BOM yet.</td></tr>'}</tbody></table></div>
    ${p.children.length ? `<h3 class="block-title">Contains</h3><div class="table-wrap"><table class="cost-table"><thead><tr><th>Variant</th><th>Part</th><th class="num">Qty</th></tr></thead><tbody>
      ${p.children.map((c) => `<tr class="clickable" data-open="${c.id}"><td>${esc(c.variant)}</td><td>${esc(c.part_code)} · ${esc(c.name)}</td><td class="calc num">${fmt(c.quantity, 2)}</td></tr>`).join("")}</tbody></table></div>` : ""}

    <h3 class="block-title">History</h3>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th></tr></thead><tbody>
      ${p.history.map((h) => `<tr><td>${esc(h.at.slice(0, 16).replace("T", " "))}</td><td>${esc(h.user)}</td><td>${esc(h.action.replace("_", " "))}</td>
        <td>${historyText(h.detail)}</td></tr>`).join("")}</tbody></table></div>`;
}

function historyText(d) {
  return Object.entries(d || {}).map(([k, v]) =>
    v && typeof v === "object" && "old" in v ? `${esc(k)}: ${esc(v.old ?? "—")} → <b>${esc(v.new ?? "—")}</b>` : `${esc(k)}: ${esc(v)}`).join("<br/>");
}

$("panelBody").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (e.target.id === "partForm") {
    const f = new FormData(e.target);
    const data = Object.fromEntries([...f.entries()].filter(([k]) => k !== "shape" && !k.startsWith("dim_")));
    data.price_is_example = f.has("price_is_example");
    data.dimensions = readDims(f) ?? {};
    try {
      await api(`/api/parts/${part.id}`, { method: "PUT", body: JSON.stringify(data) });
      await openPart(part.id);
      status($("partStatus"), "Saved. The change is in the history below.", "ok");
      search();
    } catch (err) {
      status($("partStatus"), err.message, "error");
    }
  }
  if (e.target.id === "rmForm") {
    const f = new FormData(e.target);
    const inputs = {};
    for (const [k, v] of f.entries()) if (k.startsWith("in_") && v !== "") inputs[k.slice(3)] = Number(v);
    status($("rmStatus"), "Calculating…");
    try {
      const res = await api(`/api/parts/${part.id}/rm-cost`, { method: "POST", body: JSON.stringify({
        rm_inputs: inputs, country: f.get("country"), costing_month: f.get("costing_month"), reason: "changed in the part panel" }) });
      await openPart(part.id);
      search();
      status($("rmStatus"), res.message, "ok");
    } catch (err) {
      status($("rmStatus"), err.message, "error");
    }
  }
  if (e.target.id === "toolForm") {
    const f = new FormData(e.target);
    const inputs = { warranty: f.has("warranty"), hot_runner: f.has("hot_runner") };
    for (const k of ["cavities", "slides_per_cavity", "lifters_per_cavity", "inserts_per_cavity"]) if (f.get(k)) inputs[k] = Number(f.get(k));
    if (inputs.warranty) delete inputs.warranty; // the default
    if (!inputs.hot_runner) delete inputs.hot_runner;
    status($("toolStatus"), "Calculating…");
    try {
      const res = await api(`/api/parts/${part.id}/tool-cost`, { method: "POST", body: JSON.stringify({
        tool_inputs: inputs, tool_country: f.get("tool_country"), reason: "changed in the part panel" }) });
      await openPart(part.id);
      search();
      status($("toolStatus"), res.message, res.stored === false && res.version === null ? "error" : "ok");
    } catch (err) {
      status($("toolStatus"), err.message, "error");
    }
  }
  if (e.target.id === "insertForm") {
    const f = new FormData(e.target);
    const data = { insert_part_code: f.get("insert_part_code"), quantity: f.get("quantity"), name: f.get("name"),
      material: f.get("material"), dimensions: readDims(f, "n_"), price_is_example: f.has("n_price_is_example") };
    for (const k of ["unit_price", "price_currency", "price_source", "price_month"]) data[k] = f.get(`n_${k}`);
    if (!data.name) delete data.material;
    try {
      await api(`/api/parts/${part.id}/inserts`, { method: "POST", body: JSON.stringify(data) });
      await openPart(part.id);
      search();
    } catch (err) {
      status($("insertStatus"), err.message, "error");
    }
  }
  if (e.target.id === "revForm") {
    status($("revStatus"), "Reading the STEP file…");
    try {
      await api(`/api/parts/${part.id}/revisions`, { method: "POST", body: new FormData(e.target) });
      await openPart(part.id);
      search();
    } catch (err) {
      status($("revStatus"), err.message, "error");
    }
  }
});

$("panelBody").addEventListener("click", async (e) => {
  const t = e.target.closest("[data-trace]");
  if (t) {
    try {
      const trace = part.trace || (await api(`/api/parts/${part.id}/trace`));
      if (!trace.nodes[t.dataset.trace]) throw new Error("Set the part's material to see its weight (density comes from Master data → Materials).");
      window.TracePanel.open(trace, t.dataset.trace);
    } catch (err) {
      status($("partStatus"), err.message, "error");
    }
  }
  const rt = e.target.closest("[data-rmtrace]");
  if (rt && part.rmTrace) window.TracePanel.open(part.rmTrace, rt.dataset.rmtrace);
  const rv = e.target.closest("[data-rmversion]");
  if (rv) {
    const tr = await api(`/api/parts/${part.id}/rm-cost/trace?version=${rv.dataset.rmversion}`);
    window.TracePanel.open(tr, tr.root);
  }
  const tt = e.target.closest("[data-tooltrace]");
  if (tt && part.toolTrace) window.TracePanel.open(part.toolTrace, tt.dataset.tooltrace);
  const tvn = e.target.closest("[data-toolversion]");
  if (tvn) {
    const tr = await api(`/api/parts/${part.id}/tool-cost/trace?version=${tvn.dataset.toolversion}`);
    window.TracePanel.open(tr, tr.root);
  }
  if (e.target.id === "conceptRun") {
    status($("conceptStatus"), "Analysing the 3D model…");
    try {
      const c = await api(`/api/parts/${part.id}/concept`);
      status($("conceptStatus"), "");
      $("conceptOut").innerHTML = `<p>Opening direction <b>${esc(c.opening_axis.toUpperCase())}</b> (least undercut; the register uses ${esc(c.stored_pull_direction.toUpperCase())}, largest shadow).
        Undercut area ${fmt(c.undercut_area_cm2, 1)} cm² → <b>${c.slides}</b> slide(s), <b>${c.lifters}</b> lifter(s).${c.sampled ? " Faces were sampled." : ""}</p>
        <div class="table-wrap"><table class="cost-table"><thead><tr><th>Axis</th><th class="num">Undercut (mm²)</th><th class="num">Shadow (mm²)</th></tr></thead><tbody>
        ${c.ranking.map((r) => `<tr><td>${esc(r.axis.toUpperCase())}</td><td class="num">${fmt(r.undercut_area_mm2, 0)}</td><td class="num">${fmt(r.projected_area_mm2, 0)}</td></tr>`).join("")}</tbody></table></div>
        ${c.regions.length ? `<ul>${c.regions.map((r) => `<li><b>${esc(r.kind)}</b> · ${fmt(r.area_mm2, 0)} mm² at ${r.centre_mm.join(", ")} · ${esc(r.reason)}</li>`).join("")}</ul>` : ""}
        <h4>Proposals</h4><ul>${c.proposals.map((x) => `<li><b>${esc(x.topic)}</b>: ${esc(x.proposal)} <span class="note">(${esc(x.rule)}${x.is_example ? ", EXAMPLE rule" : ""})</span></li>`).join("")}</ul>
        <button type="button" class="btn btn-primary small" id="conceptApply" data-slides="${c.slides}" data-lifters="${c.lifters}">Use ${c.slides} slide(s) and ${c.lifters} lifter(s) in the tool cost</button>`;
    } catch (err) {
      status($("conceptStatus"), err.message, "error");
    }
  }
  if (e.target.id === "simRun") {
    status($("simStatus"), "Analysing the 3D model…");
    try {
      const r = await api(`/api/parts/${part.id}/simulation`);
      status($("simStatus"), "");
      const m = r.maps, mc = r.machine;
      $("simOut").innerHTML = `${r.is_example ? '<p class="note"><b>Uses EXAMPLE simulation rules.</b></p>' : ""}
        <h4>${r.corrections.length ? "Corrections required" : "No corrections required"}</h4>
        <ul>${r.corrections.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
        ${part.loop ? `<button type="button" class="btn btn-outline small" id="simToLoop" data-status="${r.corrections.length ? "corrections_required" : "simulation_ok"}"
          data-comment="${esc(r.corrections.join(" "))}">Put this result in the Design loop form</button>` : ""}
        <p>Opening ${esc(r.opening_axis.toUpperCase())} · wall ${fmt(r.wall_mm, 2)} mm · low draft ${fmt(m.draft_low_cm2, 1)} cm² · sink risk ${fmt(m.sink_risk_cm2, 1)} cm² ·
          thin ${fmt(m.thin_cm2, 1)} cm² · undercut ${fmt(m.undercut_cm2, 1)} cm²${r.sampled ? " (faces sampled)" : ""}<br/>
          Cycle <b>${fmt(r.results.cycle_s, 1)} s</b> · clamp <b>${fmt(r.results.clamp_t, 1)} t</b> → machine <b>${esc(mc.machine_id || "none large enough")}</b>${mc.tonnage_t ? ` (${fmt(mc.tonnage_t)} t)` : ""}</p>
        <div class="table-wrap"><table class="cost-table"><thead><tr><th>Step</th><th>Formula</th><th class="num">Value</th></tr></thead><tbody>
        ${r.steps.map((x) => `<tr><td>${esc(x.label || x.name)}</td><td><code>${esc(x.formula)}</code></td><td class="num">${fmt(x.value, 2)} ${esc(x.unit)}</td></tr>`).join("")}</tbody></table></div>`;
    } catch (err) {
      status($("simStatus"), err.message, "error");
    }
  }
  if (e.target.id === "simToLoop") {
    const sel = $("loopForm").elements.status;
    if (![...sel.options].some((o) => o.value === e.target.dataset.status)) return status($("simStatus"), "That status is not an allowed next step from the current status.", "error");
    sel.value = e.target.dataset.status;
    $("loopComment").value = e.target.dataset.comment || "Simulation OK, no corrections";
    $("loopForm").scrollIntoView({ block: "center" });
  }
  if (e.target.id === "conceptApply") {
    const inputs = { ...(part.tool_inputs || {}), slides_per_cavity: Number(e.target.dataset.slides), lifters_per_cavity: Number(e.target.dataset.lifters) };
    await api(`/api/parts/${part.id}/tool-cost`, { method: "POST", body: JSON.stringify({ tool_inputs: inputs, reason: "slides / lifters from the mould concept" }) });
    await openPart(part.id);
    search();
  }
  if (e.target.id === "toolRecalc") {
    e.target.disabled = true;
    try {
      const res = await api(`/api/parts/${part.id}/tool-cost`, { method: "POST", body: JSON.stringify({ reason: "recalculated with the latest approved rates" }) });
      await openPart(part.id);
      search();
      status($("partStatus"), res.message, "ok");
    } catch (err) {
      e.target.disabled = false;
      status($("partStatus"), err.message, "error");
    }
  }
  if (e.target.id === "rmRecalc") {
    e.target.disabled = true;
    try {
      const res = await api(`/api/parts/${part.id}/rm-cost`, { method: "POST", body: JSON.stringify({ reason: "recalculated with the latest approved rates" }) });
      await openPart(part.id);
      search();
      status($("partStatus"), res.message, "ok");
    } catch (err) {
      e.target.disabled = false;
      status($("partStatus"), err.message, "error");
    }
  }
  const o = e.target.closest("[data-open]");
  if (o) openPart(Number(o.dataset.open));
  const u = e.target.closest("[data-unlink]");
  if (u && confirm("Remove this insert from the part? The insert part itself stays in the register.")) {
    try {
      await api(`/api/parts/${part.id}/inserts/${u.dataset.unlink}`, { method: "DELETE" });
      await openPart(part.id);
      search();
    } catch (err) {
      status($("partStatus"), err.message, "error");
    }
  }
  if (e.target.id === "useSuggestion") {
    $("partForm").elements.namedItem("process").value = part.suggestion.process;
    $("partForm").requestSubmit();
  }
});

// shape picked: show its dimension inputs; code typed: offer matching part codes
$("panelBody").addEventListener("input", async (e) => {
  if (e.target.name === "insert_part_code" && e.target.value.length >= 2) {
    const res = await api(`/api/parts?q=${encodeURIComponent(e.target.value)}&limit=15`).catch(() => null);
    if (res) $("codeList").innerHTML = res.rows.filter((r) => r.id !== part.id && !r.is_assembly)
      .map((r) => `<option value="${esc(r.part_code)}">${esc(r.name)}</option>`).join("");
  }
});

// country comparison and landed cost in India (stage 11)
function compareBlock(p) {
  if (p.is_assembly || !p.tool?.applicable) return "";
  return `<h3 class="block-title">Country comparison and landed cost</h3>
    <form id="cmpForm" class="card grid2">
      <label>Freight <select name="mode"><option value="sea">Sea</option><option value="air">Air</option></select></label>
      <label class="check"><input type="checkbox" name="use_fta" checked /> Use FTA / preferential duty where there is one</label>
      <div class="span2 dialog-actions"><button type="submit" class="btn btn-primary small">Compare all countries</button></div>
      <p class="status span2" id="cmpStatus"></p></form><div id="cmpOut"></div>`;
}

const CMP_COLORS = ["#1f6feb", "#2da44e", "#bf8700", "#8250df", "#8b949e", "#0969da", "#cf222e", "#6e7781"];
function renderCompare(res) {
  const ok = res.rows.filter((r) => !r.error);
  const seg = (r) => [r.components_inr.rm, r.components_inr.process, r.components_inr.tool, r.components_inr.packing, r.components_inr.other,
    r.landed.freight + r.landed.insurance, r.landed.bcd + r.landed.sws + r.landed.igst - r.landed.igst_credit, r.landed.clearance + r.landed.inland];
  const labels = ["RM", "Process", "Tool", "Packing", "Other", "Freight+ins.", "Duty+IGST net", "Clearance+inland"];
  const max = Math.max(...ok.map((r) => r.landed.landed), 1e-9);
  const bars = ok.map((r) => `<div style="display:flex;align-items:center;gap:6px;margin:2px 0"><b style="width:28px">${esc(r.country)}</b>
    <div style="display:flex;height:16px;width:${(r.landed.landed / max) * 70}%">${seg(r).map((v, i) => `<span title="${labels[i]} ${fmt(v, 2)}"
      style="background:${CMP_COLORS[i]};width:${(v / r.landed.landed) * 100}%"></span>`).join("")}</div>
    <span class="${r.country === res.cheapest ? "strong" : ""}">${fmt(r.landed.landed, 2)}${r.country === res.cheapest ? " ◀ cheapest" : ""}</span></div>`).join("");
  const q = `mode=${res.mode}&use_fta=${res.use_fta}`;
  return `${ok.some((r) => r.is_example) ? '<p class="note"><span class="badge badge-example">EXAMPLE</span> Uses example rates and duties – not for negotiation.</p>' : ""}
    <div>${bars}</div><p class="note">${labels.map((l, i) => `<span style="color:${CMP_COLORS[i]}">■</span> ${l}`).join(" · ")}</p>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th>Country</th><th class="num">Ex-works (local)</th><th class="num">USD</th><th class="num">Ex-works INR</th>
      <th class="num">Freight+ins.</th><th class="num">BCD+SWS</th><th class="num">IGST</th><th class="num">IGST credit</th><th class="num">Landed INR</th>
      <th class="num">Forex −${res.fx_pct}% / +${res.fx_pct}%</th><th class="num">Tool landed INR</th></tr></thead><tbody>
    ${res.rows.map((r) => r.error ? `<tr><td>${esc(r.country)}</td><td colspan="10" class="empty">${esc(r.error)}</td></tr>` : `<tr class="${r.country === res.cheapest ? "total" : ""}">
      <td>${esc(r.country)}</td><td class="calc num">${fmt(r.exw_local, 2)} ${esc(r.currency)}</td><td class="calc num">${fmt(r.exw_usd, 2)}</td><td class="calc num">${fmt(r.exw_inr, 2)}</td>
      <td class="calc num">${fmt(r.landed.freight + r.landed.insurance, 2)}</td><td class="calc num">${fmt(r.landed.bcd + r.landed.sws, 2)} <small>${esc(r.landed.duty_basis)}</small></td>
      <td class="calc num">${fmt(r.landed.igst, 2)}</td><td class="calc num">${fmt(r.landed.igst_credit, 2)}</td><td class="calc num"><b>${fmt(r.landed.landed, 2)}</b></td>
      <td class="calc num">${Object.entries(r.forex.scenario).filter(([k]) => k !== "0%").map(([, v]) => fmt(v, 2)).join(" / ")}</td>
      <td class="calc num">${fmt(r.tool.landed.landed, 0)}</td></tr>`).join("")}</tbody></table></div>
    <p class="note">Part and tool made in each country with that country's approved rates; the landed cost adds freight, insurance, duty, IGST (credit shown apart),
      clearance and inland transport in India. Cheapest tool landed: ${esc(res.cheapest_tool || "—")}.
      <a class="link" href="/api/parts/${part.id}/country-comparison/export.xlsx?${q}">Excel</a> · <a class="link" href="/api/parts/${part.id}/country-comparison/export.pdf?${q}">PDF</a></p>`;
}

$("panelBody").addEventListener("submit", async (e) => {
  if (e.target.id !== "cmpForm") return;
  e.preventDefault();
  const f = new FormData(e.target);
  status($("cmpStatus"), "Costing the part in every country…");
  try {
    const res = await api(`/api/parts/${part.id}/country-comparison?mode=${f.get("mode")}&use_fta=${f.has("use_fta")}`);
    status($("cmpStatus"), "");
    $("cmpOut").innerHTML = renderCompare(res);
  } catch (err) {
    status($("cmpStatus"), err.message, "error");
  }
});

// sheet-metal tools I: operation sequence, die type, forces, press, formability
function sheetBlock(p) {
  const s = p.sheet;
  if (!s) return "";
  let html = `<h3 class="block-title">Sheet-metal tools</h3>`;
  if (s.problem) return html + `<p class="note">${esc(s.problem)}</p>`;
  const f = s.features, pr = s.press["all stations"];
  html += `${s.is_example ? '<p class="note"><span class="badge badge-example">EXAMPLE</span> Uses example sheet rules.</p>' : ""}
    <p>Die type <b>${s.mode === "progressive" ? "Progressive" : "Multi-stage"}</b> (suggested: ${s.recommended === "progressive" ? "progressive" : "multi-stage"}) ·
      sequence ${esc(s.sequence_source)} · thickness ${fmt(f.t, 2)} mm · ${f.hole_count} hole(s) · ${f.bends} bend(s) · draw ${fmt(f.draw_depth, 1)} mm</p>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th>#</th><th>Operation</th><th class="num">Force (t)</th><th class="num">Stage weight (g)</th><th>Press</th></tr></thead><tbody>
    ${s.operations.map((o) => `<tr><td>${o.n}</td><td>${esc(o.name)}</td><td class="calc num">${fmt(o.force_t, 1)}</td><td class="calc num">${fmt(o.stage_weight_g, 1)}</td>
      <td>${o.press ? esc(o.press.machine_id || "none large enough") : ""}</td></tr>`).join("")}
    <tr class="total"><td></td><td>Total × safety ${fmt(s.safety_factor, 2)}</td><td class="calc num">${fmt(s.design_force_t, 1)}</td><td></td>
      <td>${pr ? esc(pr.machine_id ? `${pr.machine_id} (${fmt(pr.tonnage_t)} t)` : "none large enough") : ""}</td></tr></tbody></table></div>
    ${s.problems.length ? `<h4>Formability</h4><ul>${s.problems.map((x) => `<li>${esc(x.message)}</li>`).join("")}</ul>` : '<p class="note">Formability checks passed.</p>'}
    ${layoutBlock(p)}
    <form id="sheetForm" class="card grid2">
      <label>Die type <select name="mode"><option value="">Follow the part's process</option>
        <option value="progressive" ${p.sheet_inputs?.mode === "progressive" ? "selected" : ""}>Progressive</option>
        <option value="multi_stage" ${p.sheet_inputs?.mode === "multi_stage" ? "selected" : ""}>Multi-stage</option></select></label>
      <label>Draw depth (mm) <input type="number" min="0" step="any" name="draw_depth_mm" value="${p.sheet_inputs?.draw_depth_mm ?? ""}" placeholder="from the model" /></label>
      <label>Inside bend radius (mm) <input type="number" min="0" step="any" name="bend_radius_mm" value="${p.sheet_inputs?.bend_radius_mm ?? ""}" placeholder="from the model" /></label>
      <label class="span2">Operations in order (codes, comma-separated; blank = suggested). Available: ${s.available_operations.map((o) => esc(o.code)).join(", ")}
        <input name="operations" value="${esc((p.sheet_inputs?.operations || []).join(", "))}" /></label>
      <div class="span2 dialog-actions"><button type="submit" class="btn btn-primary small">Save and recalculate</button></div>
      <p class="status span2" id="sheetStatus"></p></form>`;
  return html;
}

// flat pattern, progressive strip layout and downloads (stage 10)
function layoutBlock(p) {
  const l = p.layout;
  if (!l) return "";
  const fp = l.flat_pattern, b = l.strip.best, v = b.values, o = l.strip.other.values;
  return `<h4>Blank and strip layout</h4>
    <p>Blank ${fmt(fp.length_mm, 1)} × ${fmt(fp.width_mm, 1)} mm, area ${fmt(fp.area_mm2, 0)} mm² · ${esc(fp.method)}</p>
    <div class="table-wrap"><table class="cost-table"><tbody>
      <tr><td>Feed</td><td class="calc num">${esc(b.feed)}</td></tr>
      <tr><td>Pitch · bridge · edge (mm)</td><td class="calc num">${fmt(v.pitch_mm, 1)} · ${fmt(v.bridge_mm, 1)} · ${fmt(v.edge_mm, 1)}</td></tr>
      <tr><td>Strip width (mm)</td><td class="calc num">${fmt(v.strip_width_mm, 1)}</td></tr>
      <tr><td>Stations · pilots</td><td class="calc num">${fmt(v.stations)} · ${fmt(v.pilots)} × Ø${fmt(v.pilot_dia_mm, 1)}</td></tr>
      <tr class="total"><td>Material utilisation (other feed direction ${fmt(o.utilisation_pct, 1)} %)</td><td class="calc num">${fmt(v.utilisation_pct, 1)} %</td></tr></tbody></table></div>
    ${l.strip.problems.map((x) => `<p class="note"><b>${esc(x)}</b></p>`).join("")}
    <p class="note">Download: <a class="link" href="/api/parts/${p.id}/sheet-layout/blank.dxf">Blank DXF</a> ·
      <a class="link" href="/api/parts/${p.id}/sheet-layout/strip.dxf">Strip DXF</a> ·
      <a class="link" href="/api/parts/${p.id}/sheet-layout/tool-pack.pdf">Tool pack PDF</a></p>`;
}

$("panelBody").addEventListener("submit", async (e) => {
  if (e.target.id !== "sheetForm") return;
  e.preventDefault();
  const f = new FormData(e.target);
  const inputs = {};
  if (f.get("mode")) inputs.mode = f.get("mode");
  for (const k of ["draw_depth_mm", "bend_radius_mm"]) if (f.get(k) !== "") inputs[k] = Number(f.get(k));
  if (f.get("operations").trim()) inputs.operations = f.get("operations").split(",").map((x) => x.trim()).filter(Boolean);
  try {
    await api(`/api/parts/${part.id}`, { method: "PUT", body: JSON.stringify({ sheet_inputs: inputs }) });
    await openPart(part.id);
  } catch (err) {
    status($("sheetStatus"), err.message, "error");
  }
});

// part (piece) cost: live traced result, typed inputs, stored versions, downloads
function pieceBlock(p) {
  const s = p.piece;
  if (!s) return "";
  let html = `<h3 class="block-title">Part cost</h3>`;
  if (s.problem) return html + `<p class="note">${esc(s.problem)}</p>`;
  const tr = s.live, cur = tr.currency;
  const v = (n) => `<span class="clickable calc" data-piecetrace="${esc(n)}">${fmt(tr.nodes[n].value, 4)}</span>`;
  html += `${tr.is_example ? '<p class="note"><span class="badge badge-example">EXAMPLE</span> Uses example rates – not for negotiation.</p>' : ""}
    ${s.outdated ? `<p class="note"><b>${esc(s.outdated)}</b></p>` : ""}
    <div class="table-wrap"><table class="cost-table"><tbody>
      ${tr.steps.map((x) => `<tr class="${x.is_result ? "total" : ""}"><td>${esc(tr.nodes[x.node].label)}</td><td class="num">${v(x.node)} ${esc(tr.nodes[x.node].unit)}</td></tr>`).join("")}
      <tr class="total"><td>Part cost per piece (INR)</td><td class="num">${v("result:inr")}</td></tr></tbody></table></div>
    <p class="note">Machine ${esc(tr.machine)} · operator grade ${esc(tr.grade)} · RM version ${tr.rm_version} · tool version ${tr.tool_version} ·
      ${esc(tr.country)} · ${esc(tr.as_of)}. Click any value for its formula, inputs and rate versions.
      ${s.latest ? `<a class="link" href="/api/parts/${p.id}/piece-cost/export.xlsx">Excel</a> · <a class="link" href="/api/parts/${p.id}/piece-cost/export.pdf">PDF</a>` : ""}</p>
    <form id="pieceForm" class="card grid2">
      <label>Cycle time (s) <input type="number" min="0" step="any" name="cycle_s" value="${p.piece_inputs?.cycle_s ?? ""}" placeholder="Parameters" /></label>
      <label>Cavities <input type="number" min="1" step="1" name="cavities" value="${p.piece_inputs?.cavities ?? ""}" placeholder="tool cost" /></label>
      <label>Secondary operations (% of process) <input type="number" min="0" step="any" name="secondary_ops_pct" value="${p.piece_inputs?.secondary_ops_pct ?? ""}" placeholder="Parameters" /></label>
      <div class="span2 dialog-actions"><button type="submit" class="btn btn-primary small">Save and store part cost</button></div>
      <p class="status span2" id="pieceStatus"></p></form>`;
  if (s.versions.length) html += `<details class="card add-insert"><summary class="btn btn-outline small">Part cost versions (${s.versions.length})</summary>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th>Ver</th><th>Rev</th><th>Country</th><th>Month</th><th class="num">${esc(cur)}</th><th class="num">INR</th><th>Why</th><th>By / when</th></tr></thead><tbody>
    ${s.versions.map((x) => `<tr class="clickable" data-pieceversion="${x.version}"><td><b>${x.version}</b></td><td>${esc(x.rev)}</td><td>${esc(x.country)}</td><td>${esc(x.as_of)}</td>
      <td class="calc num">${fmt(x.piece_cost, 4)}</td><td class="calc num">${fmt(x.piece_cost_inr, 4)}</td><td>${esc(x.reason)}</td>
      <td>${esc(x.created_by)} · ${esc(x.created_at.slice(0, 16).replace("T", " "))}</td></tr>`).join("")}</tbody></table></div></details>`;
  return html;
}

$("panelBody").addEventListener("submit", async (e) => {
  if (e.target.id !== "pieceForm") return;
  e.preventDefault();
  const f = new FormData(e.target);
  const inputs = {};
  for (const k of ["cycle_s", "cavities", "secondary_ops_pct"]) if (f.get(k) !== "") inputs[k] = Number(f.get(k));
  try {
    const r = await api(`/api/parts/${part.id}/piece-cost`, { method: "POST", body: JSON.stringify({ piece_inputs: inputs, reason: "changed in the part panel" }) });
    await openPart(part.id);
    status($("pieceStatus"), r.message, "ok");
  } catch (err) {
    status($("pieceStatus"), err.message, "error");
  }
});

$("panelBody").addEventListener("click", async (e) => {
  const n = e.target.closest("[data-piecetrace]");
  if (n) window.TracePanel.open(part.piece.live, n.dataset.piecetrace);
  const pv = e.target.closest("[data-pieceversion]");
  if (pv) {
    const tr = await api(`/api/parts/${part.id}/piece-cost/trace?version=${pv.dataset.pieceversion}`);
    window.TracePanel.open(tr, tr.root);
  }
});

// design loop: status flow, allowed moves, timeline
function loopBlock(p) {
  const l = p.loop;
  if (!l) return "";
  const name = (c) => l.flow.find((f) => f.code === c)?.name ?? c;
  return `<h3 class="block-title">Design loop</h3>
    <p>${l.flow.map((f) => `<span class="badge ${f.code === l.status ? "status" : ""}" title="${fmt(f.days, 1)} days">${esc(f.name)}</span>`).join(" → ")}</p>
    <form id="loopForm" class="card grid2">
      <label>Move to <select name="status">${l.next.map((c) => `<option value="${esc(c)}">${esc(name(c))}</option>`).join("")}</select></label>
      <label>Comment (what has to change, or why) <input name="comment" id="loopComment" /></label>
      <div class="span2 dialog-actions"><button type="submit" class="btn btn-primary small">Change status</button></div>
      <p class="status span2" id="loopStatus"></p></form>
    <details class="card add-insert"><summary class="btn btn-outline small">What changed, who, when (${l.timeline.length})</summary>
      <div class="table-wrap"><table class="cost-table"><thead><tr><th>When</th><th>Who</th><th>What</th></tr></thead><tbody>
      ${l.timeline.slice().reverse().map((e) => `<tr><td>${esc(e.when.slice(0, 16).replace("T", " "))}</td><td>${esc(e.who)}</td><td>${
        e.action === "status_changed" ? `${esc(name(e.old))} → <b>${esc(name(e.new))}</b>${e.comment ? ` · ${esc(e.comment)}` : ""}`
        : e.action === "revision_added" ? `Revision <b>${esc(e.rev)}</b> ${esc(e.change_note || "")}` : "Created"}</td></tr>`).join("")}</tbody></table></div></details>`;
}

$("panelBody").addEventListener("submit", async (e) => {
  if (e.target.id !== "loopForm") return;
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await api(`/api/parts/${part.id}/status`, { method: "POST", body: JSON.stringify({ status: f.get("status"), comment: f.get("comment") }) });
    await openPart(part.id);
    search();
  } catch (err) {
    status($("loopStatus"), err.message, "error");
  }
});

// side-by-side compare of two revisions
$("panelBody").addEventListener("change", (e) => {
  if (e.target.dataset.dims != null) {
    const prefix = e.target.dataset.dims;
    const shape = meta.insert_shapes.find((s) => s.code === e.target.value);
    e.target.closest("form").querySelector(`.dims[data-for="${prefix}"]`).innerHTML = shape
      ? shape.dims.map((d) => `<label>${esc(d)} <input type="number" min="0" step="any" name="${prefix}dim_${d}" required /></label>`).join("") : "";
    return;
  }
  if (!e.target.classList.contains("cmp")) return;
  const ids = [...document.querySelectorAll(".cmp:checked")].map((c) => Number(c.value));
  if (ids.length !== 2) return ($("compare").innerHTML = ids.length > 2 ? '<p class="note">Tick exactly two revisions.</p>' : "");
  const [a, b] = ids.map((id) => part.revisions.find((r) => r.id === id));
  const rows = [
    ["File", (g, r) => r.original_name || "—"],
    ["What changed", (g, r) => r.change_note || "—"],
    ["Volume (cm³)", (g) => fmt(g.volume_cm3, 3)],
    ["Surface (cm²)", (g) => fmt((g.surface_area_mm2 ?? 0) / 100, 2)],
    ["Bounding box (mm)", (g) => (g.bbox_mm ? `${fmt(g.bbox_mm.length, 1)} × ${fmt(g.bbox_mm.width, 1)} × ${fmt(g.bbox_mm.height, 1)}` : "—")],
    ["Main wall (mm)", (g) => fmt(g.wall_mm, 2)],
    ["RM cost, latest (INR)", (g, r) => fmt(part.rmVersions.find((x) => x.rev === r.rev)?.net_rm_cost_inr, 2)],
    ["Tool cost, latest (INR)", (g, r) => fmt(part.toolVersions.find((x) => x.rev === r.rev)?.tool_cost_inr, 0)],
    ["By / when", (g, r) => `${r.created_by} · ${r.created_at.slice(0, 16).replace("T", " ")}`],
  ];
  $("compare").innerHTML = `<h3 class="block-title">Compare rev ${esc(a.rev)} and rev ${esc(b.rev)}</h3>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th></th><th>Rev ${esc(a.rev)}</th><th>Rev ${esc(b.rev)}</th></tr></thead><tbody>
    ${rows.map(([label, f]) => {
      const x = f(a.geometry || {}, a), y = f(b.geometry || {}, b);
      return `<tr><td>${label}</td><td class="calc">${esc(x)}</td><td class="calc ${x !== y ? "strong" : ""}">${esc(y)}${x !== y ? " ◀" : ""}</td></tr>`;
    }).join("")}</tbody></table></div>`;
});

init();


// Design pack (roadmap stage 20): corrected 3D design, tool design, drawings, simulation video and downloads
function designPackBlock(p) {
  const moulds = p.tool?.applicable && !p.tool.problem && /plastic|die_casting|injection|casting/.test(p.process || "");
  if (p.is_assembly || !(moulds || p.sheet)) return "";
  return `<h3 class="block-title">Design pack: corrected 3D, tool design, drawings, video</h3>
    <div class="card" id="packCard">
      <p class="note">${p.sheet ? "Every stage of the sheet-metal tool (die set in 3D, plan drawing, press from 0 to 3000 t), strip and blank, reports and video."
        : "Draft correction on the 3D model from the simulation, simulation again on the corrected part, mould concept in 3D, corrected drawing, reports and video."}
        Concept level: the engineer's CAD governs the final tool.</p>
      <label>Simulation video <select id="packVideo"><option value="short">short (fast)</option><option value="full">full</option><option value="none">none</option></select></label>
      <button type="button" class="btn btn-primary small" id="packRun">Build design pack</button> <span class="status" id="packStatus"></span>
      <div id="packOut"></div></div>`;
}

const PACK_LABELS = { xlsx: "Excel report", pdf: "PDF report", pptx: "PowerPoint", "3d": "3D report (open in browser)", drawing: "Corrected drawing (PDF)",
  "drawing-dxf": "Corrected drawing (DXF)", "corrected-step": "Corrected part (STEP)", "tool-step": "Tool design (STEP)", "tool-drawing": "Tool design drawing (PDF)",
  video: "Simulation video (MP4)", "stage-drawings": "Stage tool drawings (PDF)", "part-drawing": "Part drawing (PDF)", "part-drawing-dxf": "Part drawing (DXF)",
  "blank-dxf": "Blank (DXF)", "strip-dxf": "Strip (DXF)", "tool-pack": "Tool pack (PDF)" };

$("panelBody").addEventListener("click", async (e) => {
  if (e.target.id !== "packRun") return;
  const video = $("packVideo").value;
  e.target.disabled = true;
  status($("packStatus"), "Building: correcting the 3D model, designing the tool, drawing, rendering. This can take a minute…");
  try {
    const r = await api(`/api/parts/${part.id}/design-pack?video=${video}`);
    status($("packStatus"), `Built in ${r.seconds} s`);
    const s = r.summary, base = `/api/parts/${part.id}/design-pack`;
    const facts = s.kind === "mould"
      ? `Draft-deficient wall ${fmt(s.draft_before_cm2, 1)} → ${fmt(s.draft_after_cm2, 2)} cm² (${s.faces_drafted} faces drafted${s.faces_failed ? `, ${s.faces_failed} not` : ""}) · machine ${esc(s.machine || "none")} · mould base ${esc(s.mould_base)}`
      : `${esc(s.mode.replace("_", " "))} · ${s.stages} stage(s) · ${fmt(s.total_force_t, 1)} t · presses ${esc([...new Set(s.presses)].join(", ") || "none")}`;
    const warn = [...(s.warnings || []), ...(s.corrections_after || [])];
    $("packOut").innerHTML = `<p>${facts}</p>
      ${warn.length ? `<h4>Still open for R&amp;D / the tool designer</h4><ul>${warn.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
      <ul class="links">${Object.entries(r.kinds).filter(([, n]) => n).map(([k, n]) =>
        `<li><a class="link" href="${base}/${encodeURIComponent(n)}?video=${video}" ${k === "3d" ? 'target="_blank"' : ""}>${esc(PACK_LABELS[k] || k)}</a></li>`).join("")}
        <li><a class="link" href="${base}.zip?video=${video}"><b>Everything (ZIP)</b></a></li></ul>`;
  } catch (err) {
    status($("packStatus"), err.message, "error");
  }
  e.target.disabled = false;
});
