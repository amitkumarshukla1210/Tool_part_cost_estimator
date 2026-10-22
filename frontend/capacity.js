// Capacity validation 0 to 3000 t and the free-software list (roadmap stage 20).
const { $, esc, fmt, api, status } = window.DTC;

const tile = (label, value, sub, alert = false) =>
  `<div class="card tile ${alert ? "alert" : ""}"><div class="label">${esc(label)}</div><div class="value">${value}</div><div class="sub">${esc(sub)}</div></div>`;
const table = (heads, rows) =>
  `<div class="table-wrap"><table class="cost-table"><thead><tr>${heads.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
const mark = (ok) => (ok ? "✔" : '<b style="color:var(--danger)">✘</b>');

function summarise(rows, keyFn, cols) {
  // compact view: one line per material / process with the worst case first
  const groups = new Map();
  rows.forEach((r) => groups.set(keyFn(r), [...(groups.get(keyFn(r)) || []), r]));
  return [...groups.entries()].map(([k, list]) => {
    const bad = list.filter((r) => !r.ok);
    return `<tr><td>${esc(k)}</td><td class="num">${list.length}</td><td class="num">${list.length - bad.length}</td>
      <td>${bad.length ? `<span style="color:var(--danger)">${esc(bad[0].problem)} (${bad[0].target_t} t)</span>` : "all pass"}</td>
      <td class="num">${cols(list)}</td></tr>`;
  });
}

async function run(e) {
  e?.preventDefault();
  status($("status"), "Running: this takes about 30 seconds…");
  try {
    const r = await api(`/api/capacity/validation?step_t=${$("step").value || 250}`);
    status($("status"), "");
    $("tiles").innerHTML =
      tile("Result", r.ok ? "✔ all pass" : "✘ gaps found", `${r.totals.cases} checks, ${r.totals.failed} failed`, !r.ok) +
      tile("Machines", fmt(r.coverage.machine_count), "injection, die casting and press machines") +
      tile("Mould bases / die holders", fmt(r.coverage.mould_base_count), "standard sizes in the database") +
      tile("Largest tonnage checked", `${fmt(r.max_t)} t`, "all three machine ladders reach it", false);
    $("limits").innerHTML = table(["Process", "Largest machine", "Tonnage (t)", "Reaches 3000 t", "Note"],
      r.limits.map((l) => `<tr><td>${esc(l.process)}</td><td>${esc(l.machine)}</td><td class="num">${fmt(l.max_t)}</td><td>${mark(l.reaches_3000t)}</td><td>${esc(l.note)}</td></tr>`));
    $("coverage").innerHTML = (r.coverage.gaps.length ? `<ul>${r.coverage.gaps.map((g) => `<li>${esc(g)}</li>`).join("")}</ul>` : "") +
      table(["Process", "Required (t)", "Machine", "Machine (t)", "Mould base / die holder", "Countries with a machine price"],
        r.coverage.rows.map((x) => `<tr><td>${esc(x.process)}</td><td class="num">${fmt(x.required_t)}</td><td>${esc(x.machine || "none")}</td><td class="num">${fmt(x.machine_t)}</td>
          <td>${esc(x.base || "-")}</td><td class="num">${x.rate_countries}</td></tr>`));
    const head = ["Part type · material", "Cases", "Pass", "First problem", "Largest tool cost (INR)"];
    $("designs").innerHTML = table(head, summarise(r.designs.rows, (x) => `${x.part_type} · ${x.material}`,
      (l) => fmt(Math.max(...l.map((x) => x.tool_cost_inr || 0)))));
    $("sheet").innerHTML = table(["Material", "Cases", "Pass", "First problem", "Largest press used (t)"], summarise(r.sheet.rows, (x) => x.material,
      (l) => fmt(Math.max(...l.map((x) => x.press_t || 0)))));
  } catch (err) {
    status($("status"), err.message, "error");
  }
}

async function software() {
  const list = await api("/api/free-software").catch(() => []);
  $("software").innerHTML = table(["Tool", "Used for", "Group", "Licence", "Status", "Install"], list.map((s) =>
    `<tr><td><b>${esc(s.name)}</b>${s.required ? "" : ' <span class="note">(optional)</span>'}</td><td>${esc(s.used_for)}</td><td>${esc(s.group)}</td><td>${esc(s.licence)}</td>
     <td>${s.installed ? `✔ ${esc(s.version || "installed")}` : s.required ? '<b style="color:var(--danger)">missing</b>' : "not installed"}${!s.installed && s.location ? `<br/><span class="note">${esc(s.location)}</span>` : ""}</td>
     <td><code>${esc(s.install)}</code></td></tr>`));
}

$("runForm").addEventListener("submit", run);
software();
run();
