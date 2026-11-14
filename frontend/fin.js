// Heat-exchanger fin dies (stage 57): fin spec -> fin die cost (BOM) and fin part cost per pack / fin / kg, traced.
const { $, esc, fmt, api, status } = window.DTC;
let opts = null, current = null, last = null;

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
  $("fName").value = rec.name || "";
  $("fProject").value = rec.project_id || "";
  const s = rec.spec;
  $("fPattern").value = s.pattern; $("fMaterial").value = s.material; $("fCountry").value = s.country || ""; $("fPress").value = s.press || "";
  Object.keys(opts.spec).forEach((k) => { $("n_" + k).value = s[k] ?? opts.default[k]; });   // fields added later: their default
  ["xlsx", "pdf", "delBtn"].forEach((id) => ($(id).hidden = !current));
  if (current) { $("xlsx").href = `/api/fin-dies/${current.id}/export.xlsx`; $("pdf").href = `/api/fin-dies/${current.id}/export.pdf`; }
}

function spec() {
  const s = { pattern: $("fPattern").value, material: $("fMaterial").value, country: $("fCountry").value, press: $("fPress").value };
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
  if (!id) { fill({ name: "", project_id: "", spec: opts.default }); $("out").innerHTML = ""; return; }
  fill(await api(`/api/fin-dies/${id}`));
  await run(() => api(`/api/fin-dies/${id}/cost`));
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
  const body = JSON.stringify({ name: $("fName").value, project_id: Number($("fProject").value) || null, spec: spec() });
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
init().catch((err) => status($("status"), err.message, "error"));
