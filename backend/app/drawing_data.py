"""Technical data of the tool drawings (roadmap stage 28): what is printed, reviewed, changed and uploaded again.

Every made part carries the data a supplier needs to make it: material grade, hardness, heat and surface treatment, general tolerances (linear and angular,
ISO 2768 class with the tables), surface roughness, stock, weight, quantity and extra note points. The defaults come from the component class
(Master data → Component classes) and the general-tolerance tables (Master data → General tolerances). The designer reviews them on the tool-design page or in the
*drawing data sheet* (Excel: download, change, upload) and the drawings, the bill of materials and the purchase orders follow. Only a draft is changed (a released
design is never edited: start a new revision); every change is kept in the revision history printed on the drawing.
"""

from __future__ import annotations

import io
import re
from datetime import datetime

from sqlalchemy import select

from . import auth, mould_db
from . import projects_db as db

CLASSES = ("f", "m", "c", "v")
FIELDS = ("steel", "hardness", "heat_treatment", "surface_treatment", "tolerance_class", "finish_ra", "tolerance")
LABELS = {"steel": "Material grade", "hardness": "Hardness", "heat_treatment": "Heat treatment", "surface_treatment": "Surface treatment",
          "tolerance_class": "General tolerance class (f, m, c, v)", "finish_ra": "Surface roughness Ra (µm)", "tolerance": "Tolerance text (fits, forming surface …)"}
MAX_NOTES, MAX_NOTE = 12, 300
EXAMPLE = "EXAMPLE - ISO 2768-1 values as remembered: check them against your copy of the standard"
LINEAR = ((0.5, 3), (3, 6), (6, 30), (30, 120), (120, 400), (400, 1000), (1000, 2000), (2000, 4000))
ANGULAR = ((0, 10), (10, 50), (50, 120), (120, 400), (400, 100000))
SEED_LINEAR = {"f": (0.05, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, None), "m": (0.1, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0),
               "c": (0.2, 0.3, 0.5, 0.8, 1.2, 2.0, 3.0, 4.0), "v": (None, 0.5, 1.0, 1.5, 2.5, 4.0, 6.0, 8.0)}
SEED_ANGULAR = {"f": (60, 30, 20, 10, 5), "m": (60, 30, 20, 10, 5), "c": (90, 50, 25, 15, 10), "v": (180, 120, 60, 30, 20)}


def seed() -> int:
    d = mould_db.tables()
    have = {(r["tol_class"], r["kind"], r["from_mm"]) for r in d["general_tolerances"]}
    n = 0
    for cls in CLASSES:
        for (lo, hi), v in zip(LINEAR, SEED_LINEAR[cls]):
            if v is not None and (cls, "linear", lo) not in have:
                d["general_tolerances"].append({"tol_class": cls, "kind": "linear", "from_mm": lo, "to_mm": hi, "value": v, "is_example": 1, "notes": EXAMPLE})
                n += 1
        for (lo, hi), v in zip(ANGULAR, SEED_ANGULAR[cls]):
            if (cls, "angular", lo) not in have:
                d["general_tolerances"].append({"tol_class": cls, "kind": "angular", "from_mm": lo, "to_mm": hi, "value": v, "is_example": 1, "notes": EXAMPLE})
                n += 1
    if n:
        mould_db.write(d)
    return n


def validate(clean: dict) -> None:
    for i, r in enumerate(clean.get("general_tolerances", []), start=2):
        if r["tol_class"] not in CLASSES:
            raise mould_db.MouldDbError(f"General tolerances row {i}: class must be one of {', '.join(CLASSES)}.")
        if r["kind"] not in ("linear", "angular"):
            raise mould_db.MouldDbError(f"General tolerances row {i}: kind must be linear or angular.")
        if r["to_mm"] <= r["from_mm"] or r["value"] <= 0:
            raise mould_db.MouldDbError(f"General tolerances row {i}: 'to' must be above 'from' and the value above 0.")


