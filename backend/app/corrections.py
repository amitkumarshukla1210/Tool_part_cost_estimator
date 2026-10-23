"""3D design correction from the simulation (roadmap stage 20).

The simulation marks faces with too little draft along the opening direction. This module applies the draft to the 3D model
(OpenCascade BRepOffsetAPI_DraftAngle through CadQuery), re-measures the draft map on the corrected solid and returns the
corrected STEP, so the tool is designed on the corrected part.

    parting plane   chosen from the model: it should not cut through vertical faces, and pockets that open one way pull
                    that way (a cup's core comes from the open side)
    draft sign      a face is released by the tool on its own side of the parting plane: +Z tool, face normal tilts up;
                    -Z tool, tilts down (checked on a box and a hole, see tests)
    not corrected   thick sections (coring out), thin walls, undercuts: these change the part's function, so they stay a
                    written "Corrections required" item for R&D. Faces the kernel cannot draft are listed, not hidden.
"""

from __future__ import annotations

import math

import cadquery as cq
import numpy as np
from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

AXIS_TO_Z = {"z": None, "x": ((0, 1, 0), -90.0), "y": ((1, 0, 0), 90.0)}   # rotation that brings the axis onto +Z


def to_z(shape: cq.Shape, axis: str) -> cq.Shape:
    rot = AXIS_TO_Z[axis]
    return shape if rot is None else shape.rotate(cq.Vector(0, 0, 0), cq.Vector(*rot[0]), rot[1])


def from_z(shape: cq.Shape, axis: str) -> cq.Shape:
    rot = AXIS_TO_Z[axis]
    return shape if rot is None else shape.rotate(cq.Vector(0, 0, 0), cq.Vector(*rot[0]), -rot[1])


def to_z_point(p, axis: str) -> tuple:
    """A point of the original model moved the way to_z moves the shape (opening axis onto +Z)."""
    v = to_z(cq.Vertex.makeVertex(*p), axis)
    c = v.Center()
    return (c.x, c.y, c.z)


def draft_map(shape: cq.Shape, min_draft_deg: float) -> dict:
    """Face area (cm²) whose wall is closer to the opening direction (Z) than `min_draft_deg` (like the simulation's map)."""
    from .geometry import tessellate
    v, t = tessellate(shape)
    tri = np.asarray(v, float)[np.asarray(t, int)]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    twice = np.linalg.norm(cross, axis=1)
    nz = np.abs(cross[:, 2]) / np.where(twice > 0, twice, 1)
    draft = np.degrees(np.arcsin(np.clip(nz, 0, 1)))
    area = twice / 2
    wall = draft < 89.0                                      # horizontal faces (parting / floors) need no draft
    low = wall & (draft < min_draft_deg)
    return {"low_draft_cm2": float(area[low].sum()) / 100, "wall_cm2": float(area[wall].sum()) / 100,
            "min_draft_deg": float(draft[wall].min()) if wall.any() else 90.0}


