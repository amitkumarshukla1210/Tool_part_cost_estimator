import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) => Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

// Material presets (density) come from the master data file; their RATES come from the approved rate library.
let materials = [];
let rmMeta = null;
let registerInfo = null;

async function loadMaterials() {
  try {
    const res = await fetch("/api/master-data");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);
    materials = data.Materials;
    rmMeta = await (await fetch("/api/rm/meta")).json();
    $("country").innerHTML = rmMeta.countries
      .map((c) => `<option value="${c.code}" ${c.code === rmMeta.default_country ? "selected" : ""}>${c.name} (${c.currency})</option>`).join("");
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
const loaded = loadMaterials().then(openRegisteredPart);

// ---------- 3D viewer ----------
const container = $("viewer");
let renderer, scene, camera, controls, partGroup;

// Viewer colours come from the Design to Cost theme variables.
const themeColor = (name) => new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue(name).trim());

function initViewer() {
  container.innerHTML = "";
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setClearColor(themeColor("--grey-light"));
  container.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(themeColor("--white"), themeColor("--grey"), 1.6));
  const sun = new THREE.DirectionalLight(themeColor("--white"), 1.6);
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
    new THREE.Mesh(geom, new THREE.MeshStandardMaterial({ color: themeColor("--table-row-hover"), metalness: 0.15, roughness: 0.6, side: THREE.DoubleSide })),
    new THREE.LineSegments(new THREE.EdgesGeometry(geom, 25), new THREE.LineBasicMaterial({ color: themeColor("--ink") })),
  );

  geom.computeBoundingBox();
  const box = geom.boundingBox;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const diag = size.length() || 1;

  const helper = new THREE.Box3Helper(box, themeColor("--accent"));
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
    await startStageB(data, chosenMaterial());
    showMesh(data.mesh);
    setStatus(`${data.file_name} · ${data.part_type_label}`);
    $("fileInfo").textContent = `${data.file_name} · ${data.part_type_label} · density ${data.metrics.density_g_cm3} g/cm³`;
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
      (a) => `<tr class="${a === m.pull_direction ? "total" : ""}">
        <td>${a.toUpperCase()}${a === m.pull_direction ? " · opening direction" : ""}</td>
        <td class="calc num">${fmt(m.bbox_axes_mm[a], 1)}</td>
        <td class="calc num">${fmt(m.projected_area_mm2[a] / 100, 2)}</td></tr>`,
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
let baseline = {}; // what the form showed after loading: only edited fields are sent, so defaults stay "master data"
let lastB = null; // last RM result (its trace opens in the traceability panel)
let lastCurrency = "";

const ESTIMATED = ["thickness_mm", "blank_length_mm", "blank_width_mm"];
const RATE_VARIABLE = { material_rate_per_kg: "material_rate", scrap_rate_per_kg: "scrap_rate" };

