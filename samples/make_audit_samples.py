"""Sample 3D parts of every tool group at a low and a high capacity, for the end-to-end audit (scripts/audit_e2e.py).

Run from the repository root:  python samples/make_audit_samples.py
"""

from pathlib import Path

import cadquery as cq

OUT = Path(__file__).resolve().parent / "audit"


def cover(l, w, h, wall, boss=4, ribs=False):
    shell = cq.Workplane("XY").box(l, w, h).edges("|Z").fillet(min(l, w) / 16).faces(">Z").shell(-wall)
    pts = [(x, y) for x in (-l * 0.38, l * 0.38) for y in (-w * 0.3, w * 0.3)]
    base = cq.Workplane("XY").workplane(offset=-h / 2 + wall).pushPoints(pts)
    out = shell.union(base.circle(boss).extrude(h * 0.6)).cut(base.circle(boss * 0.4).extrude(h * 0.6))
    if ribs:
        for dx in (-l / 4, 0, l / 4):
            out = out.union(cq.Workplane("XY").box(wall, w - 2 * wall - 2, h * 0.5).translate((dx, 0, -h / 2 + wall + h * 0.25)))
    return out


def foundry_box(l, w, h, wall, hole):
    body = cq.Workplane("XY").box(l, w, h, centered=(True, True, False)).faces(">Z").workplane().rect(l - 2 * wall, w - 2 * wall).cutBlind(-(h - wall))
    return body.faces(">X").workplane(centerOption="CenterOfBoundBox").hole(hole)


def u_channel(l, w, h, t):
    return cq.Workplane("XZ").polyline([(0, 0), (w, 0), (w, h), (w - t, h), (w - t, t), (t, t), (t, h), (0, h)]).close().extrude(-l)


def bottle(r, h, neck_r, wall):
    def body(rr, hh, nr, z0):
        pts = [(0, z0), (rr, z0), (rr, hh * 0.7), (nr, hh * 0.85), (nr, hh + 1 if z0 else hh), (0, hh + 1 if z0 else hh)]
        return cq.Workplane("XZ").polyline(pts).close().revolve(360, (0, 0, 0), (0, 1, 0))
    return body(r, h, neck_r, 0).cut(body(r - wall, h - wall * 0.5, neck_r - wall, wall))


PARTS = {
    "plastic_small": cover(80, 50, 20, 2),
    "plastic_large": cover(900, 500, 150, 3, boss=10, ribs=True),
    "diecast_small": cover(70, 50, 25, 2.5, boss=4),
    "diecast_large": cover(650, 450, 120, 4, boss=9, ribs=True),
    "foundry_small": foundry_box(120, 80, 50, 10, 20),
    "foundry_large": foundry_box(700, 450, 250, 25, 90),
    "sheet_small": u_channel(60, 30, 20, 1.0),
    "sheet_large": u_channel(500, 250, 60, 2.0),
    "eps_small": cover(200, 150, 80, 15, boss=6),
    "eps_large": cover(1000, 600, 400, 30, boss=15),
    "blow_small": bottle(30, 150, 12, 0.6),
    "blow_large": bottle(75, 300, 22, 1.5),
}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, wp in PARTS.items():
        cq.exporters.export(wp, str(OUT / f"{name}.step"))
        print(name, [round(x) for x in (wp.val().BoundingBox().xlen, wp.val().BoundingBox().ylen, wp.val().BoundingBox().zlen)])
