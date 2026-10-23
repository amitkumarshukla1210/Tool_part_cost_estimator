"""Structural check of tool steel with free software (roadmap stage 20): Gmsh meshes the solid, CalculiX solves it.

    mould / die insert   fixed at its bottom face, cavity pressure on the cavity surface (every face that is not a plain face
                         of the insert's own box): deflection and von Mises stress against the limits in Parameters
    sheet-metal die      fixed at its bottom face, the stage force spread over the top face

Linear elastic, second-order tetrahedra (C3D10). A design check to find a plate or insert that is too weak, not a substitute
for a full FEA of the tool. Everything is skipped with a clear note when Gmsh or CalculiX is not installed.
Results are also written as a legacy VTK file that ParaView opens.
"""

from __future__ import annotations

import io
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import threading

import cadquery as cq
import numpy as np

_GMSH_LOCK = threading.Lock()          # Gmsh keeps global state: one mesh at a time

from . import master_data

PARAMS = {"fea_e_mpa": (210000.0, "MPa", "Young's modulus of tool steel"), "fea_poisson": (0.3, "", "Poisson's ratio of tool steel"),
          "fea_yield_mpa": (800.0, "MPa", "Yield strength of the insert steel (EXAMPLE: pre-hardened P20)"),
          "fea_safety": (1.5, "x", "Safety factor on yield"),
          "fea_max_deflection_mm": (0.05, "mm", "Allowed elastic deflection of an insert or die block")}
EXAMPLE = "EXAMPLE - replace with your tool-steel data"


def seed() -> int:
    """Add the FEA parameters (all part types that have tools) to Master data → Parameters if missing."""
    md = master_data.tables()
    have = {(r["part_type"], r["parameter"]) for r in md["Parameters"]}
    cols = list(md["Parameters"][0].keys())
    new = []
    for pt in ("plastic", "die_casting", "sheet_metal"):
        for k, (v, unit, desc) in PARAMS.items():
            if (pt, k) not in have:
                row = {c: "" for c in cols}
                row |= {"part_type": pt, "parameter": k, "value": v, "unit": unit, "description": desc, "notes": EXAMPLE}
                new.append(row)
    if new:
        md["Parameters"] = md["Parameters"] + new
        master_data.write(md)
    return len(new)


def tools() -> dict:
    ccx = os.environ.get("DTC_CCX") or shutil.which("ccx") or shutil.which("ccx_2.21")
    try:
        import gmsh  # noqa: F401
        gm = True
    except Exception:
        gm = False
    return {"gmsh": gm, "ccx": ccx}


def _mesh(shape: cq.Shape, size: float, workdir: Path):
    import gmsh
    path = workdir / "part.step"
    cq.exporters.export(cq.Workplane("XY").add(shape), str(path))
    _GMSH_LOCK.acquire()
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("m")
        gmsh.model.occ.importShapes(str(path))
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", size / 3)
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        gmsh.model.mesh.generate(3)
        gmsh.model.mesh.setOrder(2)
        ntags, ncoords, _ = gmsh.model.mesh.getNodes()
        coords = {int(t): ncoords[3 * i:3 * i + 3] for i, t in enumerate(ntags)}
        _, etags, enodes = gmsh.model.mesh.getElements(3, -1)
        tets = np.array(enodes[0], int).reshape(-1, 10)
        surfaces = {}
        for dim, tag in gmsh.model.getEntities(2):
            _, _, nodes = gmsh.model.mesh.getElements(2, tag)
            tri = np.array(nodes[0], int).reshape(-1, 6)[:, :3] if nodes else np.zeros((0, 3), int)
            surfaces[tag] = {"tri": tri, "centre": np.array(gmsh.model.occ.getCenterOfMass(2, tag)), "area": gmsh.model.occ.getMass(2, tag)}
        return coords, tets, surfaces
    finally:
        gmsh.finalize()
        _GMSH_LOCK.release()


def _is_box_face(face: cq.Face, bb) -> bool:
    """A plane lying on a side of the part's own bounding box."""
    if face.geomType() != "PLANE":
        return False
    n = face.normalAt()
    c = face.Center()
    for ax, (lo, hi, cv, nv) in enumerate(((bb.xmin, bb.xmax, c.x, n.x), (bb.ymin, bb.ymax, c.y, n.y), (bb.zmin, bb.zmax, c.z, n.z))):
        if abs(nv) > 0.999 and (abs(cv - lo) < 1e-3 or abs(cv - hi) < 1e-3):
            return True
    return False


