// Project dashboard: projects, variants, part status, BOM, CAPEX vs targets.
const { $, esc, fmt, inr, api, registerMeta, status } = window.DTC;
let meta = null;
const nameOf = (list, code) => list?.find((x) => x.code === code)?.name ?? code ?? "";
let projects = [];
let dash = null;
let editingVariant = null;

const current = () => Number($("project").value) || null;

async function loadProjects(select) {
  projects = await api("/api/projects");
  $("project").innerHTML = projects.map((p) => `<option value="${p.id}">${esc(p.code)} · ${esc(p.name)} (${p.part_count} parts)</option>`).join("");
  const want = select ?? Number(new URLSearchParams(location.search).get("project")) ?? null;
  if (want && projects.some((p) => p.id === want)) $("project").value = want;
  $("empty").hidden = projects.length > 0;
  $("content").hidden = projects.length === 0;
  ["editProject", "newVariant", "openParts", "importLink", "xlsx", "pdf", "rmRecalc", "toolRecalc", "pieceRecalc"].forEach((id) => ($(id).hidden = !projects.length));
  if (projects.length) load();
}

async function load() {
  const id = current();
  history.replaceState(null, "", `?project=${id}`);
  $("openParts").href = `/parts?project=${id}`;
  $("importLink").href = `/import?project=${id}`;
  $("xlsx").href = `/api/parts/export.xlsx?project_id=${id}`;
  $("pdf").href = `/api/projects/${id}/dashboard.pdf`;
  try {
    dash = await api(`/api/projects/${id}/dashboard`);
  } catch (err) {
    status($("status"), err.message, "error");
    return;
  }
  status($("status"), "");
  render();
  loadLeader();
}

// ---------- project leader view (stage 13) ----------
let lead = null;
async function loadLeader() {
  try {
    lead = await api(`/api/projects/${current()}/leader`);
  } catch (err) {
    $("leader").innerHTML = `<p class="warn">${esc(err.message)}</p>`;
    return;
  }
  renderLeader();
}

