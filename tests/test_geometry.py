import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.geometry import analyze, load_step
from backend.app.main import app

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
client = TestClient(app)


def test_plate_with_hole():
    m = analyze(load_step(str(SAMPLES / "plate_with_hole.step")), "die_casting", 2.70)
    volume = 100 * 60 * 20 - math.pi * 10**2 * 20
    assert m.volume_mm3 == pytest.approx(volume, rel=1e-6)
    assert m.net_weight_g == pytest.approx(volume / 1000 * 2.70, abs=1e-3)
    assert m.bbox_mm == pytest.approx({"length": 100, "width": 60, "height": 20}, abs=1e-3)
    # Hole goes through along Z, so it is cut out of the Z shadow.
    assert m.projected_area_mm2["z"] == pytest.approx(6000 - math.pi * 100, rel=1e-3)
    assert m.projected_area_mm2["x"] == pytest.approx(60 * 20, rel=1e-6)
    assert m.projected_area_mm2["y"] == pytest.approx(100 * 20, rel=1e-6)
    assert m.pull_direction == "z"
    assert m.projected_area_cm2 == pytest.approx(m.projected_area_mm2["z"] / 100, rel=1e-6)


def test_sheet_metal_bracket():
    m = analyze(load_step(str(SAMPLES / "sheet_metal_bracket.step")), "sheet_metal", 7.85)
    assert m.volume_mm3 == pytest.approx((80 * 2 + 38 * 2) * 50, rel=1e-6)
    assert m.bbox_mm == pytest.approx({"length": 80, "width": 50, "height": 40}, abs=1e-3)
    assert m.projected_area_mm2["z"] == pytest.approx(80 * 50, rel=1e-6)


def test_invalid_inputs():
    shape = load_step(str(SAMPLES / "plate_with_hole.step"))
    with pytest.raises(ValueError):
        analyze(shape, "forging", 7.85)
    with pytest.raises(ValueError):
        analyze(shape, "plastic", 0)


def test_api_analyze():
    with open(SAMPLES / "plastic_cover.step", "rb") as fh:
        r = client.post(
            "/api/analyze",
            files={"file": ("plastic_cover.step", fh, "application/octet-stream")},
            data={"part_type": "plastic", "density": "1.04"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["metrics"]["net_weight_g"] > 0
    assert len(body["mesh"]["positions"]) % 3 == 0
    assert len(body["mesh"]["indices"]) % 3 == 0


def test_api_rejects_wrong_extension():
    r = client.post(
        "/api/analyze",
        files={"file": ("part.stl", b"solid x", "application/octet-stream")},
        data={"part_type": "plastic", "density": "1.04"},
    )
    assert r.status_code == 400


def test_api_rejects_garbage_step():
    r = client.post(
        "/api/analyze",
        files={"file": ("bad.step", b"not a step file", "application/octet-stream")},
        data={"part_type": "plastic", "density": "1.04"},
    )
    assert r.status_code == 422
