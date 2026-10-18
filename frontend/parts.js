// Part register: search/filter, part panel with revisions, history and traced geometry.
const { $, esc, fmt, inr, api, registerMeta, options, status, thumb } = window.DTC;
const PAGE = 50;
let offset = 0;
let meta, projects;
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
  $("table").innerHTML = `<thead><tr><th></th><th>Part code</th><th>Name</th><th>Rev</th><th>Project</th><th>Process</th>
    <th>Material</th><th>Status</th><th>Sourcing</th><th class="num">Volume (cm³)</th><th>File</th></tr></thead><tbody>` +
    (res.rows.length ? res.rows.map((r) => `<tr class="clickable" data-id="${r.id}"><td>${thumb(r.thumbnail_file_id)}</td>
      <td><b>${esc(r.part_code)}</b></td><td>${esc(r.name)}${r.is_assembly ? ' <span class="badge assy">assembly</span>' : ""}</td>
      <td>${esc(r.rev ?? "")}</td><td>${esc(r.project_code)}</td><td>${esc(nameOf(meta.processes, r.process))}</td>
      <td>${esc(r.material)}</td><td><span class="badge status">${esc(nameOf(meta.statuses, r.status))}</span></td>
      <td>${esc(nameOf(meta.sourcing, r.sourcing))}</td>
      <td class="calc num">${r.geometry?.volume_cm3 != null ? fmt(r.geometry.volume_cm3, 2) : "—"}</td>
      <td>${r.file_id ? "STEP" : '<span class="badge missing">File missing</span>'}</td></tr>`).join("")
      : '<tr><td colspan="11" class="empty">No parts match. Import parts on the Import page.</td></tr>') + "</tbody>";
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
  if (part.file_id) part.trace = await api(`/api/parts/${id}/trace`).catch(() => null);
  renderPart();
  $("panel").hidden = false;
}

function geometryRows(g) {
  if (!g || g.assembly) return g?.assembly ? `<tr><td>Structure</td><td class="calc">${g.children.map(([n, q]) => `${esc(n)} × ${q}`).join(", ")}</td></tr>` : "";
  const b = g.bbox_mm;
  return `<tr><td>Volume</td><td class="calc num"><button type="button" class="tv" data-trace="volume">${fmt(g.volume_cm3, 3)} cm³</button></td></tr>
    <tr><td>Net weight</td><td class="calc num">${part.trace?.nodes.weight ? `<button type="button" class="tv" data-trace="weight">${fmt(part.trace.nodes.weight.value, 2)} g</button>` : "set a material to calculate"}</td></tr>
    <tr><td>Bounding box L × W × H</td><td class="calc num">${fmt(b.length, 1)} × ${fmt(b.width, 1)} × ${fmt(b.height, 1)} mm</td></tr>
    <tr><td>Projected area (along ${esc(g.pull_direction.toUpperCase())})</td><td class="calc num"><button type="button" class="tv" data-trace="proj">${fmt(g.projected_area_mm2[g.pull_direction] / 100, 2)} cm²</button></td></tr>
    <tr><td>Main wall / sheet thickness</td><td class="calc num">${fmt(g.wall_mm, 2)} mm (${fmt(g.sheet_share * 100, 0)} % sheet-like)</td></tr>`;
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
          <label>Material <select name="material">${options(meta.materials, p.material, "—")}</select></label>
          <label>Process ${sel("process", meta.processes, p.process)}</label>
          <label>Sourcing ${sel("sourcing", meta.sourcing, p.sourcing)}</label>
          <label>Status ${sel("status", meta.statuses, p.status)}</label>
          <label>Annual volume <input type="number" name="annual_volume" min="0" value="${p.annual_volume ?? ""}" /></label>
          <label>Programme life (years) <input type="number" name="programme_life_years" min="0" step="any" value="${p.programme_life_years ?? ""}" /></label>
          <label>Target piece cost (INR) <input type="number" name="target_piece_cost_inr" min="0" step="any" value="${p.target_piece_cost_inr ?? ""}" /></label>
          <label class="span2">Notes <input name="notes" value="${esc(p.notes)}" /></label>
          <div class="span2 dialog-actions"><button type="submit" class="btn btn-primary">Save changes</button></div>
          <p class="status span2" id="partStatus"></p>
        </form></div>
    </div>

    <h3 class="block-title">Geometry · rev ${esc(cur?.rev ?? "—")}</h3>
    <div class="table-wrap"><table class="cost-table"><tbody>${geometryRows(cur?.geometry) || '<tr><td class="empty">No 3D file for this revision.</td></tr>'}</tbody></table></div>

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
    const data = Object.fromEntries(new FormData(e.target).entries());
    try {
      part = await api(`/api/parts/${part.id}`, { method: "PUT", body: JSON.stringify(data) });
      part.trace = part.file_id ? await api(`/api/parts/${part.id}/trace`).catch(() => null) : null;
      renderPart();
      status($("partStatus"), "Saved. The change is in the history below.", "ok");
      search();
    } catch (err) {
      status($("partStatus"), err.message, "error");
    }
  }
  if (e.target.id === "revForm") {
    status($("revStatus"), "Reading the STEP file…");
    try {
      part = await api(`/api/parts/${part.id}/revisions`, { method: "POST", body: new FormData(e.target) });
      part.trace = await api(`/api/parts/${part.id}/trace`).catch(() => null);
      renderPart();
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
  const o = e.target.closest("[data-open]");
  if (o) openPart(Number(o.dataset.open));
});

// side-by-side compare of two revisions
$("panelBody").addEventListener("change", (e) => {
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
  ];
  $("compare").innerHTML = `<h3 class="block-title">Compare rev ${esc(a.rev)} and rev ${esc(b.rev)}</h3>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th></th><th>Rev ${esc(a.rev)}</th><th>Rev ${esc(b.rev)}</th></tr></thead><tbody>
    ${rows.map(([label, f]) => {
      const x = f(a.geometry || {}, a), y = f(b.geometry || {}, b);
      return `<tr><td>${label}</td><td class="calc">${esc(x)}</td><td class="calc ${x !== y ? "strong" : ""}">${esc(y)}${x !== y ? " ◀" : ""}</td></tr>`;
    }).join("")}</tbody></table></div>`;
});

init();
