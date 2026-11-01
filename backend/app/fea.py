"""Structural check of the load-carrying tool parts with real FEA (roadmap stage 45): Gmsh meshes the part, CalculiX solves it.

    parts     moulds: cavity insert, core insert and B plate; sheet-metal dies: die plate and bottom shoe (the tool parts whose name
              starts with one of the names in fea_parts of Mould & die database → Design rules, per part type)
    load      the clamp / press force of the tool cost (try-out machine force) ÷ cavities, as a pressure on the outside faces of the
              moulding / forming faces seen from that side inside the part's outline (the workpiece size in the tool design), its
              clamp-direction part (side pressures on opposite walls cancel); total force = that force
    support   inserts and the die plate sit in their pocket on their flat back face (found from the geometry), held there; the B plate and the bottom shoe rest
              on two strips along their long edges, as wide as the spacer blocks (moulds) or fea_support_strip_mm (dies)
    result    largest deflection (mm) and largest von Mises stress (MPa) against fea_max_deflection_mm and fea_allow_stress_mpa;
              steel stiffness fea_e_mpa and fea_poisson; element size fea_mesh_mm (all Design rules, EXAMPLE)
    programs  Gmsh (Python package `gmsh`) and CalculiX (`ccx`: on the PATH, in DTC_CCX, or ccx*.exe in <data folder>/tools/calculix
              or <app>/tools/calculix). Without them the check says it is not available and how to install them; nothing is
              estimated instead.
Every run is stored (tool_fea_runs, append only) with its picture; the toolmaker review reads the latest run of the revision.
"""

from __future__ import annotations

import io
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import select

from . import auth, mould_db
from . import projects_db as db

EXAMPLE = "EXAMPLE - replace with your toolroom's limits and steel data"
PART_TYPES = ("plastic", "die_casting", "foundry", "eps", "blow", "sheet_metal")
NUM = (("fea_e_mpa", 210000.0, "MPa", "FEA: Young's modulus of the tool steel"),
       ("fea_poisson", 0.3, "-", "FEA: Poisson's ratio of the tool steel"),
       ("fea_mesh_mm", 10.0, "mm", "FEA: largest element size of the mesh"),
       ("fea_max_deflection_mm", 0.05, "mm", "FEA: largest allowed deflection of a load-carrying tool part"),
       ("fea_allow_stress_mpa", 300.0, "MPa", "FEA: largest allowed von Mises stress (yield ÷ safety factor)"),
       ("fea_support_strip_mm", 60.0, "mm", "FEA: width of the support strips under a plate that spans (when no spacer block gives it)"))
PARTS = {"sheet_metal": "Die plate, Bottom shoe"}
DEFAULT_PARTS = "Cavity insert, Core insert, B plate (core side)"
SPANNING = ("b plate", "bottom shoe")
INSTALL = ("Install the free programs: Gmsh (in the app's Python: pip install gmsh; Windows kit: DTC_Install_FEA.bat) and CalculiX "
           "(ccx, from the official CalculiX site; on Windows put ccx.exe in DTC_Data\\tools\\calculix, or set DTC_CCX to its path).")


class FeaError(ValueError):
    pass


# ---------- master data ----------

def seed() -> int:
    """Add the FEA Design rules rows that are missing (existing rows are never changed)."""
    d = mould_db.tables()
    have = {(r["part_type"], r["parameter"]) for r in d["design_rules"]}
    new = []
    for pt in PART_TYPES:
        for name, value, unit, desc in NUM:
            if (pt, name) not in have:
                new.append({"part_type": pt, "parameter": name, "value": value, "text": "", "unit": unit, "description": desc, "is_example": True})
        if (pt, "fea_parts") not in have:
            new.append({"part_type": pt, "parameter": "fea_parts", "value": None, "text": PARTS.get(pt, DEFAULT_PARTS), "unit": "",
                        "description": "FEA: tool parts checked (names as in the tool design, comma separated)", "is_example": True})
    if new:
        d["design_rules"] += new
        mould_db.write(d)
    return len(new)


