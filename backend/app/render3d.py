"""Shaded pictures of 3D models without a graphics card (roadmap stage 27): iso views of tool assemblies on the
drawings and the frames of the sheet-metal simulation video.

Every solid is tessellated, its triangles are projected (orthographic) for the view direction and
filled with a flat Lambert shade of the solid's colour with a depth buffer (numpy); object outlines are darkened.
"""

from __future__ import annotations

import io
import math

import numpy as np
from PIL import Image


def mesh(shape, tol: float = 0.4):
    verts, tris = shape.tessellate(tol, 0.3)
    v = np.array([p.toTuple() for p in verts], float)
    t = np.array(tris, int)
    return v, t


def view_matrix(az_deg: float = -50, el_deg: float = 30):
    az, el = math.radians(az_deg), math.radians(el_deg)
    d = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])   # towards the viewer
    up = np.array([0, 0, 1.0])
    right = np.cross(up, d)
    right /= np.linalg.norm(right)
    up2 = np.cross(d, right)
    return np.vstack([right, up2, d])


def render(items, size=(1200, 800), az=-50, el=30, bg=(255, 255, 255), bounds=None, margin=0.06, edges=True,
           sphere=None) -> Image.Image:
    """items: list of (vertices (n×3), triangles (m×3), (r, g, b) 0-1). Returns a Pillow image (depth-buffered)."""
    M = view_matrix(az, el)
    light = M[2] * 0.6 + M[0] * -0.3 + M[1] * 0.5
    light /= np.linalg.norm(light)
    W, H = size
    img = np.empty((H, W, 3), np.uint8)
    img[:] = bg
    zbuf = np.full((H, W), -np.inf)
    ids = np.full((H, W), -1, np.int64)
    items = [it for it in items if len(it[1])]
    if not items:
        return Image.fromarray(img)
    proj = [v @ M.T for v, _, _ in items]
    if sphere is not None:          # same zoom from every direction: the bounding sphere seen from this view
        c = M @ np.asarray(sphere[0], float)
        r = sphere[1]
        bounds = (c[0] - r, c[1] - r, c[0] + r, c[1] + r)
    if bounds is None:
        q = np.vstack(proj)
        x0, y0, x1, y1 = q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max()
    else:
        x0, y0, x1, y1 = bounds
    s = min(W * (1 - 2 * margin) / max(x1 - x0, 1e-9), H * (1 - 2 * margin) / max(y1 - y0, 1e-9))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    obj = 0
    for (v, t, rgb), p in zip(items, proj):
        obj += 1
        P = np.column_stack([W / 2 + (p[:, 0] - cx) * s, H / 2 - (p[:, 1] - cy) * s, p[:, 2]])
        n = np.cross(v[t][:, 1] - v[t][:, 0], v[t][:, 2] - v[t][:, 0])
        ln = np.linalg.norm(n, axis=1)
        ok = ln > 1e-12
        n[ok] /= ln[ok, None]
        shade = 0.38 + 0.62 * np.abs(n @ light)
        base = np.array(rgb) * 255
        T = P[t]                                   # triangles × 3 × (x, y, z)
        span = np.maximum(T[:, :, 0].max(1) - T[:, :, 0].min(1), T[:, :, 1].max(1) - T[:, :, 1].min(1))
        tiny = ok & (span < 1.5)
        if tiny.any():                             # smaller than a pixel: one pixel at the centre, all at once
            c = T[tiny].mean(1)
            xi, yi = c[:, 0].astype(int), c[:, 1].astype(int)
            inside = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
            c, xi, yi = c[inside], xi[inside], yi[inside]
            col = np.clip(base[None, :] * shade[tiny][inside][:, None], 0, 255).astype(np.uint8)
            order = np.argsort(c[:, 2])            # far first, so the nearest one is written last
            xi, yi, z, col = xi[order], yi[order], c[order, 2], col[order]
            front = z > zbuf[yi, xi]
            img[yi[front], xi[front]] = col[front]
            zbuf[yi[front], xi[front]] = np.maximum(zbuf[yi[front], xi[front]], z[front])
            ids[yi[front], xi[front]] = obj
        rest = ok & ~tiny
        for size in (4, 8, 16, 32, 64):           # small triangles: many at once, by the size of their box
            pick = rest & (span < size - 1)
            if pick.any():
                cols = np.clip(base[None, :] * shade[pick][:, None], 0, 255).astype(np.uint8)

                def write(pix, k, cols=cols, obj=obj):
                    img.reshape(-1, 3)[pix] = cols[k]
                    ids.flat[pix] = obj
                _fill(T[pick], size, zbuf, write)
                rest &= ~pick
        for k in np.nonzero(rest)[0]:             # the few large ones, one by one
            a_, b_, c_ = P[t[k]]
            xmin, xmax = int(max(0, np.floor(min(a_[0], b_[0], c_[0])))), int(min(W - 1, np.ceil(max(a_[0], b_[0], c_[0]))))
            ymin, ymax = int(max(0, np.floor(min(a_[1], b_[1], c_[1])))), int(min(H - 1, np.ceil(max(a_[1], b_[1], c_[1]))))
            if xmin > xmax or ymin > ymax:
                continue
            den = (b_[1] - c_[1]) * (a_[0] - c_[0]) + (c_[0] - b_[0]) * (a_[1] - c_[1])
            if abs(den) < 1e-12:
                continue
            xs = np.arange(xmin, xmax + 1)[None, :] + 0.5
            ys = np.arange(ymin, ymax + 1)[:, None] + 0.5
            w1 = ((b_[1] - c_[1]) * (xs - c_[0]) + (c_[0] - b_[0]) * (ys - c_[1])) / den
            w2 = ((c_[1] - a_[1]) * (xs - c_[0]) + (a_[0] - c_[0]) * (ys - c_[1])) / den
            w3 = 1 - w1 - w2
            inside = (w1 >= -1e-6) & (w2 >= -1e-6) & (w3 >= -1e-6)
            if not inside.any():
                continue
            z = w1 * a_[2] + w2 * b_[2] + w3 * c_[2]
            zb = zbuf[ymin:ymax + 1, xmin:xmax + 1]
            upd = inside & (z > zb)
            zb[upd] = z[upd]
            img[ymin:ymax + 1, xmin:xmax + 1][upd] = np.clip(base * shade[k], 0, 255).astype(np.uint8)
            ids[ymin:ymax + 1, xmin:xmax + 1][upd] = obj
    if edges:   # dark outline where the visible object changes
        e = np.zeros((H, W), bool)
        e[:, 1:] |= ids[:, 1:] != ids[:, :-1]
        e[1:, :] |= ids[1:, :] != ids[:-1, :]
        img[e] = (img[e] * 0.35).astype(np.uint8)
    return Image.fromarray(img)


