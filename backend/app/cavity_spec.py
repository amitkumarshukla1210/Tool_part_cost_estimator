"""Cavities asked before the mould design (roadmap stage 46).

Before the first 3D design of a mould (plastic, die casting, EPS, blow moulding, foundry pattern equipment) the part page asks
how many cavities the tool gets, in the same way as the production machine (stage 33):

    recommended   Stage C of the tool cost: cavities needed for the annual volume, the cycle and the OEE, rounded to a
                  cavities-per-tool layout (traced: the Stage C line of the tool cost)
    confirmed     you accept the recommendation: the cavities keep following Stage C (a new volume changes them)
    typed         you type a number (1 - 256): it is saved as the tool input "cavities" (the same value the Tool features form
                  and the part register hold), so the tool cost, the layout, the mould base and the 3D design all use it

The answer is kept on the part (parts.cavity_check: asked, typed, recommended at the time, by, at) and logged. Asking again is
possible at any time from the tool design panel; nothing is asked for sheet-metal dies or machined parts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from . import auth, register, register_setup, tool_cost
from . import projects_db as db

MOULD_TYPES = tool_cost.PART_TYPES        # plastic, die_casting, eps, blow, foundry


def _part(part_id: int) -> tuple[dict, str]:
    d = register.part_detail(part_id, with_rm=False)
    pt = (register_setup.processes().get(d["process"]) or {}).get("part_type") or ""
    return d, pt


def get(part_id: int) -> dict:
    d, pt = _part(part_id)
    if pt not in MOULD_TYPES:
        raise register.RegisterError(f"Cavities are asked for moulds and pattern equipment; this part's process is {d['process']}.")
    with db.engine().connect() as conn:
        asked = conn.execute(select(db.parts.c.cavity_check).where(db.parts.c.id == part_id)).scalar() or {}
    tr = register.tool_trace(part_id)
    sc = tr.get("stage_c") or {}
    typed = (d["tool_inputs"] or {}).get("cavities")
    return {"part_id": part_id, "part_type": pt, "asked": bool(asked), "typed": typed,
            "recommended": sc.get("cavities_per_tool"), "needed": sc.get("cavities_needed"), "limited_by": sc.get("limited_by"),
            "stage_c_note": sc.get("note") or "", "in_use": tr.get("cavities") or (tr.get("key") or {}).get("cavities") or typed or sc.get("cavities_per_tool"),
            "source": "typed by you" if typed else "Stage C of the tool cost (recommended)",
            "answer": asked or None}


def save(part_id: int, cavities=None) -> dict:
    """cavities: a whole number 1 - 256 (typed), or None / "" = take the recommended number of Stage C."""
    d, pt = _part(part_id)
    if pt not in MOULD_TYPES:
        raise register.RegisterError("This part's process has no mould: cavities are not asked.")
    n = None
    if cavities not in (None, ""):
        try:
            n = int(str(cavities).strip())
        except ValueError:
            raise register.RegisterError(f"Cavities: '{cavities}' is not a whole number.") from None
        if not 1 <= n <= 256:
            raise register.RegisterError("Cavities must be between 1 and 256.")
    inputs = dict(d["tool_inputs"] or {})
    if n is None:
        inputs.pop("cavities", None)
    else:
        inputs["cavities"] = n
    rec = None
    try:
        rec = (register.tool_trace(part_id).get("stage_c") or {}).get("cavities_per_tool")
    except register.RegisterError:
        pass
    value = {"asked": True, "typed": n, "recommended": rec, "by": auth.username() or "",
             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with db.engine().begin() as conn:
        conn.execute(db.parts.update().where(db.parts.c.id == part_id).values(cavity_check=value))
        auth.log(conn, "part", part_id, "cavities_set", value)
    if (d["tool_inputs"] or {}).get("cavities") != n:
        register.set_tool_inputs(part_id, inputs, reason=f"cavities {'typed: ' + str(n) if n else 'from Stage C'} (asked before the mould design)")
    return get(part_id)
