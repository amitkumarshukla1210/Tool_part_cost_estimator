"""Design skills (roadmap stage 44): the software learns from the corrections made to the drawing data of its tool designs.

    learn     every change of a drawing-data field (heat treatment, surface treatment, tolerance class, Ra, tolerance unit) of a
              made tool part is kept as an event: part type, part name (e.g. "Cavity insert"), field, new value, part, who, when
              (append only)
    skill     the same value for the same field of the same part name and part type, set on at least *skill_min_parts*
              different parts (Mould & die database → Design rules, per part type, EXAMPLE) becomes a skill; when two values
              compete the one set on more parts wins (then the latest)
    apply     a skill is the starting value of that field on the next tool designs (shown as "skill"); a value typed on the part
              always wins; a skill can be switched off and on (kept as history)
    release   when a design is frozen (last status of the design loop) the skill values it shows are written into its drawing
              data, so a released drawing never changes when the team learns something new

Nothing is fixed here: without a skill_min_parts row for the part type no skill is applied.
"""

from __future__ import annotations

from sqlalchemy import select

from . import auth, mould_db
from . import projects_db as db

FIELDS = ("heat_treatment", "surface_treatment", "tolerance_class", "finish_ra", "tolerance_unit")
EXAMPLE = "EXAMPLE - how many different parts must show the same correction before it becomes a skill"
SEED_MIN_PARTS = 2
PART_TYPES = ("plastic", "die_casting", "foundry", "eps", "blow", "sheet_metal")


def _name(component: str) -> str:
    return " ".join(str(component or "").split()).lower()


def _value(v) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


# ---------- master data ----------

def seed() -> int:
    """Add the skill_min_parts Design rules row of each part type that is missing (existing rows are never changed)."""
    d = mould_db.tables()
    have = {(r["part_type"], r["parameter"]) for r in d["design_rules"]}
    new = [{"part_type": pt, "parameter": "skill_min_parts", "value": SEED_MIN_PARTS, "text": "", "unit": "parts",
            "description": "Design skills: a drawing-data correction becomes a skill after it was made on this many different parts",
            "is_example": True} for pt in PART_TYPES if (pt, "skill_min_parts") not in have]
    if new:
        d["design_rules"] += new
        mould_db.write(d)
    return len(new)


def min_parts(part_type: str) -> float | None:
    r = mould_db.design_rules(part_type).get("skill_min_parts")
    return float(r["value"]) if r and r.get("value") not in (None, "") else None


# ---------- learning ----------

def learn(conn, part_id: int, part_type: str, component: str, old: dict, new: dict) -> int:
    """Called by drawing_data.save: one event per field the user set to a new value."""
    n = 0
    for k in FIELDS:
        if k in new and new[k] not in (None, "") and old.get(k) != new[k]:
            conn.execute(db.design_skill_events.insert().values(part_id=part_id, part_type=part_type or "", component=_name(component),
                                                                 field=k, value=_value(new[k]), by=auth.username() or "local user"))
            n += 1
    return n


def _status(conn) -> dict:
    out = {}
    for r in conn.execute(select(db.design_skill_status).order_by(db.design_skill_status.c.id)).mappings():
        out[(r["part_type"], r["component"], r["field"], r["value"])] = dict(r)
    return out


