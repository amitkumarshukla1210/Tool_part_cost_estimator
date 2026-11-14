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
    "eps": "EPS (thermocole) shape moulding",
    "blow": "PET stretch blow moulding (bottles)",
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


def solidify(shape):
    """Closed shells (some CAD systems write a closed body as a shell, not a solid) made solids; others unchanged."""
    if shape is None or shape.Solids():
        return shape
    solids = []
    for sh in shape.Shells():
        try:
            if sh.Closed():
                sol = cq.Solid.makeSolid(sh)
                if sol.isValid() and sol.Volume() < 0:
                    sol = cq.Solid(sol.wrapped.Reversed())
                if sol.isValid() and sol.Volume() > 0:
                    solids.append(sol)
        except Exception:
            pass
    if not solids:
        return shape
    return solids[0] if len(solids) == 1 else cq.Compound.makeCompound(solids)


def load_step(path: str) -> cq.Shape:
    """Read a STEP file and return a single shape holding all its solids."""
    wp = cq.importers.importStep(path)
    solids = [s for obj in wp.vals() for s in solidify(obj).Solids()]
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


def _unit(v):
    n = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-12 else None


def _sheet_faces(shape: cq.Shape, thickness: float) -> list:
    """Flat faces of the sheet itself: each has a parallel twin facing the other way one thickness away.
    (Edge faces, the side faces of an L / U profile and the rim of a tray do not: their twin is a part size away.)"""
    flats = []
    for f in shape.Faces():
        if f.geomType() == "PLANE":
            n, c = f.normalAt(), f.Center()
            flats.append((f, (n.x, n.y, n.z), n.x * c.x + n.y * c.y + n.z * c.z))
    out = []
    for i, (f, n, off) in enumerate(flats):
        if any(sum(a * b for a, b in zip(n, n2)) < -0.999 and abs(abs(off + off2) - thickness) <= 0.1 * thickness
               for j, (_, n2, off2) in enumerate(flats) if j != i):
            out.append(f)
    return out


