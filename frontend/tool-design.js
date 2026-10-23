// Production tool design (roadmap stage 21): 3D viewer with measuring, section and explode, component drawings and STEP files,
// correction by STEP upload, checks, release and the purchase-order pack.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const { $, esc, fmt, api, status } = window.DTC;
const params = new URLSearchParams(location.search);
let partId = params.get("part") ? Number(params.get("part")) : null;
let designId = params.get("design") ? Number(params.get("design")) : null;
let design = null, payload = null, selected = null, measureOn = false, measurePts = [], measures = [];
const meshes = new Map(); // component id -> {mesh, edges, comp}

// ---------------------------------------------------------------- three.js scene
const canvas = $("canvas");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.localClippingEnabled = true;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xeef2f7);
const camera = new THREE.PerspectiveCamera(35, 1, 1, 1e6);
const controls = new OrbitControls(camera, canvas);
scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.05));
const sun = new THREE.DirectionalLight(0xffffff, 1.1);
sun.position.set(1, 2, 1.5);
scene.add(sun);
const root = new THREE.Group(); // CAD z is up
root.rotation.x = -Math.PI / 2;
scene.add(root);
const markers = new THREE.Group(), meas = new THREE.Group();
root.add(markers, meas);
let sizeMm = 100, box = new THREE.Box3(), clip = null;

function resize() {
  const w = canvas.parentElement.clientWidth, h = canvas.parentElement.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
addEventListener("resize", resize);
(function loop() {
  requestAnimationFrame(loop);
  controls.update();
  renderer.render(scene, camera);
})();

const b64 = (s, T) => {
  const bin = atob(s), u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return new T(u.buffer);
};

function buildScene() {
  for (const { mesh, edges } of meshes.values()) { root.remove(mesh); root.remove(edges); mesh.geometry.dispose(); }
  meshes.clear();
  box = new THREE.Box3();
  for (const c of payload.components) {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(b64(c.v, Float32Array), 3));
    g.setIndex(new THREE.BufferAttribute(b64(c.f, Uint32Array), 1));
    g.computeVertexNormals();
    const col = new THREE.Color(...c.color);
    const mat = new THREE.MeshStandardMaterial({ color: col, metalness: 0.25, roughness: 0.55, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
    const mesh = new THREE.Mesh(g, mat);
    mesh.userData = { id: c.id, kind: c.kind, group: c.group, color: col.clone(), partNo: c.part_no, name: c.name };
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(g, 35), new THREE.LineBasicMaterial({ color: c.edited ? 0x1f5fa8 : 0x2b3a4a }));
    edges.userData = { id: c.id };
    root.add(mesh, edges);
    meshes.set(c.id, { mesh, edges, comp: c });
    box.expandByObject(mesh);
  }
  sizeMm = box.getSize(new THREE.Vector3()).length();
  applyVisibility();
  setView("iso");
}

function setView(v) {
  const c = box.getCenter(new THREE.Vector3()), d = sizeMm * 0.95;
  const dirs = { iso: [0.8, 0.7, 1.0], top: [0, 1.0, 0.001], front: [0, 0, 1], right: [1, 0, 0] };
  const [x, y, z] = dirs[v];
  const cw = root.localToWorld(c.clone());
  camera.position.set(cw.x + x * d, cw.y + y * d, cw.z + z * d);
  controls.target.copy(cw);
  camera.near = sizeMm / 500; camera.far = sizeMm * 40;
  camera.updateProjectionMatrix();
  controls.update();
}

function applyVisibility() {
  const showRef = $("showRef").checked, showStd = $("showStd").checked, wire = $("wire").checked;
  for (const { mesh, edges } of meshes.values()) {
    const k = mesh.userData.kind;
    const vis = !mesh.userData.hidden && (["work", "part", "proposal"].includes(k) ? showRef : k === "standard" ? showStd : true);
    mesh.visible = vis; edges.visible = vis && !wire;
    mesh.material.wireframe = wire;
    mesh.material.clippingPlanes = clip ? [clip] : [];
    edges.material.clippingPlanes = clip ? [clip] : [];
    const isSel = mesh.userData.id === selected;
    mesh.material.emissive.setHex(isSel ? 0x6b4a00 : 0x000000);
    const ref = ["work", "part"].includes(k);
    mesh.material.transparent = ref; mesh.material.opacity = ref ? 0.55 : 1;
    edges.material.color.setHex(isSel ? 0xe07b1f : meshes.get(mesh.userData.id).comp.edited ? 0x1f5fa8 : 0x2b3a4a);
  }
  applyExplode();
}

function applyExplode() {
  const k = Number($("explode").value), span = payload ? payload.span_mm : 0;
  for (const { mesh, edges } of meshes.values()) {
    const z = mesh.userData.group === "upper" ? k * span : 0;
    mesh.position.z = z; edges.position.z = z;
  }
}

function applySection() {
  const axis = $("secAxis").value;
  if (!axis) { clip = null; applyVisibility(); return; }
  const lo = box.min[axis], hi = box.max[axis], pos = lo + (hi - lo) * Number($("secPos").value);
  const n = new THREE.Vector3(axis === "x" ? 1 : 0, axis === "y" ? 1 : 0, axis === "z" ? 1 : 0);
  clip = new THREE.Plane(n.negate(), pos).applyMatrix4(root.matrixWorld);
  applyVisibility();
}

// ---------------------------------------------------------------- picking and measuring
const ray = new THREE.Raycaster();
function pick(ev) {
  const r = canvas.getBoundingClientRect();
  const m = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(m, camera);
  const hits = ray.intersectObjects([...meshes.values()].map((x) => x.mesh).filter((m2) => m2.visible), false)
    .filter((h) => !clip || clip.distanceToPoint(h.point) >= 0);
  return hits[0] || null;
}
function snapped(hit) {
  const pos = hit.object.geometry.attributes.position, f = hit.face;
  let best = hit.point.clone(), bd = sizeMm * 0.02;
  for (const i of [f.a, f.b, f.c]) {
    const v = new THREE.Vector3().fromBufferAttribute(pos, i);
    hit.object.localToWorld(v);
    const d = v.distanceTo(hit.point);
    if (d < bd) { bd = d; best = v; }
  }
  return best;
}
const cad = (w) => root.worldToLocal(w.clone());
let down = null;
canvas.addEventListener("pointerdown", (e) => (down = [e.clientX, e.clientY]));
canvas.addEventListener("pointerup", (e) => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
  const hit = pick(e);
  if (measureOn) return hit && addMeasurePoint(snapped(hit));
  if (hit) select(hit.object.userData.id, true);
});
canvas.addEventListener("pointermove", (e) => {
  const hit = pick(e);
  if (!hit) return ($("hud").textContent = "");
  const p = cad(snapped(hit));
  $("hud").textContent = `${hit.object.userData.partNo}  ${hit.object.userData.name}   X ${p.x.toFixed(2)}  Y ${p.y.toFixed(2)}  Z ${p.z.toFixed(2)} mm`;
});

