"""Technical data, release and revision history on the tool drawings (roadmap stage 30).

Every made part of a tool design (tool_design.py / mould_design.py) carries on its detail drawing what the toolmaker
needs: material grade and hardness (from the editable tool BOM, stage 23), heat treatment, surface treatment, surface
roughness Ra, the ISO 2768 general tolerance class with its linear and angular tables (Mould & die database →
General tolerances) and the reviewer's note points. The designer reviews and changes them per part on the part panel
(Tool design → Drawing data) or in an Excel sheet (download, change, upload); every change is logged.

Title block (drawing_style.py): release date and approved by come from the design loop: the drawing is released when
the part reaches the last status of the flow (Tool design frozen) and stays there; before that it says NOT RELEASED.
The revision history lists the part revisions, the releases and the technical-data changes.
"""

from __future__ import annotations

import io
import re
from datetime import datetime

from sqlalchemy import select

from . import auth, mould_db, register_setup
from . import projects_db as db

CLASSES = ("f", "m", "c", "v")
FIELDS = ("heat_treatment", "surface_treatment", "tolerance_class", "finish_ra", "tolerance_unit")
LABELS = {"heat_treatment": "Heat treatment", "surface_treatment": "Surface treatment",
          "tolerance_class": "General tolerance class (f, m, c, v)", "finish_ra": "Surface roughness Ra (µm)",
          "tolerance_unit": "Tolerances shown in (mm or µm)"}
MAX_NOTES, MAX_NOTE = 12, 300
EXAMPLE = "EXAMPLE - ISO 2768-1 values as remembered: check them against your copy of the standard"
LINEAR = ((0.5, 3), (3, 6), (6, 30), (30, 120), (120, 400), (400, 1000), (1000, 2000), (2000, 4000))
ANGULAR = ((0, 10), (10, 50), (50, 120), (120, 400), (400, 100000))
SEED_LINEAR = {"f": (0.05, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, None), "m": (0.1, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0),
               "c": (0.2, 0.3, 0.5, 0.8, 1.2, 2.0, 3.0, 4.0), "v": (None, 0.5, 1.0, 1.5, 2.5, 4.0, 6.0, 8.0)}
SEED_ANGULAR = {"f": (60, 30, 20, 10, 5), "m": (60, 30, 20, 10, 5), "c": (90, 50, 25, 15, 10), "v": (180, 120, 60, 30, 20)}


def seed_rows() -> list[dict]:
    rows = []
    for cls in CLASSES:
        rows += [{"tol_class": cls, "kind": "linear", "from_mm": lo, "to_mm": hi, "value": v, "is_example": True, "notes": EXAMPLE}
                 for (lo, hi), v in zip(LINEAR, SEED_LINEAR[cls]) if v is not None]
        rows += [{"tol_class": cls, "kind": "angular", "from_mm": lo, "to_mm": hi, "value": v, "is_example": True, "notes": EXAMPLE}
                 for (lo, hi), v in zip(ANGULAR, SEED_ANGULAR[cls])]
    return rows


def seed() -> int:
    """Add the general-tolerance rows that are missing (existing rows are never changed)."""
    d = mould_db.tables()
    have = {(r["tol_class"], r["kind"], r["from_mm"]) for r in d["general_tolerances"]}
    new = [r for r in seed_rows() if (r["tol_class"], r["kind"], r["from_mm"]) not in have]
    if new:
        d["general_tolerances"] += new
        mould_db.write(d)
    return len(new)


def validate(clean: dict) -> None:
    for i, r in enumerate(clean.get("general_tolerances", []), start=2):
        if r["to_mm"] <= r["from_mm"] or r["value"] <= 0:
            raise mould_db.MouldDbError(f"General tolerances row {i}: 'to' must be above 'from' and the value above 0.")


# ---------- tolerance tables ----------

def tolerance_class(text: str, override: str | None = None) -> str:
    if override in CLASSES:
        return override
    m = re.search(r"2768[- ]?-?\s*([fmcv])", text or "", re.I)
    return m.group(1).lower() if m else "m"


def tolerance_table(cls: str, kind: str) -> list[dict]:
    rows = [r for r in mould_db.tables()["general_tolerances"] if r["tol_class"] == cls and r["kind"] == kind] \
        or [r for r in seed_rows() if r["tol_class"] == cls and r["kind"] == kind]      # a database not yet updated
    return sorted(({"from": r["from_mm"], "to": r["to_mm"], "value": r["value"]} for r in rows), key=lambda r: r["from"])


