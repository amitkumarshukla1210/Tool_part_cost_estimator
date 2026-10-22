import cadquery as cq
import pytest
from fastapi.testclient import TestClient

from backend.app import mould_db, sheet_tools
from backend.app.geometry import analyze, blank_estimate
from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def feats(shape, **typed):
    m = analyze(shape, "sheet_metal", 7.85)
    g = {"volume_mm3": m.volume_mm3, "bbox_mm": m.bbox_mm, "wall_mm": 2.0, "bend_count": 0}
    blank = blank_estimate(m.volume_mm3, m.bbox_mm, 2.0)
    return sheet_tools.features(shape, g, blank, typed, 7.85, 200000, 5)


def plate():
    return cq.Workplane("XY").box(80, 60, 2).faces(">Z").workplane().rarray(30, 20, 2, 2).hole(6).val()


def test_forces_by_hand_and_sequence():
    f = feats(plate())
    assert f["hole_count"] == 4 and f["hole_perimeter"] == pytest.approx(4 * 3.14159 * 6, rel=1e-3)
    r = sheet_tools.run(f, "Mild steel CRCA / HR", {})
    by = {o["code"]: o for o in r["operations"]}
    assert list(by) == ["blank", "pierce"]                              # no bends, no draw
    assert by["blank"]["force_t"] == pytest.approx(2 * (80 + 60) * 2 * 300 / 9806.65 * 1.1)
    assert by["pierce"]["force_t"] == pytest.approx(f["hole_perimeter"] * 2 * 300 / 9806.65 * 1.1)
    slug = 4 * 28.274 * 2 * 7.85 / 1000
    assert by["blank"]["stage_weight_g"] == pytest.approx(f["weight_g"] + slug, rel=1e-3)
    assert by["pierce"]["stage_weight_g"] == pytest.approx(f["weight_g"])
    assert r["mode"] == "progressive" and r["press"]["all stations"]["machine_id"] == "PRESS-63"
    assert r["design_force_t"] == pytest.approx(r["total_force_t"] * 1.25)


def test_multi_stage_gets_a_press_per_operation_and_edits_are_honoured():
    f = feats(plate())
    r = sheet_tools.run(f, "Mild steel CRCA / HR", {"mode": "multi_stage", "operations": ["pierce", "blank", "bend"]})
    assert [o["code"] for o in r["operations"]] == ["pierce", "blank", "bend"] and r["sequence_source"] == "your sequence"
    assert all(o["press"]["machine_id"] for o in r["operations"])
    with pytest.raises(ValueError, match="not in Sheet operations"):
        sheet_tools.run(f, "Mild steel CRCA / HR", {"operations": ["nope"]})


def test_formability_checks_and_deep_draw_goes_multi_stage():
    cup = cq.Workplane("XY").circle(60).extrude(30).faces(">Z").shell(-2).val()
    f = feats(cup, draw_depth_mm=28)
    f["blank_dia"] = 300                                                  # 300 mm blank on a ~135 mm punch = ratio 2.2
    r = sheet_tools.run(f, "Mild steel CRCA / HR", {})
    assert r["values"]["draw_ratio"] > 2 and r["recommended"] == "multi_stage"
    assert any(p["check"] == "draw_ratio" for p in r["problems"])
    small = cq.Workplane("XY").box(40, 40, 2).faces(">Z").workplane().hole(1).val()
    assert any(p["check"] == "hole_diameter" for p in sheet_tools.run(feats(small), "Mild steel CRCA / HR", {})["problems"])
    f = feats(plate(), bend_radius_mm=0.5)
    f["bends"], f["bend_len"] = 1, 60
    assert any(p["check"] == "bend_radius" for p in sheet_tools.run(f, "Mild steel CRCA / HR", {})["problems"])


def test_rules_are_data():
    db = mould_db.tables()
    next(r for r in db["sheet_operations"] if r["code"] == "blank")["force_t"] = "100"
    mould_db.write(db)
    assert sheet_tools.run(feats(plate()), "Mild steel CRCA / HR", {})["operations"][0]["force_t"] == 100
    db["sheet_checks"][0]["message"] = "{no_such_value}"
    with pytest.raises(mould_db.MouldDbError, match="Sheet checks row 2"):
        mould_db.write(db)


def test_part_endpoint_and_saved_choices():
    pid = add_part(project("SM9"), file="sheet_metal_bracket.step", material="Mild steel CRCA / HR", process="sheet_metal_progressive", code="BR-1")
    r = client.get(f"/api/parts/{pid}/sheet-tools")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["features"]["t"] == 2.0 and s["features"]["bends"] == 1 and "bend" in [o["code"] for o in s["operations"]]
    assert s["mode"] == "progressive" and s["process"] == "sheet_metal_progressive"      # the part's process sets the die type
    assert client.put(f"/api/parts/{pid}", json={"sheet_inputs": {"mode": "multi_stage", "operations": ["blank", "bend"]}}).status_code == 200
    s = client.get(f"/api/parts/{pid}/sheet-tools").json()
    assert s["mode"] == "multi_stage" and [o["code"] for o in s["operations"]] == ["blank", "bend"]
    assert client.put(f"/api/parts/{pid}", json={"sheet_inputs": {"operations": ["zzz"]}}).status_code == 400
