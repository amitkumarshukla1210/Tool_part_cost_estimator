import math

import cadquery as cq
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import flow_sim, master_data, mould_db, process_params, render3d, sim_jobs
from backend.app.geometry import analyze, tessellate
from backend.app.main import app

client = TestClient(app)


def solve(shape, part_type, material, axis="z", **kw):
    m = analyze(shape, part_type, 1.0)
    across = sorted((v for a, v in m.bbox_axes_mm.items() if a != axis), reverse=True)
    rho = {"plastic": 1.05, "die_casting": 2.7, "foundry": 7.1, "eps": 0.02, "blow": 1.38}[part_type]
    facts = {"part_weight_g": m.volume_mm3 / 1000 * rho, "wall_mm": kw.pop("wall", 0), "part_l": across[0], "part_w": across[1],
             "part_h": m.bbox_axes_mm[axis], "projected_area_cm2": m.projected_area_mm2[axis] / 100, "volume_cm3": m.volume_mm3 / 1000,
             "cavities": 1, "density_g_cm3": rho}
    mat = kw.pop("mat", None) or flow_sim.material(material)
    return flow_sim.run(*tessellate(shape), part_type, mat, process_params.window(material), facts, axis, **kw)


def near(clusters, point, tol):
    return any(np.linalg.norm(np.asarray(c["centre_mm"]) - np.asarray(point)) < tol for c in clusters)


def test_seeded_flow_data_for_every_moulded_material():
    assert flow_sim.seed() == {"materials": 0, "rules": 0}          # shipped already, nothing added twice
    have = {r["material"] for r in mould_db.tables()["flow_materials"]}
    for r in master_data.tables()["Materials"]:
        if r["part_type"] in flow_sim.PART_TYPES:
            assert r["material"] in have, r["material"]
    names = {(r["part_type"], r["name"]) for r in mould_db.tables()["flow_rules"]}
    for pt in flow_sim.PART_TYPES:
        assert (pt, "mesh_size_mm") in names


def test_refine_makes_an_even_mesh():
    v, f = tessellate(cq.Workplane("XY").box(200, 100, 3).val())
    tri0 = np.asarray(v)[np.asarray(f)]
    tri, src, s = flow_sim.refine(tri0, 5, 100000)
    edges = np.linalg.norm(tri - np.roll(tri, 1, axis=1), axis=2).max(1)
    assert len(tri0) == 12 and len(tri) > 1000 and edges.max() <= s + 1e-9
    area = lambda t: np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() / 2
    assert math.isclose(area(tri), area(tri0), rel_tol=1e-9)        # same surface, only split


def test_plastic_plate_fills_from_the_gate_with_a_weld_line_behind_the_hole():
    plate = cq.Workplane("XY").box(200, 80, 3).faces(">Z").workplane().hole(24).val()
    r = solve(plate, "plastic", "ABS", gate_point=[-99, 0, 0], wall=3)
    f, res = r["_faces"], r["results"]
    x = f["tri"].mean(1)[:, 0]
    t = f["t"]
    assert np.nanmean(t[x < -60]) < np.nanmean(t[x > 60])           # fills from the gate end to the far end
    assert res["unfilled_cm2"] == 0 and res["fill_time_s"] > 0
    assert 0 < res["injection_bar"] < 1800 and res["clamp_t"] > 0
    assert near(r["clusters"]["weld"], [30, 0, 0], 35)              # the fronts meet behind the hole
    # cooling time of the 3 mm wall: h² / (π² α) · ln(4/π · (Tm − Tw) / (Te − Tw)) with the ABS data
    w, mat = process_params.window("ABS"), flow_sim.material("ABS")
    t_cool = 9 / (math.pi ** 2 * mat["diffusivity_mm2_s"]) * math.log(4 / math.pi * (w["melt_c"] - w["mould_c"]) / (w["eject_c"] - w["mould_c"]))
    assert math.isclose(np.median(f["solid"]), t_cool, rel_tol=0.05)
    assert r["machine"]["machine_id"] and r["is_example"]            # seeded flow data are EXAMPLE values


def test_die_casting_isolated_thick_boss_is_shrinkage_porosity():
    part = cq.Workplane("XY").box(140, 60, 3).union(cq.Workplane("XY").box(18, 18, 16).translate((50, 0, 8))).val()
    r = solve(part, "die_casting", "Aluminium ADC12 / A383", gate_point=[-69, 0, 0], wall=3)
    assert r["areas_cm2"]["porosity"] > 0
    assert near(r["clusters"]["porosity"], [50, 0, 6], 20)
    assert r["risers"] and r["risers"][0]["modulus_mm"] > 3
    assert 0.005 < r["results"]["fill_time_s"] < 0.5                # NADCA: tens of milliseconds
    assert any("porosity" in c for c in r["corrections"])


