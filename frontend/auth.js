// Server mode: shows who is logged in (with Log out, Users for admins) in the page header. Does nothing in local mode.
(async function () {
  try {
    const me = await (await fetch("/api/auth/me")).json();
    if (me.mode !== "server" || !me.user) return;
    const ul = document.querySelector("header nav ul");
    if (!ul) return;
    if (me.user.role !== "admin") ul.querySelectorAll('a[href="/backup"]').forEach((a) => a.closest("li")?.remove());   // backups are the admin's
    const li = document.createElement("li");
    li.innerHTML = `${me.user.role === "admin" ? '<a href="/users">Users</a> · ' : ""}<a href="/account" title="${me.user.role}: my account and password">${(me.user.name || me.user.username).replace(/[<>&"]/g, "")}</a> · <a href="#" id="logoutLink">Log out</a>`;
    ul.appendChild(li);
    document.getElementById("logoutLink").addEventListener("click", async (e) => {
      e.preventDefault();
      await fetch("/api/auth/logout", { method: "POST" });
      location.href = "/login";
    });
  } catch { /* offline: ignore */ }
})();
