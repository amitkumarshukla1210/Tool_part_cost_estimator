"""Stage 53: unique codes on every master-data row, live Price master prices, main / sub materials, more grades."""

from fastapi.testclient import TestClient

from backend.app import item_codes, master_data, material_grades, mould_db, price_master, rates
from backend.app.main import app

client = TestClient(app)


def test_new_grades_are_sub_materials_with_example_prices_of_their_main_grade():
    mats = {m["material"]: m for m in master_data.tables()["Materials"]}
    for name, main in (("PP CaCO3 20 % (mineral / talc filled)", "Polypropylene (PP)"), ("PP GF 30 % (glass filled)", "Polypropylene (PP)"),
                       ("ABS Colour White", "ABS"), ("ABS Sparkle", "ABS"), ("GI EDD (deep drawing, DX53D)", "Coated steel sheet"),
                       ("Zinc Zamak 5 (ZnAl4Cu1, ZP5)", "Zinc die-cast alloy"), ("Aluminium LM25 (AlSi7Mg, A356)", "Aluminium casting alloy"),
                       ("Brass CW617N (CuZn40Pb2, forging) bar", "Brass bar")):
        assert mats[name]["material_type"] == main
    for country in ("IN", "CN", "VN"):
        white, abs_ = rates.lookup("material", "ABS Colour White", country), rates.lookup("material", "ABS", country)
        assert white["value"] == abs_["value"] and white["is_example"] and "same as ABS" in white["source"]
        assert rates.lookup("material_scrap", "ABS Colour White", country)["value"] == rates.lookup("material_scrap", "ABS", country)["value"]
    assert rates.lookup("tool_material", "D3 (1.2080)", "IN")["value"] == rates.lookup("tool_material", "D2 (1.2379)", "IN")["value"]
    db = mould_db.tables()
    assert any(r["material"] == "ABS Sparkle" for r in db["flow_materials"])          # simulation works with the new grade
    assert any(r["material"] == "ABS Sparkle" for r in db["process_windows"])
    assert any(r["material"] == "GI IF (interstitial free, DX54D / DX56D)" for r in db["sheet_materials"])
    assert material_grades.seed() == {"materials": 0, "tool_materials": 0, "rates": 0, "engine_rows": 0}   # idempotent


def test_every_row_has_a_unique_stable_code_with_its_family_prefix():
    c = item_codes.for_dataset("general")
    mats = master_data.tables()["Materials"]
    code = dict(zip((m["material"] for m in mats), c["codes"]["Materials"]))
    assert code["ABS"].startswith("RM-PLE-") and code["PP (polypropylene)"].startswith("RM-PLC-")
    assert code["Galvanised steel GI"].startswith("RM-SHT-") and code["Zinc Zamak 3"].startswith("RM-ZN-")
    assert code["Aluminium ADC12 / A383"].startswith("RM-ALC-") and code["Gunmetal LG2 (CC491K, CuSn5Zn5Pb5)"].startswith("RM-CU-")
    assert len(set(code.values())) == len(code)                                         # one material, one code
    params = c["codes"]["Parameters"]
    assert all(x.startswith("PA-") for x in params) and len(set(params)) == len(params)
    m = item_codes.for_dataset("mould")
    assert m["codes"]["tool_materials"][0].startswith("TS-") and m["codes"]["design_rules"][0].startswith("DR-")
    every = [x for ds in ("general", "mould", "setup", "register") for t, xs in item_codes.for_dataset(ds)["codes"].items()
             if t not in item_codes.MATERIAL_TABLES for x in xs]
    assert len(every) == len(set(every))                                                # unique across all tabs
    # a changed value keeps the code; a new row gets the next number
    md = master_data.tables()
    abs_row = next(r for r in md["Materials"] if r["material"] == "ABS")
    abs_row["density_g_cm3"] = 1.06
    md["Materials"].append(dict(abs_row) | {"material": "ABS test grade", "recommended": ""})
    master_data.write(md)
    again = dict(zip((m["material"] for m in master_data.tables()["Materials"]), item_codes.for_dataset("general")["codes"]["Materials"]))
    assert again["ABS"] == code["ABS"]
    n = max(int(v.rsplit("-", 1)[1]) for k, v in code.items() if v.startswith("RM-PLE-"))
    assert again["ABS test grade"] == f"RM-PLE-{n + 1:03d}"


def test_live_price_per_country_and_month_from_the_price_master():
    c = item_codes.for_dataset("mould", "CN")
    p20 = c["prices"]["tool_materials"][0]
    assert p20["value"] == rates.lookup("tool_material", "P20 (1.2311)", "CN")["value"] and p20["currency"] == "CNY"
    assert c["priced"]["tool_materials"] == "tool_material" and "machines" not in c["prices"]
    s = item_codes.for_dataset("setup", "IN")
    assert s["prices"]["machines"][0]["unit"].startswith("INR")
    old = item_codes.for_dataset("general", "IN", "2020-01")
    assert old["prices"]["Materials"][0] is None                                         # no price before the first one
    rates.save_settings({"approver_name": "Tester"})
    price_master.set_price("part_material", "ABS", "IN", "2026-12", 155, approve=True)   # change in the Price master ...
    i = [m["material"] for m in master_data.tables()["Materials"]].index("ABS")
    assert item_codes.for_dataset("general", "IN", "2026-12")["prices"]["Materials"][i]["value"] == 155   # ... shows at once
    r = client.get("/api/master-codes/general?country=CN").json()
    assert r["country"] == "CN" and r["codes"]["Materials"][i].startswith("RM-PLE-")
    assert client.get("/api/master-codes/nope").status_code == 404


def test_price_master_rows_and_material_picker_carry_main_sub_and_code():
    g = price_master.grid("part_material", "IN")
    row = next(r for r in g["rows"] if r["item"] == "ABS Colour Black")
    assert row["type"] == "ABS" and row["code"].startswith("RM-PLE-")
    tool = next(r for r in price_master.grid("tool_material", "IN")["rows"] if r["item"] == "DC53 (Daido)")
    assert tool["code"].startswith("TS-")
    tree = {g["main"]: g["subs"] for g in client.get("/api/register-meta").json()["material_tree"]}
    subs = [s["material"] for s in tree["ABS"]]
    assert {"ABS", "ABS Colour White", "ABS Colour Black", "ABS Sparkle", "ABS flame retardant V0"} <= set(subs)
    assert {"GI D (IS 277 GP, DX51D)", "GI DD (drawing, DX52D)", "GI EDD (deep drawing, DX53D)",
            "GI IF (interstitial free, DX54D / DX56D)"} <= {s["material"] for s in tree["Coated steel sheet"]}
