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


def example_bracket(radius: float = 0.0):
    """Work-instruction example: L mounting bracket, 2 mm galvanised sheet, 40 mm wide, legs 250 mm and 80 mm,
    four Ø8.5 holes in the long leg and two in the short leg. Rev A has a 0.5 mm inside bend radius (too tight), Rev B a 2 mm
    inside bend radius (the correction asked by the forming simulation)."""
    t, w = 2.0, 40.0
    prof = cq.Workplane("XZ").polyline([(0, 0), (250, 0), (250, t), (t, t), (t, 80), (0, 80)]).close().extrude(-w)
    if radius:
        prof = prof.edges("|Y").edges(cq.selectors.NearestToPointSelector((t, w / 2, t))).fillet(radius)
        prof = prof.edges("|Y").edges(cq.selectors.NearestToPointSelector((0, w / 2, 0))).fillet(radius + t)
    long_holes = cq.Workplane("XY").pushPoints([(60, w / 2), (110, w / 2), (160, w / 2), (210, w / 2)]).circle(4.25).extrude(10).translate((0, 0, -5))
    short_holes = cq.Workplane("YZ").pushPoints([(w / 2, 35), (w / 2, 65)]).circle(4.25).extrude(10).translate((-5, 0, 0))
    return prof.cut(long_holes).cut(short_holes)


def large_plastic_tub():
    """Large moulded part (about 12 kg PP): open tub 1050 x 700 x 420 mm, 6 mm wall, rounded corners, 4 ribs under the floor.
    Needs a mould for a 3000 t class injection machine."""
    tub = (cq.Workplane("XY").box(1050, 700, 420).edges("|Z").fillet(60).faces("<Z").edges().fillet(30)
           .faces(">Z").shell(-6))
    ribs = cq.Workplane("XY").workplane(offset=-210).pushPoints([(x, 0) for x in (-315, -105, 105, 315)]).rect(6, 600).extrude(-40)
    return tub.union(ribs)


def large_sheet_tray():
    """Large deep-drawn sheet part (about 16 kg): tray 1400 x 900 mm, 120 mm deep, 1.2 mm sheet, corner radius 60 mm.
    Needs a drawing die on a large press."""
    return (cq.Workplane("XY").box(1400, 900, 120).edges("|Z").fillet(60).faces("<Z").edges().fillet(15)
            .faces(">Z").shell(-1.2))


def large_sheet_channel():
    """Large bent sheet part (about 18 kg): U channel 1600 mm long, 300 mm base, 100 mm flanges, 3 mm sheet, inside radius 6 mm,
    8 Ø14 holes in the base."""
    t, r = 3.0, 6.0
    prof = (cq.Workplane("YZ").polyline([(0, 0), (300, 0), (300, 100), (300 - t, 100), (300 - t, t), (t, t), (t, 100), (0, 100)])
            .close().extrude(1600))
    prof = prof.edges("|X").edges(cq.selectors.NearestToPointSelector((800, t, t))).fillet(r)
    prof = prof.edges("|X").edges(cq.selectors.NearestToPointSelector((800, 300 - t, t))).fillet(r)
    prof = prof.edges("|X").edges(cq.selectors.NearestToPointSelector((800, 0, 0))).fillet(r + t)
    prof = prof.edges("|X").edges(cq.selectors.NearestToPointSelector((800, 300, 0))).fillet(r + t)
    holes = cq.Workplane("XY").pushPoints([(x, y) for x in (200, 600, 1000, 1400) for y in (90, 210)]).circle(7).extrude(20).translate((0, 0, -10))
    return prof.cut(holes)


def pet_bottle():
    """500 ml PET bottle (blow moulding): body Ø65 x 160 mm, shoulder, neck Ø28 x 20 mm, 0.5 mm wall, axis along X."""
    prof = (cq.Workplane("XY").moveTo(0, 0).lineTo(32.5, 0).lineTo(32.5, 160).threePointArc((26, 180), (14, 195))
            .lineTo(14, 215).lineTo(0, 215).close())
    body = prof.revolve(360, (0, 0, 0), (0, 1, 0))
    return body.faces(">Y").shell(-0.5).rotate((0, 0, 0), (0, 0, 1), -90)


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


def insert_moulded_housing():
    """Plastic housing 80 x 50 x 20 mm (2.5 mm wall) with 4 bosses; a brass threaded insert
    (tube Ø6 / Ø3.4 x 8 mm) sits in a blind hole in each boss; plus a loose cover screwed on top."""
    points = [(x, y) for x in (-30, 30) for y in (-17, 17)]
    shell = cq.Workplane("XY").box(80, 50, 20).faces(">Z").shell(-2.5)
    bosses = cq.Workplane("XY").workplane(offset=-7.5).pushPoints(points).circle(5).extrude(17.5)
    holes = cq.Workplane("XY").workplane(offset=2).pushPoints(points).circle(3).extrude(8)
    housing = shell.union(bosses).cut(holes)
    insert = cq.Workplane("XY").circle(3).circle(1.7).extrude(8)
    cover = cq.Workplane("XY").box(80, 50, 2).translate((0, 0, 11))
    assy = cq.Assembly(name="housing_assembly")
    body = cq.Assembly(name="housing_with_inserts")
    body.add(housing, name="housing")
    for i, (x, y) in enumerate(points):
        body.add(insert, name=f"threaded_insert_{i + 1}", loc=cq.Location((x, y, 2)))
    assy.add(body, name="housing_with_inserts")
    assy.add(cover, name="cover")
    return assy


def machined_shaft():
    """Turned shaft along Z: Ø40 x 30 collar, Ø25 x 60 journal, Ø16 x 20 spigot, Ø8 centre bore 15 deep, 2 cross holes Ø6."""
    body = (cq.Workplane("XY").circle(20).extrude(30)
            .faces(">Z").workplane().circle(12.5).extrude(60)
            .faces(">Z").workplane().circle(8).extrude(20)
            .faces(">Z").workplane().hole(8, 15))
    cross = cq.Workplane("YZ").workplane(offset=-30).center(0, 15).circle(3).extrude(60)
    return body.cut(cross)


def machined_block():
    """Milled block 80 x 50 x 30 mm with a 40 x 20 x 10 pocket and 4 drilled holes Ø8."""
    pts = [(x, y) for x in (-30, 30) for y in (-15, 15)]
    return (cq.Workplane("XY").box(80, 50, 30)
            .faces(">Z").workplane().rect(40, 20).cutBlind(-10)
            .faces(">Z").workplane().pushPoints(pts).hole(8))


if __name__ == "__main__":
    demo_assembly().export(str(OUT / "demo_assembly.step"))
    print("wrote", OUT / "demo_assembly.step")
    insert_moulded_housing().export(str(OUT / "insert_moulded_housing.step"))
    print("wrote", OUT / "insert_moulded_housing.step")
    for name, fn in [
        ("plate_with_hole", plate_with_hole),
        ("plastic_cover", plastic_cover),
        ("sheet_metal_bracket", sheet_metal_bracket),
        ("example_bracket_revA", lambda: example_bracket(0.5)),
        ("example_bracket_revB", lambda: example_bracket(2.0)),
        ("large_plastic_tub", large_plastic_tub),
        ("large_sheet_tray", large_sheet_tray),
        ("large_sheet_channel", large_sheet_channel),
        ("pet_bottle", pet_bottle),
        ("machined_shaft", machined_shaft),
        ("machined_block", machined_block),
    ]:
        path = OUT / f"{name}.step"
        cq.exporters.export(fn(), str(path))
        print("wrote", path)
