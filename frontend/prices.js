// Price master: month-wise prices of tool materials, standard parts and part materials per country (roadmap stage 20).
const { $, esc, fmt, api, status } = window.DTC;
let meta = null;
let grid = null;
let group = "tool_material";

const COLS = {
  tool_material: ["Type", "Grade", "Used for"],
  standard_part: ["BOM element", "Make", "Catalogue"],
  part_material: ["Type", "Grade", "Part type"],
  part_scrap: ["Type", "Grade", "Part type"],
};

async function init() {
  meta = await api("/api/price-master/meta");
  $("groups").innerHTML = Object.entries(meta.groups).map(([k, title]) =>
    `<button role="tab" class="btn btn-outline" data-group="${k}" aria-selected="${k === group}">${esc(title)}</button>`).join("");
  $("country").innerHTML = meta.countries.map((c) =>
    `<option value="${esc(c.code)}" ${c.code === meta.base ? "selected" : ""}>${esc(c.name)} (${esc(c.currency)})</option>`).join("");
  const s = await api("/api/settings");
  $("approverBox").hidden = !!s.approver_name;
  addForm();
  await load();
}

async function load() {
  status($("status"), "Loading…");
  try {
    grid = await api(`/api/price-master/grid?group=${group}&country=${$("country").value}&months=${$("months").value}`);
  } catch (err) {
    return status($("status"), err.message, "error");
  }
  status($("status"), "");
  const types = [...new Set(grid.rows.map((r) => r.type).filter(Boolean))].sort();
  const keep = $("type").value;
  $("type").innerHTML = '<option value="">All types</option>' + types.map((t) => `<option ${t === keep ? "selected" : ""}>${esc(t)}</option>`).join("");
  $("download").href = `/api/price-master/export.xlsx?group=${group}&country=${grid.country}&months=${$("months").value}`;
  render();
}

function render() {
  const q = $("q").value.trim().toLowerCase();
  const type = $("type").value;
  const rows = grid.rows.filter((r) => (!type || r.type === type) &&
    (!q || `${r.type} ${r.grade} ${r.info} ${r.item}`.toLowerCase().includes(q)));
  const [c1, c2, c3] = COLS[group];
  const cur = grid.current_month;
  const head = `<thead><tr><th class="sticky0">${c1}</th><th class="sticky1">${c2}</th><th>${c3}</th>` +
    grid.months.map((m) => `<th class="num ${m === cur ? "now" : ""}">${m}${m > cur ? "<br><span class=\"note\">next</span>" : ""}</th>`).join("") +
    "</tr></thead>";
  const body = rows.map((r) => {
    const cells = grid.months.map((m) => {
      const c = r.cells[m];
      const cls = ["price", c?.starts ? "starts" : c ? "carried" : "", c?.is_example ? "example" : "", m === cur ? "now" : ""].join(" ");
      const title = c ? `${c.source || ""}${c.draft != null ? ` · open draft ${c.draft}` : ""}` : "no price yet";
      return `<td class="${cls}" title="${esc(title)}"><input type="number" min="0" step="any" data-item="${esc(r.item)}" data-month="${m}"
        value="${c?.value ?? ""}" placeholder="—" />${c?.draft != null ? '<b class="draft" title="open draft">D</b>' : ""}</td>`;
    }).join("");
    return `<tr class="${r.orphan ? "orphan" : ""}"><td class="sticky0">${esc(r.type)}</td>
      <td class="sticky1"><b>${r.recommended ? "★ " : ""}${esc(r.grade)}</b>${r.is_example ? '<span class="example-mark" title="Example row">•</span>' : ""}</td>
      <td class="note">${[r.info, r.origin, r.density ? `${fmt(r.density, 3)} g/cm³` : "", r.hardness].filter(Boolean).map(esc).join(" · ")}</td>${cells}</tr>`;
  }).join("");
  $("grid").innerHTML = head + `<tbody>${body || `<tr><td class="empty" colspan="${grid.months.length + 3}">Nothing matches.</td></tr>`}</tbody>`;
  $("grid").insertAdjacentHTML("beforeend", `<caption class="note">${esc(grid.title)} · ${esc(grid.unit)} · ${rows.length} items</caption>`);
}

// A typed price: a new version from that month on (approved, or a draft for the Rate review).
$("grid").addEventListener("change", async (e) => {
  const inp = e.target.closest("input[data-item]");
  if (!inp || inp.value === "") return;
  status($("status"), "Saving…");
  try {
    await api("/api/price-master/price", { method: "POST", body: JSON.stringify({
      group, item: inp.dataset.item, country: grid.country, month: inp.dataset.month, value: Number(inp.value),
      approve: $("approve").checked }) });
    await load();
    status($("status"), `${inp.dataset.item} ${inp.dataset.month}: saved${$("approve").checked ? " and approved" : " as a draft (Rates → Rate review)"}.`, "ok");
  } catch (err) {
    status($("status"), err.message, "error");
  }
});

