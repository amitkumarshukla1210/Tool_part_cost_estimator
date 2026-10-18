// Master data editor: one table per sheet of master_data.xlsx.

const $ = (id) => document.getElementById(id);

const PART_TYPES = ["plastic", "die_casting", "foundry", "sheet_metal"];
const COLUMNS = {
  Parameters: [
    ["part_type", "Part type"],
    ["parameter", "Parameter"],
    ["value", "Value"],
    ["unit", "Unit"],
    ["description", "Description", "wide"],
  ],
  Materials: [
    ["part_type", "Part type"],
    ["material", "Material"],
    ["density_g_cm3", "Density (g/cm³)", "number"],
    ["rate_per_kg", "RM rate / kg", "number"],
    ["scrap_rate_per_kg", "Scrap value / kg", "number"],
    ["notes", "Notes", "wide"],
  ],
  Machines: [
    ["part_type", "Part type"],
    ["machine", "Machine"],
    ["tonnage_t", "Tonnage (t)", "number"],
    ["length_mm", "Tie-bar / bed length (mm)", "number"],
    ["width_mm", "Tie-bar / bed width (mm)", "number"],
    ["mhr_per_hour", "MHR / hour", "number"],
    ["notes", "Notes", "wide"],
  ],
};

let saved = null; // last data from the server
let data = null; // working copy being edited
let savedById = {}; // _id -> saved row, to mark edited rows
let nextId = 1;
let sheet = "Parameters";
let badRow = null; // { sheet, index } from the last failed save

const clone = (o) => JSON.parse(JSON.stringify(o));
const display = (v) => (Array.isArray(v) ? v.join(", ") : v ?? "");

async function load() {
  try {
    const res = await fetch("/api/master-data");
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail);
    setData(body);
    setStatus("");
  } catch (err) {
    setStatus(`Could not load master data: ${err.message}`, "error");
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

function render() {
  const cols = COLUMNS[sheet];
  const filter = $("filter").value;
  const query = $("search").value.trim().toLowerCase();
  const nameKey = cols[1][0];

  const head = `<thead><tr><th>Row</th>${cols.map(([, label]) => `<th>${label}</th>`).join("")}<th></th></tr></thead>`;
  const rows = data[sheet]
    .map((row, i) => ({ row, i }))
    .filter(({ row }) => !filter || row.part_type === filter)
    .filter(({ row }) => !query || `${row[nameKey]} ${row.description ?? ""} ${row.notes ?? ""}`.toLowerCase().includes(query));

  const body = rows
    .map(({ row, i }) => {
      const cls = badRow && badRow.sheet === sheet && badRow.index === i ? "bad" : isChanged(sheet, i) ? "changed" : "";
      const cells = cols
        .map(([key, , kind]) => {
          if (key === "part_type") {
            const types = sheet === "Parameters" ? ["all", ...PART_TYPES] : PART_TYPES;
            const opts = types.map((t) => `<option ${t === row.part_type ? "selected" : ""}>${t}</option>`).join("");
            return `<td><select data-i="${i}" data-k="${key}">${opts}</select></td>`;
          }
          const type = kind === "number" ? 'type="number" step="any"' : 'type="text"';
          const wide = kind === "wide" ? 'class="wide"' : "";
          return `<td><input ${type} ${wide} data-i="${i}" data-k="${key}" value="${escapeHtml(display(row[key]))}" /></td>`;
        })
        .join("");
      // Excel row = position in the sheet + 1 for the header row.
      return `<tr class="${cls}"><td class="rownum">${i + 2}</td>${cells}<td><button class="del" data-del="${i}" title="Delete row">✕</button></td></tr>`;
    })
    .join("");

  $("table").innerHTML =
    head + `<tbody>${body || `<tr><td class="empty" colspan="${cols.length + 2}">No rows match.</td></tr>`}</tbody>`;
  $("save").disabled = !anyChanges();
  $("revert").disabled = !anyChanges();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function setStatus(msg, kind = "") {
  $("status").textContent = msg;
  $("status").className = kind === "error" ? "error" : kind === "ok" ? "ok" : "";
}

// ---------- editing ----------
$("table").addEventListener("input", (e) => {
  const { i, k } = e.target.dataset;
  if (i === undefined) return;
  const v = e.target.value;
  data[sheet][i][k] = e.target.type === "number" && v !== "" ? Number(v) : v;
  const tr = e.target.closest("tr");
  tr.className = isChanged(sheet, Number(i)) ? "changed" : "";
  $("save").disabled = !anyChanges();
  $("revert").disabled = !anyChanges();
});
$("table").addEventListener("change", (e) => {
  if (e.target.tagName === "SELECT") render();
});
$("table").addEventListener("click", (e) => {
  const i = e.target.dataset.del;
  if (i === undefined) return;
  const row = data[sheet][i];
  const name = row[COLUMNS[sheet][1][0]] || "this row";
  if (!confirm(`Delete "${name}" (${row.part_type})? It is removed from the file when you click Save.`)) return;
  data[sheet].splice(Number(i), 1);
  render();
});

$("addRow").addEventListener("click", () => {
  const row = Object.fromEntries(COLUMNS[sheet].map(([k, , kind]) => [k, kind === "number" ? 0 : ""]));
  const f = $("filter").value;
  row.part_type = f && (f !== "all" || sheet === "Parameters") ? f : sheet === "Parameters" ? "all" : "plastic";
  row._id = nextId++;
  data[sheet].push(row);
  $("search").value = "";
  render();
  const inputs = $("table").querySelectorAll(`[data-i="${data[sheet].length - 1}"]`);
  inputs[1]?.focus();
  inputs[1]?.scrollIntoView({ block: "center" });
});

document.querySelectorAll(".tabs button").forEach((btn) =>
  btn.addEventListener("click", () => {
    sheet = btn.dataset.sheet;
    document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b === btn)));
    render();
  }),
);
$("filter").addEventListener("change", render);
$("search").addEventListener("input", render);

// ---------- save / undo / upload ----------
$("save").addEventListener("click", async () => {
  $("save").disabled = true;
  setStatus("Saving…");
  try {
    const res = await fetch("/api/master-data", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(withoutIds()),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(errorText(body.detail));
    setData(body);
    setStatus("Saved to master_data.xlsx. New values apply to the next calculation.", "ok");
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
  if (anyChanges() && !confirm("Uploading replaces the master data and discards your unsaved edits. Continue?")) {
    $("upload").value = "";
    return;
  }
  const form = new FormData();
  form.append("file", file);
  setStatus("Checking and uploading…");
  try {
    const res = await fetch("/api/master-data/upload", { method: "POST", body: form });
    const body = await res.json();
    if (!res.ok) throw new Error(errorText(body.detail));
    setData(body);
    setStatus(`${file.name} uploaded and saved as the master data.`, "ok");
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
  // Messages name the Excel row, e.g. "Parameters row 12, oee_pct: ..."
  const m = msg.match(/^(Parameters|Materials|Machines) row (\d+)/);
  badRow = m ? { sheet: m[1], index: Number(m[2]) - 2 } : null;
  if (badRow && badRow.sheet !== sheet) document.querySelector(`.tabs [data-sheet="${badRow.sheet}"]`).click();
  else render();
  if (badRow) {
    $("filter").value = "";
    $("search").value = "";
    render();
    $("table").querySelector("tr.bad")?.scrollIntoView({ block: "center" });
  }
  setStatus(`Not saved: ${msg}`, "error");
}

load();
