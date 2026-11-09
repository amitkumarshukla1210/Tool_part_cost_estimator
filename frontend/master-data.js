// Master data editor for both data sets:
//   general - master_data/master_data.xlsx (rates, defaults, materials, machines)
//   mould   - master_data/mould_db.sqlite (mould bases, steels, BOM rules, rates)

const $ = (id) => document.getElementById(id);
const PART_TYPES = ["plastic", "die_casting", "foundry", "sheet_metal"];

const DATASETS = {
  general: {
    api: "/api/master-data",
    file: "master_data/master_data.xlsx",
    intro:
      "Every default and rule used by Stages A–C, and the density of each material. Material RATES (per kg, and the scrap value) " +
      "are versioned, approved rates: set them on the Rates page (category material / material_scrap). Edit here and click Save, " +
      "or download the Excel file, change it in Excel and upload it again. New values apply to the next calculation.",
    tables: {
      Parameters: {
        title: "Parameters",
        columns: [
          { key: "part_type", label: "Part type", kind: "part_type_all" },
          { key: "parameter", label: "Parameter", kind: "text" },
          { key: "value", label: "Value", kind: "text" },
          { key: "unit", label: "Unit", kind: "text" },
          { key: "description", label: "Description", kind: "wide" },
        ],
      },
      Materials: {
        title: "Materials",
        columns: [
          { key: "part_type", label: "Part type", kind: "part_type" },
          { key: "material", label: "Material (grade)", kind: "text" },
          { key: "material_type", label: "Material type", kind: "text" },
          { key: "recommended", label: "Recommended grade of its type", kind: "yesno" },
          { key: "density_g_cm3", label: "Density (g/cm³)", kind: "number" },
          { key: "notes", label: "Notes", kind: "wide" },
          { key: "scrap_reuse_pct", label: "Scrap used again (%) · blank = Parameters", kind: "optnumber" },
          { key: "scrap_rate_pct_of_rm", label: "Scrap rate (% of RM rate) · blank = Parameters", kind: "optnumber" },
        ],
      },
    },
  },
  mould: {
    api: "/api/mould-db",
    file: "master_data/costing_db.sqlite",
    intro:
      "Data that sizes a mould or die and prices it: cavities + part size → insert size → standard mould base → BOM. " +
      "Tool processes say how each process is priced (machine hours = MHR + operators × labour rate, labour hours, or a rate " +
      "per unit); Process time parameters are the removal rates and set-up hours the BOM rules use. " +
      "Rows marked Example are placeholders. Replace them with your catalogue and supplier values; editing a row clears its " +
      "Example flag. Export to Excel and import it back to edit in bulk.",
    schemaApi: "/api/mould-db/schema",
    tables: null, // loaded from the schema
  },
  setup: {
    api: "/api/costing-setup",
    file: "master_data/costing_db.sqlite",
    intro:
      "The calculation logic of the rate engine: countries and currencies, machines (technical data; prices and consumables " +
      "are country rates in the Rate library), labour grades, every MHR and labour-rate step as a formula, and where each " +
      "formula variable comes from (MHR, labour rate, RM cost and tool cost: scopes tool_clamp and tool). Change a formula " +
      "here and every result changes with it. Saves are checked first.",
    schemaApi: "/api/costing-setup/schema",
    tables: null,
  },
  register: {
    api: "/api/register-setup",
    file: "master_data/costing_db.sqlite",
    intro:
      "Lists and settings of the part register: processes (the material family decides first, then the rule that scores the 3D " +
      "geometry), the design-loop statuses, sourcing types, insert materials and shapes, the insert-moulding rules used by the " +
      "mould, simulation and costing stages, the part-code pattern, insert detection settings and the folder where CAD files are stored.",
    schemaApi: "/api/register-setup/schema",
    tables: null,
  },
};

let ds = "general";
let sheet = null;
let saved = null; // last data from the server
let data = null; // working copy
let savedById = {};
let nextId = 1;
let badRow = null; // { sheet, index } from the last failed save
let formulaVars = {};
// stage 53: unique code of every row and the live Price master price of priced rows (never stored in the tables)
let codeById = {};
let priceById = {};
let pricedSheets = {};
const PRICE_GROUP = { material: "part_material", tool_material: "tool_material" };