def sample_point(face: cq.Face) -> cq.Vector:
    """A point that really lies on the face, in the middle of it (its Center() lies inside the material for a convex cylinder, and the
    tessellation vertices of a cylinder are all on its end rings)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt2d
    from OCP.TopAbs import TopAbs_IN
    try:
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face.wrapped)
        surf = BRep_Tool.Surface_s(face.wrapped)
        for fu, fv in ((0.5, 0.5), (0.4, 0.5), (0.6, 0.5), (0.5, 0.4), (0.5, 0.6), (0.3, 0.3), (0.7, 0.7)):
            u, v = u0 + (u1 - u0) * fu, v0 + (v1 - v0) * fv
            cls = BRepClass_FaceClassifier(face.wrapped, gp_Pnt2d(u, v), 1e-6)
            if cls.State() == TopAbs_IN:
                p = surf.Value(u, v)
                return cq.Vector(p.X(), p.Y(), p.Z())
    except Exception:
        pass
    verts, _ = face.tessellate(0.2)
    pts = np.array([[v.x, v.y, v.z] for v in verts])
    mid = pts.mean(axis=0)
    return cq.Vector(*pts[int(np.argmin(((pts - mid) ** 2).sum(axis=1)))])


def to_z_point(p, axis: str) -> tuple:
    """A point of the original model moved the way to_z moves the shape (opening axis onto +Z)."""
    v = to_z(cq.Vertex.makeVertex(*p), axis)
    c = v.Center()
    return (c.x, c.y, c.z)


def draft_map(shape: cq.Shape, min_draft_deg: float) -> dict:
    """Face area (cm²) whose wall is closer to the opening direction (Z) than `min_draft_deg` (like the simulation's map)."""
    from .geometry import tessellate
    v, t = tessellate(shape)
    tri = np.asarray(v, float)[np.asarray(t, int)]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    twice = np.linalg.norm(cross, axis=1)
    nz = np.abs(cross[:, 2]) / np.where(twice > 0, twice, 1)
    draft = np.degrees(np.arcsin(np.clip(nz, 0, 1)))
    area = twice / 2
    wall = draft < 89.0                                      # horizontal faces (parting / floors) need no draft
    low = wall & (draft < min_draft_deg)
    return {"low_draft_cm2": float(area[low].sum()) / 100, "wall_cm2": float(area[wall].sum()) / 100,
            "min_draft_deg": float(draft[wall].min()) if wall.any() else 90.0}


def _escapes(shape: cq.Shape, p: cq.Vector, direction: int, length: float) -> bool:
    """True if a ray leaving point `p` along ±Z meets no solid within `length`."""
    from OCP.gp import gp_Lin
    hit = IntCurvesFace_ShapeIntersector()
    hit.Load(shape.wrapped, 1e-6)
    hit.Perform(gp_Lin(gp_Pnt(p.x, p.y, p.z), gp_Dir(0, 0, direction)), 0.0, length)
    return hit.NbPnt() == 0


def parting_plane(shape: cq.Shape, faces: list[cq.Face], opens: dict) -> float:
    """Z of the proposed parting plane (shape already has the opening axis along Z)."""
    bb = shape.BoundingBox()
    levels = {round(bb.zmin, 3), round(bb.zmax, 3), round((bb.zmin + bb.zmax) / 2, 3)}
    for f in shape.Faces():
        if f.geomType() == "PLANE" and abs(f.normalAt().z) > 0.999:
            levels.add(round(f.Center().z, 3))
    best, best_score = (bb.zmin + bb.zmax) / 2, None
    for z0 in sorted(levels):
        score = 0.0
        for f in faces:
            fb = f.BoundingBox()
            if fb.zmin + 0.5 < z0 < fb.zmax - 0.5:                      # the plane would cut this wall
                score += f.Area() * 2
            side = opens.get(id(f))
            if side == "up" and z0 < f.Center().z - 0.01:               # a pocket opening up with the plane above it
                score += f.Area()
            if side == "down" and z0 > f.Center().z + 0.01:
                score += f.Area()
        score += 1e-6 * abs(z0 - (bb.zmin + bb.zmax) / 2)               # tie: nearest the middle
        if best_score is None or score < best_score:
            best, best_score = z0, score
    return best


def apply_draft(shape: cq.Shape, axis: str, min_draft_deg: float, margin_deg: float = 0.5) -> dict:
    """Draft every wall below `min_draft_deg` to `min_draft_deg + margin_deg`. Returns the corrected shape and a report."""
    z = to_z(shape, axis)
    bb = z.BoundingBox()
    height = max(bb.zlen, 1.0)
    target = min_draft_deg + margin_deg
    before = draft_map(z, min_draft_deg)
    walls = []
    for f in z.Faces():
        if f.geomType() in ("PLANE", "CYLINDER", "CONE") and abs(f.normalAt().z) < math.sin(math.radians(min_draft_deg)):
            walls.append(f)
    opens = {}
    for f in walls:
        c = sample_point(f)
        n = f.normalAt(c)
        q = cq.Vector(c.x + n.x * 0.05, c.y + n.y * 0.05, c.z + n.z * 0.05)
        up, dn = _escapes(z, q, +1, height * 1.5), _escapes(z, q, -1, height * 1.5)
        opens[id(f)] = "up" if up and not dn else "down" if dn and not up else "both"
    plane_z = parting_plane(z, walls, opens)
    plane = gp_Pln(gp_Pnt(0, 0, plane_z), gp_Dir(0, 0, 1))
    done, failed = [], []

    def build(items):
        builder = BRepOffsetAPI_DraftAngle(z.wrapped)
        for f, sign in items:
            builder.Add(f.wrapped, gp_Dir(0, 0, 1), math.radians(sign * target), plane)
        builder.Build()
        if not builder.IsDone():
            raise ValueError("the kernel could not draft these faces together")
        out = cq.Shape.cast(builder.Shape())
        if not out.isValid():
            raise ValueError("drafting gave an invalid solid")
        return out

    items = []
    for f in walls:
        c = sample_point(f)
        side = opens[id(f)]
        items.append((f, 1 if side == "up" else -1 if side == "down" else (1 if c.z >= plane_z else -1)))
    # all faces in one operation (neighbours must move together); if the kernel refuses, leave faces out one at a time
    current, kept = z, list(items)
    while kept:
        try:
            current = build(kept)
            break
        except Exception:
            f, _ = kept.pop()
            failed.append({"face_area_mm2": round(f.Area(), 1), "reason": "the kernel cannot draft this face with its neighbours"})
    for f, sign in kept:
        done.append({"face_area_mm2": round(f.Area(), 1), "type": f.geomType().lower(), "angle_deg": sign * target,
                     "tool_side": "+Z" if sign > 0 else "-Z"})
    after = draft_map(current, min_draft_deg)
    return {"shape": from_z(current, axis), "axis": axis, "parting_z_mm": plane_z, "target_deg": target,
            "faces_drafted": done, "faces_failed": failed, "before": before, "after": after,
            "volume_change_pct": 100 * (current.Volume() - z.Volume()) / max(z.Volume(), 1e-9),
            "improved": after["low_draft_cm2"] < before["low_draft_cm2"] - 1e-9 or before["low_draft_cm2"] == 0}


# ---------------------------------------------------------------- sheet metal

def _edge_faces(shape: cq.Shape) -> list[tuple[cq.Edge, list[cq.Face]]]:
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    m = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape.wrapped, TopAbs_EDGE, TopAbs_FACE, m)
    out = []
    for i in range(1, m.Extent() + 1):
        faces = [cq.Face(f) for f in m.FindFromIndex(i)]
        out.append((cq.Edge(m.FindKey(i)), faces))
    return out