def fmt_angle(minutes: float) -> str:
    deg, mins = divmod(int(round(minutes)), 60)
    return f"±{deg}°" + (f"{mins:02d}′" if mins else "")


def tables_text(cls: str) -> dict:
    lin = [{"range": f"{r['from']:g} – {r['to']:g}", "value": f"±{r['value']:g}"} for r in tolerance_table(cls, "linear")]
    ang = [{"range": "up to 10" if r["from"] == 0 else (f"over {r['from']:g}" if r["to"] >= 100000 else f"{r['from']:g} – {r['to']:g}"),
            "value": fmt_angle(r["value"])} for r in tolerance_table(cls, "angular")]
    return {"linear": lin, "angular": ang}


# ---------- defaults and effective data of one made part ----------

def _ra(text: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)", text or "")
    return float(m.group(1)) if m else 3.2


def defaults(comp, part_type: str) -> dict:
    """What the drawing shows before anybody changes it, from the part (BOM) and the Design rules of the part type."""
    rules = {k: (r["text"] or "") for k, r in mould_db.design_rules(part_type).items()} if part_type else {}
    hard = (comp.hardness or "").lower()
    hardened = "hrc" in hard and "pre" not in hard
    return {"heat_treatment": (rules.get("heat_treat_note") or "Harden and temper") if hardened else "none (as supplied)",
            "surface_treatment": "none",
            "tolerance_class": tolerance_class(rules.get("general_tolerance", "ISO 2768-mK")),
            "finish_ra": _ra(rules.get("finish_general", "Ra 3.2")), "tolerance_unit": "mm"}


def effective(comp, part_type: str, over: dict | None) -> dict:
    f = defaults(comp, part_type) | {k: v for k, v in ((over or {}).get("fields") or {}).items() if k in FIELDS and v not in (None, "")}
    f["tolerance_class"] = tolerance_class("", f["tolerance_class"])
    f["finish_ra"] = float(f["finish_ra"])
    f["material"], f["hardness"] = comp.material or "-", comp.hardness or "-"
    f["notes"] = list((over or {}).get("notes") or [])
    f["tables"] = tables_text(f["tolerance_class"])
    f["changed"] = bool(over and ((over.get("fields") or {}) or over.get("notes")))
    from . import dim_tolerances                    # stage 31: a tolerance on every dimension
    f["dim_overrides"] = dict(((over or {}).get("fields") or {}).get("features") or {})
    f["dims"] = dim_tolerances.for_component(comp, part_type, f["tolerance_class"], f["dim_overrides"], f["tolerance_unit"])
    return f


# ---------- stored changes ----------

def stored(conn, part_id: int) -> dict:
    """{(tool key, item no): {fields, notes, edited_by, edited_at}}"""
    return {(r["tool_key"], r["item_no"]): {"fields": r["fields"] or {}, "notes": r["notes"] or [], "edited_by": r["edited_by"],
                                            "edited_at": r["edited_at"].isoformat(timespec="seconds") if r["edited_at"] else None}
            for r in conn.execute(select(db.tool_drawing_data).where(db.tool_drawing_data.c.part_id == part_id)).mappings()}


def clean(fields: dict | None, notes) -> tuple[dict, list]:
    from . import dim_tolerances
    out = {}
    for k, v in (fields or {}).items():
        if k not in FIELDS and k != "features":
            raise auth.AuthError(f"'{k}' cannot be changed here ({', '.join(FIELDS)}); material and hardness are changed in the tool BOM.", 400)
        if k == "features":
            feats = dim_tolerances.clean_overrides(v)
            if feats:
                out["features"] = feats
            continue
        if v in (None, ""):
            continue
        if k == "tolerance_unit":
            v = dim_tolerances.clean_unit(v)
        elif k == "tolerance_class":
            v = str(v).strip().lower()
            if v not in CLASSES:
                raise auth.AuthError("General tolerance class must be f, m, c or v.", 400)
        elif k == "finish_ra":
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise auth.AuthError(f"Surface roughness Ra '{v}' is not a number.", 400) from None
            if v <= 0:
                raise auth.AuthError("Surface roughness Ra must be more than 0.", 400)
        else:
            v = str(v).strip()[:160]
        out[k] = v
    nl = [str(n).strip()[:MAX_NOTE] for n in (notes or []) if str(n).strip()]
    if len(nl) > MAX_NOTES:
        raise auth.AuthError(f"At most {MAX_NOTES} note points per drawing.", 400)
    return out, nl