function addMeasurePoint(w) {
  measurePts.push(w);
  const s = new THREE.Mesh(new THREE.SphereGeometry(sizeMm * 0.004, 12, 8), new THREE.MeshBasicMaterial({ color: 0xb91c1c, depthTest: false }));
  s.position.copy(cad(w)); s.renderOrder = 10; meas.add(s);
  if (measurePts.length === 2) {
    const [a, b] = measurePts.map(cad);
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), new THREE.LineBasicMaterial({ color: 0xb91c1c, depthTest: false }));
    line.renderOrder = 10; meas.add(line);
    const d = b.clone().sub(a);
    measures.push({ dist: d.length(), dx: Math.abs(d.x), dy: Math.abs(d.y), dz: Math.abs(d.z), a, b });
    measurePts = [];
    renderMeasure();
  }
  $("hud").textContent = measurePts.length ? "Click the second point" : "";
}
function clearMeasures() { measures = []; measurePts = []; while (meas.children.length) meas.remove(meas.children[0]); renderMeasure(); }
function renderMeasure() {
  $("tab-measure").innerHTML = `<p class="note">Turn on <b>Measure distance</b> in the toolbar and click two points on the model (points snap to nearby corners).
    Coordinates are CAD X, Y, Z in mm. Click a hole or radius in a part's details to mark it in 3D.</p>
    <button class="btn btn-outline small" id="clearMeas" type="button">Clear</button>
    <table class="cost-table"><thead><tr><th>#</th><th class="num">Distance</th><th class="num">ΔX</th><th class="num">ΔY</th><th class="num">ΔZ</th></tr></thead><tbody>
    ${measures.map((m, i) => `<tr><td>${i + 1}</td><td class="num"><b>${m.dist.toFixed(2)}</b></td><td class="num">${m.dx.toFixed(2)}</td><td class="num">${m.dy.toFixed(2)}</td><td class="num">${m.dz.toFixed(2)}</td></tr>`).join("") || '<tr><td colspan="5">none yet</td></tr>'}</tbody></table>`;
  $("clearMeas")?.addEventListener("click", clearMeasures);
}

