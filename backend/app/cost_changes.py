"""Cost change report of a project (roadmap stage 55): every part's cost now against the cost that was valid on a date.

    then     the latest stored part cost version made on or before the date (end of that day)
    now      the latest stored part cost version
    lines    the cost lines of the part cost, read from each version's own trace: the terms of the result formula, with every
             term that is itself only a sum of other steps (e.g. cost before profit) opened up. So the lines follow the
             Cost formulas of scope piece as they were when each version was made; nothing is listed here in code
    flag     |change| ≥ Parameters → all / cost_change_flag_pct (EXAMPLE): the row is highlighted and sorted first

Stored versions are never changed; the report only reads them. Parts of other tool groups are left out for a limited user.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime, timedelta

from sqlalchemy import and_, select

from . import master_data
from . import projects_db as db

SEED_PARAMETERS = {
    "cost_change_flag_pct": (5, "%", "EXAMPLE: part cost changes of at least this % (up or down) are highlighted in the project's "
                                     "cost change report (stage 55)"),
    "cost_change_lookback_days": (30, "days", "EXAMPLE: the cost change report compares with the part costs valid this many days "
                                              "ago unless you pick a date (stage 55)"),
}
_SUM = re.compile(r"\s*[A-Za-z_]\w*(\s*\+\s*[A-Za-z_]\w*)*\s*")


class ChangeError(ValueError):
    pass


def seed() -> int:
    """Add the report's Parameters rows that are missing (part type 'all'); existing rows are never changed."""
    sheets = {k: [dict(r) for r in v] for k, v in master_data.tables().items()}
    have = {(r["part_type"], r["parameter"]) for r in sheets["Parameters"]}
    add = [{"part_type": "all", "parameter": k, "value": v, "unit": u, "description": d}
           for k, (v, u, d) in SEED_PARAMETERS.items() if ("all", k) not in have]
    if add:
        sheets["Parameters"] += add
        master_data.write(sheets)
    return len(add)


def _param(name: str) -> float:
    v = master_data.parameters("all").get(name)
    if not isinstance(v, (int, float)) or v < 0:
        raise ChangeError(f"Master data → Parameters needs a number 'all / {name}' (the cost change report uses it).")
    return float(v)


def cost_lines(trace: dict) -> list[dict]:
    """[{name, label, value}] in the version's currency: the terms of the part cost formula, sums opened up."""
    nodes = trace.get("nodes") or {}
    root = nodes.get(trace.get("root") or "calc:piece_cost") or nodes.get("calc:piece_cost")
    if not root:
        return []
    out, seen = [], set()

    def visit(node: dict, name: str):
        if node["id"] in seen:
            return
        seen.add(node["id"])
        if node.get("kind") == "calculated" and _SUM.fullmatch(node.get("formula") or "") and node.get("inputs"):
            by_name = {i["name"]: i["node"] for i in node["inputs"]}
            for term in (t.strip() for t in node["formula"].split("+")):     # in the formula's own order
                if by_name.get(term) in nodes:
                    visit(nodes[by_name[term]], term)
            return
        out.append({"name": name, "label": node.get("label") or name, "value": float(node.get("value") or 0)})

    if root.get("kind") == "calculated" and _SUM.fullmatch(root.get("formula") or ""):
        visit(root, "piece_cost")
    return out


def _version(row) -> dict:
    fx = row["piece_cost_inr"] / row["piece_cost"] if row["piece_cost"] else 1.0
    return {"version": row["version"], "at": row["created_at"].isoformat(timespec="minutes"), "by": row["created_by"],
            "reason": row["reason"], "as_of": row["as_of"], "country": row["country"], "rev": row["rev"],
            "cost_inr": row["piece_cost_inr"], "is_example": bool((row["trace"] or {}).get("is_example")),
            "lines": {x["name"]: x | {"inr": x["value"] * fx} for x in cost_lines(row["trace"] or {})}}


