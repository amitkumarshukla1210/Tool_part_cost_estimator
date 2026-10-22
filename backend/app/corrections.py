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
    """A point that really lies on the face (its Center() lies inside the material for a convex cylinder)."""
    verts, _ = face.tessellate(0.2)
    pts = np.array([[v.x, v.y, v.z] for v in verts])
    mid = pts.mean(axis=0)
    p = pts[int(np.argmin(((pts - mid) ** 2).sum(axis=1)))]
    return cq.Vector(*p)


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