function mark(pos, label, color = 0xb91c1c) {
  const s = new THREE.Mesh(new THREE.SphereGeometry(Math.max(sizeMm * 0.006, 0.8), 14, 10), new THREE.MeshBasicMaterial({ color, depthTest: false }));
  s.position.set(...pos); s.renderOrder = 12; markers.add(s);
  const el = $("hud"); el.textContent = label;
}
const clearMarks = () => { while (markers.children.length) markers.remove(markers.children[0]); };

// ---------------------------------------------------------------- selection and detail
function select(id, scrollList = false) {
  selected = id;
  clearMarks();
  applyVisibility();
  document.querySelectorAll("#tab-parts tr[data-id]").forEach((tr) => tr.classList.toggle("sel", Number(tr.dataset.id) === id));
  if (scrollList) document.querySelector(`#tab-parts tr[data-id="${id}"]`)?.scrollIntoView({ block: "nearest" });
  detail(id);
}

async function detail(id) {
  const c = design.components.find((x) => x.id === id);
  const el = $("detail");
  if (!c) return (el.hidden = true);
  el.hidden = false;
  const i = c.info || {}, draft = design.status === "draft";
  if (c.kind !== "made") {
    el.innerHTML = `<h3>${esc(c.part_no)} · ${esc(c.name)}</h3><p class="note">${c.kind === "standard" ? "Bought-out standard part: ordered from the catalogue (see the bought-out list in BOM &amp; PO)." : "Reference only (not part of the tool BOM)."}</p>
      <p>Size ${(i.bbox_mm || []).map((x) => fmt(x, 1)).join(" × ")} mm</p>${c.kind === "standard" ? `<p><a class="link" href="/api/tool-designs/${design.id}/components/${c.id}/step">Download STEP</a></p>` : ""}`;
    return;
  }
  const f = i.features || {}, st = i.stock || {};
  const base = `/api/tool-designs/${design.id}/components/${c.id}`;
  el.innerHTML = `<h3>${esc(c.part_no)} · ${esc(c.name.split(":")[0])} <span class="badge">rev ${esc(c.rev)}</span> ${c.edited ? '<span class="badge edited">edited</span>' : ""}</h3>
    <div class="row"><a class="btn btn-outline small" href="${base}/step">STEP</a><a class="btn btn-outline small" href="${base}/drawing.pdf" target="_blank">Drawing PDF</a>
      <a class="btn btn-outline small" href="${base}/drawing.dxf">DXF</a></div>
    <table class="cost-table"><tbody>
      <tr><td>Class</td><td>${esc(i.class_name)}</td></tr><tr><td>Steel</td><td>${esc(i.steel)} · ${esc(i.hardness || "")}</td></tr>
      <tr><td>Finished size</td><td>${(i.bbox_mm || []).map((x) => fmt(x, 2)).join(" × ")} mm · ${fmt(i.volume_cm3, 1)} cm³ · ${fmt(st.finished_weight_kg, 2)} kg</td></tr>
      <tr><td>Raw stock</td><td>${(st.size_mm || []).map((x) => fmt(x, 0)).join(" × ")} mm · ${fmt(st.weight_kg, 2)} kg</td></tr>
      <tr><td>Tolerances</td><td>${esc(i.tolerance)}</td></tr><tr><td>Route</td><td>${esc(i.route)}</td></tr>
      <tr><td>Estimate</td><td>material ${fmt(i.material_cost)} · machining ${fmt(i.machining_cost)} (${esc(design.bill.currency)})</td></tr></tbody></table>
    <h4>Machining operations</h4>
    <table class="cost-table"><tbody>${(i.operations || []).map((o) => `<tr><td>${esc(o.label)}</td><td class="num">${fmt(o.amount, 2)} ${esc(o.unit)}</td><td class="num">${o.cost == null ? "no rate" : fmt(o.cost)}</td></tr>`).join("")}</tbody></table>
    <h4>Features (click to mark in 3D)</h4>
    <table class="cost-table"><tbody>
      ${(f.holes || []).map((h, k) => `<tr class="clickable feat" data-k="h${k}"><td>${h.count} × hole Ø${fmt(h.dia_mm, 2)}</td><td>depth ${fmt(h.depth_mm, 1)}${h.through ? " thru" : ""}</td><td>axis ${esc(h.axis)}</td></tr>`).join("")}
      ${(f.openings || []).map((o, k) => `<tr class="clickable feat" data-k="o${k}"><td>opening ${fmt(o.length_mm, 1)} × ${fmt(o.width_mm, 1)}</td><td>contour ${fmt(o.perimeter_mm, 0)}</td><td>${o.through ? "thru" : "blind"}</td></tr>`).join("")}
      ${(f.pockets || []).map((p, k) => `<tr class="clickable feat" data-k="p${k}"><td>pocket ${fmt(p.length_mm, 1)} × ${fmt(p.width_mm, 1)}</td><td>depth ${fmt(p.depth_mm, 1)}</td><td></td></tr>`).join("")}
      ${(f.fillets || []).slice(0, 12).map((r, k) => `<tr class="clickable feat" data-k="r${k}"><td>radius R${fmt(r.radius_mm, 2)}</td><td>${r.convex ? "convex" : "concave"}</td><td>length ${fmt(r.length_mm, 1)}</td></tr>`).join("")}
    </tbody></table>
    <h4>Correct this part</h4>
    ${draft ? `<p class="note">Download the STEP, change it in your CAD (a radius, a thickness …) and upload it here. Identical parts follow; size, stock, weight, machining and the overlap check are recalculated.</p>
      <input type="file" id="upFile" accept=".step,.stp" /><input id="upNote" placeholder="What did you change?" style="width:100%" />
      <button class="btn btn-primary small" id="upGo" type="button">Upload corrected STEP</button> <span class="status" id="upStatus"></span>`
      : `<p class="note">This design is ${esc(design.status)}: start a new revision to change a part.</p>`}
    <h4>Revisions</h4><div id="revs"></div>`;
  el.querySelectorAll(".feat").forEach((tr) => tr.addEventListener("click", () => markFeature(c, tr.dataset.k)));
  $("upGo")?.addEventListener("click", () => upload(c));
  const revs = await api(`${base}/revisions`).catch(() => []);
  $("revs").innerHTML = `<table class="cost-table"><tbody>${revs.map((r) => `<tr><td><b>${esc(r.rev)}</b></td><td>${esc(r.note)}</td><td>${fmt(r.volume_cm3, 1)} cm³</td>
    <td>${draft && r.rev !== c.rev ? `<button class="btn btn-outline small revert" data-rev="${esc(r.rev)}" type="button">use</button>` : ""}</td></tr>`).join("")}</tbody></table>`;
  el.querySelectorAll(".revert").forEach((b) => b.addEventListener("click", async () => {
    await api(`${base}/revert`, { method: "POST", body: JSON.stringify({ rev: b.dataset.rev }) });
    await loadDesign(design.id, id);
  }));
}