function renderLeader() {
  const l = lead, c = l.capex, pl = l.plan;
  const stateCls = (s) => (s === "over target" ? "badge missing" : s === "within target" ? "badge status" : "badge");
  $("leader").innerHTML = `
    ${l.is_example ? window.exampleBanner("The BOM cost or machine prices use EXAMPLE values.") : ""}
    <h3 class="block-title">Project leader view · BOM cost vs target</h3>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th>Variant</th><th class="num">Target</th><th class="num">BOM cost</th><th class="num">Difference</th><th class="num">%</th><th>State</th><th class="num">Parts without cost</th></tr></thead><tbody>
      ${l.variants.map((v) => `<tr><td>${esc(v.code)} · ${esc(v.name)}</td><td class="calc num">${inr(v.target_inr)}</td><td class="calc num">${inr(v.bom_cost_inr)}${v.is_example ? " •" : ""}</td>
        <td class="calc num">${v.delta_inr != null ? (v.delta_inr > 0 ? "+" : "") + fmt(v.delta_inr, 2) : "—"}</td><td class="calc num">${v.delta_pct != null ? fmt(v.delta_pct, 1) + " %" : "—"}</td>
        <td><span class="${stateCls(v.state)}">${esc(v.state)}</span></td><td class="calc num">${v.parts_missing || "0"}</td></tr>`).join("") || '<tr><td colspan="7" class="empty">No variant yet.</td></tr>'}</tbody></table></div>
    <p class="note">BOM cost = Σ quantity × part cost per piece (parts we make) or bought-out price. ${l.parts_without_piece_cost ? `<b>${l.parts_without_piece_cost} part(s) have no part cost yet</b>: open the part, or press “Recalculate part costs”. ` : ""}Moulded-in inserts are inside their body's cost.</p>
    <div class="tiles">
      ${tile("CAPEX budget", inr(c.budget_inr), `SOP ${esc(pl.sop_date || "not set")}`)}
      ${tile("Tools & moulds", inr(c.tool_inr), "stored tool CAPEX")}
      ${tile("Machines", inr(c.machine_inr), `${l.machines.rows.reduce((a, m) => a + m.machines, 0)} machine(s) from capacity`)}
      ${tile("Total CAPEX", inr(c.total_inr), c.left_inr != null ? `${c.left_inr < 0 ? "over by " + inr(-c.left_inr) : inr(c.left_inr) + " left"}` : "", c.over_budget)}
      ${tile("Open corrections", fmt(l.corrections.length), l.corrections.slice(0, 3).map((x) => esc(x.part_code)).join(", "), l.corrections.length > 0)}
    </div>
    <h3 class="block-title">Machines needed (from the stored part costs)</h3>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th>Machine</th><th class="num">Hours / yr</th><th class="num">Per machine</th><th class="num">Machines</th><th class="num">Utilisation</th><th class="num">CAPEX</th></tr></thead><tbody>
      ${l.machines.rows.map((m) => `<tr><td>${esc(m.machine_id)} <small>${esc(m.country)}</small></td><td class="calc num">${fmt(m.hours_needed)}</td><td class="calc num">${fmt(m.hours_per_machine)}</td>
        <td class="calc num"><b>${m.machines}</b></td><td class="calc num">${fmt(m.utilisation_pct, 1)} %</td><td class="calc num">${inr(m.capex_inr)}${m.is_example ? " •" : ""}</td></tr>`).join("") || '<tr><td colspan="6" class="empty">No part cost stored yet.</td></tr>'}</tbody></table></div>
    <h3 class="block-title">CAPEX plan · suppliers, countries, payment milestones</h3>
    <p><button type="button" class="btn btn-outline small" id="capexBuild">Add lines for costed tools and machines</button>
       <button type="button" class="btn btn-outline small" id="capexAdd">+ Other CAPEX line</button>
       <a class="btn btn-outline small" href="/api/projects/${current()}/leader.xlsx">Leader Excel</a> <a class="btn btn-primary small" href="/api/projects/${current()}/leader.pdf">Leader PDF</a></p>
    <div class="table-wrap"><table class="cost-table" id="capexTable"><thead><tr><th>Kind</th><th>Line</th><th>Supplier</th><th>Country</th><th class="num">Amount</th><th>Need by</th><th>Payments (due · amount · paid)</th><th></th></tr></thead><tbody>
      ${pl.items.map((i) => `<tr><td>${esc(i.kind)}</td><td>${esc(i.description)}</td><td>${esc(i.supplier || "—")}</td><td>${esc(i.country || "—")}</td><td class="calc num">${inr(i.amount_inr)}</td>
        <td>${esc(i.need_by_effective || "—")}</td><td>${i.milestones.map((m) => `<label class="check"><input type="checkbox" data-pay="${i.id}" data-ms="${esc(m.milestone)}" ${m.paid_date ? "checked" : ""} />
          ${esc(m.milestone)} ${esc(m.due || "no date")} · ${inr(m.amount_inr)}${m.overdue ? ' <span class="badge missing">overdue</span>' : ""}</label>`).join("<br/>")}</td>
        <td><button type="button" class="btn btn-outline small" data-capex-edit="${i.id}">Edit</button></td></tr>`).join("") || '<tr><td colspan="8" class="empty">No CAPEX lines yet. Add the costed tools and machines, or an other line.</td></tr>'}</tbody></table></div>
    <div class="two-col"><div><h3 class="block-title">Cash-out by month</h3><div class="table-wrap"><table class="cost-table"><tbody>
      ${pl.by_month.map(([m, a]) => `<tr><td>${esc(m)}</td><td class="calc num">${inr(a)}</td></tr>`).join("") || '<tr><td class="empty">—</td></tr>'}</tbody></table></div></div>
      <div><h3 class="block-title">By supplier and country</h3><div class="table-wrap"><table class="cost-table"><tbody>
      ${pl.by_supplier.map(([k, a]) => `<tr><td>Supplier · ${esc(k)}</td><td class="calc num">${inr(a)}</td></tr>`).join("")}
      ${pl.by_country.map(([k, a]) => `<tr><td>Country · ${esc(k)}</td><td class="calc num">${inr(a)}</td></tr>`).join("")}</tbody></table></div></div></div>
    ${l.corrections.length ? `<h3 class="block-title">Open corrections</h3><ul>${l.corrections.map((x) => `<li><a class="link" href="/parts?part=${x.part_id}">${esc(x.part_code)}</a> ${esc(x.name)} · ${esc(x.status)}</li>`).join("")}</ul>` : ""}`;
}

