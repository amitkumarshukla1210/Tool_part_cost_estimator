"""Stage 60: fin parts in the part register like moulded / pressed parts - RM, tool, part cost, design, FEA, moved fin dies."""

import pytest
from fastapi.testclient import TestClient

from backend.app import fea, fin_design, fin_die, fin_part, register_setup, scope, sim_jobs
from backend.app.main import app

client = TestClient(app)
needs_fea = pytest.mark.skipif(not fea.available()["available"], reason="Gmsh / CalculiX not installed")


def fin_part_id(code="FIN-1", spec=None):
    p = client.post("/api/projects", json={"code": "AC" + code[-1], "name": "AC"}).json()
    m = client.post("/api/import/step", files={"file": ("fin.step", fin_design.fin_step(spec or {}))}).json()
    r = client.post(f"/api/import/{m['token']}/commit", json={"project_id": p["id"], "items": {m["root"]: {
        "material": fin_die.DEFAULT_MATERIAL, "process": "fin_press", "part_code": code}}})
    assert r.status_code == 200, r.text
    pid = r.json()["part_ids"][0]
    assert client.put(f"/api/parts/{pid}", json={"annual_volume": 100000, "programme_life_years": 5}).status_code == 200
    return pid, p["id"]


def test_process_and_groups_shipped():
    assert fin_part.seed() == 0
    proc = register_setup.processes()["fin_press"]
    assert proc["part_type"] == "fin" and not proc["is_assembly"]
    assert "fin" in register_setup.PART_TYPES and "fin" in scope.GROUPS


def test_costs_like_any_part():
    pid, proj = fin_part_id()
    d = client.get(f"/api/parts/{pid}").json()
    assert d["rm"]["applicable"] and d["tool"]["applicable"]
    assert d["rm_cost_inr"] > 0 and d["tool_cost_inr"] > 0                 # calculated when the part was saved, like every part
    assert client.post(f"/api/parts/{pid}/piece-cost", json={}).json()["stored"]
    tr = client.get(f"/api/parts/{pid}/piece-cost/trace").json()
    rm = client.get(f"/api/parts/{pid}/rm-cost/trace").json()
    tool = client.get(f"/api/parts/{pid}/tool-cost/trace").json()
    assert tr["machine"] == "YKC-48SH-125" and tool["part_type"] == "fin" and tool["trial"]["machine"]["machine_id"] == "YKC-48SH-125"
    assert tr["nodes"]["calc:rm_cost"]["value"] == pytest.approx(rm["value"])          # RM card = the foil step of the pack cost
    assert tr["nodes"]["die:" + tool["root"]]["value"] == pytest.approx(tool["value"])  # the stored fin die is grafted in
    assert rm["named"]["gross_g"] > rm["named"]["net_g"] > 0
    d = client.get(f"/api/parts/{pid}").json()
    assert d["piece_cost_inr"] == pytest.approx(tr["value_inr"])
    dash = client.get(f"/api/projects/{proj}/dashboard")
    assert dash.status_code == 200
    vs = client.get(f"/api/parts/{pid}/vs-country")
    assert vs.status_code == 200 and client.get(f"/api/parts/{pid}/country-comparison").status_code == 200


def test_fin_inputs_recalculate():
    pid, _ = fin_part_id("FIN-2")
    f = client.get(f"/api/parts/{pid}/fin").json()
    assert f["ok"] and f["spec"]["pattern"] == "plain" and f["read"]["source"] == "STEP"   # the test STEP has no louvers
    assert f["spec"]["die_rows"] == 66 and f["proposal"]["progressions"] == 4
    plain = client.get(f"/api/parts/{pid}").json()["tool_cost_inr"]
    r = client.put(f"/api/parts/{pid}/fin", json={"pattern": "louver", "pack_length_mm": 650, "spm": 260})
    assert r.status_code == 200 and r.json()["spec"]["pattern"] == "louver" and r.json()["typed"]["spm"] == 260
    d = client.get(f"/api/parts/{pid}").json()
    assert d["tool_cost_inr"] > plain and d["fin_inputs"]["pack_length_mm"] == 650   # louver die costs more; recalculated at once
    assert client.put(f"/api/parts/{pid}/fin", json={"pattern": "pin"}).status_code == 400
    assert client.put(f"/api/parts/{pid}/fin", json={"fin_rows": 99}).status_code == 400