function markFeature(c, key) {
  clearMarks();
  const info = payload.components.find((x) => x.id === c.id)?.info || {}, o = info.bbox_min || [0, 0, 0], f = info.features || {};
  const add = (p) => [p[0] + o[0], p[1] + o[1], p[2] + o[2]];
  const k = Number(key.slice(1));
  if (key[0] === "h") (f.holes[k].positions_mm || []).forEach((p) => mark(add(p), `Ø${f.holes[k].dia_mm} depth ${f.holes[k].depth_mm}`));
  if (key[0] === "o") { const x = f.openings[k]; mark(add([x.x_mm + x.length_mm / 2, x.y_mm + x.width_mm / 2, info.bbox_mm[2]]), `opening ${x.length_mm} × ${x.width_mm}`, 0x15803d); }
  if (key[0] === "p") { const x = f.pockets[k]; mark(add([x.x_mm + x.length_mm / 2, x.y_mm + x.width_mm / 2, info.bbox_mm[2] - x.depth_mm]), `pocket depth ${x.depth_mm}`, 0xc2410c); }
  if (key[0] === "r") { const x = f.fillets[k]; mark(add(x.at_mm), `R${x.radius_mm}`, 0x7c3aed); }
}

async function upload(c) {
  const file = $("upFile").files[0], note = $("upNote").value.trim();
  if (!file) return status($("upStatus"), "Choose the corrected STEP file.", "error");
  if (!note) return status($("upStatus"), "Say what you changed.", "error");
  const fd = new FormData();
  fd.append("file", file); fd.append("note", note);
  status($("upStatus"), "Checking the solid and recalculating…");
  try {
    const r = await api(`/api/tool-designs/${design.id}/components/${c.id}/upload`, { method: "POST", body: fd });
    status($("upStatus"), `Rev ${r.rev} applied to ${r.applied_to} part(s). Size ${r.size_mm.before.join("×")} → ${r.size_mm.after.join("×")}; ${r.checks.errors} error(s), ${r.checks.warnings} warning(s) in the check.`, r.checks.errors ? "error" : "");
    await loadDesign(design.id, c.id, r.issues_for_this_part);
  } catch (err) {
    status($("upStatus"), err.message, "error");
  }
}

