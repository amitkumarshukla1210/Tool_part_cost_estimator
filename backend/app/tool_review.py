"""Toolmaker review of a tool design (roadmap stage 22).

*Review checklist* (master data) lists what must be true before a design is released to suppliers. Rows with an automatic check are
evaluated from facts of the design (overlap check, structural check, undercuts left, pins and channels placed, press and tie-bar fit …);
rows without one are signed by the toolmaker: ok / issue / not applicable / waived, with a comment, name and time. A blocking row that is
neither ok, not applicable nor waived stops the release. Automatic rows are re-evaluated whenever the design changes; a toolmaker's
decision on a manual row is kept.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update

from . import formula, master_data, mould_db
from . import projects_db as db

EXAMPLE = "EXAMPLE - replace with your toolroom's release checklist"
FACTS = ("check_errors", "check_warnings", "fea_ok", "fea_deflection_mm", "fea_limit_mm", "pins_placed", "pins_wanted", "cool_placed", "cool_wanted",
         "slides", "lifters", "undercut_unresolved", "draft_left_cm2", "tie_bar_fit", "clamp_t", "machine_t", "press_fit", "springs_placed",
         "springs_wanted", "form_undercuts", "pattern_ok", "gating_ok", "cores", "plates_thickened", "stages", "hot_runner", "cavities", "machine_fit")
SEED = [
    ("mould", "All solids are valid and no two parts overlap", "check_errors == 0", "The overlap / validity check found errors: see the Checks tab.", 1),
    ("mould", "Overlap warnings reviewed", "check_warnings == 0", "The overlap check has warnings: look at each and say why it is acceptable.", 0),
    ("mould", "Structural check (FEA) of the insert is within its limits", "fea_ok == 1", "The structural check was not run or is over a limit: thicken or support the insert.", 0),
    ("mould", "Mould base fits between the tie bars of the machine", "tie_bar_fit == 1", "The mould base is wider than the tie-bar space of the machine that takes the clamp force.", 1),
    ("mould", "Every undercut has a slide or lifter", "undercut_unresolved == 0", "Voids between the envelopes are left without a slide or lifter: see the notes.", 1),
    ("mould", "All wanted ejector pins are placed", "pins_placed >= pins_wanted", "Fewer ejector pins fit under the part than the BOM wants.", 0),
    ("mould", "All wanted cooling channels are placed", "cool_placed >= cool_wanted", "Fewer cooling channels fit than wanted: baffles or bubblers are needed.", 0),
    ("mould", "Draft on all walls", "draft_left_cm2 < 1", "Some wall area still has less draft than required.", 0),
    ("mould", "Toolmaker: steel grades and hardness suit the part material and the run", "", "", 1),
    ("mould", "Toolmaker: parting line, gate position and venting accepted", "", "", 1),
    ("mould", "Toolmaker: ejection (pin positions on the part, stroke) accepted", "", "", 1),
    ("mould", "Toolmaker: cooling layout accepted for the heat load", "", "", 1),
    ("mould", "Toolmaker: slides, lifters and angle pins (strokes, locks) accepted", "", "", 0),
    ("mould", "Toolmaker: every drawing matches its 3D file (STEP checksum on the drawing)", "", "", 1),
    ("sheet_metal", "All solids are valid and no two parts overlap", "check_errors == 0", "The overlap / validity check found errors: see the Checks tab.", 1),
    ("sheet_metal", "Overlap warnings reviewed", "check_warnings == 0", "The overlap check has warnings: look at each and say why it is acceptable.", 0),
    ("sheet_metal", "A press takes every stage (force and bolster)", "press_fit == 1", "No press takes the force and die set of a stage: split the operations or use a larger press.", 1),
    ("sheet_metal", "Structural check (FEA) of the die block is within its limits", "fea_ok == 1", "The structural check was not run or is over a limit: thicken the die block.", 0),
    ("sheet_metal", "No undercut against the forming direction", "form_undercuts == 0", "A forming stage has an undercut that needs a cam or a pad-and-wipe tool.", 1),
    ("sheet_metal", "All wanted stripper springs are placed", "springs_placed >= springs_wanted", "Fewer springs fit than the stripping force needs: use stronger springs or a larger die set.", 0),
    ("sheet_metal", "Toolmaker: die clearance, steel grade and hardness suit the sheet material", "", "", 1),
    ("sheet_metal", "Toolmaker: shut height and press daylight, feed direction and strip layout accepted", "", "", 1),
    ("sheet_metal", "Toolmaker: pilots, stock lifters, scrap and slug removal accepted", "", "", 0),
    ("sheet_metal", "Toolmaker: every drawing matches its 3D file (STEP checksum on the drawing)", "", "", 1),
    ("foundry", "All solids are valid and no two parts overlap", "check_errors == 0", "The overlap / validity check found errors: see the Checks tab.", 1),
    ("foundry", "Pattern is made with the shrinkage and machining allowance of the alloy", "pattern_ok == 1", "The pattern could not be oversized: see the notes.", 1),
    ("foundry", "Gating and riser sized and placed", "gating_ok == 1", "The gating could not be placed on the pattern.", 0),
    ("foundry", "Toolmaker / foundry: parting line, core prints and cores accepted", "", "", 1),
    ("foundry", "Toolmaker / foundry: gating, riser and chill layout accepted for the alloy", "", "", 1),
    ("foundry", "Toolmaker: every drawing matches its 3D file (STEP checksum on the drawing)", "", "", 1),
    ("mould", "The tool suits the machine you typed (tie bars, platen, mould height, opening, tonnage)", "machine_fit != 0", "Part of the typed machine does not suit the tool: see the Machine tab for the numbers.", 1),
    ("mould", "Production: the machine (typed or recommended) is available for this tool", "", "", 1),
    ("sheet_metal", "The press you typed suits the die (tonnage, bolster, shut height, stroke)", "machine_fit != 0", "Part of the typed press does not suit the die: see the Machine tab for the numbers.", 1),
    ("sheet_metal", "Production: the press (typed or recommended) is available for this die", "", "", 1),
    ("foundry", "The pattern set suits the flask you typed", "machine_fit != 0", "The typed flask is too small for the match plate or too low: see the Machine tab.", 0),
]


def seed() -> int:
    d = mould_db.tables()
    have = {(r["tool_group"], r["step"]) for r in d["review_items"]}
    n = 0
    step = {}
    for g, text, check, msg, blocking in SEED:
        step[g] = step.get(g, 0) + 1
        if (g, step[g]) in have:
            continue
        d["review_items"].append({"tool_group": g, "step": step[g], "text": text, "auto_check": check, "fail_message": msg, "blocking": blocking,
                                  "is_example": 1, "notes": EXAMPLE})
        n += 1
    if n:
        mould_db.write(d)
    return n


def validate(clean: dict) -> None:
    env = {k: 1.0 for k in FACTS}
    for i, r in enumerate(clean.get("review_items", []), start=2):
        if r["auto_check"]:
            try:
                formula.evaluate(r["auto_check"], env)
            except formula.FormulaError as exc:
                raise mould_db.MouldDbError(f"Review checklist row {i}, check: {exc}") from None
            except ArithmeticError:
                pass


def _eval(check: str, facts: dict) -> bool:
    env = {k: 0.0 for k in FACTS} | {k: float(v) for k, v in facts.items() if isinstance(v, (int, float, bool))}
    try:
        return bool(formula.evaluate(check, env))
    except (ArithmeticError, formula.FormulaError):
        return False


def sync(conn, design_id: int, group: str, facts: dict) -> None:
    """Create the checklist of a design (once) and re-evaluate its automatic rows. Manual decisions are kept."""
    rows = sorted((r for r in mould_db.tables()["review_items"] if r["tool_group"] == group), key=lambda r: r["step"])
    have = {r["step"]: dict(r) for r in conn.execute(select(db.tool_reviews).where(db.tool_reviews.c.design_id == design_id)).mappings()}
    for r in rows:
        if r["step"] not in have:
            conn.execute(db.tool_reviews.insert().values(design_id=design_id, step=r["step"], text=r["text"], kind="auto" if r["auto_check"] else "manual",
                                                         blocking=int(bool(r["blocking"])), status="open", detail=""))
    have = {r["step"]: dict(r) for r in conn.execute(select(db.tool_reviews).where(db.tool_reviews.c.design_id == design_id)).mappings()}
    for r in rows:
        cur = have.get(r["step"])
        if not cur or not r["auto_check"]:
            continue
        passed = _eval(r["auto_check"], facts)
        status = "ok" if passed else ("waived" if cur["status"] == "waived" and cur["comment"] else "issue")
        conn.execute(update(db.tool_reviews).where(db.tool_reviews.c.id == cur["id"]).values(
            status=status, detail="" if passed else r["fail_message"], text=r["text"], blocking=int(bool(r["blocking"]))))


def items(conn, design_id: int) -> list[dict]:
    rows = conn.execute(select(db.tool_reviews).where(db.tool_reviews.c.design_id == design_id).order_by(db.tool_reviews.c.step)).mappings().all()
    return [{**dict(r), "at": r["at"].isoformat() if r["at"] else None} for r in rows]


def decide(conn, design_id: int, item_id: int, status: str, comment: str, user: str) -> dict:
    if status not in ("ok", "issue", "na", "waived"):
        raise ValueError("Status must be ok, issue, na or waived.")
    row = conn.execute(select(db.tool_reviews).where((db.tool_reviews.c.id == item_id) & (db.tool_reviews.c.design_id == design_id))).mappings().first()
    if not row:
        raise ValueError("Review item not found.")
    if status in ("issue", "waived", "na") and not comment.strip():
        raise ValueError("Say why (a comment is needed for issue, waived and not applicable).")
    if row["kind"] == "auto" and status == "ok" and row["status"] != "ok":
        raise ValueError("An automatic check cannot be signed off while it fails: correct the design, or waive it with a reason.")
    conn.execute(update(db.tool_reviews).where(db.tool_reviews.c.id == item_id).values(status=status, comment=comment.strip(), by=user, at=datetime.utcnow()))
    return dict(conn.execute(select(db.tool_reviews).where(db.tool_reviews.c.id == item_id)).mappings().one())


def blockers(conn, design_id: int) -> list[str]:
    return [f"{r['text']} ({r['status']})" for r in items(conn, design_id) if r["blocking"] and r["status"] not in ("ok", "na", "waived")]
