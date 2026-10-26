"""Stage 33: the production machine of the tool: asked before the design, checked against it, or recommended."""

from fastapi.testclient import TestClient

from backend.app import mould_db
from backend.app.main import app
from tests.test_drawing_data import bracket, pdf_text
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def cover(code):
    return add_part(project(code), "plastic_cover.step", "ABS", "injection_moulding", f"{code}-1")


def test_machine_form_and_catalogue_per_family():
    m = client.get(f"/api/parts/{cover('MS1')}/machine").json()
    assert m["family"] == "moulding" and not m["asked"] and m["spec"] is None
    assert {"tonnage_t", "tie_bar_h_mm", "min_height_mm", "opening_stroke_mm"} <= {f["key"] for f in m["fields"]}
    assert m["catalog"] and all(x["machine_id"].startswith("IMM") for x in m["catalog"])
    assert client.get(f"/api/parts/{bracket('MS2')}/machine").json()["family"] == "press"
    plain = add_part(project("MS3"), "plate_with_hole.step", "Mild steel CRCA / HR", "machined", "MS3-1")
    assert client.get(f"/api/parts/{plain}/machine").status_code == 400
    assert {r["parameter"] for r in mould_db.tables()["design_rules"]} >= {"rec_tonnage_margin_pct", "rec_platen_margin_mm"}


def test_typed_machine_is_saved_and_cleaned():
    pid = cover("MS4")
    r = client.put(f"/api/parts/{pid}/machine", json={"spec": {"tonnage_t": "250", "tie_bar_h_mm": 560, "junk": 3}})
    assert r.status_code == 200 and r.json()["spec"] == {"tonnage_t": 250.0, "tie_bar_h_mm": 560.0} and r.json()["asked"]
    assert client.put(f"/api/parts/{pid}/machine", json={"spec": {"tonnage_t": "abc"}}).status_code == 400
    assert client.put(f"/api/parts/{pid}/machine", json={"spec": {"min_height_mm": 700, "max_height_mm": 600}}).status_code == 400
    assert client.put(f"/api/parts/{pid}/machine", json={"spec": {"machine_id": "NOPE"}}).status_code == 400
    r = client.put(f"/api/parts/{pid}/machine", json={"spec": {"machine_id": "IMM-250"}})
    assert r.json()["spec"]["tonnage_t"] == 250 and r.json()["spec"]["tie_bar_h_mm"] == 560      # filled from the list
    r = client.put(f"/api/parts/{pid}/machine", json={"spec": None, "skipped": True})
    assert r.json()["skipped"] and r.json()["spec"] is None


def test_skipped_machine_is_recommended():
    pid = cover("MS5")
    client.put(f"/api/parts/{pid}/machine", json={"spec": None, "skipped": True})
    r = client.get(f"/api/parts/{pid}/machine-check").json()
    rec, tool = r["recommended"]["values"], r["tools"][0]
    assert rec["tonnage_t"] >= tool["force_t"] and rec["tie_bar_h_mm"] > max(tool["length_mm"], tool["width_mm"])
    assert rec["min_height_mm"] < tool["height_mm"] < rec["max_height_mm"] and rec["opening_stroke_mm"] > 0
    assert r["recommended"]["nearest"]["tonnage_t"] >= rec["tonnage_t"] and r["check"] == [] and "No machine typed" in r["note"]


def test_typed_machine_is_checked_with_advice_and_noted_on_the_drawings():
    pid = cover("MS6")
    tool = client.get(f"/api/parts/{pid}/machine-check").json()["tools"][0]
    client.put(f"/api/parts/{pid}/machine", json={"spec": {"tonnage_t": 5, "tie_bar_h_mm": 2000, "tie_bar_v_mm": 2000,
                                                           "min_height_mm": tool["height_mm"] + 40, "max_height_mm": 900}})
    r = client.get(f"/api/parts/{pid}/machine-check").json()
    by = {c["what"]: c for c in r["check"]}
    assert not by["Tonnage"]["ok"] and by["Tie bars / bolster"]["ok"] and not r["fits"]
    assert not by["Smallest height"]["ok"] and "riser" in by["Smallest height"]["advice"] and "40 mm" in by["Smallest height"]["advice"]
    text = pdf_text(client.get(f"/api/parts/{pid}/tool-design.pdf").content)
    assert "Machine check" in text
    client.put(f"/api/parts/{pid}/machine", json={"spec": {"tonnage_t": 400, "tie_bar_h_mm": 2000, "tie_bar_v_mm": 2000}})
    assert client.get(f"/api/parts/{pid}/machine-check").json()["fits"]


def test_press_check_for_a_die():
    pid = bracket("MS7")
    client.put(f"/api/parts/{pid}/machine", json={"spec": {"tonnage_t": 30, "bolster_l_mm": 1000, "bolster_w_mm": 600}})
    r = client.get(f"/api/parts/{pid}/machine-check").json()
    assert len(r["tools"]) == 3
    blank = [c for c in r["check"] if c["tool"].startswith("Die 1") and c["what"] == "Tonnage"][0]
    assert not blank["ok"]                                  # blanking needs about 62 t