def _fill(T, size, zbuf, write):
    """Rasterise triangles (n × 3 × (x, y, z)) whose box fits in size × size pixels, in chunks, with the depth buffer;
    write(pixel indices, triangle indices) paints the pixels where a triangle is the nearest so far."""
    H, W = zbuf.shape
    off = np.arange(size)
    chunk = max(1, 2_000_000 // (size * size))
    for s0 in range(0, len(T), chunk):
        t = T[s0:s0 + chunk]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        x0 = np.floor(t[:, :, 0].min(1)).astype(np.int64)
        y0 = np.floor(t[:, :, 1].min(1)).astype(np.int64)
        den = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
        good = np.abs(den) > 1e-12
        den = np.where(good, den, 1.0)
        xs = x0[:, None, None] + off[None, None, :]
        ys = y0[:, None, None] + off[None, :, None]
        px, py = xs + 0.5 - c[:, 0, None, None], ys + 0.5 - c[:, 1, None, None]
        w1 = ((b[:, 1] - c[:, 1])[:, None, None] * px + (c[:, 0] - b[:, 0])[:, None, None] * py) / den[:, None, None]
        w2 = ((c[:, 1] - a[:, 1])[:, None, None] * px + (a[:, 0] - c[:, 0])[:, None, None] * py) / den[:, None, None]
        w3 = 1 - w1 - w2
        inside = ((w1 >= -1e-6) & (w2 >= -1e-6) & (w3 >= -1e-6) & good[:, None, None]
                  & (xs >= 0) & (xs < W) & (ys >= 0) & (ys < H))
        k, iy, ix = np.nonzero(inside)
        if not len(k):
            continue
        z = (w1 * a[:, 2, None, None] + w2 * b[:, 2, None, None] + w3 * c[:, 2, None, None])[k, iy, ix]
        pix = ys[k, iy, 0] * W + xs[k, 0, ix]
        order = np.lexsort((z, pix))                # nearest last for every pixel
        pix, z, k = pix[order], z[order], k[order]
        last = np.r_[pix[1:] != pix[:-1], True]
        pix, z, k = pix[last], z[last], k[last]
        front = z > zbuf.flat[pix]
        pix, z, k = pix[front], z[front], k[front]
        zbuf.flat[pix] = z
        write(pix, k + s0)


def face_view(tri: np.ndarray, size=(960, 540), az=-50, el=30, sphere=None, margin=0.06) -> dict:
    """Which triangle (index, -1 = background) and which shade every pixel shows, for one view of a mesh (m × 3 × 3).
    Drawn once per view; paint() then colours it for any map (wall, fill time, pressure …) without drawing again."""
    M = view_matrix(az, el)
    light = M[2] * 0.6 + M[0] * -0.3 + M[1] * 0.5
    light /= np.linalg.norm(light)
    W, H = size
    p = tri.reshape(-1, 3) @ M.T
    if sphere is not None:
        c, r = M @ np.asarray(sphere[0], float), sphere[1]
        x0, y0, x1, y1 = c[0] - r, c[1] - r, c[0] + r, c[1] + r
    else:
        x0, y0, x1, y1 = p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()
    s = min(W * (1 - 2 * margin) / max(x1 - x0, 1e-9), H * (1 - 2 * margin) / max(y1 - y0, 1e-9))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    T = np.column_stack([W / 2 + (p[:, 0] - cx) * s, H / 2 - (p[:, 1] - cy) * s, p[:, 2]]).reshape(-1, 3, 3)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1)
    ok = ln > 1e-12
    n[ok] /= ln[ok, None]
    shade = 0.38 + 0.62 * np.abs(n @ light)
    zbuf = np.full((H, W), -np.inf)
    tid = np.full((H, W), -1, np.int64)
    span = np.maximum(T[:, :, 0].max(1) - T[:, :, 0].min(1), T[:, :, 1].max(1) - T[:, :, 1].min(1))
    tiny = np.nonzero(ok & (span < 1.5))[0]
    if len(tiny):                                  # smaller than a pixel: one pixel at the centre
        c = T[tiny].mean(1)
        xi, yi = c[:, 0].astype(int), c[:, 1].astype(int)
        inside = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
        c, xi, yi, k = c[inside], xi[inside], yi[inside], tiny[inside]
        order = np.argsort(c[:, 2])
        xi, yi, z, k = xi[order], yi[order], c[order, 2], k[order]
        front = z > zbuf[yi, xi]
        zbuf[yi[front], xi[front]] = z[front]
        tid[yi[front], xi[front]] = k[front]
    rest = ok & (span >= 1.5)
    for size_px in (4, 8, 16, 32, 64):
        pick = np.nonzero(rest & (span < size_px - 1))[0]
        if len(pick):
            _fill(T[pick], size_px, zbuf, lambda pix, k, pick=pick: tid.flat.__setitem__(pix, pick[k]))
            rest[pick] = False
    for k in np.nonzero(rest)[0]:                  # the few large ones, one by one
        _fill(T[k:k + 1], int(np.ceil(span[k])) + 2, zbuf, lambda pix, _, k=k: tid.flat.__setitem__(pix, k))
    return {"tid": tid, "shade": np.where(tid >= 0, shade[np.maximum(tid, 0)], 1.0), "size": (W, H)}