def tolerance_class(text: str, override: str | None = None) -> str:
    if override in CLASSES:
        return override
    m = re.search(r"2768[- ]?-?\s*([fmcv])\b", text or "", re.I)
    return m.group(1).lower() if m else "m"


def tolerance_table(cls: str, kind: str) -> list[dict]:
    return sorted(({"from": r["from_mm"], "to": r["to_mm"], "value": r["value"]} for r in mould_db.tables()["general_tolerances"] if r["tol_class"] == cls and r["kind"] == kind),
                  key=lambda r: r["from"])


def fmt_angle(minutes: float) -> str:
    deg, mins = divmod(int(round(minutes)), 60)
    return f"±{deg}°" + (f"{mins:02d}′" if mins else "")


def fmt_linear(v: float) -> str:
    return f"±{v:g}"


# ---------- defaults, overrides and the data a drawing prints ----------

def heat_treatment_of(info: dict) -> str:
    ops = (info.get("ops_codes") or "").split(",")
    if "vacuum" in ops:
        return "Vacuum harden and temper"
    if "heat" in ops:
        return "Harden and temper"
    return "none"


def surface_treatment_of(info: dict) -> str:
    route = (info.get("route") or "").lower()
    found = [w for k, w in (("nitrid", "nitride"), ("polish", "polish"), ("textur", "texture / etch"), ("chrom", "hard chrome"), ("bead blast", "bead blast")) if k in route]
    return ", ".join(found) if found else "none"


def defaults(info: dict) -> dict:
    return {"steel": info["steel"], "hardness": info["hardness"] or "as supplied", "heat_treatment": heat_treatment_of(info), "surface_treatment": surface_treatment_of(info),
            "tolerance_class": tolerance_class(info["tolerance"]), "finish_ra": info["finish_ra"] or 3.2, "tolerance": info["tolerance"]}


def effective(info: dict, over: dict | None) -> dict:
    """The technical data the drawing prints: class defaults, over-typed by the user, with the tolerance tables of the class."""
    f = defaults(info) | {k: v for k, v in ((over or {}).get("fields") or {}).items() if v not in (None, "")}
    cls = tolerance_class(f["tolerance"], f["tolerance_class"])
    f["tolerance_class"] = cls
    small = sorted(info["bbox_mm"])[0]
    lin = tolerance_table(cls, "linear")
    ang = tolerance_table(cls, "angular")
    f["linear_table"] = [{"range": f"{r['from']:g} – {r['to']:g}", "value": fmt_linear(r["value"])} for r in lin]
    f["angular_table"] = [{"range": (f"up to {r['to']:g}" if r["from"] == 0 else f"over {r['from']:g}" if r["to"] >= 100000 else f"{r['from']:g} – {r['to']:g}"), "value": fmt_angle(r["value"])} for r in ang]
    f["general_tolerance_text"] = f"ISO 2768-{cls}" + (f" · {f['tolerance']}" if f["tolerance"] and "2768" not in f["tolerance"] else (f" · {f['tolerance'].split(';', 1)[1].strip()}" if ";" in f["tolerance"] else ""))
    f["notes"] = list((over or {}).get("notes") or [])
    return f


def apply(info: dict, over: dict | None, country: str, month: str) -> dict:
    """The component info with the typed data in it: steel, hardness, tolerance text, roughness; a new steel grade re-prices and re-weighs the stock."""
    out = dict(info)
    fields = (over or {}).get("fields") or {}
    for k in ("steel", "hardness", "tolerance"):
        if fields.get(k):
            out[k] = fields[k]
    if fields.get("finish_ra"):
        out["finish_ra"] = float(fields["finish_ra"])
    if fields.get("steel") and fields["steel"] != info["steel"] and info.get("stock"):
        from . import tool_components
        st = dict(info["stock"])
        size = st["size_mm"]
        density = tool_components._density(fields["steel"])
        st["weight_kg"] = round(size[0] * size[1] * size[2] * density * 1e-6, 2)
        st["finished_weight_kg"] = round(info["volume_cm3"] * density / 1000, 2)
        st["density"], st["steel"] = density, fields["steel"]
        out["stock"] = st
        rate = tool_components._lookup("tool_material", fields["steel"], country, month)
        out["steel_rate"] = rate
        out["material_cost"] = None if rate is None else round(st["weight_kg"] * rate)
    ef = effective(out, over)
    out["heat_treatment"], out["surface_treatment"], out["tolerance_class"] = ef["heat_treatment"], ef["surface_treatment"], ef["tolerance_class"]
    out["drawing_notes"] = ef["notes"]
    return out