def solve(shape: cq.Shape, pressure_mpa: float, load: str = "cavity", params: dict | None = None, element_size: float | None = None) -> dict:
    """Mesh and solve. load = 'cavity' (pressure on every non-box face) or 'top' (pressure on the top face)."""
    have = tools()
    if not have["gmsh"] or not have["ccx"]:
        missing = [n for n in ("gmsh", "ccx") if not have[n]]
        return {"available": False, "note": f"FEA skipped: {' and '.join(missing)} not installed "
                                            "(pip install gmsh + apt install libglu1-mesa; apt install calculix-ccx)."}
    p = params or {}
    E, nu = p.get("fea_e_mpa", 210000.0), p.get("fea_poisson", 0.3)
    bb = shape.BoundingBox()
    size = element_size or max(bb.xlen, bb.ylen, bb.zlen) / 10
    with tempfile.TemporaryDirectory() as d:
        wd = Path(d)
        coords, tets, surfaces = _mesh(shape, size, wd)
        # which surface entities take the pressure
        faces = shape.Faces()
        pressured = set()
        for tag, s in surfaces.items():
            f = min(faces, key=lambda f: (f.Center() - cq.Vector(*s["centre"])).Length)
            top = abs(f.normalAt().z) > 0.999 and abs(f.Center().z - bb.zmax) < 1e-3
            if (load == "cavity" and not _is_box_face(f, bb)) or (load == "top" and top):
                pressured.add(tag)
        # element faces (CalculiX C3D10 numbering: F1 1-2-3, F2 1-4-2, F3 2-4-3, F4 3-4-1; gmsh 9/10 swapped)
        tets = tets[:, [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]]
        face_of = {}
        for ei, t in enumerate(tets, start=1):
            for fn, idx in ((1, (0, 1, 2)), (2, (0, 3, 1)), (3, (1, 3, 2)), (4, (2, 3, 0))):
                face_of[frozenset(t[list(idx)])] = (ei, fn)
        dload, area = [], 0.0
        for tag in pressured:
            for tri in surfaces[tag]["tri"]:
                hit = face_of.get(frozenset(tri))
                if hit:
                    dload.append(hit)
        used = sorted({int(n) for t in tets for n in t})
        z0 = bb.zmin
        fixed = [n for n in used if coords[n][2] <= z0 + 1e-6]
        inp = io.StringIO()
        inp.write("*NODE, NSET=NALL\n" + "".join(f"{n}, {coords[n][0]:.6f}, {coords[n][1]:.6f}, {coords[n][2]:.6f}\n" for n in used))
        inp.write("*ELEMENT, TYPE=C3D10, ELSET=EALL\n" + "".join(f"{i}, " + ", ".join(map(str, t)) + "\n" for i, t in enumerate(tets, start=1)))
        inp.write(f"*MATERIAL, NAME=STEEL\n*ELASTIC\n{E}, {nu}\n*SOLID SECTION, ELSET=EALL, MATERIAL=STEEL\n")
        inp.write("*NSET, NSET=FIX\n" + "".join(f"{n},\n" for n in fixed))
        inp.write("*BOUNDARY\nFIX, 1, 3\n*STEP\n*STATIC\n*DLOAD\n")
        inp.write("".join(f"{e}, P{f}, {pressure_mpa:.6f}\n" for e, f in dload))
        inp.write("*NODE FILE\nU\n*EL FILE\nS\n*END STEP\n")
        (wd / "job.inp").write_text(inp.getvalue())
        run = subprocess.run([have["ccx"], "job"], cwd=wd, capture_output=True, text=True, timeout=300)
        frd = wd / "job.frd"
        if not frd.exists() or not dload or not fixed:
            return {"available": True, "ok": False, "note": f"CalculiX produced no result ({(run.stdout + run.stderr)[-160:].strip()}).",
                    "loaded_faces": len(dload), "fixed_nodes": len(fixed)}
        disp, vm = _read_frd(frd)
        umax = max(math.sqrt(x * x + y * y + z * z) for x, y, z in disp.values())
        vmax = max(vm.values()) if vm else 0.0
        vtk = _vtk(coords, tets, disp, vm)
    limit = p.get("fea_max_deflection_mm", 0.05)
    allow = p.get("fea_yield_mpa", 800.0) / p.get("fea_safety", 1.5)
    return {"available": True, "ok": umax <= limit and vmax <= allow, "max_deflection_mm": umax, "max_von_mises_mpa": vmax,
            "deflection_limit_mm": limit, "stress_limit_mpa": allow, "pressure_mpa": pressure_mpa, "elements": len(tets), "nodes": len(used),
            "loaded_faces": len(dload), "element_size_mm": round(size, 2), "vtk": vtk,
            "note": "Linear elastic C3D10 (Gmsh + CalculiX). Indicative design check."}


def _read_frd(path: Path):
    """Nodal displacements and von Mises stress from a CalculiX .frd (ASCII)."""
    disp, vm, block = {}, {}, None
    for line in path.read_text().splitlines():
        if line.startswith(" -4"):
            block = line.split()[1]
        elif line.startswith(" -1") and block in ("DISP", "STRESS"):
            node = int(line[3:13])
            vals = [float(line[13 + 12 * i:25 + 12 * i]) for i in range((len(line) - 13) // 12)]
            if block == "DISP" and len(vals) >= 3:
                disp[node] = tuple(vals[:3])
            elif block == "STRESS" and len(vals) >= 6:
                sxx, syy, szz, sxy, syz, szx = vals[:6]
                vm[node] = math.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3 * (sxy ** 2 + syz ** 2 + szx ** 2))
    return disp, vm


def _vtk(coords, tets, disp, vm) -> bytes:
    nodes = sorted({int(n) for t in tets for n in t[:4]})
    idx = {n: i for i, n in enumerate(nodes)}
    out = ["# vtk DataFile Version 3.0", "Design to Cost FEA", "ASCII", "DATASET UNSTRUCTURED_GRID", f"POINTS {len(nodes)} float"]
    out += [" ".join(f"{c:.5f}" for c in coords[n]) for n in nodes]
    out += [f"CELLS {len(tets)} {len(tets) * 5}"] + ["4 " + " ".join(str(idx[int(n)]) for n in t[:4]) for t in tets]
    out += [f"CELL_TYPES {len(tets)}"] + ["10"] * len(tets)
    out += [f"POINT_DATA {len(nodes)}", "VECTORS displacement_mm float"] + [" ".join(f"{x:.6e}" for x in disp.get(n, (0, 0, 0))) for n in nodes]
    out += ["SCALARS von_mises_mpa float 1", "LOOKUP_TABLE default"] + [f"{vm.get(n, 0.0):.4f}" for n in nodes]
    return ("\n".join(out) + "\n").encode()
