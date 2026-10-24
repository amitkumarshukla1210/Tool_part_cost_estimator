// Small helpers shared by the register pages (Dashboard, Parts, Import).
window.DTC = (function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const fmt = (v, d = 0) => (v == null || v === "" ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
  const inr = (v) => (v == null ? "—" : `INR ${fmt(v, 0)}`);

  async function api(url, opts = {}) {
    const isForm = opts.body instanceof FormData;
    const res = await fetch(url, { ...(isForm ? {} : { headers: { "Content-Type": "application/json" } }), ...opts });
    const body = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
    if (!res.ok) {
      const d = body?.detail;
      throw new Error(Array.isArray(d) ? d.map((x) => `${x.loc?.at(-1)}: ${x.msg}`).join("; ") : d || res.statusText);
    }
    return body;
  }

  let meta = null;
  async function registerMeta() {
    meta ??= await api("/api/register-meta");
    return meta;
  }
  const options = (list, value, blank) =>
    (blank != null ? `<option value="">${esc(blank)}</option>` : "") +
    list.map((o) => `<option value="${esc(o.code ?? o)}" ${String(o.code ?? o) === String(value ?? "") ? "selected" : ""}>${esc(o.name ?? o)}</option>`).join("");

  function status(el, msg, kind = "") {
    el.textContent = msg;
    el.className = `status ${kind}`;
  }

  const thumb = (fileId, cls = "thumb") =>
    fileId ? `<img class="${cls}" src="/api/files/${fileId}" alt="" loading="lazy" />` : `<span class="${cls} none">no 3D</span>`;

  return { $, esc, fmt, inr, api, registerMeta, options, status, thumb };
})();

// version in the footer of every page
fetch("/api/version").then((r) => (r.ok ? r.json() : null)).then((v) => {
  if (v) document.querySelectorAll(".footnote").forEach((el) => { if (!el.textContent.includes(v.version)) el.textContent += ` · Version ${v.version}`; });
}).catch(() => {});