def _summary(old: dict, fields: dict, notes: list) -> str:
    of = old.get("fields") or {}
    bits = [f"{LABELS[k].split(' (')[0].lower()} {of.get(k, 'default')} → {v}" for k, v in fields.items() if k != "features" and of.get(k) != v]
    bits += [f"{LABELS[k].split(' (')[0].lower()} back to default" for k in of if k not in fields and k != "features"]
    oft, nft = of.get("features") or {}, fields.get("features") or {}
    bits += [f"tolerance {k} {oft.get(k, 'as drawn')} → {nft.get(k, 'as drawn')}" for k in sorted(set(oft) | set(nft)) if oft.get(k) != nft.get(k)]
    if (old.get("notes") or []) != notes:
        bits.append(f"note points {len(old.get('notes') or [])} → {len(notes)}")
    return "Technical data changed: " + "; ".join(bits)


def save(conn, part_id: int, tool_key: str, item_no: str, fields: dict | None, notes) -> dict | None:
    fields, notes = clean(fields, notes)
    cur = stored(conn, part_id).get((tool_key, item_no), {"fields": {}, "notes": []})
    if (cur["fields"], cur["notes"]) == (fields, notes):
        return None
    summary = _summary(cur, fields, notes)
    who = auth.username() or "local user"
    t = db.tool_drawing_data
    row = conn.execute(select(t.c.id).where((t.c.part_id == part_id) & (t.c.tool_key == tool_key) & (t.c.item_no == item_no))).first()
    vals = {"fields": fields, "notes": notes, "edited_by": who, "edited_at": datetime.utcnow()}
    if row:
        conn.execute(t.update().where(t.c.id == row[0]).values(**vals))
    else:
        conn.execute(t.insert().values(part_id=part_id, tool_key=tool_key, item_no=item_no, **vals))
    conn.execute(db.tool_drawing_edits.insert().values(part_id=part_id, tool_key=tool_key, item_no=item_no, summary=summary[:500], by=who))
    auth.log(conn, "part", part_id, "drawing_data_changed", {"tool": tool_key, "item": item_no, "summary": summary[:300]})
    return {"tool": tool_key, "item": item_no, "summary": summary}


def attach(part_id: int, designs: list) -> list:
    """Give every made part of the designs its technical data (comp.tech) and its note points (on the drawing)."""
    with db.engine().connect() as conn:
        over = stored(conn, part_id)
    for _, des in designs:
        pt = des.get("part_type", "")
        for c in des["components"]:
            if c.kind != "made":
                continue
            o = over.get((des["key"], c.no))
            c.tech = effective(c, pt, o)
            c.dims = c.tech["dims"]
            if o and o.get("notes"):
                c.notes = list(c.notes) + [n for n in o["notes"] if n not in c.notes]
    return designs


# ---------- release (design loop) and revision history ----------

def release(part_id: int) -> dict:
    """{released, date, by, status}: released = the part is at the last status of the design loop (Tool design frozen)."""
    sts = register_setup.statuses()
    final = sts[-1]["code"] if sts else ""
    names = {s["code"]: s["name"] for s in sts}
    with db.engine().connect() as conn:
        p = conn.execute(select(db.parts.c.status).where(db.parts.c.id == part_id)).first()
        rows = conn.execute(select(db.history).where((db.history.c.entity == "part") & (db.history.c.entity_id == part_id)
                                                     & (db.history.c.action == "status_changed")).order_by(db.history.c.id)).mappings().all()
    status = p[0] if p else ""
    hit = [r for r in rows if (r["detail"] or {}).get("new") == final]
    if status == final and hit:
        return {"released": True, "date": hit[-1]["at"].date().isoformat(), "by": hit[-1]["user"] or "-", "status": names.get(status, status)}
    return {"released": False, "date": "NOT RELEASED", "by": "", "status": names.get(status, status)}