# ---------- stored data ----------

def stored(conn, design_id: int) -> dict:
    return {r["part_no"]: {"fields": r["fields"] or {}, "notes": r["notes"] or [], "edited_by": r["edited_by"], "edited_at": r["edited_at"].isoformat(timespec="seconds") if r["edited_at"] else None}
            for r in conn.execute(select(db.tool_drawing_data).where(db.tool_drawing_data.c.design_id == design_id)).mappings()}


def _clean(fields: dict | None, notes) -> tuple[dict, list]:
    out = {}
    steels = {r["code"] for r in mould_db.tables()["tool_materials"]}
    for k, v in (fields or {}).items():
        if k not in FIELDS:
            raise auth.AuthError(f"'{k}' is not a drawing data field ({', '.join(FIELDS)}).", 400)
        if v in (None, ""):
            continue
        if k == "steel" and v not in steels:
            raise auth.AuthError(f"Material grade '{v}' is not in Master data → Tool materials: add it there first (the purchase order prices it from there).", 400)
        if k == "tolerance_class":
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
        raise auth.AuthError(f"At most {MAX_NOTES} extra note points per drawing.", 400)
    return out, nl


def _summary(old: dict, fields: dict, notes: list) -> str:
    bits = [f"{LABELS[k].split(' (')[0].lower()} {old.get('fields', {}).get(k, 'default')} → {v}" for k, v in fields.items() if old.get("fields", {}).get(k) != v]
    if (old.get("notes") or []) != notes:
        bits.append(f"note points {len(old.get('notes') or [])} → {len(notes)}")
    return "Technical data changed: " + "; ".join(bits)


def save(conn, design_id: int, part_no: str, fields: dict | None, notes, by: str) -> dict | None:
    fields, notes = _clean(fields, notes)
    cur = stored(conn, design_id).get(part_no, {"fields": {}, "notes": []})
    if (cur["fields"], cur["notes"]) == (fields, notes):
        return None
    summary = _summary(cur, fields, notes)
    row = conn.execute(select(db.tool_drawing_data.c.id).where((db.tool_drawing_data.c.design_id == design_id) & (db.tool_drawing_data.c.part_no == part_no))).first()
    vals = {"fields": fields, "notes": notes, "edited_by": by, "edited_at": datetime.utcnow()}
    if row:
        conn.execute(db.tool_drawing_data.update().where(db.tool_drawing_data.c.id == row[0]).values(**vals))
    else:
        conn.execute(db.tool_drawing_data.insert().values(design_id=design_id, part_no=part_no, **vals))
    conn.execute(db.tool_drawing_edits.insert().values(design_id=design_id, part_no=part_no, summary=summary[:500], by=by))
    return {"part_no": part_no, "summary": summary}


# ---------- revision history and the release block ----------

