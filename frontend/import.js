// Import: STEP part / assembly (preview tree, then register) and Excel bulk upload.
const { $, esc, fmt, api, registerMeta, options, status } = window.DTC;
let meta, projects = [], manifest = null;

async function init() {
  meta = await registerMeta();
  projects = await api("/api/projects");
  if (!projects.length) {
    status($("stepStatus"), "Create a project first (Dashboard → + New project).", "error");
  }
  $("project").innerHTML = projects.map((p) => `<option value="${p.id}">${esc(p.code)} · ${esc(p.name)}</option>`).join("");
  const want = new URLSearchParams(location.search).get("project");
  if (want) $("project").value = want;
  $("pattern").textContent = meta.part_code_pattern;
  fillVariants();
}

function fillVariants() {
  const p = projects.find((x) => x.id === Number($("project").value));
  if (!p) return;
  api(`/api/projects/${p.id}`).then((full) => {
    $("variant").innerHTML = '<option value="">— none (register only) —</option>' +
      full.variants.map((v) => `<option value="${v.id}">${esc(v.code)} · ${esc(v.name)}</option>`).join("");
    if (full.variants.length) $("variant").value = full.variants[0].id;
  });
}
$("project").addEventListener("change", fillVariants);

$("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-tab]");
  if (!b) return;
  document.querySelectorAll("#tabs [data-tab]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
  $("tab-step").hidden = b.dataset.tab !== "step";
  $("tab-excel").hidden = b.dataset.tab !== "excel";
});

// ---------- STEP: preview ----------
$("stepForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  status($("stepStatus"), "Reading the STEP file, splitting the assembly and making thumbnails…");
  $("preview").hidden = true;
  try {
    manifest = await api("/api/import/step", { method: "POST", body: new FormData(e.target) });
  } catch (err) {
    return status($("stepStatus"), err.message, "error");
  }
  const n = Object.values(manifest.defs).filter((d) => !d.is_assembly).length;
  status($("stepStatus"), `${manifest.file_name}: ${n} unique part${n === 1 ? "" : "s"}` +
    (Object.keys(manifest.defs).length > 1 ? `, ${Object.values(manifest.defs).filter((d) => d.is_assembly).length} assemblies` : ""), "ok");
  renderTree();
});

function rowsInOrder() {
  const out = [], seen = new Set();
  const walk = (key, depth, qty) => {
    out.push({ key, depth, qty, repeat: seen.has(key) });
    if (seen.has(key)) return;
    seen.add(key);
    for (const [child, q] of Object.entries(manifest.defs[key].children)) walk(child, depth + 1, q);
  };
  walk(manifest.root, 0, 1);
  return out;
}

// Material choices: estimator materials, then bought-out insert materials.
function materialOptions(value) {
  const opt = (m) => `<option value="${esc(m)}" ${m === value ? "selected" : ""}>${esc(m)}</option>`;
  return `<option value="">—</option><optgroup label="Part materials">${meta.materials.map(opt).join("")}</optgroup>` +
    `<optgroup label="Insert materials">${meta.insert_materials.map((m) => opt(m.name)).join("")}</optgroup>`;
}
const procName = (code) => meta.processes.find((p) => p.code === code)?.name ?? code;

// detected inserts of a body, and whether each is ticked
const insertsOf = (key) => (manifest.inserts || []).filter((x) => x.body === key);
const confirmedInserts = (key) =>
  insertsOf(key).filter((x) => document.querySelector(`.ins-confirm[data-body="${key}"][data-insert="${x.insert}"]`)?.checked);
const isConfirmedInsert = (key) =>
  (manifest.inserts || []).some((x) => x.insert === key && document.querySelector(`.ins-confirm[data-body="${x.body}"][data-insert="${key}"]`)?.checked);

function reasonHtml(sug) {
  if (!sug?.reason) return "";
  return `<details class="reason"><summary>why?</summary>${(sug.steps || [sug.reason]).map((t) => `<p>${esc(t)}</p>`).join("")}</details>`;
}

