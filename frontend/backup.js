// Backup page: make, download, upload and restore backups; shows the version.
const { $, esc, fmt, api, status } = window.DTC;

async function load() {
  $("version").textContent = (await api("/api/version")).version;
  const rows = await api("/api/backups");
  $("list").innerHTML = `<thead><tr><th>Backup</th><th>Created</th><th class="num">Size (MB)</th><th>Files (master data / data / storage)</th><th></th></tr></thead><tbody>` +
    (rows.length ? rows.map((b) => `<tr><td>${esc(b.name)}</td><td>${esc(b.created.replace("T", " "))}</td><td class="calc num">${fmt(b.bytes / 1e6, 1)}</td>
      <td>${b.files.master_data ?? 0} / ${b.files.data ?? 0} / ${b.files.storage ?? 0}</td>
      <td><a class="btn btn-outline btn-small" href="/api/backups/${encodeURIComponent(b.name)}">Download</a>
      <button type="button" class="btn btn-outline btn-danger btn-small" data-restore="${esc(b.name)}">Restore</button></td></tr>`).join("")
      : '<tr><td colspan="5" class="empty">No backup yet. Press “Back up now”.</td></tr>') + "</tbody>";
}

$("make").addEventListener("click", async () => {
  try {
    status($("status"), "Backing up …");
    const b = await api("/api/backups", { method: "POST", body: "{}" });
    status($("status"), `Backup ${b.name} written (${fmt(b.bytes / 1e6, 1)} MB). Download it and keep a copy outside this computer.`, "ok");
    await load();
  } catch (e) { status($("status"), e.message, "error"); }
});

$("upFile").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  try {
    const b = await api("/api/backups/upload", { method: "POST", body: fd });
    status($("status"), `Uploaded as ${b.name}. Press Restore to put it back.`, "ok");
    await load();
  } catch (err) { status($("status"), err.message, "error"); }
  e.target.value = "";
});

document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-restore]");
  if (!b) return;
  const name = b.dataset.restore;
  if (!confirm(`Restore ${name}?\n\nYour projects, CAD files and master data are replaced by what is in this backup. What is there now is saved first as a safety backup.`)) return;
  try {
    const r = await api("/api/backups/restore", { method: "POST", body: JSON.stringify({ name }) });
    status($("status"), `Restored (${Object.entries(r.restored).map(([k, v]) => `${k}: ${v} files`).join(", ")}). Safety backup: ${r.safety_backup.split(/[\\/]/).pop()}. ${r.note}`, "ok");
    await load();
  } catch (err) { status($("status"), err.message, "error"); }
});

load().catch((e) => status($("status"), e.message, "error"));
