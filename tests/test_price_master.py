"""Stage 20: price master (month-wise prices by country) and recommended / chosen grades and makes."""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import master_data, mould_db, price_master, rates, tool_cost
from backend.app.main import app

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
MONTH = "2026-10"
client = TestClient(app)
COVER = dict(part_type="plastic", part_length_mm=120, part_width_mm=80, part_height_mm=30, projected_area_cm2=95.78,
             part_weight_g=48.66, part_volume_cm3=46.3, part_surface_cm2=420, material="ABS", as_of=MONTH, cavities=2)


def run(**kw):
    return tool_cost.run(tool_cost.ToolInput(**(COVER | kw)))


def line(r, element):
    return next(l for l in r["lines"] if l["element"] == element)


def approver():
    client.put("/api/settings", json={"approver_name": "Tester"})


# ---------- master data ----------

def test_master_lists_have_types_grades_makes_and_beryllium_copper():
    db = mould_db.tables()
    steels = {r["code"]: r for r in db["tool_materials"]}
    assert steels["Beryllium copper C17200"]["material_type"] == "Copper alloy"
    assert {"P20 (1.2311)", "D2 (1.2379)", "2738 (1.2738)", "Beryllium copper C17510"} <= set(steels)
    assert all(r["material_type"] for r in db["tool_materials"])
    pillars = {r["make"]: r for r in db["standard_parts"] if r["element"] == "Guide pillar"}
    assert {"HASCO", "MISUMI", "DME"} <= set(pillars) and pillars["HASCO"]["recommended"]
    mats = master_data.tables()["Materials"]
    assert all(r["material_type"] for r in mats)
    pp = [r for r in mats if r["material_type"] == "Polypropylene (PP)"]
    assert len(pp) >= 3 and sum(1 for r in pp if r["recommended"]) == 1


def test_two_years_of_month_wise_prices_for_every_country():
    months = price_master.months(MONTH)
    assert len(months) == 24 and months[0] == "2024-11"
    for group, item in (("tool_material", "Beryllium copper C17200"), ("standard_part", "Guide pillar · MISUMI"),
                        ("part_material", "ABS"), ("part_scrap", "ABS")):
        for country in ("IN", "DE", "CN", "US"):
            g = price_master.grid(group, country, MONTH)
            row = next(r for r in g["rows"] if r["item"] == item)
            assert all(row["cells"][m]["value"] is not None for m in months), (group, item, country)
            assert row["cells"]["2024-11"]["is_example"]
    assert g["months"][-1] == "2026-11"  # one month ahead, to enter next month's prices


def test_master_checks_reject_bad_rows():
    db = mould_db.tables()
    db["standard_parts"].append(dict(db["standard_parts"][0], make="NoSuchMake"))
    with pytest.raises(mould_db.MouldDbError, match="not in Makes"):
        mould_db.write(db)
    db = mould_db.tables()
    db["standard_parts"][1]["recommended"] = True
    with pytest.raises(mould_db.MouldDbError, match="already has a recommended make"):
        mould_db.write(db)
    db = mould_db.tables()
    db["grade_rules"][0] = dict(db["grade_rules"][0], material_code="Unobtainium")
    with pytest.raises(mould_db.MouldDbError, match="not in Tool materials"):
        mould_db.write(db)
    md = master_data.tables()
    rows = [dict(r) for r in md["Materials"]]
    rows.append(dict(next(r for r in rows if r["material"] == "ABS"), material="ABS 2"))
    with pytest.raises(master_data.MasterDataError, match="already has a recommended grade"):
        master_data.write({"Parameters": md["Parameters"], "Materials": rows})


# ---------- recommended and chosen grades / makes (your examples) ----------

def test_recommendation_from_grade_rules_else_the_bom_element():
    r = run()  # volume unknown: the BOM element's own material
    assert line(r, "Cavity insert (steel)")["recommended_material"] == "2738 (1.2738)"
    small = run(part_length_mm=100, part_width_mm=60, annual_volume=50_000)
    ins = line(small, "Cavity insert (steel)")
    assert ins["material"] == ins["recommended_material"] == "P20 (1.2311)" and "P20" in ins["material_reason"]
    assert line(run(annual_volume=800_000), "Core insert (steel)")["recommended_material"] == "H13 (1.2344)"
    assert line(r, "Guide pillar")["make"] == line(r, "Guide pillar")["recommended_make"] == "HASCO"
    assert r["selections"] == {} and "Beryllium copper C17200" in [m["code"] for m in r["choices"]["materials"]]
    assert [m["make"] for m in r["choices"]["makes"]["Guide pillar"]][:2] == ["HASCO", "MISUMI"]


@pytest.mark.parametrize("start, to", [("P20 (1.2311)", "D2 (1.2379)"), ("D2 (1.2379)", "2738 (1.2738)"),
                                       ("2738 (1.2738)", "Beryllium copper C17200")])
