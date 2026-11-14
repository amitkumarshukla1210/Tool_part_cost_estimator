"""Stage 59: FEA of the fin die at the full press capacity - plates (Gmsh + CalculiX) and punch buckling (formula)."""

import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from backend.app import fea, fin_die, fin_die_draw, fin_fea, mould_db, sim_jobs
from backend.app.main import app

client = TestClient(app)
needs_fea = pytest.mark.skipif(not fea.available()["available"], reason="Gmsh / CalculiX not installed")


def _rules(**values):
    d = mould_db.tables()
    for r in d["design_rules"]:
        if r["part_type"] == "fin" and r["parameter"] in values:
            v = values[r["parameter"]]
            if isinstance(v, str):
                r["text"] = v
            else:
                r["value"] = v
    mould_db.write(d)


@pytest.fixture
def coarse():
    _rules(fea_mesh_mm=60, fea_mesh_per_circle=4)          # fast meshes for the tests


def test_rules_shipped():
    assert fin_fea.seed() == 0
    R = fin_fea.rules()
    assert (R["fea_max_deflection_mm"], R["fea_lower_support"], R["fea_slice_rows"], R["thicken"]) == (0.02, "full", 4, [1.25, 1.5, 2.0])
    assert R["parts"] == ["pierce sub-die plate", "draw sub-die plate", "lower die plate"]


def test_punch_buckling_at_press_capacity():
    des = fin_die_draw.build({}, 1, "x")
    force, how = fin_fea.capacity_n(des)
    assert force == pytest.approx(125 * 1000 * 9.80665) and how.startswith("YKC-48SH-125: 125 t")
    rows = {p["name"]: p for p in fin_fea.punch_checks(des)}
    assert set(rows) == {"Draw punch", "Pierce & burring punch", "Ironing punch", "Reflare punch"}
    pierce = rows["Pierce & burring punch"]
    assert pierce["load_n"] == pytest.approx(force / (6 * 264), rel=1e-3)       # 6 punch stations × 264 holes share the press capacity
    assert pierce["d_mm"] == pytest.approx(3.12) and pierce["free_mm"] == pytest.approx(0.6 * 55)
    assert pierce["ok"] and pierce["safety"] > 3 and pierce["method"] == "Johnson"
    _rules(fea_punch_free_share=6, fea_punch_sf_min=50)
    bad = {p["name"]: p for p in fin_fea.punch_checks(des)}["Pierce & burring punch"]
    assert not bad["ok"] and bad["method"] == "Euler" and bad["suggest"].startswith("Guide the punch closer: free length ≤")


def test_targets_slice_and_support():
    des = fin_die_draw.build({}, 1, "x")
    t = {x["key"]: x for x in fin_fea.targets(des, 4, "full")}
    p = t["Pierce sub-die plate"]
    assert p["dims"] == (80.0, pytest.approx(4 * 12.7), 45.0) and len(p["holes"]) == 4 * 4 and p["share"] == pytest.approx(50.8 / 848)
    assert t["Lower die plate"]["strip"] is False and t["Lower die plate"]["dims"] == (1500, 1100, 90)
    assert fin_fea.targets(des, 3, "strips")[0]["dims"][1] == pytest.approx(4 * 12.7)   # staggered: whole periods (3 → 4 rows)
    assert fin_fea.targets(des, 4, "strips")[-1]["strip"] is True
    _rules(fea_lower_support="beams")
    with pytest.raises(fin_fea.FinFeaError, match="full' or 'strips"):
        fin_fea.rules()


@needs_fea
def test_fea_run_stored_and_out_of_date(coarse):
    rec = fin_die.save({"name": "fea test", "spec": {}})
    fin_fea.run(rec["id"])
    lat = fin_fea.latest(rec["id"])
    plates = [r for r in lat["runs"] if r["kind"] == "plate"]
    assert len(plates) == 3 and lat["ok"] and all(r["result"]["press_force_n"] == pytest.approx(125 * 9806.65) for r in plates)
    assert plates[0]["result"]["slice"].startswith("4 of 66 rows")
    assert fin_fea.picture(rec["id"], plates[0]["id"]).startswith(b"\x89PNG")
    assert len(fin_fea.pictures(rec["id"])) == 3
    fin_die.save({"name": "fea test", "spec": {"pattern": "plain"}}, rec["id"])
    later = fin_fea.latest(rec["id"])
    assert later["out_of_date"] and not later["runs"] and later["ok"] is None


@needs_fea
def test_failing_plate_gets_a_thickness(coarse):
    _rules(fea_parts="Lower die plate", fea_lower_support="strips", fea_max_deflection_mm=0.3)
    rec = fin_die.save({"name": "thin", "spec": {}})
    fin_fea.run(rec["id"])
    r = next(x for x in fin_fea.latest(rec["id"])["runs"] if x["kind"] == "plate")["result"]
    assert r["support"] == "two edge strips" and r["thickness_mm"] == 90
    if r["ok"]:                                                   # the coarse mesh may already pass at 0.3 mm
        assert r["suggest"] is None
    else:
        assert r["suggest"]["text"]
        if r["suggest"]["thickness_mm"]:
            assert r["suggest"]["thickness_mm"] > 90 and r["suggest"]["thickness_mm"] % 5 == 0


@needs_fea
def test_api_job_and_po_pack(coarse):
    rec = client.post("/api/fin-dies", json={"name": "api fea", "spec": {}}).json()
    first = client.get(f"/api/fin-dies/{rec['id']}/fea").json()
    assert first["runs"] == [] and len(first["punches_now"]) == 4 and first["available"]["available"]
    job = client.post(f"/api/fin-dies/{rec['id']}/fea").json()
    done = sim_jobs.wait(job["id"], 900)
    assert done["status"] == "done", done
    assert client.get(f"/api/fin-dies/{rec['id']}/fea-jobs/{job['id']}").json()["status"] == "done"
    res = client.get(f"/api/fin-dies/{rec['id']}/fea").json()
    assert len(res["runs"]) == 4 and res["ok"]
    png = client.get(f"/api/fin-dies/{rec['id']}/fea/{res['runs'][0]['id']}.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    pdf = PdfReader(io.BytesIO(client.get(f"/api/fin-dies/{rec['id']}/design/po-pack.pdf").content))
    text = "".join(p.extract_text() for p in pdf.pages[:4])
    assert "FEA at the full press capacity" in text and "Punch" in text
    assert client.get(f"/api/fin-dies/{rec['id']}/fea-jobs/nope").status_code == 404
