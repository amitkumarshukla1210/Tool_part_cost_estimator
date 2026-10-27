// AI assistant (roadmap stage 36): a chat panel on every page, loaded by auth.js when the admin has switched it on.
// It only reads, with the user's own login. The chat stays in this browser tab (sessionStorage) and is sent back with each question.
(function () {
  if (document.getElementById("dtcBot")) return;
  const KEY = "dtc-bot";
  const LABELS = {
    list_projects: "projects", project_details: "project", project_dashboard: "project dashboard", project_leader_view: "leader view",
    search_parts: "part search", part_details: "part", part_geometry_trace: "weight trace", rm_cost: "RM cost", part_cost: "part cost",
    part_cost_trace: "part cost trace", tool_cost: "tool cost", tool_cost_trace: "tool cost trace", mould_concept: "tool concept",
    simulation: "simulation", sheet_metal_tools: "sheet-metal tools", tool_design: "tool design", process_parameters: "process parameters",
    machine_check: "machine", design_loop: "design loop", country_comparison: "country comparison", part_suppliers: "part suppliers",
    search_suppliers: "suppliers", rates_grid: "rates", rate_history: "rate history", price_master: "price master",
    tool_steel_prices: "steel prices", download_links: "downloads",
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  let state = { turns: [], open: false };
  try { state = { ...state, ...JSON.parse(sessionStorage.getItem(KEY) || "{}") }; } catch { /* private mode: start empty */ }
  const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch { /* ignore */ } };

  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = "/static/bot.css";
  document.head.appendChild(css);

  const root = document.createElement("div");
  root.id = "dtcBot";
  root.innerHTML = `
    <button type="button" class="bot-fab" id="dtcbFab" aria-expanded="false" aria-controls="dtcbPanel" title="Ask the AI assistant">Ask AI</button>
    <div class="bot-panel" id="dtcbPanel" role="dialog" aria-label="AI assistant" hidden>
      <div class="bot-head">
        <div><b>AI assistant</b><span class="bot-sub">Reads your data · changes nothing</span></div>
        <div class="bot-actions">
          <button type="button" class="bot-link" id="dtcbNew" title="Start a new chat">New chat</button>
          <button type="button" class="bot-x" id="dtcbClose" aria-label="Close">×</button>
        </div>
      </div>
      <div class="bot-msgs" id="dtcbMsgs" aria-live="polite"></div>
      <form class="bot-form" id="dtcbForm">
        <textarea id="dtcbQ" rows="2" placeholder="e.g. Why did the part cost of 1023 go up?  ·  Which parts of project X are over target?" required></textarea>
        <button class="btn btn-primary" type="submit" id="dtcbSend">Send</button>
      </form>
      <p class="bot-foot">Answers come from your projects and rates. Check important numbers in the trace before you use them.</p>
    </div>`;
  document.body.appendChild(root);
  const $ = (id) => document.getElementById(id);

  // Small, safe markdown: everything is escaped first; links only to this app (paths starting with /).
  function inline(s) {
    return s
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/\[([^\]]+)\]\((\/(?!\/)[^)\s]*)\)/g, (_, t, u) => `<a href="${u}" target="_blank" rel="noopener">${t}</a>`);
  }
  function md(text) {
    const lines = esc(text).split("\n");
    let html = "", list = "", table = [];
    const flushList = () => { if (list) { html += `</${list}>`; list = ""; } };
    const flushTable = () => {
      if (!table.length) return;
      const rows = table.filter((r) => !/^\|?\s*:?-{2,}/.test(r));
      const cells = (r) => r.replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
      html += `<div class="bot-table"><table><thead><tr>${cells(rows[0]).map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>` +
        rows.slice(1).map((r) => `<tr>${cells(r).map((c) => `<td>${c}</td>`).join("")}</tr>`).join("") + "</tbody></table></div>";
      table = [];
    };
    for (const raw of lines) {
      const line = raw.trimEnd();
      if (/^\s*\|/.test(line)) { flushList(); table.push(line.trim()); continue; }
      flushTable();
      const bullet = line.match(/^\s*[-*]\s+(.*)/), num = line.match(/^\s*\d+[.)]\s+(.*)/);
      if (bullet || num) {
        const kind = bullet ? "ul" : "ol";
        if (list !== kind) { flushList(); html += `<${kind}>`; list = kind; }
        html += `<li>${inline((bullet || num)[1])}</li>`;
        continue;
      }
      flushList();
      const head = line.match(/^#{1,4}\s+(.*)/);
      if (head) html += `<p class="bot-h">${inline(head[1])}</p>`;
      else if (line.trim()) html += `<p>${inline(line)}</p>`;
    }
    flushList();
    flushTable();
    return html;
  }

  function render(pending) {
    const box = $("dtcbMsgs");
    if (!state.turns.length && !pending) {
      box.innerHTML = `<div class="bot-hello"><p><b>Ask about your parts, costs, tools and rates.</b></p>
        <ul><li>What is the part cost of <i>part code</i>, and what drives it?</li>
        <li>Compare tool cost in India and China for <i>part code</i>.</li>
        <li>Which parts of project <i>code</i> are over their target cost?</li>
        <li>Send me the tool drawing and PO pack of <i>part code</i>.</li></ul></div>`;
      return;
    }
    box.innerHTML = state.turns.map((t) => t.role === "user"
      ? `<div class="bot-msg me">${esc(t.text).replace(/\n/g, "<br>")}</div>`
      : `<div class="bot-msg ai${t.error ? " err" : ""}">${md(t.text)}${t.tools?.length
          ? `<div class="bot-tools">Looked at: ${[...new Set(t.tools.map((x) => LABELS[x.tool] || x.tool))].map(esc).join(", ")}</div>` : ""}</div>`).join("") +
      (pending ? `<div class="bot-msg ai wait"><span class="dot"></span><span class="dot"></span><span class="dot"></span> Looking it up…</div>` : "");
    box.scrollTop = box.scrollHeight;
  }

  function open(on) {
    state.open = on;
    save();
    $("dtcbPanel").hidden = !on;
    $("dtcbFab").hidden = on;
    $("dtcbFab").setAttribute("aria-expanded", String(on));
    if (on) { render(); $("dtcbQ").focus(); }
  }

  async function ask(q) {
    const history = state.turns.filter((t) => !t.error).map((t) => ({ role: t.role, text: t.text }));
    state.turns.push({ role: "user", text: q });
    save();
    render(true);
    $("dtcbSend").disabled = true;
    try {
      const res = await fetch("/api/bot/chat", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, history, page: location.pathname + location.search }) });
      const body = await res.json().catch(() => ({}));
      if (res.status === 401) location.href = "/login";
      if (!res.ok) throw new Error(body.detail || res.statusText);
      state.turns.push({ role: "assistant", text: body.reply, tools: body.tools });
    } catch (e) {
      state.turns.push({ role: "assistant", text: e.message || "Something went wrong.", error: true });
    }
    save();
    render();
    $("dtcbSend").disabled = false;
    $("dtcbQ").focus();
  }

  $("dtcbFab").addEventListener("click", () => open(true));
  $("dtcbClose").addEventListener("click", () => open(false));
  $("dtcbNew").addEventListener("click", () => { state.turns = []; save(); render(); $("dtcbQ").focus(); });
  $("dtcbForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("dtcbQ").value.trim();
    if (!q || $("dtcbSend").disabled) return;
    $("dtcbQ").value = "";
    ask(q);
  });
  $("dtcbQ").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("dtcbForm").requestSubmit(); }
  });
  root.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.open) open(false); });
  open(!!state.open);
})();