def report(project_id: int, since: str | None = None) -> dict:
    from . import scope
    flag = _param("cost_change_flag_pct")
    if since:
        try:
            day = date.fromisoformat(since)
        except ValueError:
            raise ChangeError("The date must be written as YYYY-MM-DD.") from None
    else:
        day = date.today() - timedelta(days=_param("cost_change_lookback_days"))
    cut = datetime.combine(day, datetime.max.time())
    with db.engine().connect() as conn:
        proj = conn.execute(select(db.projects).where(db.projects.c.id == project_id)).mappings().first()
        if not proj:
            raise ChangeError(f"Project {project_id} does not exist.")
        sv = scope.project_view(conn, project_id)
        parts = [p for p in conn.execute(select(db.parts.c.id, db.parts.c.part_code, db.parts.c.name).where(
                 and_(db.parts.c.project_id == project_id, db.parts.c.is_assembly.is_(False))).order_by(db.parts.c.part_code)).mappings()
                 if sv["visible"] is None or p["id"] in sv["visible"]]
        rows_by_part: dict[int, list] = {}
        if parts:
            for r in conn.execute(select(db.piece_costs).where(db.piece_costs.c.part_id.in_([p["id"] for p in parts]))
                                  .order_by(db.piece_costs.c.part_id, db.piece_costs.c.version)).mappings():
                rows_by_part.setdefault(r["part_id"], []).append(r)
    rows = []
    for p in parts:
        vs = rows_by_part.get(p["id"], [])
        row = {"part_id": p["id"], "part_code": p["part_code"], "name": p["name"], "then": None, "now": None,
               "delta_inr": None, "delta_pct": None, "flagged": False, "lines": []}
        if not vs:
            rows.append(row | {"status": "no_cost"})
            continue
        now = vs[-1]
        then = next((v for v in reversed(vs) if v["created_at"] <= cut), None)
        row["now"] = _version(now)
        if then is None:
            rows.append(row | {"status": "new"})
            continue
        row["then"] = _version(then)
        a, b = row["then"]["cost_inr"] or 0.0, row["now"]["cost_inr"] or 0.0
        row["delta_inr"] = b - a
        row["delta_pct"] = (b - a) / a * 100 if a else None
        row["flagged"] = row["delta_pct"] is not None and abs(row["delta_pct"]) >= flag
        names = list(row["now"]["lines"]) + [n for n in row["then"]["lines"] if n not in row["now"]["lines"]]
        for n in names:
            o, w = row["then"]["lines"].get(n), row["now"]["lines"].get(n)
            row["lines"].append({"name": n, "label": (w or o)["label"], "then_inr": o["inr"] if o else None,
                                 "now_inr": w["inr"] if w else None, "delta_inr": (w["inr"] if w else 0) - (o["inr"] if o else 0)})
        status = "unchanged" if then["version"] == now["version"] or abs(row["delta_inr"]) < 1e-9 else "changed"
        rows.append(row | {"status": status})
    order = {"changed": 1, "new": 2, "unchanged": 3, "no_cost": 4}
    rows.sort(key=lambda r: (not r["flagged"], order[r["status"]], -abs(r["delta_pct"] or 0), r["part_code"]))
    for r in rows:
        for v in (r["then"], r["now"]):
            if v:
                v.pop("lines")
    count = lambda s: sum(r["status"] == s for r in rows)  # noqa: E731
    return {"project": {"id": proj["id"], "code": proj["code"], "name": proj["name"]}, "since": day.isoformat(),
            "flag_pct": flag, "rows": rows,
            "totals": {"parts": len(rows), "changed": count("changed"), "flagged": sum(r["flagged"] for r in rows),
                       "new": count("new"), "unchanged": count("unchanged"), "no_cost": count("no_cost")},
            "scope": {"limited": sv["limited"], "note": sv["note"]},
            "is_example": any(r["now"]["is_example"] for r in rows if r["now"])}


# ---------- downloads (stage 56): the same report as Excel and PDF; logo and name are added on the way out (stage 35) ----------

STATUS = {"changed": "Changed", "new": "New since the date", "unchanged": "Unchanged", "no_cost": "No part cost yet"}


def _shown(lines: list[dict]) -> list[dict]:
    """Cost lines worth printing: not ₹0 both then and now."""
    return [x for x in lines if abs(x["then_inr"] or 0) >= 0.005 or abs(x["now_inr"] or 0) >= 0.005]


