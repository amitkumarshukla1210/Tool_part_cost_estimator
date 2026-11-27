"""Family tools (roadmap stage 68): stored families, their cost versions, the switch per part and the outputs.

A family groups 2-4 parts of one tool group (moulds: same shot; sheet metal: same stroke or swap inserts) under one
code. Calculating it stores a numbered version (like a part's tool cost) with the share of every part. A part whose
switch is "family tool" (default) then takes its share of the family tool cost and CAPEX in the part register,
Dashboard and part cost; with the switch on "own tool" it keeps its own single tool. A part is in one family at most.
"""

from __future__ import annotations

import io
import json
import zipfile

from sqlalchemy import select

from . import family_tool, register, register_setup, tool_cost
from . import projects_db as db
from .family_tool import FamilyError

FIELDS = ("code", "name", "mode", "country", "members", "common", "bom", "notes")


def _part_type(d: dict) -> str:
    proc = register_setup.processes().get(d.get("process") or "")
    return proc["part_type"] if proc else ""


def _row(conn, fid: int) -> dict:
    r = conn.execute(select(db.tool_families).where(db.tool_families.c.id == fid)).mappings().first()
    if not r:
        raise FamilyError(f"There is no family tool {fid}.")
    return register._plain(r)


def _versions(conn, fid: int) -> list[dict]:
    c = db.family_costs.c
    rows = conn.execute(select(c.id, c.version, c.country, c.currency, c.as_of, c.tool_cost, c.tool_cost_inr, c.tool_capex_inr,
                               c.shares, c.example, c.reason, c.created_by, c.created_at, c.key)
                        .where(c.family_id == fid).order_by(c.version.desc())).mappings().all()
    return [register._plain(r) for r in rows]


def _family_input(row: dict) -> dict:
    return {"part_type": row["part_type"], "mode": row["mode"], "country": row["country"] or None,
            "members": row["members"] or [], "common": row["common"] or {}, "bom": row["bom"] or {}}


def _stable(key: dict) -> dict:
    """The key without costing months (a new month alone is not a change while the same rate versions are used)."""
    k = json.loads(json.dumps(key, default=str))
    for m in k.get("members") or []:
        (m.get("key") or {}).pop("as_of", None)
    return k


def list_families() -> list[dict]:
    with db.engine().connect() as conn:
        rows = [register._plain(r) for r in conn.execute(select(db.tool_families).order_by(db.tool_families.c.code)).mappings()]
        codes = dict(conn.execute(select(db.parts.c.id, db.parts.c.part_code)).all())
        for r in rows:
            v = _versions(conn, r["id"])
            r["latest"] = {k: v[0][k] for k in ("version", "tool_cost_inr", "tool_capex_inr", "as_of", "country")} if v else None
            for m in r["members"] or []:
                m["part_code"] = codes.get(int(m["part_id"]), "?")
    from . import scope
    g = scope.groups()
    return [r for r in rows if g is None or r["part_type"] in g]


def get(fid: int) -> dict:
    with db.engine().connect() as conn:
        row = _row(conn, fid)
        row["versions"] = _versions(conn, fid)
    for m in row["members"] or []:
        try:
            d = register.part_detail(int(m["part_id"]), with_rm=False)
            m |= {"part_code": d["part_code"], "name": d["name"], "material": d["material"], "process": d["process"],
                  "project_id": d["project_id"]}
        except register.RegisterError:
            m |= {"part_code": "?", "name": "(part deleted)"}
    row["modes"] = {k: family_tool.MODES[k] for k in family_tool.modes_for(row["part_type"])}
    return row


