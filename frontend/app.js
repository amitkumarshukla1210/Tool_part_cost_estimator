import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) => Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

// Material presets (density, RM rate, scrap value) come from the master data file.
let materials = [];

async function loadMaterials() {
  try {
    const res = await fetch("/api/master-data");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);
    materials = data.Materials;
  } catch (err) {
    setStatus(`Master data could not be loaded: ${err.message}`, true);
  }
  fillMaterials();
}

function fillMaterials() {
  const list = materials.filter((m) => m.part_type === $("partType").value);
  $("material").innerHTML =
    '<option value="">— enter density manually —</option>' +
    list.map((m) => `<option value="${materials.indexOf(m)}">${m.material} (${m.density_g_cm3})</option>`).join("");
  if (list.length) {
    $("material").value = String(materials.indexOf(list[0]));
    $("density").value = list[0].density_g_cm3;
  }
}
const chosenMaterial = () => ($("material").value === "" ? null : materials[Number($("material").value)]);

$("partType").addEventListener("change", fillMaterials);
$("material").addEventListener("change", () => {
  if (chosenMaterial()) $("density").value = chosenMaterial().density_g_cm3;
});
$("density").addEventListener("input", () => ($("material").value = ""));
loadMaterials();

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

  // Distance at which the part's bounding sphere fits the narrower of the
  // two view angles, so tall or narrow windows don't crop the part.
  const vFov = THREE.MathUtils.degToRad(camera.fov);
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
  const dist = (diag / 2 / Math.sin(Math.min(vFov, hFov) / 2)) * 1.1;
  controls.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(1, -1.4, 0.9).normalize().multiplyScalar(dist));
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
    resetMould();
    startStageB(data, chosenMaterial());
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

// ---------- Stage B: gross weight & RM cost ----------
const LABELS = {
  process_loss_pct: { plastic: "Purge / start-up loss (%)", die_casting: "Melt loss (%)", foundry: "Melt loss (%)" },
  scrap_rate_per_kg: {
    plastic: "Regrind / scrap value per kg",
    die_casting: "Returns (runner, biscuit, overflow) value per kg",
    foundry: "Returns (gating, risers) value per kg",
    sheet_metal: "Scrap (skeleton, holes) value per kg",
  },
  returns: {
    plastic: "Runner / sprue",
    die_casting: "Biscuit, runners & overflows",
    foundry: "Gating & risers",
    sheet_metal: "Skeleton & punched-out scrap",
  },
};

const formB = $("formB");
let analysis = null; // last Stage A response
let timerB = null;

async function startStageB(data, material) {
  analysis = data;
  const type = data.metrics.part_type;
  // Re-read every time so changes saved on the Master data page apply at once.
  const defaultsB = await (await fetch("/api/gross-weight/defaults")).json();

  // Only show the inputs and result rows that belong to this part type.
  document.querySelectorAll("#stageB [class*='t-']").forEach((el) => {
    el.hidden = !el.classList.contains(`t-${type}`);
  });
  document.querySelectorAll("#stageB [data-label]").forEach((el) => {
    el.textContent = LABELS[el.dataset.label][type] ?? "";
  });

  // Fresh defaults for each analysed part. Rates come from the chosen
  // material; with density typed by hand, the last rates entered are kept.
  for (const [key, value] of Object.entries(defaultsB[type])) formB.elements[key].value = value;
  if (material) {
    formB.elements.material_rate_per_kg.value = material.rate_per_kg;
    formB.elements.scrap_rate_per_kg.value = material.scrap_rate_per_kg;
  }
  if (data.sheet_metal) {
    formB.elements.thickness_mm.value = data.sheet_metal.thickness_mm;
    formB.elements.blank_length_mm.value = data.sheet_metal.blank_mm.length;
    formB.elements.blank_width_mm.value = data.sheet_metal.blank_mm.width;
    $("sheetHint").textContent =
      "Thickness and flat blank size were estimated from the 3D model. Check them against the drawing or flat pattern.";
  }

  $("stageB").hidden = false;
  calculateB();
  startStageC(data);
}