$("groups").addEventListener("click", (e) => {
  const b = e.target.closest("[data-group]");
  if (!b) return;
  group = b.dataset.group;
  for (const x of $("groups").children) x.setAttribute("aria-selected", x === b);
  $("type").value = "";
  addForm();
  load();
});
for (const id of ["country", "months"]) $(id).addEventListener("change", load);
for (const id of ["type", "q"]) $(id).addEventListener("input", render);

$("upload").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("group", group);
  form.append("country", grid.country);
  form.append("approve", $("approve").checked);
  form.append("file", file);
  status($("status"), "Uploading…");
  try {
    const res = await api("/api/price-master/upload", { method: "POST", body: form });
    await load();
    status($("status"), `${res.versions_created} new price version(s) saved (${res.status}).`, "ok");
  } catch (err) {
    status($("status"), err.message, "error");
  }
  e.target.value = "";
});

$("approverSave").addEventListener("click", async () => {
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ approver_name: $("approverName").value }) });
    $("approverBox").hidden = true;
  } catch (err) {
    status($("status"), err.message, "error");
  }
});

// ---------- add a new grade / make ----------
function addForm() {
  const list = (id, values) => `<datalist id="${id}">${values.map((v) => `<option value="${esc(v)}">`).join("")}</datalist>`;
  const month = `<label>From month <input name="month" type="month" value="${meta.month}" /></label>`;
  const price = (label) => `<label>${label} <input name="price" type="number" min="0" step="any" required /></label>`;
  const forms = {
    tool_material: ["+ Add a new tool material grade", `
      <label>Grade <input name="code" required placeholder="e.g. 1.2738 HH, NAK80, Beryllium copper C17200" /></label>
      <label>Material type <input name="material_type" list="tmTypes" placeholder="e.g. Pre-hardened mould steel" /></label>
      <label>Used for <input name="application" list="tmApps" placeholder="core_cavity" /></label>
      <label>Density (g/cm³) <input name="density" type="number" min="0" step="any" required /></label>
      <label>Hardness <input name="hardness" placeholder="e.g. 30-36 HRC" /></label>
      ${price("Price per kg (country currency)")}${month}
      ${list("tmTypes", meta.tool_material_types)}${list("tmApps", meta.applications)}`],
    standard_part: ["+ Add a make to a standard part", `
      <label>BOM element <select name="element" required>${meta.elements.map((x) => `<option>${esc(x)}</option>`).join("")}</select></label>
      <label>Make <input name="make" list="makes" required placeholder="e.g. HASCO, MISUMI, DME, Strack" /></label>
      <label>Home country of a new make <input name="origin_country" maxlength="3" placeholder="e.g. DE" /></label>
      <label>Catalogue reference <input name="catalogue_ref" /></label>
      ${price("Price each (country currency)")}${month}
      <p class="note span2">The size factor follows the element's other makes; change it in Master data → Standard parts.</p>
      ${list("makes", meta.makes)}`],
    part_material: ["+ Add a new part raw material grade", `
      <label>Part type <select name="part_type">${meta.part_types.map((x) => `<option>${esc(x)}</option>`).join("")}</select></label>
      <label>Grade <input name="material" required placeholder="e.g. PP GF30, CRCA D513 EDD" /></label>
      <label>Material type <input name="material_type" list="pmTypes" placeholder="e.g. Polypropylene (PP)" /></label>
      <label>Density (g/cm³) <input name="density" type="number" min="0" step="any" required /></label>
      ${price("Price per kg (country currency)")}
      <label>Scrap value per kg <input name="scrap_price" type="number" min="0" step="any" /></label>${month}
      ${list("pmTypes", meta.part_material_types)}`],
  };
  const f = forms[group === "part_scrap" ? "part_material" : group];
  $("addTitle").textContent = f[0];
  $("addForm").innerHTML = f[1] + `<div class="span2 dialog-actions"><button type="submit" class="btn btn-primary">Add with this price</button></div>`;
}

$("addForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = { group: group === "part_scrap" ? "part_material" : group, country: $("country").value, approve: $("approve").checked };
  for (const [k, v] of new FormData(e.target)) if (v !== "") data[k] = ["price", "scrap_price", "density"].includes(k) ? Number(v) : v;
  status($("addStatus"), "Saving…");
  try {
    const res = await api("/api/price-master/item", { method: "POST", body: JSON.stringify(data) });
    meta = await api("/api/price-master/meta");
    addForm();
    await load();
    status($("addStatus"), `${res.item} added with its price for ${grid.country}. It is now in the drop-downs of the tool / part cost.`, "ok");
  } catch (err) {
    status($("addStatus"), err.message, "error");
  }
});

init().catch((err) => status($("status"), err.message, "error"));
