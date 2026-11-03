"""Toolmaker review of a tool design (roadmap stage 43).

Master data → Mould & die database → *Review checklist* lists what must be true before a tool design is frozen (released to the
toolmaker). A row with a check formula is worked out from facts of the design (parts without material, machine fit, saved
simulations, example rules …). A row without a formula is signed by the toolmaker: ok / issue / not applicable / waived, with a
comment (required for issue and waived), the name and the time. A sign-off is never overwritten: every decision is a new row, the
latest one counts and the older ones stay as the history.

A blocking row that is not ok, not applicable or waived stops the part from moving to the last status of the design loop
(Tool design frozen). Which rows exist, their formulas and whether they block are all master data; the shipped rows are EXAMPLE.
"""

from __future__ import annotations

from sqlalchemy import func, select

from . import auth, fea, formula, machine_spec, mould_db, register_setup
from . import projects_db as db

EXAMPLE = "EXAMPLE - replace with your toolroom's release checklist"
STATUSES = ("ok", "issue", "na", "waived")
NEEDS_COMMENT = ("issue", "waived")
GOOD = ("ok", "na", "waived")
FACTS = {"made_parts": "Made parts in the tool", "std_parts": "Bought-out standard parts", "no_material": "Made parts without a material",
         "no_hardness": "Made parts without a hardness", "rules_example": "1 when the design rules used are still EXAMPLE",
         "machine_typed": "1 when a production machine was typed", "machine_bad": "Points of the typed machine this tool does not fit",
         "sim_runs": "Saved flow simulations of the part", "shut_height": "Shut height of the tool (mm)",
         # stage 45: tool internals
         "pins_wanted": "Ejector pins the rules want (pitch grid under the part, per cavity)", "pins_placed": "Ejector pins placed under the part",
         "cool_wanted": "Cooling lines tried in the inserts", "cool_placed": "Cooling lines placed clear of the part",
         "screws": "Socket head screws in the tool", "dowels": "Dowels / gauge pins in the tool",
         "fea_targets": "Load-carrying parts to check by FEA (Design rules → fea_parts)", "fea_checked": "Of those, checked by FEA on this revision",
         "fea_bad": "Of those, over the deflection or stress limit",
         # stage 46: Mould systems
         "systems_bad": "Mould systems checks (gate, overflow, ejection, cooling) that fail",
         "systems_unchecked": "Mould systems checks that could not be worked out (data missing)"}
MOULD = ("plastic", "die_casting", "foundry", "eps", "blow")
AUTO = (
    ("Every made part has a material", "no_material == 0", "Some made parts have no material: set it in the tool BOM.", 1),
    ("Every made part has a hardness", "no_hardness == 0", "Some made parts have no hardness on the drawing.", 0),
    ("The typed production machine takes this tool", "machine_bad == 0", "The tool does not fit the typed machine: see the Machine block.", 1),
    ("Design rules used are not EXAMPLE values", "rules_example == 0", "The design rules (Mould & die database) are still EXAMPLE values.", 0),
)
INTERNALS = (       # stage 45: added as new rows; existing rows are never changed
    ("plastic", "All wanted ejector pins are placed", "pins_placed >= pins_wanted", "Fewer ejector pins fit under the part than the pitch rule wants: place the rest by hand or use blade ejectors.", 0),
    ("die_casting", "All wanted ejector pins are placed", "pins_placed >= pins_wanted", "Fewer ejector pins fit under the part than the pitch rule wants: place the rest by hand.", 0),
) + tuple((pt, "All cooling lines are placed clear of the part", "cool_placed >= cool_wanted",
           "Some cooling lines hit the part and were left out: baffles, bubblers or a different layout are needed.", 0)
          for pt in ("plastic", "die_casting", "blow")) + tuple(
    (pt, "Plates are held by socket head screws", "screws >= 4", "Fewer than 4 screws in the tool: check how the plates are held.", 0)
    for pt in ("plastic", "die_casting", "foundry", "eps", "blow", "sheet_metal"))
FEA_ROWS = tuple((pt, "Strength check (FEA) of the load-carrying parts is within its limits", "fea_checked >= fea_targets and fea_bad == 0",
                  "The FEA was not run on this revision, or a part is over its deflection / stress limit: run it under Tool design → Strength check.", 0)
                 for pt in ("plastic", "die_casting", "foundry", "eps", "blow", "sheet_metal"))
SYSTEM_ROWS = tuple((pt, "Mould systems checks pass (gate, overflow, ejection, cooling)", "systems_bad == 0",
                     "A Mould systems check fails: see Tool design → Mould systems.", 0) for pt in ("plastic", "die_casting", "foundry", "eps", "blow"))