$("leader").addEventListener("click", async (e) => {
  if (e.target.id === "capexBuild") {
    const r = await api(`/api/projects/${current()}/capex/build`, { method: "POST" });
    status($("status"), `${r.created} line(s) added, ${r.refreshed} amount(s) refreshed.`, "ok");
    loadLeader();
  }
  if (e.target.id === "capexAdd") editCapex(null);
  const ed = e.target.closest("[data-capex-edit]");
  if (ed) editCapex(lead.plan.items.find((i) => i.id === Number(ed.dataset.capexEdit)));
});
$("leader").addEventListener("change", async (e) => {
  const pay = e.target.closest("[data-pay]");
  if (!pay) return;
  const item = lead.plan.items.find((i) => i.id === Number(pay.dataset.pay));
  const payments = Object.fromEntries(item.milestones.filter((m) => m.paid_date).map((m) => [m.milestone, m.paid_date]));
  if (pay.checked) payments[pay.dataset.ms] = new Date().toISOString().slice(0, 10);
  else delete payments[pay.dataset.ms];
  await api(`/api/capex/${item.id}`, { method: "PUT", body: JSON.stringify({ payments }) });
  loadLeader();
});
// simple editor: prompts keep the page small
async function editCapex(item) {
  const ask = (label, cur) => window.prompt(label, cur ?? "");
  const description = ask("Line (what is bought)", item?.description);
  if (description === null) return;
  const data = { description, supplier: ask("Supplier", item?.supplier), country: ask("Country code (e.g. CN, IN)", item?.country),
    amount_inr: ask("Amount (INR)", item?.amount_inr), need_by: ask("Need-by date YYYY-MM-DD (blank = SOP date)", item?.need_by) };
  if (item) data.supplier ??= "";
  try {
    if (item) {
      if (item.source_key) delete data.amount_inr;
      await api(`/api/capex/${item.id}`, { method: "PUT", body: JSON.stringify(data) });
    } else await api(`/api/projects/${current()}/capex`, { method: "POST", body: JSON.stringify({ kind: "other", ...data }) });
    loadLeader();
  } catch (err) {
    status($("status"), err.message, "error");
  }
}
$("pieceRecalc").addEventListener("click", async () => {
  status($("status"), "Recalculating the part cost of every part…");
  try {
    const r = await api(`/api/projects/${current()}/piece-cost/recalculate`, { method: "POST" });
    await load();
    status($("status"), `${r.new_versions} part(s) got a new part cost version, ${r.unchanged} unchanged.` + (r.problems.length ? ` ${r.problems.length} could not be costed (open the part to see why).` : ""), r.problems.length ? "error" : "ok");
  } catch (err) {
    status($("status"), err.message, "error");
  }
});

function tile(label, value, sub = "", alert = false) {
  return `<div class="card tile ${alert ? "alert" : ""}"><div class="label">${esc(label)}</div>
    <div class="value">${value}</div><div class="sub">${sub}</div></div>`;
}

function bars(rows, total) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return `<thead><tr><th>Name</th><th class="num">Parts</th><th class="num">Share</th><th></th></tr></thead><tbody>` +
    (rows.length ? rows.map((r) => `<tr><td>${esc(r.name)}</td><td class="calc num">${r.count}</td>
      <td class="calc num">${total ? fmt((r.count / total) * 100, 0) : 0} %</td>
      <td class="bar-cell"><div class="bar" style="width:${(r.count / max) * 100}%" title="${r.count} parts"></div></td></tr>`).join("")
      : '<tr><td colspan="4" class="empty">No parts yet.</td></tr>') + "</tbody>";
}