const clone = (o) => JSON.parse(JSON.stringify(o));
const display = (v) => (Array.isArray(v) ? v.join(", ") : v ?? "");
const conf = () => DATASETS[ds];
const cols = () => conf().tables[sheet].columns;
const hasExample = () => cols().some((c) => c.key === "is_example");

async function loadSchema() {
  const d = conf();
  if (!d.schemaApi || d.tables) return;
  const s = await (await fetch(d.schemaApi)).json();
  d.tables = Object.fromEntries(Object.entries(s.tables).map(([key, t]) => [key, { title: t.title, columns: t.columns }]));
  d.formulaVars = s.formula_variables || null;
}

// Formula help: fixed mould variables, or this data set's own formula inputs and steps.
function renderHelp() {
  let vars = conf().formulaVars;
  if (!vars && data?.formula_inputs) {
    vars = {};
    const FROM = { machine: "machine field ", parameter: "Parameters row ", part: "part value ", tool: "tool engine value " };
    for (const r of data.formula_inputs) vars[`${r.variable} (${r.scope})`] = `${r.label}: ${FROM[r.source] ? FROM[r.source] + r.item : "rate " + r.category + " / " + r.item}`;
    for (const r of data.cost_formulas || []) vars[`${r.name} (${r.scope})`] = `${r.label}: result of another formula`;
  }
  $("variables").innerHTML = Object.entries(vars || {}).map(([k, v]) => `<dt><code>${escapeHtml(k)}</code></dt><dd>${escapeHtml(v)}</dd>`).join("");
}

async function switchDataset(name) {
  if (data && anyChanges() && !confirm("You have unsaved changes. Switch and discard them?")) return;
  ds = name;
  document.querySelectorAll(".datasets button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.dataset === ds)));
  $("intro").textContent = conf().intro;
  $("download").href = `${conf().api}/download`;
  data = null;
  setStatus("Loading…");
  try {
    await loadSchema();
    const res = await fetch(conf().api);
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail);
    const want = new URLSearchParams(location.search).get("sheet");
    sheet = name === startSet && conf().tables[want] ? want : Object.keys(conf().tables)[0];
    $("tabs").innerHTML = Object.entries(conf().tables)
      .map(([key, t]) => `<button role="tab" class="btn btn-outline" data-sheet="${key}" aria-selected="${key === sheet}">${t.title}</button>`)
      .join("");
    setData(body);
    setStatus("");
    loadCodes();
  } catch (err) {
    setStatus(`Could not load: ${err.message}`, "error");
  }
}

async function loadCodes() {
  try {
    const q = new URLSearchParams({ country: $("priceCountry").value || "IN", month: $("priceMonth").value || "" });
    const res = await fetch(`/api/master-codes/${ds}?${q}`);
    if (!res.ok) return;
    const c = await res.json();
    if (!$("priceMonth").value) $("priceMonth").value = c.month;
    codeById = {};
    priceById = {};
    pricedSheets = c.priced || {};
    for (const [s, rows] of Object.entries(saved || {})) {
      rows.forEach((row, i) => {
        if (c.codes[s]) codeById[row._id] = c.codes[s][i];
        if (c.prices[s]) priceById[row._id] = c.prices[s][i];
      });
    }
    render();
  } catch { /* codes are extra information: the editor works without them */ }
}

async function loadCountries() {
  try {
    const m = await (await fetch("/api/price-master/meta")).json();
    $("priceCountry").innerHTML = m.countries.map((c) =>
      `<option value="${escapeHtml(c.code)}" ${c.code === m.base ? "selected" : ""}>${escapeHtml(c.name)} (${escapeHtml(c.currency)})</option>`).join("");
  } catch { $("priceCountry").innerHTML = '<option value="IN">India</option>'; }
}

