// Traceability panel: shows how any traced value was made.
//   window.TracePanel.open(trace, nodeId)   a node of a calculation trace
//   window.TracePanel.openRate(rate)        a rate-library version (history + trend)
// A trace is { root, currency, nodes: {id: node}, rates_used: [...], components: [...] }.

(function () {
  const STATUS = { approved: "Approved", reviewed: "Reviewed", draft: "Draft", rejected: "Rejected" };
  let stack = [];
  let panel;

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
      <span class="kicker">Traceability</span><button type="button" class="trace-close" aria-label="Close">✕</button></div>
      <div class="trace-body"></div>`;
    document.body.appendChild(panel);
    panel.querySelector(".trace-close").addEventListener("click", close);
    panel.querySelector(".trace-back").addEventListener("click", () => {
      stack.pop();
      render();
    });
    document.addEventListener("keydown", (e) => e.key === "Escape" && !panel.hidden && close());
    panel.addEventListener("click", (e) => {
      const go = e.target.closest("[data-go]");
      if (go) {
        stack.push({ trace: stack.at(-1).trace, node: go.dataset.go });
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

    if (n.kind === "calculated") {
      html += `<p class="trace-label">Formula</p><code class="trace-formula">${esc(n.formula)}</code>`;
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

  window.TracePanel = {
    open(trace, nodeId) {
      ensurePanel();
      stack = [{ trace, node: nodeId || trace.root }];
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