def bend_axes(shape: cq.Shape, thickness: float) -> list[tuple]:
    """Directions of the bend lines of a sheet-metal part.

    Rounded bends: the axes of the bend cylinders. Sharp-cornered models: the line where two large flat faces with
    different normals meet (cross product of the normals). Parallel directions are merged.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    # rounded bends: coaxial cylinder pairs whose radii differ by the thickness (hole walls are single cylinders)
    cyl = []
    for face in shape.Faces():
        if face.geomType() == "CYLINDER":
            c = BRepAdaptor_Surface(face.wrapped).Cylinder()
            ax, loc = c.Axis().Direction(), c.Axis().Location()
            cyl.append(((ax.X(), ax.Y(), ax.Z()), (loc.X(), loc.Y(), loc.Z()), c.Radius()))
    dirs = []
    for i, (d1, o1, r1) in enumerate(cyl):
        for d2, o2, r2 in cyl[i + 1:]:
            if abs(sum(a * b for a, b in zip(d1, d2))) < 0.999 or abs(abs(r1 - r2) - thickness) > max(0.05 * thickness, 0.01):
                continue
            off = [b - a for a, b in zip(o1, o2)]
            along = sum(a * b for a, b in zip(off, d1))
            if sum((a - along * b) ** 2 for a, b in zip(off, d1)) ** 0.5 < 1e-3:
                dirs.append(d1)
    if not dirs:
        planes = sorted(_sheet_faces(shape, thickness), key=lambda f: -f.Area())
        big = [f for f in planes if f.Area() > 0.05 * planes[0].Area()] if planes else []
        normals = []
        for f in big:
            n = f.normalAt()
            n = (n.x, n.y, n.z)
            if all(abs(sum(a * b for a, b in zip(n, m))) < 0.99 for m in normals):
                normals.append(n)
        for i, a in enumerate(normals):
            for b in normals[i + 1:]:
                c = _unit((a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]))
                if c:
                    dirs.append(c)
    out = []
    for d in dirs:
        d = _unit(d)
        if d and all(abs(sum(a * b for a, b in zip(d, e))) < 0.99 for e in out):
            out.append(d)
    return out


def extent_along(shape: cq.Shape, d: tuple) -> float:
    """Size of the part along a direction (projection of its vertices)."""
    vals = [v.x * d[0] + v.y * d[1] + v.z * d[2] for v in (p.Center() for p in shape.Vertices())]
    return (max(vals) - min(vals)) if vals else 0.0


def developed_blank(shape: cq.Shape, volume_mm3: float, bbox_mm: dict, thickness: float) -> dict:
    """The flat blank of a sheet-metal part, chosen for the best material yield.

    Options compared (material yield = flat part area ÷ blank area):
      developed strip   bent part whose bends all run the same way (L, U, Z, channel): strip width = the part's size
                        along the bend lines, length = flat area ÷ width. A straight strip, formed by a bending stage.
      rectangle         the rectangle the old estimate used: part width × developed length (keeps the formed width).
    A flat part (no bend) uses its own length × width. The option with the highest yield is used.
    """
    old = blank_estimate(volume_mm3, bbox_mm, thickness)
    hole_area = 0.0
    if shape is not None:   # holes punched through the sheet (each shows on both faces of the sheet)
        hole_area = sum(cq.Face.makeFromWires(w).Area() for f in _sheet_faces(shape, thickness) for w in f.innerWires()) / 2
    flat_area = volume_mm3 / thickness + hole_area
    opt = lambda name, l, w, note: {"name": name, "length": round(l, 1), "width": round(w, 1), "area_mm2": round(l * w, 1),
                                    "yield_pct": round(100 * flat_area / max(l * w, 1e-9), 1), "note": note}
    if bbox_mm["height"] <= thickness * 1.05 or shape is None:
        o = opt("Flat part", old["length"], old["width"], "length × width of the flat part")
        return {"length": o["length"], "width": o["width"], "method": o["name"], "options": [o], "chosen": o["name"],
                "flat_area_mm2": round(flat_area, 1), "bends": 0}
    options = [opt("Rectangle keeping the formed width", old["length"], old["width"],
                   "part width × developed length: wide blank, low yield when the part is L / U shaped")]
    axes = bend_axes(shape, thickness)
    # the main bend direction: the one most of the sheet area is bent around (faces whose normal is square to it);
    # small stiffeners, embossings or tabs add other directions but do not make the part a tray
    faces = _sheet_faces(shape, thickness)
    total = sum(f.Area() for f in faces) or 1.0
    def share(d):
        return sum(f.Area() for f in faces if abs(sum(a * b for a, b in zip(d, f.normalAt().toTuple()))) < 0.05) / total
    main = max(axes, key=share) if axes else None
    main_share = share(main) if main else 0.0
    strip = tray = None
    if main and (len(axes) == 1 or main_share >= 0.9):
        w = extent_along(shape, main)
        if w > thickness:
            strip = opt("Developed straight strip + bending stage", flat_area / w, w,
                        "strip width = part size along the bend line; length = flat area ÷ width; "
                        f"the L / U / Z shape is formed in a bending stage ({100 * main_share:.0f} % of the sheet bends this way)")
            options.append(strip)
    if len(axes) >= 2 and not strip:  # bends two ways (the third direction is the vertical corner of a tray / box)
        h = bbox_mm["height"] - thickness
        tray = opt("Tray / box blank (L + 2·H) × (W + 2·H)", bbox_mm["length"] + 2 * h, bbox_mm["width"] + 2 * h,
                   "flanges on both sides folded up in bending stages; corners notched (relief)")
        options.append(tray)
    valid = [o for o in options if o["yield_pct"] <= 100.5] or options   # a blank smaller than the flat part is impossible
    rect = options[0]
    if strip in valid:
        best = strip                     # the true developed blank of a part bent one way
    elif tray in valid and (rect not in valid or rect["yield_pct"] >= 99):
        best = tray                      # the rectangle only matches the area by chance: a tray needs its flanges
    else:
        best = max(valid, key=lambda o: o["yield_pct"])
    return {"length": best["length"], "width": best["width"], "method": best["name"], "options": options,
            "chosen": best["name"], "flat_area_mm2": round(flat_area, 1), "bends": 1 if len(axes) == 1 else len(axes),
            "bend_axes": len(axes)}


DOUBLY_CURVED = ("TORUS", "SPHERE", "BSPLINE", "BEZIER", "REVOLUTION", "OFFSET", "OTHER")


def drawn_share(shape: cq.Shape) -> float:
    """Share of the surface that is curved both ways (torus, sphere, free-form): corners of a drawn part."""
    total = sum(f.Area() for f in shape.Faces()) or 1.0
    return sum(f.Area() for f in shape.Faces() if f.geomType() in DOUBLY_CURVED) / total


def sheet_features(shape: cq.Shape, thickness: float) -> dict:
    """Holes and bend radii of a sheet-metal part.

    Holes: inner wires of the planar faces (each through hole shows on both sides, so the total is halved).
    Bend radii: coaxial cylinder pairs whose radii differ by the thickness (inside radius, axial length);
    sharp-cornered models have none, so the radius is unknown (None).
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    holes = []
    sheet = {f.hashCode() for f in _sheet_faces(shape, thickness)}
    for face in shape.Faces():
        if face.geomType() != "PLANE" or face.Area() < thickness * thickness or face.hashCode() not in sheet:
            continue                     # only the faces of the sheet itself (not the rim / edge faces of a tray)
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


