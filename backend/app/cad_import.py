"""Read a STEP file into a part tree: single part or assembly.

Assemblies are read with OpenCascade's XCAF reader, which keeps the product
structure. Instances of the same definition (4 identical pins) point to one
shared definition, so they become ONE part with quantity 4 in their parent.
Different definitions that look identical (same volume, area and size) are
flagged as look-alikes for the engineer to confirm; they are never merged
silently.

Each unique part definition is measured, exported as its own STEP file and
rendered as a thumbnail (matplotlib, colours taken from the theme file).
"""

from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path

import cadquery as cq
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFDoc import XCAFDoc_DocumentTool

from .geometry import exact_bbox, projected_area, tessellate, wall_stats

THEME_CSS = Path(__file__).resolve().parents[2] / "theme" / "dtc-theme.css"


class ImportError_(ValueError):
    pass


# ---------- reading the product structure ----------

def _name(label) -> str:
    n = TDataStd_Name()
    return n.Get().ToExtString().strip() if label.FindAttribute(TDataStd_Name.GetID_s(), n) else ""


def read_structure(path: str, fallback_name: str) -> dict:
    """Return {"root": key, "defs": {key: {...}}} with children and quantities per parent."""
    doc = TDocStd_Document(TCollection_ExtendedString("dtc"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    if reader.ReadFile(path) != IFSelect_RetDone or not reader.Transfer(doc):
        raise ImportError_("Could not read the STEP file (is it a valid STEP AP203/AP214/AP242 file?).")
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    roots = TDF_LabelSequence()
    tool.GetFreeShapes(roots)
    if roots.Length() == 0:
        raise ImportError_("The STEP file contains no shapes.")

    defs: dict[str, dict] = {}

    def good(name: str) -> bool:
        return bool(name) and not re.fullmatch(r"[\d\s=]*|SOLID|COMPOUND|Open CASCADE STEP translator.*", name, re.I)

    def visit(label, instance_name="") -> str:
        proto = label
        if tool.IsReference_s(label):
            ref = TDF_Label()
            tool.GetReferredShape_s(label, ref)
            proto = ref
        key = f"d{proto.Tag()}"
        if key not in defs:
            name = _name(proto)
            is_assy = tool.IsAssembly_s(proto)
            defs[key] = {"key": key, "name": name if good(name) else "", "is_assembly": is_assy,
                         "shape": tool.GetShape_s(proto), "children": {}, "instance_names": []}
            if is_assy:
                comps = TDF_LabelSequence()
                tool.GetComponents_s(proto, comps)
                for i in range(1, comps.Length() + 1):
                    comp = comps.Value(i)
                    child = visit(comp, _name(comp))
                    defs[key]["children"][child] = defs[key]["children"].get(child, 0) + 1
        if instance_name and good(instance_name):
            defs[key]["instance_names"].append(instance_name)
        return key

    root_keys = [visit(roots.Value(i)) for i in range(1, roots.Length() + 1)]
    if len(root_keys) == 1:
        root = root_keys[0]
    else:  # several top-level shapes: wrap them in one assembly named after the file
        root = "d_root"
        children: dict[str, int] = {}
        for k in root_keys:
            children[k] = children.get(k, 0) + 1
        defs[root] = {"key": root, "name": fallback_name, "is_assembly": True, "shape": None,
                      "children": children, "instance_names": []}

    # Names: definition name, else first instance name, else file name + number.
    n = 0
    for d in defs.values():
        if not d["name"]:
            if d["instance_names"]:
                d["name"] = re.sub(r"[_\-\s]*\d+$", "", d["instance_names"][0]) or d["instance_names"][0]
            else:
                n += 1
                d["name"] = fallback_name if d["key"] == root else f"{fallback_name} part {n}"
    return {"root": root, "defs": defs}


# ---------- measuring ----------

def measure(shape: cq.Shape) -> dict:
    """Geometry kept for each revision; also the inputs of the process suggestion rules."""
    vertices, triangles = tessellate(shape)
    axes = exact_bbox(shape)
    length, width, height = sorted(axes.values(), reverse=True)
    proj = {a: projected_area(vertices, triangles, a) for a in ("x", "y", "z")}
    pull = max(proj, key=proj.get)
    volume = shape.Volume()
    wall, share = wall_stats(shape)
    box_volume = max(axes["x"] * axes["y"] * axes["z"], 1e-9)
    return {
        "volume_mm3": round(volume, 3),
        "volume_cm3": round(volume / 1000, 4),
        "surface_area_mm2": round(shape.Area(), 3),
        "bbox_mm": {"length": round(length, 3), "width": round(width, 3), "height": round(height, 3)},
        "bbox_axes_mm": {a: round(v, 3) for a, v in axes.items()},
        "projected_area_mm2": {a: round(v, 3) for a, v in proj.items()},
        "pull_direction": pull,
        "solid_count": len(shape.Solids()),
        "wall_mm": round(wall, 3),
        "sheet_share": round(share, 4),
        "fill_ratio": round(volume / box_volume, 4),
        "max_dim_mm": round(length, 3),
        "min_dim_mm": round(height, 3),
    }


def signature(m: dict) -> tuple:
    """Shape fingerprint for look-alike detection (4 significant digits)."""
    sig = lambda v: float(f"{v:.4g}")
    b = m["bbox_mm"]
    return (sig(m["volume_mm3"]), sig(m["surface_area_mm2"]), sig(b["length"]), sig(b["width"]), sig(b["height"]))


# ---------- files ----------

def step_bytes(shape: cq.Shape) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "part.step"
        cq.exporters.export(cq.Workplane().add(shape), str(p), exportType="STEP")
        return p.read_bytes()


def _theme_colours() -> dict:
    css = THEME_CSS.read_text(encoding="utf-8") if THEME_CSS.exists() else ""
    get = lambda name, default: (re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", css) or [None, default])[1]
    return {"part": get("table-row-hover", "#d5e2f3"), "edge": get("ink", "#152238"), "bg": get("grey-light", "#f6f8fa")}


def thumbnail_png(shape: cq.Shape, size_px: int = 220) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import numpy as np
    from matplotlib import pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    colours = _theme_colours()
    bb = shape.BoundingBox()
    tol = max(bb.DiagonalLength / 150, 0.05)
    verts, tris = shape.tessellate(tol, 0.5)
    v = np.array([p.toTuple() for p in verts])
    t = np.array([tuple(x) for x in tris])
    fig = plt.figure(figsize=(size_px / 100, size_px / 100), dpi=100)
    fig.patch.set_facecolor(colours["bg"])
    ax = fig.add_subplot(projection="3d")
    ax.set_facecolor(colours["bg"])
    if len(t):
        faces = v[t]
        normals = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
        normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
        light = np.array([0.4, -0.6, 0.7]) / np.linalg.norm([0.4, -0.6, 0.7])
        shade = 0.2 + 0.8 * np.clip(np.abs(normals @ light), 0, 1)
        base = np.array(matplotlib.colors.to_rgb(colours["part"]))
        ink = np.array(matplotlib.colors.to_rgb(colours["edge"]))
        rgb = ink + (base - ink) * shade[:, None]
        ax.add_collection3d(Poly3DCollection(faces, facecolors=rgb, edgecolors="none"))
        lo, hi = v.min(axis=0), v.max(axis=0)
        mid, span = (lo + hi) / 2, (hi - lo).max() / 2 or 1
        ax.set_xlim(mid[0] - span, mid[0] + span)
        ax.set_ylim(mid[1] - span, mid[1] + span)
        ax.set_zlim(mid[2] - span, mid[2] + span)
    ax.view_init(elev=25, azim=-55)
    ax.set_axis_off()
    fig.subplots_adjust(0, 0, 1, 1)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=colours["bg"])
    plt.close(fig)
    return buf.getvalue()


# ---------- whole file ----------

def analyse_file(path: str, file_name: str, with_files: bool = True) -> dict:
    """Part tree with measurements; optionally STEP bytes + thumbnail per definition."""
    stem = Path(file_name).stem
    tree = read_structure(path, stem)
    defs = tree["defs"]
    for d in defs.values():
        shape = cq.Shape.cast(d["shape"]) if d["shape"] is not None else None
        d.pop("shape")
        d.pop("instance_names")
        if shape is None:  # synthetic root: build the compound of its children for the picture
            d["metrics"] = None
            d["_shape"] = None
            continue
        d["_shape"] = shape
        d["metrics"] = None if d["is_assembly"] else measure(shape)
        if with_files:
            d["step"] = step_bytes(shape) if not d["is_assembly"] else None
            d["thumbnail"] = thumbnail_png(shape)

    # total quantity of each definition in one root assembly
    totals: dict[str, float] = {}

    def roll(key, mult):
        for child, qty in defs[key]["children"].items():
            totals[child] = totals.get(child, 0) + qty * mult
            roll(child, qty * mult)

    roll(tree["root"], 1)
    for d in defs.values():
        d["total_quantity"] = totals.get(d["key"], 1 if d["key"] == tree["root"] else 0)
        d.pop("_shape", None)
        # A definition used several times is often named after its first instance ("pin_1").
        if d["total_quantity"] > 1:
            d["name"] = re.sub(r"[_\-\s]+\d+$", "", d["name"]) or d["name"]

    # look-alikes among different part definitions
    groups: dict[tuple, list[str]] = {}
    for d in defs.values():
        if d["metrics"]:
            groups.setdefault(signature(d["metrics"]), []).append(d["key"])
    for keys in groups.values():
        for k in keys:
            defs[k]["looks_like"] = [defs[o]["name"] for o in keys if o != k]
    return tree
