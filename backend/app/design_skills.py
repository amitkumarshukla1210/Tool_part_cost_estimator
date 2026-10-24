"""Design skills (roadmap stage 27): the software learns from the corrections you make to its tool designs and applies them to the next ones.

    learn    when you replace a component by an edited STEP file, the change is measured against the old file: a thicker plate, other cooling
             holes … (rows of Master data → Skill knobs say which measure feeds which design value). It is stored as a skill:
             factor  the value the rules give × the factor you showed (a plate 25 % thicker → ×1.25)
             set     the value you used (cooling Ø 10 mm, 6 channels)
             a second correction of the same kind averages with the first (evidence counts)
    apply    every new design of the same tool group and part type (and a tool of 0.6 to 1.67 times the size) uses your skills: the plates are
             as thick as you make them, the cooling as you draw it. The design says which skills it used; a skill can be switched off, shared
             (head / admin: for everybody) or deleted on the Skills page; a design can also be made without skills.
Skills are yours (personal) until a head or admin shares them. Nothing about a skill is written in the code: only how a measure is taken.
"""

from __future__ import annotations

import contextvars
import math
from datetime import datetime

from sqlalchemy import select

from . import auth, mould_db
from . import projects_db as db

MEASURES = ("zlen", "cool_dia", "cool_count")
MODES = ("factor", "set")
SCOPES = ("personal", "shared")
EXAMPLE = "EXAMPLE - the parts a toolmaker typically changes"
SEED = [  # group, component, measure, target, mode, min change %
    ("mould", "A plate", "zlen", "base.a_plate_mm", "factor", 3), ("mould", "B plate", "zlen", "base.b_plate_mm", "factor", 3),
    ("mould", "Support plate", "zlen", "base.support_plate_mm", "factor", 3), ("mould", "Bottom clamp plate", "zlen", "base.clamp_plates_mm", "factor", 3),
    ("mould", "Spacer block", "zlen", "base.spacer_block_mm", "factor", 3), ("mould", "Ejector plate", "zlen", "base.ejector_plates_mm", "factor", 3),
    ("mould", "A side insert", "cool_dia", "rule.cool_dia_mm", "set", 5), ("mould", "B side insert", "cool_dia", "rule.cool_dia_mm", "set", 5),
    ("mould", "A side insert", "cool_count", "rule.cool_channels", "set", 0), ("mould", "B side insert", "cool_count", "rule.cool_channels", "set", 0),
    ("sheet_metal", "Die block", "zlen", "stage.die_block_t_mm", "factor", 3), ("sheet_metal", "Stripper plate", "zlen", "stage.stripper_t_mm", "factor", 3),
    ("sheet_metal", "Punch plate", "zlen", "stage.punch_plate_t_mm", "factor", 3), ("sheet_metal", "Backing plate", "zlen", "stage.backing_t_mm", "factor", 3),
    ("sheet_metal", "Lower shoe", "zlen", "stage.shoe_t_mm", "factor", 3), ("sheet_metal", "Upper shoe", "zlen", "stage.shoe_t_mm", "factor", 3),
    ("foundry", "Match plate", "zlen", "rule.match_plate_t_mm", "factor", 3),
]
_ctx: contextvars.ContextVar = contextvars.ContextVar("dtc_skills", default=None)


def seed() -> int:
    d = mould_db.tables()
    have = {(r["tool_group"], r["component"], r["measure"]) for r in d["skill_knobs"]}
    n = 0
    for g, comp, meas, target, mode, pct in SEED:
        if (g, comp, meas) not in have:
            d["skill_knobs"].append({"tool_group": g, "component": comp, "measure": meas, "target": target, "mode": mode, "min_change_pct": pct, "is_example": 1, "notes": EXAMPLE})
            n += 1
    if n:
        mould_db.write(d)
    return n


def validate(clean: dict) -> None:
    for i, r in enumerate(clean.get("skill_knobs", []), start=2):
        if r["measure"] not in MEASURES:
            raise mould_db.MouldDbError(f"Skill knobs row {i}: measure must be one of {', '.join(MEASURES)}.")
        if r["mode"] not in MODES:
            raise mould_db.MouldDbError(f"Skill knobs row {i}: mode must be factor or set.")
        if r["target"].split(".")[0] not in ("base", "rule", "stage"):
            raise mould_db.MouldDbError(f"Skill knobs row {i}: target must start with base., rule. or stage.")


