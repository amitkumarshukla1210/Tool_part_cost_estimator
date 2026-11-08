"""Saved files with revisions (stage 47): every file made for a part is saved, handed out again at once while its data has
not changed (also after a restart), and made again as the next revision after a change; earlier revisions stay."""

from fastapi.testclient import TestClient

from backend.app import register
from backend.app.main import app
from tests.test_rm_cost import add_part, project

client = TestClient(app)


def _restart():
    """What closing and opening the app forgets: everything kept in memory."""
    with register._DESIGN_CACHE_LOCK:
        register._DESIGN_CACHE.clear()
    with register._SIMULATION_CACHE_LOCK:
        register._SIMULATION_CACHE.clear()
    register.clear_file_cache()


def test_a_file_is_saved_handed_out_again_and_revised_after_a_change():
    pid = add_part(project("SF1"), "plastic_cover.step", "ABS", "injection_moulding", "SF1-1")
    first = client.get(f"/api/parts/{pid}/rm-cost/export.pdf")
    assert first.status_code == 200 and first.headers["x-dtc-saved"] == "rev 1 (new)"
    again = client.get(f"/api/parts/{pid}/rm-cost/export.pdf")
    assert again.headers["x-dtc-saved"].startswith("rev 1 of") and again.content == first.content
    assert again.headers["content-disposition"] == first.headers["content-disposition"]
    files = client.get(f"/api/parts/{pid}/saved-files").json()["files"]
    f = next(x for x in files if x["key"] == "rm-cost/export.pdf")
    assert f["label"] == "RM cost sheet" and f["up_to_date"] and f["revisions"][0]["changed"] == "first issue"
    # a change of the part: the saved file is out of date, the next download is revision 2, revision 1 stays
    assert client.put(f"/api/parts/{pid}", json={"name": "Cover changed"}).status_code == 200
    f = next(x for x in client.get(f"/api/parts/{pid}/saved-files").json()["files"] if x["key"] == "rm-cost/export.pdf")
    assert not f["up_to_date"]
    second = client.get(f"/api/parts/{pid}/rm-cost/export.pdf")
    assert second.headers["x-dtc-saved"] == "rev 2 (new)"
    f = next(x for x in client.get(f"/api/parts/{pid}/saved-files").json()["files"] if x["key"] == "rm-cost/export.pdf")
    assert [v["rev_no"] for v in f["revisions"]] == [2, 1] and f["up_to_date"]
    assert "part data" in f["revisions"][0]["changed"]
    old = client.get(f"/api/parts/{pid}/saved-files/{f['revisions'][1]['id']}")
    assert old.status_code == 200 and old.content == first.content and "_rev1." in old.headers["content-disposition"]
    assert client.get(f"/api/parts/{pid}/saved-files/999999").status_code == 404


def test_after_a_restart_the_tool_design_and_its_files_are_not_made_again(monkeypatch):
    pid = add_part(project("SF2"), "plastic_cover.step", "ABS", "injection_moulding", "SF2-1")
    assert client.get(f"/api/parts/{pid}/tool-design").status_code == 200
    pdf = client.get(f"/api/parts/{pid}/tool-design.pdf")
    piece = client.get(f"/api/parts/{pid}/piece-cost").json()
    _restart()

    def no(*a, **k):
        raise AssertionError("made again after the restart")
    monkeypatch.setattr(register, "_tool_designs_build", no)
    from backend.app import simulation, tool_drawings
    monkeypatch.setattr(simulation, "run", no)
    monkeypatch.setattr(tool_drawings, "design_pdf", no)
    assert client.get(f"/api/parts/{pid}/tool-design").status_code == 200        # 3D design from the disk
    assert client.get(f"/api/parts/{pid}/piece-cost").json() == piece              # simulation from the disk
    r = client.get(f"/api/parts/{pid}/tool-design.pdf")
    assert r.content == pdf.content and r.headers["x-dtc-saved"].startswith("rev 1 of")


def test_saved_for_every_part_type_and_cache_busters_do_not_make_new_files():
    pid = add_part(project("SF3"), "sheet_metal_bracket.step", "Mild steel CRCA / HR", "sheet_metal_multistage", "SF3-1")
    r = client.get(f"/api/parts/{pid}/drawing.pdf?t=1")
    assert r.status_code == 200 and r.headers["x-dtc-saved"] == "rev 1 (new)"
    assert client.get(f"/api/parts/{pid}/drawing.pdf?t=2").headers["x-dtc-saved"].startswith("rev 1 of")
    keys = [f["key"] for f in client.get(f"/api/parts/{pid}/saved-files").json()["files"]]
    assert keys == ["drawing.pdf"]
    # JSON answers and errors are not saved
    assert client.get(f"/api/parts/{pid}/rm-cost").status_code == 200
    assert client.get(f"/api/parts/{pid}/tool-design.xyz").status_code == 404
    assert [f["key"] for f in client.get(f"/api/parts/{pid}/saved-files").json()["files"]] == ["drawing.pdf"]