// ---------------------------------------------------------------- tabs
function partsTab() {
  const comps = design.components.filter((c) => !["work", "part"].includes(c.kind) || false);
  const groups = new Map();
  for (const c of design.components) {
    const g = c.stage_no ? `Stage ${c.stage_no}` : c.kind === "work" || c.kind === "part" ? "Reference" : c.kind === "proposal" ? "To be designed" : c.group === "upper" ? "Upper half" : "Lower half";
    groups.set(g, [...(groups.get(g) || []), c]);
  }
  $("tab-parts").innerHTML = `<table class="cost-table"><thead><tr><th>Part no.</th><th>Name</th><th>Rev</th><th>Kind</th></tr></thead><tbody>
    ${[...groups.entries()].map(([g, list]) => `<tr><th colspan="4">${esc(g)}</th></tr>` + list.map((c) => `<tr class="clickable" data-id="${c.id}" ${c.id === selected ? 'class="sel"' : ""}>
      <td>${esc(c.part_no)}${c.instance > 1 ? ` #${c.instance}` : ""}</td><td>${esc(c.name)}</td><td>${esc(c.rev)}${c.edited ? " ✎" : ""}</td><td>${esc(c.kind)}</td></tr>`).join("")).join("")}</tbody></table>`;
  document.querySelectorAll("#tab-parts tr[data-id]").forEach((tr) => tr.addEventListener("click", () => {
    const id = Number(tr.dataset.id);
    select(id);
    const m = meshes.get(id);
    if (m) { const c = new THREE.Box3().setFromObject(m.mesh).getCenter(new THREE.Vector3()); controls.target.copy(c); }
  }));
}

