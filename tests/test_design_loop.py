from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)
SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def move(pid, status, comment=""):
    return client.post(f"/api/parts/{pid}/status", json={"status": status, "comment": comment})


def test_status_flow_follows_the_rules_and_records_who_and_why():
    pid = add_part(project("DL"))
    loop = client.get(f"/api/parts/{pid}/design-loop").json()
    assert loop["status"] == "uploaded" and loop["next"] == ["concept_tool"]
    assert move(pid, "simulation").status_code == 400                 # skipping a step is refused
    assert move(pid, "concept_tool").status_code == 200
    move(pid, "simulation")
    r = move(pid, "corrections_required")
    assert r.status_code == 400 and "needs a comment" in r.json()["detail"]
    loop = move(pid, "corrections_required", "Add 1° draft on the side walls").json()
    last = loop["timeline"][-1]
    assert last["action"] == "status_changed" and last["old"] == "simulation" and last["new"] == "corrections_required"
    assert last["comment"] == "Add 1° draft on the side walls" and last["who"]
    assert [f["code"] for f in loop["flow"]][0] == "uploaded" and all(f["days"] >= 0 for f in loop["flow"])


def test_new_revision_moves_corrections_required_to_revised():
    pid = add_part(project("DL2"))
    for s, c in (("concept_tool", ""), ("simulation", ""), ("corrections_required", "thick boss")):
        assert move(pid, s, c).status_code == 200
    with open(SAMPLES / "plastic_cover.step", "rb") as fh:
        r = client.post(f"/api/parts/{pid}/revisions", files={"file": ("plastic_cover.step", fh)},
                        data={"rev": "B", "change_note": "boss cored out"})
    assert r.status_code == 200, r.text
    loop = client.get(f"/api/parts/{pid}/design-loop").json()
    assert loop["status"] == "revised" and loop["next"] == ["simulation"]
    assert loop["timeline"][-1]["comment"] == "new revision B uploaded"
    assert any(e["action"] == "revision_added" and e["rev"] == "B" for e in loop["timeline"])


def test_bad_status_code_in_setup_is_rejected():
    t = client.get("/api/register-setup").json()
    t["part_statuses"][0]["next_statuses"] = "no_such_status"
    r = client.put("/api/register-setup", json=t)
    assert r.status_code == 400 and "not a status code" in r.text


def test_step_back_to_a_forgotten_status_needs_a_comment():
    pid = add_part(project("DL3"))
    for s in ("concept_tool", "simulation"):
        assert move(pid, s).status_code == 200
    loop = client.get(f"/api/parts/{pid}/design-loop").json()
    assert loop["back"] == ["concept_tool", "uploaded"]                  # earlier statuses, nearest first
    r = move(pid, "concept_tool")
    assert r.status_code == 400 and "needs a comment" in r.json()["detail"]
    loop = move(pid, "concept_tool", "concept tool review forgotten").json()
    assert loop["status"] == "concept_tool" and loop["timeline"][-1]["step_back"] is True
    assert move(pid, "simulation").status_code == 200                     # and on again as normal