function priceCell(row) {
  const p = priceById[row._id];
  const cat = pricedSheets[sheet];
  if (!(row._id in priceById)) return `<td class="calc note">save first</td>`;
  const code = codeById[row._id] || "";
  const group = PRICE_GROUP[cat];
  const href = group ? `/master-data/prices?group=${group}&country=${encodeURIComponent($("priceCountry").value)}&code=${encodeURIComponent(code)}` : "/rates";
  if (!p) return `<td class="calc"><span class="note">no approved price</span> <a class="link" href="${href}">set it</a></td>`;
  return `<td class="calc num" title="${escapeHtml(p.source || "")}">${escapeHtml(String(p.value))} <span class="note">${escapeHtml(p.unit || "")}</span>` +
    `<br><span class="note">${escapeHtml(p.month)} · ${p.is_example ? "EXAMPLE" : escapeHtml(p.status)}</span> <a class="link" href="${href}">edit</a></td>`;
}

function setData(body) {
  savedById = {};
  for (const rows of Object.values(body)) {
    for (const row of rows) {
      row._id = nextId++;
      savedById[row._id] = JSON.stringify(row);
    }
  }
  saved = body;
  data = clone(body);
  badRow = null;
  renderHelp();
  render();
}

const isChanged = (s, i) => savedById[data[s][i]._id] !== JSON.stringify(data[s][i]);
const anyChanges = () => JSON.stringify(data) !== JSON.stringify(saved);
const withoutIds = () =>
  Object.fromEntries(Object.entries(data).map(([s, rows]) => [s, rows.map(({ _id, ...row }) => row)]));

function options(values, current, blank = false) {
  const list = (blank ? [""] : []).concat(values);
  if (current && !list.includes(current)) list.push(current); // keep unknown values visible
  return list.map((v) => `<option value="${escapeHtml(v)}" ${v === current ? "selected" : ""}>${escapeHtml(v || "—")}</option>`).join("");
}

function cell(col, row, i) {
  const v = row[col.key];
  // The row's name column (second column) gets room for long names.
  if (col === cols()[1] && col.kind === "text") {
    return `<input type="text" class="name" data-i="${i}" data-k="${col.key}" value="${escapeHtml(display(v))}" />`;
  }
  const attrs = `data-i="${i}" data-k="${col.key}"`;
  if (col.choices) return `<select ${attrs}>${options(col.choices.filter(Boolean), v, col.choices.includes(""))}</select>`;
  switch (col.kind) {
    case "part_type":
    case "part_type_all":
      return `<select ${attrs}>${options(col.kind === "part_type_all" ? ["all", ...PART_TYPES] : PART_TYPES, v)}</select>`;
    case "material":
      return `<select ${attrs}>${options(data.tool_materials.map((m) => m.code), v, true)}</select>`;
    case "yesno":
      return `<select ${attrs}>${options(["", "yes"], v)}</select>`;
    case "category":
      return `<select ${attrs}>${options(["made", "bought_out", "process"], v)}</select>`;
    case "process":
      return `<select ${attrs}>${options(data.tool_processes.filter((p) => p.cost_group !== "trial").map((p) => p.code), v, true)}</select>`;
    case "bool":
      return `<label class="flag"><input type="checkbox" ${attrs} ${v ? "checked" : ""} />${v ? (col.key === "is_example" ? "Example" : "Yes") : ""}</label>`;
    case "number":
    case "optnumber":                         // a number that may stay blank (blank = take the default)
      return `<input type="number" step="any" ${attrs} value="${escapeHtml(display(v))}" />`;
    case "formula":
      return `<input type="text" class="formula" spellcheck="false" ${attrs} value="${escapeHtml(display(v))}" />`;
    default:
      return `<input type="text" ${col.kind === "wide" || col.key === "notes" || col.key === "description" ? 'class="wide"' : ""} ${attrs} value="${escapeHtml(display(v))}" />`;
  }
}

