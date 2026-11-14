"""Stage 61: fin simulation - collar forming and press checks, collar forming FEA, strip pictures and video, report, saved run."""

import io
import math

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from backend.app import fea, fin_die_draw, fin_sim, sim_jobs
from backend.app.main import app
from tests.test_fin_part import fin_part_id

client = TestClient(app)
needs_ccx = pytest.mark.skipif(not fea.available()["ccx"], reason="CalculiX not installed")


def test_rules_shipped():
    assert fin_sim.seed() == 0
    R = fin_sim.rules()
    assert (R["fin_edge_strain_max"], R["fin_thinning_max_pct"], R["fin_form_skip_rings"]) == (0.6, 50, 1) and R["is_example"]


def test_checks_by_formula():
    des = fin_die_draw.build({}, 1, "x")
    c = {x["name"]: x for x in fin_sim.checks(des)}
    assert c["Hole-edge strain"]["value"] == pytest.approx(math.log((5.2 + 0.095) / (0.6 * 5.2)), abs=1e-4) and c["Hole-edge strain"]["ok"]
    assert c["Collar height"]["value"] == pytest.approx(25.4 / 21 - 0.095, abs=1e-4)
    assert c["Draw depth per draw step"]["value"] == pytest.approx((25.4 / 21 - 0.095) / 3, abs=1e-4)
    assert c["Die force vs press tonnage"]["ok"] and c["Press speed"]["value"] == pytest.approx(198)
    assert c["Feed per stroke vs press feed length"]["value"] == 64 and c["Foil width vs press material width"]["ok"]
    fast = {x["name"]: x for x in fin_sim.checks(fin_die_draw.build({"spm": 350}, 1, "x"))}
    assert not fast["Press speed"]["ok"]                                    # above the YKC-48SH-125 300 SPM
    small = {x["name"]: x for x in fin_sim.checks(fin_die_draw.build({"fpi": 28}, 1, "x"))}
    assert small["Collar height"]["value"] < 0.9


def test_pictures_and_video():
    des = fin_die_draw.build({}, 1, "x")
    pics = fin_sim.pictures(des)
    assert len(pics) == len(des["stations"]) and pics[0][1].startswith(b"\x89PNG") and pics[6][0] == "07 Reflare"
    data, ext = fin_sim.video(des)
    assert ext in ("mp4", "gif") and len(data) > 1000


@needs_ccx
def test_collar_forming_fea():
    des = fin_die_draw.build({}, 1, "x")
    fe = fin_sim.forming_fea(des)
    assert fe["png"].startswith(b"\x89PNG") and fe["elements"] == 60 * 3
    edge = math.log((5.2 + 0.095) / (0.6 * 5.2))
    assert edge < fe["peeq_max"] < 1.2 and 0 < fe["peeq_p95"] <= fe["peeq_max"]   # at least the hoop strain of the edge
    assert 20 < fe["thinning_max_pct"] < 50 and fe["ok"]
    tight = fin_sim.forming_fea(des, fin_sim.rules() | {"fin_thinning_max_pct": 10})
    assert not tight["ok_thinning"] and not tight["ok"]


@needs_ccx
def test_run_saved_on_the_part():
    pid, _ = fin_part_id("FIN-7")
    live = client.get(f"/api/parts/{pid}/fin-sim").json()
    assert live["runs"] == [] and live["ok"] and len(live["checks"]) == 7
    job = client.post(f"/api/parts/{pid}/fin-sim").json()
    done = sim_jobs.wait(job["id"], 600)
    assert done["status"] == "done", done
    runs = client.get(f"/api/parts/{pid}/fin-sim").json()["runs"]
    assert len(runs) == 1 and runs[0]["kind"] == "fin_sim" and runs[0]["pdf"] and runs[0]["video"]
    assert runs[0]["results"]["peeq_max"] > 0
    pdf = client.get(f"/api/parts/{pid}/sim-runs/{runs[0]['id']}/pdf")
    text = PdfReader(io.BytesIO(pdf.content)).pages[0].extract_text()
    assert pdf.status_code == 200 and "FIN SIMULATION" in text and "Collar forming FEA" in text
    vid = client.get(f"/api/parts/{pid}/sim-runs/{runs[0]['id']}/video")
    assert vid.status_code == 200 and vid.headers["content-type"] in ("video/mp4", "image/gif")
