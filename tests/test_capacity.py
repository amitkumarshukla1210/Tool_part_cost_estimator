from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.capacity import CapacityInput, calculate, choose_cavities
from backend.app.main import app

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
client = TestClient(app)


def test_plastic_two_cavity_and_tool_life():
    r = calculate(CapacityInput(part_type="plastic", footprint_length_mm=120, footprint_width_mm=80,
                                annual_volume=1_000_000))
    # 300 days × 2 shifts × 8 h × 75 % OEE = 3600 h
    assert r["available_hours_per_year"] == pytest.approx(3600)
    assert r["cavities_needed"] == pytest.approx(1_000_000 / 3600 * 25 / 3600, abs=1e-3)
    # 500 × 400 plate, 30 mm spacing: 3 × 3 cavities of 120 × 80 fit.
    assert r["cavities_fit_on_plate"] == 9
    assert r["cavities_per_tool"] == 2
    assert r["limited_by"] is None
    assert r["tools_for_capacity"] == 1
    assert r["shots_per_year"] == 500_000
    # 2.5 M shots over 5 years on a 1 M shot mould → 3 moulds.
    assert r["tools_for_life"] == 3
    assert r["tool_sets_over_programme"] == 3
    assert r["machine_utilisation_pct"] == pytest.approx(100 * 500_000 * 25 / 3600 / 0.75 / 4800, abs=0.1)


def test_die_casting_capped_by_max_cavities():
    r = calculate(CapacityInput(part_type="die_casting", footprint_length_mm=100, footprint_width_mm=60,
                                annual_volume=1_500_000))
    assert r["cavities_needed"] == pytest.approx(5.58, abs=0.01)
    assert r["cavities_per_tool"] == 4
    assert r["limited_by"] == "maximum cavities"
    assert r["tools_for_capacity"] == 2


def test_foundry_capped_by_plate():
    r = calculate(CapacityInput(part_type="foundry", footprint_length_mm=300, footprint_width_mm=250,
                                annual_volume=500_000))
    assert r["cavities_fit_on_plate"] == 1
    assert r["cavities_per_tool"] == 1
    assert r["limited_by"] == "plate size"
    assert r["tools_for_capacity"] == 3


def test_sheet_metal_dies_per_operation():
    r = calculate(CapacityInput(part_type="sheet_metal", footprint_length_mm=118, footprint_width_mm=50,
                                annual_volume=200_000))
    assert r["cavities_per_tool"] == 1
    assert r["dies_per_set"] == 3
    assert r["total_dies"] == r["tool_sets_over_programme"] * 3


def test_standard_cavity_rounding():
    assert choose_cavities("plastic", 2.1, 32) == 4
    assert choose_cavities("plastic", 9, 32) == 12
    assert choose_cavities("plastic", 9, 10) == 8  # limit wins
    assert choose_cavities("foundry", 2.1, 8) == 3  # any whole number


def test_part_too_big_for_plate():
    with pytest.raises(ValueError):
        calculate(CapacityInput(part_type="plastic", footprint_length_mm=700, footprint_width_mm=700))


def test_api_capacity_and_hints():
    r = client.post("/api/capacity", json={"part_type": "die_casting", "footprint_length_mm": 100,
                                           "footprint_width_mm": 60, "annual_volume": 1_500_000})
    assert r.status_code == 200 and r.json()["cavities_per_tool"] == 4
    assert client.post("/api/capacity", json={"part_type": "plastic", "footprint_length_mm": 700,
                                              "footprint_width_mm": 700}).status_code == 400
    assert client.post("/api/capacity", json={"part_type": "plastic", "footprint_length_mm": 100,
                                              "footprint_width_mm": 60, "oee_pct": 0}).status_code == 422

    with open(SAMPLES / "plastic_cover.step", "rb") as fh:
        a = client.post("/api/analyze", files={"file": ("cover.step", fh, "application/octet-stream")},
                        data={"part_type": "plastic", "density": "1.04"})
    process = a.json()["process"]
    assert process["wall_thickness_mm"] == pytest.approx(2.5)
    assert process["footprint_mm"] == {"length": 120.0, "width": 80.0}
    assert process["cycle_time_s_estimate"] == pytest.approx(20.5)


@pytest.mark.parametrize("oee", [50, 75, 100])
def test_oee_applied_once(oee):
    """Regression guard: OEE must reduce capacity once, not twice."""
    r = calculate(CapacityInput(part_type="plastic", footprint_length_mm=120, footprint_width_mm=80,
                                annual_volume=1_000_000, cycle_time_s=25, oee_pct=oee))
    planned = 300 * 2 * 8
    assert r["planned_hours_per_year"] == planned
    assert r["available_hours_per_year"] == pytest.approx(planned * oee / 100)
    assert r["cavities_needed"] == pytest.approx(1_000_000 * 25 / 3600 / (planned * oee / 100), abs=1e-3)
    # Utilisation × machines × cavities gives back the cavities needed only if
    # OEE is counted once on each side.
    util = r["machine_utilisation_pct"] / 100
    assert util * r["tools_for_capacity"] * r["cavities_per_tool"] == pytest.approx(r["cavities_needed"], rel=2e-3)
    # Halving OEE doubles the cavities needed (a double count would quadruple it).
    half = calculate(CapacityInput(part_type="plastic", footprint_length_mm=120, footprint_width_mm=80,
                                   annual_volume=1_000_000, cycle_time_s=25, oee_pct=oee / 2))
    assert half["cavities_needed"] == pytest.approx(2 * r["cavities_needed"], rel=1e-3)