def rules(part_type: str) -> dict:
    r = mould_db.design_rules(part_type)
    missing = [k for k, *_ in NUM if k not in r or r[k].get("value") in (None, "")] + ([] if "fea_parts" in r else ["fea_parts"])
    if missing:
        raise FeaError(f"Mould & die database → Design rules has no {', '.join(missing)} for '{part_type}'.")
    out = {k: float(r[k]["value"]) for k, *_ in NUM}
    out["parts"] = [x.strip().lower() for x in str(r["fea_parts"].get("text") or "").split(",") if x.strip()]
    out["is_example"] = any(bool(r[k].get("is_example")) for k in [*(n for n, *_ in NUM), "fea_parts"])
    return out


# ---------- programs ----------

def ccx_path() -> str | None:
    env = os.environ.get("DTC_CCX", "").strip()
    if env and Path(env).exists():
        return env
    for name in ("ccx", "ccx.exe", "ccx_static", "ccx_2.21", "ccx_2.22"):
        p = shutil.which(name)
        if p:
            return p
    roots = [Path(os.environ[k]) / "tools" / "calculix" for k in ("DTC_DATA_FOLDER",) if os.environ.get(k)]
    roots.append(Path(__file__).resolve().parents[2] / "tools" / "calculix")
    for root in roots:
        if root.exists():
            hits = sorted(root.rglob("ccx*.exe")) + sorted(root.rglob("ccx"))
            if hits:
                return str(hits[0])
    return None


def available() -> dict:
    try:
        import gmsh  # noqa: F401
        g = True
    except Exception:          # not installed, or its graphics libraries are missing
        g = False
    c = ccx_path()
    ok = g and bool(c)
    return {"available": ok, "gmsh": g, "ccx": c, "message": "" if ok else
            "Real FEA is not available on this computer: " + ", ".join(x for x, have in (("Gmsh", g), ("CalculiX", bool(c))) if not have)
            + " missing. " + INSTALL}


# ---------- one part ----------

_MESHER = r"""
import json, sys
import gmsh
step, size, algo, out = sys.argv[1], float(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
gmsh.initialize(["-noenv"])
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("part")
gmsh.model.occ.importShapes(step)
gmsh.model.occ.synchronize()
gmsh.option.setNumber("Mesh.MeshSizeMax", size)
gmsh.option.setNumber("Mesh.Algorithm", algo)
gmsh.option.setNumber("Mesh.SecondOrderLinear", 1)       # mid-side nodes on straight edges: no inverted elements on curved faces
gmsh.model.mesh.generate(3)
gmsh.model.mesh.setOrder(2)
tags, coords, _ = gmsh.model.mesh.getNodes()
etypes, etags, enodes = gmsh.model.mesh.getElements(3)
elems = []
for et, tg, nd in zip(etypes, etags, enodes):
    if et == 11:                                         # 10-node tetrahedron
        elems += [[int(e)] + [int(x) for x in nd[10 * i:10 * i + 10]] for i, e in enumerate(tg)]
json.dump({"tags": [int(t) for t in tags], "coords": [float(c) for c in coords], "elems": elems}, open(out, "w"))
gmsh.finalize()
"""
# Attempts, each in a fresh Gmsh process (a failed mesh leaves Gmsh unusable): element size factor and surface method
# (6 Frontal-Delaunay, 1 MeshAdapt). Small features (cooling holes next to faces) need a finer mesh.
ATTEMPTS = ((1.0, 6), (1.0, 1), (0.5, 6), (0.5, 1), (0.25, 6))


