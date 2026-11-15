"""Stage 62: the oil & air system of the fin die - quantities, BOM lines, design outputs and checks."""

import io
import zipfile

import pytest
from pypdf import PdfReader

from backend.app import fin_die, fin_die_draw, fin_oil, fin_sim, mould_db


def test_seed_shipped_and_lump_sum_retired():
    assert fin_oil.seed() == {"rows": 0, "lump_retired": 0}
    lump = next(r for r in mould_db.tables()["bom_elements"] if r["part_type"] == "fin" and r["element"] == fin_oil.LUMP)
    assert lump["quantity_rule"] == "0" and "stage 62" in lump["notes"]


def test_changed_lump_sum_row_is_left_alone():
    d = mould_db.tables()
    lump = next(r for r in d["bom_elements"] if r["part_type"] == "fin" and r["element"] == fin_oil.LUMP)
    lump["quantity_rule"], lump["unit_cost_rule"] = "1", "90000"            # your own price
    mould_db.write(d)
    assert fin_oil.seed()["lump_retired"] == 0
    lump = next(r for r in mould_db.tables()["bom_elements"] if r["part_type"] == "fin" and r["element"] == fin_oil.LUMP)
    assert (lump["quantity_rule"], lump["unit_cost_rule"]) == ("1", "90000")


def test_quantities_and_bom_lines():
    d = fin_die.run({})["die"]
    c = fin_oil.counts(d)
    assert c == {"oil_stations": 6, "oil_nozzles": 36, "air_stations": 2, "air_nozzles": 18, "pipe_m": pytest.approx(2 * (1260 + 2 * 968) / 1000)}
    lines = {l["element"]: l for l in d["lines"]}
    assert lines["Mist oil nozzle"]["quantity"] == 36 and lines["Air blow nozzle"]["quantity"] == 18
    assert lines["Oil / air piping & fittings (per m)"]["quantity"] == 7 and fin_oil.LUMP not in lines
    assert lines["Oil & air system fitting"]["hours"] == pytest.approx(12 + 0.25 * (36 + 18))
    assert d["nodes"]["v:oil_nozzles"]["formula"] == "oil_stations * ceil(foil_w / fin_oil_nozzle_pitch_mm)"
    plain = fin_oil.counts(fin_die.run({"pattern": "plain"})["die"])
    assert plain["oil_stations"] == 5 and plain["oil_nozzles"] == 30          # 3 draw + pierce + edge trim (no ironing)


def test_design_outputs():
    des = fin_die_draw.build({}, 3, "IFB louver")
    names = [p["name"] for p in des["parts"]]
    assert {"Mist oil nozzle", "Air blow nozzle", "Oil manifold block", "Air manifold block"} <= set(names)
    lay = fin_oil.layout(des)
    assert sum(1 for n in lay["nozzles"] if n["kind"] == "oil") == 36 and sum(1 for n in lay["nozzles"] if n["kind"] == "air") == 18
    pdf = PdfReader(io.BytesIO(fin_die_draw.drawings_pdf(des)))
    assert "Oil & air system schematic" in pdf.pages[2].extract_text()
    with zipfile.ZipFile(io.BytesIO(fin_die_draw.dxf_zip(des))) as z:
        assert "FD-3-OA_oil_air_schematic.dxf" in z.namelist()
    po = "".join(p.extract_text() for p in PdfReader(io.BytesIO(fin_die_draw.po_pack_pdf(des))).pages[:3])
    assert "11. Oil & air system" in po and "FD-3-OA" in po
    assert "Mist oil nozzles" in fin_die_draw.viewer_html(des)


def test_checks_in_the_simulation():
    des = fin_die_draw.build({}, 1, "x")
    c = {x["name"]: x for x in fin_sim.checks(des)}
    assert c["Air blow use vs air supply"]["value"] == pytest.approx(18 * 0.05 * 198) and c["Air blow use vs air supply"]["ok"]
    assert c["Mist oil per pack vs oil of the part cost"]["ok"]
    d = mould_db.tables()
    for r in d["design_rules"]:
        if r["part_type"] == "fin" and r["parameter"] == "fin_air_supply_nl_min":
            r["value"] = 100
    mould_db.write(d)
    assert not {x["name"]: x for x in fin_sim.checks(des)}["Air blow use vs air supply"]["ok"]
