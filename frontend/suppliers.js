// Supplier master: list, add / edit (code from the pattern in master data), rating, parts quoted against should-cost.
const { $, esc, fmt, api, status } = window.DTC;
let list = [];
let statuses = [];
let editing = null;

const badge = (s) => `<span class="badge ${s === "blocked" ? "missing" : s === "approved" ? "status" : ""}">${esc(s || "—")}</span>`;

async function load() {
  const p = new URLSearchParams({ q: $("q").value, status: $("fStatus").value });
  try {
    const r = await api(`/api/suppliers?${p}`);
    list = r.suppliers;
    if (!statuses.length) {
      statuses = r.statuses;
      $("fStatus").innerHTML = '<option value="">all</option>' + statuses.map((s) => `<option>${esc(s)}</option>`).join("");
      $("supStatus").innerHTML = statuses.map((s) => `<option>${esc(s)}</option>`).join("");
    }
  } catch (err) {
    return status($("status"), err.message, "error");
  }
  const by = (s) => list.filter((x) => x.status === s).length;
  $("tiles").innerHTML = [["Suppliers", list.length], ...statuses.slice(0, 3).map((s) => [s, by(s)]),
    ["Rated", list.filter((x) => x.rating != null).length]]
    .map(([l, v]) => `<div class="tile"><div class="label">${esc(l)}</div><div class="value">${v}</div></div>`).join("");
  $("suppliers").innerHTML = `<thead><tr><th>Code</th><th>Name</th><th>Status</th><th>Commodities</th><th>Country</th><th>City</th>
    <th>Contact</th><th>Certifications</th><th class="num">Rating</th><th class="num">Parts</th><th></th></tr></thead><tbody>${
    list.map((s) => `<tr data-id="${s.id}"><td><a href="#" data-open="${s.id}"><b>${esc(s.code)}</b></a></td><td>${esc(s.name)}</td><td>${badge(s.status)}</td>
      <td>${esc(s.commodities)}</td><td>${esc(s.country)}</td><td>${esc(s.city)}</td>
      <td>${esc(s.contact_person)}${s.email ? `<br><a href="mailto:${esc(s.email)}">${esc(s.email)}</a>` : ""}${s.phone ? `<br>${esc(s.phone)}` : ""}</td>
      <td>${esc(s.certifications)}</td><td class="num">${s.rating == null ? "—" : fmt(s.rating, 1)}</td><td class="num">${s.part_count}</td>
      <td><button class="btn btn-outline small" data-edit="${s.id}" type="button">Edit</button></td></tr>`).join("")
    || '<tr><td colspan="11" class="empty">No supplier yet. Click + New supplier.</td></tr>'}</tbody>`;
  status($("status"), "");
}

async function openDetail(id) {
  const s = await api(`/api/suppliers/${id}`);
  $("detail").innerHTML = `<h3 class="block-title">${esc(s.code)} · ${esc(s.name)} ${badge(s.status)}</h3>
    <div class="two-col"><div class="card"><table class="cost-table"><tbody>
      ${[["Commodities", s.commodities], ["Address", [s.address, s.city, s.country].filter(Boolean).join(", ")], ["Contact", s.contact_person],
        ["E-mail", s.email], ["Phone", s.phone], ["GST / tax ID", s.tax_id], ["Payment terms", s.payment_terms], ["Currency", s.currency],
        ["Certifications", s.certifications], ["Last audit", s.audit_date], ["Capacity", s.capacity], ["Notes", s.notes]]
        .map(([k, v]) => `<tr><td>${k}</td><td>${esc(v || "—")}</td></tr>`).join("")}</tbody></table></div>
    <div class="card"><table class="cost-table"><tbody>
      <tr><td>Quality</td><td class="num">${fmt(s.quality_score, 0)}</td></tr><tr><td>Delivery</td><td class="num">${fmt(s.delivery_score, 0)}</td></tr>
      <tr><td>Cost</td><td class="num">${fmt(s.cost_score, 0)}</td></tr><tr><td><b>Rating (average)</b></td><td class="num"><b>${fmt(s.rating, 1)}</b></td></tr>
      </tbody></table></div></div>
    <h3 class="block-title">Parts quoted (${s.parts.length})</h3>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th>Part</th><th>Name</th><th>Project</th><th>Role</th><th class="num">Piece price</th>
      <th class="num">Tool price</th><th>Currency</th><th>Quote</th></tr></thead><tbody>${s.parts.map((p) => `<tr>
      <td><a href="/parts?part=${p.part_id}">${esc(p.part_code)}</a></td><td>${esc(p.part_name)}</td><td>${esc(p.project)}</td><td>${esc(p.role)}</td>
      <td class="num">${fmt(p.piece_price, 2)}</td><td class="num">${fmt(p.tool_price, 0)}</td><td>${esc(p.currency)}</td>
      <td>${esc([p.quote_ref, p.quote_date].filter(Boolean).join(" · "))}</td></tr>`).join("")
      || '<tr><td colspan="8" class="empty">Not linked to a part yet. Add it on a part (Parts → part → Suppliers &amp; quotes).</td></tr>'}</tbody></table></div>
    <details class="card"><summary>What changed, who, when (${s.history.length})</summary><ul>${s.history.map((h) =>
      `<li>${esc(h.at.replace("T", " "))} · ${esc(h.user)} · ${esc(h.action)}</li>`).join("")}</ul></details>`;
  $("detail").scrollIntoView({ behavior: "smooth" });
}

function openForm(s) {
  editing = s || null;
  const f = $("supForm");
  f.reset();
  $("supTitle").textContent = s ? `Edit ${s.code}` : "New supplier";
  if (s) for (const el of f.elements) if (el.name && s[el.name] != null) el.value = s[el.name];
  $("supDelete").hidden = !s;
  status($("supStatusMsg"), "");
  $("supDialog").showModal();
}

$("suppliers").addEventListener("click", (e) => {
  const ed = e.target.closest("[data-edit]");
  if (ed) return openForm(list.find((s) => s.id === Number(ed.dataset.edit)));
  const op = e.target.closest("[data-open]");
  if (op) { e.preventDefault(); openDetail(Number(op.dataset.open)); }
});
$("newSupplier").addEventListener("click", () => openForm(null));
document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));
$("supForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target).entries());
  try {
    const s = editing ? await api(`/api/suppliers/${editing.id}`, { method: "PUT", body: JSON.stringify(data) })
      : await api("/api/suppliers", { method: "POST", body: JSON.stringify(data) });
    $("supDialog").close();
    await load();
    status($("status"), `${s.code} · ${s.name} saved.`, "ok");
    openDetail(s.id);
  } catch (err) {
    status($("supStatusMsg"), err.message, "error");
  }
});
$("supDelete").addEventListener("click", async () => {
  if (!editing || !confirm(`Delete supplier ${editing.code} · ${editing.name}?`)) return;
  try {
    await api(`/api/suppliers/${editing.id}`, { method: "DELETE" });
    $("supDialog").close();
    $("detail").innerHTML = "";
    load();
  } catch (err) {
    status($("supStatusMsg"), err.message, "error");
  }
});
let t = null;
$("q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 250); });
$("fStatus").addEventListener("change", load);
load();