def machining_features(shape: cq.Shape, hole_max_dia_mm: float = 20.0) -> dict:
    """What a machined part (roadmap stage 37) needs from its 3D model: is it turned, and where are its holes.

    round_share   share of the surface that is turned about one axis: cylinders, cones and tori on that axis plus the
                  flat faces square to it (end faces, shoulders). A shaft is near 1, a milled block far below.
    turn_*        that axis, the largest diameter about it and the length along it (from the mesh)
    sizes_mm      the three box sizes, largest first (milled stock)
    holes         drilled holes: concave cylinders up to hole_max_dia_mm (one per axis line and diameter, so a hole
                  split in two faces counts once); for a turned part the bores on the turning axis are turned, not drilled
    Only the measurement is done here; the route (turned / milled) and every allowance come from master data.
    """
    import math
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp_Face
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Torus
    from OCP.gp import gp_Pnt, gp_Vec

    def vec(d):
        return (d.X(), d.Y(), d.Z())

    def dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    def off_axis(p, loc, d):  # vector from the axis line to the point
        r = sub(p, loc)
        t = dot(r, d)
        return (r[0] - t * d[0], r[1] - t * d[1], r[2] - t * d[2])

    def parallel(a, b):
        return abs(abs(dot(a, b)) - 1) < 1e-4

    faces = shape.Faces()
    total = sum(f.Area() for f in faces) or 1.0
    revolved, planes = [], []
    for f in faces:
        s = BRepAdaptor_Surface(f.wrapped)
        kind = s.GetType()
        if kind in (GeomAbs_Cylinder, GeomAbs_Cone, GeomAbs_Torus):
            ax = {GeomAbs_Cylinder: s.Cylinder, GeomAbs_Cone: s.Cone, GeomAbs_Torus: s.Torus}[kind]().Axis()
            d, loc = vec(ax.Direction()), vec(ax.Location())
            u0, u1, v0, v1 = BRepTools.UVBounds_s(f.wrapped)
            p, n = gp_Pnt(), gp_Vec()
            BRepGProp_Face(f.wrapped).Normal((u0 + u1) / 2, (v0 + v1) / 2, p, n)
            radial = off_axis(vec(p), loc, d)
            ends = [dot(sub(v.toTuple(), loc), d) for v in f.Vertices()] or [0.0]
            revolved.append({"d": d, "loc": loc, "area": f.Area(), "cyl": kind == GeomAbs_Cylinder,
                             "r": s.Cylinder().Radius() if kind == GeomAbs_Cylinder else None,
                             "concave": dot(vec(n), radial) < 0, "depth": max(ends) - min(ends), "span": u1 - u0})
        elif kind == GeomAbs_Plane:
            planes.append((vec(s.Plane().Axis().Direction()), f.Area()))

    def on_line(x, line):
        return parallel(x["d"], line["d"]) and math.dist(off_axis(x["loc"], line["loc"], line["d"]), (0, 0, 0)) < 0.01

    best, score = None, 0.0
    for cand in revolved:
        sc = sum(x["area"] for x in revolved if on_line(x, cand)) + sum(a for n, a in planes if parallel(n, cand["d"]))
        if sc > score + 1e-9:
            best, score = cand, sc
    out = {"round_share": round(score / total, 4), "sizes_mm": sorted(exact_bbox(shape).values(), reverse=True)}
    if best:
        verts, _ = shape.tessellate(MESH_TOLERANCE, MESH_ANGULAR_TOLERANCE)
        pts = [v.toTuple() for v in verts]
        along = [dot(sub(p, best["loc"]), best["d"]) for p in pts]
        radius = max(math.dist(off_axis(p, best["loc"], best["d"]), (0, 0, 0)) for p in pts)
        out |= {"turn_axis": [round(c, 6) for c in best["d"]], "turn_dia_mm": round(2 * radius, 3),
                "turn_length_mm": round(max(along) - min(along), 3)}
    holes = []
    for x in revolved:
        if not (x["cyl"] and x["concave"] and 2 * x["r"] <= hole_max_dia_mm + 1e-6):
            continue
        g = next((h for h in holes if abs(h["r"] - x["r"]) < 1e-3 and on_line(x, h)), None)
        if g:
            g["depth"], g["span"] = max(g["depth"], x["depth"]), g["span"] + x["span"]
        else:
            holes.append(dict(x))
    # a hole goes (nearly) all round; an inner fillet or a slot end is only part of a cylinder
    out["holes"] = [{"dia_mm": round(2 * h["r"], 3), "depth_mm": round(h["depth"], 3),
                     "on_turn_axis": bool(best) and on_line(h, best)} for h in holes if h["span"] >= 1.8 * math.pi]
    return out