def history(conn, design_id: int, part_no: str | None) -> list[dict]:
    """Rows of the revision table printed on a drawing: [{rev, date, text, by, approved}] newest last."""
    d = conn.execute(select(db.tool_designs).where(db.tool_designs.c.id == design_id)).mappings().one()
    approved = d["released_by"] or ""
    rows = []
    if part_no and part_no != "*":
        comps = conn.execute(select(db.tool_components.c.id).where((db.tool_components.c.design_id == design_id) & (db.tool_components.c.part_no == part_no)).limit(1)).first()
        if comps:
            for r in conn.execute(select(db.tool_component_revs).where(db.tool_component_revs.c.component_id == comps[0]).order_by(db.tool_component_revs.c.id)).mappings():
                text = "First issue: generated from the 3D model" if r["note"] == "generated" else r["note"]
                rows.append({"rev": r["rev"], "date": r["created_at"], "text": text, "by": r["created_by"] or ""})
        for r in conn.execute(select(db.tool_drawing_edits).where((db.tool_drawing_edits.c.design_id == design_id) & (db.tool_drawing_edits.c.part_no.in_([part_no, "*"])))
                              .order_by(db.tool_drawing_edits.c.id)).mappings():
            rows.append({"rev": "", "date": r["at"], "text": r["summary"], "by": r["by"] or ""})
    else:
        for x in conn.execute(select(db.tool_designs).where(db.tool_designs.c.part_id == d["part_id"]).order_by(db.tool_designs.c.version)).mappings():
            rows.append({"rev": x["rev_label"], "date": x["released_at"] or x["created_at"], "text": (x["note"] or "Tool design") + (" · released" if x["released_at"] else f" · {x['status']}"),
                         "by": x["released_by"] or x["created_by"] or ""})
    rows.sort(key=lambda r: r["date"] or datetime.min)
    last_rev = ""
    for r in rows:
        if r["rev"]:
            last_rev = r["rev"]
        else:
            r["rev"] = last_rev or "A"
        r["date"] = r["date"].date().isoformat() if r["date"] else ""
        r["approved"] = approved if (d["status"] != "draft" and approved) else "—"
    return rows


def release_block(design: dict) -> dict:
    """Release date and approver for the title block. A draft is shown as not released."""
    released = design.get("released_at")
    if hasattr(released, "date"):
        released = released.date().isoformat()
    elif isinstance(released, str):
        released = released[:10]
    return {"status": design["status"], "rev_label": design["rev_label"], "version": design["version"], "release_date": released or "NOT RELEASED",
            "approved_by": design.get("released_by") or "— (not approved)" if released else "— (not approved)"}


# ---------- the drawing data sheet (Excel) ----------

