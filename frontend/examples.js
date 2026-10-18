// Replace example values: every rate and master-data row still marked EXAMPLE, counted by category, replaceable here.
const { $, esc, fmt, api, status } = window.DTC;
let list = null;
const open = new Set(); // expanded categories / tables, kept across reloads

const pct = (left, total) => (total ? Math.round((100 * (total - left)) / total) : 100);
const bar = (left, total) => `<div class="ex-bar" title="${pct(left, total)} % replaced"><span style="width:${pct(left, total)}%"></span></div>`;
const tile = (label, value, sub, alert = false) =>
  `<div class="card tile ${alert ? "alert" : ""}"><div class="label">${esc(label)}</div><div class="value">${value}</div><div class="sub">${esc(sub)}</div></div>`;

async function load() {
  try {
    list = await api("/api/examples");
  } catch (err) {
    return status($("status"), err.message, "error");
  }
  const s = list.summary;
  $("approver").hidden = !!list.approver_name;
  $("tiles").innerHTML =
    tile("Example rates left", fmt(s.rates_left), `of ${fmt(s.rates_total)} approved rates`, s.rates_left > 0) +
    tile("Used in stored costs", fmt(s.rates_used_in_costs), "example rates that a stored RM / tool cost uses", s.rates_used_in_costs > 0) +
    tile("Example rows left", fmt(s.rows_left), `of ${fmt(s.rows_total)} master-data rows`, s.rows_left > 0) +
    tile("Replaced", `${fmt(s.replaced_pct, 1)} %`, "of all rates and rows");
  const countries = [...new Set(list.rates.flatMap((g) => Object.keys(g.by_country)))].sort();
  const c = $("country");
  const keep = c.value;
  c.innerHTML = '<option value="">All countries</option>' + countries.map((x) => `<option ${x === keep ? "selected" : ""}>${esc(x)}</option>`).join("");
  render();
}

function matches(text) {
  const q = $("q").value.trim().toLowerCase();
  return !q || text.toLowerCase().includes(q);
}

function render() {
  const country = $("country").value;
  const usedOnly = $("usedOnly").checked;
  const rateItems = (g) =>
    g.items.filter((i) => (!country || (i.country || "global") === country) && (!usedOnly || i.used_by > 0) &&
      matches(`${g.title} ${i.item} ${i.country}`));

  $("ratesNote").textContent = `(approved versions as of ${list.as_of}; the ones used by the most stored costs come first)`;
  $("rates").innerHTML = `<thead><tr><th>Category</th><th class="num">Example left</th><th class="num">Of</th><th>Replaced</th>
    <th>By country</th></tr></thead><tbody>` +
    list.rates.map((g) => {
      const items = rateItems(g);
      const id = `r:${g.category}`;
      const isOpen = open.has(id) && items.length;
      return `<tr class="group ${isOpen ? "open" : ""}" data-toggle="${esc(id)}"><td><b>${esc(g.title)}</b> <span class="note">${esc(g.category)}</span></td>
        <td class="calc num">${g.example ? `<b>${fmt(g.example)}</b>` : '<span class="done">0 ✓</span>'}</td><td class="calc num">${fmt(g.total)}</td>
        <td>${bar(g.example, g.total)}</td>
        <td><div class="chips">${Object.entries(g.by_country).map(([k, n]) => `<span class="chip">${esc(k)} ${n}</span>`).join("")}</div></td></tr>` +
        (isOpen ? `<tr class="detail"><td colspan="5"><table class="cost-table inner"><thead><tr><th>Item</th><th>Country</th>
          <th class="num">Current (EXAMPLE)</th><th>Month</th><th class="num">Used by</th><th>New value</th><th></th></tr></thead><tbody>
          ${items.map((i) => `<tr><td>${esc(i.item)}</td><td>${esc(i.country || "—")}</td>
            <td class="calc num">${fmt(i.value, 4)} ${esc(i.unit)}</td><td>${esc(i.month)}</td>
            <td class="calc num">${i.used_by ? `${i.used_by} part${i.used_by === 1 ? "" : "s"}` : "—"}</td>
            <td><input class="new" type="number" min="0" step="any" data-rate="${i.id}" placeholder="${i.value}" /></td>
            <td><button type="button" class="btn btn-primary small" data-replace-rate="${i.id}">Replace</button>
              <button type="button" class="btn btn-outline small" data-keep-rate="${i.id}" title="The value is right: approve it as a real value">Keep</button></td></tr>`).join("")}
          </tbody></table></td></tr>` : "");
    }).join("") + "</tbody>";

  $("rows").innerHTML = `<thead><tr><th>Table</th><th class="num">Example left</th><th class="num">Of</th><th>Replaced</th><th></th></tr></thead><tbody>` +
    list.tables.map((t) => {
      const items = t.items.filter((i) => matches(`${t.title} ${i.label} ${i.notes}`));
      const id = `t:${t.set}:${t.table}`;
      const isOpen = open.has(id) && items.length;
      const edit = `/master-data?set=${t.set}&sheet=${t.table}&examples=1`;
      return `<tr class="group ${isOpen ? "open" : ""}" data-toggle="${esc(id)}"><td><b>${esc(t.title)}</b> <span class="note">${esc(t.set_title)}</span></td>
        <td class="calc num">${t.example ? `<b>${fmt(t.example)}</b>` : '<span class="done">0 ✓</span>'}</td><td class="calc num">${fmt(t.total)}</td>
        <td>${bar(t.example, t.total)}</td><td><a class="link" href="${edit}">Edit in Master data</a></td></tr>` +
        (isOpen ? `<tr class="detail"><td colspan="5"><table class="cost-table inner"><thead><tr><th>Row</th>
          ${t.value_column ? `<th class="num">${esc(t.value_label)} (EXAMPLE)</th><th>New value</th>` : "<th>Notes</th>"}<th></th></tr></thead><tbody>
          ${items.map((i, n) => `<tr><td>${esc(i.label)}</td>
            ${t.value_column ? `<td class="calc num">${fmt(i.value, 4)}</td>
              <td><input class="new" type="number" min="0" step="any" data-row="${n}" placeholder="${i.value ?? ""}" /></td>`
              : `<td class="note">${esc(i.notes).slice(0, 120)}</td>`}
            <td>${t.value_column ? `<button type="button" class="btn btn-primary small" data-replace-row="${n}" data-table="${esc(id)}">Replace</button> ` : `<a class="btn btn-outline small" href="${edit}">Edit</a> `}
              <button type="button" class="btn btn-outline small" data-keep-row="${n}" data-table="${esc(id)}" title="The row is right: clear its Example flag">Keep</button></td></tr>`).join("")}
          </tbody></table></td></tr>` : "");
    }).join("") + "</tbody>";
}

