"""Stage 55: cost change report of a project: part cost now vs the cost valid on a date, line by line."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import update

from backend.app import master_data
from backend.app import projects_db as db
from tests.test_rm_cost import add_part, client, project


def set_all(name, value):
    sheets = {k: [dict(r) for r in v] for k, v in master_data.tables().items()}
    next(r for r in sheets["Parameters"] if r["part_type"] == "all" and r["parameter"] == name)["value"] = value
    master_data.write(sheets)


def costed_part(p, code):
    pid = add_part(p, code=code)
    assert client.post(f"/api/parts/{pid}/tool-cost", json={}).status_code == 200
    assert client.post(f"/api/parts/{pid}/piece-cost", json={}).json()["stored"]
    return pid


def backdate(pid, version, when):
    with db.engine().begin() as conn:
        conn.execute(update(db.piece_costs).where((db.piece_costs.c.part_id == pid) & (db.piece_costs.c.version == version))
                     .values(created_at=when))


def test_change_since_a_date_line_by_line_and_flagged():
    p = project()
    pid = costed_part(p, "CC-1")
    backdate(pid, 1, datetime(2026, 1, 10, 9, 0))
    set_all("rejection_pct", 10)                                   # 2 % → 10 %
    assert client.post(f"/api/projects/{p['id']}/piece-cost/recalculate").json()["new_versions"] == 1
    c = client.get(f"/api/projects/{p['id']}/cost-changes", params={"since": "2026-06-01"}).json()
    r = next(x for x in c["rows"] if x["part_id"] == pid)
    assert r["status"] == "changed" and r["then"]["version"] == 1 and r["now"]["version"] == 2
    assert r["delta_inr"] == pytest.approx(r["now"]["cost_inr"] - r["then"]["cost_inr"])
    assert r["delta_pct"] == pytest.approx(r["delta_inr"] / r["then"]["cost_inr"] * 100)
    assert r["flagged"] == (abs(r["delta_pct"]) >= c["flag_pct"]) and r["flagged"]
    # the lines add up to the part cost of each version, and their changes to the total change
    assert sum(x["then_inr"] or 0 for x in r["lines"]) == pytest.approx(r["then"]["cost_inr"])
    assert sum(x["now_inr"] or 0 for x in r["lines"]) == pytest.approx(r["now"]["cost_inr"])
    assert sum(x["delta_inr"] for x in r["lines"]) == pytest.approx(r["delta_inr"])
    moved = {x["name"] for x in r["lines"] if abs(x["delta_inr"]) > 1e-9}
    assert "rejection_cost" in moved and "rm_cost" not in moved
    assert c["totals"]["changed"] == 1 and c["totals"]["flagged"] == 1 and c["rows"][0]["part_id"] == pid


def test_new_unchanged_and_without_cost():
    p = project()
    new = costed_part(p, "CC-2")
    old = costed_part(p, "CC-3")
    backdate(old, 1, datetime(2026, 1, 10, 9, 0))
    none = add_part(p, code="CC-4")
    c = client.get(f"/api/projects/{p['id']}/cost-changes", params={"since": "2026-06-01"}).json()
    by = {r["part_id"]: r for r in c["rows"]}
    assert by[new]["status"] == "new" and by[new]["then"] is None
    assert by[old]["status"] == "unchanged" and by[old]["delta_inr"] == 0 and not by[old]["flagged"]
    assert by[none]["status"] == "no_cost"
    assert c["totals"] == {"parts": 3, "changed": 0, "flagged": 0, "new": 1, "unchanged": 1, "no_cost": 1}


def test_threshold_and_default_date_come_from_master_data():
    p = project()
    costed_part(p, "CC-5")
    set_all("cost_change_lookback_days", 7)
    set_all("cost_change_flag_pct", 12)
    c = client.get(f"/api/projects/{p['id']}/cost-changes").json()
    assert c["since"] == (date.today() - timedelta(days=7)).isoformat() and c["flag_pct"] == 12
    assert client.get(f"/api/projects/{p['id']}/cost-changes", params={"since": "31-12-2026"}).status_code == 400
    assert client.get("/api/projects/99999/cost-changes").status_code == 400


def test_excel_and_pdf_downloads():
    """Stage 56: the same report as Excel (Summary, Parts, Cost lines) and PDF."""
    import io
    from openpyxl import load_workbook
    p = project()
    pid = costed_part(p, "CC-6")
    backdate(pid, 1, datetime(2026, 1, 10, 9, 0))
    set_all("rejection_pct", 10)
    client.post(f"/api/projects/{p['id']}/piece-cost/recalculate")
    x = client.get(f"/api/projects/{p['id']}/cost-changes.xlsx", params={"since": "2026-06-01"})
    assert x.status_code == 200 and "attachment" in x.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(x.content))
    assert {"Summary", "Parts", "Cost lines"} <= set(wb.sheetnames)
    parts = list(wb["Parts"].iter_rows(values_only=True))
    head, row = parts[0], next(r for r in parts[1:] if r[0] == "CC-6")
    c = client.get(f"/api/projects/{p['id']}/cost-changes", params={"since": "2026-06-01"}).json()
    r = next(r for r in c["rows"] if r["part_id"] == pid)
    assert row[head.index("Status")] == "Changed" and row[head.index("Highlighted")] == "⚑"
    assert row[head.index("Change (INR/part)")] == pytest.approx(r["delta_inr"])
    lines = [l for l in wb["Cost lines"].iter_rows(values_only=True) if l[0] == "CC-6"]
    assert sum(l[5] for l in lines) == pytest.approx(r["delta_inr"]) and any(l[6] == "yes" for l in lines)
    pdf = client.get(f"/api/projects/{p['id']}/cost-changes.pdf", params={"since": "2026-06-01"})
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert client.get(f"/api/projects/{p['id']}/cost-changes.pdf", params={"since": "bad"}).status_code == 400