function renderTree() {
  const defs = manifest.defs;
  const look = Object.values(defs).filter((d) => d.looks_like?.length);
  $("lookalikes").hidden = !look.length;
  $("lookalikes").textContent = look.length ? "Look-alike parts (same volume, area and size, different name): " +
    look.map((d) => `${d.name} ≈ ${d.looks_like.join(", ")}`).join(" · ") +
    ". They are kept separate; untick one and use the other with its quantity if they are really the same part." : "";
  const ins = manifest.inserts || [];
  $("insertsFound").hidden = !ins.length;
  $("insertsFound").innerHTML = ins.length ? "<b>Possible moulded-in inserts found:</b> " +
    ins.map((x) => `${esc(x.insert_name)} × ${x.quantity} in ${esc(x.body_name)} (${fmt(x.covered_share * 100, 0)} % of its surface covered)`).join(" · ") +
    ". Please confirm each one under its body. A confirmed insert is linked to the body (process insert moulding) instead of becoming a BOM child." : "";
  $("previewTitle").textContent = `Parts found in ${manifest.file_name}`;
  $("tree").innerHTML = `<thead><tr><th>Register</th><th></th><th>Name</th><th>Part code</th><th class="num">Qty</th><th class="num">Total</th>
    <th>Process</th><th>Material</th><th>Sourcing</th><th class="num">Volume (cm³)</th><th class="num">Size (mm)</th></tr></thead><tbody>` +
    rowsInOrder().map(({ key, depth, qty, repeat }) => {
      const d = defs[key], m = d.metrics || {};
      if (repeat) return `<tr class="skipped"><td></td><td></td><td style="padding-left:${10 + depth * 18}px">↳ ${esc(d.name)} (again)</td>
        <td colspan="8" class="note">same part as above, quantity ${qty} here</td></tr>`;
      const sug = d.suggestion?.process;
      const only = d.only_moulded_part;
      const tick = !only;
      let html = `<tr data-key="${key}" class="${tick ? "" : "skipped"}"><td><input type="checkbox" class="reg" ${tick ? "checked" : ""} aria-label="Register" /></td>
        <td><img class="thumb" src="/api/import/${manifest.token}/thumb/${key}" alt="" /></td>
        <td class="input" style="padding-left:${10 + depth * 18}px"><input name="name" value="${esc(d.name)}" aria-label="Name" />
          ${d.is_assembly ? '<span class="badge assy">assembly</span>' : ""}${d.looks_like?.length ? ' <span class="badge suggested" title="Looks like ' + esc(d.looks_like.join(", ")) + '">look-alike</span>' : ""}
          ${d.insert_of ? `<span class="badge insert">insert of ${esc(d.insert_of.join(", "))}</span>` : ""}
          ${only ? `<p class="note">Holds only ${esc(defs[only].name)} and its inserts, so it is one moulded part: not registered as an assembly (tick to keep it).</p>` : ""}</td>
        <td class="input"><input class="code" name="part_code" placeholder="auto" aria-label="Part code" /></td>
        <td class="calc num">${fmt(qty)}</td><td class="calc num">${fmt(d.total_quantity)}</td>
        <td class="input proc"><select name="process">${options(meta.processes, sug, "—")}</select>${sug && !d.is_assembly ? ' <span class="badge suggested">suggested</span>' : ""}
          <span class="why">${d.is_assembly ? "" : reasonHtml(d.suggestion)}</span></td>
        <td class="input"><select name="material">${materialOptions("")}</select></td>
        <td class="input"><select name="sourcing">${options(meta.sourcing, d.default_sourcing || meta.sourcing[0]?.code)}</select></td>
        <td class="calc num">${m.volume_cm3 != null ? fmt(m.volume_cm3, 2) : "—"}</td>
        <td class="calc num">${m.bbox_mm ? `${fmt(m.bbox_mm.length, 0)}×${fmt(m.bbox_mm.width, 0)}×${fmt(m.bbox_mm.height, 0)}` : "—"}</td></tr>`;
      if (insertsOf(key).length) {
        html += `<tr class="insert-row"><td></td><td></td><td colspan="9" style="padding-left:${28 + depth * 18}px">Moulded-in inserts of ${esc(d.name)}:
          ${insertsOf(key).map((x) => `<label class="check inline"><input type="checkbox" class="ins-confirm" data-body="${key}" data-insert="${x.insert}" checked />
            ${esc(x.insert_name)} × ${x.quantity} <span class="note">(${fmt(x.covered_share * 100, 0)} % of its surface covered${x.overlap_mm3 ? `, ${fmt(x.overlap_mm3, 0)} mm³ modelled inside the body is removed from the body volume` : ""})</span></label>`).join(" ")}</td></tr>`;
      }
      return html;
    }).join("") + "</tbody>";
  $("preview").hidden = false;
  status($("commitStatus"), "");
}

