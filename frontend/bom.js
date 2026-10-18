// Harness & PCB BOM extraction: upload, review (low-confidence lines in yellow), edit, mark reviewed, Excel.
const { $, esc, fmt, api, status } = window.DTC;
let ex = null;
const COLS = [["category", "Category"], ["ref", "Ref / designators"], ["part_number", "Part number"], ["maker", "Maker"], ["description", "Description"],
  ["qty", "Qty"], ["unit", "Unit"], ["length_mm", "Length mm (wires: total)"], ["wire_type", "Wire type"], ["cross_section_mm2", "mm²"], ["colour", "Colour"],
  ["package", "Package"], ["mount", "Mount"]];

async function loadList(select) {
  const list = await api("/api/bom-extracts");
  $("extract").innerHTML = list.map((e) => `<option value="${e.id}">#${e.id} · ${esc(e.name)} (${esc(e.kind)}, ${e.line_count} lines, ${esc(e.status)})</option>`).join("") || "<option value=''>No extract yet</option>";
  if (select) $("extract").value = select;
  if (list.length) await open(Number($("extract").value));
  else { ex = null; $("out").innerHTML = ""; ["reviewBtn", "xlsx", "del"].forEach((id) => ($(id).hidden = true)); showCostControls(false); }
}

async function open(id) {
  ex = await api(`/api/bom-extracts/${id}`);
  render();
}

async function costSetup() {
  const setup = await api("/api/costing-setup");
  $("costCountry").innerHTML = setup.countries.map((c) => `<option value="${esc(c.code)}">${esc(c.name)} (${esc(c.currency)})</option>`).join("");
  $("costCountry").value = "IN";
}
function showCostControls(on) {
  ["costTitle", "costForm"].forEach((id) => ($(id).hidden = !on));
  if (!on) $("cost").innerHTML = "";
}
$("costForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = new URLSearchParams({ country: $("costCountry").value, ...($("costMonth").value ? { month: $("costMonth").value } : {}) }).toString();
  status($("status"), "Calculating…");
  try {
    const c = await api(`/api/bom-extracts/${ex.id}/cost?${q}`);
    status($("status"), "");
    $("costXlsx").href = `/api/bom-extracts/${ex.id}/cost.xlsx?${q}`;
    $("costPdf").href = `/api/bom-extracts/${ex.id}/cost.pdf?${q}`;
    $("costXlsx").hidden = $("costPdf").hidden = false;
    const n = c.nodes, v = (k) => `<span class="clickable calc" data-trace="${esc(k)}">${fmt(n[k].value, 4)}</span>`;
    window.lastCost = c;
    $("cost").innerHTML = `${c.is_example || c.library_examples ? '<p class="note"><span class="badge badge-example">EXAMPLE</span> Uses example rates or library prices – not for negotiation.</p>' : ""}
      ${c.priced ? "" : `<div class="warn"><b>Not fully priced</b>: these count as 0 until they are in <i>Master data → Part register setup → Part library</i>:<ul>${c.missing.map((m) => `<li>${esc(m)}</li>`).join("")}</ul></div>`}
      ${!c.reviewed || c.low_confidence_lines ? `<p class="note">The BOM is ${c.reviewed ? "reviewed" : "<b>not reviewed</b>"} and has ${c.low_confidence_lines} line(s) to check.</p>` : ""}
      <div class="table-wrap"><table class="cost-table"><tbody>
        ${c.steps.map((s) => `<tr class="${s.is_result ? "total" : ""}"><td>${esc(n[s.node].label)}</td><td class="num">${v(s.node)} ${esc(n[s.node].unit)}</td></tr>`).join("")}
        <tr class="total"><td>Cost in INR</td><td class="num">${v("result:inr")}</td></tr></tbody></table></div>
      <h4>Priced lines</h4><div class="table-wrap"><table class="cost-table"><thead><tr><th>Category</th><th>Part</th><th>Description</th><th class="num">Qty</th><th class="num">Cost</th><th>Basis</th></tr></thead><tbody>
        ${c.lines.map((l) => `<tr><td>${esc(l.category)}</td><td>${esc(l.part_number || l.ref)}</td><td>${esc(l.description)}</td><td class="calc num">${fmt(l.qty, 2)}</td>
          <td class="calc num">${l.cost == null ? '<span class="badge missing">not priced</span>' : fmt(l.cost, 4)}</td><td>${esc(l.basis)}</td></tr>`).join("")}</tbody></table></div>
      <p class="note">Click a value for its formula, inputs and rate versions.</p>`;
  } catch (err) {
    status($("status"), err.message, "error");
  }
});
document.addEventListener("click", (e) => {
  const t = e.target.closest("#cost [data-trace]");
  if (t && window.lastCost) window.TracePanel.open(window.lastCost, t.dataset.trace);
});