def to_excel(project_id: int, since: str | None = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from .table_set import EXAMPLE_FILL, HEADER_FILL
    from .trace import EXAMPLE_WARNING
    c = report(project_id, since)
    p, t = c["project"], c["totals"]
    flag_fill = PatternFill("solid", fgColor="FDE2E1")
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    for row in ([["Cost change report", f"{p['code']} · {p['name']}"], ["Part costs compared with those valid on", c["since"]],
                 ["Made on", date.today().isoformat()], [f"Highlighted (⚑) at ± % or more", c["flag_pct"]],
                 ["Parts", t["parts"]], ["Changed", t["changed"]], ["  of which highlighted", t["flagged"]],
                 ["New since the date", t["new"]], ["Unchanged", t["unchanged"]], ["No part cost yet", t["no_cost"]]]
                + ([["Covers", c["scope"]["note"]]] if c["scope"]["limited"] else [])
                + ([["Example values", EXAMPLE_WARNING]] if c["is_example"] else [])):
        ws.append(row)
    ws["A1"].font = Font(bold=True)
    if c["is_example"]:
        for cell in ws[ws.max_row]:
            cell.fill = EXAMPLE_FILL
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 38, 60
    sheets = [
        ("Parts", ["Part", "Name", "Status", "Highlighted", f"Part cost on {c['since']} (INR)", "Version then", "Made then",
                   "Part cost now (INR)", "Version now", "Made now", "Change (INR/part)", "Change (%)", "Why (stored reason)", "By", "Rates of"],
         [[r["part_code"], r["name"], STATUS[r["status"]], "⚑" if r["flagged"] else "",
           (r["then"] or {}).get("cost_inr"), (r["then"] or {}).get("version"), (r["then"] or {}).get("at", "").replace("T", " "),
           (r["now"] or {}).get("cost_inr"), (r["now"] or {}).get("version"), (r["now"] or {}).get("at", "").replace("T", " "),
           r["delta_inr"], None if r["delta_pct"] is None else round(r["delta_pct"], 2),
           (r["now"] or {}).get("reason", ""), (r["now"] or {}).get("by", ""), (r["now"] or {}).get("as_of", "")] for r in c["rows"]]),
        ("Cost lines", ["Part", "Name", "Cost line", "Then (INR)", "Now (INR)", "Change (INR)", "Moved"],
         [[r["part_code"], r["name"], x["label"], x["then_inr"], x["now_inr"], x["delta_inr"], "yes" if abs(x["delta_inr"]) >= 0.005 else ""]
          for r in c["rows"] for x in _shown(r["lines"])]),
    ]
    for name, head, rows in sheets:
        ws = wb.create_sheet(name)
        ws.append(head)
        for cell in ws[1]:
            cell.font, cell.fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
        for r in rows:
            ws.append(r)
            if name == "Parts" and r[3]:
                for cell in ws[ws.max_row]:
                    cell.fill = flag_fill
        ws.freeze_panes = "A2"
        for col, h in zip(ws.columns, head):
            ws.column_dimensions[col[0].column_letter].width = max(10, min(40, len(str(h)) + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_pdf(project_id: int, since: str | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from .pdf_report import _example_banner, _table, _theme
    c = report(project_id, since)
    p, t = c["project"], c["totals"]
    theme, ss = _theme(), getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=18, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=11, spaceBefore=8, spaceAfter=4)
    note = ParagraphStyle("n", parent=ss["Normal"], textColor=theme["grey"], fontSize=7.5)
    rs = lambda x: "—" if x is None else f"{x:,.2f}"  # noqa: E731
    sg = lambda x: "—" if x is None else f"{x:+,.2f}"  # noqa: E731
    pc = lambda x: "—" if x is None else f"{x:+.1f} %"  # noqa: E731
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Design to Cost — Cost change report {p['code']}", author="Design to Cost")
    story = [Paragraph("COST CHANGE REPORT", ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8)),
             Paragraph(f"{p['code']} · {p['name']}", h1),
             Paragraph(f"Part cost now against the part cost valid on {c['since']} · made {date.today().isoformat()} · INR per part", note),
             Paragraph(f"<b>{t['changed']} changed</b> ({t['flagged']} by ±{c['flag_pct']:g} % or more, marked FLAG) · {t['new']} new since the date · "
                       f"{t['unchanged']} unchanged · {t['no_cost']} without a part cost", note)]
    if c["scope"]["limited"]:
        story.append(Paragraph(f"<b>{c['scope']['note']}</b>", note))
    if c["is_example"]:
        story += [Spacer(1, 2 * mm), _example_banner(ss)]
    head = [["Part", "Name", f"On {c['since']}", "Now", "Change", "Change %", "Flag", "Status"]]
    body = [[r["part_code"], r["name"][:40], rs((r["then"] or {}).get("cost_inr")), rs((r["now"] or {}).get("cost_inr")), sg(r["delta_inr"]),
             pc(r["delta_pct"]), "FLAG" if r["flagged"] else "", STATUS[r["status"]]] for r in c["rows"]]
    tbl = _table(head + body, theme, [32 * mm, 70 * mm, 28 * mm, 28 * mm, 26 * mm, 22 * mm, 12 * mm, 40 * mm])
    tbl.setStyle([("ALIGN", (1, 1), (1, -1), "LEFT"), ("ALIGN", (6, 1), (7, -1), "LEFT")])
    for i, r in enumerate(c["rows"], start=1):
        if r["flagged"]:
            tbl.setStyle([("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FDE2E1"))])
    story += [Paragraph("Parts", h2), tbl]
    moved = [r for r in c["rows"] if r["status"] == "changed"]
    if moved:
        story.append(Paragraph("Why: cost lines of the changed parts (INR per part)", h2))
        rows = [["Part", "Cost line", "Then", "Now", "Change"]]
        bold = []
        for r in moved:
            for x in _shown(r["lines"]):
                rows.append([r["part_code"], x["label"], rs(x["then_inr"]), rs(x["now_inr"]), sg(x["delta_inr"])])
                if abs(x["delta_inr"]) >= 0.005:
                    bold.append(len(rows) - 1)
        lt = _table(rows, theme, [40 * mm, 80 * mm, 30 * mm, 30 * mm, 30 * mm])
        lt.setStyle([("ALIGN", (1, 1), (1, -1), "LEFT")])
        for i in bold:
            lt.setStyle([("FONTNAME", (0, i), (-1, i), "Helvetica-Bold")])
        story.append(lt)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(f"FLAG = change of ±{c['flag_pct']:g} % or more (Master data > Parameters > all / cost_change_flag_pct). Each cost line is "
                           "read from that stored version's own trace; lines at INR 0 then and now are not shown. The report changes nothing.", note))
    doc.build(story)
    return buf.getvalue()