// Ask the server again (material first, then geometry and inserts) when the material or the inserts change.
async function resuggest(tr) {
  const key = tr.dataset.key, d = manifest.defs[key];
  if (d.is_assembly) return;
  const sel = tr.querySelector("[name=process]");
  let sug;
  if (isConfirmedInsert(key) && !tr.querySelector("[name=material]").value) {
    sug = d.insert_of ? d.suggestion : null;
  } else {
    const count = confirmedInserts(key).reduce((n, x) => n + x.quantity, 0);
    sug = await api("/api/suggest-process", { method: "POST",
      body: JSON.stringify({ metrics: d.metrics, material: tr.querySelector("[name=material]").value, insert_count: count }) });
  }
  if (!sug) return;
  if (!sel.dataset.manual && sug.process) sel.value = sug.process;
  tr.querySelector(".why").innerHTML = reasonHtml(sug);
}

$("tree").addEventListener("change", (e) => {
  const tr = e.target.closest("tr");
  if (e.target.classList.contains("reg")) tr.classList.toggle("skipped", !e.target.checked);
  if (e.target.name === "process") e.target.dataset.manual = "1";
  if (e.target.name === "material") resuggest(tr);
  if (e.target.classList.contains("ins-confirm")) {
    resuggest(document.querySelector(`#tree tr[data-key="${e.target.dataset.body}"]`));
    const insRow = document.querySelector(`#tree tr[data-key="${e.target.dataset.insert}"]`);
    if (insRow && !e.target.checked) {
      insRow.querySelector(".badge.insert")?.remove();
      manifest.defs[e.target.dataset.insert].insert_of = null;
      resuggest(insRow);
    }
  }
});

// ---------- STEP: commit ----------
$("commitForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!manifest) return;
  const items = {};
  document.querySelectorAll("#tree tr[data-key]").forEach((tr) => {
    const get = (n) => tr.querySelector(`[name="${n}"]`).value.trim();
    items[tr.dataset.key] = { register: tr.querySelector(".reg").checked, name: get("name"), part_code: get("part_code"),
      process: get("process"), material: get("material"), sourcing: get("sourcing"),
      inserts: confirmedInserts(tr.dataset.key).map((x) => x.insert) };
  });
  const f = new FormData(e.target);
  const body = { project_id: Number($("project").value), variant_id: $("variant").value ? Number($("variant").value) : null,
    rev: f.get("rev"), change_note: f.get("change_note"), items };
  status($("commitStatus"), "Registering…");
  try {
    const r = await api(`/api/import/${manifest.token}/commit`, { method: "POST", body: JSON.stringify(body) });
    status($("commitStatus"), `Done: ${r.created} new parts, ${r.new_revisions} new revisions, ${r.unchanged} unchanged (already up to date)` +
      (r.inserts_linked ? `, ${r.inserts_linked} insert link${r.inserts_linked === 1 ? "" : "s"}.` : "."), "ok");
    $("commitStatus").insertAdjacentHTML("beforeend", ` <a class="link" href="/parts?project=${body.project_id}">Open the parts →</a>`);
    manifest = null;
    $("tree").querySelectorAll("input, select").forEach((x) => (x.disabled = true));
  } catch (err) {
    status($("commitStatus"), err.message, "error");
  }
});

// ---------- Excel bulk ----------
$("excelForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  form.append("project_id", $("project").value);
  status($("excelStatus"), "Checking every row and reading the STEP files…");
  $("excelReportWrap").hidden = true;
  try {
    const r = await api("/api/import/excel", { method: "POST", body: form });
    status($("excelStatus"), `Saved: ${r.created} new parts, ${r.new_revisions} new revisions, ${r.file_missing} with file missing` +
      (r.inserts_linked ? `, ${r.inserts_linked} insert links.` : "."), "ok");
    $("excelReport").innerHTML = `<thead><tr><th class="num">Excel row</th><th>Part code</th><th>Result</th><th>File</th><th>Process</th></tr></thead><tbody>` +
      r.rows.map((x) => `<tr><td class="calc num">${x.row}</td><td><b>${esc(x.part_code)}</b></td><td>${esc(x.result)}</td>
        <td>${x.file === "File missing" ? '<span class="badge missing">File missing</span>' : esc(x.file)}</td>
        <td>${x.process ? esc(procName(x.process)) : "—"}${x.process && x.process_reason ? ' <span class="badge suggested">suggested</span>' : ""}${x.process_reason ? reasonHtml({ reason: x.process_reason, steps: x.process_steps }) : ""}</td></tr>`).join("") + "</tbody>";
    $("excelReportWrap").hidden = false;
  } catch (err) {
    status($("excelStatus"), err.message, "error");
  }
});

init();