formB.addEventListener("input", () => {
  clearTimeout(timerB);
  timerB = setTimeout(() => {
    calculateB();
    // Sheet-metal cavity layout uses the blank size from Stage B.
    if (analysis.metrics.part_type === "sheet_metal") calculateC();
  }, 300);
});

async function calculateB() {
  const m = analysis.metrics;
  const body = { part_type: m.part_type, net_weight_g: m.net_weight_g, density_g_cm3: m.density_g_cm3 };
  for (const input of formB.querySelectorAll("label:not([hidden]) input")) {
    if (input.value === "") continue;
    body[input.name] = input.type === "number" ? Number(input.value) : input.value;
  }

  try {
    const res = await fetch("/api/gross-weight", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(errorText(data.detail));
    $("statusB").textContent = "";
    $("resultsB").hidden = false;
    showResultsB(data);
  } catch (err) {
    $("statusB").textContent = err.message;
    $("resultsB").hidden = true;
  }
}

function errorText(detail) {
  // FastAPI sends a list of field errors for invalid inputs.
  if (Array.isArray(detail)) return detail.map((d) => `${d.loc.at(-1)}: ${d.msg}`).join("; ");
  return detail || "Calculation failed";
}

const grams = (g) => (g >= 1000 ? `${fmt(g / 1000, 3)} kg` : `${fmt(g, 2)} g`);

function showResultsB(r) {
  const money = (v) => `${r.currency} ${fmt(v, 2)}`;
  $("b-net").textContent = grams(r.net_weight_g);
  $("b-gross").textContent = grams(r.gross_weight_g);
  $("b-returns").textContent = grams(r.returns_scrap_g);
  $("b-loss").textContent = r.process_loss_g === undefined ? "" : grams(r.process_loss_g);
  $("b-input").textContent = grams(r.material_input_g);
  $("b-yield").textContent = `${fmt(r.material_yield_pct, 1)} %`;
  if (r.nesting) {
    const n = r.nesting;
    $("b-nest").textContent = `${n.per_sheet}  (${n.along} × ${n.across}${n.rotated ? ", blank turned 90°" : ""})`;
    $("b-sheet").textContent = `${fmt(r.sheet_weight_kg, 2)} kg · ${fmt(r.sheet_utilisation_pct, 1)} % used`;
  }
  const priced = r.inputs.material_rate_per_kg > 0;
  $("b-rm").textContent = priced ? money(r.rm_cost) : "enter material rate";
  $("b-credit").textContent = priced || r.scrap_credit ? `− ${money(r.scrap_credit)}` : "";
  $("b-net-rm").textContent = priced ? money(r.net_rm_cost) : "—";
}

// ---------- Stage C: cavities & number of tools ----------
const LABELS_C = {
  plastic: { cycle: "Cycle time per shot (s)", max: "Max cavities per mould", plate: "Mould plate", life: "Mould life (shots)" },
  die_casting: { cycle: "Cycle time per shot (s)", max: "Max cavities per die", plate: "Die plate", life: "Die life (shots)" },
  foundry: { cycle: "Moulding line cycle per mould (s)", max: "Max castings per mould", plate: "Moulding box (flask)", life: "Pattern life (moulds)" },
  sheet_metal: { cycle: "Time per stroke (s)", max: "Max parts per stroke", plate: "Die area / press bed", life: "Die life (strokes)" },
};

const formC = $("formC");
// Kept between parts once entered; everything else resets per part type.
const KEEP_C = ["annual_volume", "programme_years", "working_days", "shifts_per_day", "hours_per_shift"];
let timerC = null;

const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
const int = (n) => Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });

