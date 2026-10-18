"""Generate simple sample STEP parts with known geometry.

Run from the repository root:  python samples/make_samples.py
"""

from pathlib import Path

import cadquery as cq

OUT = Path(__file__).resolve().parent


def plate_with_hole():
    """100 x 60 x 20 mm block with a Ø20 mm through hole (along Z)."""
    return cq.Workplane("XY").box(100, 60, 20).faces(">Z").workplane().hole(20)


def plastic_cover():
    """Open-top shell 120 x 80 x 30 mm, 2.5 mm wall, with 4 bosses."""
    shell = cq.Workplane("XY").box(120, 80, 30).edges("|Z").fillet(5).faces(">Z").shell(-2.5)
    points = [(x, y) for x in (-45, 45) for y in (-25, 25)]
    base = cq.Workplane("XY").workplane(offset=-12.5).pushPoints(points)
    bosses = base.circle(4).extrude(20)
    cores = base.circle(1.5).extrude(20)
    return shell.union(bosses).cut(cores)


def sheet_metal_bracket():
    """L-bracket, 2 mm sheet, 50 mm wide, legs 80 mm and 40 mm."""
    return (
        cq.Workplane("XZ")
        .polyline([(0, 0), (80, 0), (80, 2), (2, 2), (2, 40), (0, 40)])
        .close()
        .extrude(-50)
    )


if __name__ == "__main__":
    for name, fn in [
        ("plate_with_hole", plate_with_hole),
        ("plastic_cover", plastic_cover),
        ("sheet_metal_bracket", sheet_metal_bracket),
    ]:
        path = OUT / f"{name}.step"
        cq.exporters.export(fn(), str(path))
        print("wrote", path)
