import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

// Typical densities in g/cm³ — a starting point, always check the material datasheet.
const MATERIALS = {
  plastic: [
    ["PP (polypropylene)", 0.905],
    ["ABS", 1.04],
    ["PC (polycarbonate)", 1.2],
    ["PC/ABS", 1.13],
    ["PA6", 1.13],
    ["PA66 GF30", 1.36],
    ["PBT GF30", 1.53],
    ["POM (acetal)", 1.41],
  ],
  die_casting: [
    ["Aluminium ADC12 / A383", 2.74],
    ["Aluminium A380", 2.71],
    ["Zinc Zamak 3", 6.6],
    ["Magnesium AZ91D", 1.81],
  ],
  foundry: [
    ["Grey cast iron FG260", 7.2],
    ["SG / ductile iron", 7.1],
    ["Cast steel", 7.85],
    ["Aluminium LM6 / A356", 2.68],
    ["Bronze", 8.8],
  ],
  sheet_metal: [
    ["Mild steel CRCA / HR", 7.85],
    ["Galvanised steel GI", 7.85],
    ["Stainless steel 304", 7.93],
    ["Aluminium 5052", 2.68],
    ["Copper", 8.96],
  ],
};

const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) => Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

function fillMaterials() {
  const list = MATERIALS[$("partType").value];
  $("material").innerHTML =
    '<option value="">— enter density manually —</option>' +
    list.map(([name, rho]) => `<option value="${rho}">${name} (${rho})</option>`).join("");
  $("material").value = String(list[0][1]);
  $("density").value = list[0][1];
}
$("partType").addEventListener("change", fillMaterials);
$("material").addEventListener("change", () => {
  if ($("material").value) $("density").value = $("material").value;
});
$("density").addEventListener("input", () => ($("material").value = ""));
fillMaterials();

// ---------- 3D viewer ----------
const container = $("viewer");
let renderer, scene, camera, controls, partGroup;

function initViewer() {
  container.innerHTML = "";
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setClearColor(0xf7f9fb);
  container.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(1, 2, 3);
  scene.add(sun);

  camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100000);
  camera.up.set(0, 0, 1); // CAD convention: Z is up
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  new ResizeObserver(resize).observe(container);
  resize();
  (function loop() {
    requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  })();
}

function resize() {
  const { clientWidth: w, clientHeight: h } = container;
  if (!w || !h) return;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

function showMesh(mesh) {
  if (!renderer) initViewer();
  if (partGroup) scene.remove(partGroup);

  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.Float32BufferAttribute(mesh.positions, 3));
  geom.setIndex(mesh.indices);
  geom.computeVertexNormals();

  partGroup = new THREE.Group();
  partGroup.add(
    new THREE.Mesh(geom, new THREE.MeshStandardMaterial({ color: 0x8fa9c4, metalness: 0.2, roughness: 0.55, side: THREE.DoubleSide })),
    new THREE.LineSegments(new THREE.EdgesGeometry(geom, 25), new THREE.LineBasicMaterial({ color: 0x2b3a4a })),
  );

  geom.computeBoundingBox();
  const box = geom.boundingBox;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const diag = size.length() || 1;

  const helper = new THREE.Box3Helper(box, 0xff8c00);
  helper.material.transparent = true;
  helper.material.opacity = 0.5;
  partGroup.add(helper, new THREE.AxesHelper(diag * 0.25));
  scene.add(partGroup);

  controls.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(1, -1.4, 0.9).normalize().multiplyScalar(diag * 1.6));
  camera.near = diag / 1000;
  camera.far = diag * 100;
  camera.updateProjectionMatrix();
}

// ---------- Form ----------
$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = $("file").files[0];
  if (!file) return;

  const body = new FormData();
  body.append("file", file);
  body.append("part_type", $("partType").value);
  body.append("density", $("density").value);

  setStatus("Reading STEP file and calculating…");
  $("submit").disabled = true;
  try {
    const res = await fetch("/api/analyze", { method: "POST", body });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    showResults(data.metrics);
    showMesh(data.mesh);
    setStatus(`${data.file_name} · ${data.part_type_label}`);
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    $("submit").disabled = false;
  }
});

function setStatus(msg, isError = false) {
  $("status").textContent = msg;
  $("status").classList.toggle("error", isError);
}

function showResults(m) {
  $("r-volume").textContent = `${fmt(m.volume_cm3, 3)} cm³  (${fmt(m.volume_mm3, 0)} mm³)`;
  $("r-weight").textContent =
    m.net_weight_g >= 1000 ? `${fmt(m.net_weight_kg, 3)} kg` : `${fmt(m.net_weight_g, 2)} g`;
  const b = m.bbox_mm;
  $("r-bbox").textContent = `${fmt(b.length, 1)} × ${fmt(b.width, 1)} × ${fmt(b.height, 1)} mm`;
  $("r-proj").textContent = `${fmt(m.projected_area_cm2, 2)} cm²  (along ${m.pull_direction.toUpperCase()})`;
  $("r-surface").textContent = `${fmt(m.surface_area_mm2 / 100, 2)} cm²`;
  $("r-solids").textContent = m.solid_count;
  $("r-axes").innerHTML = ["x", "y", "z"]
    .map(
      (a) => `<tr class="${a === m.pull_direction ? "pull" : ""}">
        <td>${a.toUpperCase()}</td>
        <td>${fmt(m.bbox_axes_mm[a], 1)}</td>
        <td>${fmt(m.projected_area_mm2[a] / 100, 2)}</td></tr>`,
    )
    .join("");
  $("results").hidden = false;
}