async function startStageC(data) {
  const type = data.metrics.part_type;
  const defaultsC = await (await fetch("/api/capacity/defaults")).json();
  const terms = defaultsC.terms[type];

  document.querySelectorAll("#stageC [class*='t-']").forEach((el) => {
    el.hidden = !el.classList.contains(`t-${type}`);
  });
  const text = {
    ...LABELS_C[type],
    "cavity-cap": cap(terms.cavity),
    "tool-cap": cap(terms.tool),
    "shot-cap": cap(terms.shot),
    "plate-lc": LABELS_C[type].plate.toLowerCase(),
  };
  document.querySelectorAll("#stageC [data-c]").forEach((el) => (el.textContent = text[el.dataset.c]));

  for (const [key, value] of Object.entries(defaultsC.by_part_type[type])) {
    if (!KEEP_C.includes(key) || formC.elements[key].value === "") formC.elements[key].value = value;
  }

  const p = data.process;
  if (p.cycle_time_s_estimate) {
    formC.elements.cycle_time_s.value = p.cycle_time_s_estimate;
    $("cycleNote").textContent =
      `Cycle time estimated from the ${fmt(p.wall_thickness_mm, 2)} mm main wall (cooling ≈ 2 × wall² s + 8 s). ` +
      "Replace it with your process or mould-flow figure.";
  } else {
    $("cycleNote").textContent = "Cycle time and tool life are typical values. Replace them with your own figures.";
  }

  $("stageC").hidden = false;
  calculateC();
}

formC.addEventListener("input", () => {
  clearTimeout(timerC);
  timerC = setTimeout(calculateC, 300);
});

function footprint() {
  const m = analysis.metrics;
  if (m.part_type === "sheet_metal") {
    const l = Number(formB.elements.blank_length_mm.value);
    const w = Number(formB.elements.blank_width_mm.value);
    $("footprintNote").textContent = `Layout uses the Stage B flat blank: ${fmt(l, 1)} × ${fmt(w, 1)} mm.`;
    return [l, w];
  }
  const f = analysis.process.footprint_mm;
  $("footprintNote").textContent =
    `Layout uses the part size across the parting plane: ${fmt(f.length, 1)} × ${fmt(f.width, 1)} mm ` +
    `(viewed along ${m.pull_direction.toUpperCase()}).`;
  return [f.length, f.width];
}

