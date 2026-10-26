// Admin control: login IDs and roles, permissions per role, activity log, backups and installed version.
const { $, esc, api, status } = window.DTC;
const ROLE_HELP = {
  viewer: "viewer: reads everything, changes nothing",
  engineer: "engineer: + projects, parts, costs, imports, master data, rate drafts, suppliers (default permissions)",
  approver: "approver: + approves rates, sees the activity log",
  admin: "admin: + creates IDs, sets permissions, deletes projects, backups",
};
let info = null;          // {roles, permissions, me, mine}
let activityRows = [];
let activityTotal = 0;

async function init() {
  info = await api("/api/admin/permissions");
  const me = info.me;
  const isAdmin = !me || me.role === "admin";            // no user = logins off (tests / developers)
  $("whoami").textContent = me ? `Logged in as ${me.name || me.username} (${me.role})` : "Logins are off (DTC_MODE=local)";
  $("usersAdmin").hidden = !isAdmin;
  $("usersNoAdmin").hidden = isAdmin;
  $("newRole").innerHTML = info.roles.map((r) => `<option ${r === "engineer" ? "selected" : ""}>${r}</option>`).join("");
  $("roleHelp").textContent = ROLE_HELP.engineer;
  const tabOk = { users: true, perms: true, activity: info.mine.view_activity, backups: info.mine.backups, drawings: true };
  document.querySelectorAll("#tabs [data-tab]").forEach((b) => (b.hidden = !tabOk[b.dataset.tab]));
  $("permsActions").hidden = !isAdmin;
  const want = new URLSearchParams(location.search).get("tab");
  show(want && tabOk[want] ? want : "users");
  if (isAdmin) loadUsers();
}

function show(tab) {
  document.querySelectorAll("#tabs [data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  document.querySelectorAll(".tab-pane").forEach((p) => (p.hidden = p.id !== `tab-${tab}`));
  history.replaceState(null, "", `?tab=${tab}`);
  status($("status"), "");
  ({ perms: renderPerms, activity: () => loadActivity(false), backups: loadBackups, drawings: loadDrawing })[tab]?.();
}
$("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-tab]");
  if (b) show(b.dataset.tab);
});

// ---------- users ----------
async function loadUsers() {
  const users = await api("/api/users");
  $("users").innerHTML = `<thead><tr><th>User ID</th><th>Full name</th><th>Role</th><th>Active</th><th>Last login</th>
    <th>New password</th><th></th></tr></thead><tbody>${users.map((u) => `<tr data-id="${u.id}">
    <td><b>${esc(u.username)}</b></td><td><input data-f="name" value="${esc(u.name)}" /></td>
    <td><select data-f="role">${info.roles.map((r) => `<option ${r === u.role ? "selected" : ""}>${r}</option>`).join("")}</select></td>
    <td><label class="flag"><input type="checkbox" data-f="active" ${u.active ? "checked" : ""} />${u.active ? "active" : "blocked"}</label></td>
    <td>${esc((u.last_login || "—").replace("T", " "))}</td>
    <td><input type="password" data-f="password" placeholder="leave empty" autocomplete="new-password" minlength="10" /></td>
    <td><button class="btn btn-outline small" data-save type="button">Save</button></td></tr>`).join("")}</tbody>`;
}
$("newRole").addEventListener("change", (e) => ($("roleHelp").textContent = ROLE_HELP[e.target.value] || ""));
$("users").addEventListener("click", async (e) => {
  if (!e.target.matches("[data-save]")) return;
  const tr = e.target.closest("tr"), data = {};
  tr.querySelectorAll("[data-f]").forEach((el) => { data[el.dataset.f] = el.type === "checkbox" ? el.checked : el.value; });
  if (!data.password) delete data.password;
  try {
    await api(`/api/users/${tr.dataset.id}`, { method: "PUT", body: JSON.stringify(data) });
    status($("status"), "Saved.", "ok");
    loadUsers();
  } catch (err) {
    status($("status"), err.message, "error");
  }
});
$("newUser").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const u = await api("/api/users", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(e.target))) });
    e.target.reset();
    $("roleHelp").textContent = ROLE_HELP.engineer;
    status($("status"), `ID '${u.username}' created with the role ${u.role}. Give the user the ID and first password; they can change it on Admin.`, "ok");
    loadUsers();
  } catch (err) {
    status($("status"), err.message, "error");
  }
});
$("pwForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/auth/password", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(e.target))) });
    e.target.reset();
    status($("status"), "Password changed. Log in again on other devices.", "ok");
  } catch (err) {
    status($("status"), err.message, "error");
  }
});

