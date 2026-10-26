"""Read a STEP file into a part tree: single part or assembly.

Assemblies are read with OpenCascade's XCAF reader, which keeps the product
structure. Instances of the same definition (4 identical pins) point to one
shared definition, so they become ONE part with quantity 4 in their parent.
Different definitions that look identical (same volume, area and size) are
flagged as look-alikes for the engineer to confirm; they are never merged
silently.

Each unique part definition is measured, exported as its own STEP file and
rendered as a thumbnail (matplotlib, colours taken from the theme file).

Insert detection: inside each assembly, a smaller part whose surface is largely
covered by a bigger sibling (the bigger part touches or surrounds it) is listed
as a possible moulded-in insert of that body, e.g. a brass threaded insert in a
plastic boss. The engineer confirms each one; nothing is changed automatically.
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

from .geometry import exact_bbox, projected_area, solidify, tessellate, wall_stats

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
                         "shape": tool.GetShape_s(proto), "children": {}, "instance_names": [], "placed": []}
            if is_assy:
                comps = TDF_LabelSequence()
                tool.GetComponents_s(proto, comps)
                for i in range(1, comps.Length() + 1):
                    comp = comps.Value(i)
                    child = visit(comp, _name(comp))
                    defs[key]["children"][child] = defs[key]["children"].get(child, 0) + 1
                    # the component placed in this assembly's frame, for insert detection
                    defs[key]["placed"].append((child, tool.GetShape_s(comp)))
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
                      "children": children, "instance_names": [],
                      "placed": [(k, tool.GetShape_s(roots.Value(i + 1))) for i, k in enumerate(root_keys)]}

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
    wall, share, bends = wall_stats(shape)
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
        "bend_count": bends,
        "fill_ratio": round(volume / box_volume, 4),
        "max_dim_mm": round(length, 3),
        "min_dim_mm": round(height, 3),
    }


def signature(m: dict) -> tuple:
    """Shape fingerprint for look-alike detection (4 significant digits)."""
    sig = lambda v: float(f"{v:.4g}")
    b = m["bbox_mm"]
    return (sig(m["volume_mm3"]), sig(m["surface_area_mm2"]), sig(b["length"]), sig(b["width"]), sig(b["height"]))


# ---------- moulded-in inserts ----------

def _probe_points(shape: cq.Shape, count: int):
    """Up to `count` (point, normal, area) samples spread over the surface of a shape."""
    import numpy as np
    bb = shape.BoundingBox()
    verts, tris = shape.tessellate(max(bb.DiagonalLength / 200, 0.02), 0.3)
    if not tris:
        return []
    v = np.array([p.toTuple() for p in verts])
    t = np.array([tuple(x) for x in tris])
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    cross = np.cross(b - a, c - a)
    area = np.linalg.norm(cross, axis=1) / 2
    keep = area > 1e-9
    centres, normals, area = ((a + b + c) / 3)[keep], (cross[keep].T / (2 * area[keep])).T, area[keep]
    step = max(1, len(area) // count)
    order = np.argsort(-area)  # biggest triangles first, then every n-th one
    picked = order[::step][:count]
    return [(centres[i], normals[i], area[i]) for i in picked]


def _inside(classifiers, point) -> bool:
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    p = gp_Pnt(*map(float, point))
    for cl in classifiers:
        cl.Perform(p, 1e-4)
        if cl.State() in (TopAbs_IN, TopAbs_ON):
            return True
    return False


def _classifiers(shape: cq.Shape):
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    return [BRepClass3d_SolidClassifier(s.wrapped) for s in shape.Solids()]


def enclosure(body: cq.Shape, insert: cq.Shape, offset_mm: float, points: int) -> dict:
    """How much of the insert's surface the body covers.

    Each sample point on the insert surface is moved `offset_mm` outwards (away
    from the insert material); if that point is inside or on the body, the body
    covers the insert there. `covered_share` is the covered share of the sampled
    area. `overlap_mm3` > 0 means the body was modelled solid through the insert.
    """
    if not body.Solids() or not insert.Solids():
        return {"covered_share": 0.0, "overlap_mm3": 0.0}
    b1, b2 = body.BoundingBox(), insert.BoundingBox()
    if (b2.xmin > b1.xmax + offset_mm or b2.xmax < b1.xmin - offset_mm or b2.ymin > b1.ymax + offset_mm
            or b2.ymax < b1.ymin - offset_mm or b2.zmin > b1.zmax + offset_mm or b2.zmax < b1.zmin - offset_mm):
        return {"covered_share": 0.0, "overlap_mm3": 0.0}
    own, other = _classifiers(insert), _classifiers(body)
    covered = total = inner_hits = 0.0
    for centre, normal, area in _probe_points(insert, points):
        out_pt = centre + normal * offset_mm
        if _inside(own, out_pt):  # the triangle normal pointed into the insert: flip it
            out_pt, in_pt = centre - normal * offset_mm, out_pt
        else:
            in_pt = centre - normal * offset_mm
        total += area
        if _inside(other, out_pt):
            covered += area
        if _inside(other, in_pt):
            inner_hits += area
    overlap = 0.0
    if total and inner_hits / total > 0.05:
        try:
            overlap = body.intersect(insert).Volume()
        except Exception:  # boolean failure: report no overlap rather than a wrong one
            overlap = 0.0
    return {"covered_share": round(float(covered / total), 4) if total else 0.0, "overlap_mm3": round(float(overlap), 3)}


def detect_inserts(defs: dict, min_share: float, offset_mm: float, points: int) -> list[dict]:
    """Possible moulded-in inserts in every assembly: smaller parts largely covered by a bigger sibling."""
    found = []
    for key, d in defs.items():
        placed = [(k, cq.Shape.cast(s)) for k, s in d.get("placed", []) if s is not None and not defs[k]["is_assembly"]]
        if len(placed) < 2:
            continue
        volume = {k: s.Volume() for k, s in placed}
        hits: dict[tuple, dict] = {}
        for bk, body in placed:
            for ik, ins in placed:
                if ik == bk or volume[ik] >= volume[bk]:
                    continue
                e = enclosure(body, ins, offset_mm, points)
                if e["covered_share"] >= min_share:
                    h = hits.setdefault((bk, ik), {"instances": 0, "share": 0.0, "overlap_mm3": 0.0})
                    h["instances"] += 1
                    h["share"] = max(h["share"], e["covered_share"])
                    h["overlap_mm3"] += e["overlap_mm3"]
        for (bk, ik), h in hits.items():
            n_bodies = sum(1 for k, _ in placed if k == bk) or 1
            found.append({"assembly": key, "body": bk, "insert": ik,
                          "quantity": max(1, round(h["instances"] / n_bodies)),
                          "covered_share": float(h["share"]),
                          "overlap_mm3": round(h["overlap_mm3"] / n_bodies, 3)})
    return found


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

def analyse_file(path: str, file_name: str, with_files: bool = True, insert_detection: dict | None = None) -> dict:
    """Part tree with measurements; optionally STEP bytes + thumbnail per definition.

    insert_detection: {"min_share", "offset_mm", "points"} (from master data) to look for
    moulded-in inserts; the result is tree["inserts"].
    """
    stem = Path(file_name).stem
    tree = read_structure(path, stem)
    defs = tree["defs"]
    tree["inserts"] = detect_inserts(defs, **insert_detection) if insert_detection else []
    for d in defs.values():
        d.pop("placed", None)
    for d in defs.values():
        shape = solidify(cq.Shape.cast(d["shape"])) if d["shape"] is not None else None
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