def candidates(part_type: str = "", q: str = "") -> list[dict]:
    """Parts that can join a family tool: tooled parts of a family-capable type, not an assembly, not in another family."""
    taken = in_family()
    out = []
    with db.engine().connect() as conn:
        rows = conn.execute(select(db.parts.c.id, db.parts.c.part_code, db.parts.c.name, db.parts.c.process, db.parts.c.material,
                                   db.parts.c.is_assembly, db.parts.c.project_id).order_by(db.parts.c.part_code)).mappings().all()
    for r in rows:
        pt = _part_type(r)
        if r["is_assembly"] or not family_tool.modes_for(pt) or (part_type and pt != part_type):
            continue
        if q and q.lower() not in f"{r['part_code']} {r['name']}".lower():
            continue
        out.append({"id": r["id"], "part_code": r["part_code"], "name": r["name"], "part_type": pt, "material": r["material"],
                    "project_id": r["project_id"], "family_id": taken.get(r["id"])})
    return out


def in_family() -> dict:
    """{part id: family id} of every part that is in a family tool."""
    with db.engine().connect() as conn:
        rows = conn.execute(select(db.tool_families.c.id, db.tool_families.c.members)).all()
    return {int(m["part_id"]): fid for fid, members in rows for m in (members or [])}


def save(data: dict, fid: int | None = None) -> dict:
    """Create (fid None) or change a family tool. The part type comes from the parts; every part must have it."""
    data = {k: data[k] for k in FIELDS if k in data}
    with db.engine().connect() as conn:
        old = _row(conn, fid) if fid else None
    cur = (old or {}) | data
    code = str(cur.get("code") or "").strip()
    if not code:
        raise FamilyError("Give the family tool a code (e.g. FAM-001).")
    members = []
    for m in cur.get("members") or []:
        if not m.get("part_id"):
            continue
        pct = m.get("share_pct")
        members.append({"part_id": int(m["part_id"]), "cavities": int(m["cavities"]) if m.get("cavities") not in (None, "", 0) else None,
                        "share_pct": float(pct) if pct not in (None, "") else None,
                        "use_family": bool(m.get("use_family", True))})
    types = set()
    for m in members:
        try:
            d = register.part_detail(m["part_id"], with_rm=False)
        except register.RegisterError:
            raise FamilyError(f"Part {m['part_id']} does not exist.") from None
        why = register.tool_eligibility(d)
        if why:
            raise FamilyError(f"{d['part_code']}: {why}")
        pt = _part_type(d)
        if not family_tool.modes_for(pt):
            raise FamilyError(f"{d['part_code']}: {pt.replace('_', ' ')} parts cannot share a family tool "
                              f"(moulds: {', '.join(family_tool.MOULD_TYPES)}; sheet metal).")
        types.add(pt)
        if m["cavities"] is not None and not 1 <= m["cavities"] <= 64:
            raise FamilyError(f"{d['part_code']}: cavities must be 1 to 64.")
    if len(types) > 1:
        raise FamilyError("All parts of a family tool must be of one kind (found: " + ", ".join(sorted(types)) + ").")
    part_type = types.pop() if types else (old or {}).get("part_type") or ""
    taken = {pid: f for pid, f in in_family().items() if f != fid}
    for m in members:
        if m["part_id"] in taken:
            raise FamilyError(f"Part {m['part_id']} is already in family tool {taken[m['part_id']]}; a part is in one family at most.")
    mode = cur.get("mode") or (family_tool.modes_for(part_type) or [""])[0]
    family_tool.validate({"part_type": part_type, "mode": mode, "members": members})
    common = {str(k): bool(v) for k, v in (cur.get("common") or {}).items()}
    vals = {"code": code, "name": str(cur.get("name") or "").strip(), "part_type": part_type, "mode": mode,
            "country": str(cur.get("country") or "").upper().strip(), "members": members, "common": common,
            "bom": cur.get("bom") or {}, "notes": str(cur.get("notes") or "")}
    with db.engine().begin() as conn:
        dup = conn.execute(select(db.tool_families.c.id).where(db.tool_families.c.code == code)).scalar()
        if dup and dup != fid:
            raise FamilyError(f"Family tool code {code} is already used.")
        if fid:
            conn.execute(db.tool_families.update().where(db.tool_families.c.id == fid).values(**vals))
            register._log(conn, "family", fid, "family_tool_changed", {"code": code, "parts": [m["part_id"] for m in members]})
        else:
            fid = conn.execute(db.tool_families.insert().values(**vals, created_by=register.user())).inserted_primary_key[0]
            register._log(conn, "family", fid, "family_tool_created", {"code": code, "parts": [m["part_id"] for m in members]})
        for pid in {m["part_id"] for m in members} | {int(m["part_id"]) for m in (old or {}).get("members") or []}:
            sync_part(conn, pid)
    return get(fid)


