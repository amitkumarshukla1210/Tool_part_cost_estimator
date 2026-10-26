"""Unfolding a bent sheet-metal part into its flat pattern (roadmap stage 27).

    one side of the sheet   the faces reached from the largest sheet face through sheet faces (flat, with a twin one
                            thickness away) and bend cylinders (coaxial pair one thickness apart); edge faces are the
                            thickness and are not crossed, so the walk stays on one side
    each flat face          gets a rigid transform into the plane of the first face
    crossing a bend         the next face is turned back by the bend angle about the bend axis and moved on by the
                            developed length of the bend: angle × (inside radius + k_factor × t)
    flat pattern            union of every face mapped into the plane: outline, holes with their real positions, bend
                            lines (where each bend starts and ends) with angle, inside radius and direction

Works for any part whose bends form a tree (L, U, Z, channels, trays with relieved corners). Sharp-cornered models
(no bend cylinders) bend at the shared edge with radius 0. k_factor comes from Mould & die database → Design rules.
"""

from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from .geometry import _sheet_faces


class UnfoldError(ValueError):
    pass


def _rot(axis, ang):
    """Rotation matrix about a unit axis (Rodrigues)."""
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(ang) * k + (1 - math.cos(ang)) * (k @ k)


def _affine(R=np.eye(3), t=(0, 0, 0)):
    m = np.eye(4)
    m[:3, :3] = R
    m[:3, 3] = t
    return m


def _apply(m, p):
    return m[:3, :3] @ np.asarray(p, float) + m[:3, 3]