def paint(view: dict, face_rgb: np.ndarray, bg=(255, 255, 255), edges: bool = True, edge_key: np.ndarray | None = None) -> Image.Image:
    """Colour a face_view: face_rgb (m × 3, 0-1) per triangle, shaded; outlines where edge_key (per triangle) changes."""
    tid, W, H = view["tid"], *view["size"]
    img = np.empty((H, W, 3), np.uint8)
    img[:] = bg
    hit = tid >= 0
    img[hit] = np.clip(np.asarray(face_rgb)[tid[hit]] * 255 * view["shade"][hit][:, None], 0, 255).astype(np.uint8)
    if edges:
        key = np.full((H, W), -1, np.int64)
        key[hit] = (edge_key if edge_key is not None else np.zeros(len(face_rgb), np.int64))[tid[hit]]
        e = np.zeros((H, W), bool)
        e[:, 1:] |= key[:, 1:] != key[:, :-1]
        e[1:, :] |= key[1:, :] != key[:-1, :]
        img[e] = (img[e] * 0.35).astype(np.uint8)
    return Image.fromarray(img)


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def projected_bounds(items, az=-50, el=30):
    M = view_matrix(az, el)
    q = np.vstack([v @ M.T for v, t, _ in items if len(v)])
    return q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max()


def design_items(design: dict, colors: dict, explode: float = 0.0, skip_ref: bool = False):
    """Tessellated components of a tool design at their positions (explode: lift by the stack position × factor)."""
    items = []
    for c in design["components"]:
        if skip_ref and c.kind == "ref":
            continue
        v, t = mesh(c.shape, tol=max(0.3, max(c.size) / 150 if c.size else 0.4))
        rgb = colors.get(c.color, (0.6, 0.6, 0.6))
        for (x, y, z) in c.locs:
            items.append((v + np.array([x, y, z * (1 + explode)]), t, rgb))
    return items


def sphere_of(items):
    """(centre, radius) around every vertex of the items."""
    q = np.vstack([v for v, t, _ in items if len(v)])
    c = (q.min(0) + q.max(0)) / 2
    return c, float(np.linalg.norm(q - c, axis=1).max())
