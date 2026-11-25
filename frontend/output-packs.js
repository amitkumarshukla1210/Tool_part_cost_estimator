// Output packs page (stage 66): every part of your tool groups, its newest pack (progress, every output, the ZIP) and,
// on request, every earlier revision. While a pack runs the page asks again every 5 s.
(function () {
  const { $, esc, api } = window.DTC;
  const form = $("filters");
  let timer = null;
  const TYPES = { plastic: "Plastic mould", die_casting: "Die casting", foundry: "Foundry", sheet_metal: "Press parts", fin: "Fin press die",
    eps: "EPS", blow: "Blow moulding", machined: "Machined" };

  async function projects() {
    const list = await api("/api/projects").catch(() => []);
    form.project_id.insertAdjacentHTML("beforeend", list.map((p) => `<option value="${p.id}">${esc(p.code)} · ${esc(p.name)}</option>`).join(""));
  }

  async function load() {
    clearTimeout(timer);
    const qs = new URLSearchParams();
    if (form.project_id.value) qs.set("project_id", form.project_id.value);
    if (form.part_type.value) qs.set("part_type", form.part_type.value);
    try {
      const r = await api(`/api/output-packs?${qs}`);
      const q = form.q.value.trim().toLowerCase();
      const parts = r.parts.filter((p) => !q || `${p.part_code} ${p.name}`.toLowerCase().includes(q));
      const all = form.all.checked;
      const cols = r.columns;
      const body = parts.map((p) => {
        const packs = all ? p.packs : p.packs.slice(0, 1);
        const busy = window.OutputPacks.busy(p.packs);
        const partCell = `<a class="link" href="/parts?part=${p.id}"><b>${esc(p.part_code)}</b></a> · ${esc(p.name)}
          <div class="note">${esc(p.project)} · ${esc(TYPES[p.part_type] || p.part_type || "–")}${p.packs.length > 1 ? ` · ${p.packs.length} revisions` : ""}</div>
          <button type="button" class="btn btn-outline small op-start" data-part="${p.id}" ${busy ? "disabled" : ""}>${p.packs.length ? "New revision" : "Make output pack"}</button>`;
        if (!packs.length) {
          return `<tr><td>${partCell}</td><td colspan="${cols.length + 4}" class="note">No output pack yet.</td></tr>`;
        }
        return window.OutputPacks.rows(p.id, packs, cols, { partCell, all: true });
      }).join("");
      $("out").innerHTML = parts.length ? `<div class="table-wrap"><table class="cost-table pk-table">${window.OutputPacks.head(cols, true)}<tbody>${body}</tbody></table></div>`
        : '<p class="note">No part matches.</p>';
      if (r.parts.some((p) => window.OutputPacks.busy(p.packs))) timer = setTimeout(load, 5000);
    } catch (err) { $("out").innerHTML = `<p class="status error">${esc(err.message)}</p>`; }
  }

  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (t.classList.contains("op-start")) {
      t.disabled = true;
      try { await api(`/api/parts/${t.dataset.part}/output-packs`, { method: "POST", body: JSON.stringify({ force: true }) }); }
      catch (err) { window.DTC.status($("status"), err.message, "error"); }
      load();
    } else if (t.classList.contains("pk-stop")) {
      t.disabled = true;
      await api(`/api/parts/${t.dataset.part}/output-packs/${t.dataset.pack}/stop`, { method: "POST" }).catch(() => null);
      load();
    }
  });
  form.addEventListener("change", load);
  form.addEventListener("input", (e) => { if (e.target.name === "q") load(); });
  form.addEventListener("submit", (e) => { e.preventDefault(); load(); });
  projects().then(load);
})();
