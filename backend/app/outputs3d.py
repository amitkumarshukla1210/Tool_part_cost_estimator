"""3D outputs of a tool design (roadmap stage 45): STL files, a picture per part and a 3D viewer page.

    STL        binary STL of the assembly (every part at its place) and of each tool part (its own origin, like its STEP)
    picture    an iso PNG of each tool part
    viewer     one self-contained HTML page per tool (the meshes and the part data inside, WebGL, no internet needed): rotate,
               zoom, explode, click a part to see its item, name, material, hardness, stock size and its INR share of the tool cost
               (production data). The same file is in the release ZIP, so it opens offline.
Nothing here is a rule or a rate: sizes come from the design, money from the production data (a split of the tool cost).
"""

from __future__ import annotations

import html
import json
import struct

import numpy as np

from . import render3d, tool_design


def comp_mesh(c):
    return render3d.mesh(c.shape, tol=max(0.3, max(c.size) / 150 if c.size else 0.4))


def stl_bytes(meshes, name: str = "tool") -> bytes:
    """Binary STL of [(vertices, triangles)] (already at their places)."""
    tris = []
    for v, t in meshes:
        if len(t):
            tris.append(v[t])
    allt = np.concatenate(tris) if tris else np.zeros((0, 3, 3))
    n = np.cross(allt[:, 1] - allt[:, 0], allt[:, 2] - allt[:, 0]) if len(allt) else np.zeros((0, 3))
    ln = np.linalg.norm(n, axis=1, keepdims=True) if len(n) else n
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln > 0) if len(n) else n
    head = (f"Design to Cost {name}"[:80]).encode("ascii", "replace").ljust(80, b" ")
    out = [head, struct.pack("<I", len(allt))]
    rec = np.zeros(len(allt), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, allt
    out.append(rec.tobytes())
    return b"".join(out)


def part_stl(c) -> bytes:
    v, t = comp_mesh(c)
    return stl_bytes([(v, t)], c.name)


def assembly_stl(design: dict) -> bytes:
    meshes = []
    for c in design["components"]:
        if c.kind == "ref":
            continue
        v, t = comp_mesh(c)
        meshes += [(v + np.array(loc[:3]), t) for loc in c.locs]
    return stl_bytes(meshes, design["name"])


def part_png(c, size=(700, 520)) -> bytes:
    v, t = comp_mesh(c)
    rgb = tool_design.COLORS.get(c.color, (0.6, 0.6, 0.6))
    return render3d.png(render3d.render([(v, t, rgb)], size=size))


def part_step(c) -> bytes:
    return tool_design.step_bytes(c.shape)


def find(design: dict, item: str):
    c = next((x for x in design["components"] if x.no == item and x.kind != "ref"), None)
    if not c:
        raise ValueError(f"There is no item {item} in {design['name']}.")
    return c


# ---------- viewer ----------

def viewer_data(part: dict, design: dict, rev: str, production: dict | None = None) -> dict:
    """Meshes (rounded to 0.01 mm) and data of every part of one tool; production = production_data tool entry (or None)."""
    prod = {p["item"]: p for p in (production or {}).get("parts", [])}
    std = {s["element"].lower(): s for s in (production or {}).get("standard", [])}
    parts = []
    for c in design["components"]:
        v, t = comp_mesh(c)
        p = prod.get(c.no) or {}
        s = next((x for k, x in std.items() if c.name.lower().startswith(k) or k.startswith(c.name.lower().split(" ")[0])), None) if c.kind == "std" else None
        parts.append({"item": c.no or "REF", "name": c.name, "kind": c.kind, "qty": c.qty, "material": c.material or "", "hardness": c.hardness or "",
                      "std": c.std or c.make or "", "size": [round(x, 1) for x in c.size], "stock": p.get("stock_mm"), "kg": p.get("kg_total"),
                      "inr": p.get("total_inr") if p else (s or {}).get("inr"), "inr_note": "share of the tool cost" if p else ("bought-out line" if s else ""),
                      "rgb": list(tool_design.COLORS.get(c.color, (0.6, 0.6, 0.6))), "locs": [list(map(float, loc[:3])) for loc in c.locs],
                      "v": [round(float(x), 2) for x in v.reshape(-1)], "t": [int(x) for x in t.reshape(-1)]})
    return {"title": f"{part['part_code']} rev {rev} · {design['name']}", "part_code": part["part_code"], "rev": rev, "tool": design["name"],
            "tool_cost_inr": (production or {}).get("sums", {}).get("tool_cost_inr"), "parts": parts}


def viewer_html(data: dict) -> str:
    """The self-contained viewer page (data embedded)."""
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return _PAGE.replace("__TITLE__", html.escape(data["title"])).replace("__DATA__", payload)


_PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" /><title>__TITLE__ · 3D viewer</title>
<style>
  html, body { margin: 0; height: 100%; font-family: Inter, Segoe UI, Arial, sans-serif; color: #0e1a2c; background: #f3f5f8; }
  #bar { position: absolute; top: 0; left: 0; right: 0; padding: 10px 14px; background: #0e1a2c; color: #fff; display: flex; gap: 18px; align-items: center; }
  #bar b { font-size: 15px; } #bar label { font-size: 12px; display: flex; gap: 6px; align-items: center; }
  #bar button { background: #fff; color: #0e1a2c; border: 0; border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 12px; }
  canvas { position: absolute; top: 46px; left: 0; width: calc(100% - 320px); height: calc(100% - 46px); cursor: grab; }
  #side { position: absolute; top: 46px; right: 0; width: 320px; bottom: 0; overflow: auto; background: #fff; border-left: 1px solid #dde2e8; font-size: 13px; }
  #info { padding: 12px 14px; border-bottom: 1px solid #dde2e8; min-height: 120px; }
  #info h3 { margin: 0 0 6px; font-size: 15px; } #info td { padding: 2px 6px 2px 0; vertical-align: top; } #info td:first-child { color: #5b6878; }
  #list div { padding: 5px 14px; cursor: pointer; border-bottom: 1px solid #f0f2f5; display: flex; gap: 8px; }
  #list div:hover, #list div.on { background: #e8f0fb; } #list span.sw { width: 12px; height: 12px; border-radius: 2px; flex: none; margin-top: 2px; }
  #hint { position: absolute; left: 12px; bottom: 10px; font-size: 12px; color: #5b6878; }
</style></head><body>
<div id="bar"><b>__TITLE__</b>
  <label>Explode <input type="range" id="explode" min="0" max="100" value="0" /></label>
  <label><input type="checkbox" id="showref" /> Show the part (workpiece)</label>
  <button id="reset">Reset view</button></div>
<canvas id="gl"></canvas>
<div id="side"><div id="info"><h3>Click a part</h3><p>Drag to rotate, wheel to zoom, right-drag to move. Click a part (or a row below) to see its data.</p></div><div id="list"></div></div>
<div id="hint"></div>
<script>
const D = __DATA__;
const cv = document.getElementById("gl"), gl = cv.getContext("webgl", { antialias: true, preserveDrawingBuffer: true });
const fmt = (v, d = 0) => v == null ? "—" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
if (!gl) { document.getElementById("hint").textContent = "This browser has no WebGL: open the STEP or STL files instead."; }
const VS = `attribute vec3 p; attribute vec3 n; uniform mat4 m; uniform vec3 off; varying float l;
  void main(){ vec3 q = p + off; gl_Position = m * vec4(q, 1.0); l = 0.35 + 0.65 * abs(dot(normalize(n), normalize(vec3(0.4, -0.5, 0.75)))); }`;
const FS = `precision mediump float; uniform vec3 c; uniform float pick; varying float l; void main(){ gl_FragColor = vec4(pick > 0.5 ? c : c * l, 1.0); }`;
function sh(t, s) { const o = gl.createShader(t); gl.shaderSource(o, s); gl.compileShader(o); return o; }
const pr = gl.createProgram(); gl.attachShader(pr, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(pr); gl.useProgram(pr);
const U = (n) => gl.getUniformLocation(pr, n), A = (n) => gl.getAttribLocation(pr, n);
let lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
const parts = D.parts.map((p, k) => {
  const pos = [], nor = [];
  for (let i = 0; i < p.t.length; i += 3) {
    const a = p.t[i] * 3, b = p.t[i + 1] * 3, c = p.t[i + 2] * 3, V = p.v;
    const u = [V[b] - V[a], V[b + 1] - V[a + 1], V[b + 2] - V[a + 2]], w = [V[c] - V[a], V[c + 1] - V[a + 1], V[c + 2] - V[a + 2]];
    const nn = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]];
    for (const j of [a, b, c]) { pos.push(V[j], V[j + 1], V[j + 2]); nor.push(...nn); }
  }
  for (const L of p.locs) for (let i = 0; i < p.v.length; i += 3) for (let d = 0; d < 3; d++) {
    if (p.kind === "ref") continue; lo[d] = Math.min(lo[d], p.v[i + d] + L[d]); hi[d] = Math.max(hi[d], p.v[i + d] + L[d]); }
  const pb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, pb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(pos), gl.STATIC_DRAW);
  const nb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, nb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(nor), gl.STATIC_DRAW);
  return { ...p, pb, nb, count: pos.length / 3, id: [((k + 1) & 255) / 255, (((k + 1) >> 8) & 255) / 255, 0.5] };
});
const ctr = [0, 1, 2].map((d) => (lo[d] + hi[d]) / 2), rad = Math.max(1, Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2);
let az = -0.9, el = 0.5, dist = rad * 3.2, pan = [0, 0], sel = -1;
function mat() {
  const w = cv.clientWidth, h = cv.clientHeight, asp = w / h, f = 1 / Math.tan(0.35), near = dist / 50, far = dist * 6;
  const ca = Math.cos(az), sa = Math.sin(az), ce = Math.cos(el), se = Math.sin(el);
  // view rotation, rows: x' = ca*x + sa*y ; y' = -sa*se*x + ca*se*y + ce*z ; z' = sa*ce*x - ca*ce*y + se*z (column-major below)
  const t = [-ctr[0], -ctr[1], -ctr[2]];
  const x = (p) => [ca * p[0] + sa * p[1], -sa * se * p[0] + ca * se * p[1] + ce * p[2], sa * ce * p[0] - ca * ce * p[1] + se * p[2]];
  const tx = x(t);
  const V = [ca, -sa * se, sa * ce, 0, sa, ca * se, -ca * ce, 0, 0, ce, se, 0, tx[0] + pan[0], tx[1] + pan[1], tx[2] - dist, 1];
  const P = [f / asp, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) / (near - far), -1, 0, 0, 2 * far * near / (near - far), 0];
  const M = new Array(16).fill(0);
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) for (let k = 0; k < 4; k++) M[j * 4 + i] += P[k * 4 + i] * V[j * 4 + k];
  return M;
}
function draw(pick) {
  const w = cv.clientWidth, h = cv.clientHeight;
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  gl.viewport(0, 0, w, h); gl.enable(gl.DEPTH_TEST);
  gl.clearColor(pick ? 0 : 0.953, pick ? 0 : 0.961, pick ? 0 : 0.973, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.uniformMatrix4fv(U("m"), false, new Float32Array(mat())); gl.uniform1f(U("pick"), pick ? 1 : 0);
  const ex = document.getElementById("explode").value / 100 * 1.5, showRef = document.getElementById("showref").checked;
  parts.forEach((p, k) => {
    if (p.kind === "ref" && !showRef) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, p.pb); gl.vertexAttribPointer(A("p"), 3, gl.FLOAT, false, 0, 0); gl.enableVertexAttribArray(A("p"));
    gl.bindBuffer(gl.ARRAY_BUFFER, p.nb); gl.vertexAttribPointer(A("n"), 3, gl.FLOAT, false, 0, 0); gl.enableVertexAttribArray(A("n"));
    const col = pick ? p.id : (k === sel ? [0.85, 0.1, 0.75] : p.rgb);
    gl.uniform3fv(U("c"), col);
    for (const L of p.locs) { gl.uniform3fv(U("off"), [L[0], L[1], L[2] + (L[2] - lo[2]) * ex]); gl.drawArrays(gl.TRIANGLES, 0, p.count); }
  });
}
function info(k) {
  sel = k; draw(false);
  document.querySelectorAll("#list div").forEach((d, i) => d.classList.toggle("on", i === k));
  const p = parts[k]; if (!p) return;
  document.getElementById("info").innerHTML = `<h3>${esc(p.item)} · ${esc(p.name)}</h3><table>
    <tr><td>Kind</td><td>${p.kind === "made" ? "made part" : p.kind === "std" ? "standard / bought-out" : "the part (workpiece)"}</td></tr>
    <tr><td>Qty</td><td>${p.qty}</td></tr><tr><td>Material</td><td>${esc(p.material || "—")}</td></tr><tr><td>Hardness</td><td>${esc(p.hardness || "—")}</td></tr>
    ${p.std ? `<tr><td>Standard / make</td><td>${esc(p.std)}</td></tr>` : ""}
    <tr><td>Size (mm)</td><td>${p.size.map((v) => fmt(v, 1)).join(" × ")}</td></tr>
    ${p.stock ? `<tr><td>Stock (mm)</td><td>${p.stock.map((v) => fmt(v)).join(" × ")}</td></tr><tr><td>Steel</td><td>${fmt(p.kg, 2)} kg</td></tr>` : ""}
    <tr><td>Cost</td><td>${p.inr == null ? "—" : "₹ " + fmt(p.inr) + ` <small>(${esc(p.inr_note)})</small>`}</td></tr></table>`;
}
document.getElementById("list").innerHTML = parts.map((p) => `<div><span class="sw" style="background:rgb(${p.rgb.map((c) => Math.round(c * 255)).join(",")})"></span>
  <span>${esc(p.item)} · ${esc(p.name)}${p.qty > 1 ? " × " + p.qty : ""}</span></div>`).join("");