async function calculateC() {
  const [l, w] = footprint();
  const body = { part_type: analysis.metrics.part_type, footprint_length_mm: l, footprint_width_mm: w };
  for (const input of formC.querySelectorAll("label:not([hidden]) input")) {
    if (input.value !== "") body[input.name] = Number(input.value);
  }

  try {
    const res = await fetch("/api/capacity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(errorText(data.detail));
    $("statusC").textContent = "";
    $("resultsC").hidden = false;
    showResultsC(data);
  } catch (err) {
    $("statusC").textContent = err.message;
    $("resultsC").hidden = true;
  }
}

function showResultsC(r) {
  startMould(r);
  const t = r.terms;
  const lay = r.layout;
  $("c-planned").textContent = `${int(r.planned_hours_per_year)} h`;
  $("c-hours").textContent = `${int(r.available_hours_per_year)} h`;
  $("c-pph").textContent = `${fmt(r.required_parts_per_hour, 1)} parts / h`;
  $("c-needed").textContent = fmt(r.cavities_needed, 2);
  $("c-fit").textContent = `${r.cavities_fit_on_plate}  (${lay.along} × ${lay.across}${lay.rotated ? ", turned 90°" : ""})`;
  $("c-cav").textContent = r.cavities_per_tool + (r.limited_by ? `  (limited by ${r.limited_by})` : "");
  $("c-out").textContent = `${fmt(r.output_per_tool_per_hour, 1)} parts / h`;
  $("c-tools").textContent = r.tools_for_capacity;
  $("c-shots").textContent = int(r.shots_per_year);
  $("c-prog").textContent = `${int(r.programme_shots)}  (life ${int(r.inputs.tool_life_shots)} per ${t.tool.replace(/s$/, "")})`;
  $("c-sets").textContent = r.tool_sets_over_programme;
  $("c-dies").textContent = `${r.total_dies}  (${r.dies_per_set} per set)`;
  $("c-mh").textContent = `${int(r.machine_hours_per_year)} h`;
  $("c-util").textContent = `${fmt(r.machine_utilisation_pct, 1)} %` + (r.tools_for_capacity > 1 ? ` across ${r.tools_for_capacity} machines` : "");
}

// ---------- Mould / die size & BOM (from the mould database) ----------
const formM = $("formM");
let timerM = null;
let lastCavities = null;

// A new part starts from its own Stage C cavities and no side actions.
function resetMould() {
  formM.reset();
  formM.elements.cavities.value = "";
  lastCavities = null;
  $("resultsM").hidden = true;
}

function startMould(stageC) {
  const type = analysis.metrics.part_type;
  if (!["plastic", "die_casting"].includes(type)) {
    $("stageM").hidden = true;
    return;
  }
  // Follow Stage C until the user types their own cavity count.
  if (formM.elements.cavities.value === "" || Number(formM.elements.cavities.value) === lastCavities) {
    formM.elements.cavities.value = stageC.cavities_per_tool;
  }
  lastCavities = stageC.cavities_per_tool;
  formM.elements.hot_runner.closest("label").hidden = type !== "plastic";
  formM.elements.lifters_per_cavity.closest("label").hidden = type !== "plastic";
  $("stageM").hidden = false;
  clearTimeout(timerM);
  timerM = setTimeout(calculateMould, 200);
}

formM.addEventListener("input", () => {
  clearTimeout(timerM);
  timerM = setTimeout(calculateMould, 300);
});

async function calculateMould() {
  const m = analysis.metrics;
  const f = analysis.process.footprint_mm;
  const body = {
    part_type: m.part_type,
    cavities: Number(formM.elements.cavities.value),
    part_length_mm: f.length,
    part_width_mm: f.width,
    part_height_mm: m.bbox_axes_mm[m.pull_direction],
    projected_area_cm2: m.projected_area_cm2,
    part_weight_g: m.net_weight_g,
    hot_runner: formM.elements.hot_runner.checked && m.part_type === "plastic",
  };
  for (const k of ["slides_per_cavity", "lifters_per_cavity", "inserts_per_cavity"]) {
    body[k] = formM.elements[k].closest("label").hidden ? 0 : Number(formM.elements[k].value || 0);
  }
  try {
    const res = await fetch("/api/mould/estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(errorText(data.detail));
    $("statusM").textContent = "";
    $("resultsM").hidden = false;
    showMould(data);
  } catch (err) {
    $("statusM").textContent = err.message;
    $("resultsM").hidden = true;
  }
}

function showMould(r) {
  const cur = formB.elements.currency.value || "";
  const money = (v) => `${cur} ${int(v)}`;
  const L = r.layout;
  const b = r.base;
  const examples = r.example_lines + (r.sizing_rules_are_examples ? 1 : 0);
  $("m-examples").hidden = !examples;
  $("m-examples").textContent =
    `${r.example_lines} of ${r.lines.length} BOM lines` + (r.sizing_rules_are_examples ? " and the sizing rules" : "") +
    " still use EXAMPLE placeholder values (marked •). Replace them in Master data → Mould & die database.";
  $("m-layout").textContent = `${L.rows} × ${L.cols}` + (L.empty ? ` (${L.empty} empty position)` : "");
  $("m-insert").textContent = `${fmt(L.each_l, 0)} × ${fmt(L.each_w, 0)} × ${fmt(L.half_h, 0)} mm`;
  $("m-pocket").textContent = `${fmt(L.pocket_l, 0)} × ${fmt(L.pocket_w, 0)} mm`;
  $("m-base").textContent =
    `${b.series} ${b.size_code} · ${b.width_mm} × ${b.length_mm} mm` + (r.base_turned ? " (layout turned 90°)" : "");
  $("m-plates").textContent = `${b.a_plate_mm} / ${b.b_plate_mm} mm · ${b.stack_height_mm} mm`;
  $("m-weight").textContent = `${fmt(b.weight_kg, 0)} kg`;
  $("m-bom").innerHTML = r.lines
    .map((l) => `<tr class="${l.is_example ? "example" : ""}"><td>${l.element}</td><td>${fmt(l.quantity, l.quantity % 1 ? 2 : 0)}</td>` +
      `<td>${l.material || ""}</td><td>${l.hours ? fmt(l.hours, 1) : ""}</td><td>${money(l.total)}</td></tr>`)
    .join("");
  $("m-total").innerHTML =
    `<tr><td>Total</td><td></td><td></td><td>${fmt(r.totals.hours, 0)}</td><td>${money(r.totals.total)}</td></tr>`;
  $("m-split").textContent =
    `Material ${money(r.totals.material_cost)} · bought-out ${money(r.totals.bought_out_cost)} · ` +
    `process ${money(r.totals.process_cost)}`;
  $("m-warnings").textContent = r.warnings.join(" ");
}