function bomTab() {
  const b = design.bill, t = b.totals, cur = b.currency;
  const base = `/api/tool-designs/${design.id}`;
  $("tab-bom").innerHTML = `
    <div class="tiles"><div class="card tile"><div class="label">Made parts</div><div class="value">${t.made_parts}</div><div class="sub">${t.made_qty} pieces</div></div>
      <div class="card tile"><div class="label">Raw steel</div><div class="value">${fmt(t.steel_kg, 0)} kg</div><div class="sub">${cur} ${fmt(t.material_cost)}</div></div>
      <div class="card tile"><div class="label">Machining</div><div class="value">${cur} ${fmt(t.machining_cost)}</div><div class="sub">estimate</div></div>
      <div class="card tile"><div class="label">Bought-out</div><div class="value">INR ${fmt(t.standard_cost_inr)}</div><div class="sub">${b.standard.length} items</div></div></div>
    <h4>Purchase orders</h4>
    <ul class="links"><li><a class="link" href="${base}/files/po-material">PO-1 Raw material (PDF)</a></li><li><a class="link" href="${base}/files/po-machining">PO-2 Machining (PDF)</a></li>
      <li><a class="link" href="${base}/files/po-bought-out">PO-3 Bought-out (PDF)</a></li><li><a class="link" href="${base}/files/xlsx">Purchase pack (Excel)</a></li>
      <li><a class="link" href="${base}/files/assembly-pdf">Assembly sheet with BOM (PDF)</a></li><li><a class="link" href="${base}/supplier-package.zip"><b>Supplier package (ZIP: STEP, drawings, DXF, POs)</b></a></li></ul>
    <h4>Made parts</h4><table class="cost-table"><thead><tr><th>#</th><th>Part no.</th><th>Name</th><th class="num">Qty</th><th>Steel</th><th class="num">Stock kg</th></tr></thead><tbody>
    ${b.made.map((m, i) => `<tr class="clickable" data-id="${m.ids[0]}"><td>${i + 1}</td><td>${esc(m.part_no)}</td><td>${esc(m.name)}</td><td class="num">${m.qty}</td><td>${esc(m.info.steel)}</td><td class="num">${fmt(m.info.stock.weight_kg, 1)}</td></tr>`).join("")}</tbody></table>
    <h4>Bought-out parts</h4><table class="cost-table"><thead><tr><th>Item</th><th>Specification</th><th class="num">Qty</th><th class="num">INR</th></tr></thead><tbody>
    ${b.standard.map((l) => `<tr><td>${esc(l.item)}</td><td>${esc(l.spec)}</td><td class="num">${l.quantity}</td><td class="num">${fmt(l.amount_inr)}</td></tr>`).join("")}</tbody></table>
    <h4>Assembly in your factory (${fmt(t.assembly_hours, 1)} h)</h4><ol>${b.assembly.map((a) => `<li>${esc(a.text)} <span class="note">${a.hours} h</span></li>`).join("")}</ol>
    <h4>Supplier quotes</h4>
    <p class="note">Send the purchase pack (Excel) to the supplier. They type their prices in the yellow-header “Quoted …” columns. Upload the file back here: the quotes sit
      next to the estimate (sheet “Quote comparison”) and can become your approved steel rates and bought-out prices.</p>
    <input type="file" id="qFile" accept=".xlsx" /><input id="qSupplier" placeholder="Supplier name" />
    <button class="btn btn-outline small" id="qGo" type="button">Read quotes</button>
    <button class="btn btn-primary small" id="qApply" type="button" ${design.quotes?.length ? "" : "disabled"}>Use quotes as approved rates and prices</button> <span class="status" id="qStatus"></span>
    ${design.quotes?.length ? `<table class="cost-table"><thead><tr><th>Supplier</th><th>Kind</th><th>Part / item</th><th class="num">Quoted</th></tr></thead><tbody>
      ${design.quotes.map((q) => `<tr><td>${esc(q.supplier)}</td><td>${esc(q.kind)}</td><td>${esc(q.key)}</td><td class="num">${fmt(q.value, 2)} ${esc(q.currency)}</td></tr>`).join("")}</tbody></table>` : ""}`;
  $("qGo")?.addEventListener("click", async () => {
    const f = $("qFile").files[0], sup = $("qSupplier").value.trim();
    if (!f || !sup) return status($("qStatus"), "Choose the workbook and enter the supplier name.", "error");
    const fd = new FormData(); fd.append("file", f); fd.append("supplier", sup);
    try { const r = await api(`/api/tool-designs/${design.id}/quotes`, { method: "POST", body: fd }); status($("qStatus"), `${r.quotes} quoted price(s) read${r.skipped.length ? `, ${r.skipped.length} skipped` : ""}.`); await loadDesign(design.id, selected); document.querySelector('[data-tab="bom"]').click(); }
    catch (err) { status($("qStatus"), err.message, "error"); }
  });
  $("qApply")?.addEventListener("click", async () => {
    if (!confirm("Make the quoted steel rates approved rates of the tool country and the quoted bought-out prices the Standard parts prices?")) return;
    try { const r = await api(`/api/tool-designs/${design.id}/quotes/apply`, { method: "POST" }); status($("qStatus"), `Applied: ${r.steel_rates.length} steel rate(s), ${r.standard_parts.length} standard part price(s)${r.machining_ratio ? `; machining quoted at ${fmt(r.machining_ratio * 100, 0)} % of the estimate` : ""}.`); }
    catch (err) { status($("qStatus"), err.message, "error"); }
  });
  document.querySelectorAll("#tab-bom tr[data-id]").forEach((tr) => tr.addEventListener("click", () => { select(Number(tr.dataset.id)); }));
}

function checksTab() {
  const ch = design.summary.checks || { issues: [] };
  $("tab-checks").innerHTML = `<p>${ch.errors ? `<b class="issue-error">${ch.errors} error(s)</b>` : "No errors"} · ${ch.warnings || 0} warning(s) <span class="note">checked ${esc(ch.at || "")} · ${ch.components_checked || 0} parts</span></p>
    <ul>${(ch.issues || []).map((i) => `<li class="issue-${i.level}">${esc(i.text)}</li>`).join("") || "<li>Valid solids, no overlapping parts.</li>"}</ul>
    <p class="note">The check looks for invalid solids and for parts that overlap. Standard parts are included. Run it again after every correction (done automatically on upload).</p>`;
}

