"""India vs the comparison country on every tool and part cost line (stage 48): the same engines with that country's
approved rates, in its currency and INR, landed rows up to the factory, downloads named India_vs_<country>."""

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


def test_every_line_has_the_china_value_in_cny_and_inr_and_the_landed_rows_add_up():
    pid = _costed("VS1")
    v = client.get(f"/api/parts/{pid}/vs-country").json()
    assert (v["home"], v["country"], v["name"], v["currency"]) == ("IN", "CN", "China", "CNY") and not v["error"]
    k = v["fx_inr_per_unit"]
    for block in ("tool", "piece"):
        lines = [r for r in v["rows"][block] if not r["landed"]]
        assert len(lines) > 8
        money = [r for r in lines if r["unit"] == "INR" and r["local"]]
        assert money and all(r["inr"] == pytest.approx(r["local"] * k, rel=1e-9) for r in money
                             if not r["node"].endswith(":inr")), block
        assert all(r["home"] is not None for r in lines), block                     # India value on every line
        land = {r["node"].removeprefix("landed:"): r for r in v["rows"][block] if r["landed"]}
        total = sum(land[x]["inr"] for x in ("cif", "bcd", "sws", "igst", "igst_credit", "clearance", "inland"))
        assert land["landed"]["inr"] == pytest.approx(total, rel=1e-9)            # IGST shown, its credit taken
        assert land["cif"]["inr"] == pytest.approx(land["exw"]["inr"] + land["freight"]["inr"] + land["insurance"]["inr"], rel=1e-9)
        assert land["igst"]["inr"] > 0 and land["igst_credit"]["inr"] == pytest.approx(-land["igst"]["inr"])
        assert land["freight"]["home"] == 0 and land["landed"]["home"] > 0           # India: no import, inland only
    assert v["saving_inr"]["piece"] == pytest.approx(
        next(r for r in v["rows"]["piece"] if r["node"] == "landed:landed")["inr"]
        - next(r for r in v["rows"]["piece"] if r["node"] == "landed:landed")["home"])
    # every China value can be opened: its trace comes with the answer
    assert all(r["node"] in v["piece_trace"]["nodes"] for r in v["rows"]["piece"] if not r["landed"])
    assert v["tool_trace"]["currency"] == "CNY"


def test_downloads_carry_both_countries_and_are_named_india_vs_china():
    from openpyxl import load_workbook
    pid = _costed("VS2")
    x = client.get(f"/api/parts/{pid}/vs-country/export.xlsx")
    assert x.status_code == 200 and 'filename="VS2-1_cost_India_vs_China.xlsx"' in x.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(x.content))
    assert wb.sheetnames == ["Tool cost IN vs CN", "Part cost IN vs CN", "Rates used"]
    values = [c for row in wb["Part cost IN vs CN"].iter_rows(values_only=True) for c in row if c is not None]
    assert "India (INR or unit)" in values and "China (INR)" in values and "Landed cost at the factory" in values
    p = client.get(f"/api/parts/{pid}/vs-country/export.pdf")
    assert p.status_code == 200 and 'filename="VS2-1_cost_India_vs_China.pdf"' in p.headers["content-disposition"]
    import pdfplumber
    text = "\n".join(pg.extract_text() or "" for pg in pdfplumber.open(io.BytesIO(p.content)).pages)
    assert "INDIA VS CHINA" in text and "Landed cost at the factory" in text and "Design to Cost" in text


def test_the_comparison_country_is_master_data_and_works_for_sheet_metal():
    data = register_setup.tables()
    row = next(r for r in data["register_settings"] if r["key"] == "compare_country")
    assert row["value"] == "CN" and landed.seed() == 0                              # shipped, the seed adds nothing twice
    row["value"] = "VN"
    register_setup.write(data)
    pid = _costed("VS3", "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage")
    v = client.get(f"/api/parts/{pid}/vs-country").json()
    assert (v["country"], v["currency"]) == ("VN", "VND") and not v["error"] and v["rows"]["piece"]
    assert "India_vs_Vietnam.xlsx" in client.get(f"/api/parts/{pid}/vs-country/export.xlsx").headers["content-disposition"]
    row["value"] = "IN"
    register_setup.write(data)
    assert client.get(f"/api/parts/{pid}/vs-country").status_code == 400            # the home country is refused