function render() {
  const d = dash, p = d.project;
  $("tiles").innerHTML =
    tile("Parts", fmt(d.parts_total), `${d.variants.length} variant${d.variants.length === 1 ? "" : "s"}`) +
    tile("File missing", fmt(d.file_missing), "parts without a 3D file", d.file_missing > 0) +
    tile("Open corrections", fmt(d.open_corrections), "from the design loop", d.open_corrections > 0) +
    tile("CAPEX budget", inr(d.capex.budget_inr), "tools, moulds & machines") +
    tile("Tool & mould CAPEX" + (d.capex.tool_is_example ? " •" : ""), inr(d.capex.tool_cost_inr),
      `${d.capex.tool_parts_costed} part${d.capex.tool_parts_costed === 1 ? "" : "s"} costed` +
      (d.capex.tool_share_of_budget_pct != null ? ` · ${fmt(d.capex.tool_share_of_budget_pct, 1)} % of budget` : "") +
      (d.capex.tool_parts_missing ? ` · ${d.capex.tool_parts_missing} without tool cost` : ""),
      d.capex.tool_share_of_budget_pct > 100 || d.capex.tool_parts_missing > 0) +
    tile("Parts with RM cost", fmt(d.parts_rm_costed), "raw material only") +
    tile("Parts with target", fmt(d.parts_with_target), d.target_piece_cost_sum_inr != null ? `sum of targets ${inr(d.target_piece_cost_sum_inr)}` : "");
  $("notCosted").textContent = d.not_costed_note;
  const examples = [d.rm_is_example && "the RM cost of at least one variant", d.tool_is_example && "the tool & mould CAPEX"].filter(Boolean);
  $("exampleBanner").innerHTML = examples.length
    ? window.exampleBanner(`${examples.join(" and ").replace(/^./, (c) => c.toUpperCase())} uses EXAMPLE values (marked •).`) : "";
  $("toolNote").textContent = d.capex.tool_note || "";

  $("variants").innerHTML = `<thead><tr><th>Variant</th><th>Name</th><th class="num">Annual volume</th><th class="num">BOM lines</th>
    <th class="num">Unique parts</th><th class="num">Target BOM cost</th><th class="num">RM cost (raw material only)</th><th class="num">RM vs target</th><th class="num">Parts without RM</th><th></th></tr></thead><tbody>` +
    (d.variants.length ? d.variants.map((v, i) => `<tr class="clickable" data-v="${i}"><td>${esc(v.code)}</td><td>${esc(v.name)}</td>
      <td class="calc num">${fmt(v.annual_volume)}</td><td class="calc num">${v.bom_lines}</td><td class="calc num">${v.unique_parts}</td>
      <td class="calc num">${inr(v.target_bom_cost_inr)}</td><td class="calc num">${inr(v.rm_cost_inr)}${v.rm_is_example ? ' <span class="example-mark" title="Uses example rates">•</span>' : ""}</td>
      <td class="calc num">${v.rm_cost_inr != null && v.target_bom_cost_inr ? fmt((v.rm_cost_inr / v.target_bom_cost_inr) * 100, 1) + " % of target" : "—"}</td>
      <td class="calc num">${v.rm_parts_missing ? `<span class="badge missing">${v.rm_parts_missing}</span>` : v.rm_parts_costed ? "0" : "—"}</td>
      <td><button type="button" class="btn btn-outline small" data-edit="${i}">Edit</button></td></tr>`).join("")
      : '<tr><td colspan="10" class="empty">No variant yet. Add one with “+ Variant”.</td></tr>') + "</tbody>";

  $("byStatus").innerHTML = bars(d.status, d.parts_total);
  $("byProcess").innerHTML = bars(d.process, d.parts_total);
  $("bySourcing").innerHTML = bars(d.sourcing, d.parts_total);
  $("bomBlock").hidden = true;
}

$("variants").addEventListener("click", async (e) => {
  const edit = e.target.closest("[data-edit]");
  if (edit) return openVariant(dash.variants[Number(edit.dataset.edit)]);
  const row = e.target.closest("[data-v]");
  if (!row) return;
  document.querySelectorAll("#variants tr").forEach((r) => r.classList.toggle("selected", r === row));
  const v = dash.variants[Number(row.dataset.v)];
  meta ??= await registerMeta();
  const bom = await api(`/api/variants/${v.id}/bom`);
  $("bomTitle").textContent = `BOM · ${v.code} ${v.name}`;
  $("bom").innerHTML = `<thead><tr><th>Part code</th><th>Name</th><th class="num">Qty in parent</th><th class="num">Total qty</th>
    <th>Sourcing</th><th>Status</th></tr></thead><tbody>` +
    (bom.length ? bom.map((b) => `<tr><td style="padding-left:${10 + b.depth * 18}px">${b.depth ? "└ " : ""}
      <a class="link" href="/parts?part=${b.child_part_id}">${esc(b.part_code)}</a></td><td>${esc(b.name)}${b.is_assembly ? ' <span class="badge assy">assembly</span>' : ""}${b.kind === "insert" ? ' <span class="badge insert" title="Moulded-in insert of the part above: bought separately, not assembled">moulded-in insert</span>' : ""}</td>
      <td class="calc num">${fmt(b.quantity, 2)}</td><td class="calc num">${fmt(b.total_quantity, 2)}</td><td>${esc(nameOf(meta.sourcing, b.sourcing))}</td>
      <td><span class="badge status">${esc(nameOf(meta.statuses, b.status))}</span></td></tr>`).join("")
      : '<tr><td colspan="6" class="empty">This variant has no BOM yet. Import an assembly or use the Excel template with the variant column.</td></tr>') + "</tbody>";
  $("bomBlock").hidden = false;
});