def skills(part_type: str | None = None) -> list[dict]:
    """Every learned value with how many parts show it, whether it is switched on and whether it is applied."""
    with db.engine().connect() as conn:
        q = select(db.design_skill_events).order_by(db.design_skill_events.c.id)
        if part_type:
            q = q.where(db.design_skill_events.c.part_type == part_type)
        ev = conn.execute(q).mappings().all()
        st = _status(conn)
    groups: dict = {}
    for e in ev:
        g = groups.setdefault((e["part_type"], e["component"], e["field"], e["value"]),
                              {"parts": set(), "events": 0, "by": set(), "last_at": None})
        g["parts"].add(e["part_id"])
        g["events"] += 1
        g["by"].add(e["by"])
        g["last_at"] = e["at"]
    out, mins = [], {}
    for (pt, comp, f, v), g in groups.items():
        if pt not in mins:
            mins[pt] = min_parts(pt)
        s = st.get((pt, comp, f, v))
        active = not s or bool(s["active"])
        out.append({"part_type": pt, "component": comp, "field": f, "value": v, "parts": len(g["parts"]), "events": g["events"],
                    "by": sorted(g["by"]), "last_at": g["last_at"].isoformat(timespec="seconds") if g["last_at"] else None,
                    "min_parts": mins[pt], "active": active, "switched_by": s["by"] if s else "",
                    "qualifies": mins[pt] is not None and len(g["parts"]) >= mins[pt]})
    best: dict = {}
    for s in out:
        if s["qualifies"] and s["active"]:
            k = (s["part_type"], s["component"], s["field"])
            if k not in best or (s["parts"], s["last_at"] or "") > (best[k]["parts"], best[k]["last_at"] or ""):
                best[k] = s
    for s in out:
        s["applied"] = best.get((s["part_type"], s["component"], s["field"])) is s
    return sorted(out, key=lambda s: (s["part_type"], s["component"], s["field"], -s["parts"]))


def applied(part_type: str) -> dict:
    """{(part name, field): value} of the skills applied to new designs of this part type."""
    return {(s["component"], s["field"]): s for s in skills(part_type) if s["applied"]}


def for_component(table: dict, component: str) -> dict:
    """{field: value} of the applied skills of one tool part (table = applied(part_type))."""
    c = _name(component)
    return {f: s["value"] for (comp, f), s in table.items() if comp == c}


def set_active(part_type: str, component: str, field: str, value: str, active: bool) -> dict:
    if field not in FIELDS:
        raise ValueError(f"'{field}' is not a drawing-data field ({', '.join(FIELDS)}).")
    key = (part_type, _name(component), field, str(value))
    if not any((s["part_type"], s["component"], s["field"], s["value"]) == key for s in skills(part_type)):
        raise ValueError("There is no such learned value.")
    with db.engine().begin() as conn:
        conn.execute(db.design_skill_status.insert().values(part_type=key[0], component=key[1], field=field, value=key[3],
                                                            active=bool(active), by=auth.username() or "local user"))
        auth.log(conn, "design_skill", 0, "skill_on" if active else "skill_off", {"part_type": part_type, "component": key[1], "field": field, "value": key[3]})
    return {"skills": skills()}


# ---------- release: write the skill values into the drawing data ----------

def freeze(part_id: int) -> int:
    """Before a design is frozen: the fields that show a skill value are stored as the part's own drawing data."""
    from . import drawing_data, register
    try:
        _, _, designs = register.tool_designs(part_id)
    except (register.RegisterError, ValueError):
        return 0
    n = 0
    with db.engine().begin() as conn:
        over = drawing_data.stored(conn, part_id)
        t = db.tool_drawing_data
        for _, des in designs:
            for c in des["components"]:
                tech = getattr(c, "tech", None) or {}
                keep = {k: tech[k] for k in tech.get("from_skill", [])}
                if c.kind != "made" or not keep:
                    continue
                cur = over.get((des["key"], c.no))
                fields = dict((cur or {}).get("fields") or {}) | keep
                if cur:
                    conn.execute(t.update().where((t.c.part_id == part_id) & (t.c.tool_key == des["key"]) & (t.c.item_no == c.no)).values(fields=fields))
                else:
                    conn.execute(t.insert().values(part_id=part_id, tool_key=des["key"], item_no=c.no, fields=fields, notes=[],
                                                   edited_by="design skill (at release)"))
                conn.execute(db.tool_drawing_edits.insert().values(part_id=part_id, tool_key=des["key"], item_no=c.no, by="design skill (at release)",
                                                                   summary="Design skill values kept at release: " + ", ".join(f"{k} {v}" for k, v in keep.items())))
                n += 1
    return n