def _cyl(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    c = BRepAdaptor_Surface(face.wrapped).Cylinder()
    ax, loc = c.Axis().Direction(), c.Axis().Location()
    return np.array([ax.X(), ax.Y(), ax.Z()]), np.array([loc.X(), loc.Y(), loc.Z()]), c.Radius()


def _edge_pts(edge, n=16):
    k = 1 if edge.geomType() == "LINE" else n
    return [np.array(edge.positionAt(i / k).toTuple()) for i in range(k + 1)]


def _wire_pts(wire):
    """Points of a wire in order (edges joined end to start)."""
    segs = [_edge_pts(e) for e in wire.Edges()]
    pts = list(segs.pop(0))
    while segs:
        end = pts[-1]
        k, rev = min(((i, r) for i in range(len(segs)) for r in (False, True)),
                     key=lambda ir: np.linalg.norm(end - (segs[ir[0]][-1] if ir[1] else segs[ir[0]][0])))
        q = segs.pop(k)
        pts += (q[::-1] if rev else q)[1:]
    return pts


def _shared(f1, f2):
    h = {e.hashCode() for e in f1.Edges()}
    return [e for e in f2.Edges() if e.hashCode() in h]


def _bend(m, m_far, centre, a, c_far, ang, r_in, dev) -> dict:
    """A bend of the flat pattern: centre line (in the flat plane), angle, inside radius, developed length, whether the
    far side turns up (+1, towards the normal of the first face) or down (-1), and a point on the far side."""
    c2 = _apply(m, centre)
    d2 = _apply(m, centre + a) - c2
    up = 1 if _apply(m, c_far)[2] > 0 else -1
    far = _apply(m_far, c_far)[:2]
    return {"angle_deg": round(math.degrees(ang), 2), "inner_radius_mm": round(r_in, 3), "developed_mm": round(dev, 3),
            "up": up, "_c": c2[:2], "_d": d2[:2] / (np.linalg.norm(d2[:2]) or 1), "_far": far}


def unfold(shape, t: float, k_factor: float) -> dict:
    """Flat pattern of a bent part: {outline, holes, bends, length_mm, width_mm, area_mm2}, coordinates in mm with the
    origin at the lower-left corner and the long side along X."""
    sheet = _sheet_faces(shape, t)
    sheet_ids = {f.hashCode() for f in sheet}
    if not sheet:
        raise UnfoldError("No sheet faces found (is the thickness right?).")
    cyls = {}
    all_cyl = [f for f in shape.Faces() if f.geomType() == "CYLINDER"]
    for f in all_cyl:
        a, o, r = _cyl(f)
        for g in all_cyl:
            if g is f:
                continue
            a2, o2, r2 = _cyl(g)
            off = o2 - o
            if abs(abs(a @ a2) - 1) < 1e-3 and np.linalg.norm(off - (off @ a) * a) < 1e-3 and abs(abs(r - r2) - t) < max(0.05 * t, 0.01):
                cyls[f.hashCode()] = (f, a, o, r, min(r, r2))
                break
    faces = {f.hashCode(): f for f in shape.Faces()}
    adj = {}
    for h, f in faces.items():
        if h not in sheet_ids and h not in cyls:
            continue
        for e in f.Edges():
            adj.setdefault(e.hashCode(), []).append(h)
    base = max(sheet, key=lambda f: f.Area())
    n0 = np.array(base.normalAt().toTuple())
    c0 = np.array(base.Center().toTuple())
    # frame of the base face: z = its normal; x, y in its plane
    ex = np.cross(n0, [0, 0, 1]) if abs(n0[2]) < 0.9 else np.cross(n0, [1, 0, 0])
    ex /= np.linalg.norm(ex)
    ey = np.cross(n0, ex)
    frame = np.eye(4)
    frame[:3, :3] = np.vstack([ex, ey, n0])
    frame[:3, 3] = -frame[:3, :3] @ c0
    T = {base.hashCode(): frame}
    polys, bends = [], []
    queue = [base.hashCode()]

    def face_poly(f, m, mapper=None):
        to2 = (lambda p: _apply(m, p)[:2]) if mapper is None else mapper
        outer = [to2(p) for p in _wire_pts(f.outerWire())]
        inner = [[to2(p) for p in _wire_pts(w)] for w in f.innerWires()]
        try:
            poly = Polygon(outer, [w for w in inner if len(w) >= 3]).buffer(0)
        except Exception:
            poly = Polygon(outer).buffer(0)
        return poly

    while queue:
        h = queue.pop(0)
        f = faces[h]
        m = T[h]
        if h in sheet_ids:
            polys.append(face_poly(f, m))
        nbrs = {x for e in f.Edges() for x in adj.get(e.hashCode(), []) if x != h}
        for g in nbrs:
            if g in T:
                continue
            gf = faces[g]
            if h in sheet_ids and g in cyls:
                # cross the bend: the cylinder face, then the flat face on its far side
                cf, a, o, r_face, r_in = cyls[g]
                start = _shared(f, gf)
                if not start:
                    continue
                pA = np.array(start[0].Center().toTuple())
                radA = pA - o - ((pA - o) @ a) * a
                radA /= np.linalg.norm(radA)
                nA = np.array(f.normalAt(f.Center()).toTuple())
                # direction in face A's plane, square to the bend line, pointing into the bend
                cA = np.array(f.Center().toTuple())
                w = pA - cA
                w = w - (w @ a) * a - (w @ nA) * nA
                w /= np.linalg.norm(w)
                far = [x for e in gf.Edges() for x in adj.get(e.hashCode(), []) if x != g and x in sheet_ids and x != h]
                # angle of the bend from the face on the far side (else from the cylinder's own span)
                def ang_to(p):
                    rp = p - o - ((p - o) @ a) * a
                    rp /= np.linalg.norm(rp)
                    return math.atan2(np.linalg.norm(np.cross(radA, rp)), radA @ rp)
                span = max(ang_to(np.array(v.toTuple())) for v in gf.Vertices())
                r_n = r_in + k_factor * t
                dev = span * r_n

                def map_cyl(p, m=m, a=a, o=o, r_face=r_face, radA=radA, w=w, r_n=r_n, pA=pA):
                    al = ang_to(p)
                    on_line = pA + ((p - pA) @ a) * a
                    return _apply(m, on_line + w * al * r_n)[:2]
                T[g] = m
                polys.append(face_poly(gf, m, map_cyl))
                for fh in far:
                    if fh in T:
                        continue
                    ff = faces[fh]
                    nB = np.array(ff.normalAt(ff.Center()).toTuple())
                    # turn face B about the bend axis so that its normal matches face A's
                    best = None
                    for sgn in (1, -1):
                        R = _rot(a, sgn * span)
                        if best is None or (R @ nB) @ nA > best[0]:
                            best = ((R @ nB) @ nA, R)
                    R = best[1]
                    turn = _affine(R, o - R @ o)
                    T[fh] = m @ _affine(np.eye(3), w * dev) @ turn
                    queue.append(fh)
                    cB = np.array(ff.Center().toTuple())
                    bends.append(_bend(m, T[fh], pA + w * dev / 2, a, cB, span, r_in, dev))
            elif h in sheet_ids and g in sheet_ids:
                # sharp corner: two flat faces of the same side meeting at an edge (radius 0)
                nA = np.array(f.normalAt(f.Center()).toTuple())
                nB = np.array(gf.normalAt(gf.Center()).toTuple())
                if abs(nA @ nB) > 0.999:
                    T[g] = m
                    queue.append(g)
                    continue
                e = _shared(f, gf)[0]
                p0, p1 = (np.array(v.toTuple()) for v in (e.startPoint(), e.endPoint()))
                a = (p1 - p0) / np.linalg.norm(p1 - p0)
                ang = math.acos(max(-1, min(1, nA @ nB)))
                cA = np.array(f.Center().toTuple())
                w = p0 - cA
                w = w - (w @ a) * a - (w @ nA) * nA
                w /= np.linalg.norm(w)
                best = None
                for sgn in (1, -1):
                    R = _rot(a, sgn * ang)
                    if best is None or (R @ nB) @ nA > best[0]:
                        best = ((R @ nB) @ nA, R)
                dev = ang * k_factor * t
                # walking the outside of the corner: both flat faces run on to the outer corner, one
                # t·tan(angle/2) each beyond the bend line, so that length is taken off
                dB = np.array(gf.Center().toTuple()) - p0
                dB = dB - (dB @ a) * a
                shift = dev - (2 * t * math.tan(ang / 2) if dB @ nA < 0 else 0.0)
                T[g] = m @ _affine(np.eye(3), w * shift) @ _affine(best[1], p0 - best[1] @ p0)
                queue.append(g)
                bends.append(_bend(m, T[g], p0 + w * shift / 2, a, np.array(gf.Center().toTuple()), ang, 0.0, dev))
    flat = unary_union([p.buffer(0.01) for p in polys if not p.is_empty]).buffer(-0.01)
    if flat.geom_type != "Polygon":
        flat = max(getattr(flat, "geoms", [flat]), key=lambda p: p.area)
    flat = flat.simplify(0.01)
    # long side along X, origin at the lower-left
    x0, y0, x1, y1 = flat.bounds
    swap = (x1 - x0) < (y1 - y0)
    def mv(x, y):
        return [float(round(y - y0, 3)), float(round(x - x0, 3))] if swap else [float(round(x - x0, 3)), float(round(y - y0, 3))]
    outline = [mv(x, y) for x, y in flat.exterior.coords]
    holes = [[mv(x, y) for x, y in r.coords] for r in flat.interiors]
    for b in bends:
        c, d = b.pop("_c"), b.pop("_d")
        p0, p1 = mv(*(c - d * 1e4)), mv(*(c + d * 1e4))
        seg = LineString([p0, p1]).intersection(Polygon(outline).buffer(0.5))
        b["line"] = [[float(v) for v in seg.coords[0]], [float(v) for v in seg.coords[-1]]] if not seg.is_empty and hasattr(seg, "coords") else [p0, p1]
        b["far_side"] = mv(*b.pop("_far"))
    L, W = (y1 - y0, x1 - x0) if swap else (x1 - x0, y1 - y0)
    return {"outline": outline, "holes": holes, "bends": bends, "length_mm": round(L, 3), "width_mm": round(W, 3),
            "area_mm2": round(flat.area, 2), "faces": len(polys), "k_factor": k_factor}
