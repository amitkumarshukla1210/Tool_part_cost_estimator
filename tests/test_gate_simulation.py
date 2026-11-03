"""Stage 46: the flow simulation runs on the gate of the mould design (Mould systems), mapped back to the part model."""

import math

from fastapi.testclient import TestClient

from backend.app import register
from backend.app.main import app
from tests.test_mould_systems import _design, _rows
from tests.test_rm_cost import add_part, project

client = TestClient(app)

def test_design_points_map_back_to_the_part_model():
    import cadquery as cq
    from backend.app import mould_design
    from tests.test_rm_cost import SAMPLES
    shape = cq.importers.importStep(str(SAMPLES / "plastic_cover.step")).val()
    for axis in ("z", "y", "x"):
        sp = mould_design.split_core_cavity(shape, axis, 0.005, 300, 300, 30)
        vs = [v.toTuple() for v in sp["part"].Vertices()]
        for v in shape.Vertices()[:12]:
            p = v.toTuple()
            q = mould_design.to_design(p, sp["ops"])
            assert min(math.dist(q, w) for w in vs) < 1e-3                       # the forward map is the design's own move
            assert math.dist(mould_design.to_model(q, sp["ops"]), p) < 1e-6      # and it maps back


def test_flow_simulation_runs_on_the_designed_gate():
    pid = add_part(project("MSF1"), "plastic_cover.step", "ABS", "injection_moulding", "MSF1-1")
    client.put(f"/api/parts/{pid}/cavities", json={"cavities": 2})
    gd = register.design_gates(pid)
    des = _design(pid)
    assert gd["per_cavity"] == _rows(des)["gates"]["value"] and gd["thk_mm"] == _rows(des)["gate_thk"]["value"]
    run = register.sim_run(pid, register.flow_simulation_run(pid, video=False))
    sm = run["summary"]
    assert sm["settings"]["gate_from"] == "design" and sm["gate_note"].startswith("gate(s) of the mould design")
    g = sm["gate_design"]
    assert g["thk_mm"] == gd["thk_mm"] and g["width_mm"] == gd["width_mm"] and g["shear_1_s"] > 0 and g["freeze_s"] > 0
    q = sm["results"]["shot_volume_cm3"] * 1000 / 2 / gd["per_cavity"] / sm["results"]["fill_time_s"]
    assert abs(g["shear_1_s"] - 6 * q / (g["width_mm"] * g["thk_mm"] ** 2)) / g["shear_1_s"] < 1e-6
    # the gate face the solver used is at the designed gate (within a few mm of the model point)
    assert math.dist(sm["gates"][0]["at_mm"], gd["points"][0]) < max(10.0, des["systems"]["facts"]["wall_mm"] * 5)
    # the solver's own gate when asked
    run = register.sim_run(pid, register.flow_simulation_run(pid, video=False, gate_from="auto"))
    assert run["summary"]["settings"]["gate_from"] == "found by the solver" and "gate_design" not in run["summary"]