SIM = ("A flow simulation of the part is saved", "sim_runs >= 1", "No flow simulation is saved for this part: run one on the part page.", 0)
MANUAL = {
    "mould": ("Toolmaker: steel grades and hardness suit the part material and the run",
              "Toolmaker: parting line, gate position and venting accepted",
              "Toolmaker: ejection (pin positions, stroke) accepted",
              "Toolmaker: cooling layout accepted for the heat load"),
    "sheet_metal": ("Toolmaker: die clearances, punch and die steel and hardness accepted",
                    "Toolmaker: strip layout, stock guides and stripper accepted",
                    "Toolmaker: bending radius, spring-back and overbend accepted"),
}


def seed_rows() -> list[dict]:
    rows = []
    for pt in MOULD + ("sheet_metal",):
        items = list(AUTO) + ([SIM] if pt in MOULD else [])
        items += [(m, "", "", 1) for m in MANUAL["mould" if pt in MOULD else "sheet_metal"]]
        for step, (item, chk, msg, blocking) in enumerate(items, start=1):
            rows.append({"part_type": pt, "step": step, "item": item, "rule": chk, "message": msg, "blocking": bool(blocking),
                         "is_example": True, "notes": EXAMPLE})
    for i, (pt, item, chk, msg, blocking) in enumerate(INTERNALS + FEA_ROWS + SYSTEM_ROWS, start=1):
        rows.append({"part_type": pt, "step": 100 + i, "item": item, "rule": chk, "message": msg, "blocking": bool(blocking),
                     "is_example": True, "notes": EXAMPLE})
    return rows


def seed() -> int:
    """Add the checklist rows that are missing (existing rows are never changed)."""
    d = mould_db.tables()
    have = {(r["part_type"], r["item"]) for r in d["review_checklist"]}
    new = [r for r in seed_rows() if (r["part_type"], r["item"]) not in have]
    if new:
        d["review_checklist"] += new
        mould_db.write(d)
    return len(new)


def validate(clean: dict) -> None:
    env = {k: 1.0 for k in FACTS}
    for i, r in enumerate(clean.get("review_checklist", []), start=2):
        if r.get("rule"):
            try:
                formula.evaluate(r["rule"], env)
            except formula.FormulaError as exc:
                raise mould_db.MouldDbError(f"Review checklist row {i} ({r['item']}): {exc}  Facts you can use: {', '.join(FACTS)}.") from None
            except (ArithmeticError, ValueError):
                pass


def rows_for(part_type: str) -> list[dict]:
    return sorted((r for r in mould_db.tables()["review_checklist"] if r["part_type"] == part_type), key=lambda r: (r["step"], r["item"]))


# ---------- facts of a design ----------

def internals(des: dict) -> dict:
    """Stage 45: pins and cooling lines wanted vs placed (from the design), screws and dowels counted in the tool BOM."""
    i = dict(des.get("internals") or {})
    std = [c for c in des["components"] if c.kind == "std"]
    i["screws"] = sum(c.qty for c in std if "screw" in c.name.lower())
    i["dowels"] = sum(c.qty for c in std if "dowel" in (c.name + " " + (c.std or "")).lower())
    return {k: i.get(k, 0) for k in ("pins_wanted", "pins_placed", "cool_wanted", "cool_placed", "screws", "dowels")}


def facts(part_id: int, des: dict, machine: dict | None, rev: str = "") -> dict:
    made = [c for c in des["components"] if c.kind == "made"]
    empty = ("", "-", None)
    bad = [r for r in (machine or {}).get("check", []) if r["tool"] == des["name"] and not r["ok"]]
    with db.engine().connect() as conn:
        sims = conn.execute(select(func.count()).select_from(db.sim_runs).where(db.sim_runs.c.part_id == part_id)).scalar() or 0
    return {"made_parts": float(len(made)), "std_parts": float(sum(1 for c in des["components"] if c.kind == "std")),
            "no_material": float(sum(1 for c in made if c.material in empty)), "no_hardness": float(sum(1 for c in made if c.hardness in empty)),
            "rules_example": 1.0 if des.get("rules_are_examples") else 0.0,
            "machine_typed": 1.0 if (machine or {}).get("spec") else 0.0, "machine_bad": float(len(bad)),
            "sim_runs": float(sims), "shut_height": float(des.get("shut_height") or 0),
            "systems_bad": float(sum(1 for c in (des.get("systems") or {}).get("checks", []) if c["ok"] is False)),
            "systems_unchecked": float(sum(1 for c in (des.get("systems") or {}).get("checks", []) if c["ok"] is None))} \
        | {k: float(v) for k, v in internals(des).items()} \
        | fea.facts(part_id, rev, des)


# ---------- sign-offs (append only) ----------