def _inward(face: cq.Face, mid: cq.Vector, tangent: cq.Vector) -> cq.Vector:
    """Unit vector in the face, perpendicular to the edge, from the edge midpoint into the face."""
    d = face.Center() - mid
    d = d - tangent * d.dot(tangent)
    return d.normalized() if d.Length > 1e-9 else d


def bend_edges(shape: cq.Shape, t: float) -> dict:
    """Sharp bends of a sheet part: pairs of straight edges between two large planar faces. 'inner' are the concave edges
    (inside of the bend), 'outer' the convex ones. Wall ends (cut edges, a face only t wide) are not bends."""
    inner, outer = [], []
    for e, faces in _edge_faces(shape):
        if len(faces) != 2 or e.geomType() != "LINE" or e.Length() < 2 * t:
            continue
        f1, f2 = faces
        if f1.geomType() != "PLANE" or f2.geomType() != "PLANE":
            continue
        if min(f1.Area() / max(max(x.Length() for x in f1.Edges()), 1e-9), f2.Area() / max(max(x.Length() for x in f2.Edges()), 1e-9)) < 1.5 * t:
            continue                                         # one face is only a thickness wide: a cut edge
        mid = e.Center()
        tan = (e.endPoint() - e.startPoint()).normalized()
        n1, n2 = f1.normalAt(mid), f2.normalAt(mid)
        if abs(n1.dot(n2)) > 0.995:
            continue                                         # coplanar or parallel
        convex = n1.dot(_inward(f2, mid, tan)) < 0
        (outer if convex else inner).append(e)
    return {"inner": inner, "outer": outer}


