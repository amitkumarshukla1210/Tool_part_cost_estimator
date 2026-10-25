// Column filters on every table of the app: a ▾ button in each column header opens a dropdown with a search box,
// the column's values as tick boxes (multi-select), Select all and Clear all. Works on tables the pages redraw:
// the filter is kept per table and column and applied again after each redraw. A table opts out with data-nofilter.
(function () {
  const state = new Map();          // tableKey -> Map(column label -> {values: Set|null, text: ""})
  const BLANK = "(blank)";
  let popup = null;
  let busy = false;

  const tableKey = (t) => t.id || t.dataset.tfKey || (t.dataset.tfKey = `t${[...document.querySelectorAll("table")].indexOf(t)}`);
  const labelOf = (th) => (th.dataset.tfLabel ?? (th.dataset.tfLabel = th.textContent.trim()));

  function cellValue(td) {
    if (!td) return BLANK;
    const box = td.querySelector("input[type=checkbox]");
    if (box && !td.querySelector("input:not([type=checkbox]), select")) return box.checked ? "Yes" : "No";
    const sel = td.querySelector("select");
    if (sel) return (sel.selectedOptions[0]?.textContent || sel.value || "").trim() || BLANK;
    const inp = td.querySelector("input, textarea");
    if (inp) return String(inp.value).trim() || BLANK;
    return td.textContent.replace(/\s+/g, " ").trim() || BLANK;
  }

  // header cells of the last header row with their column index (colspans counted)
  function headers(table) {
    const rows = table.tHead?.rows;
    if (!rows || !rows.length) return [];
    let col = 0;
    return [...rows[rows.length - 1].cells].map((th) => {
      const at = col;
      col += th.colSpan || 1;
      return { th, col: at, span: th.colSpan || 1 };
    });
  }

  function cellAt(tr, col) {
    let c = 0;
    for (const td of tr.cells) {
      if (col >= c && col < c + (td.colSpan || 1)) return td;
      c += td.colSpan || 1;
    }
    return null;
  }

  const dataRows = (table) => [...table.tBodies].flatMap((b) => [...b.rows])
    .filter((tr) => !(tr.cells.length === 1 && tr.cells[0].colSpan > 1));

  function filters(table) {
    const k = tableKey(table);
    if (!state.has(k)) state.set(k, new Map());
    return state.get(k);
  }

  const active = (f) => f && (f.values || f.text);

  function apply(table) {
    const fs = filters(table);
    const cols = headers(table).filter((h) => active(fs.get(labelOf(h.th))));
    let shown = 0, total = 0;
    for (const tr of dataRows(table)) {
      total++;
      const ok = cols.every((h) => {
        const f = fs.get(labelOf(h.th));
        const v = cellValue(cellAt(tr, h.col));
        return (!f.values || f.values.has(v)) && (!f.text || v.toLowerCase().includes(f.text.toLowerCase()));
      });
      tr.classList.toggle("tf-hidden", !ok);
      if (ok) shown++;
    }
    for (const h of headers(table)) h.th.querySelector(".tf-btn")?.classList.toggle("on", !!active(fs.get(labelOf(h.th))));
    bar(table, cols.length, shown, total);
  }

  function bar(table, n, shown, total) {
    const host = table.closest(".table-wrap") || table;
    let b = host.previousElementSibling;
    if (!(b && b.classList.contains("tf-bar"))) {
      if (!n) return;
      b = document.createElement("div");
      b.className = "tf-bar";
      host.before(b);
    }
    if (!n) return b.remove();
    const html = `Filtered: ${shown} of ${total} rows · ${n} column${n > 1 ? "s" : ""} <button type="button" class="tf-clear">Clear all filters</button>`;
    if (b.dataset.html === html) return;      // unchanged: no DOM write, so the observer does not loop
    b.dataset.html = html;
    b.innerHTML = html;
    b.querySelector(".tf-clear").onclick = () => { filters(table).clear(); apply(table); closePopup(); };
  }

  function closePopup() {
    popup?.remove();
    popup = null;
  }

  function openPopup(table, th, col) {
    closePopup();
    const label = labelOf(th);
    const fs = filters(table);
    const f = fs.get(label) || { values: null, text: "" };
    const counts = new Map();
    for (const tr of dataRows(table)) {
      const v = cellValue(cellAt(tr, col));
      counts.set(v, (counts.get(v) || 0) + 1);
    }
    const all = [...counts.keys()].sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }));
    let ticked = new Set(f.values || all);
    popup = document.createElement("div");
    popup.className = "tf-pop";
    popup.innerHTML = `<input type="search" class="tf-search" placeholder="Search ${label.replace(/"/g, "")}" />
      <div class="tf-actions"><button type="button" data-a="all">Select all</button><button type="button" data-a="none">Clear all</button>
      <button type="button" data-a="reset" title="Show every row of this column">Reset</button></div>
      <div class="tf-list"></div><p class="tf-hint"></p>`;
    const list = popup.querySelector(".tf-list");
    const search = popup.querySelector(".tf-search");
    search.value = f.text;
    const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const visible = () => all.filter((v) => !search.value || v.toLowerCase().includes(search.value.toLowerCase()));
    const draw = () => {
      list.innerHTML = visible().map((v) => `<label><input type="checkbox" value="${esc(v)}" ${ticked.has(v) ? "checked" : ""} />
        <span>${esc(v)}</span><em>${counts.get(v)}</em></label>`).join("") || '<p class="tf-note">No match.</p>';
      popup.querySelector(".tf-hint").textContent = ticked.size ? "" : "Nothing ticked: tick the values to show.";
    };
    const save = () => {
      const values = ticked.size === all.length ? null : new Set(ticked);
      const text = search.value.trim();
      if (values || text) fs.set(label, { values, text }); else fs.delete(label);
      apply(table);
    };
    search.addEventListener("input", () => { draw(); save(); });
    list.addEventListener("change", (e) => {
      if (e.target.type !== "checkbox") return;
      e.target.checked ? ticked.add(e.target.value) : ticked.delete(e.target.value);
      save();
      draw();
    });
    popup.querySelector(".tf-actions").addEventListener("click", (e) => {
      const a = e.target.dataset.a;
      if (!a) return;
      if (a === "all") visible().forEach((v) => ticked.add(v));
      if (a === "none") visible().forEach((v) => ticked.delete(v));
      if (a === "reset") { ticked = new Set(all); search.value = ""; }
      save();
      draw();
    });
    draw();
    (th.closest("dialog") || document.body).appendChild(popup);
    const r = th.getBoundingClientRect();
    popup.style.top = `${Math.min(r.bottom + 4, window.innerHeight - popup.offsetHeight - 8)}px`;
    popup.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - popup.offsetWidth - 8))}px`;
    search.focus();
  }

  function decorate() {
    if (busy) return;
    busy = true;
    for (const table of document.querySelectorAll("table")) {
      if (table.dataset.nofilter != null || table.closest("[data-nofilter]")) continue;
      const hs = headers(table);
      if (!hs.length || !dataRows(table).length) continue;
      for (const { th, col } of hs) {
        if (th.querySelector(".tf-btn") || !labelOf(th)) continue;
        const b = document.createElement("button");
        b.type = "button";
        b.className = "tf-btn";
        b.title = "Filter this column: search, tick values, select all / clear all";
        b.textContent = "▾";
        b.addEventListener("click", (e) => {
          e.stopPropagation();
          e.preventDefault();
          popup && popup.dataset.for === `${tableKey(table)}|${col}` ? closePopup() : (openPopup(table, th, col), (popup.dataset.for = `${tableKey(table)}|${col}`));
        });
        th.appendChild(b);
      }
      if (filters(table).size) apply(table);
    }
    busy = false;
  }

  let timer = null;
  new MutationObserver((muts) => {
    if (busy || muts.every((m) => popup && popup.contains(m.target))) return;
    clearTimeout(timer);
    timer = setTimeout(decorate, 60);
  }).observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener("click", (e) => { if (popup && !popup.contains(e.target) && !e.target.closest(".tf-btn")) closePopup(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePopup(); });
  window.addEventListener("resize", closePopup);
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", decorate) : decorate();
})();