def _latest(conn, part_id: int) -> dict:
    out = {}
    for r in conn.execute(select(db.tool_reviews).where(db.tool_reviews.c.part_id == part_id).order_by(db.tool_reviews.c.id)).mappings():
        out[(r["tool_key"], r["item"])] = dict(r)
    return out


def history(part_id: int) -> list[dict]:
    with db.engine().connect() as conn:
        rows = conn.execute(select(db.tool_reviews).where(db.tool_reviews.c.part_id == part_id).order_by(db.tool_reviews.c.id.desc())).mappings().all()
    return [{"tool_key": r["tool_key"], "item": r["item"], "status": r["status"], "comment": r["comment"], "by": r["by"],
             "at": r["at"].isoformat(timespec="seconds") if r["at"] else None} for r in rows]


def sign(part_id: int, tool_key: str, item: str, status: str, comment: str = "") -> dict:
    from .register import RegisterError, tool_designs
    if status not in STATUSES:
        raise RegisterError("Status must be ok, issue, na (not applicable) or waived.")
    comment = str(comment or "").strip()
    if status in NEEDS_COMMENT and not comment:
        raise RegisterError(f"A review decision '{status}' needs a comment (why).")
    d, rev, designs = tool_designs(part_id, None)
    des = next((x for k, x in designs if x["key"] == tool_key), None)
    if not des:
        raise RegisterError(f"There is no tool '{tool_key}' in this part's tool design.")
    if item not in {r["item"] for r in rows_for(des.get("part_type", ""))}:
        raise RegisterError(f"'{item}' is not in Mould & die database → Review checklist for this part type.")
    with db.engine().begin() as conn:
        conn.execute(db.tool_reviews.insert().values(part_id=part_id, tool_key=tool_key, item=item, status=status, comment=comment[:500],
                                                       by=auth.username() or ""))
        auth.log(conn, "part", part_id, "tool_review", {"tool": tool_key, "item": item, "status": status})
    return review(part_id)


# ---------- the review ----------

def review(part_id: int) -> dict:
    from .register import tool_designs
    d, rev, designs = tool_designs(part_id, None)
    try:
        machine = machine_spec.evaluate(part_id, designs, rev)
    except Exception:                          # no machine family for this part type: the machine row is simply not applicable
        machine = None
    with db.engine().connect() as conn:
        signed = _latest(conn, part_id)
    tools, open_blocking = [], 0
    for _, des in designs:
        fx = facts(part_id, des, machine, rev["rev"])
        rows = []
        for r in rows_for(des.get("part_type", "")):
            s = signed.get((des["key"], r["item"]))
            auto = bool(r["rule"])
            if auto:
                try:
                    passed = bool(formula.evaluate(r["rule"], fx))
                except (formula.FormulaError, ArithmeticError, ValueError):
                    passed = False
                status = s["status"] if (s and not passed) else ("ok" if passed else "issue")
            else:
                status = s["status"] if s else "open"
            blocks = bool(r["blocking"]) and status not in GOOD
            open_blocking += blocks
            rows.append({"item": r["item"], "auto": auto, "rule": r["rule"], "status": status, "blocking": bool(r["blocking"]),
                         "blocks_release": blocks, "message": r["message"] if auto and status == "issue" else "",
                         "is_example": bool(r["is_example"]), "comment": s["comment"] if s else "", "by": s["by"] if s else "",
                         "at": s["at"].isoformat(timespec="seconds") if s and s["at"] else None})
        tools.append({"key": des["key"], "name": des["name"], "facts": fx, "rows": rows,
                      "blocking_open": sum(r["blocks_release"] for r in rows)})
    return {"part_id": part_id, "tools": tools, "blocking_open": open_blocking, "can_release": open_blocking == 0,
            "fact_labels": FACTS, "history": history(part_id)}


# ---------- the gate on the design loop ----------

def final_status() -> str:
    sts = register_setup.statuses()
    return sts[-1]["code"] if sts else ""


def check_release(part_id: int) -> None:
    """Called when a part moves to the last status of the design loop: stop while a blocking review row is open."""
    from .register import RegisterError
    try:
        r = review(part_id)
    except (RegisterError, ValueError):
        return                                  # no tool design for this part (machined, no tool cost yet): nothing to review
    if r["can_release"]:
        return
    open_rows = [f"{t['name']}: {x['item']}" for t in r["tools"] for x in t["rows"] if x["blocks_release"]]
    raise RegisterError("The tool design cannot be frozen yet. Open points in the toolmaker review (Tool design → Review): "
                        + "; ".join(open_rows[:5]) + (f" … and {len(open_rows) - 5} more" if len(open_rows) > 5 else "") + ".")