def history(part_id: int, tool_key: str | None = None, item_no: str | None = None) -> list[dict]:
    """[{rev, date, text, by}] oldest first: part revisions, releases (design loop) and technical-data changes of this drawing."""
    sts = register_setup.statuses()
    final = sts[-1]["code"] if sts else ""
    with db.engine().connect() as conn:
        revs = conn.execute(select(db.revisions).where(db.revisions.c.part_id == part_id).order_by(db.revisions.c.id)).mappings().all()
        rel = conn.execute(select(db.history).where((db.history.c.entity == "part") & (db.history.c.entity_id == part_id)
                                                    & (db.history.c.action == "status_changed")).order_by(db.history.c.id)).mappings().all()
        e = db.tool_drawing_edits
        q = select(e).where(e.c.part_id == part_id)
        if tool_key is not None:
            q = q.where(e.c.tool_key == tool_key)
        if item_no is not None:
            q = q.where(e.c.item_no == item_no)
        edits = conn.execute(q.order_by(e.c.id)).mappings().all()
    rows = [{"rev": r["rev"], "at": r["created_at"], "text": (r["change_note"] or "Part model revision")[:160], "by": r["created_by"] or ""} for r in revs]
    rows += [{"rev": "", "at": r["at"], "text": "Released: " + (next((s["name"] for s in sts if s["code"] == final), final)), "by": r["user"] or ""}
             for r in rel if (r["detail"] or {}).get("new") == final]
    rows += [{"rev": "", "at": r["at"], "text": (f"Item {r['item_no']}: " if item_no is None and r["item_no"] else "") + r["summary"], "by": r["by"] or ""}
             for r in edits]
    rows.sort(key=lambda r: _naive(r["at"]))
    last = ""
    for r in rows:
        last = r["rev"] or last
        r["rev"] = last or "-"
        r["date"] = _naive(r.pop("at")).date().isoformat() if r.get("at") else ""
    return rows


def _naive(at) -> datetime:
    if not at:
        return datetime.min
    return at.replace(tzinfo=None) if at.tzinfo else at


# ---------- the drawing data sheet (Excel) ----------

HEAD = ["Tool", "Item", "Part", "Qty", "Material (tool BOM)", "Hardness (tool BOM)", "Heat treatment", "Surface treatment",
        "General tolerance class (f, m, c, v)", "Surface roughness Ra (µm)", "Note points (one per line)", "Last edited by",
        "Tolerances shown in (mm / µm)"]


