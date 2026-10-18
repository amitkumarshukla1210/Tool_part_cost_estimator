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
  ["editProject", "newVariant", "openParts", "importLink", "xlsx", "pdf", "rmRecalc"].forEach((id) => ($(id).hidden = !projects.length));
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
}

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
    tile("Tool & mould CAPEX", inr(d.capex.tool_cost_inr), "costed so far") +
    tile("Parts with RM cost", fmt(d.parts_rm_costed), "raw material only") +
    tile("Parts with target", fmt(d.parts_with_target), d.target_piece_cost_sum_inr != null ? `sum of targets ${inr(d.target_piece_cost_sum_inr)}` : "");
  $("notCosted").textContent = d.not_costed_note;

  $("variants").innerHTML = `<thead><tr><th>Variant</th><th>Name</th><th class="num">Annual volume</th><th class="num">BOM lines</th>
    <th class="num">Unique parts</th><th class="num">Target BOM cost</th><th class="num">RM cost (raw material only)</th><th class="num">RM vs target</th><th class="num">Parts without RM</th><th></th></tr></thead><tbody>` +
    (d.variants.length ? d.variants.map((v, i) => `<tr class="clickable" data-v="${i}"><td>${esc(v.code)}</td><td>${esc(v.name)}</td>
      <td class="calc num">${fmt(v.annual_volume)}</td><td class="calc num">${v.bom_lines}</td><td class="calc num">${v.unique_parts}</td>
      <td class="calc num">${inr(v.target_bom_cost_inr)}</td><td class="calc num">${inr(v.rm_cost_inr)}</td>
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
    for (const k of ["code", "name", "customer", "description", "capex_budget_inr"]) f.elements.namedItem(k).value = p[k] ?? "";
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
$("project").addEventListener("change", load);
loadProjects();