def delete(fid: int) -> dict:
    with db.engine().begin() as conn:
        row = _row(conn, fid)
        conn.execute(db.family_costs.delete().where(db.family_costs.c.family_id == fid))
        conn.execute(db.tool_families.delete().where(db.tool_families.c.id == fid))
        register._log(conn, "family", fid, "family_tool_deleted", {"code": row["code"]})
        for m in row["members"] or []:
            sync_part(conn, int(m["part_id"]))
    return {"ok": True}


def set_use(fid: int, part_id: int, use: bool) -> dict:
    """The switch of one part: its part cost, CAPEX and Dashboard use the family tool (True) or its own tool (False)."""
    with db.engine().begin() as conn:
        row = _row(conn, fid)
        members = row["members"] or []
        if not any(int(m["part_id"]) == part_id for m in members):
            raise FamilyError(f"Part {part_id} is not in family tool {row['code']}.")
        for m in members:
            if int(m["part_id"]) == part_id:
                m["use_family"] = bool(use)
        conn.execute(db.tool_families.update().where(db.tool_families.c.id == fid).values(members=members))
        register._log(conn, "part", part_id, "tool_source_changed", {"family": row["code"], "uses": "family tool" if use else "own tool"})
        sync_part(conn, part_id)
    return get(fid)


def live(fid: int, country: str | None = None) -> dict:
    with db.engine().connect() as conn:
        row = _row(conn, fid)
    r = family_tool.run(_family_input(row), country)
    return r | {"family": {"id": fid, "code": row["code"], "name": row["name"]}, "version": None, "stored": False}


def status(fid: int) -> dict:
    """Latest version, and whether it is out of date (live run with today's rates, inputs and master data)."""
    with db.engine().connect() as conn:
        vs = _versions(conn, fid)
    out = {"latest": vs[0] if vs else None, "outdated": "", "problem": "", "live": None}
    try:
        r = live(fid)
    except (FamilyError, tool_cost.ToolCostError, register.RegisterError, ValueError) as exc:
        out["problem"] = str(exc)
        return out
    out["live"] = {k: r[k] for k in ("value", "value_inr", "capex_inr", "currency", "country", "as_of", "shares", "saving_capex_inr",
                                     "missing", "warnings", "base", "tools_count", "mode_label", "common", "example")}
    out["live"]["lines"] = [{k: ln.get(k) for k in ("element", "member", "common", "family_base", "total", "line_key", "family_key",
                                                    "die", "dropped", "category")} for ln in r["lines"]]
    if r["missing"]:
        out["problem"] = " ".join(r["missing"])
    elif not vs:
        out["outdated"] = "The family tool cost has not been calculated yet."
    elif not register._same_key(_stable(vs[0]["key"]), _stable(r["key"])):
        out["outdated"] = f"Parts, inputs, rates or master data changed since family tool version {vs[0]['version']}."
    return out