# ---------- measuring ----------

def _cooling(shape) -> tuple[float, int]:
    """(diameter, number) of the horizontal through holes that are most numerous: the cooling channels of an insert."""
    from . import tool_components
    holes = [h for h in tool_components.features(shape)["holes"] if h["through"] and h["axis"] in ("x", "y") and 4 <= h["dia_mm"] <= 30]
    if not holes:
        return 0.0, 0
    best = max(holes, key=lambda h: h["count"])
    return float(best["dia_mm"]), int(best["count"])


def measure(shape, kind: str) -> float | None:
    if kind == "zlen":
        return shape.BoundingBox().zlen
    dia, n = _cooling(shape)
    return dia if kind == "cool_dia" else float(n)


# ---------- learning ----------

def _group(design: dict) -> str:
    return design["kind"]


def learn(design: dict, component: dict, old_shape, new_shape, size_ref: float | None = None) -> list[dict]:
    """Skills learned from one correction. Returns what was stored (for the message to the user)."""
    knobs = [k for k in mould_db.tables()["skill_knobs"] if k["tool_group"] == _group(design) and component["name"].startswith(k["component"])]
    out = []
    if not knobs:
        return out
    owner = (auth.current() or {}).get("username")
    for k in knobs:
        before, after = measure(old_shape, k["measure"]), measure(new_shape, k["measure"])
        if before is None or after is None:
            continue
        if k["measure"] == "zlen":
            if before <= 0 or abs(after - before) / before * 100 < k["min_change_pct"]:
                continue
            value, text = max(0.5, min(2.0, after / before)), f"{component['name']} thickness {before:.0f} → {after:.0f} mm (×{after / before:.2f})"
        elif k["measure"] == "cool_dia":
            if after <= 0 or abs(after - before) < max(0.1, before * k["min_change_pct"] / 100):
                continue
            value, text = after, f"cooling hole diameter {before:g} → {after:g} mm"
        else:
            if after <= 0 or after == before:
                continue
            value, text = after, f"cooling channels {before:.0f} → {after:.0f} per insert"
        out.append(_store(design, component, k, value, text, owner, size_ref))
    return out


def _store(design: dict, component: dict, knob: dict, value: float, text: str, owner: str | None, size_ref: float | None) -> dict:
    with db.engine().begin() as conn:
        cur = conn.execute(select(db.design_skills).where((db.design_skills.c.tool_group == _group(design)) & (db.design_skills.c.part_type == design["part_type"])
                                                          & (db.design_skills.c.target == knob["target"]) & (db.design_skills.c.owner == owner)
                                                          & (db.design_skills.c.scope == "personal"))).mappings().first()
        if cur:
            n = cur["evidence"]
            if knob["mode"] == "factor":
                new = math.exp((math.log(cur["value"]) * n + math.log(value)) / (n + 1))      # geometric mean of the factors
            else:
                new = round((cur["value"] * n + value) / (n + 1), 1)
            ref = ((cur["size_ref"] or size_ref or 0) * n + (size_ref or cur["size_ref"] or 0)) / (n + 1) or None
            conn.execute(db.design_skills.update().where(db.design_skills.c.id == cur["id"]).values(value=new, evidence=n + 1, size_ref=ref, active=True, note=text,
                                                                                                    source_design_id=design["id"], component=component["name"], updated_at=datetime.utcnow()))
            sid, val, ev = cur["id"], new, n + 1
        else:
            sid = conn.execute(db.design_skills.insert().values(tool_group=_group(design), part_type=design["part_type"], target=knob["target"], component=component["name"],
                                                                mode=knob["mode"], value=value, evidence=1, size_ref=size_ref, scope="personal", owner=owner, active=True,
                                                                source_design_id=design["id"], note=text)).inserted_primary_key[0]
            val, ev = value, 1
    return {"id": sid, "target": knob["target"], "mode": knob["mode"], "value": round(val, 3), "evidence": ev, "text": text}


# ---------- applying ----------

def _visible_filter(user: str | None):
    if not auth.server_mode() or user is None:
        return None
    return (db.design_skills.c.owner == user) | (db.design_skills.c.scope == "shared")