document.querySelectorAll("#list div").forEach((d, i) => d.addEventListener("click", () => info(i)));
document.getElementById("hint").textContent = D.tool_cost_inr ? "Tool cost ₹ " + fmt(D.tool_cost_inr) + " (production data: parts + standard parts + tool level)" : "";
let drag = null, moved = false;
cv.addEventListener("mousedown", (e) => { drag = [e.clientX, e.clientY, e.button]; moved = false; });
window.addEventListener("mouseup", (e) => {
  if (drag && !moved && e.button === 0) {
    draw(true); const r = cv.getBoundingClientRect(), px = new Uint8Array(4);
    gl.readPixels(e.clientX - r.left, cv.height - (e.clientY - r.top), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
    const k = px[0] + px[1] * 256 - 1; draw(false); if (k >= 0 && k < parts.length) info(k);
  }
  drag = null;
});
window.addEventListener("mousemove", (e) => {
  if (!drag) return; const dx = e.clientX - drag[0], dy = e.clientY - drag[1]; if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
  if (drag[2] === 2) { pan[0] += dx * dist / 900; pan[1] -= dy * dist / 900; } else { az -= dx * 0.008; el = Math.max(-1.5, Math.min(1.5, el + dy * 0.008)); }
  drag[0] = e.clientX; drag[1] = e.clientY; draw(false);
});
cv.addEventListener("contextmenu", (e) => e.preventDefault());
cv.addEventListener("wheel", (e) => { e.preventDefault(); dist *= e.deltaY > 0 ? 1.1 : 0.9; draw(false); }, { passive: false });
document.getElementById("explode").addEventListener("input", () => draw(false));
document.getElementById("showref").addEventListener("change", () => draw(false));
document.getElementById("reset").addEventListener("click", () => { az = -0.9; el = 0.5; dist = rad * 3.2; pan = [0, 0]; draw(false); });
window.addEventListener("resize", () => draw(false));
draw(false);
</script></body></html>
"""