def compute(fid: int, reason: str = "calculated") -> dict:
    """Work out the family tool cost and store it as a new version unless nothing changed; update the parts."""
    r = live(fid)
    if r["missing"]:
        raise FamilyError("Family tool cost not stored: " + " ".join(r["missing"]))
    with db.engine().begin() as conn:
        row = _row(conn, fid)
        last = conn.execute(select(db.family_costs).where(db.family_costs.c.family_id == fid)
                            .order_by(db.family_costs.c.version.desc()).limit(1)).mappings().first()
        if last and register._same_key(_stable(last["key"]), _stable(r["key"])):
            return {"stored": False, "version": last["version"], "message": f"Family tool cost already up to date (version {last['version']})."}
        version = (last["version"] if last else 0) + 1
        conn.execute(db.family_costs.insert().values(
            family_id=fid, version=version, country=r["country"], currency=r["currency"], as_of=r["as_of"], key=r["key"],
            tool_cost=r["value"], tool_cost_inr=r["value_inr"], tool_capex_inr=r["capex_inr"], shares=r["shares"],
            example=r["example"], trace=json.loads(json.dumps(r, default=str)), reason=reason, created_by=register.user()))
        register._log(conn, "family", fid, "family_tool_calculated", {
            "code": row["code"], "version": version, "tool cost (INR)": round(r["value_inr"], 2),
            "CAPEX (INR)": round(r["capex_inr"], 2) if r["capex_inr"] is not None else None,
            "shares": {s["part_code"]: round(s["pct"], 2) for s in r["shares"]}})
        for s in r["shares"]:
            sync_part(conn, s["part_id"])
            register._log(conn, "part", s["part_id"], "family_share", {"family": row["code"], "version": version,
                                                                      "share %": round(s["pct"], 2), "CAPEX share (INR)": s["capex_inr"]})
    return {"stored": True, "version": version, "message": f"Family tool version {version} stored."}


def trace(fid: int, version: int | None = None) -> dict:
    with db.engine().connect() as conn:
        row = _row(conn, fid)
        q = select(db.family_costs).where(db.family_costs.c.family_id == fid)
        q = q.where(db.family_costs.c.version == version) if version is not None else q.order_by(db.family_costs.c.version.desc())
        v = conn.execute(q.limit(1)).mappings().first()
    if v is None:
        if version is not None:
            raise FamilyError(f"Family tool {row['code']} has no version {version}.")
        return live(fid)
    return v["trace"] | {"family": {"id": fid, "code": row["code"], "name": row["name"]}, "version": v["version"], "stored": True,
                         "created_by": v["created_by"], "created_at": v["created_at"].isoformat(timespec="seconds")}


# ---------- the parts ----------

def for_part(part_id: int, conn=None) -> dict | None:
    """The family tool of a part: {family, member, latest version, share} or None."""
    own = conn is None
    conn = conn or db.engine().connect()
    try:
        for fid, code, name, mode, members in conn.execute(select(db.tool_families.c.id, db.tool_families.c.code, db.tool_families.c.name,
                                                                  db.tool_families.c.mode, db.tool_families.c.members)).all():
            m = next((x for x in members or [] if int(x["part_id"]) == part_id), None)
            if not m:
                continue
            v = conn.execute(select(db.family_costs.c.version, db.family_costs.c.shares, db.family_costs.c.tool_cost_inr,
                                    db.family_costs.c.tool_capex_inr, db.family_costs.c.as_of)
                             .where(db.family_costs.c.family_id == fid).order_by(db.family_costs.c.version.desc()).limit(1)).mappings().first()
            share = next((s for s in (v["shares"] if v else []) if s["part_id"] == part_id), None)
            return {"family_id": fid, "code": code, "name": name, "mode": mode, "mode_label": family_tool.MODES.get(mode, mode),
                    "use_family": bool(m.get("use_family", True)), "member": m,
                    "version": v["version"] if v else None, "share": share,
                    "family_cost_inr": v["tool_cost_inr"] if v else None, "family_capex_inr": v["tool_capex_inr"] if v else None}
        return None
    finally:
        if own:
            conn.close()


def uses_family(part_id: int, conn=None) -> dict | None:
    """The family of the part when its switch is on "family tool" and the family has a calculated version, else None."""
    f = for_part(part_id, conn)
    return f if f and f["use_family"] and f["share"] else None


def sync_part(conn, part_id: int) -> None:
    """Keep the part register's tool cost / CAPEX columns on the tool the part uses (its family share or its own tool)."""
    f = uses_family(part_id, conn)
    if f:
        vals = {"tool_cost_inr": f["share"]["cost_inr"], "tool_capex_inr": f["share"]["capex_inr"]}
    else:
        last = conn.execute(select(db.tool_costs.c.id, db.tool_costs.c.tool_cost_inr, db.tool_costs.c.tool_capex_inr)
                            .where(db.tool_costs.c.part_id == part_id).order_by(db.tool_costs.c.version.desc()).limit(1)).mappings().first()
        vals = {"tool_cost_inr": last["tool_cost_inr"], "tool_capex_inr": last["tool_capex_inr"]} if last else \
            {"tool_cost_inr": None, "tool_capex_inr": None}
    conn.execute(db.parts.update().where(db.parts.c.id == part_id).values(**vals))