def test_foundry_gas_trapped_on_a_post_inside_a_bowl_not_in_a_plain_bowl():
    bowl = cq.Workplane("XY").box(120, 120, 60).faces(">Z").shell(-6)
    plain = solve(bowl.val(), "foundry", "Grey cast iron FG260", wall=6)
    assert plain["areas_cm2"]["air_trap"] == 0
    post = bowl.union(cq.Workplane("XY").box(24, 24, 30).translate((0, 0, -24 + 15))).val()
    r = solve(post, "foundry", "Grey cast iron FG260", wall=6)
    assert near(r["clusters"]["air_trap"], [0, 0, 6], 12)             # the top of the post: gas cannot rise to the vents
    assert r["results"]["cope_weight_kg"] > 0


def test_blow_moulding_over_stretch(tmp_path):
    from pathlib import Path
    shape = cq.importers.importStep(str(Path(__file__).parents[1] / "samples" / "pet_bottle.step")).val()
    ok = solve(shape, "blow", "PET bottle grade (IV 0.80)", axis="x")
    assert ok["areas_cm2"]["over_stretch"] == 0 and 2 < ok["results"]["axial"] < 4
    tight = dict(flow_sim.material("PET bottle grade (IV 0.80)"), stretch_max=4)
    r = solve(shape, "blow", "PET bottle grade (IV 0.80)", axis="x", mat=tight)
    assert r["areas_cm2"]["over_stretch"] > 0 and any("Stretch ratio" in c for c in r["corrections"])


def test_no_flow_data_for_the_material():
    with pytest.raises(flow_sim.FlowError, match="Flow materials"):
        solve(cq.Workplane("XY").box(50, 50, 3).val(), "plastic", "Unknown grade")


def test_face_view_paints_like_render():
    v, f = tessellate(cq.Workplane("XY").box(60, 40, 20).edges("|Z").fillet(5).val())
    v, f = np.asarray(v), np.asarray(f)
    a = np.asarray(render3d.render([(v, f, (0.5, 0.6, 0.7))], size=(300, 200), edges=False))
    view = render3d.face_view(v[f], size=(300, 200))
    b = np.asarray(render3d.paint(view, np.tile((0.5, 0.6, 0.7), (len(f), 1)), edges=False))
    assert (np.abs(a.astype(int) - b.astype(int)).sum(2) > 6).sum() < 0.002 * a.shape[0] * a.shape[1]


def test_flow_simulation_job_saves_the_run_with_pdf_and_video():
    from tests.test_rm_cost import add_part, project
    pid = add_part(project("FLOW"))
    j = client.post(f"/api/parts/{pid}/flow-simulation", json={"gates": 2}).json()
    assert j["status"] in ("queued", "running", "done")
    j = sim_jobs.wait(j["id"])
    assert j["status"] == "done", j
    assert client.get(f"/api/parts/{pid}/sim-jobs/{j['id']}").json()["pct"] == 100
    runs = client.get(f"/api/parts/{pid}/sim-runs").json()
    assert len(runs) == 1 and runs[0]["kind"] == "flow" and runs[0]["pdf"] and runs[0]["video"]
    run = client.get(f"/api/parts/{pid}/sim-runs/{runs[0]['id']}").json()
    assert len(run["summary"]["gates"]) == 2 and run["summary"]["results"]["clamp_t"] > 0
    pdf = client.get(f"/api/parts/{pid}/sim-runs/{runs[0]['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    vid = client.get(f"/api/parts/{pid}/sim-runs/{runs[0]['id']}/video")
    assert vid.status_code == 200 and len(vid.content) > 1000
    # the report of another program, kept with the runs
    r = client.post(f"/api/parts/{pid}/sim-runs/external", files={"file": ("moldflow.pdf", b"%PDF-1.4 test", "application/pdf")},
                    data={"program": "Moldflow", "note": "tool release"})
    assert r.status_code == 200, r.text
    bad = client.post(f"/api/parts/{pid}/sim-runs/external", files={"file": ("x.txt", b"x", "text/plain")})
    assert bad.status_code == 400
    runs = client.get(f"/api/parts/{pid}/sim-runs").json()
    assert [x["kind"] for x in runs] == ["external", "flow"] and runs[0]["title"] == "Moldflow report · tool release"
    assert client.delete(f"/api/parts/{pid}/sim-runs/{runs[0]['id']}").status_code == 200
    assert len(client.get(f"/api/parts/{pid}/sim-runs").json()) == 1
    assert client.post(f"/api/parts/{pid}/flow-simulation", json={"gates": 9}).status_code == 400


def test_analysis_video_job():
    from tests.test_rm_cost import add_part, project
    pid = add_part(project("VID"))
    j = sim_jobs.wait(client.post(f"/api/parts/{pid}/simulation/video-job").json()["id"])
    assert j["status"] == "done", j
    runs = client.get(f"/api/parts/{pid}/sim-runs").json()
    assert runs[0]["kind"] == "analysis_video" and runs[0]["video"]
    assert client.get(f"/api/parts/{pid}/sim-runs/{runs[0]['id']}/video").status_code == 200