def correct_sheet(shape: cq.Shape, t: float, min_bend_r_factor: float, min_hole_factor: float, default_r_factor: float = 1.0) -> dict:
    """Make a sheet-metal model manufacturable: give sharp bends an inside radius (at least min_bend_r_factor × t, outside
    radius = inside + t) and open undersized punched holes to min_hole_factor × t. Returns the new shape and what changed."""
    r_in = max(min_bend_r_factor, default_r_factor) * t
    min_hole = min_hole_factor * t
    cur, log = shape, []
    be = bend_edges(shape, t)
    for kind, edges, r in (("inner", be["inner"], r_in), ("outer", be["outer"], r_in + t)):
        if not edges:
            continue
        try:
            out = cur.fillet(r, edges) if False else cq.Workplane("XY").add(cur).newObject(edges).fillet(r).val()
        except Exception:
            out = None
        if out is not None and out.isValid() and out.Volume() > 0.5 * cur.Volume():
            log.append({"kind": f"bend radius ({kind})", "count": len(edges), "value_mm": round(r, 2)})
            cur = out
        else:
            log.append({"kind": f"bend radius ({kind})", "count": 0, "value_mm": round(r, 2),
                        "failed": "the kernel could not round these edges"})
    # holes: through cylinders (concave, as long as the sheet is thick) whose diameter is under the minimum
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    opened = 0
    for f in shape.Faces():
        if f.geomType() != "CYLINDER":
            continue
        cyl = BRepAdaptor_Surface(f.wrapped).Cylinder()
        ax, loc, r = cyl.Axis().Direction(), cyl.Axis().Location(), cyl.Radius()
        axis = cq.Vector(ax.X(), ax.Y(), ax.Z())
        if 2 * r + 1e-6 >= min_hole:
            continue
        verts, _ = f.tessellate(0.1)
        along = [(v.x * axis.x + v.y * axis.y + v.z * axis.z) for v in verts]
        height = max(along) - min(along)
        if not 0.9 * t <= height <= 1.1 * t:
            continue
        p = sample_point(f)
        n = f.normalAt(p)
        radial = cq.Vector(loc.X() - p.x, loc.Y() - p.y, loc.Z() - p.z)
        radial = radial - axis * radial.dot(axis)
        if n.dot(radial) <= 0:
            continue                                         # convex (an outside corner), not a hole
        mid = (min(along) + max(along)) / 2
        base = cq.Vector(loc.X(), loc.Y(), loc.Z())
        base = base + axis * (mid - base.dot(axis))
        cut = cq.Solid.makeCylinder(min_hole / 2, t * 3, base - axis * (t * 1.5), axis)
        try:
            out = cur.cut(cut)
            if out.isValid() and out.Volume() < cur.Volume():
                cur = out
                opened += 1
        except Exception:
            pass
    if opened:
        log.append({"kind": "hole opened to the minimum", "count": opened, "value_mm": round(min_hole, 2)})
    return {"shape": cur, "changes": log, "changed": any(x.get("count") for x in log), "r_in_mm": r_in, "min_hole_mm": min_hole,
            "volume_change_pct": 100 * (cur.Volume() - shape.Volume()) / max(shape.Volume(), 1e-9)}
