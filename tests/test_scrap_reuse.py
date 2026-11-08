"""Scrap used again and scrap rate as % of the RM price (stage 49): moulding and casting buy only the virgin material, the
scrap left is sold at the fixed scrap rate or at a % of the RM rate; part > material > family."""

import pytest
from fastapi.testclient import TestClient

from backend.app import master_data, rm_cost
from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)
PART = {"net_weight_g": {"value": 1400, "unit": "g", "label": "Net weight"}}


def _run(**given):
    r = rm_cost.run("plastic", country="IN", material="PP (polypropylene)", part=PART,
                    given={"runner_pct": 600 / 14, "process_loss_pct": 0} | given)
    return {k.split(":", 1)[1]: v for k, v in r["nodes"].items()}


def test_amits_example_gross_2_net_1_4_reuse_20_percent():
    n = _run(scrap_reuse_pct=20, scrap_rate_pct_of_rm=30)
    assert n["gross_g"]["value"] == pytest.approx(2000) and n["returns_g"]["value"] == pytest.approx(600)
    assert n["reused_g"]["value"] == pytest.approx(120)                     # 0.6 kg × 20 %
    assert n["virgin_g"]["value"] == pytest.approx(1880)                    # 2 - 0.12 kg bought
    assert n["sold_g"]["value"] == pytest.approx(480)                       # 0.6 - 0.12 kg sold
    rate = n["material_rate"]["value"]
    assert n["scrap_value"]["value"] == pytest.approx(rate * 0.30)           # % of the RM rate
    assert n["rm_cost"]["value"] == pytest.approx(1.88 * rate)
    assert n["scrap_credit"]["value"] == pytest.approx(-0.48 * rate * 0.30)
    assert n["net_rm_cost"]["value"] == pytest.approx(1.88 * rate - 0.48 * rate * 0.30)


def test_starting_values_keep_the_rm_cost_as_before_with_the_fixed_scrap_rate():
    n = _run()                                                              # Parameters: 0 % and 0
    assert n["scrap_reuse_pct"]["source"] == {"type": "master", "sheet": "Parameters", "row": "plastic / scrap_reuse_pct"}
    rate, scrap = n["material_rate"]["value"], n["scrap_rate"]["value"]
    assert n["scrap_value"]["value"] == pytest.approx(scrap)                # fixed rate of the rate library
    assert n["net_rm_cost"]["value"] == pytest.approx(2.0 * rate - 0.6 * scrap)   # the formula before stage 49
    # sheet metal and machined parts keep their formulas
    assert not [r for r in master_data.tables()["Parameters"] if r["parameter"] == "scrap_reuse_pct"
                and r["part_type"] in ("sheet_metal", "machined")]


def test_material_value_wins_over_the_family_and_the_part_over_both():
    data = master_data.tables()
    data = {k: [dict(r) for r in v] for k, v in data.items()}
    row = next(r for r in data["Materials"] if r["part_type"] == "plastic" and r["material"] == "PP (polypropylene)")
    row["scrap_reuse_pct"], row["scrap_rate_pct_of_rm"] = 50, 25
    master_data.write(data)
    n = _run()
    assert n["scrap_reuse_pct"]["value"] == 50 and n["scrap_reuse_pct"]["source"]["sheet"] == "Materials"
    assert n["scrap_value"]["value"] == pytest.approx(n["material_rate"]["value"] * 0.25)
    pid = add_part(project("SR1"), "plastic_cover.step", "PP (polypropylene)", "injection_moulding", "SR1-1")
    r = client.post(f"/api/parts/{pid}/rm-cost", json={"rm_inputs": {"scrap_reuse_pct": 20}, "reason": "regrind 20 %"})
    assert r.status_code == 200
    tr = client.get(f"/api/parts/{pid}/rm-cost/trace").json()
    assert tr["nodes"]["in:scrap_reuse_pct"]["value"] == 20 and tr["nodes"]["in:scrap_reuse_pct"]["source"]["type"] == "user"
    assert tr["nodes"]["in:scrap_rate_pct_of_rm"]["value"] == 25                  # still the material's
    row["scrap_reuse_pct"] = 120
    with pytest.raises(master_data.MasterDataError):
        master_data.write(data)                                                 # 0-100 %, blank = Parameters


def test_seed_adds_nothing_twice():
    assert rm_cost.seed_scrap_reuse() == {"parameters": 0, "inputs": 0, "formulas": 0, "changed": 0}
