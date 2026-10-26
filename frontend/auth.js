// Release name (VERSION) in the page footer. Logged-in user in the page header: Admin (users, permissions, activity, backups), the user's name and Log out.
(async function () {
  try {
    const me = await (await fetch("/api/auth/me")).json();
    const foot = document.querySelector("footer .footnote");
    if (foot && me.version) foot.textContent = `© Design to Cost · Part Cost Estimator ${me.version}`;
    const ul = document.querySelector("header nav ul");
    if (!ul) return;
    if (!ul.querySelector('a[href="/admin"]')) {
      const admin = document.createElement("li");
      admin.innerHTML = `<a href="/admin" ${location.pathname === "/admin" ? 'class="active" aria-current="page"' : ""}>Admin</a>`;
      ul.appendChild(admin);
    }
    if (me.mode !== "server" || !me.user) return;
    const li = document.createElement("li");
    li.className = "who";
    li.innerHTML = `<span title="Role: ${me.user.role}">${(me.user.name || me.user.username).replace(/[<>&"]/g, "")} · ${me.user.role}</span> · <a href="#" id="logoutLink">Log out</a>`;
    ul.appendChild(li);
    document.getElementById("logoutLink").addEventListener("click", async (e) => {
      e.preventDefault();
      await fetch("/api/auth/logout", { method: "POST" });
      location.href = "/login";
    });
  } catch { /* offline: ignore */ }
})();