def workbook(part: dict, rows: list[dict], hist: list[dict]) -> bytes:
    """rows: {tool, tool_name, item, name, qty, eff, edited_by}."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Drawing data"
    ws.append(HEAD)
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="152238")
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for r in rows:
        e = r["eff"]
        ws.append([r["tool"], r["item"], r["name"], r["qty"], e["material"], e["hardness"], e["heat_treatment"], e["surface_treatment"],
                   e["tolerance_class"], e["finish_ra"], "\n".join(e["notes"]), r.get("edited_by") or "", e.get("tolerance_unit", "mm")])
        for c in list(ws[ws.max_row][6:11]) + [ws[ws.max_row][12]]:
            c.fill = PatternFill("solid", fgColor="FFF7E6")              # the cells you may change
        for c in ws[ws.max_row]:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    for i, w in enumerate((16, 8, 30, 6, 24, 22, 28, 22, 14, 12, 60, 16, 14), start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    ws.freeze_panes = "D2"
    ds = wb.create_sheet("Dimension tolerances")          # stage 31
    ds.append(["Tool", "Item", "Dimension", "What", "Tolerance on the drawing", "Your tolerance (empty = as drawn)"])
    for c in ds[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="152238")
    for r in rows:
        ov = r["eff"].get("dim_overrides") or {}
        for f in r.get("dimensions") or []:
            ds.append([r["tool"], r["item"], f["key"], f["what"], f["tolerance"], ov.get(f["key"], "")])
            ds.cell(ds.max_row, 6).fill = PatternFill("solid", fgColor="FFF7E6")
    for col_, w in zip("ABCDEF", (16, 8, 12, 46, 26, 30)):
        ds.column_dimensions[col_].width = w
    ds.freeze_panes = "A2"
    ins = wb.create_sheet("How to use")
    for line in [f"Drawing data of the tool design of {part['part_code']} {part['name']}", "",
                 "1. Change the coloured columns: heat treatment, surface treatment, general tolerance class (f, m, c, v), roughness Ra, note points.",
                 "2. Material and hardness come from the tool BOM: change them there (part panel → Tool cost → tool BOM).",
                 "3. Upload this file on the part panel (Tool design → Drawing data → Upload). The PDF and DXF drawings follow.",
                 "4. Do not change the Tool and Item columns or the sheet names. An empty cell goes back to the default.",
                 "4b. Sheet 'Dimension tolerances': every dimension of every detail drawing with its tolerance. Type a new one in the last column:"
                 " general (ISO 2768), class (the fit of the hole label), a fit (H7, g6, k6 …), ±0.02, +0.02/-0.01 (mm) or a thread class (6H)."
                 " Last column of 'Drawing data': show the tolerances in mm or µm.",
                 "5. Every change is kept and printed in the revision history of the drawing."]:
        ins.append([line])
    ins.column_dimensions["A"].width = 140
    tol = wb.create_sheet("Tolerance tables")
    tol.append(["Class", "Kind", "From", "To", "± value"])
    for r in sorted(mould_db.tables()["general_tolerances"] or seed_rows(), key=lambda r: (r["tol_class"], r["kind"], r["from_mm"])):
        tol.append([r["tol_class"], r["kind"], r["from_mm"], r["to_mm"], r["value"]])
    hs = wb.create_sheet("Revision history")
    hs.append(["Rev", "Date", "Change", "By"])
    for r in hist:
        hs.append([r["rev"], r["date"], r["text"], r["by"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_workbook(content: bytes) -> list[dict]:
    """[{tool, item, fields, notes}] from an uploaded drawing data sheet."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(content), data_only=True)
    except Exception:
        raise auth.AuthError("The file is not an Excel workbook (.xlsx).", 400) from None
    if "Drawing data" not in wb.sheetnames:
        raise auth.AuthError("This workbook has no sheet 'Drawing data': download the drawing data sheet, change it and upload it again.", 400)
    rows = list(wb["Drawing data"].iter_rows(values_only=True))
    top = next((i for i, r in enumerate(rows[:12]) if r and str(r[0] or "").strip() == "Tool" and str(r[1] or "").strip() == "Item"), None)
    if top is None:
        raise auth.AuthError("The header row (Tool, Item, …) of the downloaded sheet is missing from 'Drawing data'.", 400)
    out = []
    for r in rows[top + 1:]:
        if not r or not r[0] or not r[1]:
            continue
        r = list(r) + [None] * len(HEAD)
        out.append({"tool": str(r[0]).strip(), "item": str(r[1]).strip(),
                    "fields": {k: r[i] for k, i in (("heat_treatment", 6), ("surface_treatment", 7), ("tolerance_class", 8), ("finish_ra", 9),
                                                    ("tolerance_unit", 12)) if r[i] not in (None, "")},
                    "notes": [x for x in str(r[10] or "").splitlines() if x.strip()]})
    if "Dimension tolerances" in wb.sheetnames:
        by = {(o["tool"], o["item"]): o for o in out}
        drows = list(wb["Dimension tolerances"].iter_rows(values_only=True))
        top = next((i for i, r in enumerate(drows[:12]) if r and str(r[0] or "").strip() == "Tool" and str(r[2] or "").strip() == "Dimension"), None)
        for r in (drows[top + 1:] if top is not None else []):
            if not r or len(r) < 6 or not r[0] or r[5] in (None, ""):
                continue
            key = (str(r[0]).strip(), str(r[1]).strip())
            if key not in by:
                raise auth.AuthError(f"Dimension tolerances: tool {key[0]} item {key[1]} is not on the sheet 'Drawing data'.", 400)
            by[key]["fields"].setdefault("features", {})[str(r[2]).strip()] = str(r[5]).strip()
    return out


# ---------- what the part panel and the API use ----------

