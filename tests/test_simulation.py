import math

import cadquery as cq
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import formula, mould_db, simulation
from backend.app.geometry import analyze, tessellate
from backend.app.main import app

client = TestClient(app)


def facts(shape, **kw):
    m = analyze(shape, "plastic", 1.0)
    bb = sorted(m.bbox_mm.values(), reverse=True)
    return {"part_weight_g": 20, "wall_mm": 0, "part_l": bb[0], "part_w": bb[1], "part_h": bb[2],
            "projected_area_cm2": m.projected_area_cm2, "volume_cm3": m.volume_mm3 / 1000, "cavities": 2,
            "slides": 0, "lifters": 0, "inserts": 0} | kw, m.projected_area_mm2


def run(shape, part_type="plastic", **kw):
    f, pa = facts(shape, **kw)
    return simulation.run(*tessellate(shape), part_type, f, pa)


def test_thickness_by_ray_casting():
    plate = cq.Workplane("XY").box(80, 60, 3).val()
    r = run(plate)
    assert r["results"]["min_wall_mm"] == pytest.approx(3, abs=0.01)  # most faces: through the 3 mm plate
    assert r["opening_axis"] == "z"


def test_vertical_walls_without_draft_are_flagged():
    plate = cq.Workplane("XY").box(80, 60, 3).val()
    r = run(plate)
    assert r["maps"]["draft_low_cm2"] == pytest.approx(2 * (80 + 60) * 3 / 100, rel=1e-3)
    assert any("draft" in c for c in r["corrections"])


def test_cooling_cycle_and_clamp_follow_the_rules():
    plate = cq.Workplane("XY").box(80, 60, 3).val()
    r = run(plate, wall_mm=3)
    res = r["results"]
    w = res["max_wall_mm"]
    cooling = w**2 / (9.8696 * 0.09) * math.log(4 / 3.1416 * (230 - 50) / (90 - 50))
    assert res["cooling_s"] == pytest.approx(cooling)
    assert res["cycle_s"] == pytest.approx(0.5 + 40 / 50 + cooling + 4)
    bar = min(1800, 300 + 4 * (80 + 3) / 3) * 0.4
    assert res["clamp_t"] == pytest.approx(48 * 2 * bar * 1.2 / 1000)
    assert r["machine"]["machine_id"] == "IMM-80"                          # smallest moulding machine ≥ clamp


def test_thick_boss_is_a_sink_risk():
    part = cq.Workplane("XY").box(80, 60, 3).union(cq.Workplane("XY").box(20, 20, 15).translate((0, 0, 7))).val()
    r = run(part, wall_mm=3)
    assert r["maps"]["sink_risk_cm2"] > 0 and any("Core out" in c for c in r["corrections"])


def test_insert_loading_adds_to_the_cycle():
    plate = cq.Workplane("XY").box(80, 60, 3).val()
    a, b = run(plate, wall_mm=3), run(plate, wall_mm=3, inserts=2)
    assert b["results"]["cycle_s"] - a["results"]["cycle_s"] == pytest.approx(2 * 2 * 3.0)   # 4 per shot ≤ 4: manual, no table


def test_die_casting_rules_and_pictures():
    plate = cq.Workplane("XY").box(80, 60, 3).val()
    r = run(plate, "die_casting", wall_mm=3)
    assert r["results"]["clamp_t"] == pytest.approx(48 * 2 * 1.3 * 800 * 1.2 / 1000)
    pics = simulation.pictures(r)
    assert len(pics) == 3 and all(p[:4] == b"\x89PNG" for _, p in pics)


def test_formula_log_and_bad_rule():
    assert formula.evaluate("log(exp(2))", {}) == pytest.approx(2)
    db = mould_db.tables()
    next(r for r in db["simulation_rules"] if r["name"] == "cycle_s")["formula"] = "nope + 1"
    with pytest.raises(mould_db.MouldDbError, match="Simulation rules row"):
        mould_db.write(db)


def test_part_simulation_endpoint_and_pdf():
    from tests.test_rm_cost import add_part, project
    pid = add_part(project("SIM"))
    r = client.get(f"/api/parts/{pid}/simulation")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["machine"]["process"] == "Injection moulding" and "cycle_s" in s["results"] and s["is_example"]
    pdf = client.get(f"/api/parts/{pid}/simulation/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
