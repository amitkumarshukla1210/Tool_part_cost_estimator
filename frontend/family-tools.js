// Family tools page (stage 68): list, create / change a family (2-4 parts), calculate it, share % and the switch per part,
// common / per-part ticks of the BOM lines, downloads (layout + split PDF, tool cost PDF / Excel, pack ZIP) and versions.
(function () {
  const { $, esc, fmt, api, status } = window.DTC;
  const form = $("famForm");
  const MODES = { plastic: ["same_shot"], eps: ["same_shot"], die_casting: ["same_shot"], blow: ["same_shot"], foundry: ["same_shot"],
    sheet_metal: ["same_shot", "swap_inserts"] };
  const MODE_LABEL = { same_shot: "Same shot / same stroke (all parts every shot)", swap_inserts: "Common die set, swap inserts" };
  const TYPE_LABEL = { plastic: "Plastic mould", eps: "EPS mould", die_casting: "Die casting", blow: "Blow moulding", foundry: "Foundry",
    sheet_metal: "Sheet metal die" };
  const lakh = (v) => (v == null ? "—" : `₹ ${fmt(v / 1e5, 2)} lakh`);
  let editing = null;      // the family open in the form / detail
  let cands = [];

  async function loadList() {
    try {
      const list = await api("/api/families");
      $("listBox").innerHTML = list.length ? `<div class="table-wrap"><table class="cost-table"><thead><tr><th>Code</th><th>Name</th>
        <th>Tool type</th><th>Mode</th><th>Parts</th><th class="num">Tool cost (latest)</th><th class="num">CAPEX (latest)</th><th></th></tr></thead><tbody>
        ${list.map((f) => `<tr class="clickable${editing && editing.id === f.id ? " selected" : ""}" data-open="${f.id}"><td><b>${esc(f.code)}</b></td>
          <td>${esc(f.name)}</td><td>${esc(TYPE_LABEL[f.part_type] || f.part_type)}</td><td>${esc(MODE_LABEL[f.mode] || f.mode)}</td>
          <td>${(f.members || []).map((m) => esc(m.part_code)).join(", ")}</td>
          <td class="num">${f.latest ? lakh(f.latest.tool_cost_inr) + ` <span class="note">v${f.latest.version}</span>` : '<span class="note">not calculated</span>'}</td>
          <td class="num">${f.latest ? lakh(f.latest.tool_capex_inr) : "—"}</td>
          <td><button type="button" class="btn btn-outline small" data-open="${f.id}">Open</button></td></tr>`).join("")}</tbody></table></div>`
        : '<p class="note">No family tool yet. Make the first one below.</p>';
    } catch (err) { $("listBox").innerHTML = `<p class="status error">${esc(err.message)}</p>`; }
  }

  function modes() {
    const pt = form.part_type.value;
    const cur = form.mode.value;
    form.mode.innerHTML = MODES[pt].map((m) => `<option value="${m}" ${m === cur ? "selected" : ""}>${esc(MODE_LABEL[m])}</option>`).join("");
  }

  async function loadCands() {
    cands = await api(`/api/families/candidates?part_type=${form.part_type.value}`).catch(() => []);
  }

  function memberRows(members = []) {
    const rows = [];
    for (let i = 0; i < 4; i++) {
      const m = members[i] || {};
      const opts = cands.filter((c) => !c.family_id || (editing && c.family_id === editing.id))
        .map((c) => `<option value="${c.id}" ${String(c.id) === String(m.part_id || "") ? "selected" : ""}>${esc(c.part_code)} · ${esc(c.name)}${c.material ? " · " + esc(c.material) : ""}</option>`).join("");
      rows.push(`<tr><td>${i + 1}</td><td><select name="part_${i}"><option value="">${i < 2 ? "— choose a part —" : "— none —"}</option>${opts}</select></td>
        <td class="num"><input name="cav_${i}" type="number" min="1" max="64" step="1" style="width:70px" value="${m.cavities ?? ""}" ${form.part_type.value === "sheet_metal" ? "disabled" : ""} /></td>
        <td class="num"><input name="pct_${i}" type="number" min="0" max="100" step="0.01" style="width:90px" value="${m.share_pct ?? ""}" /></td></tr>`);
    }
    $("memberRows").innerHTML = rows.join("");
  }

  async function fresh(f = null) {
    editing = f;
    $("formTitle").textContent = f ? `Change family tool ${f.code}` : "New family tool";
    form.code.value = f?.code || "";
    form.name.value = f?.name || "";
    form.country.value = f?.country || "";
    form.part_type.value = f?.part_type || form.part_type.value || "plastic";
    form.part_type.disabled = !!f;
    modes();
    if (f) form.mode.value = f.mode;
    await loadCands();
    memberRows(f?.members || []);
    status($("formStatus"), "");
  }

  function body() {
    const members = [];
    for (let i = 0; i < 4; i++) {
      const pid = form[`part_${i}`].value;
      if (!pid) continue;
      const old = (editing?.members || []).find((m) => String(m.part_id) === pid);
      members.push({ part_id: Number(pid), cavities: form[`cav_${i}`].value ? Number(form[`cav_${i}`].value) : null,
        share_pct: form[`pct_${i}`].value === "" ? null : Number(form[`pct_${i}`].value), use_family: old ? old.use_family !== false : true });
    }
    return { code: form.code.value.trim(), name: form.name.value.trim(), mode: form.mode.value, country: form.country.value.trim(), members };
  }

  async function open(id) {
    const f = await api(`/api/families/${id}`);
    await fresh(f);
    loadList();
    detail(f);
  }

  async function detail(f) {
    const box = $("detail");
    box.innerHTML = `<div class="card"><p class="note">Working out family tool ${esc(f.code)} (each part's tool engine, then the family)…</p></div>`;
    let st;
    try { st = await api(`/api/families/${f.id}/status`); }
    catch (err) { box.innerHTML = `<div class="card"><p class="status error">${esc(err.message)}</p></div>`; return; }
    const lv = st.live, v = st.latest;
    let html = `<div class="card"><h3 class="block-title" style="margin-top:0">${esc(f.code)} · ${esc(f.name || "")}
      <span class="note">${esc(TYPE_LABEL[f.part_type] || f.part_type)} · ${esc(MODE_LABEL[f.mode])}</span></h3>`;
    if (lv?.example?.any) html += window.exampleBanner(esc(lv.example.detail));
    if (st.problem) html += `<p class="warn">${esc(st.problem)}</p>`;
    if (st.outdated) html += `<p class="warn">${esc(st.outdated)}</p>`;
    (lv?.warnings || []).forEach((w) => { html += `<p class="warn">${esc(w)}</p>`; });
    if (lv) {
      html += `<p><b>Family tool (live): ${lakh(lv.value_inr)} per tool · CAPEX ${lakh(lv.capex_inr)}</b>
        (${fmt(lv.value, 0)} ${esc(lv.currency)} · ${esc(lv.country)} · ${esc(lv.as_of)} · base ${esc(lv.base.series)} ${esc(lv.base.size_code)}
        · ${lv.tools_count} tool(s) over the programme)` +
        `</p>` + (lv.saving_capex_inr != null ? `<p><b>CAPEX ${lv.saving_capex_inr >= 0 ? "saving" : "extra"} vs one own tool per part (their own cavities): ${lakh(Math.abs(lv.saving_capex_inr))}</b></p>` : "");
      html += `<div class="table-wrap"><table class="cost-table"><thead><tr><th>Part</th><th class="num">Cavities</th><th class="num">Weight (g)</th>
        <th class="num">Share %</th><th class="num">Share of tool cost</th><th class="num">Share of CAPEX</th><th class="num">Own tool CAPEX</th>
        <th>Part cost &amp; CAPEX use</th></tr></thead><tbody>${lv.shares.map((s) => `<tr><td><a class="link" href="/parts?part=${s.part_id}"><b>${esc(s.part_code)}</b></a> · ${esc(s.name)}</td>
        <td class="num">${s.cavities}</td><td class="num">${fmt(s.weight_g, 1)}</td><td class="num">${fmt(s.pct, 2)}${s.typed ? " <span class='note'>typed</span>" : ""}</td>
        <td class="num">${lakh(s.cost_inr)}</td><td class="num">${lakh(s.capex_inr)}</td>
        <td class="num">${s.own ? lakh(s.own.capex_inr) + ` <span class="note">${s.own.cavities} cav</span>` : "—"}</td>
        <td><label class="choice"><input type="radio" name="use_${s.part_id}" data-use="${s.part_id}" value="1" ${s.use_family ? "checked" : ""}/> family tool</label>
            <label class="choice"><input type="radio" name="use_${s.part_id}" data-use="${s.part_id}" value="0" ${s.use_family ? "" : "checked"}/> own tool</label></td></tr>`).join("")}
        </tbody></table></div>`;
      const lines = lv.lines.filter((l) => !l.family_base && (l.line_key || l.family_key));
      const seen = new Map();
      lines.forEach((l) => { const k = l.line_key || l.family_key; if (!seen.has(k)) seen.set(k, { key: k, l, rows: [] }); seen.get(k).rows.push(l); });
      html += `<details class="card" style="margin-top:12px" ${f.mode === "swap_inserts" ? "open" : ""}><summary><b>BOM lines: common or per part</b>
        <span class="note">(common = counted once at the largest part's value; per part = counted for every part.
        ${f.mode === "swap_inserts" ? "Swap inserts: every line starts common – tick the lines each part needs of its own (inserts, changed stations)." : "Same shot: the parts' lines start per part; tick a line common when one serves every part."})</span></summary>
        <div class="table-wrap"><table class="cost-table"><thead><tr><th>Common</th><th>BOM line</th><th>Parts</th><th class="num">Counted (INR)</th></tr></thead><tbody>
        ${[...seen.values()].map((g) => { const common = g.rows.some((r) => r.common);
          const parts = g.rows.map((r) => r.member).concat(...g.rows.map((r) => (r.dropped || []).map((d) => d.member + " (not counted)")));
          return `<tr><td><input type="checkbox" data-common="${esc(g.key)}" ${common ? "checked" : ""}/></td><td>${esc((g.l.die ? g.l.die + " · " : "") + g.l.element)}</td>
          <td class="note">${parts.map(esc).join(", ")}</td><td class="num">${fmt(g.rows.reduce((a, r) => a + r.total, 0), 0)}</td></tr>`; }).join("")}
        </tbody></table></div><button type="button" class="btn btn-outline small" id="saveCommon">Save ticks</button> <span class="status" id="commonStatus"></span></details>`;
    }
    html += `<div class="toolbar" style="padding:12px 0 0"><button type="button" class="btn" id="famCalc" ${st.problem ? "disabled" : ""}>Calculate &amp; store version</button>
      <a class="btn btn-outline small" href="/api/families/${f.id}/layout.pdf">Layout &amp; split (PDF)</a>
      <a class="btn btn-outline small" href="/api/families/${f.id}/export.pdf">Tool cost (PDF)</a>
      <a class="btn btn-outline small" href="/api/families/${f.id}/export.xlsx">Tool cost (Excel)</a>
      <a class="btn btn-outline small" href="/api/families/${f.id}/pack.zip">Family pack (ZIP)</a>
      <span class="spacer"></span><button type="button" class="btn btn-outline small" id="famDelete">Delete family tool</button>
      <span class="status" id="calcStatus"></span></div>
      <p class="note">Downloads use the latest stored version (or the live preview before the first one).</p>`;
    if (f.versions.length) {
      html += `<h4>Versions</h4><div class="table-wrap"><table class="cost-table"><thead><tr><th>Version</th><th>Month</th><th class="num">Tool cost</th>
        <th class="num">CAPEX</th><th>Shares</th><th>By</th><th>When</th><th></th></tr></thead><tbody>${f.versions.map((x) => `<tr><td>${x.version}</td><td>${esc(x.as_of)}</td>
        <td class="num">${lakh(x.tool_cost_inr)}</td><td class="num">${lakh(x.tool_capex_inr)}</td>
        <td class="note">${(x.shares || []).map((s) => `${esc(s.part_code)} ${fmt(s.pct, 1)} %`).join(", ")}</td><td>${esc(x.created_by)}</td><td>${esc(x.created_at)}</td>
        <td><a class="link" href="/api/families/${f.id}/export.pdf?version=${x.version}">PDF</a> · <a class="link" href="/api/families/${f.id}/export.xlsx?version=${x.version}">Excel</a></td></tr>`).join("")}</tbody></table></div>`;
    }
    box.innerHTML = html + "</div>";
  }

  form.part_type.addEventListener("change", async () => { modes(); await loadCands(); memberRows(); });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    $("famSave").disabled = true;
    try {
      const f = await api(editing ? `/api/families/${editing.id}` : "/api/families", { method: editing ? "PUT" : "POST", body: JSON.stringify(body()) });
      status($("formStatus"), "Saved.", "ok");
      await open(f.id);
    } catch (err) { status($("formStatus"), err.message, "error"); }
    $("famSave").disabled = false;
  });
  $("famNew").addEventListener("click", () => { fresh(null); $("detail").innerHTML = ""; loadList(); });

  document.addEventListener("click", async (e) => {
    const t = e.target.closest("[data-open]") || e.target;
    if (t.dataset?.open) return open(t.dataset.open);
    if (e.target.id === "famCalc" && editing) {
      e.target.disabled = true;
      status($("calcStatus"), "Calculating…");
      try {
        const r = await api(`/api/families/${editing.id}/calculate`, { method: "POST", body: "{}" });
        status($("calcStatus"), r.message, "ok");
        await open(editing.id);
      } catch (err) { status($("calcStatus"), err.message, "error"); e.target.disabled = false; }
    } else if (e.target.id === "famDelete" && editing) {
      if (!confirm(`Delete family tool ${editing.code}? Its parts use their own tools again.`)) return;
      await api(`/api/families/${editing.id}`, { method: "DELETE" });
      fresh(null); $("detail").innerHTML = ""; loadList();
    } else if (e.target.id === "saveCommon" && editing) {
      const common = { ...(editing.common || {}) };
      document.querySelectorAll("[data-common]").forEach((c) => { common[c.dataset.common] = c.checked; });
      try { await api(`/api/families/${editing.id}`, { method: "PUT", body: JSON.stringify({ common }) }); await open(editing.id); }
      catch (err) { status($("commonStatus"), err.message, "error"); }
    }
  });
  document.addEventListener("change", async (e) => {
    const pid = e.target.dataset?.use;
    if (!pid || !editing) return;
    try { await api(`/api/families/${editing.id}/parts/${pid}/use`, { method: "PUT", body: JSON.stringify({ use_family: e.target.value === "1" }) }); }
    catch (err) { status($("calcStatus"), err.message, "error"); }
    open(editing.id);
  });

  fresh(null).then(() => {
    loadList();
    const id = new URLSearchParams(location.search).get("id");
    if (id) open(id);
  });
})();
