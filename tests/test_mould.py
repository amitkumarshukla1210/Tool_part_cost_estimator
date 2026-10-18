import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import formula, mould_db
from backend.app.mould import MouldInput, estimate
from backend.app.main import app

client = TestClient(app)
COVER = dict(part_type="plastic", part_length_mm=120, part_width_mm=80, part_height_mm=30,
             projected_area_cm2=95.78, part_weight_g=48.66)


def line(result, element):
    return next(l for l in result["lines"] if l["element"] == element)


# ---------- formulas ----------

def test_formula_rules():
    env = formula.SAMPLE | {"cavities": 6, "hot_runner": 0, "projected_area_cm2": 20}
    assert formula.evaluate("max(4, ceil(cavities * projected_area_cm2 / 8))", env) == 15
    assert formula.evaluate("cavities if hot_runner else 0", env) == 0
    assert formula.evaluate("=4 if cavities < 8 and not hot_runner else 6", env) == 4


@pytest.mark.parametrize("bad", ["__import__('os')", "().__class__", "open('x')", "cavites * 2", "2 +", "9 ** 99", "1/0"])
def test_formula_rejects_unsafe_or_wrong(bad):
    with pytest.raises(formula.FormulaError):
        formula.check(bad)


# ---------- sizing ----------

def test_insert_and_base_follow_cavities_and_part_size():
    r = estimate(MouldInput(cavities=2, **COVER))
    lay = r["layout"]
    # insert = part + 2 × 25 mm wall; height per half = 30 / 2 + 30 mm backing
    assert (lay["each_l"], lay["each_w"], lay["half_h"]) == (170, 130, 45)
    assert (lay["rows"], lay["cols"]) == (2, 1)
    assert (lay["pocket_l"], lay["pocket_w"]) == (170, 2 * 130 + 10)
    # Smallest example base with a pocket ≥ 270 × 170 is 3040 (pocket 290 × 190), turned.
    assert r["base"]["size_code"] == "3040" and r["base_turned"]
    assert r["lines"][0]["total"] == r["base"]["cost"]

    four = estimate(MouldInput(cavities=4, **COVER))
    assert (four["layout"]["rows"], four["layout"]["cols"]) == (2, 2)  # not a long 1 × 4 strip
    one = estimate(MouldInput(cavities=1, **COVER))
    assert one["base"]["length_mm"] * one["base"]["width_mm"] < r["base"]["length_mm"] * r["base"]["width_mm"]


def test_no_base_large_enough():
    with pytest.raises(ValueError, match="Add a larger size"):
        estimate(MouldInput(cavities=8, **COVER))


def test_bom_quantities_follow_rules():
    cold = estimate(MouldInput(cavities=2, **COVER))
    hot = estimate(MouldInput(cavities=2, hot_runner=True, slides_per_cavity=1, **COVER))
    assert line(cold, "Sprue bush")["quantity"] == 1
    assert "Hot runner nozzle (drop)" not in [l["element"] for l in cold["lines"]]
    assert line(hot, "Hot runner nozzle (drop)")["quantity"] == 2
    assert "Sprue bush" not in [l["element"] for l in hot["lines"]]
    assert line(hot, "Slide block")["quantity"] == 2
    assert line(cold, "Ejector pin")["quantity"] == 24  # ceil(2 × 95.78 / 8)
    # Insert weight = 170 × 130 × 45 mm × 7.85 g/cm³
    ins = line(cold, "Cavity insert (steel)")
    assert ins["weight_each_kg"] == pytest.approx(170 * 130 * 45 * 7.85 / 1e6, abs=1e-3)
    assert ins["material_cost"] == pytest.approx(2 * ins["weight_each_kg"] * 420, rel=1e-3)
    assert hot["totals"]["total"] > cold["totals"]["total"]
    # Every seeded line is a placeholder.
    assert cold["example_lines"] == len(cold["lines"]) and cold["sizing_rules_are_examples"]


# ---------- editing the database ----------

def test_edits_change_the_result():
    data = client.get("/api/mould-db").json()
    for r in data["sizing_rules"]:
        if r["part_type"] == "plastic" and r["parameter"] == "insert_wall_mm":
            r["value"], r["is_example"] = 40, False
    big = dict(data["mould_bases"][-9], size_code="7080", length_mm=800, width_mm=700,
               max_insert_length_mm=640, max_insert_width_mm=540)
    data["mould_bases"].append(big)
    assert client.put("/api/mould-db", json=data).status_code == 200

    r = estimate(MouldInput(cavities=8, **COVER))  # now fits in the new base
    assert r["layout"]["each_l"] == 200
    assert r["base"]["size_code"] == "7080"


@pytest.mark.parametrize("change, message", [
    (lambda d: d["bom_elements"][0].update(quantity_rule="cavites"), "BOM elements row 2, quantity_rule: unknown name"),
    (lambda d: d["bom_elements"][0].update(material_code="Unobtainium"), "not in Tool materials"),
    (lambda d: d["bom_elements"][0].update(category="misc"), "category"),
    (lambda d: d["tool_materials"][0].update(rate_per_kg="abc"), "Tool materials row 2"),
    (lambda d: d["mould_bases"].append(dict(d["mould_bases"][0])), "listed twice"),
    (lambda d: d["mould_bases"][0].update(max_insert_length_mm=9999), "insert pocket is larger"),
])
def test_bad_edits_are_rejected(change, message):
    before = client.get("/api/mould-db").json()
    data = client.get("/api/mould-db").json()
    change(data)
    r = client.put("/api/mould-db", json=data)
    assert r.status_code == 400 and message in r.json()["detail"]
    assert client.get("/api/mould-db").json() == before  # nothing half-saved


def test_excel_round_trip():
    xlsx = client.get("/api/mould-db/download")
    wb = load_workbook(io.BytesIO(xlsx.content))
    assert set(wb.sheetnames) >= {"Mould bases", "Tool materials", "BOM elements", "Process rates", "Sizing rules", "Formula help"}
    ws = wb["Process rates"]
    for row in ws.iter_rows(min_row=2):
        if row[0].value == "CNC milling":
            row[2].value = 1500
            row[3].value = "no"
    buf = io.BytesIO()
    wb.save(buf)
    assert client.post("/api/mould-db/upload", files={"file": ("mould_db.xlsx", buf.getvalue())}).status_code == 200
    cnc = next(p for p in mould_db.tables()["process_rates"] if p["code"] == "CNC milling")
    assert cnc == {**cnc, "rate_per_hour": 1500, "is_example": False}

    bad = client.post("/api/mould-db/upload", files={"file": ("x.xlsx", b"nope")})
    assert bad.status_code == 400 and "Excel" in bad.json()["detail"]


def test_api_estimate():
    r = client.post("/api/mould/estimate", json={**COVER, "cavities": 2})
    assert r.status_code == 200 and r.json()["base"]["size_code"] == "3040"
    assert client.post("/api/mould/estimate", json={**COVER, "cavities": 8}).status_code == 400
