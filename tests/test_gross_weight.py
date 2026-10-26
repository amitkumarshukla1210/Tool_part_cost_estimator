from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.gross_weight import GrossWeightInput, calculate
from backend.app.main import app

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
client = TestClient(app)


def test_plastic_runner_and_cost():
    r = calculate(GrossWeightInput(
        part_type="plastic", net_weight_g=100, density_g_cm3=1.04,
        runner_pct=15, process_loss_pct=2, material_rate_per_kg=150, scrap_rate_per_kg=20,
    ))
    assert r["gross_weight_g"] == pytest.approx(115)
    assert r["returns_scrap_g"] == pytest.approx(15)
    assert r["material_input_g"] == pytest.approx(117.3)
    assert r["rm_cost"] == pytest.approx(117.3 / 1000 * 150)
    assert r["scrap_credit"] == pytest.approx(15 / 1000 * 20)
    assert r["net_rm_cost"] == pytest.approx(17.595 - 0.3)
    assert r["material_yield_pct"] == pytest.approx(100 / 117.3 * 100, abs=0.01)


def test_die_casting_yield_defaults():
    r = calculate(GrossWeightInput(part_type="die_casting", net_weight_g=300, density_g_cm3=2.74))
    # Defaults: 60 % casting yield, 3 % melt loss.
    assert r["gross_weight_g"] == pytest.approx(500)
    assert r["returns_scrap_g"] == pytest.approx(200)
    assert r["material_input_g"] == pytest.approx(515)
    assert r["rm_cost"] == 0


def test_sheet_metal_nesting():
    net_g = 11800 / 1000 * 7.85  # sample bracket
    r = calculate(GrossWeightInput(
        part_type="sheet_metal", net_weight_g=net_g, density_g_cm3=7.85,
        thickness_mm=2, blank_length_mm=118, blank_width_mm=50,
    ))
    # Usable sheet 2490 × 1240 with 5 mm gaps: 118 mm across the sheet width
    # gives 45 × 10 = 450 blanks, better than 20 × 22 = 440 the other way.
    assert r["nesting"] == {"along": 45, "across": 10, "per_sheet": 450, "rotated": True}
    sheet_g = 2500 * 1250 * 2 / 1000 * 7.85
    # gross weight = the calculated blank plus the 5 mm gap (pitch × width), not a share of the standard sheet
    assert r["gross_weight_g"] == pytest.approx((118 + 5) * (50 + 5) * 2 / 1000 * 7.85, abs=1e-3)
    assert r["sheet_utilisation_pct"] == pytest.approx(100 * net_g * 450 / sheet_g, abs=0.01)


def test_sheet_metal_blank_too_big():
    with pytest.raises(ValueError):
        calculate(GrossWeightInput(
            part_type="sheet_metal", net_weight_g=10, density_g_cm3=7.85,
            thickness_mm=2, blank_length_mm=5000, blank_width_mm=2500,
        ))


def test_api_gross_weight_and_validation():
    ok = client.post("/api/gross-weight", json={"part_type": "foundry", "net_weight_g": 650, "density_g_cm3": 7.2})
    assert ok.status_code == 200
    assert ok.json()["gross_weight_g"] == pytest.approx(1000)
    assert client.post("/api/gross-weight", json={
        "part_type": "foundry", "net_weight_g": 650, "density_g_cm3": 7.2, "yield_pct": 0}).status_code == 422
    assert client.post("/api/gross-weight", json={
        "part_type": "sheet_metal", "net_weight_g": 650, "density_g_cm3": 7.85}).status_code == 422
    assert client.post("/api/gross-weight", json={
        "part_type": "sheet_metal", "net_weight_g": 10, "density_g_cm3": 7.85, "thickness_mm": 2,
        "blank_length_mm": 5000, "blank_width_mm": 2500}).status_code == 400


def test_api_analyze_returns_sheet_hints():
    with open(SAMPLES / "sheet_metal_bracket.step", "rb") as fh:
        r = client.post(
            "/api/analyze",
            files={"file": ("bracket.step", fh, "application/octet-stream")},
            data={"part_type": "sheet_metal", "density": "7.85"},
        )
    sheet = r.json()["sheet_metal"]
    assert sheet["thickness_mm"] == pytest.approx(2.0)
    assert sheet["blank_mm"] == {"length": 118.0, "width": 50.0}