def test_mould_insert_grade_can_be_changed_from_the_master_list(start, to):
    base = run(selections={"Cavity insert (steel)": {"material": start}})
    r = run(selections={"Cavity insert (steel)": {"material": to}})
    ins = line(r, "Cavity insert (steel)")
    assert ins["material"] == to and ins["recommended_material"] == "2738 (1.2738)"
    assert ins["material_chosen"] == (to != "2738 (1.2738)")
    steel = rates.lookup("tool_material", to, "IN", MONTH)["value"]
    density = next(m for m in mould_db.tables()["tool_materials"] if m["code"] == to)["density_g_cm3"]
    assert ins["weight_each_kg"] == pytest.approx(170 * 130 * 45 * density / 1e6, abs=1e-6)
    assert ins["material_cost"] == pytest.approx(ins["quantity"] * ins["weight_each_kg"] * steel, rel=1e-9)
    assert ("your choice" in r["nodes"][ins["nodes"]["mat"]]["description"]) == ins["material_chosen"]
    assert r["selections"] == ({} if to == "2738 (1.2738)" else {"Cavity insert (steel)": {"material": to}})
    assert line(r, "Core insert (steel)")["material"] == "2738 (1.2738)"  # the other insert keeps its recommendation
    assert r["value"] != base["value"]


def test_guide_pillar_make_can_be_changed_from_hasco_to_misumi():
    hasco = run()
    r = run(selections={"Guide pillar": {"make": "MISUMI"}})
    gp = line(r, "Guide pillar")
    assert gp["make"] == "MISUMI" and gp["make_chosen"] and gp["recommended_make"] == "HASCO" and gp["catalogue_ref"] == "GPH"
    price = rates.lookup("standard_part", "Guide pillar · MISUMI", "IN", MONTH)["value"]
    size = r["nodes"][f"{gp['nodes']['total']}:size"]["value"]
    assert gp["bought_out_cost"] == pytest.approx(gp["quantity"] * price * size, rel=1e-9)
    assert gp["bought_out_cost"] < line(hasco, "Guide pillar")["bought_out_cost"]
    assert line(hasco, "Guide pillar")["bought_out_cost"] == pytest.approx(gp["quantity"] * (600 + 3 * r["base"]["width_mm"]))


def test_make_price_follows_the_month_and_country():
    old = line(run(as_of="2025-01"), "Guide pillar")["bought_out_cost"]
    assert old < line(run(), "Guide pillar")["bought_out_cost"]
    de = run(country="DE")
    assert de["currency"] == "EUR" and line(de, "Guide pillar")["bought_out_cost"] > 0 and de["priced"]


def test_unknown_choice_falls_back_to_the_recommendation_with_a_warning():
    r = run(selections={"Cavity insert (steel)": {"material": "Unobtainium"}, "Guide pillar": {"make": "Nobody"}})
    assert line(r, "Cavity insert (steel)")["material"] == "2738 (1.2738)" and line(r, "Guide pillar")["make"] == "HASCO"
    assert sum("no longer in" in w for w in r["warnings"]) == 2


def test_choices_are_stored_on_the_part_and_shown_in_the_exports():
    p = client.post("/api/projects", json={"code": "G", "name": "Grades"}).json()
    with open(SAMPLES / "plastic_cover.step", "rb") as fh:
        m = client.post("/api/import/step", files={"file": ("plastic_cover.step", fh)}).json()
    pid = client.post(f"/api/import/{m['token']}/commit", json={"project_id": p["id"], "items": {
        m["root"]: {"material": "ABS", "process": "injection_moulding", "part_code": "G-1"}}}).json()["part_ids"][0]
    first = client.get(f"/api/parts/{pid}").json()["tool"]["latest"]
    picks = {"Cavity insert (steel)": {"material": "Beryllium copper C17200"}, "Guide pillar": {"make": "MISUMI"}}
    res = client.post(f"/api/parts/{pid}/tool-cost", json={"tool_inputs": {"selections": picks}}).json()
    assert res["stored"] and res["part"]["tool_inputs"]["selections"] == picks
    tr = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    assert line(tr, "Cavity insert (steel)")["material"] == "Beryllium copper C17200"
    assert tr["value_inr"] > first["tool_cost_inr"]
    ws = load_workbook(io.BytesIO(client.get(f"/api/parts/{pid}/tool-cost/export.xlsx").content))["BOM & processes"]
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    head = next(r for r in rows if "Choice" in r)
    gp = next(r for r in rows if r[0] == "Guide pillar")
    assert gp[head.index("Make")] == "MISUMI" and gp[head.index("Choice")] == "yours"
    assert client.get(f"/api/parts/{pid}/tool-cost/export.pdf").status_code == 200
    bad = client.post(f"/api/parts/{pid}/tool-cost", json={"tool_inputs": {"selections": {"Guide pillar": {"colour": "x"}}}})
    assert bad.status_code == 400
    rec = client.get(f"/api/parts/{pid}").json()["material_recommendation"]
    assert rec["material"] == "ABS" and rec["is_recommended"] and "ABS flame retardant V0" in rec["grades"]


