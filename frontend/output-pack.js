// Output packs (stage 66): the table of every output of a part, one row per pack revision, shared by the part panel and the
// Output packs page. The pack is made by the app in the background: closing the window does not stop it.
window.OutputPacks = (function () {
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const KIND = { pdf: "PDF", xlsx: "Excel", zip: "ZIP", dxf: "DXF", step: "STEP", stp: "STEP", stl: "STL", html: "3D viewer",
    mp4: "Video", gif: "Video", png: "Picture", csv: "CSV" };
  const kindOf = (name) => KIND[(String(name).split(".").pop() || "").toLowerCase()] || "File";
  const kb = (b) => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} kB`);
  const when = (t) => (t ? String(t).slice(0, 16).replace("T", " ") : "");

  // one line per output (label + its files: "Tool drawing  PDF DXF"); jobs (simulation, FEA) show ✓ when done
  const base = (label) => String(label).replace(/\s*\([^)]*\)\s*$/, "");
  function cell(pid, p, items) {
    if (!items || !items.length) return '<span class="note">–</span>';
    const lines = new Map();
    for (const it of items) {
      const files = it.files || (it.file_id ? [it] : []);
      let html = "";
      if (files.length) {
        html = files.map((f, k) => `<a class="pk-link" title="${esc((f.label || it.label) + " · " + f.filename + " · " + kb(f.size || 0))}"
          href="/api/parts/${pid}/output-packs/${p.id}/items/${it.n}${files.length > 1 ? `?k=${k}` : ""}">${esc(kindOf(f.filename))}</a>`).join("");
      } else if (it.kind === "job") {
        html = it.reused ? `<span class="pk-ok" title="${esc(it.note || "")}">✓ ${esc(it.reused)}</span>` : { done: '<span class="pk-ok">✓</span>', running: '<span class="note">…</span>', waiting: "" }[it.status]
          ?? `<span class="pk-na" title="${esc(it.reason || it.status)}">${it.status === "failed" ? "failed" : "n/a"}</span>`;
      } else if (it.status === "running") html = '<span class="note">…</span>';
      else if (it.status !== "waiting") html = `<span class="pk-na" title="${esc(it.label + ": " + (it.reason || it.status))}">${it.status === "failed" ? "failed" : "n/a"}</span>`;
      const key = it.kind === "job" ? it.label : base(it.label);
      lines.set(key, (lines.get(key) || "") + html);
    }
    const out = [...lines].filter(([, h]) => h).map(([k, h]) => `<div class="pk-item"><span class="pk-base">${esc(k)}</span> ${h}</div>`).join("");
    return out || '<span class="note">…</span>';
  }

  function progress(p) {
    const pct = Math.round(p.progress || 0);
    const run = p.status === "running" || p.status === "queued";
    const word = p.status === "done" ? "Yes · 100 %" : run ? `${pct} %` : `${p.status} · ${pct} %`;
    return `<div class="pk-bar${run ? " run" : ""}${p.status === "done" ? " ok" : ""}"><span style="width:${pct}%"></span></div>
      <div class="pk-word">${esc(word)}</div>${run ? `<div class="note">${esc(p.step || "")}</div>` : p.status === "failed" ? `<div class="status error">${esc(p.error || "")}</div>` : ""}`;
  }

  function rows(pid, packs, cols, opts = {}) {
    return packs.map((p, i) => `<tr${i && !opts.all ? ' class="muted"' : ""}>
        ${opts.partCell ? `<td>${i ? "" : opts.partCell}</td>` : ""}
        <td><b>${esc(p.rev)}</b><div class="note">${esc(when(p.created_at))}<br/>${esc(p.created_by)}${p.auto ? " · auto" : ""}</div>
          ${p.changed && p.changed !== "first pack" ? `<div class="note" title="What changed">${esc(p.changed)}</div>` : ""}</td>
        <td>${esc(p.design_stage || "")}</td>
        <td class="pk-prog">${progress(p)}${p.status === "running" || p.status === "queued" ? ` <button type="button" class="btn btn-outline small pk-stop" data-part="${pid}" data-pack="${p.id}">Stop</button>` : ""}</td>
        ${cols.map((c) => `<td>${cell(pid, p, (p.groups || {})[c.key])}</td>`).join("")}
        <td>${p.zip_file_id ? `<a class="btn ${p.zip_stage === "quick" ? "btn-outline" : "btn-primary"} small" href="/api/parts/${pid}/output-packs/${p.id}/pack.zip" title="${esc(p.zip_name)}">⬇ ZIP</a>
          <div class="note">${kb(p.zip_size || 0)}${p.zip_stage === "quick" ? "<br/>files only: simulation and FEA still running" : ""}</div>` : ""}</td>
      </tr>`).join("");
  }

  function head(cols, partCol) {
    return `<thead><tr>${partCol ? "<th>Part</th>" : ""}<th>Revision</th><th>Stage</th><th>Progress</th>${cols.map((c) => `<th>${esc(c.label)}</th>`).join("")}<th>All in one ZIP</th></tr></thead>`;
  }

  // the part panel block
  function panelHtml(o) {
    const latest = o.packs[0];
    const busy = latest && (latest.status === "running" || latest.status === "queued");
    return `<p class="note">Every output of this part (tool design pack, 2D, 3D, strip layout, simulation, FEA, costs of all countries, BOM, PO pack)
        in one ZIP, made by the app in the background: you may close this window, the progress stays here. Each revision is kept.</p>
      <div class="toolbar" style="gap:12px;align-items:center;flex-wrap:wrap">
        <button type="button" class="btn btn-primary small" id="pkStart" ${busy ? "disabled" : ""}>${latest ? "Make a new revision now" : "Make output pack (one click, all outputs)"}</button>
        <span class="pk-auto"><input type="checkbox" id="pkAuto" ${o.auto ? "checked" : ""}/> <label for="pkAuto">Auto: a saved change of the part makes the
          next revision (after it has not changed for 2 min)</label></span>
        ${o.out_of_date ? `<span class="badge missing">Out of date: the part changed${o.auto && o.auto_in_s != null ? `, next revision in ~${o.auto_in_s} s` : ""}</span>` : ""}
        <span class="status" id="pkStatus"></span></div>
      ${o.packs.length ? `<div class="table-wrap"><table class="cost-table pk-table">${head(o.columns)}<tbody>${rows(o.part_id, o.packs, o.columns)}</tbody></table></div>`
        : '<p class="note">No output pack yet.</p>'}`;
  }

  return { panelHtml, rows, head, kindOf, busy: (packs) => packs.some((p) => p.status === "running" || p.status === "queued") };
})();
