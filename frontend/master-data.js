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
      "Every rate, default and rule used by Stages A–C. Edit here and click Save, or download the Excel file, " +
      "change it in Excel and upload it again. New values apply to the next calculation.",
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
          { key: "material", label: "Material", kind: "text" },
          { key: "density_g_cm3", label: "Density (g/cm³)", kind: "number" },
          { key: "rate_per_kg", label: "RM rate / kg", kind: "number" },
          { key: "scrap_rate_per_kg", label: "Scrap value / kg", kind: "number" },
          { key: "notes", label: "Notes", kind: "wide" },
        ],
      },
      Machines: {
        title: "Machines",
        columns: [
          { key: "part_type", label: "Part type", kind: "part_type" },
          { key: "machine", label: "Machine", kind: "text" },
          { key: "tonnage_t", label: "Tonnage (t)", kind: "number" },
          { key: "length_mm", label: "Tie-bar / bed length (mm)", kind: "number" },
          { key: "width_mm", label: "Tie-bar / bed width (mm)", kind: "number" },
          { key: "mhr_per_hour", label: "MHR / hour", kind: "number" },
          { key: "notes", label: "Notes", kind: "wide" },
        ],
      },
    },
  },
  mould: {
    api: "/api/mould-db",
    file: "master_data/mould_db.sqlite",
    intro:
      "Data that sizes a mould or die and builds its BOM: cavities + part size → insert size → standard mould base → BOM. " +
      "Rows marked Example are placeholders. Replace them with your catalogue and supplier values; editing a row clears its " +
      "Example flag. Export to Excel and import it back to edit in bulk.",
    tables: null, // loaded from /api/mould-db/schema
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

const clone = (o) => JSON.parse(JSON.stringify(o));
const display = (v) => (Array.isArray(v) ? v.join(", ") : v ?? "");
const conf = () => DATASETS[ds];
const cols = () => conf().tables[sheet].columns;
const hasExample = () => cols().some((c) => c.key === "is_example");

async function loadSchema() {
  if (DATASETS.mould.tables) return;
  const s = await (await fetch("/api/mould-db/schema")).json();
  DATASETS.mould.tables = Object.fromEntries(
    Object.entries(s.tables).map(([key, t]) => [key, { title: t.title, columns: t.columns }]),
  );
  formulaVars = s.formula_variables;
  $("variables").innerHTML = Object.entries(formulaVars)
    .map(([k, v]) => `<dt><code>${k}</code></dt><dd>${v}</dd>`)
    .join("");
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
    if (ds === "mould") await loadSchema();
    const res = await fetch(conf().api);
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail);
    sheet = Object.keys(conf().tables)[0];
    $("tabs").innerHTML = Object.entries(conf().tables)
      .map(([key, t]) => `<button role="tab" data-sheet="${key}" aria-selected="${key === sheet}">${t.title}</button>`)
      .join("");
    setData(body);
    setStatus("");
  } catch (err) {
    setStatus(`Could not load: ${err.message}`, "error");
  }
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
  switch (col.kind) {
    case "part_type":
    case "part_type_all":
      return `<select ${attrs}>${options(col.kind === "part_type_all" ? ["all", ...PART_TYPES] : PART_TYPES, v)}</select>`;
    case "material":
      return `<select ${attrs}>${options(data.tool_materials.map((m) => m.code), v, true)}</select>`;
    case "category":
      return `<select ${attrs}>${options(["made", "bought_out", "process"], v)}</select>`;
    case "process":
      return `<select ${attrs}>${options(data.process_rates.map((p) => p.code), v, true)}</select>`;
    case "bool":
      return `<label class="flag"><input type="checkbox" ${attrs} ${v ? "checked" : ""} />${v ? "Example" : ""}</label>`;
    case "number":
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
    .filter(({ row }) => !query || Object.values(row).join(" ").toLowerCase().includes(query));

  const head = `<thead><tr><th>Row</th>${columns.map((c) => `<th>${c.label}</th>`).join("")}<th></th></tr></thead>`;
  const body = visible
    .map(({ row, i }) => {
      const cls = [
        badRow && badRow.sheet === sheet && badRow.index === i ? "bad" : isChanged(sheet, i) ? "changed" : "",
        row.is_example ? "example" : "",
      ].join(" ");
      // Excel row number = position + 1 for the header row.
      return `<tr class="${cls}"><td class="rownum">${i + 2}</td>${columns.map((c) => `<td>${cell(c, row, i)}</td>`).join("")}` +
        `<td><button class="del" data-del="${i}" title="Delete row">✕</button></td></tr>`;
    })
    .join("");
  $("table").innerHTML =
    head + `<tbody>${body || `<tr><td class="empty" colspan="${columns.length + 2}">No rows match.</td></tr>`}</tbody>`;

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
  $("status").className = kind;
}

// ---------- editing ----------
function edited(e) {
  const { i, k } = e.target.dataset;
  if (i === undefined) return;
  const row = data[sheet][i];
  const kind = cols().find((c) => c.key === k).kind;
  const v = e.target.value;
  if (kind === "bool") row[k] = e.target.checked;
  else row[k] = kind === "number" && v !== "" ? Number(v) : v;
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
    setData(body);
    setStatus(`${file.name} imported and saved to ${conf().file}.`, "ok");
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

switchDataset(new URLSearchParams(location.search).get("set") === "mould" ? "mould" : "general");