// ---------- permissions ----------
function renderPerms(rows = info.permissions) {
  const editable = !$("permsActions").hidden;
  $("perms").innerHTML = `<thead><tr><th>Action</th><th>What it covers</th><th>Lowest role</th><th>Default</th><th>Changed by</th></tr></thead><tbody>${
    rows.map((p) => `<tr><td><b>${esc(p.label)}</b></td><td>${esc(p.covers)}</td>
    <td>${editable ? `<select data-action="${esc(p.action)}">${info.roles.map((r) => `<option ${r === p.min_role ? "selected" : ""}>${r}</option>`).join("")}</select>` : esc(p.min_role)}</td>
    <td>${esc(p.default)}${p.min_role !== p.default ? ' <span class="badge missing">changed</span>' : ""}</td>
    <td>${esc(p.updated_by ? `${p.updated_by} · ${p.updated_at.replace("T", " ")}` : "—")}</td></tr>`).join("")}
    <tr><td><b>Manage users &amp; permissions</b></td><td>Create login IDs, roles, block users, reset passwords, this table</td><td>admin</td><td>admin (fixed)</td><td>—</td></tr></tbody>`;
}
$("permsDefault").addEventListener("click", () => renderPerms(info.permissions.map((p) => ({ ...p, min_role: p.default }))));
$("permsSave").addEventListener("click", async () => {
  const permissions = [...document.querySelectorAll("#perms select[data-action]")].map((s) => ({ action: s.dataset.action, min_role: s.value }));
  try {
    await api("/api/admin/permissions", { method: "PUT", body: JSON.stringify({ permissions }) });
    info = await api("/api/admin/permissions");
    renderPerms();
    status($("status"), "Permissions saved. They apply from the next click of every user.", "ok");
  } catch (err) {
    status($("status"), err.message, "error");
  }
});

// ---------- activity log ----------
const ACTION_TEXT = { created: "created", updated: "changed", deleted: "deleted", saved: "saved", status_changed: "status changed",
  revision_added: "new revision", approved: "approved" };
function actQuery(offset = 0) {
  const f = Object.fromEntries([...new FormData($("actFilter")).entries()].filter(([, v]) => v));
  return new URLSearchParams({ ...f, offset, limit: 200 }).toString();
}
async function loadActivity(more) {
  try {
    const r = await api(`/api/admin/activity?${actQuery(more ? activityRows.length : 0)}`);
    activityRows = more ? activityRows.concat(r.rows) : r.rows;
    activityTotal = r.total;
    const sel = $("actEntity"), cur = sel.value;
    sel.innerHTML = '<option value="">everything</option>' + r.entities.map((x) => `<option ${x === cur ? "selected" : ""}>${esc(x)}</option>`).join("");
    $("actXlsx").href = `/api/admin/activity.xlsx?${actQuery()}`;
    $("actCount").textContent = `${activityTotal} record(s)` + (activityTotal > activityRows.length ? `, showing the newest ${activityRows.length}` : "");
    $("actMore").hidden = activityTotal <= activityRows.length;
    $("activity").innerHTML = `<thead><tr><th>When</th><th>Who</th><th>What</th><th>Which</th><th>Action</th><th>Details</th></tr></thead><tbody>${
      activityRows.map((a) => `<tr><td>${esc(a.at.replace("T", " "))}</td><td>${esc(a.user)}</td><td>${esc(a.entity)}</td>
      <td><b>${esc(a.name)}</b></td><td>${esc(ACTION_TEXT[a.action] || a.action.replace(/_/g, " "))}</td><td class="wrap">${esc(a.summary)}</td></tr>`).join("")
      || '<tr><td colspan="6" class="empty">Nothing recorded for these filters.</td></tr>'}</tbody>`;
  } catch (err) {
    status($("status"), err.message, "error");
  }
}
$("actFilter").addEventListener("submit", (e) => { e.preventDefault(); loadActivity(false); });
$("actMore").addEventListener("click", () => loadActivity(true));

