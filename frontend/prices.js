// Price master: month-wise prices of tool materials and part raw materials per country (roadmap stage 29).
const { $, esc, fmt, api, status } = window.DTC;
let meta = null;
let grid = null;
let group = "tool_material";

const COLS = {
  tool_material: ["Type", "Grade", "Used for"],
  part_material: ["Type", "Grade", "Part type"],
  part_scrap: ["Type", "Grade", "Part type"],
};

async function init() {
  meta = await api("/api/price-master/meta");
  $("groups").innerHTML = Object.entries(meta.groups).map(([k, title]) =>
    `<button role="tab" class="btn btn-outline" data-group="${k}" aria-selected="${k === group}">${esc(title)}</button>`).join("");
  $("country").innerHTML = meta.countries.map((c) =>
    `<option value="${esc(c.code)}" ${c.code === meta.base ? "selected" : ""}>${esc(c.name)} (${esc(c.currency)})</option>`).join("");
  // Prices are drafts for Rates → Rate review; only a user who may approve rates sees (unticked) "Save & approve".
  $("approveBox").hidden = !meta.may_approve;
  $("approve").checked = false;
  const [s, me] = await Promise.all([api("/api/settings"), api("/api/auth/me")]);
  $("approverBox").hidden = !meta.may_approve || me.mode === "server" || !!s.approver_name;  // with logins: the logged-in user
  await load();
}

const approving = () => meta.may_approve && $("approve").checked;

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
  const wrap = document.querySelector(".price-wrap");
  wrap.scrollLeft = wrap.scrollWidth;  // open on the latest months (older ones fill up as real prices are entered)
}

// A typed price: a new version from that month on (a draft for the Rate review, or approved by an approver).
$("grid").addEventListener("change", async (e) => {
  const inp = e.target.closest("input[data-item]");
  if (!inp || inp.value === "") return;
  status($("status"), "Saving…");
  try {
    await api("/api/price-master/price", { method: "POST", body: JSON.stringify({
      group, item: inp.dataset.item, country: grid.country, month: inp.dataset.month, value: Number(inp.value),
      approve: approving() }) });
    await load();
    status($("status"), `${inp.dataset.item} ${inp.dataset.month}: saved${approving() ? " and approved" : " as a draft (Rates → Rate review)"}.`, "ok");
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
  form.append("approve", approving());
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

init().catch((err) => status($("status"), err.message, "error"));
