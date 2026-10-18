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


def demo_assembly():
    """Base plate + bracket group (2 identical brackets) + 4 identical pins + 1 look-alike pin."""
    plate = cq.Workplane("XY").box(200, 120, 10)
    bracket = (cq.Workplane("XZ").polyline([(0, 0), (40, 0), (40, 4), (4, 4), (4, 30), (0, 30)])
               .close().extrude(-25))
    pin = cq.Workplane("XY").circle(4).extrude(20)
    group = cq.Assembly(name="bracket_group")
    group.add(bracket, name="bracket", loc=cq.Location((0, 0, 5)))
    group.add(bracket, name="bracket_2", loc=cq.Location((60, 0, 5)))
    assy = cq.Assembly(name="demo_assembly")
    assy.add(plate, name="base_plate")
    assy.add(group, name="bracket_group", loc=cq.Location((-80, -20, 0)))
    for i, (x, y) in enumerate([(-90, -50), (90, -50), (-90, 50), (90, 50)]):
        assy.add(pin, name=f"pin_{i + 1}", loc=cq.Location((x, y, 5)))
    assy.add(cq.Workplane("XY").circle(4).extrude(20), name="locating_pin", loc=cq.Location((0, 50, 5)))
    return assy


if __name__ == "__main__":
    demo_assembly().export(str(OUT / "demo_assembly.step"))
    print("wrote", OUT / "demo_assembly.step")
    for name, fn in [
        ("plate_with_hole", plate_with_hole),
        ("plastic_cover", plastic_cover),
        ("sheet_metal_bracket", sheet_metal_bracket),
    ]:
        path = OUT / f"{name}.step"
        cq.exporters.export(fn(), str(path))
        print("wrote", path)
