"""Stage 45: real FEA (Gmsh + CalculiX) of the load-carrying tool parts; rules in master data; stored runs; review facts."""

import cadquery as cq
import pytest
from fastapi.testclient import TestClient

from backend.app import fea, mould_db, sim_jobs
from backend.app.main import app
from tests.test_drawing_data import bracket
from tests.test_rm_cost import add_part, project

client = TestClient(app)
needs_programs = pytest.mark.skipif(not fea.available()["available"], reason="Gmsh and CalculiX are not installed on this computer")


def run_job(pid):
    """Start the background FEA job, wait for it, return the stored runs of the current revision."""
    r = client.post(f"/api/parts/{pid}/fea")
    assert r.status_code == 200, r.text
    j = sim_jobs.wait(r.json()["id"], timeout=1500)
    assert j["status"] == "done", j.get("error")
    assert client.get(f"/api/parts/{pid}/sim-jobs/{j['id']}").json()["pct"] == 100
    return [p["run"] | {"tool": t["name"], "name": p["name"]} for t in client.get(f"/api/parts/{pid}/fea").json()["tools"] for p in t["parts"]]


def cover(code):
    return add_part(project(code), "plastic_cover.step", "ABS", "injection_moulding", f"{code}-1")


def test_rules_are_master_data_and_seed_adds_only_missing_rows():
    assert not fea.seed()
    r = fea.rules("plastic")
    assert r["is_example"] and r["fea_e_mpa"] > 0 and "cavity insert" in r["parts"] and "b plate (core side)" in r["parts"]
    assert fea.rules("sheet_metal")["parts"] == ["die plate", "bottom shoe"]
    d = mould_db.tables()
    d["design_rules"] = [x for x in d["design_rules"] if not (x["part_type"] == "plastic" and x["parameter"] == "fea_mesh_mm")]
    mould_db.write(d)
    with pytest.raises(fea.FeaError, match="fea_mesh_mm"):
        fea.rules("plastic")


def test_missing_programs_say_how_to_install(monkeypatch):
    monkeypatch.setattr(fea, "ccx_path", lambda: None)
    a = fea.available()
    assert not a["available"] and "CalculiX" in a["message"] and "DTC_Install_FEA.bat" in a["message"]
    pid = cover("FE0")
    assert client.get(f"/api/parts/{pid}/fea").json()["programs"]["available"] is False
    r = client.post(f"/api/parts/{pid}/fea")
    assert r.status_code == 400 and "not available" in r.json()["detail"]


@needs_programs
def test_plate_on_two_strips_agrees_with_beam_theory():
    L, W, H, F, strip = 300.0, 200.0, 30.0, 100000.0, 20.0
    R = fea.rules("plastic") | {"fea_mesh_mm": 8.0}
    r = fea.check_part(cq.Workplane("XY").box(L, W, H, centered=False).val(), (L, W, H), F, (L, W), strip, R)
    span = W - 2 * strip                                                         # clear span between the support strips
    q = F * span / W / span                                                      # load on the span, per mm
    beam = 5 * q * span ** 4 / (384 * R["fea_e_mpa"] * L * H ** 3 / 12)
    assert 0.5 * beam < r["max_deflection_mm"] < 1.5 * beam and r["png"][:4] == b"\x89PNG" and r["support"] == "two edge strips"
    full = fea.check_part(cq.Workplane("XY").box(L, W, H, centered=False).val(), (L, W, H), F, (L, W), None, R)
    assert full["max_deflection_mm"] < r["max_deflection_mm"] / 3                  # sitting on its full face it hardly bends


@needs_programs
def test_mould_run_is_stored_and_read_by_the_review():
    pid = cover("FE1")
    before = {x["item"]: x for x in client.get(f"/api/parts/{pid}/tool-review").json()["tools"][0]["rows"]}
    assert before["Strength check (FEA) of the load-carrying parts is within its limits"]["status"] == "issue"
    runs = run_job(pid)
    assert {x["name"] for x in runs} == {"Cavity insert", "Core insert", "B plate (core side)"}
    b = next(x for x in runs if x["name"].startswith("B plate"))
    assert b["support"] == "two edge strips" and b["force_n"] > 0 and "clamp force" in b["load_source"]
    cav = next(x for x in runs if x["name"] == "Cavity insert")
    assert cav["support"] == "full back face (top)" and 10 < cav["pressure_mpa"] < 200        # its moulding face points down
    # audit: the core insert's Ø3 mm boss pins were one element thick and bent 1.7 mm sideways (906 MPa); fea_mesh_per_circle
    # gives them several elements: about 0.012 mm and 125 MPa, like a solid steel insert on its full back face
    core = next(x for x in runs if x["name"] == "Core insert")
    assert core["max_deflection_mm"] < 0.05 and core["max_von_mises_mpa"] < 300 and core["support"] == "full back face (bottom)"
    assert client.get(f"/api/parts/{pid}/fea/{b['id']}.png").content[:4] == b"\x89PNG"
    s = client.get(f"/api/parts/{pid}/fea").json()
    assert all(p["run"] for t in s["tools"] for p in t["parts"])
    f = client.get(f"/api/parts/{pid}/tool-review").json()["tools"][0]["facts"]
    assert f["fea_targets"] == 3 and f["fea_checked"] == 3 and f["fea_bad"] == sum(1 for x in runs if not x["ok"])