# ---------- outputs ----------

def _pseudo_part(tr: dict) -> dict:
    f = tr.get("family") or {}
    return {"part_code": f.get("code", "Family tool"), "name": (f.get("name") or "") + " (family tool)", "process": tr["mode_label"]}


def excel(fid: int, version: int | None = None) -> bytes:
    """The tool cost workbook of the family tool, with a first sheet "Family split" (parts, share %, ₹, own-tool saving)."""
    from openpyxl import load_workbook
    from openpyxl.styles import Font
    tr = trace(fid, version)
    data = register.tool_cost_excel(tr, _pseudo_part(tr))
    wb = load_workbook(io.BytesIO(data))
    ws = wb.create_sheet("Family split", 0)
    ws.append([f"Family tool {tr['family']['code']} · {tr['family']['name']} · {tr['mode_label']}"])
    ws.append([f"Tool cost {tr['value_inr']:,.0f} INR per tool · CAPEX {tr['capex_inr'] or 0:,.0f} INR · base {tr['base']['series']} "
               f"{tr['base']['size_code']} · version {tr.get('version') or 'live, not stored'} · {tr['country']} {tr['as_of']}"])
    ws.append([])
    head = ["Part", "Name", "Cavities", "Net weight (g)", "Share %", "Share typed", "Share of tool cost (INR)",
            "Share of CAPEX (INR)", "Own tool CAPEX (INR)", "Own tool cavities", "Uses"]
    ws.append(head)
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for s in tr["shares"]:
        own = s.get("own") or {}
        ws.append([s["part_code"], s["name"], s["cavities"], round(s["weight_g"], 2), round(s["pct"], 4), "yes" if s["typed"] else "by weight",
                   round(s["cost_inr"], 2), round(s["capex_inr"], 2) if s["capex_inr"] is not None else None,
                   round(own["capex_inr"], 2) if own.get("capex_inr") is not None else None, own.get("cavities"),
                   "family tool" if s["use_family"] else "own tool"])
    ws.append([])
    if tr.get("saving_capex_inr") is not None:
        ws.append(["CAPEX saving: own tools − family tool (INR)", round(tr["saving_capex_inr"], 2)])
    ws.append([])
    ws.append(["BOM line", "Part", "Common / per part", "Line total"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for ln in tr["lines"]:
        ws.append([(ln.get("die") + " · " if ln.get("die") else "") + ln["element"], ln.get("member") or "",
                   "family base" if ln.get("family_base") else ("common (counted once)" if ln.get("common") else "per part"),
                   round(ln["total"], 2)])
    for col, w in zip("ABCDEFGHIJK", (44, 30, 18, 14, 10, 12, 22, 22, 22, 16, 14)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def pdf(fid: int, version: int | None = None) -> bytes:
    """Family split page + layout drawing, then the full tool cost sheet of the family tool."""
    from pypdf import PdfReader, PdfWriter

    from .pdf_report import tool_cost_pdf
    tr = trace(fid, version)
    out = PdfWriter()
    for part in (layout_pdf(fid, version, tr), tool_cost_pdf(tr, _pseudo_part(tr))):
        for page in PdfReader(io.BytesIO(part)).pages:
            out.add_page(page)
    buf = io.BytesIO()
    out.write(buf)
    return buf.getvalue()


def layout_pdf(fid: int, version: int | None = None, tr: dict | None = None) -> bytes:
    """2D layout of the family tool: the parts' cavity blocks (moulds) or work areas (dies) on the base, with the split table."""
    from datetime import date

    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    tr = tr or trace(fid, version)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"Design to Cost — Family tool {tr['family']['code']}", author="Design to Cost")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=16, alignment=0, spaceAfter=2)
    note = ParagraphStyle("n", parent=ss["Normal"], fontSize=8, textColor=colors.HexColor("#6b7683"))
    palette = [colors.HexColor(c) for c in ("#2f6fdf", "#e07a1f", "#2a9d5b", "#b8418f")]
    story = [Paragraph("FAMILY TOOL · LAYOUT AND SPLIT", note),
             Paragraph(f"{tr['family']['code']} · {tr['family']['name'] or ''}", h1),
             Paragraph(f"{tr['mode_label']} · {tr['part_type'].replace('_', ' ')} · tool country {tr['country']} · {tr['as_of']} · "
                       + (f"version {tr['version']}" if tr.get("version") else "live preview, not stored") + f" · {date.today().isoformat()}", note),
             Spacer(1, 4 * mm)]
    colour = {s["part_code"]: palette[i % len(palette)] for i, s in enumerate(tr["shares"])}

    def plan(base_l, base_w, pocket_l, pocket_w, places, labels, title, max_w=120 * mm, max_h=80 * mm):
        k = min(max_w / base_l, max_h / base_w)
        d = Drawing(base_l * k + 4, base_w * k + 16)
        d.add(Rect(0, 12, base_l * k, base_w * k, strokeColor=colors.black, fillColor=colors.HexColor("#f4f6f8")))
        ox, oy = (base_l - pocket_l) / 2, (base_w - pocket_w) / 2
        d.add(Rect(ox * k, 12 + oy * k, pocket_l * k, pocket_w * k, strokeColor=colors.HexColor("#6b7683"), fillColor=None,
                   strokeDashArray=[3, 2]))
        for p, lab in zip(places, labels):
            c = colour.get(lab[0], palette[0])
            d.add(Rect((ox + p["x"]) * k, 12 + (oy + p["y"]) * k, p["l"] * k, p["w"] * k, strokeColor=c, fillColor=c, fillOpacity=0.25))
            d.add(String((ox + p["x"] + p["l"] / 2) * k, 12 + (oy + p["y"] + p["w"] / 2) * k, lab[1], fontSize=7, textAnchor="middle"))
        d.add(String(0, 2, title, fontSize=7))
        return d

    drawings = []
    fl = tr.get("family_layout") or {}
    if fl.get("pack"):
        b, a = fl["base"], fl["pack"]
        bl, bw = (b["width_mm"], b["length_mm"]) if fl.get("turned") else (b["length_mm"], b["width_mm"])
        labels = [(blk["label"], f"{blk['label']} · {blk['cavities']} cav ({blk['layout']['rows']}×{blk['layout']['cols']})")
                  for blk in fl["blocks"]]
        drawings.append(plan(bl, bw, a["pocket_l"], a["pocket_w"], a["places"], labels,
                             f"Base {b['series']} {b['size_code']} {bl:.0f} × {bw:.0f} mm · insert pocket {a['pocket_l']:.0f} × "
                             f"{a['pocket_w']:.0f} mm"))
    for die in fl.get("dies") or []:
        b, dp = die["base"], die["die_plate"]
        if die.get("pack"):
            a = die["pack"]
            places, pl, pw = a["places"], a["pocket_l"], a["pocket_w"]
        else:   # swap inserts: every part's work area on the same die set, one over the other
            places = [{"x": 0, "y": 0, "l": p["work_l"], "w": p["work_w"]} for p in die["parts"]]
            pl, pw = max(p["work_l"] for p in die["parts"]), max(p["work_w"] for p in die["parts"])
        labels = [(p["label"], f"{p['label']} · {p['die'].split(': ', 1)[-1]}") for p in die["parts"]]
        if not die.get("pack"):   # one over the other: one label naming every part, from the largest work area out
            joined = " / ".join(p["label"] for p in die["parts"]) + " · swap inserts"
            labels = [(lab[0], joined if i == 0 else "") for i, lab in enumerate(labels)]
        drawings.append(plan(max(b["length_mm"], dp["die_l"]), max(b["width_mm"], dp["die_w"]), pl, pw, places, labels,
                             f"{die['name']} · die set {b['series']} {b['size_code']} · die plate {dp['die_l']:.0f} × {dp['die_w']:.0f} × "
                             f"{dp['die_h']:.0f} mm", 120 * mm, 55 * mm))
    for i in range(0, len(drawings), 2):
        story.append(Table([drawings[i:i + 2]]))
        story.append(Spacer(1, 3 * mm))
    rows = [["Part", "Cavities", "Weight (g)", "Share %", "Share of tool cost (INR)", "Share of CAPEX (INR)", "Own tool CAPEX (INR)", "Uses"]]
    for s in tr["shares"]:
        own = s.get("own") or {}
        rows.append([f"{s['part_code']} · {s['name']}"[:48], s["cavities"], f"{s['weight_g']:,.1f}",
                     f"{s['pct']:.2f}" + (" (typed)" if s["typed"] else ""), f"{s['cost_inr']:,.0f}",
                     f"{s['capex_inr']:,.0f}" if s["capex_inr"] is not None else "—",
                     f"{own['capex_inr']:,.0f}" if own.get("capex_inr") is not None else "—", "family" if s["use_family"] else "own tool"])
    rows.append(["Family tool", "", "", "100.00", f"{tr['value_inr']:,.0f}", f"{tr['capex_inr'] or 0:,.0f}",
                 f"saving {tr['saving_capex_inr']:,.0f}" if tr.get("saving_capex_inr") is not None else "", ""])
    t = Table(rows, colWidths=[70 * mm, 18 * mm, 22 * mm, 26 * mm, 38 * mm, 36 * mm, 36 * mm, 20 * mm], repeatRows=1)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#152238")),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c9d1da")),
                           ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
    story += [t, Spacer(1, 3 * mm), Paragraph(
        "Share % = your % or, when blank, part weight × cavities ÷ Σ of the parts without a typed %. Part share of tool cost and "
        "CAPEX = family value × share %." + (" Same shot: the moulding / press machine hour is shared by the same %." if tr["family_mode"] == "same_shot"
                                              else " Swap inserts: the parts run one after another, each on its own machine time."), note)]
    if (tr.get("example") or {}).get("any"):
        story.append(Paragraph(f"<font color='#b91c1c'>{tr['example']['warning']}. {tr['example']['detail']}</font>", note))
    doc.build(story)
    return buf.getvalue()


def pack(fid: int, version: int | None = None) -> bytes:
    """Family pack: layout + split PDF, tool cost PDF and Excel of the family tool, BOM (CSV) and a read-me."""
    tr = trace(fid, version)
    code = tr["family"]["code"].replace("/", "-")
    bom = io.StringIO()
    bom.write("Die / tool;Element;Part;Common / per part;Quantity;Grade;Make;Line total\n")
    for ln in tr["lines"]:
        bom.write(";".join(str(x) for x in (ln.get("die") or "Mould", ln["element"], ln.get("member") or "",
                                             "family base" if ln.get("family_base") else ("common" if ln.get("common") else "per part"),
                                             ln.get("quantity"), ln.get("grade") or "", ln.get("make") or "", round(ln["total"], 2))) + "\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{code}_family_layout_and_split.pdf", layout_pdf(fid, version, tr))
        z.writestr(f"{code}_family_tool_cost.pdf", pdf(fid, version))
        z.writestr(f"{code}_family_tool_cost.xlsx", excel(fid, version))
        z.writestr(f"{code}_family_bom.csv", bom.getvalue())
        z.writestr("README.txt", f"Family tool {code} · {tr['mode_label']}\nVersion {tr.get('version') or 'live'} · {tr['country']} "
                                 f"{tr['as_of']}\nParts: " + ", ".join(f"{s['part_code']} {s['pct']:.2f} %" for s in tr["shares"])
                                 + "\nThe parts' own outputs (drawings, simulation, FEA ...) are in each part's output pack.\n")
    return buf.getvalue()
