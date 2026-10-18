// Rates page: machine & labour rates (traced), rate library, rate review.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const num = (v, d) => window.TracePanel.format(v, d);
const STATUS = { approved: "Approved", reviewed: "Reviewed", draft: "Draft", rejected: "Rejected" };
const badge = (s) => `<span class="badge badge-${esc(s)}">${STATUS[s] || esc(s)}</span>`;
const exampleTag = (on) => (on ? '<span class="badge badge-example">EXAMPLE</span>' : "");

let countries = [];
let mhrData = null;
let library = [];
let tab = "mhr";

async function api(url, opts = {}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await res.json();
  if (!res.ok) throw new Error(Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail);
  return body;
}

const country = () => $("country").value;
const month = () => $("month").value;

// ---------- approver name: asked once, then remembered ----------
async function ensureApprover() {
  const s = await api("/api/settings");
  if (s.approver_name) return true;
  const name = prompt("Your name for approvals (asked once, change it under Rate review):");
  if (!name || !name.trim()) return false;
  await api("/api/settings", { method: "PUT", body: JSON.stringify({ approver_name: name.trim() }) });
  $("approver").value = name.trim();
  return true;
}

// ---------- tabs ----------
function showTab(name) {
  tab = name;
  document.querySelectorAll("#tabs [data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  document.querySelectorAll(".tab-pane").forEach((p) => (p.hidden = p.id !== `tab-${name}`));
  history.replaceState(null, "", `#${name}`);
  refresh();
}
$("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-tab]");
  if (b) showTab(b.dataset.tab);
});
$("country").addEventListener("change", refresh);
$("month").addEventListener("change", refresh);

function refresh() {
  if (tab === "mhr") loadMhr();
  if (tab === "library") loadLibrary();
  if (tab === "review") loadReview();
  updateReviewCount();
}

// ---------- Machine & labour rates ----------
const MHR_COLS = [
  ["depreciation", "Depreciation"], ["interest", "Interest"], ["power", "Power"], ["maintenance", "Maintenance"],
  ["floor_space", "Floor space"], ["consumables", "Consumables"], ["overhead", "Overhead"],
];
const LAB_COLS = [["base_rate", "Base rate"], ["supervision", "Supervision"], ["productivity_loss", "Non-productive"]];

function cellFor(row, nodeId, cls = "") {
  if (row.error || !row.nodes?.[nodeId]) return `<td class="calc num">—</td>`;
  return `<td class="calc num ${cls}"><button type="button" class="tv" data-row="${row._key}" data-node="${esc(nodeId)}">
    ${num(row.nodes[nodeId].value, 2)}</button></td>`;
}

async function loadMhr() {
  $("mhrStatus").textContent = "";
  try {
    mhrData = await api(`/api/mhr?country=${country()}&as_of=${month()}`);
  } catch (err) {
    $("mhrStatus").textContent = err.message;
    return;
  }
  const cur = mhrData.country.currency;
  const all = [...mhrData.machines, ...mhrData.labour];
  all.forEach((r, i) => (r._key = i));
  const errs = all.filter((r) => r.error);
  $("mhrStatus").textContent = errs.length ? `${errs.length} rows could not be calculated: ${errs[0].error}` : "";

  const exIds = new Set();
  all.forEach((r) => (r.rates_used || []).forEach((x) => x.is_example && exIds.add(x.id)));
  $("mhrExamples").hidden = !exIds.size;
  $("mhrExamples").textContent = `${exIds.size} of the rate versions used for ${mhrData.country.name} are still EXAMPLE values. ` +
    "Replace them in the Rate library before using these rates for negotiations.";

  $("mhrTable").innerHTML = `<thead><tr><th>Machine</th><th>Process</th>
    ${MHR_COLS.map(([, l]) => `<th class="num">${l} (${cur}/h)</th>`).join("")}
    <th class="num">MHR (${cur}/h)</th><th class="num">MHR (INR/h)</th></tr></thead><tbody>` +
    mhrData.machines.map((r) => `<tr><td>${esc(r.machine.name)}${r.machine.is_example ? ' <span class="example-mark" title="Example machine data">•</span>' : ""}
      <div class="trace-var">${esc(r.machine.machine_id)}</div></td><td>${esc(r.machine.process)}</td>
      ${r.error ? `<td colspan="${MHR_COLS.length + 2}" class="error">${esc(r.error)}</td>` :
        MHR_COLS.map(([n]) => cellFor(r, `calc:${n}`)).join("") + cellFor(r, r.root, "strong") + cellFor(r, "result:inr", "strong")}
      </tr>`).join("") + "</tbody>";

  $("labourTable").innerHTML = `<thead><tr><th>Skill level</th>
    ${LAB_COLS.map(([, l]) => `<th class="num">${l} (${cur}/h)</th>`).join("")}
    <th class="num">Labour rate (${cur}/h)</th><th class="num">Labour rate (INR/h)</th></tr></thead><tbody>` +
    mhrData.labour.map((r) => `<tr><td>${esc(r.grade.name)}</td>
      ${r.error ? `<td colspan="${LAB_COLS.length + 2}" class="error">${esc(r.error)}</td>` :
        LAB_COLS.map(([n]) => cellFor(r, `calc:${n}`)).join("") + cellFor(r, r.root, "strong") + cellFor(r, "result:inr", "strong")}
      </tr>`).join("") + "</tbody>";
}

