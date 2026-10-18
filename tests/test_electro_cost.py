import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import rate_engine, rates, register_setup
from backend.app.main import app
from tests.test_bom_extract import CPL, KBL, KICAD

client = TestClient(app)


def calc(trace, name):
    return trace["nodes"][f"calc:{name}"]["value"]


def upload(file, **kw):
    r = client.post("/api/bom-extracts", files=file, data=kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_harness_cost_by_hand():
    e = upload({"file": ("h.xml", KBL)})
    c = client.get(f"/api/bom-extracts/{e['id']}/cost").json()
    assert c["kind"] == "harness" and c["country"] == "IN"
    # wires: 770 mm of 0.5 mm² (no library row for FLRY-B-0.5): copper g/m × (copper rate + conversion) per kg
    kg_m = 0.5 * 8.96 / 1000
    cu = rates.lookup("material", "Copper", "IN", c["as_of"])["value"]
    cv = rates.lookup("harness", "wire_conversion_per_kg_copper", "IN", c["as_of"])["value"]
    wire = 0.77 * kg_m * (cu + cv)
    parts = 2 * 12.0 + 4 * 1.1                                                  # 2 housings + 4 terminals from the Part library
    assert c["nodes"]["in:wire_cost"]["value"] == pytest.approx(wire)
    assert c["nodes"]["in:parts_cost"]["value"] == pytest.approx(parts)
    assert any("Corrugated tube" in m or "sleeve" in m for m in c["missing"]) and not c["priced"]     # the sleeve has no library row
    # processing: cut and strip = 2 wires × 6 s on WIRE-CS with one operator, at the country's MHR and labour rate
    mhr = rate_engine.mhr("WIRE-CS", "IN", c["as_of"])["value"]
    lab = rate_engine.labour_rate("operator", "IN", c["as_of"])["value"]
    assert c["nodes"]["proc:cut_strip"]["value"] == pytest.approx(2 * 6 / 3600 * (mhr + 1 * lab))
    assert c["nodes"]["proc:crimp"]["value"] == pytest.approx(4 * 5 / 3600 * (rate_engine.mhr("CRIMP-P", "IN", c["as_of"])["value"] + lab))
    proc = sum(v["value"] for k, v in c["nodes"].items() if k.startswith("proc:"))
    assert c["nodes"]["process_total"]["value"] == pytest.approx(proc) and proc > 0
    rej = (wire + parts + proc) * 2 / 98
    over = proc * 0.05
    before = wire + parts + proc + rej + over
    assert c["value"] == pytest.approx(before * 1.10 * 1.015)
    assert any(k.startswith("p0:mhr:") and "electricity" in k for k in c["nodes"])        # MHR grafted down to the electricity rate


def test_library_price_wins_and_sleeve_priced():
    r = register_setup.tables()
    r["part_library"].append({"part_number": "FLRY-B-0.5", "maker": "", "description": "wire", "unit": "m", "unit_price": 20.0, "currency": "INR",
                              "source": "t", "month": "2026-10", "is_example": False})
    r["part_library"].append({"part_number": "Corrugated tube", "maker": "", "description": "t", "unit": "pcs", "unit_price": 3.0, "currency": "INR",
                              "source": "t", "month": "2026-10", "is_example": False})
    register_setup.write(r)
    e = upload({"file": ("h.xml", KBL)})
    c = client.get(f"/api/bom-extracts/{e['id']}/cost").json()
    assert c["nodes"]["in:wire_cost"]["value"] == pytest.approx(0.77 * 20.0)
    assert [m for m in c["missing"] if "sleeve" in m]                           # matched by part number only: the tube has none


def test_pcb_cost_by_hand_and_other_country():
    e = upload({"file": ("bom.csv", KICAD), "cpl": ("cpl.csv", CPL)}, layers="4", width_mm="60", height_mm="40", thickness_mm="1.6")
    c = client.get(f"/api/bom-extracts/{e['id']}/cost").json()
    assert c["kind"] == "pcb" and c["drivers"]["smt_placements"] == 6 and c["drivers"]["tht_placements"] == 1 and c["drivers"]["board_cm2"] == pytest.approx(24)
    rate = rates.lookup("pcb_board", "4L", "IN", c["as_of"])["value"]
    assert c["nodes"]["in:board_cost"]["value"] == pytest.approx(24 * rate * 1.15)                         # 15 % panel waste
    comp = 3 * 0.55 + 2 * 180.0 + 6.0                                          # C1-C3, U1 x2, J1; R1 is not in the library
    assert c["nodes"]["in:components_cost"]["value"] == pytest.approx(comp)
    assert any("R1" in m or "10k" in m or "not in the Part library" in m for m in c["missing"])
    de = client.get(f"/api/bom-extracts/{e['id']}/cost", params={"country": "DE"}).json()
    assert de["currency"] == "EUR" and de["value_inr"] > 0 and de["nodes"]["in:board_cost"]["unit"] in ("EUR", "")


def test_exports_and_errors():
    e = upload({"file": ("h.xml", KBL)})
    wb = load_workbook(io.BytesIO(client.get(f"/api/bom-extracts/{e['id']}/cost.xlsx").content))
    assert wb.sheetnames == ["Summary", "Steps", "Lines", "Processes", "Inputs", "Not priced", "Rates used"]
    assert client.get(f"/api/bom-extracts/{e['id']}/cost.pdf").content[:4] == b"%PDF"
    assert client.get(f"/api/bom-extracts/{e['id']}/cost", params={"country": "ZZ"}).status_code == 400
    assert client.get("/api/bom-extracts/999999/cost").status_code == 400
    good = client.get("/api/register-setup").json()
    bad = client.get("/api/register-setup").json()
    bad["electro_processes"][0]["driver"] = "nope"
    client.put("/api/register-setup", json=bad)
    assert client.get(f"/api/bom-extracts/{e['id']}/cost").status_code == 400
    client.put("/api/register-setup", json=good)
