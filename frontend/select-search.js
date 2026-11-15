// Search box on long dropdowns (every page): a <select> with SEARCH_MIN or more choices opens a list with a
// search field instead of the browser list. The <select> itself stays the source of truth: picking a line sets
// select.value and fires "input" + "change", so every page's own code keeps working. Matching: every typed word
// must appear in the option text, its value (codes) or its group heading; case does not matter.
(function () {
  const SEARCH_MIN = 12;
  let pop = null; // { box, input, list, select, items, active }

  const norm = (s) => String(s ?? "").toLowerCase();
  const wants = (sel) => sel && sel.tagName === "SELECT" && !sel.multiple && !sel.disabled && (sel.size || 0) <= 1 &&
    sel.options.length >= SEARCH_MIN && !sel.hasAttribute("data-no-search");

  function close(focusBack) {
    if (!pop) return;
    const sel = pop.select;
    pop.box.remove();
    pop = null;
    if (focusBack) sel.focus({ preventScroll: true });
  }

  function choose(opt) {
    const sel = pop.select;
    const changed = sel.value !== opt.value || !opt.selected;
    opt.selected = true;
    close(true);
    if (changed) {
      sel.dispatchEvent(new Event("input", { bubbles: true }));
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  function setActive(i) {
    const shown = pop.items.filter((x) => !x.el.hidden && !x.opt.disabled);
    if (!shown.length) { pop.active = null; return; }
    i = Math.max(0, Math.min(shown.length - 1, i));
    pop.items.forEach((x) => x.el.classList.remove("active"));
    pop.active = shown[i];
    pop.active.el.classList.add("active");
    pop.active.el.scrollIntoView({ block: "nearest" });
  }

  function filter() {
    const words = norm(pop.input.value).split(/\s+/).filter(Boolean);
    let count = 0;
    for (const x of pop.items) {
      x.el.hidden = !words.every((w) => x.hay.includes(w));
      if (!x.el.hidden) count++;
    }
    for (const g of pop.list.querySelectorAll(".ss-group")) {
      let n = g.nextElementSibling, any = false;
      while (n && !n.classList.contains("ss-group")) { if (!n.hidden) any = true; n = n.nextElementSibling; }
      g.hidden = !any;
    }
    pop.empty.hidden = count > 0;
    pop.count.textContent = words.length ? `${count} of ${pop.items.length}` : `${pop.items.length} choices`;
    setActive(0);
  }

  function place() {
    const r = pop.select.getBoundingClientRect();
    const box = pop.box;
    const w = Math.max(r.width, 260);
    box.style.minWidth = `${w}px`;
    const below = window.innerHeight - r.bottom, above = r.top;
    const h = Math.min(420, Math.max(below, above) - 12);
    pop.list.style.maxHeight = `${Math.max(120, h - 80)}px`;
    let left = r.left;
    if (left + box.offsetWidth > window.innerWidth - 8) left = Math.max(8, window.innerWidth - box.offsetWidth - 8);
    box.style.left = `${left}px`;
    box.style.top = below >= 220 || below >= above
      ? `${r.bottom + 2}px`
      : `${Math.max(4, r.top - box.offsetHeight - 2)}px`;
  }

  function open(sel) {
    close(false);
    const box = document.createElement("div");
    box.className = "ss-pop";
    box.innerHTML = `<div class="ss-head"><input type="search" class="ss-input" placeholder="Search…" autocomplete="off" />
      <span class="ss-count"></span></div><div class="ss-list" role="listbox"></div>`;
    const list = box.querySelector(".ss-list");
    const items = [];
    const add = (opt, group) => {
      const el = document.createElement("div");
      el.className = "ss-item" + (opt.selected ? " selected" : "") + (opt.disabled ? " disabled" : "") + (group ? " in-group" : "");
      el.textContent = opt.text.trim() || "—";
      el.setAttribute("role", "option");
      list.appendChild(el);
      items.push({ el, opt, hay: norm(`${opt.text} ${opt.value} ${group}`) });
    };
    for (const node of sel.children) {
      if (node.tagName === "OPTGROUP") {
        const g = document.createElement("div");
        g.className = "ss-group";
        g.textContent = node.label;
        list.appendChild(g);
        for (const o of node.children) if (o.tagName === "OPTION") add(o, node.label);
      } else if (node.tagName === "OPTION") add(node, "");
    }
    const empty = document.createElement("div");
    empty.className = "ss-empty";
    empty.textContent = "No match";
    list.appendChild(empty);
    (sel.closest("dialog[open]") || document.body).appendChild(box); // inside a modal dialog, or it cannot be clicked
    pop = { box, input: box.querySelector(".ss-input"), list, select: sel, items, active: null, empty, count: box.querySelector(".ss-count") };

    list.addEventListener("mousedown", (e) => e.preventDefault()); // keep focus in the search field
    list.addEventListener("click", (e) => {
      const x = items.find((it) => it.el === e.target.closest(".ss-item"));
      if (x && !x.opt.disabled) choose(x.opt);
    });
    pop.input.addEventListener("input", filter);
    pop.input.addEventListener("keydown", (e) => {
      const shown = items.filter((x) => !x.el.hidden && !x.opt.disabled);
      const i = shown.indexOf(pop.active);
      if (e.key === "ArrowDown") { e.preventDefault(); setActive(i + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive(i - 1); }
      else if (e.key === "PageDown") { e.preventDefault(); setActive(i + 10); }
      else if (e.key === "PageUp") { e.preventDefault(); setActive(i - 10); }
      else if (e.key === "Enter") { e.preventDefault(); if (pop.active) choose(pop.active.opt); }
      else if (e.key === "Escape") { e.preventDefault(); close(true); }
      else if (e.key === "Tab") close(false);
    });
    filter();
    const cur = items.filter((x) => !x.opt.disabled).findIndex((x) => x.opt.selected);
    setActive(cur < 0 ? 0 : cur);
    place();
    pop.input.focus({ preventScroll: true });
  }

  document.addEventListener("mousedown", (e) => {
    if (pop && !pop.box.contains(e.target)) close(false);
    const sel = e.target.closest?.("select");
    if (e.button === 0 && wants(sel)) {
      e.preventDefault();
      sel.focus({ preventScroll: true });
      open(sel);
    }
  }, true);
  document.addEventListener("keydown", (e) => {
    const sel = e.target;
    if (!wants(sel) || pop) return;
    if (e.key === "Enter" || e.key === " " || e.key === "F4" || (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowUp"))) {
      e.preventDefault();
      open(sel);
    }
  }, true);
  window.addEventListener("resize", () => close(false));
  // the page or a table scrolls: the list follows its dropdown, and closes once the dropdown is gone or out of sight
  document.addEventListener("scroll", (e) => {
    if (!pop || pop.box.contains(e.target)) return;
    const r = pop.select.getBoundingClientRect();
    if (!pop.select.isConnected || r.bottom < 0 || r.top > window.innerHeight) close(false);
    else place();
  }, true);

  window.DTCSelectSearch = { open, close, SEARCH_MIN };
})();
