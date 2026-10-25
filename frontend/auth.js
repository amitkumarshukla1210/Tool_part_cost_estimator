// Every page: the release name in the footer. Server mode: shows who is logged in (with Log out, Users for admins) in the page header. Does nothing in local mode.
(async function () {
  try {
    const me = await (await fetch("/api/auth/me")).json();
    const foot = document.querySelector("footer .footnote");
    if (foot && me.version) foot.textContent = `© Design to Cost · Part Cost Estimator ${me.version}`;
    if (me.mode !== "server" || !me.user) return;
    const ul = document.querySelector("header nav ul");
    if (!ul) return;
    const li = document.createElement("li");
    li.innerHTML = `${me.user.role === "admin" ? '<a href="/users">Users</a> · ' : ""}<span title="${me.user.role}">${(me.user.name || me.user.username).replace(/[<>&"]/g, "")}</span> · <a href="#" id="logoutLink">Log out</a>`;
    ul.appendChild(li);
    document.getElementById("logoutLink").addEventListener("click", async (e) => {
      e.preventDefault();
      await fetch("/api/auth/logout", { method: "POST" });
      location.href = "/login";
    });
  } catch { /* offline: ignore */ }
})();
