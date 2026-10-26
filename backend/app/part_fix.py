"""Correcting the 3D model after the simulation (roadmap stage 27): bend radius of sheet-metal parts.

A bend is a pair of coaxial cylinder faces (inside radius r, outside r + t) between two flat legs. To give it a new
inside radius R while the outside dimensions of the part stay the same (the mould lines of the legs do not move):

    new axis       o' = o + m · (r − R) / cos(θ/2)       m = middle radial direction of the bend, θ = bend angle
    corner zone    the sector of the bend seen from o' (between the two radial directions of its ends), over the
                   axial length of the bend: removed from the part (old bend + the leg ends the larger radius takes)
    new bend       ring sector R … R + t about o', same sector and length: added
The legs keep their faces, holes and outside dimensions; only the leg length next to the bend changes, as it does on
a real part. The result is checked (one solid, volume close to the old one) and offered as a new revision.
"""

from __future__ import annotations

import math

import cadquery as cq
import numpy as np


class FixError(ValueError):
    pass


def _cyl(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    c = BRepAdaptor_Surface(face.wrapped).Cylinder()
    ax, loc = c.Axis().Direction(), c.Axis().Location()
    return np.array([ax.X(), ax.Y(), ax.Z()]), np.array([loc.X(), loc.Y(), loc.Z()]), c.Radius()


def bends(shape, t: float) -> list[dict]:
    """Every bend: axis, centre, inside radius, angle, radial directions of its two ends, axial range."""
    cyl = [(f, *_cyl(f)) for f in shape.Faces() if f.geomType() == "CYLINDER"]
    out, used = [], set()
    for i, (f, a, o, r) in enumerate(cyl):
        if i in used:
            continue
        for j, (g, a2, o2, r2) in enumerate(cyl):
            if j <= i or j in used:
                continue
            off = o2 - o
            if abs(abs(a @ a2) - 1) > 1e-3 or np.linalg.norm(off - (off @ a) * a) > 1e-3 or abs(abs(r - r2) - t) > max(0.05 * t, 0.01):
                continue
            inner = f if r < r2 else g
            ri = min(r, r2)
            pts = [np.array(v.toTuple()) for v in inner.Vertices()]
            if len(pts) < 2:
                continue
            rad = []
            for p in pts:
                u = p - o - ((p - o) @ a) * a
                n = np.linalg.norm(u)
                if n > 1e-9:
                    u = u / n
                    if all(np.linalg.norm(u - q) > 1e-4 for q in rad):
                        rad.append(u)
            if len(rad) != 2:
                continue
            u1, u2 = rad
            theta = math.acos(max(-1.0, min(1.0, float(u1 @ u2))))
            ax = [float((p - o) @ a) for p in pts]
            used |= {i, j}
            out.append({"axis": a, "centre": o, "r": ri, "theta": theta, "u1": u1, "u2": u2, "a0": min(ax), "a1": max(ax)})
            break
    if not out:
        out = _sharp_bends(shape, t)
    return out


def _sharp_bends(shape, t: float) -> list[dict]:
    """Sharp-cornered models: an inside corner is an edge shared by two flat sheet faces whose normals point at each
    other (concave); it is a bend of radius 0 whose axis is that edge."""
    from .geometry import _sheet_faces
    faces = _sheet_faces(shape, t)
    out = []
    for i, fa in enumerate(faces):
        for fb in faces[i + 1:]:
            hb = {e.hashCode() for e in fb.Edges()}
            shared = [e for e in fa.Edges() if e.hashCode() in hb and e.geomType() == "LINE"]
            if not shared:
                continue
            e = shared[0]
            p0, p1 = (np.array(v.toTuple()) for v in (e.startPoint(), e.endPoint()))
            a = (p1 - p0) / np.linalg.norm(p1 - p0)
            na, nb = np.array(fa.normalAt().toTuple()), np.array(fb.normalAt().toTuple())
            if abs(na @ nb) > 0.999 or na @ (np.array(fb.Center().toTuple()) - p0) <= 0:
                continue                    # flat continuation, or the outside corner
            u1, u2 = -na, -nb
            out.append({"axis": a, "centre": p0, "r": 0.0, "theta": math.acos(max(-1.0, min(1.0, float(u1 @ u2)))),
                        "u1": u1, "u2": u2, "a0": 0.0, "a1": float(np.linalg.norm(p1 - p0))})
    return out


def _sector(o, a, u1, u2, r0, r1, a0, a1):
    """Solid ring sector between radii r0..r1 (r0 may be 0) from u1 to u2 about axis (o, a), axial range a0..a1."""
    ang = math.acos(max(-1.0, min(1.0, float(u1 @ u2))))
    v = np.cross(a, u1)
    if v @ u2 < 0:
        v = -v
    n = 24
    arc = lambda r: [o + r * (math.cos(ang * k / n) * u1 + math.sin(ang * k / n) * v) for k in range(n + 1)]
    outer = arc(r1)
    inner = arc(r0)[::-1] if r0 > 0 else [o]
    pts = [cq.Vector(*(p + a * a0)) for p in outer + inner]
    wire = cq.Wire.makePolygon(pts, close=True)
    face = cq.Face.makeFromWires(wire)
    return cq.Solid.extrudeLinear(face, cq.Vector(*(a * (a1 - a0))))


def _sector_exact(o, a, u1, u2, r0, r1, a0, a1):
    """Ring sector with true cylinders (for the new bend): annulus ∩ wedge."""
    h = a1 - a0
    base = cq.Vector(*(o + a * a0))
    d = cq.Vector(*a)
    ring = cq.Solid.makeCylinder(r1, h, base, d).cut(cq.Solid.makeCylinder(r0, h, base, d))
    wedge = _sector(o, a, u1, u2, 0, r1 * 3, a0 - 1, a1 + 1)
    return ring.intersect(wedge)


def fix_bend_radius(shape, t: float, radius: float, only_below: float | None = None):
    """New shape with every bend whose inside radius is below `only_below` (default: radius) set to `radius`.
    Returns (shape, [changes])."""
    limit = radius if only_below is None else only_below
    todo = [b for b in bends(shape, t) if b["r"] < limit - 1e-6]
    if not todo:
        raise FixError("No bend has an inside radius below the minimum: nothing to correct.")
    s = shape
    changes = []
    v0 = shape.Volume()
    for b in todo:
        a, o, r, th = b["axis"], b["centre"], b["r"], b["theta"]
        m = b["u1"] + b["u2"]
        m /= np.linalg.norm(m)
        o2 = o + m * (r - radius) / math.cos(th / 2)
        reach = (radius + t) / max(math.cos(th / 2), 0.05) * 1.6 + t
        zone = _sector(o2, a, b["u1"], b["u2"], 0, reach, b["a0"] - 1e-3, b["a1"] + 1e-3)
        new = _sector_exact(o2, a, b["u1"], b["u2"], radius, radius + t, b["a0"], b["a1"])
        s = s.cut(zone).fuse(new).clean()
        changes.append({"from_mm": round(r, 3), "to_mm": radius, "angle_deg": round(math.degrees(th), 1)})
    solids = s.Solids()
    if len(solids) != 1:
        raise FixError(f"The corrected model came out as {len(solids)} bodies: correct this bend in CAD.")
    s = solids[0]
    if abs(s.Volume() - v0) > 0.1 * v0:
        raise FixError("The corrected model differs too much from the original: correct this bend in CAD.")
    return s, changes


def fix_small_holes(shape, t: float, min_d: float):
    """New shape with every round hole smaller than min_d opened up to min_d (same centre). Returns (shape, [changes])."""
    s = shape
    changes = []
    for f in shape.Faces():
        if f.geomType() != "CYLINDER":
            continue
        a, o, r = _cyl(f)
        bb = f.BoundingBox()
        length = abs(a[0]) * bb.xlen + abs(a[1]) * bb.ylen + abs(a[2]) * bb.zlen
        if abs(length - t) > 0.05 * t + 0.01 or 2 * r >= min_d - 1e-6:
            continue                                   # not a through hole of the sheet, or big enough
        c = np.array(f.Center().toTuple())
        if abs(np.linalg.norm(c - o - ((c - o) @ a) * a)) > 0.5 * r:
            continue                                   # a part of a cylinder (fillet, slot end), not a round hole
        base = o + ((c - o) @ a) * a - a * 2 * t
        s = s.cut(cq.Solid.makeCylinder(min_d / 2, 4 * t, cq.Vector(*base), cq.Vector(*a)))
        changes.append({"from_mm": round(2 * r, 3), "to_mm": min_d})
    if not changes:
        raise FixError("No hole is smaller than the minimum: nothing to correct.")
    return s.clean(), changes