document.addEventListener("click", (e) => {
  const b = e.target.closest("button.tv[data-row]");
  if (!b || !mhrData) return;
  const all = [...mhrData.machines, ...mhrData.labour];
  window.TracePanel.open(all[Number(b.dataset.row)], b.dataset.node);
});

// ---------- Rate library ----------
async function loadLibrary() {
  $("libStatus").textContent = "";
  try {
    const body = await api(`/api/rates?as_of=${month()}&country=${country()}`);
    library = body.rows;
  } catch (err) {
    $("libStatus").textContent = err.message;
    $("libStatus").className = "status error";
    return;
  }
  const cats = [...new Set(library.map((r) => r.category))];
  const keep = $("category").value;
  $("category").innerHTML = '<option value="">All</option>' + cats.map((c) => `<option ${c === keep ? "selected" : ""}>${esc(c)}</option>`).join("");
  renderLibrary();
}

function renderLibrary() {
  const cat = $("category").value;
  const q = $("search").value.trim().toLowerCase();
  const exOnly = $("examplesOnly").checked;
  const rows = library.filter((r) => (!cat || r.category === cat) &&
    (!exOnly || r.approved?.is_example) &&
    (!q || `${r.item} ${r.approved?.source ?? ""} ${r.approved?.comment ?? ""}`.toLowerCase().includes(q)));
  $("libTable").innerHTML = `<thead><tr><th>Category</th><th>Item</th><th>Country</th><th class="num">Approved value</th>
    <th>Unit</th><th>Month</th><th>Status</th><th>Source</th><th>Open drafts</th><th></th></tr></thead><tbody>` +
    (rows.map((r) => {
      const a = r.approved;
      const i = library.indexOf(r);
      return `<tr><td>${esc(r.category)}</td><td>${esc(r.item)}</td><td>${esc(r.country || "global")}</td>
        <td class="calc num">${a ? `<button type="button" class="tv" data-lib="${i}">${num(a.value)}</button>` : "—"}</td>
        <td>${esc(a?.unit ?? "")}</td><td>${esc(a?.month ?? "no approved version")}</td>
        <td>${a ? badge("approved") : ""} ${exampleTag(a?.is_example)}</td>
        <td class="src">${esc(a?.source ?? "")}</td>
        <td>${r.open_drafts ? `<button type="button" class="link-btn" data-goreview>${r.open_drafts} in review</button>` : ""}</td>
        <td><button type="button" class="btn btn-outline small" data-newver="${i}">New version</button></td></tr>`;
    }).join("") || '<tr><td colspan="10" class="empty">No rates match.</td></tr>') + "</tbody>";
}
$("category").addEventListener("change", renderLibrary);
$("search").addEventListener("input", renderLibrary);
$("examplesOnly").addEventListener("change", renderLibrary);
$("libTable").addEventListener("click", (e) => {
  const v = e.target.closest("[data-lib]");
  if (v) return window.TracePanel.openRate(library[Number(v.dataset.lib)].approved);
  const n = e.target.closest("[data-newver]");
  if (n) return openRateForm(library[Number(n.dataset.newver)]);
  if (e.target.closest("[data-goreview]")) showTab("review");
});

