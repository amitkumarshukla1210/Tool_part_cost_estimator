"""Geometry analysis of STEP parts using CadQuery.

All CAD lengths are assumed to be in millimetres (the STEP default for
almost every OEM CAD system). Results are converted to cm / cm³ / g where
that is the usual costing unit.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import cadquery as cq
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from shapely import union_all
from shapely.geometry import Polygon

# Part types supported in Stage A. The value is a human-readable label.
PART_TYPES = {
    "plastic": "Plastic injection moulding",
    "die_casting": "Pressure die casting",
    "foundry": "Foundry / sand / gravity casting",
    "sheet_metal": "Sheet metal",
}

# Tessellation tolerance (mm) used for projected area and the 3D viewer.
MESH_TOLERANCE = 0.05
MESH_ANGULAR_TOLERANCE = 0.2

AXES = ("x", "y", "z")


@dataclass
class PartMetrics:
    part_type: str
    density_g_cm3: float
    solid_count: int
    volume_mm3: float
    volume_cm3: float
    surface_area_mm2: float
    net_weight_g: float
    net_weight_kg: float
    bbox_mm: dict  # {"length": L, "width": W, "height": H}
    bbox_axes_mm: dict  # {"x": dx, "y": dy, "z": dz}
    projected_area_mm2: dict  # {"x": ..., "y": ..., "z": ...}
    projected_area_cm2: float  # area on the main pull direction
    pull_direction: str  # axis the projected area above is viewed along

    def to_dict(self) -> dict:
        return asdict(self)


def load_step(path: str) -> cq.Shape:
    """Read a STEP file and return a single shape holding all its solids."""
    wp = cq.importers.importStep(path)
    solids = [s for obj in wp.vals() for s in obj.Solids()]
    if not solids:
        raise ValueError("The STEP file contains no solid bodies (surfaces only?).")
    return solids[0] if len(solids) == 1 else cq.Compound.makeCompound(solids)


def tessellate(shape: cq.Shape):
    """Return (vertices, triangles) as plain Python lists."""
    verts, tris = shape.tessellate(MESH_TOLERANCE, MESH_ANGULAR_TOLERANCE)
    return [v.toTuple() for v in verts], [tuple(t) for t in tris]


def projected_area(vertices, triangles, axis: str) -> float:
    """Shadow (silhouette) area in mm² of the mesh viewed along ``axis``.

    Every triangle is flattened onto the plane normal to ``axis`` and the
    flattened triangles are merged, so holes through the part are excluded
    and overlapping features are counted once. This is the area the mould /
    die clamping force acts on.
    """
    keep = [i for i, a in enumerate(AXES) if a != axis]
    flat = []
    for tri in triangles:
        pts = [(vertices[i][keep[0]], vertices[i][keep[1]]) for i in tri]
        (x1, y1), (x2, y2), (x3, y3) = pts
        signed = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)
        # For a closed solid, the front-facing triangles alone cover the
        # whole shadow; skipping back-facing and edge-on ones halves the work.
        if signed > 1e-9:
            flat.append(Polygon(pts))
    if not flat:
        return 0.0
    return union_all(flat).area


def exact_bbox(shape: cq.Shape) -> dict:
    """Tight axis-aligned box in mm. CadQuery's default box adds a tolerance margin."""
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return {"x": xmax - xmin, "y": ymax - ymin, "z": zmax - zmin}


def analyze(shape: cq.Shape, part_type: str, density_g_cm3: float, mesh=None) -> PartMetrics:
    if part_type not in PART_TYPES:
        raise ValueError(f"Unknown part type '{part_type}'.")
    if density_g_cm3 <= 0:
        raise ValueError("Density must be greater than zero.")

    vertices, triangles = mesh if mesh else tessellate(shape)

    volume_mm3 = shape.Volume()
    volume_cm3 = volume_mm3 / 1000.0
    weight_g = volume_cm3 * density_g_cm3

    axes = exact_bbox(shape)
    # L >= W >= H, independent of how the part sits in the CAD axes.
    length, width, height = sorted(axes.values(), reverse=True)

    proj = {a: projected_area(vertices, triangles, a) for a in AXES}
    # Default pull direction: the axis with the largest shadow. For a mould
    # or die this is normally the opening direction (the part is oriented
    # with its biggest face across the parting line).
    pull = max(proj, key=proj.get)

    return PartMetrics(
        part_type=part_type,
        density_g_cm3=density_g_cm3,
        solid_count=len(shape.Solids()),
        volume_mm3=round(volume_mm3, 3),
        volume_cm3=round(volume_cm3, 4),
        surface_area_mm2=round(shape.Area(), 3),
        net_weight_g=round(weight_g, 3),
        net_weight_kg=round(weight_g / 1000.0, 5),
        bbox_mm={"length": round(length, 3), "width": round(width, 3), "height": round(height, 3)},
        bbox_axes_mm={a: round(v, 3) for a, v in axes.items()},
        projected_area_mm2={a: round(v, 3) for a, v in proj.items()},
        projected_area_cm2=round(proj[pull] / 100.0, 4),
        pull_direction=pull,
    )