def test_dxf_drawing_without_step():
    p = client.post("/api/projects", json={"code": "ACD", "name": "AC"}).json()
    from backend.app import projects_db as db, register
    with db.engine().begin() as conn:
        pid, _ = register.upsert_part(conn, p["id"], "FIN-D", {"name": "fin", "material": fin_die.DEFAULT_MATERIAL, "process": "fin_press"})
    s = client.get(f"/api/parts/{pid}/fin").json()
    assert not s["ok"] and "STEP" in s["problem"]
    r = client.post(f"/api/parts/{pid}/fin/drawing", files={"file": ("fin.dxf", fin_design.fin_dxf({}))})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["read"]["source"] == "DXF" and r.json()["spec"]["hole_pitch_mm"] == 16


def test_design_files_on_the_part():
    pid, _ = fin_part_id("FIN-3")
    d = client.get(f"/api/parts/{pid}/fin-design").json()
    assert d["prefix"] == "FD-FIN-3" and d["parts"][0]["drawing"] == "FD-FIN-3-01"
    r = client.get(f"/api/parts/{pid}/fin-design/po-pack.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers.get("x-dtc-saved", "").startswith("rev 1")   # saved files
    again = client.get(f"/api/parts/{pid}/fin-design/po-pack.pdf")
    assert "rev 1" in again.headers.get("x-dtc-saved", "")
    assert client.get(f"/api/parts/{pid}/fin-design/strip.dxf").status_code == 200
    assert client.get(f"/api/parts/{pid}/fin-design/x").status_code == 404
    f = client.get(f"/api/parts/{pid}/fin-fea").json()
    assert f["runs"] == [] and len(f["punches_now"]) == 3                    # plain fin: draw, pierce, reflare punches


@needs_fea
def test_fea_on_the_part():
    from backend.app import mould_db
    d = mould_db.tables()
    for r in d["design_rules"]:
        if r["part_type"] == "fin" and r["parameter"] in ("fea_mesh_mm", "fea_mesh_per_circle"):
            r["value"] = 60 if r["parameter"] == "fea_mesh_mm" else 4
    mould_db.write(d)
    pid, _ = fin_part_id("FIN-4")
    job = client.post(f"/api/parts/{pid}/fin-fea").json()
    assert sim_jobs.wait(job["id"], 900)["status"] == "done"
    f = client.get(f"/api/parts/{pid}/fin-fea").json()
    assert len(f["runs"]) == 4 and f["ok"]
    png = client.get(f"/api/parts/{pid}/fin-fea/{f['runs'][0]['id']}.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"


def test_saved_fin_dies_moved_and_page_redirects():
    rec = client.post("/api/fin-dies", json={"name": "IFB louver", "spec": {"pattern": "louver", "pack_length_mm": 650}}).json()
    first = fin_part.move_saved_fin_dies()
    assert first["moved"] == 1 and fin_part.move_saved_fin_dies() == {"moved": 0}
    rows = client.get("/api/parts").json()["rows"]
    moved = next(x for x in rows if x["part_code"] == f"FIN-{rec['id']}")
    d = client.get(f"/api/parts/{moved['id']}").json()
    assert (d["process"], d["rev"], d["fin_inputs"]["pattern"], d["fin_inputs"]["pack_length_mm"]) == ("fin_press", "A", "louver", 650)
    assert d["rm_cost_inr"] > 0 and d["tool_cost_inr"] > 0
    r = client.get("/fin-dies", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/parts"