def _mesh(shape, size: float):
    """Second-order tetrahedra of a CadQuery shape: (nodes {id: (x, y, z)}, elements [(id, [10 node ids])], element size used).
    Gmsh runs in its own Python process: it needs the main thread (signals) and keeps one global model."""
    import json
    import sys
    import cadquery as cq
    last = "no message"
    with tempfile.TemporaryDirectory() as tmp:
        step, out = Path(tmp) / "part.step", Path(tmp) / "mesh.json"
        cq.exporters.export(cq.Workplane("XY").add(shape), str(step), exportType="STEP")
        for factor, algo in ATTEMPTS:
            out.unlink(missing_ok=True)
            try:
                r = subprocess.run([sys.executable, "-c", _MESHER, str(step), str(size * factor), str(algo), str(out)],
                                   capture_output=True, text=True, timeout=600)
            except subprocess.TimeoutExpired:
                raise FeaError("Gmsh took more than 10 minutes: make fea_mesh_mm larger.") from None
            if r.returncode == 0 and out.exists():
                m = json.loads(out.read_text())
                if m["elems"]:
                    c = m["coords"]
                    nodes = {t: (c[3 * i], c[3 * i + 1], c[3 * i + 2]) for i, t in enumerate(m["tags"])}
                    return nodes, [(e[0], e[1:]) for e in m["elems"]], size * factor
            last = ((r.stderr or r.stdout).strip().splitlines() or ["no volume mesh"])[-1][:300]
    raise FeaError(f"Gmsh could not mesh the part (also with a finer mesh): {last}")


# Gmsh 10-node tetra order -> CalculiX C3D10 order (Gmsh swaps the last two edge nodes)
_ORDER = (0, 1, 2, 3, 4, 5, 6, 7, 9, 8)


def _inp(nodes, elems, fixed_z, pins, loads, E, nu, held: bool = False) -> str:
    """held = the support nodes are held in x, y and z (an insert in its pocket); else only z, plus two pins against sliding."""
    out = ["*NODE"] + [f"{i},{x:.6f},{y:.6f},{z:.6f}" for i, (x, y, z) in nodes.items()]
    out += ["*ELEMENT, TYPE=C3D10, ELSET=EALL"] + [f"{e}," + ",".join(str(n[k]) for k in _ORDER) for e, n in elems]
    out += ["*NSET, NSET=NALL"] + [",".join(str(i) for i in list(nodes)[k:k + 12]) for k in range(0, len(nodes), 12)]
    out += ["*MATERIAL, NAME=STEEL", "*ELASTIC", f"{E:g},{nu:g}", "*SOLID SECTION, ELSET=EALL, MATERIAL=STEEL", "*BOUNDARY"]
    out += [f"{i},1,3,0" if held else f"{i},3,3,0" for i in fixed_z]
    if not held:
        out += [f"{pins[0]},1,2,0", f"{pins[1]},2,2,0"]
    out += ["*STEP", "*STATIC", "*CLOAD"] + [f"{i},3,{f:.6f}" for i, f in sorted(loads.items())]
    out += ["*NODE PRINT, NSET=NALL", "U", "*EL PRINT, ELSET=EALL", "S", "*END STEP"]
    return "\n".join(out) + "\n"


def _vm(sx, sy, sz, txy, txz, tyz) -> float:
    return math.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3 * (txy ** 2 + txz ** 2 + tyz ** 2))


def _parse_dat(text: str) -> tuple[dict, float]:
    """(displacement {node: (ux, uy, uz)}, largest element-average von Mises stress) from the CalculiX .dat file.
    The stress of an element is the average of its integration points: a sharp inside corner gives a single-point peak
    that is a property of the mesh, not of the steel."""
    disp, acc, mode = {}, {}, None
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith("displacements"):
            mode = "u"
            continue
        if low.startswith("stresses"):
            mode = "s"
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            nums = [float(x) for x in parts]
        except ValueError:
            continue
        if mode == "u" and len(nums) == 4:
            disp[int(nums[0])] = tuple(nums[1:])
        elif mode == "s" and len(nums) == 8:
            a = acc.setdefault(int(nums[0]), [0.0] * 7)
            for k in range(6):
                a[k] += nums[2 + k]
            a[6] += 1
    vm = max((_vm(*(a[k] / a[6] for k in range(6))) for a in acc.values() if a[6]), default=0.0)
    return disp, vm


