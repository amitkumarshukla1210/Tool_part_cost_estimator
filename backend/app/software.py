"""Free software used by the design tools, and what is installed on this PC (roadmap stage 20).

Nothing here is bundled: `status()` only looks for each tool and says what it is used for, its licence and how to install
it. Required tools are installed by `pip install -r requirements.txt`; optional ones add deeper checks.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import shutil
import subprocess

# id, name, job in Design to Cost, licence, python module, executable, install, required, group
TOOLS = [
    ("cadquery", "CadQuery + OpenCascade", "3D solids: STEP read / write, booleans, draft correction, hidden-line views", "Apache-2.0 / LGPL",
     "cadquery", None, "pip install cadquery", True, "3D design"),
    ("shapely", "Shapely", "2D geometry: flat patterns, strip layout, clearance offsets", "BSD-3", "shapely", None, "pip install shapely", True, "3D design"),
    ("numpy", "NumPy", "Ray casting for wall thickness, draft and undercut maps", "BSD-3", "numpy", None, "pip install numpy", True, "Simulation"),
    ("matplotlib", "Matplotlib", "Coloured simulation pictures, 3D renders, video frames", "PSF-based", "matplotlib", None,
     "pip install matplotlib", True, "Simulation"),
    ("imageio_ffmpeg", "imageio-ffmpeg (FFmpeg)", "Encodes the simulation video (MP4, H.264)", "BSD-2 / LGPL FFmpeg", "imageio_ffmpeg", "ffmpeg",
     "pip install imageio-ffmpeg", True, "Video"),
    ("ezdxf", "ezdxf", "DXF drawings: blank, strip, stage and part drawings", "MIT", "ezdxf", None, "pip install ezdxf", True, "Drawings"),
    ("reportlab", "ReportLab", "PDF reports and drawing sheets", "BSD", "reportlab", None, "pip install reportlab", True, "Downloads"),
    ("openpyxl", "openpyxl", "Excel downloads", "MIT", "openpyxl", None, "pip install openpyxl", True, "Downloads"),
    ("pptx", "python-pptx", "PowerPoint downloads", "MIT", "pptx", None, "pip install python-pptx", True, "Downloads"),
    ("threejs", "three.js", "3D viewer page (bundled in frontend/vendor/three)", "MIT", None, None, "bundled", True, "3D report"),
    ("trimesh", "trimesh", "Mesh repair and checks before meshing for FEA", "MIT", "trimesh", None, "pip install trimesh", False, "Simulation"),
    ("gmsh", "Gmsh", "Run by the app: meshes inserts and die blocks for the structural check", "GPL-2+", "gmsh", "gmsh", "pip install gmsh", False, "Simulation"),
    ("calculix", "CalculiX (ccx)", "Run by the app: solves the insert / die block check (deflection, von Mises); results also as VTK", "GPL-2+", None, "ccx",
     "apt install calculix-ccx  |  conda install -c conda-forge calculix", False, "Simulation"),
    ("freecad", "FreeCAD", "Not run by the app: opens the STEP files; SheetMetal workbench unfolds complex parts, FEM workbench for deeper analysis", "LGPL-2+", None, "freecadcmd",
     "apt install freecad  |  https://www.freecad.org", False, "3D design"),
    ("openfoam", "OpenFOAM / openInjMoldSim", "3D mould-filling research solver (not production grade)", "GPL-3", None, "simpleFoam",
     "https://www.openfoam.com", False, "Simulation"),
    ("paraview", "ParaView", "Not run by the app: opens the fea_result.vtk file (deflection, von Mises)", "BSD-3", None, "paraview", "apt install paraview", False, "Simulation"),
    ("libreoffice", "LibreOffice", "Converts the PowerPoint / Excel downloads to PDF if you want", "MPL-2", None, "soffice",
     "apt install libreoffice", False, "Downloads"),
    ("tesseract", "Tesseract OCR", "Scanned-PDF BOM extraction (harness and PCB)", "Apache-2.0", None, "tesseract", "apt install tesseract-ocr", False, "Harness"),
]


def _version(module: str) -> str:
    for name in {module, module.replace("_", "-"), {"pptx": "python-pptx"}.get(module, module)}:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return ""


def _exe_version(exe: str) -> str:
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=5)
        return (out.stdout or out.stderr).splitlines()[0][:60] if (out.stdout or out.stderr) else ""
    except Exception:
        return ""


def ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def status() -> list[dict]:
    out = []
    for tid, name, job, lic, module, exe, install, required, group in TOOLS:
        found, version, where = False, "", ""
        if tid == "threejs":
            from .outputs3d import VENDOR
            found, where = (VENDOR / "three.module.js").exists(), str(VENDOR)
        else:
            if module:
                try:
                    importlib.import_module(module)
                    found, version = True, _version(module)
                except Exception as exc:
                    where = f"import failed: {str(exc)[:80]} (Gmsh needs libGLU: apt install libglu1-mesa)" if tid == "gmsh" else ""
            if tid == "imageio_ffmpeg" and not found:
                where, found = (shutil.which("ffmpeg") or ""), bool(shutil.which("ffmpeg"))
            if not found and exe and not module:
                where = (ffmpeg() if tid == "imageio_ffmpeg" else None) or shutil.which(os.environ.get(f"DTC_{tid.upper()}", exe)) or ""
                found = bool(where)
        out.append({"id": tid, "name": name, "used_for": job, "licence": lic, "group": group, "required": required,
                    "installed": found, "version": version, "location": where, "install": install})
    return out


def mesh_check(shape) -> dict:
    """Optional: mesh the corrected part with Gmsh (when installed) to prove it is ready for FEA. Never raises."""
    try:
        import gmsh
    except Exception:
        return {"available": False, "note": "Gmsh not installed (pip install gmsh): FEA meshing skipped."}
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        path = Path(d, "part.step")
        import cadquery as cq
        cq.exporters.export(cq.Workplane("XY").add(shape), str(path))
        try:
            gmsh.initialize(interruptible=False)
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.open(str(path))
            bb = shape.BoundingBox()
            size = max(bb.xlen, bb.ylen, bb.zlen) / 12
            gmsh.option.setNumber("Mesh.MeshSizeMax", size)
            gmsh.model.mesh.generate(3)
            types, tags, _ = gmsh.model.mesh.getElements(3)
            tets = sum(len(t) for t in tags)
            nodes = len(gmsh.model.mesh.getNodes()[0])
            return {"available": True, "tetrahedra": tets, "nodes": nodes, "element_size_mm": round(size, 2),
                    "note": "Volume mesh generated: the corrected part can go to CalculiX / FreeCAD FEM."}
        except Exception as exc:
            return {"available": True, "note": f"Gmsh could not mesh the part: {str(exc)[:100]}"}
        finally:
            try:
                gmsh.finalize()
            except Exception:
                pass