function reviewTab() {
  const items = design.review || [], draft = design.status === "draft", f = design.summary.fea;
  const open = items.filter((r) => r.blocking && !["ok", "na", "waived"].includes(r.status)).length;
  $("tab-review").innerHTML = `<p><b>${open ? `${open} blocking item(s) not signed off` : "All blocking items are signed off"}</b> <span class="note">Release needs every blocking row ok, not applicable or waived with a reason.</span></p>
    ${f && f.max_deflection_mm != null ? `<p class="note">Structural check (Gmsh + CalculiX): deflection ${fmt(f.max_deflection_mm, 4)} mm (limit ${fmt(f.deflection_limit_mm, 3)}), von Mises ${fmt(f.max_von_mises_mpa, 0)} MPa (limit ${fmt(f.stress_limit_mpa, 0)}) · <a class="link" href="/api/tool-designs/${design.id}/fea.vtk">result for ParaView</a></p>` : f ? `<p class="note">${esc(f.note || "")}</p>` : ""}
    <table class="cost-table"><thead><tr><th>Check</th><th>Status</th><th>Decision</th></tr></thead><tbody>
    ${items.map((r) => `<tr><td>${esc(r.text)}${r.blocking ? "" : ' <span class="note">(not blocking)</span>'}<br/><span class="note">${r.kind === "auto" ? "automatic" : "toolmaker"}${r.detail ? ` · ${esc(r.detail)}` : ""}${r.by ? ` · ${esc(r.by)} ${esc((r.at || "").slice(0, 10))}` : ""}${r.comment ? ` · “${esc(r.comment)}”` : ""}</span></td>
      <td><span class="badge ${r.status === "ok" ? "released" : r.status === "issue" || r.status === "open" ? "draft" : "superseded"}">${esc(r.status)}</span></td>
      <td>${draft ? `<input class="rv-note" data-id="${r.id}" placeholder="comment" style="width:100%" />
        <button type="button" class="btn btn-outline small rv" data-id="${r.id}" data-s="ok">OK</button><button type="button" class="btn btn-outline small rv" data-id="${r.id}" data-s="issue">Issue</button>
        <button type="button" class="btn btn-outline small rv" data-id="${r.id}" data-s="na">N/A</button><button type="button" class="btn btn-outline small rv" data-id="${r.id}" data-s="waived">Waive</button>` : ""}</td></tr>`).join("")}</tbody></table>`;
  document.querySelectorAll(".rv").forEach((b) => b.addEventListener("click", async () => {
    const id = Number(b.dataset.id), comment = document.querySelector(`.rv-note[data-id="${id}"]`).value;
    try { await api(`/api/tool-designs/${design.id}/review/${id}`, { method: "POST", body: JSON.stringify({ status: b.dataset.s, comment }) }); await loadDesign(design.id, selected); document.querySelector('[data-tab="review"]').click(); }
    catch (err) { status($("status"), err.message, "error"); }
  }));
}

function render() {
  const d = design, s = d.summary;
  $("title").textContent = `${s.part_code || ""} · ${d.kind === "mould" ? "mould" : "sheet-metal die"} (${d.part_type.replace("_", " ")})`;
  $("subtitle").innerHTML = `Version ${d.version} · drawing revision ${esc(d.rev_label)} <span class="badge ${d.status}">${esc(d.status)}</span> · tool country ${esc(d.country)} · rates ${esc(d.as_of)} ·
    ${d.kind === "mould" ? `mould base ${esc(s.mould_base)}, ${s.cavities} cavity(ies)` : `${esc((s.mode || "").replace("_", " "))}, ${s.stages} stage(s), ${fmt(s.total_force_t, 1)} t`}`;
  const base = `/api/tool-designs/${d.id}`;
  $("dlMenu").innerHTML = `<a class="link" href="${base}/supplier-package.zip"><b>Supplier package (ZIP)</b></a><a class="link" href="${base}/assembly.step">Whole tool assembly (STEP)</a>
    <a class="link" href="${base}/assembly.step?reference=true">Assembly with part / workpiece (STEP)</a><a class="link" href="${base}/files/xlsx">Purchase pack (Excel)</a>
    <a class="link" href="${base}/files/po-material">PO raw material (PDF)</a><a class="link" href="${base}/files/po-machining">PO machining (PDF)</a><a class="link" href="${base}/files/po-bought-out">PO bought-out (PDF)</a>
    <a class="link" href="${base}/files/assembly-pdf">Assembly sheet (PDF)</a>`;
  $("release").disabled = d.status !== "draft";
  $("newrev").disabled = d.status === "draft";
  $("banner").innerHTML = (d.status === "draft" ? `<div class="warn">DRAFT: not released. Correct and check it, then release it before you issue purchase orders.</div>`
    : d.status === "released" ? `<div class="info">Released as drawing revision ${esc(d.rev_label)} by ${esc(d.released_by)} on ${esc((d.released_at || "").slice(0, 10))}. To change a part, start a new revision.</div>`
    : `<div class="info">Superseded by a newer release.</div>`) + (s.example ? `<div class="warn">Uses example rates – not for negotiation</div>` : "") + (s.notes ? `<div class="info">${esc(s.notes)}</div>` : "");
  partsTab(); bomTab(); reviewTab(); checksTab(); renderMeasure();
}

// ---------------------------------------------------------------- loading and actions
async function loadList() {
  const list = await api(`/api/parts/${partId}/tool-designs`);
  $("version").innerHTML = list.map((d) => `<option value="${d.id}">v${d.version} · rev ${esc(d.rev_label)} · ${esc(d.status)}</option>`).join("") || '<option value="">no design yet</option>';
  return list;
}