// ---------- new version dialog ----------
let editingId = null;
function openRateForm(entry, draft) {
  const f = $("rateForm");
  // namedItem: f.elements.item would be the collection's item() method, not the "item" field.
  const el = (k) => f.elements.namedItem(k);
  f.reset();
  editingId = draft?.id ?? null;
  const base = draft || entry?.approved || {};
  for (const k of ["category", "item", "country", "unit", "currency", "source", "source_url", "comment", "fetched_date"]) {
    el(k).value = base[k] ?? entry?.[k] ?? "";
  }
  el("value").value = base.value ?? "";
  el("month").value = draft ? draft.month : month();
  el("is_example").checked = Boolean(draft?.is_example);
  const keyed = Boolean(entry || draft);
  ["category", "item", "country"].forEach((k) => (el(k).readOnly = keyed));
  if (!entry && !draft) el("country").value = country();
  $("rateDialogTitle").textContent = draft ? "Edit draft" : entry ? "New version" : "New rate";
  $("rateFormStatus").textContent = "";
  $("rateDialog").showModal();
}
$("addRate").addEventListener("click", () => openRateForm(null));
$("rateCancel").addEventListener("click", () => $("rateDialog").close());

async function saveRate(approve) {
  const f = $("rateForm");
  if (!f.reportValidity()) return;
  if (approve && !(await ensureApprover())) return;
  const data = Object.fromEntries(new FormData(f).entries());
  data.value = Number(data.value);
  data.is_example = f.elements.namedItem("is_example").checked;
  data.approve = approve;
  try {
    await api(editingId ? `/api/rates/${editingId}` : "/api/rates", {
      method: editingId ? "PUT" : "POST", body: JSON.stringify(data) });
    $("rateDialog").close();
    refresh();
  } catch (err) {
    $("rateFormStatus").textContent = err.message;
  }
}
$("rateSaveDraft").addEventListener("click", () => saveRate(false));
$("rateSaveApprove").addEventListener("click", () => saveRate(true));

$("upload").addEventListener("change", async () => {
  const file = $("upload").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch("/api/rates/upload", { method: "POST", body: form });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail);
    $("libStatus").textContent = `${body.drafts_created} rates imported as drafts. Review and approve them under Rate review.`;
    $("libStatus").className = "status ok";
    refresh();
  } catch (err) {
    $("libStatus").textContent = `Import rejected, nothing was changed: ${err.message}`;
    $("libStatus").className = "status error";
  } finally {
    $("upload").value = "";
  }
});

// ---------- Rate review ----------
let reviewItems = [];
async function loadReview() {
  const s = await api("/api/settings");
  $("approver").value = s.approver_name;
  $("threshold").value = s.review_threshold_pct;
  const body = await api("/api/rates/review");
  reviewItems = body.items;
  $("reviewTable").innerHTML = `<thead><tr><th><input type="checkbox" id="checkAll" aria-label="Select all" /></th>
    <th>Rate</th><th>Country</th><th class="num">Approved now</th><th class="num">Proposed</th><th>Month</th>
    <th class="num">Change</th><th>Source</th><th>Comment</th><th>Status</th><th></th></tr></thead><tbody>` +
    (reviewItems.map((it, i) => {
      const d = it.draft, a = it.approved;
      const ch = it.change_pct == null ? "new" : `${it.change_pct > 0 ? "+" : ""}${num(it.change_pct, 1)} %`;
      const link = d.source_url ? `<a class="link" href="${esc(d.source_url)}" target="_blank" rel="noopener">link</a>` : "";
      return `<tr class="${it.over_threshold ? "over" : ""}">
        <td><input type="checkbox" class="pick" data-i="${i}" aria-label="Select" /></td>
        <td>${esc(d.category)} / ${esc(d.item)} ${exampleTag(d.is_example)}</td><td>${esc(d.country || "global")}</td>
        <td class="calc num">${a ? `<button type="button" class="tv" data-appr="${i}">${num(a.value)}</button><div class="trace-var">${esc(a.month)}</div>` : "—"}</td>
        <td class="input num"><input type="number" step="any" min="0" value="${d.value}" data-val="${i}" aria-label="Proposed value" /></td>
        <td>${esc(d.month)}</td>
        <td class="calc num ${it.over_threshold ? "flag" : ""}">${ch}${it.over_threshold ? ' <span title="Above threshold">⚠</span>' : ""}</td>
        <td>${esc(d.source)} ${link}</td>
        <td class="input"><input type="text" value="" placeholder="${esc(d.comment)}" data-com="${i}" aria-label="Comment" /></td>
        <td>${badge(d.status)}</td>
        <td class="actions"><button type="button" class="btn btn-primary small" data-act="approved" data-i="${i}">Approve</button>
          <button type="button" class="btn btn-outline small" data-act="reviewed" data-i="${i}">Reviewed</button>
          <button type="button" class="btn btn-outline small" data-act="rejected" data-i="${i}">Reject</button></td></tr>`;
    }).join("") || '<tr><td colspan="11" class="empty">Nothing waiting for review.</td></tr>') + "</tbody>";
  updateBulk();
}