# ---------- price master page API ----------

def test_typed_price_is_a_new_version_for_that_month_only_from_then_on():
    approver()
    r = client.post("/api/price-master/price", json={"group": "tool_material", "item": "Beryllium copper C17200",
                                                     "country": "IN", "month": "2026-11", "value": 5100})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    row = next(x for x in client.get("/api/price-master/grid", params={"group": "tool_material", "country": "IN"}).json()["rows"]
               if x["item"] == "Beryllium copper C17200")
    assert row["cells"]["2026-11"]["value"] == 5100 and row["cells"]["2026-11"]["starts"]
    assert row["cells"]["2026-10"]["value"] == 4800
    sel = {"Cavity insert (steel)": {"material": "Beryllium copper C17200"}}
    assert run(selections=sel, as_of="2026-11")["value"] > run(selections=sel)["value"]
    draft = client.post("/api/price-master/price", json={"group": "part_material", "item": "ABS", "country": "IN",
                                                         "month": "2026-11", "value": 999, "approve": False}).json()
    assert draft["status"] == "draft"
    assert rates.lookup("material", "ABS", "IN", "2026-11")["value"] != 999
    bad = client.post("/api/price-master/price", json={"group": "tool_material", "item": "Nope", "country": "IN",
                                                       "month": "2026-11", "value": 1})
    assert bad.status_code == 400 and "master list" in bad.json()["detail"]


def test_new_grade_and_new_make_reach_the_tool_cost_drop_downs():
    r = client.post("/api/price-master/item", json={"group": "tool_material", "code": "1.2738 HH", "material_type":
                                                    "Pre-hardened mould steel", "density": 7.85, "price": 480})
    assert r.status_code == 400 and "approvals" in r.json()["detail"]  # nothing saved without an approver
    assert "1.2738 HH" not in {m["code"] for m in mould_db.tables()["tool_materials"]}
    approver()
    assert client.post("/api/price-master/item", json={"group": "tool_material", "code": "1.2738 HH", "material_type":
                                                       "Pre-hardened mould steel", "density": 7.85, "price": 480}).status_code == 200
    assert client.post("/api/price-master/item", json={"group": "standard_part", "element": "Guide pillar", "make": "Strack",
                                                       "origin_country": "DE", "price": 1600}).status_code == 200
    r = run(selections={"Cavity insert (steel)": {"material": "1.2738 HH"}, "Guide pillar": {"make": "Strack"}})
    assert line(r, "Cavity insert (steel)")["material"] == "1.2738 HH" and line(r, "Guide pillar")["make"] == "Strack"
    assert r["priced"] and "Strack" in [m["make"] for m in r["choices"]["makes"]["Guide pillar"]]
    assert client.post("/api/price-master/item", json={"group": "part_material", "part_type": "plastic", "material": "PP GF30",
                                                       "material_type": "Polypropylene (PP)", "density": 1.12, "price": 160,
                                                       "scrap_price": 30}).status_code == 200
    assert rates.lookup("material_scrap", "PP GF30", "IN")["value"] == 30
    dup = client.post("/api/price-master/item", json={"group": "standard_part", "element": "Guide pillar", "make": "Strack", "price": 1})
    assert dup.status_code == 400 and "already" in dup.json()["detail"]


def test_excel_round_trip_only_saves_changed_cells():
    approver()
    x = client.get("/api/price-master/export.xlsx", params={"group": "standard_part", "country": "DE"})
    up = lambda content: client.post("/api/price-master/upload", data={"group": "standard_part", "country": "DE", "approve": "true"},
                                     files={"file": ("p.xlsx", content)}).json()
    assert up(x.content) == {"versions_created": 0, "status": "approved"}
    wb = load_workbook(io.BytesIO(x.content))
    ws = wb.active
    head = [c.value for c in ws[1]]
    ws.cell(row=2, column=head.index("2026-11") + 1).value = 99
    buf = io.BytesIO()
    wb.save(buf)
    assert up(buf.getvalue())["versions_created"] == 1
    assert rates.lookup("standard_part", ws.cell(row=2, column=1).value, "DE", "2026-11")["value"] == 99


def test_history_seed_never_overwrites_a_month():
    approver()
    rates.create({"category": "tool_material", "item": "NAK80", "country": "IN", "value": 1, "unit": "INR/kg", "currency": "INR",
                  "month": "2026-12"}, approve=True)
    assert price_master.seed_history("2026-10")["created"] == 0
    assert price_master.trend_factor("steel", 0) == 1
