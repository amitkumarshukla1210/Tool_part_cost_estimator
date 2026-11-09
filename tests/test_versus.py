"""The producing country next to other countries on every RM, tool and part cost line (stages 48 and 50): the same engines
with each country's approved rates, its currency and INR, a forex row, landed rows up to the factory, downloads named
<own>_vs_<others>."""

import io

import pytest
from fastapi.testclient import TestClient

from backend.app import landed, register_setup
from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def _costed(code, file="plastic_cover.step", material="ABS", process="injection_moulding"):
    pid = add_part(project(code), file, material, process, f"{code}-1")
    for what in ("rm-cost", "tool-cost", "piece-cost"):
        assert client.post(f"/api/parts/{pid}/{what}", json={"reason": "test"}).status_code == 200, what
    return pid


def test_every_line_has_each_country_in_its_currency_and_inr_and_the_landed_rows_add_up():
    pid = _costed("VS1")
    v = client.get(f"/api/parts/{pid}/vs-country").json()
    assert v["own"] == {**v["own"], "country": "IN", "name": "India", "currency": "INR"}
    assert [b["country"] for b in v["countries"]] == ["CN"]                         # default: Register settings compare_country
    cn = v["countries"][0]
    assert cn["currency"] == "CNY" and not cn["error"]
    k = cn["fx_inr_per_unit"]
    for block in ("rm", "tool", "piece"):
        money = [n for n in cn[block]["nodes"].values() if n["money"] and n["value"] and not n["unit"].startswith("INR")]
        kb = cn["tool"]["fx_inr_per_unit"] if block == "tool" else k
        assert money and all(n["inr"] == pytest.approx(n["value"] * kb, rel=1e-9) for n in money), block
    for block in ("tool", "piece"):
        land = {x["key"]: x for x in cn["landed"][block]}
        total = sum(land[x]["inr"] for x in ("cif", "bcd", "sws", "igst", "igst_credit", "clearance", "inland"))
        assert land["landed"]["inr"] == pytest.approx(total, rel=1e-9)            # IGST shown, its credit taken
        assert land["igst"]["inr"] > 0 and land["igst_credit"]["inr"] == pytest.approx(-land["igst"]["inr"])
        own = {x["key"]: x for x in v["own"][block]["landed"]}
        assert own["freight"]["inr"] == 0 and own["landed"]["inr"] > 0           # India: no import, inland only
        assert cn["saving_inr"][block] == pytest.approx(land["landed"]["inr"] - own["landed"]["inr"])
    # rows: own local | own INR | China CNY | China INR, the forex row first
    rows = landed.versus_rows(v, "piece")
    assert rows[0][0].startswith("Forex") and rows[0][1] == 1.0 and rows[0][3] == pytest.approx(k)
    assert all(len(r) == 5 for r in rows)
    assert all(n in cn["traces"]["piece"]["nodes"] for n in cn["piece"]["nodes"])  # every value can be opened


def test_downloads_carry_every_country_and_are_named_after_them():
    from openpyxl import load_workbook
    pid = _costed("VS2")
    x = client.get(f"/api/parts/{pid}/vs-country/export.xlsx")
    assert x.status_code == 200 and 'filename="VS2-1_cost_India_vs_China.xlsx"' in x.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(x.content))
    assert wb.sheetnames == ["RM cost IN vs CN", "Tool cost IN vs CN", "Part cost IN vs CN", "Rates used"]
    values = [c for row in wb["Part cost IN vs CN"].iter_rows(values_only=True) for c in row if c is not None]
    assert "India (INR)" in values and "China (CNY)" in values and "China (INR)" in values and "Landed cost at the factory" in values
    p = client.get(f"/api/parts/{pid}/vs-country/export.pdf")
    assert p.status_code == 200 and 'filename="VS2-1_cost_India_vs_China.pdf"' in p.headers["content-disposition"]
    import pdfplumber
    text = "\n".join(pg.extract_text() or "" for pg in pdfplumber.open(io.BytesIO(p.content)).pages)
    assert "INDIA VS CHINA" in text and "Landed cost at the factory" in text and "Design to Cost" in text


def test_several_countries_per_part_and_a_china_producing_part_shows_china_in_its_own_column():
    pid = _costed("VS3")
    assert client.put(f"/api/parts/{pid}", json={"compare_countries": ["CN", "VN"]}).status_code == 200
    v = client.get(f"/api/parts/{pid}/vs-country").json()
    assert [b["country"] for b in v["countries"]] == ["CN", "VN"]
    assert landed.versus_head(v) == ["Line", "India (INR)", "India (INR)", "China (CNY)", "China (INR)", "Vietnam (VND)", "Vietnam (INR)"]
    assert "India_vs_China_Vietnam.xlsx" in client.get(f"/api/parts/{pid}/vs-country/export.xlsx").headers["content-disposition"]
    assert client.put(f"/api/parts/{pid}", json={"compare_countries": ["XX"]}).status_code == 400
    # producing country China (screenshot: both columns showed the China values under 'India'): own = China, India compared
    assert client.put(f"/api/parts/{pid}", json={"country": "CN", "compare_countries": ["IN"]}).status_code == 200
    for what in ("rm-cost", "tool-cost", "piece-cost"):
        client.post(f"/api/parts/{pid}/{what}", json={"reason": "China"})
    v = client.get(f"/api/parts/{pid}/vs-country").json()
    assert (v["own"]["country"], v["own"]["currency"]) == ("CN", "CNY") and [b["country"] for b in v["countries"]] == ["IN"]
    own_rate = v["own"]["rm"]["nodes"]["in:material_rate"]
    india_rate = v["countries"][0]["rm"]["nodes"]["in:material_rate"]
    assert own_rate["unit"].startswith("CNY") and india_rate["unit"].startswith("INR") and own_rate["value"] != india_rate["value"]


def test_the_default_comparison_country_is_master_data_and_works_for_sheet_metal():
    data = register_setup.tables()
    row = next(r for r in data["register_settings"] if r["key"] == "compare_country")
    assert row["value"] == "CN" and landed.seed() == 0
    row["value"] = "VN"
    register_setup.write(data)
    pid = _costed("VS4", "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage")
    v = client.get(f"/api/parts/{pid}/vs-country").json()
    assert [(b["country"], b["currency"]) for b in v["countries"]] == [("VN", "VND")] and not v["countries"][0]["error"]
    assert client.get(f"/api/parts/{pid}").json()["effective_compare_countries"] == ["VN"]


def test_tool_life_typed_on_the_part_drives_the_tools_and_the_amortisation():
    pid = _costed("VS5")
    before = client.get(f"/api/parts/{pid}/piece-cost/trace").json()
    assert client.put(f"/api/parts/{pid}", json={"tool_life_shots": 50000}).status_code == 200
    client.post(f"/api/parts/{pid}/piece-cost", json={"reason": "tool life"})
    after = client.get(f"/api/parts/{pid}/piece-cost/trace").json()
    assert after["nodes"]["in:tool_life_shots"]["value"] == 50000 and after["nodes"]["in:tool_life_shots"]["source"]["type"] == "user"
    assert after["nodes"]["in:tool_life_shots"]["value"] != before["nodes"]["in:tool_life_shots"]["value"]
    assert client.put(f"/api/parts/{pid}", json={"tool_life_shots": -5}).status_code == 400