async function startStageB(data, material) {
  analysis = data;
  const type = data.metrics.part_type;
  // Re-read every time so changes saved on the Master data page apply at once.
  const defaultsB = await (await fetch("/api/gross-weight/defaults")).json();

  // Only show the inputs and result rows that belong to this part type.
  document.querySelectorAll("#stageB [data-types]").forEach((el) => {
    el.hidden = !el.dataset.types.split(" ").includes(type);
  });
  document.querySelectorAll("#stageB [data-label]").forEach((el) => {
    el.textContent = LABELS[el.dataset.label][type] ?? "";
  });

  // Fresh defaults (from Master data → Parameters) for each analysed part. Rates stay empty: the approved library rate is used.
  for (const input of formB.elements) if (input.name) input.value = "";
  for (const [key, value] of Object.entries(defaultsB[type])) if (formB.elements[key]) formB.elements[key].value = value;
  if (data.sheet_metal) {
    formB.elements.thickness_mm.value = data.sheet_metal.thickness_mm;
    formB.elements.blank_length_mm.value = data.sheet_metal.blank_mm.length;
    formB.elements.blank_width_mm.value = data.sheet_metal.blank_mm.width;
    $("sheetHint").textContent =
      "Thickness and flat blank size were estimated from the 3D model. Check them against the drawing or flat pattern.";
  }
  baseline = Object.fromEntries([...formB.elements].filter((i) => i.name).map((i) => [i.name, i.value]));
  applyRegisteredInputs();

  $("stageB").hidden = false;
  await calculateB();
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
$("country").addEventListener("change", () => analysis && calculateB());
$("asOf").addEventListener("change", () => analysis && calculateB());

async function calculateB() {
  const m = analysis.metrics;
  const body = { part_type: m.part_type, net_weight_g: m.net_weight_g, density_g_cm3: m.density_g_cm3,
    material: chosenMaterial()?.material ?? registered?.material ?? "", country: $("country").value, estimated: [] };
  if ($("asOf").value.trim()) body.as_of = $("asOf").value.trim();
  for (const input of formB.querySelectorAll("label:not([hidden]) input")) {
    if (input.value === "") continue;
    const same = input.value === baseline[input.name];
    if (ESTIMATED.includes(input.name)) {
      body[input.name] = Number(input.value);
      if (same) body.estimated.push(input.name); // still the value estimated from the 3D file
    } else if (!same) {
      body[input.name] = input.type === "number" ? Number(input.value) : input.value; // only what you changed
    }
  }

  try {
    const res = await fetch("/api/gross-weight", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(errorText(data.detail));
    lastB = data;
    lastCurrency = data.currency;
    $("statusB").textContent = data.missing.join(" ");
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

// A value that opens the traceability panel on click.
const traced = (id, text) => `<button type="button" class="tv" data-node="${id}">${text}</button>`;

function showResultsB(r) {
  const n = r.nodes;
  const money = (v) => `${r.currency} ${fmt(v, 2)}`;
  const set = (el, node, text) => ($(el).innerHTML = n[node] ? traced(node, text) : text);
  set("b-net", "in:net_weight_g", grams(r.net_weight_g));
  set("b-gross", "calc:gross_g", grams(r.gross_weight_g));
  set("b-returns", "calc:returns_g", grams(r.returns_scrap_g));
  $("b-loss").innerHTML = r.process_loss_g === undefined ? "" : traced("calc:loss_g", grams(r.process_loss_g));
  set("b-input", "calc:input_g", grams(r.material_input_g));
  set("b-yield", "calc:material_yield_pct", `${fmt(r.material_yield_pct, 1)} %`);
  if (r.nesting) {
    const k = r.nesting;
    set("b-nest", "in:blanks_per_sheet", `${k.per_sheet}  (${k.along} × ${k.across}${k.rotated ? ", blank turned 90°" : ""})`);
    set("b-sheet", "calc:sheet_weight_g", `${fmt(r.sheet_weight_kg, 2)} kg · ${fmt(r.sheet_utilisation_pct, 1)} % used`);
  }
  $("b-example").innerHTML = (r.rates_used || []).some((x) => x.is_example) ? window.exampleBanner("Replace the EXAMPLE rates on the Rates page.") : "";
  const rate = n["in:material_rate"];
  const rs = rate?.source;
  $("b-rate").innerHTML = r.priced || rs?.type === "user"
    ? traced("in:material_rate", `${money(rate.value)} / kg`) +
      (rs?.type === "rate" ? ` <span class="note">${rs.rate.month}${rs.rate.is_example ? ' <span class="badge badge-example">EXAMPLE</span>' : ""}</span>`
        : ' <span class="note">your input</span>')
    : "no approved rate";
  if (r.priced) {
    set("b-rm", "calc:rm_cost", money(r.rm_cost));
    set("b-credit", "calc:scrap_credit", `− ${money(r.scrap_credit)}`);
    $("b-net-rm").innerHTML = traced(r.root, money(r.net_rm_cost)) + (r.currency !== "INR" ? ` <span class="note">${fmt(r.value_inr, 2)} INR</span>` : "");
  } else {
    $("b-rm").textContent = "needs a material rate";
    $("b-credit").textContent = "";
    $("b-net-rm").textContent = "—";
  }
}

$("resultsB").addEventListener("click", (e) => {
  const b = e.target.closest("[data-node]");
  if (b && lastB) window.TracePanel.open(lastB, b.dataset.node);
});

// ---------- open a registered part / save back to it ----------
let registered = null;

async function openRegisteredPart() {
  const id = Number(new URLSearchParams(location.search).get("part"));
  if (!id) return;
  const banner = (text, msg = "", kind = "") => {
    $("partBanner").hidden = false;
    $("partBannerText").textContent = text;
    $("partBannerStatus").textContent = msg;
    $("partBannerStatus").className = `status ${kind}`;
  };
  try {
    registerInfo = await (await fetch("/api/register-meta")).json();
    registered = await (await fetch(`/api/parts/${id}`)).json();
    if (registered.detail) throw new Error(registered.detail);
    const family = registerInfo.processes.find((x) => x.code === registered.process)?.part_type;
    if (!registered.file_id) throw new Error("This part has no 3D file yet. Upload a revision on the Parts page.");
    if (!family) throw new Error("RM for this process comes in a later stage; choose a moulding, casting or sheet-metal process on the Parts page.");
    banner(`Estimating registered part ${registered.part_code} · ${registered.name} (rev ${registered.rev})`, "Loading its 3D file…");
    const blob = await (await fetch(`/api/files/${registered.file_id}`)).blob();
    const dt = new DataTransfer();
    dt.items.add(new File([blob], `${registered.part_code}.step`));
    $("file").files = dt.files;
    $("partType").value = family;
    fillMaterials();
    const idx = materials.findIndex((m) => m.material === registered.material && m.part_type === family);
    if (idx >= 0) {
      $("material").value = String(idx);
      $("density").value = materials[idx].density_g_cm3;
    }
    $("country").value = registered.country || registered.effective_country;
    $("asOf").value = registered.costing_month || "";
    $("savePart").hidden = false;
    $("form").requestSubmit();
    banner(`Estimating registered part ${registered.part_code} · ${registered.name} (rev ${registered.rev})`,
      "Its stored inputs are filled in. Change anything, then use Save to part.");
  } catch (err) {
    banner("Could not open the registered part", err.message, "error");
  }
}

// Stored per-part inputs go into the form after the first analysis.
function applyRegisteredInputs() {
  if (!registered?.rm_inputs) return;
  for (const [variable, value] of Object.entries(registered.rm_inputs)) {
    const name = Object.keys(RATE_VARIABLE).find((k) => RATE_VARIABLE[k] === variable) ?? variable;
    if (formB.elements[name]) formB.elements[name].value = value;
  }
}

$("savePartBtn").addEventListener("click", async () => {
  const inputs = {};
  for (const input of formB.querySelectorAll("label:not([hidden]) input")) {
    if (input.value === "" || input.value === baseline[input.name]) continue;
    inputs[RATE_VARIABLE[input.name] ?? input.name] = Number(input.value);
  }
  const status = $("partBannerStatus");
  status.textContent = "Saving…";
  try {
    const res = await fetch(`/api/parts/${registered.id}/rm-cost`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rm_inputs: inputs, country: $("country").value === rmMeta.default_country ? "" : $("country").value,
        costing_month: $("asOf").value.trim(), reason: "saved from the Estimate page" }) });
    const data = await res.json();
    if (!res.ok) throw new Error(errorText(data.detail));
    status.className = "status ok";
    status.innerHTML = `${data.message} <a class="link" href="/parts?part=${registered.id}">Open the part</a>`;
  } catch (err) {
    status.className = "status error";
    status.textContent = err.message;
  }
});

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

  document.querySelectorAll("#stageC [data-types]").forEach((el) => {
    el.hidden = !el.dataset.types.split(" ").includes(type);
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
  $("bomBlock").hidden = true;
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
    $("bomBlock").hidden = false;
    showMould(data);
  } catch (err) {
    $("statusM").textContent = err.message;
    $("resultsM").hidden = true;
    $("bomBlock").hidden = true;
  }
}

function showMould(r) {
  const cur = lastCurrency;
  const money = (v) => `${cur} ${int(v)}`;
  const L = r.layout;
  const b = r.base;
  const examples = r.example_lines + (r.sizing_rules_are_examples ? 1 : 0);
  $("m-examples").innerHTML = examples
    ? window.exampleBanner(`${r.example_lines} of ${r.lines.length} BOM lines` + (r.sizing_rules_are_examples ? " and the sizing rules" : "") +
      " use EXAMPLE placeholder values (marked •). Replace them in Master data → Mould &amp; die database.") : "";
  $("m-layout").textContent = `${L.rows} × ${L.cols}` + (L.empty ? ` (${L.empty} empty position)` : "");
  $("m-insert").textContent = `${fmt(L.each_l, 0)} × ${fmt(L.each_w, 0)} × ${fmt(L.half_h, 0)} mm`;
  $("m-pocket").textContent = `${fmt(L.pocket_l, 0)} × ${fmt(L.pocket_w, 0)} mm`;
  $("m-base").textContent =
    `${b.series} ${b.size_code} · ${b.width_mm} × ${b.length_mm} mm` + (r.base_turned ? " (layout turned 90°)" : "");
  $("m-plates").textContent = `${b.a_plate_mm} / ${b.b_plate_mm} mm · ${b.stack_height_mm} mm`;
  $("m-weight").textContent = `${fmt(b.weight_kg, 0)} kg`;
  const CATEGORY = { made: "Made", bought_out: "Bought-out", process: "Process" };
  const blank = (v, f) => (v ? f(v) : "");
  $("m-bom").innerHTML = r.lines
    .map((l) => `<tr><td>${l.element}${l.is_example ? '<span class="example-mark" title="Example value">•</span>' : ""}</td>` +
      `<td>${CATEGORY[l.category] ?? l.category}</td>` +
      `<td class="calc num">${fmt(l.quantity, l.quantity % 1 ? 2 : 0)}</td><td>${l.material || ""}</td>` +
      `<td class="calc num">${blank(l.material_cost, money)}</td><td class="calc num">${blank(l.bought_out_cost, money)}</td>` +
      `<td class="calc num">${blank(l.hours, (h) => fmt(h, 1))}</td><td class="calc num">${blank(l.process_cost, money)}</td>` +
      `<td class="calc num">${money(l.total)}</td></tr>`)
    .join("");
  const t = r.totals;
  $("m-total").innerHTML =
    `<tr class="total"><td>Total mould cost</td><td></td><td></td><td></td><td class="num">${money(t.material_cost)}</td>` +
    `<td class="num">${money(t.bought_out_cost)}</td><td class="num">${fmt(t.hours, 0)}</td>` +
    `<td class="num">${money(t.process_cost)}</td><td class="num">${money(t.total)}</td></tr>`;
  $("m-warnings").textContent = r.warnings.join(" ");
}