def begin(group: str, part_type: str, enabled: bool = True):
    """Start a design that uses the user's skills; returns a token for end()."""
    user = (auth.current() or {}).get("username")
    skills = []
    if enabled:
        with db.engine().connect() as conn:
            q = select(db.design_skills).where((db.design_skills.c.tool_group == group) & db.design_skills.c.active & (db.design_skills.c.part_type.in_([part_type, ""])))
            flt = _visible_filter(user)
            if flt is not None:
                q = q.where(flt)
            skills = [dict(r) for r in conn.execute(q).mappings()]
    skills.sort(key=lambda s: (s["owner"] != user, -s["evidence"]))        # your own first, then the most proven
    return _ctx.set({"group": group, "part_type": part_type, "enabled": enabled, "skills": skills, "applied": [], "base": {}})


def end(token) -> dict:
    ctx = _ctx.get() or {}
    _ctx.reset(token)
    return {"enabled": ctx.get("enabled", False), "applied": ctx.get("applied", []), "base": ctx.get("base", {})}


class off:
    """`with off():` evaluates rules without the user's skills (for helper look-ups that must not be recorded)."""

    def __enter__(self):
        self.token = _ctx.set(None)

    def __exit__(self, *exc):
        _ctx.reset(self.token)


def adjust(target: str, value: float, size: float | None = None) -> float:
    """The value of a design parameter after the user's skills; the value the rules gave is remembered for learning."""
    ctx = _ctx.get()
    if not ctx or not ctx["enabled"]:
        return value
    ctx["base"].setdefault(target, value)
    for s in ctx["skills"]:
        if s["target"] != target:
            continue
        if size and s["size_ref"] and not (0.6 <= size / s["size_ref"] <= 1 / 0.6):
            continue
        used = value * s["value"] if s["mode"] == "factor" else s["value"]
        if not any(a["id"] == s["id"] for a in ctx["applied"]):
            ctx["applied"].append({"id": s["id"], "target": target, "mode": s["mode"], "skill": s["value"], "from": round(value, 2), "to": round(used, 2), "text": s["note"],
                                   "evidence": s["evidence"], "scope": s["scope"]})
        return used
    return value


# ---------- the Skills page ----------

def list_skills() -> list[dict]:
    user = (auth.current() or {}).get("username")
    with db.engine().connect() as conn:
        q = select(db.design_skills).order_by(db.design_skills.c.tool_group, db.design_skills.c.target)
        flt = _visible_filter(user) if (auth.current() or {}).get("role") == "user" else None
        if flt is not None:
            q = q.where(flt)
        rows = [dict(r) for r in conn.execute(q).mappings()]
    for r in rows:
        r["created_at"] = r["created_at"].isoformat(timespec="seconds") if r["created_at"] else None
        r["updated_at"] = r["updated_at"].isoformat(timespec="seconds") if r["updated_at"] else None
    return rows


def _own(conn, sid: int) -> dict:
    row = conn.execute(select(db.design_skills).where(db.design_skills.c.id == sid)).mappings().first()
    if not row:
        raise auth.AuthError(f"Skill {sid} does not exist.", 404)
    me = auth.current()
    if auth.server_mode() and me and me["role"] == "user" and row["owner"] != me["username"]:
        raise auth.AuthError("This skill is not yours.", 403)
    return dict(row)


def update_skill(sid: int, data: dict) -> dict:
    with db.engine().begin() as conn:
        row = _own(conn, sid)
        vals = {}
        if "active" in data:
            vals["active"] = bool(data["active"])
        if "scope" in data:
            if data["scope"] not in SCOPES:
                raise auth.AuthError("Scope must be personal or shared.", 400)
            if data["scope"] == "shared" and auth.server_mode() and not auth.has_role("head"):
                raise auth.AuthError("Only the head of department or the admin shares a skill with everybody.", 403)
            vals["scope"] = data["scope"]
        if "value" in data:
            v = float(data["value"])
            if row["mode"] == "factor" and not 0.5 <= v <= 2.0:
                raise auth.AuthError("A factor must be between 0.5 and 2.", 400)
            vals["value"] = v
        if vals:
            conn.execute(db.design_skills.update().where(db.design_skills.c.id == sid).values(**vals, updated_at=datetime.utcnow()))
    return next(s for s in list_skills() if s["id"] == sid)


def delete_skill(sid: int) -> dict:
    with db.engine().begin() as conn:
        _own(conn, sid)
        conn.execute(db.design_skills.delete().where(db.design_skills.c.id == sid))
    return {"deleted": sid}
