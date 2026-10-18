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


def wall_stats(shape: cq.Shape) -> tuple[float, float, int]:
    """(most common wall thickness in mm, share of the surface at that thickness, number of bends).

    Pairs of opposite flat faces vote for the wall with their smaller area. A bend is
    either a pair of coaxial cylinder faces whose radii differ by that wall (a radiused
    bend), or, for sharp-cornered models, a change in direction between the face pairs
    at that wall (an L-bracket has two directions, so one bend). The share leaves out
    the narrow edge strips of a sheet (faces no wider than about 1.2 × the wall), so a
    thick, small bracket still reads as sheet-like.
    """
    planes = []
    for face in shape.Faces():
        if face.geomType() != "PLANE":
            continue
        planes.append((face.normalAt(), face.Center(), face.Area()))
    votes: dict[float, float] = {}
    pair_dirs: dict[float, list] = {}
    for i, (n1, c1, a1) in enumerate(planes):
        for n2, c2, a2 in planes[i + 1:]:
            if n1.dot(n2) > -0.999:
                continue
            gap = abs((c2 - c1).dot(n1))
            if gap > 1e-3:
                key = round(gap, 2)
                votes[key] = votes.get(key, 0.0) + min(a1, a2)
                pair_dirs.setdefault(key, []).append(n1)
    area = shape.Area() or 1.0
    if not votes:
        return 2 * shape.Volume() / area, 0.0, 0
    best = max(votes, key=votes.get)
    covered = votes[best]

    # radiused bends: coaxial cylinders, radii differing by the wall
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    cylinders = []
    for face in shape.Faces():
        if face.geomType() == "CYLINDER":
            cyl = BRepAdaptor_Surface(face.wrapped).Cylinder()
            ax = cyl.Axis()
            d, o = ax.Direction(), ax.Location()
            cylinders.append(((d.X(), d.Y(), d.Z()), (o.X(), o.Y(), o.Z()), cyl.Radius(), face.Area()))
    bends = 0
    for i, (d1, o1, r1, a1) in enumerate(cylinders):
        for d2, o2, r2, a2 in cylinders[i + 1:]:
            if abs(sum(x * y for x, y in zip(d1, d2))) < 0.999:
                continue
            off = [b - a for a, b in zip(o1, o2)]
            along = sum(x * y for x, y in zip(off, d1))
            dist = sum((x - along * y) ** 2 for x, y in zip(off, d1)) ** 0.5
            if dist < 1e-3 and abs(abs(r1 - r2) - best) <= max(0.05 * best, 0.01):
                bends += 1
                covered += min(a1, a2)

    if not bends:  # sharp corners: count the distinct directions of the wall pairs
        dirs = []
        for n in pair_dirs[best]:
            if not any(abs(n.dot(m)) > 0.999 for m in dirs):
                dirs.append(n)
        bends = max(0, len(dirs) - 1)
    edge = 0.0
    for face in shape.Faces():
        perimeter = sum(e.Length() for e in face.Edges())
        if face.Area() <= 0.6 * perimeter * best:  # a strip: area ≈ length × width, perimeter ≈ 2 × length
            edge += face.Area()
    return best, min(1.0, 2 * covered / max(area - edge, 1e-9)), bends


def sheet_thickness(shape: cq.Shape) -> float:
    """Estimate sheet thickness in mm from opposite parallel planar faces.

    In a sheet-metal part most of the area is in pairs of flat faces that
    face each other at a distance equal to the thickness. Every such pair
    votes with its smaller area, and the distance with the most votes wins.
    Falls back to 2 × volume / surface area if no pair is found.
    """
    planes = []
    for face in shape.Faces():
        if face.geomType() != "PLANE":
            continue
        n = face.normalAt()
        planes.append((n, face.Center(), face.Area()))

    votes: dict[float, float] = {}
    for i, (n1, c1, a1) in enumerate(planes):
        for n2, c2, a2 in planes[i + 1:]:
            if n1.dot(n2) > -0.999:
                continue
            gap = abs((c2 - c1).dot(n1))
            if gap > 1e-3:
                key = round(gap, 2)
                votes[key] = votes.get(key, 0.0) + min(a1, a2)
    if votes:
        return max(votes, key=votes.get)
    return 2 * shape.Volume() / shape.Area()


def blank_estimate(volume_mm3: float, bbox_mm: dict, thickness_mm: float) -> dict:
    """Suggest a rectangular flat blank (mm) for a sheet-metal part.

    A flat part (height ≈ thickness) uses its L × W directly. A bent part
    keeps its width and gets the developed length from flat area / width.
    Holes punched out of the part make this slightly short, so the result
    is a starting point for the user to correct.
    """
    length, width, height = bbox_mm["length"], bbox_mm["width"], bbox_mm["height"]
    if height <= thickness_mm * 1.05:
        return {"length": round(length, 1), "width": round(width, 1)}
    flat_area = volume_mm3 / thickness_mm
    return {"length": round(max(flat_area / width, length), 1), "width": round(width, 1)}


def sheet_features(shape: cq.Shape, thickness: float) -> dict:
    """Holes and bend radii of a sheet-metal part.

    Holes: inner wires of the planar faces (each through hole shows on both sides, so the total is halved).
    Bend radii: coaxial cylinder pairs whose radii differ by the thickness (inside radius, axial length);
    sharp-cornered models have none, so the radius is unknown (None).
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    holes = []
    for face in shape.Faces():
        if face.geomType() != "PLANE" or face.Area() < thickness * thickness:
            continue
        for w in face.innerWires():
            area = cq.Face.makeFromWires(w).Area()
            holes.append((w.Length(), area))
    holes = sorted(holes, key=lambda h: h[1])
    holes = holes[::2] if len(holes) % 2 == 0 else holes   # both sides of a through hole
    cyl = []
    for face in shape.Faces():
        if face.geomType() == "CYLINDER":
            c = BRepAdaptor_Surface(face.wrapped).Cylinder()
            ax, loc = c.Axis().Direction(), c.Axis().Location()
            bb = face.BoundingBox()
            extent = abs(ax.X()) * bb.xlen + abs(ax.Y()) * bb.ylen + abs(ax.Z()) * bb.zlen
            cyl.append(((ax.X(), ax.Y(), ax.Z()), (loc.X(), loc.Y(), loc.Z()), c.Radius(), extent))
    bends = []
    for i, (d1, o1, r1, e1) in enumerate(cyl):
        for d2, o2, r2, e2 in cyl[i + 1:]:
            if abs(sum(a * b for a, b in zip(d1, d2))) < 0.999 or abs(abs(r1 - r2) - thickness) > max(0.05 * thickness, 0.01):
                continue
            off = [b - a for a, b in zip(o1, o2)]
            along = sum(a * b for a, b in zip(off, d1))
            if sum((a - along * b) ** 2 for a, b in zip(off, d1)) ** 0.5 < 1e-3:
                bends.append({"inner_radius_mm": min(r1, r2), "length_mm": min(e1, e2)})
    return {"holes": [{"perimeter_mm": p, "area_mm2": a} for p, a in holes], "bends": bends}