async function loadDesign(id, keepSelected = null) {
  status($("status"), "Loading the 3D model…");
  try {
    [design, payload] = await Promise.all([api(`/api/tool-designs/${id}`), api(`/api/tool-designs/${id}/mesh`)]);
  } catch (err) {
    return status($("status"), err.message, "error");
  }
  designId = id; partId = design.part_id;
  history.replaceState(null, "", `?part=${partId}&design=${id}`);
  $("backLink").href = `/parts?part=${partId}`;
  status($("status"), "");
  const sel = keepSelected && design.components.some((c) => c.id === keepSelected) ? keepSelected : null;
  selected = sel;
  render(); buildScene(); resize();
  if (sel) select(sel); else $("detail").hidden = true;
  await loadList().then(() => ($("version").value = String(id)));
}

$("version").addEventListener("change", (e) => e.target.value && loadDesign(Number(e.target.value)));
$("generate").addEventListener("click", async () => {
  if (!partId) return;
  status($("status"), "Generating the tool design: simulation, 3D, drawings… (about a minute)");
  $("generate").disabled = true;
  try {
    const d = await api(`/api/parts/${partId}/tool-designs`, { method: "POST", body: JSON.stringify({}) });
    await loadDesign(d.id);
  } catch (err) {
    status($("status"), err.message, "error");
  }
  $("generate").disabled = false;
});
$("check").addEventListener("click", async () => {
  status($("status"), "Checking all parts…");
  try { await api(`/api/tool-designs/${design.id}/check`, { method: "POST" }); await loadDesign(design.id, selected); document.querySelector('[data-tab="checks"]').click(); }
  catch (err) { status($("status"), err.message, "error"); }
});
$("release").addEventListener("click", async () => {
  if (!confirm("Release this design as the drawing revision for your suppliers? A released design cannot be edited; a new revision is started from it.")) return;
  try {
    await api(`/api/tool-designs/${design.id}/release`, { method: "POST", body: JSON.stringify({ accept_warnings: false }) });
    await loadDesign(design.id, selected);
  } catch (err) {
    if (/warning/.test(err.message) && confirm(err.message + "\n\nRelease anyway?")) {
      await api(`/api/tool-designs/${design.id}/release`, { method: "POST", body: JSON.stringify({ accept_warnings: true }) });
      await loadDesign(design.id, selected);
    } else status($("status"), err.message, "error");
  }
});
$("newrev").addEventListener("click", async () => {
  try { const d = await api(`/api/tool-designs/${design.id}/new-revision`, { method: "POST", body: JSON.stringify({}) }); await loadDesign(d.id); }
  catch (err) { status($("status"), err.message, "error"); }
});
document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  document.querySelectorAll(".tab").forEach((t) => (t.hidden = t.id !== `tab-${b.dataset.tab}`));
}));
document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
$("fit").addEventListener("click", () => setView("iso"));
for (const id of ["wire", "showRef", "showStd"]) $(id).addEventListener("change", applyVisibility);
$("explode").addEventListener("input", applyExplode);
$("secAxis").addEventListener("change", applySection);
$("secPos").addEventListener("input", applySection);
$("measureBtn").addEventListener("click", () => {
  measureOn = !measureOn; measurePts = [];
  $("measureBtn").classList.toggle("btn-primary", measureOn); $("measureBtn").classList.toggle("btn-outline", !measureOn);
  $("hud").textContent = measureOn ? "Click the first point" : "";
  if (measureOn) document.querySelector('[data-tab="measure"]').click();
});
$("isolate").addEventListener("click", () => {
  if (!selected) return;
  for (const { mesh } of meshes.values()) mesh.userData.hidden = mesh.userData.id !== selected;
  applyVisibility();
});
$("showAll").addEventListener("click", () => { for (const { mesh } of meshes.values()) mesh.userData.hidden = false; applyVisibility(); });

(async () => {
  resize();
  if (designId) return loadDesign(designId);
  if (!partId) return status($("status"), "Open this page from a part (Parts → the part → Production tool design).", "error");
  const list = await loadList().catch((err) => (status($("status"), err.message, "error"), []));
  if (list.length) return loadDesign((list.find((d) => d.status === "released") || list[0]).id);
  $("banner").innerHTML = `<div class="info">No tool design yet for this part. Click <b>Generate new design</b> to create the 3D components, drawings, bill of materials and purchase-order data.</div>`;
})();