# mid-side node of each edge of a 10-node tetrahedron, in Gmsh's order (positions 4-9)
_MID = {frozenset((0, 1)): 4, frozenset((1, 2)): 5, frozenset((0, 2)): 6, frozenset((0, 3)): 7, frozenset((2, 3)): 8, frozenset((1, 3)): 9}
# faces of a tetrahedron (corner positions 0-3) as CalculiX numbers them: P1 = 1-2-3, P2 = 1-4-2, P3 = 2-4-3, P4 = 3-4-1
_FACES = ((1, (0, 1, 2), 3), (2, (0, 3, 1), 2), (3, (1, 3, 2), 0), (4, (2, 3, 0), 1))


def _visible(faces, nodes, toward: float, cell: float) -> list:
    """The faces seen from the moulding / forming side: a face is hidden when another face nearer to that side covers its centre
    (seen along z). The melt or the sheet touches the visible faces; hidden ones (the lower half of a cooling bore, a floor under an
    overhang) carry no cavity pressure."""
    grid = {}
    for k, f in enumerate(faces):
        xs, ys = [c[0] for c in f[5]], [c[1] for c in f[5]]
        for gx in range(int(min(xs) // cell), int(max(xs) // cell) + 1):
            for gy in range(int(min(ys) // cell), int(max(ys) // cell) + 1):
                grid.setdefault((gx, gy), []).append(k)

    def covers(f, x, y):
        (ax, ay, _), (bx, by, _), (cx, cy, _) = f[5]
        d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(d) < 1e-12:
            return False
        l1 = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / d
        l2 = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / d
        return l1 >= -1e-9 and l2 >= -1e-9 and 1 - l1 - l2 >= -1e-9

    out = []
    for k, f in enumerate(faces):
        x, y, z = f[4]
        h = -z * toward
        hidden = any(j != k and -faces[j][4][2] * toward > h + 1e-3 and covers(faces[j], x, y)
                     for j in grid.get((int(x // cell), int(y // cell)), ()))
        if not hidden:
            out.append(f)
    return out


def _boundary_faces(nodes, elems):
    """[(element, face no, area, outward normal, centroid)] of the faces on the outside of the mesh."""
    seen = {}
    for e, n in elems:
        for face, idx, opp in _FACES:
            key = tuple(sorted(n[k] for k in idx))
            mids = [n[_MID[frozenset((idx[0], idx[1]))]], n[_MID[frozenset((idx[1], idx[2]))]], n[_MID[frozenset((idx[2], idx[0]))]]]
            seen.setdefault(key, []).append((e, face, [n[k] for k in idx], n[opp], mids))
    out = []
    for hits in seen.values():
        if len(hits) != 1:
            continue
        e, face, corners, opp, mids = hits[0]
        a, b, c = (nodes[k] for k in corners)
        u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        nx, ny, nz = u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]
        ln = math.sqrt(nx * nx + ny * ny + nz * nz)
        if ln == 0:
            continue
        cen = tuple((a[k] + b[k] + c[k]) / 3 for k in range(3))
        o = nodes[opp]
        if (o[0] - cen[0]) * nx + (o[1] - cen[1]) * ny + (o[2] - cen[2]) * nz > 0:     # make the normal point outwards
            nx, ny, nz = -nx, -ny, -nz
        out.append((e, face, ln / 2, (nx / ln, ny / ln, nz / ln), cen, (a, b, c), mids))
    return out


def _picture(nodes, disp, top, title) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    xs = [nodes[i][0] for i in top]
    ys = [nodes[i][1] for i in top]
    uz = [math.sqrt(sum(v * v for v in disp.get(i, (0, 0, 0)))) * 1000 for i in top]           # total movement, as in the table
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=110)
    sc = ax.tricontourf(xs, ys, uz, levels=14, cmap="viridis") if len(set(uz)) > 1 else ax.scatter(xs, ys, c=uz, s=6)
    fig.colorbar(sc, ax=ax, label="Deflection of the loaded (moulding / forming) face (µm)")
    ax.set_aspect("equal")
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    ax.set_title(title, fontsize=10)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def check_part(shape, size, force_n: float, patch: tuple, strip: float | None, R: dict, title: str = "") -> dict:
    """FEA of one part. size = (L, W, H); patch = (l, w) of the part's outline, centred; strip = support strip width along the two
    long edges of the bottom face (a plate that spans), None = the part sits on its flat back face.

    Support: a spanning plate rests on its bottom face strips; any other part on whichever of its two end faces (bottom / top) is the
    larger flat face - its back; the moulding or forming side is the other one. Load: a pressure on the outside faces of the
    loaded side inside the outline, scaled so that its total force along z is the clamp / press force (cavity pressure)."""
    av = available()
    if not av["available"]:
        raise FeaError(av["message"])
    nodes, elems, mesh_mm = _mesh(shape, R["fea_mesh_mm"])
    zmin = min(p[2] for p in nodes.values())
    zmax = max(p[2] for p in nodes.values())
    xmin, xmax = min(p[0] for p in nodes.values()), max(p[0] for p in nodes.values())
    ymin, ymax = min(p[1] for p in nodes.values()), max(p[1] for p in nodes.values())
    tol = max(1e-3, mesh_mm * 1e-3)
    faces = _boundary_faces(nodes, elems)
    on = lambda f, z: abs(f[4][2] - z) < tol and abs(abs(f[3][2]) - 1) < 1e-6
    area_bottom = sum(f[2] for f in faces if on(f, zmin) and f[3][2] < 0)
    area_top = sum(f[2] for f in faces if on(f, zmax) and f[3][2] > 0)
    back_top = not strip and area_top > area_bottom * 1.05           # cavity-side insert: its flat back is the top face
    zs = zmax if back_top else zmin
    sup = [i for i, p in nodes.items() if abs(p[2] - zs) < tol]
    long_x = (xmax - xmin) >= (ymax - ymin)
    if strip:
        edge = (lambda p: p[1] - ymin <= strip or ymax - p[1] <= strip) if long_x else (lambda p: p[0] - xmin <= strip or xmax - p[0] <= strip)
        sup = [i for i in sup if edge(nodes[i])]
    if len(sup) < 3:
        raise FeaError("Too few support nodes: make fea_mesh_mm smaller.")
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    toward = 1.0 if back_top else -1.0                               # the load pushes toward the support
    # the part's outline; a blanking die plate is open there, the cutting force then sits on the ring around the opening:
    # the area grows until it holds faces to load
    for grow in (1.0, 1.25, 1.5, 2.0, 1e9):
        pl, pw = min(patch[0] * grow, xmax - xmin), min(patch[1] * grow, ymax - ymin)
        inside = lambda c: abs(c[0] - cx) <= pl / 2 + tol and abs(c[1] - cy) <= pw / 2 + tol
        cand = [f for f in faces if inside(f[4]) and f[3][2] * toward < -0.3 and not abs(f[4][2] - zs) < tol]
        loaded = _visible(cand, nodes, toward, mesh_mm / 2)
        if loaded:
            break
    proj = sum(f[2] * abs(f[3][2]) for f in loaded)
    if not loaded or proj <= 0:
        raise FeaError("No face to load inside the part outline.")
    p = force_n / proj                                               # MPa (N/mm²): total z force = force_n
    # the clamp-direction part of the pressure only (side pressures on opposite walls cancel in the mould): per face
    # p × projected area, on its three mid-side nodes (the consistent load of a 6-node triangle puts nothing on the corners)
    loads = {}
    for f in loaded:
        share = p * f[2] * abs(f[3][2]) / 3 * toward
        for m in f[6]:
            loads[m] = loads.get(m, 0.0) + share
    pins = sorted(sup, key=lambda i: (nodes[i][0], nodes[i][1]))
    pins = (pins[0], pins[-1])
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp) / "job"
        job.with_suffix(".inp").write_text(_inp(nodes, elems, sup, pins, loads, R["fea_e_mpa"], R["fea_poisson"],
                                                  held=not strip))
        try:
            run = subprocess.run([available()["ccx"], "-i", str(job)], cwd=tmp, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            raise FeaError("CalculiX took more than 10 minutes: make fea_mesh_mm larger.") from None
        dat = job.with_suffix(".dat")
        msg = (run.stdout + run.stderr).strip().splitlines()
        if run.returncode != 0 or not dat.exists() or any("*ERROR" in m for m in msg):
            raise FeaError("CalculiX stopped: " + (next((m for m in msg if "ERROR" in m), msg[-1] if msg else ""))[:300])
        disp, vm = _parse_dat(dat.read_text(errors="replace"))
    if not disp:
        raise FeaError("CalculiX gave no displacements.")
    defl = max(math.sqrt(u[0] ** 2 + u[1] ** 2 + u[2] ** 2) for u in disp.values())
    ok_d, ok_s = defl <= R["fea_max_deflection_mm"], vm <= R["fea_allow_stress_mpa"]
    face_nodes = [i for i, q in nodes.items() if abs(q[2] - (zmin if back_top else zmax)) < tol] or list(nodes)
    return {"max_deflection_mm": round(defl, 5), "max_von_mises_mpa": round(vm, 2), "limit_deflection_mm": R["fea_max_deflection_mm"],
            "limit_stress_mpa": R["fea_allow_stress_mpa"], "ok_deflection": ok_d, "ok_stress": ok_s, "ok": ok_d and ok_s,
            "force_n": round(force_n, 1), "pressure_mpa": round(p, 3), "loaded_area_mm": [round(pl, 1), round(pw, 1)],
            "support": "two edge strips" if strip else ("full back face (top)" if back_top else "full back face (bottom)"),
            "strip_mm": strip, "nodes": len(nodes), "elements": len(elems), "mesh_mm": mesh_mm, "is_example": R["is_example"],
            "png": _picture(nodes, disp, face_nodes, title or "FEA")}


# ---------- a tool design ----------

def _force_n(tr: dict, des: dict) -> tuple[float, str]:
    """Force on one cavity / die (N) from the tool cost's try-out machine force, and where it comes from."""
    if tr.get("dies"):
        die = next((d for d in tr["dies"] if d["key"] == des["key"]), None)
        t = float((die or {}).get("force_t") or 0)
        return t * 9806.65, f"press force of {des['name']} {t:.1f} t (tool cost)"
    t = float((tr.get("trial") or {}).get("force_t") or 0)
    cav = max(1, int(tr.get("cavities") or 1))
    return t * 9806.65 / cav, f"clamp force {t:.1f} t ÷ {cav} cavit{'y' if cav == 1 else 'ies'} (tool cost)"


def targets(des: dict, part_type: str) -> list:
    R = rules(part_type)
    return [c for c in des["components"] if c.kind == "made" and any(c.name.lower().startswith(x) for x in R["parts"])]


def run(part_id: int, progress=None) -> dict:
    """FEA of every load-carrying part of every tool of the part; each result stored with its picture.
    progress(pct, text) when it runs as a background job."""
    from . import register
    av = available()
    if not av["available"]:
        raise FeaError(av["message"])
    say = progress or (lambda pct, text: None)
    say(2, "Designing the tool(s)")
    d, rev, designs = register.tool_designs(part_id)
    tr = register.tool_trace(part_id)
    todo = sum(len(targets(des, des.get("part_type", ""))) for _, des in designs)
    done = 0
    out = []
    for _, des in designs:
        pt = des.get("part_type", "")
        R = rules(pt)
        force, source = _force_n(tr, des)
        if force <= 0:
            raise FeaError(f"{des['name']}: the tool cost has no clamp / press force to load the parts with.")
        ref = next((c for c in des["components"] if c.kind == "ref"), None)
        patch = (ref.size[0], ref.size[1]) if ref else (1e9, 1e9)
        spacer = next((c for c in des["components"] if c.name.lower().startswith("spacer block")), None)
        for c in targets(des, pt):
            strip = None
            if any(c.name.lower().startswith(s) for s in SPANNING):
                strip = min(spacer.size[0], spacer.size[1]) if spacer else R["fea_support_strip_mm"]
            say(5 + 90 * done / max(1, todo), f"{des['name']}: {c.name} - meshing (Gmsh) and solving (CalculiX), part {done + 1} of {todo}")
            res = check_part(c.shape, c.size, force, patch, strip, R, f"{d['part_code']} rev {rev['rev']} · {c.name}")
            done += 1
            png = res.pop("png")
            res |= {"load_source": source}
            with db.engine().begin() as conn:
                rid = conn.execute(db.tool_fea_runs.insert().values(part_id=part_id, rev=rev["rev"], tool_key=des["key"], item=c.no, name=c.name,
                                                                    result=res, png=png, by=auth.username() or "local user")).inserted_primary_key[0]
                auth.log(conn, "part", part_id, "fea_run", {"tool": des["key"], "item": c.no, "ok": res["ok"]})
            out.append({"id": rid, "tool_key": des["key"], "tool": des["name"], "item": c.no, "name": c.name} | res)
    return {"part_id": part_id, "rev": rev["rev"], "runs": out}


def latest(part_id: int, rev: str | None = None) -> dict:
    """{(tool key, item): latest stored run} of the revision (None = any)."""
    with db.engine().connect() as conn:
        q = select(db.tool_fea_runs.c.id, db.tool_fea_runs.c.rev, db.tool_fea_runs.c.tool_key, db.tool_fea_runs.c.item, db.tool_fea_runs.c.name,
                   db.tool_fea_runs.c.result, db.tool_fea_runs.c.by, db.tool_fea_runs.c.at).where(db.tool_fea_runs.c.part_id == part_id)
        if rev:
            q = q.where(db.tool_fea_runs.c.rev == rev)
        rows = conn.execute(q.order_by(db.tool_fea_runs.c.id)).mappings().all()
    return {(r["tool_key"], r["item"]): {"id": r["id"], "rev": r["rev"], "name": r["name"], "by": r["by"],
                                         "at": r["at"].isoformat(timespec="seconds") if r["at"] else None} | dict(r["result"] or {}) for r in rows}


def picture(part_id: int, run_id: int) -> bytes:
    with db.engine().connect() as conn:
        r = conn.execute(select(db.tool_fea_runs.c.png).where((db.tool_fea_runs.c.id == run_id) & (db.tool_fea_runs.c.part_id == part_id))).first()
    if not r or not r[0]:
        raise FeaError("No such FEA run.")
    return r[0]


def summary(part_id: int) -> dict:
    """What the page shows: programs, rules, the parts to check per tool and their latest run on the current revision."""
    from . import register
    d, rev, designs = register.tool_designs(part_id)
    runs = latest(part_id, rev["rev"])
    tools = []
    for _, des in designs:
        pt = des.get("part_type", "")
        R = rules(pt)
        tools.append({"key": des["key"], "name": des["name"], "parts": [
            {"item": c.no, "name": c.name, "run": runs.get((des["key"], c.no))} for c in targets(des, pt)],
            "rules": {k: R[k] for k, *_ in NUM}, "is_example": R["is_example"]})
    return {"part_id": part_id, "rev": rev["rev"], "programs": available(), "tools": tools}


def facts(part_id: int, rev: str, des: dict) -> dict:
    """For the toolmaker review: parts to check, parts checked on this revision, parts over a limit."""
    try:
        want = targets(des, des.get("part_type", ""))
    except FeaError:
        return {"fea_targets": 0.0, "fea_checked": 0.0, "fea_bad": 0.0}
    runs = latest(part_id, rev)
    got = [runs[(des["key"], c.no)] for c in want if (des["key"], c.no) in runs]
    return {"fea_targets": float(len(want)), "fea_checked": float(len(got)), "fea_bad": float(sum(1 for r in got if not r.get("ok")))}