// ---------- backups & version ----------
async function loadBackups() {
  try {
    const [b, a] = await Promise.all([api("/api/admin/backups"), api("/api/admin/about")]);
    const v = a.version || {};
    $("about").innerHTML = `<table class="cost-table"><tbody>
      <tr><td>Version</td><td><b>${esc(a.release || "—")}</b> · ${esc(v.commit || v.zip || "—")}</td></tr>
      <tr><td>Installed</td><td>${esc((v.installed || "—").replace("T", " "))}</td></tr>
      <tr><td>Data folder</td><td>${esc(a.data_folder || b.locations.data)}</td></tr>
      <tr><td>Database</td><td>${esc(a.database)}</td></tr>
      <tr><td>Logins</td><td>${a.logins ? "on" : "off"}</td></tr></tbody></table>`;
    $("backupWhere").textContent = `Backups are kept in ${b.folder}. Each one holds master data, projects and CAD files. ` +
      "Copy them to OneDrive or a pen drive too (backup_copy_to in dtc_settings.ini).";
    $("backups").innerHTML = `<thead><tr><th>Backup</th><th>Made</th><th class="num">Size (MB)</th><th></th></tr></thead><tbody>${
      b.backups.map((x) => `<tr><td>${esc(x.name)}</td><td>${esc(x.created.replace("T", " "))}</td><td class="num">${x.size_mb}</td>
      <td><a class="btn btn-outline small" href="/api/admin/backups/${encodeURIComponent(x.name)}">Download</a></td></tr>`).join("")
      || '<tr><td colspan="4" class="empty">No backup yet.</td></tr>'}</tbody>`;
    $("reports").innerHTML = a.update_reports.length
      ? a.update_reports.map((r) => `<details class="card"><summary>${esc(r.name)}</summary><pre class="report">${esc(r.text)}</pre></details>`).join("")
      : '<p class="note">No update report yet (they are written by DTC_Update.bat).</p>';
  } catch (err) {
    status($("status"), err.message, "error");
  }
}
$("backupNow").addEventListener("click", async () => {
  status($("status"), "Making a backup…");
  try {
    const r = await api("/api/admin/backups", { method: "POST" });
    status($("status"), `Backup ${r.name} made (${r.size_mb} MB).`, "ok");
    loadBackups();
  } catch (err) {
    status($("status"), err.message, "error");
  }
});

init().catch((err) => status($("status"), err.message, "error"));

// ---------- drawings: logo and title block ----------
async function loadDrawing() {
  const d = await api("/api/register-setup/drawing");
  $("logoImg").src = `/api/drawing-logo.png?t=${Date.now()}`;
  $("logoNote").textContent = d.logo === "default" ? "The app logo is used." : "Your logo is used on every drawing.";
  $("drawForm").innerHTML = Object.entries(d.settings).map(([k, v]) => `<label>${esc(d.labels[k].replace(/^Drawings: /, ""))}
    ${k === "drawing_projection" ? `<select name="${k}">${["Third angle", "First angle"].map((o) => `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select>`
      : `<input name="${k}" value="${esc(v)}" />`}</label>`).join("") +
    `<div class="span2 dialog-actions"><button class="btn btn-primary small" type="submit">Save</button></div>`;
}
$("drawForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/register-setup/drawing", { method: "PUT", body: JSON.stringify(Object.fromEntries(new FormData(e.target))) });
    status($("status"), "Drawing settings saved: they are on the next drawing you download.", "ok");
  } catch (err) {
    status($("status"), err.message, "error");
  }
});
$("logoForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const res = await fetch("/api/register-setup/drawing/logo", { method: "POST", body: new FormData(e.target) });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) return status($("status"), body.detail || "Upload failed.", "error");
  e.target.reset();
  status($("status"), "Logo saved: it is on every drawing from now on.", "ok");
  loadDrawing();
});
$("logoReset").addEventListener("click", async () => {
  await api("/api/register-setup/drawing/logo", { method: "DELETE" });
  loadDrawing();
});
