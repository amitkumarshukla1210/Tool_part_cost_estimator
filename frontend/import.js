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

function renderTree() {
  const defs = manifest.defs;
  const look = Object.values(defs).filter((d) => d.looks_like?.length);
  $("lookalikes").hidden = !look.length;
  $("lookalikes").textContent = look.length ? "Look-alike parts (same volume, area and size, different name): " +
    look.map((d) => `${d.name} ≈ ${d.looks_like.join(", ")}`).join(" · ") +
    ". They are kept separate; untick one and use the other with its quantity if they are really the same part." : "";
  $("previewTitle").textContent = `Parts found in ${manifest.file_name}`;
  const proc = (d) => d.is_assembly ? meta.processes.find((p) => p.is_assembly)?.code : d.suggestion?.process;
  $("tree").innerHTML = `<thead><tr><th>Register</th><th></th><th>Name</th><th>Part code</th><th class="num">Qty</th><th class="num">Total</th>
    <th>Process</th><th>Material</th><th>Sourcing</th><th class="num">Volume (cm³)</th><th class="num">Size (mm)</th></tr></thead><tbody>` +
    rowsInOrder().map(({ key, depth, qty, repeat }) => {
      const d = defs[key], m = d.metrics || {};
      if (repeat) return `<tr class="skipped"><td></td><td></td><td style="padding-left:${10 + depth * 18}px">↳ ${esc(d.name)} (again)</td>
        <td colspan="8" class="note">same part as above, quantity ${qty} here</td></tr>`;
      const sug = proc(d);
      return `<tr data-key="${key}"><td><input type="checkbox" class="reg" checked aria-label="Register" /></td>
        <td><img class="thumb" src="/api/import/${manifest.token}/thumb/${key}" alt="" /></td>
        <td class="input" style="padding-left:${10 + depth * 18}px"><input name="name" value="${esc(d.name)}" aria-label="Name" />
          ${d.is_assembly ? '<span class="badge assy">assembly</span>' : ""}${d.looks_like?.length ? ' <span class="badge suggested" title="Looks like ' + esc(d.looks_like.join(", ")) + '">look-alike</span>' : ""}</td>
        <td class="input"><input class="code" name="part_code" placeholder="auto" aria-label="Part code" /></td>
        <td class="calc num">${fmt(qty)}</td><td class="calc num">${fmt(d.total_quantity)}</td>
        <td class="input"><select name="process">${options(meta.processes, sug, "—")}</select>${sug && !d.is_assembly ? ' <span class="badge suggested">suggested</span>' : ""}</td>
        <td class="input"><select name="material">${options(meta.materials, "", "—")}</select></td>
        <td class="input"><select name="sourcing">${options(meta.sourcing, meta.sourcing[0]?.code)}</select></td>
        <td class="calc num">${m.volume_cm3 != null ? fmt(m.volume_cm3, 2) : "—"}</td>
        <td class="calc num">${m.bbox_mm ? `${fmt(m.bbox_mm.length, 0)}×${fmt(m.bbox_mm.width, 0)}×${fmt(m.bbox_mm.height, 0)}` : "—"}</td></tr>`;
    }).join("") + "</tbody>";
  $("preview").hidden = false;
  status($("commitStatus"), "");
}

$("tree").addEventListener("change", (e) => {
  if (e.target.classList.contains("reg")) e.target.closest("tr").classList.toggle("skipped", !e.target.checked);
});

// ---------- STEP: commit ----------
$("commitForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!manifest) return;
  const items = {};
  document.querySelectorAll("#tree tr[data-key]").forEach((tr) => {
    const get = (n) => tr.querySelector(`[name="${n}"]`).value.trim();
    items[tr.dataset.key] = { register: tr.querySelector(".reg").checked, name: get("name"), part_code: get("part_code"),
      process: get("process"), material: get("material"), sourcing: get("sourcing") };
  });
  const f = new FormData(e.target);
  const body = { project_id: Number($("project").value), variant_id: $("variant").value ? Number($("variant").value) : null,
    rev: f.get("rev"), change_note: f.get("change_note"), items };
  status($("commitStatus"), "Registering…");
  try {
    const r = await api(`/api/import/${manifest.token}/commit`, { method: "POST", body: JSON.stringify(body) });
    status($("commitStatus"), `Done: ${r.created} new parts, ${r.new_revisions} new revisions, ${r.unchanged} unchanged (already up to date).`, "ok");
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
    status($("excelStatus"), `Saved: ${r.created} new parts, ${r.new_revisions} new revisions, ${r.file_missing} with file missing.`, "ok");
    $("excelReport").innerHTML = `<thead><tr><th class="num">Excel row</th><th>Part code</th><th>Result</th><th>File</th></tr></thead><tbody>` +
      r.rows.map((x) => `<tr><td class="calc num">${x.row}</td><td><b>${esc(x.part_code)}</b></td><td>${esc(x.result)}</td>
        <td>${x.file === "File missing" ? '<span class="badge missing">File missing</span>' : esc(x.file)}</td></tr>`).join("") + "</tbody>";
    $("excelReportWrap").hidden = false;
  } catch (err) {
    status($("excelStatus"), err.message, "error");
  }
});

init();
