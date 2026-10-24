import io

import cadquery as cq
import ezdxf
import pytest
from fastapi.testclient import TestClient

from backend.app import mould_db, sheet_layout
from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def flat_plate():
    return cq.Workplane("XY").box(80, 60, 2).faces(">Z").workplane().rarray(30, 20, 2, 2).hole(6).val()


GEOM = {"bbox_mm": {"length": 80, "width": 60, "height": 2}, "bend_count": 0}
BLANK = {"length": 80, "width": 60}


def test_flat_pattern_is_the_real_outline_with_holes():
    fp = sheet_layout.flat_pattern(flat_plate(), GEOM, BLANK, 2.0)
    assert fp["length_mm"] == pytest.approx(80, abs=0.01) and fp["width_mm"] == pytest.approx(60, abs=0.01)
    assert len(fp["holes"]) == 4 and "real outline" in fp["method"]
    assert fp["area_mm2"] == pytest.approx(80 * 60 - 4 * 3.14159 * 9, rel=0.01)


def test_bent_part_gets_the_developed_rectangle():
    fp = sheet_layout.flat_pattern(flat_plate(), {"bbox_mm": {"length": 80, "width": 60, "height": 30}, "bend_count": 1}, BLANK, 2.0)
    assert fp["holes"] == [] and "developed rectangle" in fp["method"] and fp["area_mm2"] == 80 * 60


def test_strip_layout_by_hand_and_best_direction():
    fp = {"length_mm": 80, "width_mm": 60, "area_mm2": 4800}
    sl = sheet_layout.strip_layout(fp, 2.0, 2)
    v = sl["best"]["values"]
    bridge, edge = max(1.5, 1.2 * 2), max(2, 1.5 * 2)                       # 2.4, 3
    assert v["bridge_mm"] == pytest.approx(bridge) and v["edge_mm"] == pytest.approx(edge)
    util = {}
    for feed, across in ((80, 60), (60, 80)):
        util[feed] = 100 * 4800 / ((feed + bridge) * (across + 2 * edge))
    assert v["utilisation_pct"] == pytest.approx(max(util.values()))
    assert v["stations"] == 3 and v["pilots"] == 2 and v["pilot_dia_mm"] == pytest.approx(4.0)
    assert sl["best"]["values"]["utilisation_pct"] >= sl["other"]["values"]["utilisation_pct"]
    wide = sheet_layout.strip_layout({"length_mm": 400, "width_mm": 350, "area_mm2": 1e5}, 2.0, 2)
    assert wide["problems"] and "strip width" in wide["problems"][0].lower()


def test_dxf_and_pdf_pack():
    fp = sheet_layout.flat_pattern(flat_plate(), GEOM, BLANK, 2.0)
    sl = sheet_layout.strip_layout(fp, 2.0, 2)
    doc = ezdxf.read(io.StringIO(sheet_layout.blank_dxf(fp, "P1").decode()))
    assert len(list(doc.modelspace().query('LWPOLYLINE[layer=="CUT"]'))) == 5   # outline + 4 holes (the title block is on its own layer)
    strip = ezdxf.read(io.StringIO(sheet_layout.strip_dxf(fp, sl, "P1").decode()))
    assert len(list(strip.modelspace().query("CIRCLE"))) == 4              # stations + 1 pilots


def test_strip_rules_are_data():
    db = mould_db.tables()
    next(r for r in db["strip_rules"] if r["name"] == "bridge_mm")["formula"] = "5"
    mould_db.write(db)
    assert sheet_layout.strip_layout({"length_mm": 80, "width_mm": 60, "area_mm2": 4800}, 2.0, 2)["best"]["values"]["bridge_mm"] == 5
    db["strip_rules"][0]["formula"] = "nope + 1"
    with pytest.raises(mould_db.MouldDbError, match="Strip rules"):
        mould_db.write(db)


def test_part_endpoints():
    pid = add_part(project("SL10"), file="sheet_metal_bracket.step", material="Mild steel CRCA / HR",
                   process="sheet_metal_progressive", code="BR-10")
    r = client.get(f"/api/parts/{pid}/sheet-layout")
    assert r.status_code == 200, r.text
    assert r.json()["strip"]["best"]["values"]["utilisation_pct"] > 0
    for kind, head in (("blank.dxf", b"0\nSECTION"), ("strip.dxf", b"0\nSECTION"), ("tool-pack.pdf", b"%PDF")):
        f = client.get(f"/api/parts/{pid}/sheet-layout/{kind}")
        assert f.status_code == 200 and f.content.lstrip().startswith(head.lstrip()), kind
    assert client.get(f"/api/parts/{pid}/sheet-layout/x.txt").status_code == 404