// ---------- dialogs ----------
document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));
let editingProject = false;
function openProject(edit) {
  editingProject = edit;
  const f = $("projectForm");
  f.reset();
  $("projectTitle").textContent = edit ? "Edit project" : "New project";
  if (edit) {
    const p = dash.project;
    for (const k of ["code", "name", "customer", "description", "capex_budget_inr", "sop_date"]) f.elements.namedItem(k).value = p[k] ?? "";
  }
  f.elements.namedItem("code").readOnly = edit;
  status($("projectStatus"), "");
  $("projectDialog").showModal();
}
$("newProject").addEventListener("click", () => openProject(false));
$("emptyNew").addEventListener("click", () => openProject(false));
$("editProject").addEventListener("click", () => openProject(true));
$("projectForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target).entries());
  try {
    const p = editingProject
      ? await api(`/api/projects/${current()}`, { method: "PUT", body: JSON.stringify(data) })
      : await api("/api/projects", { method: "POST", body: JSON.stringify(data) });
    $("projectDialog").close();
    loadProjects(p.id);
  } catch (err) {
    status($("projectStatus"), err.message, "error");
  }
});

function openVariant(v) {
  editingVariant = v || null;
  const f = $("variantForm");
  f.reset();
  $("variantTitle").textContent = v ? `Edit variant ${v.code}` : "New variant";
  if (v) for (const k of ["code", "name", "target_bom_cost_inr", "annual_volume", "notes"]) f.elements.namedItem(k).value = v[k] ?? "";
  status($("variantStatus"), "");
  $("variantDialog").showModal();
}
$("newVariant").addEventListener("click", () => openVariant(null));
$("variantForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target).entries());
  try {
    if (editingVariant) await api(`/api/variants/${editingVariant.id}`, { method: "PUT", body: JSON.stringify(data) });
    else await api(`/api/projects/${current()}/variants`, { method: "POST", body: JSON.stringify(data) });
    $("variantDialog").close();
    load();
  } catch (err) {
    status($("variantStatus"), err.message, "error");
  }
});

$("rmRecalc").addEventListener("click", async () => {
  $("rmRecalc").disabled = true;
  status($("status"), "Recalculating RM cost with the latest approved rates…");
  try {
    const r = await api(`/api/projects/${current()}/rm-cost/recalculate`, { method: "POST" });
    await load();
    status($("status"), `${r.new_versions} part${r.new_versions === 1 ? "" : "s"} got a new RM cost version, ${r.unchanged} unchanged.` +
      (r.problems.length ? ` ${r.problems.length} could not be costed (open the part to see why).` : ""), r.problems.length ? "error" : "ok");
  } catch (err) {
    status($("status"), err.message, "error");
  } finally {
    $("rmRecalc").disabled = false;
  }
});
$("toolRecalc").addEventListener("click", async () => {
  $("toolRecalc").disabled = true;
  status($("status"), "Recalculating the tool cost of every part with the latest approved rates…");
  try {
    const r = await api(`/api/projects/${current()}/tool-cost/recalculate`, { method: "POST" });
    await load();
    status($("status"), `${r.new_versions} part${r.new_versions === 1 ? "" : "s"} got a new tool cost version, ${r.unchanged} unchanged.` +
      (r.problems.length ? ` ${r.problems.length} could not be costed (open the part to see why).` : ""), r.problems.length ? "error" : "ok");
  } catch (err) {
    status($("status"), err.message, "error");
  } finally {
    $("toolRecalc").disabled = false;
  }
});
$("project").addEventListener("change", load);
loadProjects();
