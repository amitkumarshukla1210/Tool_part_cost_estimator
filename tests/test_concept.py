import cadquery as cq
import pytest
from fastapi.testclient import TestClient

from backend.app import concept, mould_db
from backend.app.geometry import analyze, load_step, tessellate
from backend.app.main import app

client = TestClient(app)


def mesh(shape):
    return tessellate(shape)


def areas(shape):
    return analyze(shape, "plastic", 1.0).projected_area_mm2


def hooked_cup():
    """Open-top cup (walls 2 mm) with a ledge on the inside of one wall: shadowed along Z, so an undercut."""
    cup = cq.Workplane("XY").box(60, 40, 30).cut(cq.Workplane("XY").box(56, 36, 30).translate((0, 0, 2)))
    return cup.union(cq.Workplane("XY").box(20, 4, 4).translate((0, 16, 4))).val()


def test_plain_box_has_no_undercut():
    box = cq.Workplane("XY").box(60, 40, 20).val()
    r = concept.analyze(*mesh(box), "plastic", areas(box))
    assert r["undercut_area_cm2"] == 0 and r["slides"] == 0 and r["lifters"] == 0


def test_side_hole_is_a_slide_and_opening_axis_avoids_it():
    # block with a hole through its X side only: opening along X leaves no undercut, Z/Y do
    box = cq.Workplane("XY").box(60, 40, 30).faces(">X").workplane().hole(10).val()
    r = concept.analyze(*mesh(box), "plastic", areas(box))
    assert r["opening_axis"] == "x" and r["slides"] == 0
    z = next(x for x in r["ranking"] if x["axis"] == "z")
    assert z["undercut_area_mm2"] > 0


def test_internal_pocket_with_side_opening_needs_a_lifter():
    # hollow box (open at top) with an internal rib-hook undercut: box shell + inward lip near the rim
    part = hooked_cup()
    r = concept.analyze(*mesh(part), "plastic", areas(part))
    assert r["opening_axis"] == "z" and r["lifters"] + r["slides"] >= 1
    assert all(x["kind"] in ("slide", "lifter") for x in r["regions"])


def test_die_casting_never_proposes_lifters():
    part = hooked_cup()
    assert concept.analyze(*mesh(part), "die_casting", areas(part))["lifters"] == 0


def test_proposals_follow_rules_in_the_database():
    facts = {"cavities": 4, "part_weight_g": 20, "slides": 0, "lifters": 1, "inserts": 2, "part_h": 20, "part_l": 80}
    p = {x["topic"]: x for x in concept.proposals("plastic", facts)}
    assert set(p) == {"gate", "runner", "cooling", "ejection", "insert"}
    assert "Sub (tunnel)" in p["gate"]["proposal"] and "lifters" in p["ejection"]["proposal"]
    db = mould_db.tables()
    for r in db["concept_rules"]:
        if r["part_type"] == "plastic" and r["topic"] == "gate" and r["step"] == 1:
            r["proposal"] = "Changed in master data"
    mould_db.write(db)
    assert concept.proposals("plastic", facts)[0]["proposal"] == "Changed in master data"


def test_bad_rule_is_rejected():
    db = mould_db.tables()
    db["concept_rules"][0]["condition"] = "no_such_name > 1"
    with pytest.raises(mould_db.MouldDbError, match="Concept rules row 2"):
        mould_db.write(db)


def test_part_concept_endpoint():
    from tests.test_rm_cost import add_part, project
    pid = add_part(project("CN"))
    r = client.get(f"/api/parts/{pid}/concept")
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["opening_axis"] in ("x", "y", "z") and {x["topic"] for x in c["proposals"]} >= {"gate", "runner", "cooling", "ejection"}
    assert c["rules"]["is_example"] and len(c["ranking"]) == 3


def test_concept_endpoint_says_why_not():
    assert client.get("/api/parts/999999/concept").status_code in (400, 404)