@needs_programs
def test_sheet_metal_die_plate_and_bottom_shoe():
    pid = bracket("FE2")
    runs = run_job(pid)
    names = {x["name"] for x in runs}
    assert "Die plate" in names and any(x.startswith("Bottom shoe") for x in names) and all("press force" in x["load_source"] for x in runs)


def test_static_solver_first_and_a_broken_one_is_skipped(tmp_path, monkeypatch):
    """Windows download of CalculiX 2.22: ccx_dynamic.exe misses mkl_rt.2.dll; ccx_static.exe runs and is the one used."""
    folder = tmp_path / "tools" / "calculix" / "calculix_2.22_4win"
    folder.mkdir(parents=True)
    for name, body in (("ccx_dynamic.exe", "exit 1"), ("ccx_static.exe", "echo 'This is Version 2.22'")):
        (folder / name).write_text(f"#!/bin/sh\n{body}\n")
        (folder / name).chmod(0o755)
    monkeypatch.setenv("DTC_DATA_FOLDER", str(tmp_path))
    monkeypatch.delenv("DTC_CCX", raising=False)
    monkeypatch.setattr(fea.shutil, "which", lambda name: None)
    cands = fea.candidates()
    assert cands[0].endswith("ccx_static.exe") and fea.ccx_path().endswith("ccx_static.exe")
    (folder / "ccx_static.exe").unlink()
    assert fea.ccx_path() is None
    a = fea.available()
    assert not a["available"] and "does not start" in a["message"] and "ccx_dynamic.exe" in a["message"]


def test_a_mesh_calculix_refuses_is_made_again(monkeypatch):
    """Stage 46: a distorted element (nonpositive jacobian) next to a cooling hole: the next Gmsh attempt is used, not an estimate."""
    calls = []

    def fake(shape, size, force_n, patch, strip, R, title="", start=0, used=None):
        calls.append(start)
        used.append(start)
        if start < 2:
            raise fea.FeaError("CalculiX stopped:  *ERROR in e_c3d: nonpositive jacobian")
        return {"ok": True, "start": start}
    monkeypatch.setattr(fea, "_check_part", fake)
    assert fea.check_part(None, (1, 1, 1), 1.0, (1, 1), None, {})["start"] == 2 and calls == [0, 1, 2]
    monkeypatch.setattr(fea, "_check_part", lambda *a, **k: (_ for _ in ()).throw(fea.FeaError("CalculiX stopped: other")))
    with pytest.raises(fea.FeaError, match="other"):
        fea.check_part(None, (1, 1, 1), 1.0, (1, 1), None, {})


@needs_programs
def test_a_mesh_above_fea_max_elements_stops_before_the_solver(monkeypatch):
    """Audit after stage 56: a fine mesh of a mould plate needed 6 GB in the direct solver and stopped the PC; now the mesh is
    counted first and a mesh above Design rules → fea_max_elements stops with a message, without a finer try or the solver."""
    calls = []
    real = fea.subprocess.run
    monkeypatch.setattr(fea.subprocess, "run", lambda cmd, *a, **k: calls.append(cmd) or real(cmd, *a, **k))
    R = fea.rules("plastic") | {"fea_mesh_mm": 8.0, "fea_max_elements": 500}
    with pytest.raises(fea.FeaError, match=r"more than fea_max_elements \(500"):
        fea.check_part(cq.Workplane("XY").box(300, 200, 30, centered=False).val(), (300, 200, 30), 1e5, (300, 200), 20.0, R)
    assert len(calls) == 1 and "-c" in calls[0]                       # one Gmsh run, no finer attempt, no CalculiX
    assert fea.rules("plastic")["fea_max_elements"] == 250000


@needs_programs
def test_iterative_solver_is_used():
    assert "*STATIC, SOLVER=ITERATIVE CHOLESKY" in fea._inp({1: (0, 0, 0), 2: (1, 0, 0)}, [], [1], (1, 2), {2: 1.0}, 210000, 0.3)