function render() {
  if (!data) return;
  const columns = cols();
  const filter = $("filter").value;
  const query = $("search").value.trim().toLowerCase();
  const examplesOnly = $("examplesOnly").checked && hasExample();
  const hasPartType = columns.some((c) => c.key === "part_type");

  const visible = data[sheet]
    .map((row, i) => ({ row, i }))
    .filter(({ row }) => !filter || !hasPartType || row.part_type === filter)
    .filter(({ row }) => !examplesOnly || row.is_example)
    .filter(({ row }) => !query || `${codeById[row._id] || ""} ${Object.values(row).join(" ")}`.toLowerCase().includes(query));

  const priced = sheet in pricedSheets;
  $("priceBox").hidden = !priced;
  const head = `<thead><tr><th>Row</th><th>Code</th>${columns.map((c) => `<th>${c.label}</th>`).join("")}` +
    `${priced ? `<th>Price · ${escapeHtml($("priceCountry").value)} ${escapeHtml($("priceMonth").value)}<br><span class="note">live from Price master / Rates</span></th>` : ""}<th></th></tr></thead>`;
  const body = visible
    .map(({ row, i }) => {
      const cls = [
        badRow && badRow.sheet === sheet && badRow.index === i ? "bad" : isChanged(sheet, i) ? "changed" : "",
        row.is_example ? "example" : "",
      ].join(" ");
      // Excel row number = position + 1 for the header row.
      // Yellow = cell you type into, grey = row number (theme costing-table style).
      return `<tr class="${cls}"><td class="calc rownum">${i + 2}</td><td class="calc"><code class="item-code">${escapeHtml(codeById[row._id] || "new")}</code></td>` +
        `${columns.map((c) => `<td class="input">${cell(c, row, i)}</td>`).join("")}${priced ? priceCell(row) : ""}` +
        `<td><button class="del" data-del="${i}" title="Delete row">✕</button></td></tr>`;
    })
    .join("");
  $("table").innerHTML =
    head + `<tbody>${body || `<tr><td class="empty" colspan="${columns.length + 4}">No rows match.</td></tr>`}</tbody>`;

  document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.sheet === sheet)));
  $("formulaHelp").hidden = !columns.some((c) => c.kind === "formula");
  $("filter").disabled = !hasPartType;
  $("examplesOnly").disabled = !hasExample();
  const examples = hasExample() ? data[sheet].filter((r) => r.is_example).length : 0;
  $("counts").textContent =
    `${visible.length} of ${data[sheet].length} rows` + (hasExample() ? ` · ${examples} still example values` : "");
  $("save").disabled = !anyChanges();
  $("revert").disabled = !anyChanges();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function setStatus(msg, kind = "") {
  $("status").textContent = msg;
  $("status").className = `status ${kind}`;
}

// ---------- editing ----------
function edited(e) {
  const { i, k } = e.target.dataset;
  if (i === undefined) return;
  const row = data[sheet][i];
  const kind = cols().find((c) => c.key === k).kind;
  const v = e.target.value;
  if (kind === "bool") row[k] = e.target.checked;
  else row[k] = (kind === "number" || kind === "optnumber") && v !== "" ? Number(v) : v;
  // A row you have changed is no longer a placeholder (tick it again if it still is).
  if (k !== "is_example" && "is_example" in row && row.is_example) {
    row.is_example = false;
    render();
    return;
  }
  if (e.target.tagName === "SELECT" || kind === "bool") return render();
  e.target.closest("tr").classList.toggle("changed", isChanged(sheet, Number(i)));
  $("save").disabled = !anyChanges();
  $("revert").disabled = !anyChanges();
}
$("table").addEventListener("input", (e) => e.target.type !== "checkbox" && e.target.tagName !== "SELECT" && edited(e));
$("table").addEventListener("change", (e) => (e.target.type === "checkbox" || e.target.tagName === "SELECT") && edited(e));

$("table").addEventListener("click", (e) => {
  const i = e.target.dataset.del;
  if (i === undefined) return;
  const row = data[sheet][i];
  const name = row[cols()[1].key] || "this row";
  if (!confirm(`Delete "${name}"? It is removed from the file when you click Save.`)) return;
  data[sheet].splice(Number(i), 1);
  render();
});