def part_data(part_id: int) -> dict:
    """Every made part of every tool of the part with its default and its current technical data."""
    from . import register
    d, rev, designs = register.tool_designs(part_id)
    with db.engine().connect() as conn:
        over = stored(conn, part_id)
    rel = release(part_id)
    tools = []
    for k, des in designs:
        items = []
        for c in des["components"]:
            if c.kind != "made":
                continue
            o = over.get((des["key"], c.no)) or {}
            eff = getattr(c, "tech", None) or effective(c, des.get("part_type", ""), o)
            from . import dim_tolerances
            items.append({"item": c.no, "name": c.name, "qty": c.qty, "defaults": defaults(c, des.get("part_type", "")),
                          "effective": {k2: eff[k2] for k2 in (*FIELDS, "material", "hardness", "notes", "dim_overrides")}, "changed": eff["changed"],
                          "dimensions": dim_tolerances.rows(eff["dims"], c),
                          "edited_by": o.get("edited_by"), "edited_at": o.get("edited_at")})
        tools.append({"stage": k, "key": des["key"], "name": des["name"], "items": items})
    return {"part_id": part_id, "part_code": d["part_code"], "rev": rev["rev"], "release": rel, "editable": not rel["released"],
            "fields": LABELS, "tools": tools, "history": history(part_id)}


def part_save(part_id: int, items: list[dict]) -> dict:
    """items: [{tool, item, fields, notes}] replace the stored data of those parts (an empty field = the default)."""
    rel = release(part_id)
    if rel["released"]:
        raise auth.AuthError(f"The tool design is released (design loop: {rel['status']}, {rel['date']}): step the design loop back to change "
                             "the drawing data; the change is then printed in the revision history.", 400)
    known = {(t["key"], i["item"]) for t in part_data(part_id)["tools"] for i in t["items"]}
    changed = []
    with db.engine().begin() as conn:
        for it in items:
            key = (str(it.get("tool", "")), str(it.get("item", "")))
            if key not in known:
                raise auth.AuthError(f"Tool {key[0]} item {key[1]} is not a made part of this part's tool design.", 400)
            try:
                r = save(conn, part_id, key[0], key[1], it.get("fields"), it.get("notes"))
            except auth.AuthError as exc:
                raise auth.AuthError(f"Tool {key[0]} item {key[1]}: {exc}", 400) from None
            if r:
                changed.append(r)
    return {"changed": changed, "unchanged": len(items) - len(changed)}


def part_xlsx(part_id: int) -> tuple[bytes, str]:
    data = part_data(part_id)
    from . import register
    part = register.part_detail(part_id, with_rm=False)
    with db.engine().connect() as conn:
        over = stored(conn, part_id)
    rows = [{"tool": t["key"], "item": i["item"], "name": i["name"], "qty": i["qty"], "eff": i["effective"], "dimensions": i["dimensions"],
             "edited_by": (over.get((t["key"], i["item"])) or {}).get("edited_by")} for t in data["tools"] for i in t["items"]]
    return workbook(part, rows, data["history"]), f"{part['part_code']}_rev{data['rev']}_drawing_data.xlsx"


def part_upload(part_id: int, content: bytes) -> dict:
    sheet = read_workbook(content)
    cur = {(t["key"], i["item"]): i for t in part_data(part_id)["tools"] for i in t["items"]}
    unknown = [f"{r['tool']} / {r['item']}" for r in sheet if (r["tool"], r["item"]) not in cur]
    if unknown:
        raise auth.AuthError("Not in this part's tool design: " + ", ".join(unknown[:5]) + ". Download the sheet again.", 400)
    items = []
    for r in sheet:
        dflt = cur[(r["tool"], r["item"])]["defaults"]

        def same(k, v):
            if k == "finish_ra":
                try:
                    return float(v) == float(dflt[k])
                except (TypeError, ValueError):
                    return False
            return str(v).strip().lower() == str(dflt.get(k)).strip().lower()
        fields = {k: v for k, v in r["fields"].items() if k != "features" and not same(k, v)}
        if r["fields"].get("features"):
            fields["features"] = r["fields"]["features"]
        items.append({"tool": r["tool"], "item": r["item"], "fields": fields, "notes": r["notes"]})
    out = part_save(part_id, items)
    out["rows_in_sheet"] = len(items)
    return out


def meta_of(part: dict) -> tuple[dict | None, list | None]:
    """(release, history) of a part-level drawing (part drawing, blank, strip layout, tool pack): the part found by id or
    part code; (None, None) when it is not in the register (then the title block is as before)."""
    pid = part.get("id")
    if not pid and part.get("part_code"):
        with db.engine().connect() as conn:
            row = conn.execute(select(db.parts.c.id).where(db.parts.c.part_code == part["part_code"])).first()
        pid = row[0] if row else None
    if not pid:
        return None, None
    return release(pid), history(pid, tool_key="")          # tool_key "" = no tool edits: part revisions and releases only