def workbook(design_id: int, rows: list[dict], history_rows: list[dict]) -> bytes:
    """rows: one per made part number: {part_no, name, qty, rev, eff (effective data), edited_by}."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Drawing data"
    head = ["Part no.", "Name", "Qty per tool", "Revision", "Material grade", "Hardness", "Heat treatment", "Surface treatment", "General tolerance class (f, m, c, v)",
            "Surface roughness Ra (µm)", "Tolerance text", "Extra note points (one per line)", "Last edited by"]
    ws.append(head)
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="0F172A")
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for r in rows:
        e = r["eff"]
        ws.append([r["part_no"], r["name"], r["qty"], r["rev"], e["steel"], e["hardness"], e["heat_treatment"], e["surface_treatment"], e["tolerance_class"], e["finish_ra"], e["tolerance"],
                   "\n".join(e["notes"]), r.get("edited_by") or ""])
    for i, w in enumerate((18, 28, 8, 8, 24, 24, 24, 24, 16, 12, 44, 60, 18), start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
        for c in row[4:12]:
            c.fill = PatternFill("solid", fgColor="FEF9C3")        # the cells you may change
    ws.freeze_panes = "C2"
    ins = wb.create_sheet("How to use")
    for line in ["Drawing data sheet of the tool design", "",
                 "1. Review the yellow columns: material grade, hardness, heat and surface treatment, general tolerance class, surface roughness, tolerance text, extra note points.",
                 "2. Change what must change. Material grade must be a grade of Master data → Tool materials (the purchase order prices it). Class is f, m, c or v.",
                 "3. Upload this file on the tool-design page (BOM & PO → Drawing data → Upload). The drawings (PDF and DXF), the bill of materials and the purchase orders follow.",
                 "4. Only a draft can be changed. A released design is never edited: start a new revision.",
                 "5. Every change is kept in the revision history printed on the drawing. Do not change the grey columns, the part numbers or the sheet names."]:
        ins.append([line])
    ins.column_dimensions["A"].width = 150
    tol = wb.create_sheet("Tolerance tables")
    tol.append(["Class", "Kind", "From", "To", "± value"])
    for r in mould_db.tables()["general_tolerances"]:
        tol.append([r["tol_class"], r["kind"], r["from_mm"], r["to_mm"], r["value"]])
    hs = wb.create_sheet("Revision history")
    hs.append(["Part no.", "Rev", "Date", "Change", "By", "Approved"])
    for r in history_rows:
        hs.append([r.get("part_no", ""), r["rev"], r["date"], r["text"], r["by"], r["approved"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_workbook(content: bytes) -> dict[str, dict]:
    """{part_no: {"fields": {...}, "notes": [...]}} from an uploaded drawing data sheet."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(content), data_only=True)
    except Exception:
        raise auth.AuthError("The file is not an Excel workbook (.xlsx).", 400) from None
    if "Drawing data" not in wb.sheetnames:
        raise auth.AuthError("This workbook has no sheet 'Drawing data': download the drawing data sheet, change it and upload it again.", 400)
    rows = list(wb["Drawing data"].iter_rows(values_only=True))
    # the logo rows added to every download sit above the header: find the header row
    top = next((i for i, r in enumerate(rows[:12]) if r and str(r[0] or "").strip() == "Part no."), None)
    if top is None:
        raise auth.AuthError("The header row ('Part no.', 'Name', …) of the downloaded sheet is missing from 'Drawing data'.", 400)
    rows = rows[top:]
    cols = {"steel": 4, "hardness": 5, "heat_treatment": 6, "surface_treatment": 7, "tolerance_class": 8, "finish_ra": 9, "tolerance": 10}
    out = {}
    for r in rows[1:]:
        if not r or not r[0]:
            continue
        r = list(r) + [None] * 13
        out[str(r[0]).strip()] = {"fields": {k: r[i] for k, i in cols.items() if r[i] not in (None, "")},
                                  "notes": [x for x in str(r[11] or "").splitlines() if x.strip()]}
    return out


# ---------- title block of the strip layout / blank drawings (belong to the part, released with its sheet-metal tool design) ----------

def part_meta(part_id: int, title: str, number: str, rev: str, scale: str = "") -> dict:
    """Release block and revision history for a drawing of the part itself (blank, strip layout): the release is that of the part's
    latest released tool design; part revisions and tool design releases make the history."""
    from . import drawing_sheet
    with db.engine().connect() as conn:
        designs = [dict(r) for r in conn.execute(select(db.tool_designs).where(db.tool_designs.c.part_id == part_id)
                                                  .order_by(db.tool_designs.c.version)).mappings()]
        revs = [dict(r) for r in conn.execute(select(db.revisions).where(db.revisions.c.part_id == part_id).order_by(db.revisions.c.id)).mappings()]
    released = [d for d in designs if d["released_at"]]
    d = max(released, key=lambda x: x["released_at"]) if released else (designs[-1] if designs else None)
    rows = [{"rev": r["rev"], "date": r["created_at"].date().isoformat() if r["created_at"] else "", "text": (r["change_note"] or "Part model revision")[:160],
             "by": r["created_by"] or "", "approved": "—", "_at": r["created_at"]} for r in revs]
    for x in released:
        rows.append({"rev": rev, "date": x["released_at"].date().isoformat(), "text": f"Tool design version {x['version']} (rev {x['rev_label']}) released",
                     "by": x["created_by"] or "", "approved": x["released_by"] or "—", "_at": x["released_at"]})
    rows.sort(key=lambda r: r["_at"] or datetime.min)
    for r in rows:
        r.pop("_at")
    return drawing_sheet.sheet_meta(d, rows, title, number, rev, scale)