function render() {
  showCostControls(true);
  const s = ex.summary;
  ["reviewBtn", "xlsx", "del"].forEach((id) => ($(id).hidden = false));
  $("xlsx").href = `/api/bom-extracts/${ex.id}/export.xlsx`;
  $("reviewBtn").textContent = ex.status === "reviewed" ? `Reviewed by ${ex.reviewed_by} · reopen` : "Mark reviewed";
  const cats = ex.categories;
  $("out").innerHTML = `<p><b>${esc(ex.name)}</b> · ${esc(ex.format)} · ${s.lines} lines · <span class="${s.low_confidence ? "badge missing" : "badge status"}">${s.low_confidence} to check</span>
    ${ex.kind === "harness" ? ` · wire length ${fmt(s.wire_length_m, 2)} m` : ` · SMT ${fmt(s.by_mount.SMT || 0)} · THT ${fmt(s.by_mount.THT || 0)}`}</p>
    <div class="table-wrap tall"><table class="cost-table"><thead><tr>${COLS.map(([, l]) => `<th>${l}</th>`).join("")}<th>Confidence</th><th></th></tr></thead><tbody>
    ${ex.lines.map((l) => `<tr data-id="${l.id}" style="${l.confidence < ex.low_threshold ? "background:#fff2cc" : ""}">
      ${COLS.map(([k]) => k === "category" ? `<td><select data-f="category">${cats.map((c) => `<option ${c === l.category ? "selected" : ""}>${c}</option>`).join("")}</select></td>`
        : k === "mount" ? `<td><select data-f="mount">${["", "SMT", "THT"].map((c) => `<option ${c === (l.mount || "") ? "selected" : ""}>${c}</option>`).join("")}</select></td>`
        : `<td><input data-f="${k}" value="${esc(l[k] ?? "")}" size="${k === "description" ? 22 : k === "ref" ? 16 : 9}" /></td>`).join("")}
      <td title="${esc(l.flags.join("; ") || l.source)}">${fmt(l.confidence, 2)}${l.edited ? " ✎" : ""}<br/><small>${esc(l.flags.join("; "))}</small><br/><small>${esc(l.source)}</small></td>
      <td><button type="button" class="btn btn-outline small" data-del="${l.id}">✕</button></td></tr>`).join("")}</tbody></table></div>
    <p><button type="button" class="btn btn-outline small" id="addLine">+ Add line</button></p>
    <p class="note">Yellow lines have a confidence under ${ex.low_threshold}: the reason is under the number. Editing a line sets its confidence to 1. The BOM is priced in stage 15.</p>`;
}

$("out").addEventListener("change", async (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (!tr || !e.target.dataset.f) return;
  try {
    ex = await api(`/api/bom-extracts/${ex.id}/lines/${tr.dataset.id}`, { method: "PUT", body: JSON.stringify({ [e.target.dataset.f]: e.target.value }) });
    status($("status"), "Saved.", "ok");
    render();
  } catch (err) {
    status($("status"), err.message, "error");
  }
});
$("out").addEventListener("click", async (e) => {
  const d = e.target.closest("[data-del]");
  try {
    if (d) ex = await api(`/api/bom-extracts/${ex.id}/lines/${d.dataset.del}`, { method: "DELETE" });
    else if (e.target.id === "addLine") ex = await api(`/api/bom-extracts/${ex.id}/lines`, { method: "POST", body: JSON.stringify({ category: ex.categories[0], description: "New line", qty: 1 }) });
    else return;
    render();
  } catch (err) {
    status($("status"), err.message, "error");
  }
});
$("extract").addEventListener("change", () => open(Number($("extract").value)));
$("reviewBtn").addEventListener("click", async () => {
  ex = await api(`/api/bom-extracts/${ex.id}/status`, { method: "POST", body: JSON.stringify({ status: ex.status === "reviewed" ? "draft" : "reviewed" }) });
  render();
  loadList(ex.id);
});
$("del").addEventListener("click", async () => {
  if (!confirm("Delete this extract and all its lines?")) return;
  await api(`/api/bom-extracts/${ex.id}`, { method: "DELETE" });
  loadList();
});
$("uploadForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  for (const k of [...f.keys()]) if (f.get(k) === "" || (f.get(k) instanceof File && !f.get(k).name)) f.delete(k);
  status($("uploadStatus"), "Reading the file…");
  try {
    const r = await api("/api/bom-extracts", { method: "POST", body: f });
    status($("uploadStatus"), `${r.lines.length} lines read, ${r.summary.low_confidence} to check.`, "ok");
    await loadList(r.id);
  } catch (err) {
    status($("uploadStatus"), err.message, "error");
  }
});
(async () => {
  await costSetup();
  const projects = await api("/api/projects").catch(() => []);
  $("project").innerHTML = '<option value="">None</option>' + projects.map((p) => `<option value="${p.id}">${esc(p.code)} · ${esc(p.name)}</option>`).join("");
  loadList();
})();
