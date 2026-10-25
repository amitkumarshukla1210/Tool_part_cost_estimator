// Traceability panel: shows how any traced value was made.
//   window.TracePanel.open(trace, nodeId, ctx)   a node of a calculation trace; with ctx = {partId, scope, reload()}
//                                                every value can be changed for this part only, or corrected at its
//                                                source for the future (rate library / master data)
//   window.TracePanel.openRate(rate)        a rate-library version (history + trend)
// A trace is { root, currency, nodes: {id: node}, rates_used: [...], components: [...] }.

(function () {
  const STATUS = { approved: "Approved", reviewed: "Reviewed", draft: "Draft", rejected: "Rejected" };
  let stack = [];
  let panel;
  let panelClick = () => {};

  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  function num(v, digits) {
    const abs = Math.abs(v);
    const d = digits ?? (abs >= 1000 ? 0 : abs >= 1 ? 2 : abs >= 0.01 ? 4 : 6);
    return Number(v).toLocaleString(undefined, { minimumFractionDigits: Math.min(d, 2), maximumFractionDigits: d });
  }
  const fmtNode = (n) => `${num(n.value)} ${esc(n.unit || "")}`.trim();
  const badge = (status) => `<span class="badge badge-${esc(status)}">${STATUS[status] || esc(status)}</span>`;
  const example = (on) => (on ? '<span class="badge badge-example" title="Placeholder value - replace it">EXAMPLE</span>' : "");

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement("aside");
    panel.className = "trace-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "How this value is calculated");
    panel.hidden = true;
    panel.innerHTML = `<div class="trace-head"><button type="button" class="btn btn-outline trace-back" hidden>← Back</button>
      <span class="kicker">Traceability</span>
      <button type="button" class="btn btn-outline small trace-full" title="Full screen / side panel">⤢ Full screen</button>
      <button type="button" class="trace-close" aria-label="Close">✕</button></div>
      <div class="trace-body"></div>`;
    document.body.appendChild(panel);
    panel.querySelector(".trace-close").addEventListener("click", close);
    const full = panel.querySelector(".trace-full");
    const setFull = (on) => {
      panel.classList.toggle("full", on);
      full.textContent = on ? "⤡ Side panel" : "⤢ Full screen";
      try { localStorage.setItem("dtc-trace-full", on ? "1" : ""); } catch { /* private window */ }
    };
    try { setFull(localStorage.getItem("dtc-trace-full") === "1"); } catch { setFull(false); }
    full.addEventListener("click", () => setFull(!panel.classList.contains("full")));
    panel.addEventListener("click", onEditClick);
    panel.addEventListener("click", (e) => panelClick(e));
    panel.querySelector(".trace-back").addEventListener("click", () => {
      stack.pop();
      render();
    });
    document.addEventListener("keydown", (e) => e.key === "Escape" && !panel.hidden && close());
    panel.addEventListener("click", (e) => {
      const go = e.target.closest("[data-go]");
      if (go) {
        stack.push({ trace: stack.at(-1).trace, node: go.dataset.go, ctx: stack.at(-1).ctx });
        render();
      }
    });
    return panel;
  }

  function close() {
    panel.hidden = true;
    stack = [];
  }

  function sourceText(node) {
    const s = node.source || {};
    if (s.type === "rate") {
      const r = s.rate;
      return `Rate library · ${esc(r.category)} / ${esc(r.item)}${r.country ? " · " + esc(r.country) : ""} · ${esc(r.month)} ${badge(r.status)} ${example(r.is_example)}`;
    }
    if (s.type === "machine") return `Master data → Machines · ${esc(s.machine_id)} · ${esc(s.field)} ${example(s.is_example)}`;
    if (s.type === "base") return esc(s.note);
    if (s.type === "user") return "Your input";
    if (s.type === "cad") return `3D file ${esc(s.file || "")}${s.rev ? " · rev " + esc(s.rev) : ""}${s.note ? " · " + esc(s.note) : ""}`;
    if (s.type === "master") return `Master data → ${esc(s.sheet)} · ${esc(s.row)} ${example(s.is_example)}`;
    if (s.type === "register") return `Part register · ${esc(s.note)}`;
    if (s.type === "override") return `<span class="badge badge-override">changed for this part</span> ${esc(s.by || "")} ${esc((s.at || "").replace("T", " "))}
      · was ${num(s.was)} from ${sourceText({ source: s.was_source })}${s.note && s.note !== "Changed for this part" ? ` · ${esc(s.note)}` : ""}`;
    return node.kind === "calculated" ? "Calculated" : "—";
  }

  function render() {
    const { trace, node: id, rate } = stack.at(-1);
    const body = panel.querySelector(".trace-body");
    panel.querySelector(".trace-back").hidden = stack.length < 2;
    if (rate) return renderRate(body, rate);

    const n = trace.nodes[id];
    let html = `<h3>${esc(n.label)}</h3><p class="trace-value">${fmtNode(n)}</p>`;
    if (n.description) html += `<p class="note">${esc(n.description)}</p>`;
    html += gradeBox(n, trace, stack.at(-1).ctx);       // steel grade first: why it was chosen, and another with its price

    if (n.kind === "calculated") {
      html += `<p class="trace-label">Formula${n.override ? ' <span class="badge badge-override">changed for this part</span>' : ""}</p>
        <code class="trace-formula">${esc(n.formula)}</code>`;
      if (n.override) html += `<p class="note">${esc(n.override.by || "")} ${esc((n.override.at || "").replace("T", " "))} · ` +
        (n.override.was_formula ? `master-data formula: <code>${esc(n.override.was_formula)}</code>` : `calculated value was ${num(n.override.was_value)}`) + "</p>";
      html += `<p class="trace-label">Inputs</p><div class="table-wrap"><table class="cost-table">
        <thead><tr><th>Name</th><th class="num">Value</th><th>Comes from</th></tr></thead><tbody>`;
      for (const inp of n.inputs) {
        const m = trace.nodes[inp.node];
        html += `<tr><td><button type="button" class="tv" data-go="${esc(inp.node)}">${esc(m.label)}</button>
          <div class="trace-var">${esc(inp.name)}</div></td>
          <td class="calc num">${fmtNode(m)}</td><td>${sourceText(m)}</td></tr>`;
      }
      html += "</tbody></table></div>";
    } else {
      html += `<p class="trace-label">Source</p><p>${sourceText(n)}</p>`;
      if (n.source?.type === "rate") html += rateDetails(n.source.rate) + `<div class="trace-history" data-rate></div>`;
    }

    // Full breakup of the final result, e.g. MHR = depreciation + interest + power + ...
    // Only steps in the result's own unit are listed; a step built only from other listed
    // steps is a subtotal (bold, no share) so the shares add up to 100 %.
    if (id === trace.root && trace.components?.length) {
      const total = n.value || 1;
      const parts = trace.components.filter((c) => trace.nodes[c].unit === n.unit);
      const isSubtotal = (c) => {
        const ins = trace.nodes[c].inputs || [];
        return ins.length > 1 && ins.every((i) => parts.includes(i.node));
      };
      html += `<p class="trace-label">Full breakup</p><div class="table-wrap"><table class="cost-table">
        <thead><tr><th>Component</th><th class="num">Value</th><th class="num">Share</th></tr></thead><tbody>`;
      for (const c of parts) {
        const m = trace.nodes[c];
        const sub = isSubtotal(c);
        html += `<tr class="${sub ? "subtotal" : ""}"><td><button type="button" class="tv" data-go="${esc(c)}">${esc(m.label)}</button></td>
          <td class="calc num">${fmtNode(m)}</td><td class="calc num">${sub ? "" : `${num((m.value / total) * 100, 1)} %`}</td></tr>`;
      }
      html += `<tr class="total"><td>${esc(n.label)}</td><td class="num">${fmtNode(n)}</td><td class="num">100 %</td></tr></tbody></table></div>
        <p class="note">Intermediate steps (hours per year, residual value, …) are one click away inside each component.</p>`;
    }

    html += editBox(n, stack.at(-1).ctx);

    if (stack.length === 1 && trace.rates_used?.length) {
      const ex = trace.rates_used.filter((r) => r.is_example).length;
      html += `<p class="trace-label">Rate versions used (for reproducible reports)</p>
        <p class="note">${trace.rates_used.length} approved versions as of ${esc(trace.as_of || "")}` +
        (ex ? ` · <b>${ex} still EXAMPLE values</b>` : "") +
        `: ${trace.rates_used.map((r) => `#${r.id}`).join(", ")}</p>`;
    }
    body.innerHTML = html;
    const holder = body.querySelector("[data-rate]");
    if (holder) loadHistory(holder, n.source.rate);
    const grades = body.querySelector("[data-grades]");
    if (grades) loadGrades(grades, trace);
    const bases = body.querySelector("[data-bases]");
    if (bases) loadBases(bases, n, stack.at(-1).ctx);
  }

  function rateDetails(r) {
    const link = r.source_url ? `<a class="link" href="${esc(r.source_url)}" target="_blank" rel="noopener">${esc(r.source_url)}</a>` : "—";
    return `<div class="table-wrap"><table class="cost-table"><tbody>
      <tr><td>Rate</td><td class="calc">${esc(r.category)} / ${esc(r.item)}${r.country ? " · " + esc(r.country) : ""}</td></tr>
      <tr><td>Value</td><td class="calc">${num(r.value)} ${esc(r.unit)} ${r.currency ? "(" + esc(r.currency) + ")" : ""}</td></tr>
      <tr><td>Valid from month</td><td class="calc">${esc(r.month)}</td></tr>
      <tr><td>Status</td><td class="calc">${badge(r.status)} ${example(r.is_example)}</td></tr>
      <tr><td>Approved by / date</td><td class="calc">${esc(r.approved_by || "—")} · ${esc(r.approved_date || "—")}</td></tr>
      <tr><td>Source</td><td class="calc">${esc(r.source || "—")}</td></tr>
      <tr><td>Source URL</td><td class="calc">${link}</td></tr>
      <tr><td>Fetched</td><td class="calc">${esc(r.fetched_date || "—")}</td></tr>
      <tr><td>Comment</td><td class="calc">${esc(r.comment || "—")}</td></tr>
      <tr><td>Version id</td><td class="calc">#${esc(r.id)}</td></tr>
    </tbody></table></div>`;
  }

  function renderRate(body, r) {
    body.innerHTML = `<h3>${esc(r.category)} / ${esc(r.item)}${r.country ? " · " + esc(r.country) : ""}</h3>
      <p class="trace-value">${num(r.value)} ${esc(r.unit)}</p>${rateDetails(r)}<div class="trace-history" data-rate></div>`;
    loadHistory(body.querySelector("[data-rate]"), r);
  }

  async function loadHistory(holder, r) {
    holder.innerHTML = '<p class="note">Loading history…</p>';
    try {
      const q = new URLSearchParams({ category: r.category, item: r.item, country: r.country || "" });
      const res = await fetch(`/api/rates/history?${q}`);
      const rows = await res.json();
      if (!res.ok) throw new Error(rows.detail);
      holder.innerHTML = `<p class="trace-label">Month-on-month history</p>${trend(rows, r)}
        <div class="table-wrap"><table class="cost-table"><thead><tr><th>Month</th><th class="num">Value</th>
        <th>Status</th><th>Approved by</th><th>Source</th></tr></thead><tbody>
        ${rows.slice().reverse().map((h) => `<tr><td>${esc(h.month)}${h.id === r.id ? " ◀" : ""}</td>
          <td class="calc num">${num(h.value)}</td><td>${badge(h.status)} ${example(h.is_example)}</td>
          <td>${esc(h.approved_by || "—")}</td><td>${esc(h.source || "—")}</td></tr>`).join("")}
        </tbody></table></div>`;
    } catch (err) {
      holder.innerHTML = `<p class="error">History could not be loaded: ${esc(err.message)}</p>`;
    }
  }

  // Single-series trend line: approved versions solid, drafts hollow (status also in the tooltip).
  function trend(rows, current) {
    const pts = rows.filter((h) => h.status !== "rejected");
    if (pts.length < 2) return '<p class="note">The trend chart appears once there are two or more months.</p>';
    const W = 360, H = 150, L = 52, R = 12, T = 12, B = 26;
    const vals = pts.map((p) => p.value);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (lo === hi) { lo -= Math.abs(lo) * 0.05 || 1; hi += Math.abs(hi) * 0.05 || 1; }
    const pad = (hi - lo) * 0.1;
    lo -= pad; hi += pad;
    const x = (i) => L + (i * (W - L - R)) / (pts.length - 1);
    const y = (v) => T + ((hi - v) * (H - T - B)) / (hi - lo);
    const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
    const ticks = [lo + pad, (lo + hi) / 2, hi - pad];
    // Several versions in one month: 2026-10, 2026-10 v2, ...
    const label = (i) => {
      const same = pts.slice(0, i + 1).filter((p) => p.month === pts[i].month).length;
      return same > 1 ? `${pts[i].month} v${same}` : pts[i].month;
    };
    return `<figure class="trend" aria-label="Trend of ${esc(current.item)}">
      <svg viewBox="0 0 ${W} ${H}" role="img">
        ${ticks.map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/>
          <text class="axis" x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${num(t)}</text>`).join("")}
        <path class="series" d="${line}"/>
        ${pts.map((p, i) => `<g class="pt" data-tip="${esc(label(i))}: ${num(p.value)} ${esc(p.unit)} · ${STATUS[p.status]}">
          <circle class="hit" cx="${x(i)}" cy="${y(p.value)}" r="12"/>
          <circle class="dot ${p.status === "approved" ? "" : "open"}" cx="${x(i)}" cy="${y(p.value)}" r="4.5"/></g>
          <text class="axis" x="${x(i)}" y="${H - 8}" text-anchor="${i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle"}">${esc(label(i))}</text>`).join("")}
      </svg><figcaption class="note">Solid = approved, hollow = draft / reviewed.</figcaption>
      <div class="tip" hidden></div></figure>`;
  }

  // Tooltip for trend points
  document.addEventListener("pointerover", (e) => {
    const g = e.target.closest?.(".trend .pt");
    const fig = e.target.closest?.(".trend");
    if (!fig) return;
    const tip = fig.querySelector(".tip");
    if (!g) { tip.hidden = true; return; }
    tip.textContent = g.dataset.tip;
    const box = fig.getBoundingClientRect(), dot = g.querySelector(".dot").getBoundingClientRect();
    tip.style.left = `${dot.left - box.left + dot.width / 2}px`;
    tip.style.top = `${dot.top - box.top - 8}px`;
    tip.hidden = false;
  });

  // ---------- editing (stage 24) ----------
  function editInfo(n) {
    const formula = n.kind === "calculated" && !n.method;
    const ov = formula ? n.override : n.source?.type === "override" ? n.source : null;
    const src = !formula && n.source?.type === "override" ? n.source.was_source : n.source;
    const ref = formula ? n.ref : src?.ref;
    const rate = !formula && src?.type === "rate" ? src.rate : null;
    return { formula, ov, src, ref, rate };
  }

  function editBox(n, ctx) {
    const { formula, ov, ref, rate } = editInfo(n);
    const future = ref || rate;
    if (!ctx && !future) return "";
    if (n.method) return "";
    const where = rate ? "a new version in the Rate library (this month)" : ref ? `Master data → ${esc(ref.table.replace(/_/g, " "))}` : "";
    let html = `<div class="trace-edit" data-node="${esc(n.id)}"><p class="trace-label">${formula ? "Change this formula" : "Change this value"}</p>
      ${formula ? `<textarea data-ed="formula">${esc(n.formula)}</textarea>
        <p class="note">Use the names in the Inputs table above and numbers, + - * / ( ), min, max, ceil, round, 'a if condition else b'.</p>`
        : `<div class="row"><input type="number" step="any" data-ed="value" value="${n.value}" /> <span>${esc(n.unit || "")}</span></div>`}
      <div class="row"><input data-ed="note" placeholder="Why (optional, kept in the history)" style="flex:1" /></div>
      <div class="row">
        ${ctx ? `<button type="button" class="btn btn-primary small" data-edit="part">For this ${ctx.partCode ? "part (" + esc(ctx.partCode) + ")" : "part"} only</button>` : ""}
        ${future ? `<button type="button" class="btn btn-outline small" data-edit="future" title="Corrects ${where}">Save for the future</button>` : ""}
        ${ctx && ov ? '<button type="button" class="btn btn-outline small" data-edit="reset">Reset to master data</button>' : ""}
      </div>
      <p class="note">${ctx ? "<b>For this part only</b>: used in this part's cost from now on (recalculated and stored as a new version); master data stays as it is. " : ""}
        ${future ? `<b>Save for the future</b>: corrects ${where}; new and recalculated costs use it.` : ""}</p>
      <p class="status" data-ed="status"></p></div>`;
    if (!formula && n.source?.type !== "override" && ref?.choose_base) html += `<div data-bases></div>`;
    if (!formula && ref?.choose_base && n.source?.type === "override") html += `<div data-bases></div>`;
    return html;
  }

  // ---------- steel grade: why this grade, and choose another with its price (tool BOM lines) ----------
  function gradeInfo(n, trace) {
    if (n.grade) return { current: n.grade.grade, lines: [n.grade] };
    const src = n.source?.type === "override" ? n.source.was_source : n.source;
    if (src?.type !== "rate" || src.rate.category !== "tool_material") return null;
    const current = src.rate.item;
    const lines = (trace.lines || []).filter((l) => l.grade === current)
      .map((l) => ({ line_key: l.key, element: (l.die ? l.die + " · " : "") + l.element, grade: l.grade, reason: l.grade_reason, suggested: l.suggested_grade }));
    return { current, lines };
  }

  function gradeBox(n, trace, ctx) {
    const g = gradeInfo(n, trace);
    if (!g || !g.lines.length) return "";
    const editable = ctx && ctx.scope === "tool";
    return `<div class="trace-edit grade-box" data-grades><p class="trace-label">Steel grade · ${esc(g.current)}</p>
      <div class="table-wrap"><table class="cost-table" data-nofilter><thead><tr>${editable ? "<th></th>" : ""}<th>BOM line</th><th>Why this grade</th></tr></thead><tbody>
      ${g.lines.map((l) => `<tr>${editable ? `<td><input type="checkbox" data-gline="${esc(l.line_key)}" checked /></td>` : ""}
        <td>${esc(l.element)}</td><td>${esc(l.reason || "")}${l.suggested && l.suggested !== l.grade ? ` · suggested ${esc(l.suggested)}` : ""}</td></tr>`).join("")}
      </tbody></table></div>
      ${editable ? `<div class="row"><label>Grade <select data-grade-pick><option value="${esc(g.current)}">${esc(g.current)} (loading prices…)</option></select></label>
        <span data-grade-price class="note"></span></div>
        <div class="row"><button type="button" class="btn btn-primary small" data-grade-apply>Use this grade for the ticked lines</button></div>
        <p class="note">The price per kg is the approved rate of the tool country (${esc(trace.country || "")}, ${esc(trace.as_of || "")}). The tool cost is
          recalculated and stored; the choice is learned for the next parts. A grade not in the list: + New grade on the Tool BOM.</p>
        <p class="status" data-grade-status></p>` : '<p class="note">Open this from a part (Parts → Tool cost) to change the grade.</p>'}</div>`;
  }

  let gradePrices = null;
  async function loadGrades(holder, trace) {
    const sel = holder.querySelector("[data-grade-pick]");
    if (!sel) return;
    const cur = sel.value;
    try {
      gradePrices = await (await fetch(`/api/tool-bom/grade-prices?country=${encodeURIComponent(trace.country || "IN")}&as_of=${encodeURIComponent(trace.as_of || "")}`)).json();
      const fmt = (code) => { const p = gradePrices[code]; return p?.value != null ? `${num(p.value)} ${p.unit}` : "no approved price"; };
      sel.innerHTML = Object.keys(gradePrices).map((code) => `<option value="${esc(code)}" ${code === cur ? "selected" : ""}>${esc(code)} · ${esc(gradePrices[code].hardness || "")} · ${fmt(code)}${code === cur ? " (now)" : ""}</option>`).join("");
      const show = () => {
        const a = gradePrices[cur]?.value, b = gradePrices[sel.value]?.value;
        holder.querySelector("[data-grade-price]").innerHTML = sel.value === cur ? "" : b == null ? "<b>No approved price for this grade in this country.</b>"
          : `${num(b)} ${esc(gradePrices[sel.value].unit)} instead of ${num(a)}${a ? ` (${b >= a ? "+" : ""}${num(((b - a) / a) * 100, 1)} %)` : ""} · make ${esc(gradePrices[sel.value].make || "—")}`;
      };
      sel.addEventListener("change", show);
      show();
    } catch (err) {
      holder.querySelector("[data-grade-price]").textContent = err.message;
    }
  }

  panelClick = async (e) => {
    const b = e.target.closest("[data-grade-apply]");
    if (!b) return;
    const box = b.closest(".grade-box");
    const st = box.querySelector("[data-grade-status]");
    const keys = [...box.querySelectorAll("[data-gline]:checked")].map((c) => c.dataset.gline);
    const grade = box.querySelector("[data-grade-pick]").value;
    const { trace, node: id, ctx } = stack.at(-1);
    try {
      if (!keys.length) throw new Error("Tick at least one BOM line.");
      st.textContent = "Recalculating the tool cost…"; st.className = "status";
      const r = await call(`/api/parts/${ctx.partId}/tool-bom/grade`, "PUT", { keys, grade });
      const fresh = await ctx.reload();
      if (fresh) {
        // the steel rate node of the new grade, else the same node
        const pre = id.includes(":steel:") ? id.slice(0, id.indexOf("steel:")) : "";
        const next = fresh.nodes[`${pre}steel:${grade}`] ? `${pre}steel:${grade}` : fresh.nodes[id] ? id : fresh.root;
        stack = [{ trace: fresh, node: next, ctx }];
        render();
      }
      const st2 = panel.querySelector("[data-grade-status]") || panel.querySelector('.trace-edit [data-ed="status"]');
      if (st2) { st2.textContent = r.message || `Grade ${grade} used.`; st2.className = "status ok"; }
    } catch (err) {
      st.textContent = err.message; st.className = "status error";
    }
  };

  async function call(url, method, body) {
    const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : res.statusText);
    return data;
  }

  async function onEditClick(e) {
    const b = e.target.closest("[data-edit], [data-base-use], [data-base-add]");
    if (!b) return;
    const top = stack.at(-1);
    const { trace, node: id, ctx } = top;
    const n = trace.nodes[id];
    const box = b.closest(".trace-edit") || panel.querySelector(".trace-edit");
    const st = box?.querySelector('[data-ed="status"]') || panel.querySelector("[data-bases] .status");
    const say = (msg, kind = "") => { if (st) { st.textContent = msg; st.className = `status ${kind}`; } };
    const { formula, ref, rate } = editInfo(n);
    const val = box?.querySelector('[data-ed="value"]')?.value;
    const ftext = box?.querySelector('[data-ed="formula"]')?.value;
    const note = box?.querySelector('[data-ed="note"]')?.value || "";
    try {
      say("Saving…");
      let msg = "";
      if (b.dataset.edit === "part" || b.dataset.edit === "reset") {
        const r = await call(`/api/parts/${ctx.partId}/trace-override`, "PUT", b.dataset.edit === "reset"
          ? { scope: ctx.scope, node: id, reset: true } : { scope: ctx.scope, node: id, note, ...(formula ? { formula: ftext } : { value: val }) });
        msg = r.message || "Saved for this part.";
      } else if (b.dataset.edit === "future") {
        const r = await call("/api/trace/save-default", "POST", { ref: rate ? null : ref, rate, note, ...(formula ? { formula: ftext } : { value: val }) });
        msg = r.message;
      } else if (b.dataset.baseUse) {
        const r = await call(`/api/parts/${ctx.partId}/tool-bom`, "PUT", { key: ref.line_key, line: { base: b.dataset.baseUse } });
        msg = r.message || "Base changed for this part.";
      } else if (b.dataset.baseAdd != null) {
        const f = b.closest("form");
        const row = Object.fromEntries(new FormData(f).entries());
        for (const k of Object.keys(row)) if (k !== "series" && k !== "size_code" && k !== "notes") row[k] = Number(row[k] || 0);
        const full = { part_type: ref.part_type, a_plate_mm: 0, b_plate_mm: 0, clamp_plates_mm: 0, support_plate_mm: 0, spacer_block_mm: 0,
          ejector_plates_mm: 0, notes: "Added from the traceability panel", ...row };
        await call(`/api/master-rows/mould_db/mould_bases`, "POST", { row: full });
        msg = `${full.series} ${full.size_code} added to Mould bases. Click "Use for this part" to take it.`;
        loadBases(panel.querySelector("[data-bases]"), n, ctx);
        say(msg, "ok");
        return;
      }
      if (ctx) {
        const fresh = await ctx.reload();
        if (fresh) {
          const nodeNow = fresh.nodes[id] ? id : fresh.root;
          stack = [{ trace: fresh, node: nodeNow, ctx }];
          render();
        }
      }
      const st2 = panel.querySelector('.trace-edit [data-ed="status"]');
      if (st2) { st2.textContent = msg; st2.className = "status ok"; }
    } catch (err) {
      say(err.message, "error");
    }
  }

  async function loadBases(holder, n, ctx) {
    const { ref } = editInfo(n);
    holder.innerHTML = '<p class="note">Loading mould bases / die sets…</p>';
    try {
      const db = await (await fetch("/api/mould-db")).json();
      const rows = db.mould_bases.filter((b) => b.part_type === ref.part_type).sort((a, b) => a.length_mm * a.width_mm - b.length_mm * b.width_mm);
      const cur = ref.match.size_code;
      holder.innerHTML = `<p class="trace-label">${ref.part_type === "sheet_metal" ? "Die sets" : "Mould bases"} (Master data → Mould bases · ${esc(ref.part_type.replace("_", " "))})</p>
        <div class="table-wrap"><table class="cost-table base-pick"><thead><tr><th>Series · size</th><th class="num">L × W (mm)</th><th class="num">Usable L × W</th>
          <th class="num">Stack h</th><th class="num">Weight (kg)</th><th class="num">Price (INR)</th><th></th></tr></thead><tbody>
        ${rows.map((b) => `<tr class="${b.size_code === cur ? "current" : ""}"><td>${esc(b.series)} <b>${esc(b.size_code)}</b>${b.is_example ? ' <span class="badge badge-example">EXAMPLE</span>' : ""}</td>
          <td class="num">${num(b.length_mm, 0)} × ${num(b.width_mm, 0)}</td><td class="num">${num(b.max_insert_length_mm, 0)} × ${num(b.max_insert_width_mm, 0)}</td>
          <td class="num">${num(b.stack_height_mm, 0)}</td><td class="num">${num(b.weight_kg, 0)}</td><td class="num">${num(b.cost, 0)}</td>
          <td>${b.size_code === cur ? "in use" : ctx ? `<button type="button" class="btn btn-outline small" data-base-use="${esc(b.size_code)}">Use for this part</button>` : ""}</td></tr>`).join("")}
        </tbody></table></div>
        <details class="card"><summary class="btn btn-outline small">+ Add a ${ref.part_type === "sheet_metal" ? "die set" : "mould base"} row</summary>
        <form class="grid2" onsubmit="return false">
          <label>Series <input name="series" required value="${esc(rows[0]?.series || "")}" /></label><label>Size code <input name="size_code" required /></label>
          <label>Length (mm) <input type="number" name="length_mm" required /></label><label>Width (mm) <input type="number" name="width_mm" required /></label>
          <label>Usable / pocket L (mm) <input type="number" name="max_insert_length_mm" required /></label><label>Usable / pocket W (mm) <input type="number" name="max_insert_width_mm" required /></label>
          <label>Stack height (mm) <input type="number" name="stack_height_mm" required /></label><label>Weight (kg) <input type="number" step="any" name="weight_kg" required /></label>
          <label>Price (INR) <input type="number" step="any" name="cost" required /></label>
          <div class="span2 dialog-actions"><button type="button" class="btn btn-primary small" data-base-add>Save to master data</button></div>
          <p class="status span2"></p></form></details>`;
    } catch (err) {
      holder.innerHTML = `<p class="error">${esc(err.message)}</p>`;
    }
  }

  window.TracePanel = {
    open(trace, nodeId, ctx) {
      ensurePanel();
      stack = [{ trace, node: nodeId || trace.root, ctx: ctx || null }];
      panel.hidden = false;
      render();
      panel.querySelector(".trace-close").focus();
    },
    openRate(rate) {
      ensurePanel();
      stack = [{ rate }];
      panel.hidden = false;
      render();
      panel.querySelector(".trace-close").focus();
    },
    format: num,
  };
})();