$("addRow").addEventListener("click", () => {
  const row = Object.fromEntries(cols().map((c) => [c.key, c.kind === "number" ? 0 : c.kind === "bool" ? false : ""]));
  const f = $("filter").value;
  if ("part_type" in row) {
    const all = cols()[0].kind === "part_type_all";
    row.part_type = f && (f !== "all" || all) ? f : all ? "all" : "plastic";
  }
  for (const c of cols()) if (c.kind === "formula") row[c.key] = "0";
  row._id = nextId++;
  data[sheet].push(row);
  $("search").value = "";
  $("examplesOnly").checked = false;
  render();
  const inputs = $("table").querySelectorAll(`[data-i="${data[sheet].length - 1}"]`);
  inputs[1]?.focus();
  inputs[1]?.scrollIntoView({ block: "center" });
});

document.querySelectorAll(".datasets button").forEach((b) => b.addEventListener("click", () => switchDataset(b.dataset.dataset)));
$("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  sheet = b.dataset.sheet;
  render();
});
$("filter").addEventListener("change", render);
$("search").addEventListener("input", render);
$("examplesOnly").addEventListener("change", render);

// ---------- save / undo / upload / download ----------
$("save").addEventListener("click", async () => {
  $("save").disabled = true;
  setStatus("Saving…");
  try {
    const res = await fetch(conf().api, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(withoutIds()),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(errorText(body.detail));
    setData(body);
    loadCodes();
    setStatus(`Saved to ${conf().file}. New values apply to the next calculation.`, "ok");
  } catch (err) {
    showError(err.message);
    $("save").disabled = false;
  }
});

$("revert").addEventListener("click", () => {
  data = clone(saved);
  badRow = null;
  render();
  setStatus("Changes undone.");
});

$("upload").addEventListener("change", async () => {
  const file = $("upload").files[0];
  if (!file) return;
  if (anyChanges() && !confirm("Uploading replaces the data and discards your unsaved edits. Continue?")) {
    $("upload").value = "";
    return;
  }
  const form = new FormData();
  form.append("file", file);
  setStatus("Checking and uploading…");
  try {
    const res = await fetch(`${conf().api}/upload`, { method: "POST", body: form });
    const body = await res.json();
    if (!res.ok) throw new Error(errorText(body.detail));
    const notes = body._notes || [];
    delete body._notes;
    setData(body);
    loadCodes();
    setStatus(`${file.name} imported and saved to ${conf().file}.${notes.length ? " Note: " + notes.join(" ") : ""}`, "ok");
  } catch (err) {
    setStatus(`Upload rejected, nothing was changed: ${err.message}`, "error");
  } finally {
    $("upload").value = "";
  }
});

$("download").addEventListener("click", (e) => {
  if (anyChanges() && !confirm("You have unsaved edits. The download contains the last saved version. Continue?")) {
    e.preventDefault();
  }
});

window.addEventListener("beforeunload", (e) => {
  if (data && anyChanges()) e.preventDefault();
});

function errorText(detail) {
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  return detail || "Request failed";
}

function showError(msg) {
  // Messages name the sheet and Excel row, e.g. "BOM elements row 12, quantity_rule: ..."
  const entry = Object.entries(conf().tables).find(([, t]) => msg.startsWith(`${t.title} row `));
  const m = entry && msg.match(/ row (\d+)/);
  badRow = m ? { sheet: entry[0], index: Number(m[1]) - 2 } : null;
  if (badRow) {
    sheet = badRow.sheet;
    $("filter").value = "";
    $("search").value = "";
    $("examplesOnly").checked = false;
  }
  render();
  $("table").querySelector("tr.bad")?.scrollIntoView({ block: "center" });
  setStatus(`Not saved: ${msg}`, "error");
}

const startSet = new URLSearchParams(location.search).get("set");
// Links from the Replace example values checklist open a sheet with "Examples only" ticked.
$("examplesOnly").checked = new URLSearchParams(location.search).has("examples");
$("priceCountry").addEventListener("change", loadCodes);
$("priceMonth").addEventListener("change", loadCodes);
loadCountries().then(() => switchDataset(DATASETS[startSet] ? startSet : "general"));
