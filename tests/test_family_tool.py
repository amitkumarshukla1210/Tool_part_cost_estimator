"""Stage 68: family tools - one mould / die for 2-4 parts (same shot, or common die set with swap inserts)."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import family_tool, mould_db
from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def plastic_family(code="FA"):
    p = project(code)
    a = add_part(p, code=f"{code}-A")
    b = add_part(p, code=f"{code}-B")
    for pid in (a, b):
        assert client.post(f"/api/parts/{pid}/tool-cost", json={}).status_code == 200
    r = client.post("/api/families", json={"code": f"FAM-{code}", "name": "Covers", "members": [
        {"part_id": a, "cavities": 2}, {"part_id": b, "cavities": 1}]})
    assert r.status_code == 200, r.text
    return r.json(), a, b


def sheet_parts(code="FS"):
    p = project(code)
    ids = [add_part(p, "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage", f"{code}-{k}") for k in (1, 2)]
    for pid in ids:
        assert client.post(f"/api/parts/{pid}/tool-cost", json={}).status_code == 200
    return ids


def test_seed_adds_the_sheet_gap_rule_once():
    assert family_tool.seed() == 0          # shipped in the master data
    row = mould_db.sizing_rules("sheet_metal")[family_tool.SHEET_GAP]
    assert row["is_example"] and row["value"] > 0


def test_arrangements_try_every_turn_and_direction():
    a = family_tool.arrangements([(100, 50), (80, 40)], 10)
    assert len(a) == 8
    assert {(x["pocket_l"], x["pocket_w"]) for x in a} >= {(190, 50), (100, 100), (50 + 10 + 40, 100)}


def test_same_shot_mould_family_cost_shares_and_trace():
    fam, a, b = plastic_family()
    assert fam["part_type"] == "plastic" and fam["mode"] == "same_shot" and list(fam["modes"]) == ["same_shot"]
    tr = client.get(f"/api/families/{fam['id']}/trace").json()
    assert tr["stored"] is False and tr["cavities"] == 3 and not tr["missing"]
    n = tr["nodes"]
    assert all(i["node"] in n for x in n.values() for i in x.get("inputs", []))          # every step opens to its inputs
    # one family base, every other line is a part's own line (cavity inserts of both parts)
    bases = [ln for ln in tr["lines"] if ln.get("family_base")]
    assert len(bases) == 1 and {ln["member"] for ln in tr["lines"] if not ln.get("family_base")} == {"FA-A", "FA-B"}
    assert sum(1 for ln in tr["lines"] if ln["element"] == "Cavity insert (steel)") == 2
    # shot weight = Σ cavities × weight of each part
    w = {s["part_code"]: s["weight_g"] for s in tr["shares"]}
    assert n["shot_weight"]["value"] == pytest.approx((2 * w["FA-A"] + w["FA-B"]) / 1000)
    # share by weight × cavities: 2 : 1 for the same part twice
    pct = {s["part_code"]: s["pct"] for s in tr["shares"]}
    assert pct["FA-A"] == pytest.approx(200 / 3) and sum(pct.values()) == pytest.approx(100)
    assert sum(s["capex_inr"] for s in tr["shares"]) == pytest.approx(tr["capex_inr"])
    assert tr["saving_capex_inr"] == pytest.approx(sum(s["own"]["capex_inr"] for s in tr["shares"]) - tr["capex_inr"])
    assert tr["family_layout"]["pack"]["places"] and tr["example"]["any"]


def test_calculate_stores_versions_and_parts_take_their_share():
    fam, a, b = plastic_family("FB")
    own_a = client.get(f"/api/parts/{a}").json()["tool_capex_inr"]
    r = client.post(f"/api/families/{fam['id']}/calculate", json={}).json()
    assert r["stored"] and r["version"] == 1
    assert client.post(f"/api/families/{fam['id']}/calculate", json={}).json()["stored"] is False
    st = client.get(f"/api/families/{fam['id']}/status").json()
    assert st["outdated"] == "" and st["latest"]["version"] == 1
    v = st["latest"]
    share_a = next(s for s in v["shares"] if s["part_id"] == a)
    assert client.get(f"/api/parts/{a}").json()["tool_capex_inr"] == pytest.approx(share_a["capex_inr"])
    # recalculating the part's own tool keeps its family share in the register
    client.post(f"/api/parts/{a}/tool-cost", json={"reason": "again"})
    assert client.get(f"/api/parts/{a}").json()["tool_capex_inr"] == pytest.approx(share_a["capex_inr"])
    # switch to own tool and back
    client.put(f"/api/families/{fam['id']}/parts/{a}/use", json={"use_family": False})
    assert client.get(f"/api/parts/{a}").json()["tool_capex_inr"] == pytest.approx(own_a)
    assert client.get(f"/api/parts/{a}/family").json()["use_family"] is False
    client.put(f"/api/families/{fam['id']}/parts/{a}/use", json={"use_family": True})
    assert client.get(f"/api/parts/{a}").json()["tool_capex_inr"] == pytest.approx(share_a["capex_inr"])
    # typed share: 40 % for B, A gets the rest
    client.put(f"/api/families/{fam['id']}", json={"members": [{"part_id": a, "cavities": 2}, {"part_id": b, "cavities": 1, "share_pct": 40}]})
    assert "changed" in client.get(f"/api/families/{fam['id']}/status").json()["outdated"]
    assert client.post(f"/api/families/{fam['id']}/calculate", json={}).json()["version"] == 2
    sh = {s["part_id"]: s for s in client.get(f"/api/families/{fam['id']}").json()["versions"][0]["shares"]}
    assert sh[b]["pct"] == 40 and sh[b]["typed"] and sh[a]["pct"] == pytest.approx(60)
    # deleting the family gives the parts their own tool back
    client.delete(f"/api/families/{fam['id']}")
    assert client.get(f"/api/parts/{a}").json()["tool_capex_inr"] == pytest.approx(own_a)


def test_part_cost_uses_the_family_share_and_shared_machine_hour():
    fam, a, b = plastic_family("FC")
    for pid in (a, b):
        client.post(f"/api/parts/{pid}/rm-cost", json={})
    before = client.get(f"/api/parts/{a}/piece-cost").json()["live"]
    client.post(f"/api/families/{fam['id']}/calculate", json={})
    live = client.get(f"/api/parts/{a}/piece-cost").json()["live"]
    assert live["family"]["code"] == "FAM-FC" and live["family"]["pct"] == pytest.approx(200 / 3)
    inp = {i["variable"]: live["nodes"][i["node"]]["value"] for i in live["inputs"]}
    share = next(s for s in client.get(f"/api/families/{fam['id']}").json()["versions"][0]["shares"] if s["part_id"] == a)
    assert inp["cavities"] == 2 and inp["tool_cost"] == pytest.approx(share["cost_inr"])
    assert "fam:mhr" in live["nodes"] and inp["mhr"] == pytest.approx(live["nodes"]["fam:mhr"]["value"])
    assert live["nodes"]["fam:mhr"]["inputs"][0]["node"].startswith("mhr:")
    assert live["machine"] == client.get(f"/api/families/{fam['id']}/trace").json()["trial"]["machine"]["machine_id"]
    assert live["value"] != pytest.approx(before["value"])
    client.put(f"/api/families/{fam['id']}/parts/{a}/use", json={"use_family": False})
    own = client.get(f"/api/parts/{a}/piece-cost").json()["live"]
    assert "family" not in own and own["value"] == pytest.approx(before["value"])


def test_sheet_metal_same_stroke_and_swap_inserts():
    s1, s2 = sheet_parts()
    r = client.post("/api/families", json={"code": "FAM-S", "mode": "swap_inserts", "members": [{"part_id": s1}, {"part_id": s2}]}).json()
    assert r["part_type"] == "sheet_metal" and set(r["modes"]) == {"same_shot", "swap_inserts"}
    swap = client.get(f"/api/families/{r['id']}/trace").json()
    own = sum(s["own"]["capex_inr"] for s in swap["shares"])
    # the same part twice, every line common: the family die set costs one part's dies
    assert swap["capex_inr"] == pytest.approx(own / 2, rel=1e-6) and swap["saving_capex_inr"] == pytest.approx(own / 2, rel=1e-6)
    assert all(ln.get("common") for ln in swap["lines"])
    # tick one line "per part": it is counted for both parts
    key = next(k for k in swap["common"] if "punch" in k.lower())
    client.put(f"/api/families/{r['id']}", json={"common": {key: False}})
    ticked = client.get(f"/api/families/{r['id']}/trace").json()
    assert ticked["value_inr"] > swap["value_inr"]
    assert sum(1 for ln in ticked["lines"] if ln["line_key"] == key) == 2
    # same stroke: one die plate takes both work areas, force = Σ
    client.put(f"/api/families/{r['id']}", json={"mode": "same_shot", "common": {}})
    same = client.get(f"/api/families/{r['id']}/trace").json()
    d = same["dies"][0]
    assert len(d["parts"]) == 2 and d["pack"] and d["force_t"] > swap["dies"][0]["force_t"]
    assert same["value_inr"] > swap["value_inr"]


def test_rules_are_checked():
    fam, a, b = plastic_family("FD")
    p = project("FD2")
    s = add_part(p, "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage", "FD-S")
    bad = lambda body: client.post("/api/families", json=body)
    assert "one kind" in bad({"code": "X1", "members": [{"part_id": a}, {"part_id": s}]}).json()["detail"]
    c = add_part(p, code="FD-C")
    d = add_part(p, code="FD-D")
    assert "already in family" in bad({"code": "X3", "members": [{"part_id": a}, {"part_id": c}]}).json()["detail"]
    assert "2 to 4" in bad({"code": "X4", "members": [{"part_id": c}]}).json()["detail"]
    assert "not possible" in bad({"code": "X5", "mode": "swap_inserts", "members": [{"part_id": c}, {"part_id": d}]}).json()["detail"]
    assert "100 %" in bad({"code": "X6", "members": [{"part_id": c, "share_pct": 70}, {"part_id": d, "share_pct": 20}]}).json()["detail"]
    assert "already used" in bad({"code": "FAM-FD", "members": [{"part_id": c}, {"part_id": d}]}).json()["detail"]
    cands = client.get("/api/families/candidates", params={"part_type": "plastic"}).json()
    assert {x["part_code"] for x in cands} >= {"FD-C", "FD-A"} and next(x for x in cands if x["part_code"] == "FD-A")["family_id"] == fam["id"]


def test_outputs_pdf_excel_layout_and_pack():
    fam, a, b = plastic_family("FE")
    client.post(f"/api/families/{fam['id']}/calculate", json={})
    wb = load_workbook(io.BytesIO(client.get(f"/api/families/{fam['id']}/export.xlsx").content))
    assert wb.sheetnames[0] == "Family split" and "BOM & processes" in wb.sheetnames
    text = " ".join(str(c.value) for row in wb["Family split"].iter_rows() for c in row if c.value)
    assert "FE-A" in text and "per part" in text and "all rights reserved" in text     # stage 67 footer on every sheet
    for url in ("export.pdf", "layout.pdf"):
        assert client.get(f"/api/families/{fam['id']}/{url}").content[:4] == b"%PDF"
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/families/{fam['id']}/pack.zip").content))
    names = z.namelist()
    assert any(n.endswith("_family_layout_and_split.pdf") for n in names) and any(n.endswith(".xlsx") for n in names)
    assert "FAM-FE" in z.read("README.txt").decode()
    # the parts' own outputs do not change
    assert client.get(f"/api/parts/{a}/tool-cost/export.pdf").content[:4] == b"%PDF"
    assert client.get("/api/families").json()[0]["latest"]["version"] == 1