async function saveEdits(i) {
  const it = reviewItems[i];
  const v = Number(document.querySelector(`[data-val="${i}"]`).value);
  if (v !== it.draft.value) await api(`/api/rates/${it.draft.id}`, { method: "PUT", body: JSON.stringify({ ...it.draft, value: v }) });
}
const commentOf = (i) => document.querySelector(`[data-com="${i}"]`).value;

async function act(indices, status) {
  if (status === "approved" && !(await ensureApprover())) return;
  try {
    for (const i of indices) await saveEdits(i);
    // One call per distinct comment keeps comments attached to the right rows.
    for (const i of indices) {
      await api("/api/rates/status", { method: "POST",
        body: JSON.stringify({ ids: [reviewItems[i].draft.id], status, comment: commentOf(i) }) });
    }
    $("reviewStatus").textContent = `${indices.length} rate${indices.length > 1 ? "s" : ""} ${STATUS[status].toLowerCase()}.`;
    $("reviewStatus").className = "status ok";
  } catch (err) {
    $("reviewStatus").textContent = err.message;
    $("reviewStatus").className = "status error";
  }
  loadReview();
  updateReviewCount();
}

$("reviewTable").addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]");
  if (b) return act([Number(b.dataset.i)], b.dataset.act);
  const a = e.target.closest("[data-appr]");
  if (a) return window.TracePanel.openRate(reviewItems[Number(a.dataset.appr)].approved);
});
$("reviewTable").addEventListener("change", (e) => {
  if (e.target.id === "checkAll") document.querySelectorAll(".pick").forEach((c) => (c.checked = e.target.checked));
  updateBulk();
});
const picked = () => [...document.querySelectorAll(".pick:checked")].map((c) => Number(c.dataset.i));
function updateBulk() {
  $("bulkApprove").disabled = $("bulkReview").disabled = !picked().length;
}
$("bulkApprove").addEventListener("click", () => act(picked(), "approved"));
$("bulkReview").addEventListener("click", () => act(picked(), "reviewed"));
$("saveSettings").addEventListener("click", async () => {
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify({
      approver_name: $("approver").value, review_threshold_pct: $("threshold").value }) });
    $("reviewStatus").textContent = "Settings saved.";
    $("reviewStatus").className = "status ok";
    loadReview();
  } catch (err) {
    $("reviewStatus").textContent = err.message;
    $("reviewStatus").className = "status error";
  }
});

async function updateReviewCount() {
  try {
    const body = await api("/api/rates/review");
    $("reviewCount").textContent = body.items.length ? `(${body.items.length})` : "";
  } catch {
    $("reviewCount").textContent = "";
  }
}

// ---------- start ----------
(async function init() {
  const setup = await api("/api/costing-setup");
  countries = setup.countries;
  $("country").innerHTML = countries.map((c) => `<option value="${esc(c.code)}">${esc(c.name)} (${esc(c.currency)})</option>`).join("");
  $("month").value = new Date().toISOString().slice(0, 7);
  const start = location.hash.slice(1);
  showTab(["mhr", "library", "review"].includes(start) ? start : "mhr");
})();