async function act(fn, done) {
  status($("status"), "Saving…");
  try {
    await fn();
    await load();
    status($("status"), done, "ok");
  } catch (err) {
    status($("status"), err.message, "error");
  }
}

function tableItem(btn, attr) {
  const [, set, table] = btn.dataset.table.split(":");
  const t = list.tables.find((x) => x.set === set && x.table === table);
  const visible = t.items.filter((i) => matches(`${t.title} ${i.label} ${i.notes}`));
  return { t, item: visible[Number(btn.dataset[attr])] };
}

document.querySelector("main").addEventListener("click", (e) => {
  const g = e.target.closest("tr.group");
  if (g && !e.target.closest("a")) {
    open.has(g.dataset.toggle) ? open.delete(g.dataset.toggle) : open.add(g.dataset.toggle);
    return render();
  }
  const rr = e.target.closest("[data-replace-rate]");
  if (rr) {
    const v = document.querySelector(`input[data-rate="${rr.dataset.replaceRate}"]`).value;
    if (v === "") return status($("status"), "Type the real value first, or use Keep if the example value is right.", "error");
    return act(() => api("/api/examples/rate", { method: "POST", body: JSON.stringify({ rate_id: Number(rr.dataset.replaceRate), value: Number(v) }) }),
      "Replaced: saved as a new approved version.");
  }
  const kr = e.target.closest("[data-keep-rate]");
  if (kr) {
    return act(() => api("/api/examples/rate", { method: "POST", body: JSON.stringify({ rate_id: Number(kr.dataset.keepRate) }) }),
      "Kept: the value is now an approved real value.");
  }
  const rw = e.target.closest("[data-replace-row]");
  if (rw) {
    const { t, item } = tableItem(rw, "replaceRow");
    const v = rw.closest("tr").querySelector("input.new").value;
    if (v === "") return status($("status"), "Type the real value first, or use Keep if the row is right.", "error");
    return act(() => api("/api/examples/row", { method: "POST", body: JSON.stringify({ set: t.set, table: t.table, key: item.key, value: Number(v) }) }),
      `Saved ${t.title} · ${item.label}.`);
  }
  const kw = e.target.closest("[data-keep-row]");
  if (kw) {
    const { t, item } = tableItem(kw, "keepRow");
    return act(() => api("/api/examples/row", { method: "POST", body: JSON.stringify({ set: t.set, table: t.table, key: item.key }) }),
      `Kept ${t.title} · ${item.label}: Example flag cleared.`);
  }
});

$("approverSave").addEventListener("click", () =>
  act(() => api("/api/settings", { method: "PUT", body: JSON.stringify({ approver_name: $("approverName").value }) }), "Name saved."));
$("country").addEventListener("change", render);
$("q").addEventListener("input", render);
$("usedOnly").addEventListener("change", render);
$("filters").addEventListener("submit", (e) => e.preventDefault());
load();
