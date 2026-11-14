"""Fin parts in the part register (roadmap stage 60): a fin pack is a part like a moulded or pressed part.

    part        process with part type 'fin' (Part register setup → Processes: Fin press (heat exchanger)), material = a fin
                foil grade, revision = the fin STEP (one fin). One part = ONE FIN PACK (one coil's fins); annual volume = packs per
                year; BOM quantity = packs per product (indoor 1, outdoor 1, ...)
    fin spec    read from the revision's STEP (stage 58: collar Ø, pitches, rows, holes, stagger, thickness, FPI, pattern hint),
                die size proposed from the press, then what you typed on the part (Fin inputs: pack length, FPI, pattern,
                rows, progressions, press, SPM, foil of one AC set ...) wins
    RM          the foil part of the fin pack cost (Cost formulas fin_part: gross foil × rate − scrap), stored as an RM version
    tool        the fin die (stage 57 tool cost engine, part type fin), stored as a tool cost version (CAPEX = × dies)
    part cost   the fin pack cost (Cost formulas fin_part) with the stored fin die version grafted in, stored as a part cost
    design      the fin die design of stage 58 and the FEA of stage 59 on the part panel; files saved with revisions (stage 47)

Everything is traced to master data and approved rates; no number is written here.
"""

from __future__ import annotations

import hashlib
import json

from . import costing_setup, fin_design, fin_die, mould_db, register_setup

PART_TYPE = fin_die.PART_TYPE
PROCESS = ("fin_press", "Fin press (heat exchanger fin pack)")
TYPED = ("pattern", "tube_od_mm", "hole_d_mm", "row_pitch_mm", "hole_pitch_mm", "fin_rows", "fin_holes", "foil_t_mm", "fpi",
         "staggered", "die_rows", "progressions", "foil_width_mm", "pack_length_mm", "press", "spm", "foil_kg_per_ac_set", "tools_count")
_READ: dict = {}


class FinPartError(ValueError):
    pass


def seed() -> int:
    """Add the process 'Fin press (heat exchanger fin pack)' (existing rows are never changed)."""
    t = register_setup.tables()
    if any(p["code"] == PROCESS[0] for p in t["processes"]):
        return 0
    t["processes"].append({"code": PROCESS[0], "name": PROCESS[1], "part_type": PART_TYPE, "is_assembly": False,
                           "is_insert_moulding": False, "suggest_rule": "0", "sort_order": 8,
                           "notes": "Stage 60: one part = one fin pack; chosen by the fin foil material"})
    register_setup.write(t)
    return 1


def is_fin(d: dict) -> bool:
    proc = register_setup.processes().get(d.get("process") or "")
    return bool(proc) and proc["part_type"] == PART_TYPE


def _current_rev(d: dict) -> dict | None:
    return next((r for r in d["revisions"] if r["id"] == d.get("current_revision_id")), d["revisions"][0] if d["revisions"] else None)


def read_revision(d: dict) -> tuple[dict | None, dict | None]:
    """What the fin STEP of the current revision gives (kept per file), and the revision."""
    from . import register
    rev = _current_rev(d)
    if not rev or not rev.get("file_id"):
        return None, rev
    key = rev.get("sha256") or rev["file_id"]
    if key not in _READ:
        try:
            _READ[key] = fin_design.read_part(register.revision_file_bytes(rev), rev.get("original_name") or "fin.step")
        except fin_design.ReadError as exc:
            _READ[key] = {"error": str(exc)}
    return _READ[key], rev


def spec_for(part_id: int, country: str | None = None) -> dict:
    """The confirmed fin spec of a part: read from the STEP, proposed die size, your typed Fin inputs, part data."""
    from . import register
    d = register.part_detail(part_id, with_rm=False)
    if not is_fin(d):
        raise FinPartError("This part is not a fin part (process with part type fin).")
    read, rev = read_revision(d)
    typed = dict(d.get("fin_inputs") or {})
    file_read = typed.pop("read", None)                       # a DXF / PDF fin drawing read on the part (no STEP)
    src = read if read and "error" not in read else file_read
    if not src and not typed.get("hole_d_mm"):
        why = (read or {}).get("error") or "Upload the fin STEP as the part's revision (or a fin DXF / PDF under Fin inputs)."
        raise FinPartError(why)
    spec = fin_design.to_spec(src or {}, fin_die.default_spec())
    spec["material"] = d["material"] or spec["material"]
    for k in TYPED:
        if typed.get(k) not in (None, ""):
            spec[k] = typed[k]
    volume, volume_note = register._annual_volume(d)
    if volume:
        spec["packs_per_year"] = max(1, round(volume))
    if d.get("programme_life_years"):
        spec["programme_years"] = d["programme_life_years"]
    spec["country"] = (country or d.get("tool_country") or d.get("country") or register_setup.settings()["default_country"]).upper()
    if d.get("costing_month"):
        spec["as_of"] = d["costing_month"]
    proposal = None
    if not all(typed.get(k) for k in ("die_rows", "progressions")):
        proposal = fin_design.propose(spec)
        for k in ("die_rows", "progressions"):
            if not typed.get(k):
                spec[k] = proposal[k]
        if not typed.get("foil_width_mm"):
            spec["foil_width_mm"] = proposal["foil_width_mm"]
    s = fin_die.normalise(spec)
    s["as_of"] = spec.get("as_of")
    return {"spec": s, "read": src, "typed": typed, "proposal": proposal, "volume_note": volume_note, "part": d, "rev": rev}


def _hash(x) -> str:
    return hashlib.sha1(json.dumps(x, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _formulas() -> str:
    setup = costing_setup.tables()
    return _hash([r for k in ("cost_formulas", "formula_inputs") for r in setup[k] if r["scope"] in costing_setup.FIN_SCOPES])


def tool(part_id: int, country: str | None = None) -> dict:
    """The fin die of the part, shaped as a tool cost version."""
    from . import register
    f = spec_for(part_id, country)
    s, d, rev = f["spec"], f["part"], f["rev"]
    r = fin_die.die_cost(s)
    r["key"] = {"revision_id": rev["id"] if rev else None, "part_type": PART_TYPE, "material": d["material"], "country": r["country"],
                "as_of": r["as_of"], "inputs": f["typed"], "spec": _hash(s), "tools_count": s["tools_count"],
                "rates": sorted(x["id"] for x in r["rates_used"]), "master": register._tool_master_hash(PART_TYPE),
                "overrides": (d.get("trace_overrides") or {}).get("tool") or {}}
    r["revision"] = {"id": rev["id"] if rev else None, "rev": rev["rev"] if rev else ""}
    r["process"] = d["process"]
    r["fin_spec"] = s
    r["stage_c"] = {"note": f"{s['packs_per_year']:,.0f} fin packs / yr ({f['volume_note']}), {s['programme_years']:g} programme years; "
                            f"{s['tools_count']} fin die(s); press {(r['trial']['machine'] or {}).get('machine_id', '-')}"}
    return r


def _part(f: dict, die: dict) -> tuple[dict, object]:
    return fin_die.part_cost(f["spec"], die, keep_trace=True)


def rm(part_id: int, country: str | None = None) -> dict:
    """The foil RM of one fin pack (the rm_cost step of the fin pack cost), shaped as an RM version."""
    from . import rate_engine
    f = spec_for(part_id, country)
    s, d, rev = f["spec"], f["part"], f["rev"]
    die = fin_die.die_cost(s)
    out, t = _part(f, die)
    fx = rate_engine.fx_to_inr(t, out["currency"], out["as_of"])
    t.compute("rm:inr", "Foil RM per fin pack in INR", "value * fx", "INR", money=True, names={"value": "calc:rm_cost", "fx": fx})
    r = t.to_dict("calc:rm_cost")
    g, net = t.value("calc:gross_kg") * 1000, t.value("calc:net_kg") * 1000
    r |= {"value": t.value("calc:rm_cost"), "value_inr": t.value("rm:inr"), "country": out["country"], "currency": out["currency"],
          "as_of": out["as_of"], "material": d["material"], "family": PART_TYPE, "process": d["process"], "missing": out["missing"],
          "named": {"gross_g": g, "returns_g": g - net, "input_g": g, "material_yield_pct": 100 * net / g if g else 0, "net_g": net},
          "warnings": [], "blank": None, "stock": None, "fin_spec": s,
          "revision": {"id": rev["id"] if rev else None, "rev": rev["rev"] if rev else ""}}
    r["key"] = {"revision_id": rev["id"] if rev else None, "material": d["material"], "family": PART_TYPE, "country": out["country"],
                "as_of": out["as_of"], "inputs": f["typed"], "spec": _hash(s), "net_weight_g": round(net, 6),
                "rates": sorted(x["id"] for x in r["rates_used"]), "formulas": _formulas(),
                "overrides": (d.get("trace_overrides") or {}).get("rm") or {}}
    return r


def piece(part_id: int, country: str | None = None) -> dict:
    """The fin pack cost with the stored fin die version (or the live one for another country), shaped as a part cost."""
    from . import register
    f = spec_for(part_id, country)
    d, rev = f["part"], f["rev"]
    rev_id = rev["id"] if rev else None
    if country:
        die = fin_die.die_cost(f["spec"])
        tool_v, rm_v = "live", "live"
    else:
        tv = next((v for v in register.tool_versions(part_id) if v["revision_id"] == rev_id), None)
        rv = next((v for v in register.rm_versions(part_id) if v["revision_id"] == rev_id), None)
        if not rv:
            raise FinPartError("Calculate the RM cost of the current revision first.")
        if not tv:
            raise FinPartError("Calculate the tool cost (fin die) of the current revision first (it selects the fin press).")
        die = register.tool_trace(part_id, tv["version"])
        tool_v, rm_v = tv["version"], rv["version"]
    out, t = _part(f, die)
    # the names the landed cost / country comparison (stages 11, 48, 50) read from every part cost: traced copies of the fin's own
    cur = out["currency"]
    t.compute("in:rm_cost", "Net RM cost per fin pack", "rm_cost", cur, money=True, names={"rm_cost": "calc:rm_cost"},
              description="The foil RM step of the fin pack cost")
    t.compute("in:total_weight_kg", "Fin pack weight (net)", "net_kg", "kg", names={"net_kg": "calc:net_kg"})
    t.add_input("calc:secondary_cost", "Secondary operations", 0, cur, {"type": "base", "note": "A fin pack has no secondary operation"}, money=True)
    out["nodes"] = t.to_dict(out["root"])["nodes"]
    out |= {"part_type": PART_TYPE, "grade": "", "revision": {"id": rev_id, "rev": rev["rev"] if rev else ""}, "rm_version": rm_v,
            "tool_version": tool_v, "machine": out["press"], "fin_spec": f["spec"],
            "inputs": [], "core_out": None,
            "tool_summary": {"value": die["value"], "value_inr": die["value_inr"], "capex_inr": die.get("capex_inr"), "currency": die["currency"],
                             "weight_kg": die["nodes"]["tool_weight"]["value"] if "tool_weight" in die["nodes"] else 0.0}}
    out["key"] = {"revision_id": rev_id, "rm": rm_v, "tool": tool_v, "inputs": f["typed"], "spec": _hash(f["spec"]),
                  "rates": sorted(x["id"] for x in out["rates_used"]), "formulas": _formulas(),
                  "overrides": (d.get("trace_overrides") or {}).get("piece") or {}}
    return out


MOVED_PROJECT = ("FINDIES", "Fin dies (moved from the Fin dies page)")


def move_saved_fin_dies() -> dict:
    """Stage 60: every fin die saved on the old Fin dies page becomes a fin part of the project 'Fin dies (moved ...)' with its spec
    (as Fin inputs) and a fin STEP (the uploaded one, else one made from the spec) as revision A. Idempotent (moved_part_id)."""
    from sqlalchemy import select
    from . import projects_db as db, register
    with db.engine().connect() as conn:
        todo = [dict(r._mapping) for r in conn.execute(select(db.fin_dies).where(db.fin_dies.c.moved_part_id.is_(None)))]
    if not todo:
        return {"moved": 0}
    with db.engine().connect() as conn:
        proj = conn.execute(select(db.projects.c.id).where(db.projects.c.code == MOVED_PROJECT[0])).first()
    pid = proj[0] if proj else register.create_project({"code": MOVED_PROJECT[0], "name": MOVED_PROJECT[1]})["id"]
    moved = 0
    for rec in todo:
        spec = fin_die.normalise(rec["spec"])
        step, name = None, f"{rec['name']}.step"
        pf = rec.get("part_file") or {}
        if pf.get("file_id") and str(pf.get("name", "")).lower().endswith((".step", ".stp")):
            from . import file_store
            with db.engine().connect() as conn:
                row = conn.execute(select(db.files).where(db.files.c.id == pf["file_id"])).mappings().first()
            if row:
                step, name = file_store.path_of(dict(row)).read_bytes(), pf["name"]
        if step is None:
            step = fin_design.fin_step(spec)
        typed = {k: spec[k] for k in TYPED if k in spec and spec[k] not in (None, "")}
        values = {"name": rec["name"][:300], "material": spec["material"], "process": PROCESS[0], "annual_volume": int(spec["packs_per_year"]),
                  "programme_life_years": spec["programme_years"], "fin_inputs": typed}
        if spec.get("country"):
            values["country"] = spec["country"]
        with db.engine().begin() as conn:
            part_id, _new = register.upsert_part(conn, pid, f"FIN-{rec['id']}", values)
        register.new_revision_from_upload(part_id, step, name, "A", "Moved from the Fin dies page (stage 60)")
        with db.engine().begin() as conn:
            conn.execute(db.fin_dies.update().where(db.fin_dies.c.id == rec["id"]).values(moved_part_id=part_id))
        moved += 1
    return {"moved": moved, "project_id": pid}


def design(part_id: int) -> dict:
    """The fin die design (stage 58) of the part's confirmed fin spec; drawing numbers start with the part code."""
    from . import fin_die_draw
    f = spec_for(part_id)
    d = f["part"]
    des = fin_die_draw.build(f["spec"], d["id"], f"{d['part_code']} {d['name']}".strip())
    des["prefix"] = f"FD-{d['part_code']}"
    for i, p in enumerate(des["parts"], start=1):
        p["drawing"] = f"{des['prefix']}-{i:02d}"
    return des


def read_drawing(part_id: int, content: bytes, name: str) -> dict:
    """A fin DXF / PDF drawing for a fin part without a STEP: what is read is kept on the part (to confirm), the file stored."""
    from . import file_store, projects_db as db, register
    read = fin_design.read_part(content, name)
    with db.engine().begin() as conn:
        row = file_store.put(content, name, "fin_part", conn)
    read["file_id"] = row["id"]
    d = register.part_detail(part_id, with_rm=False)
    typed = dict(d.get("fin_inputs") or {})
    typed["read"] = read
    register.update_part(part_id, {"fin_inputs": typed})
    return summary(part_id)


def save_inputs(part_id: int, data: dict) -> dict:
    """Fin inputs typed on the part (only the known keys; blank = from the STEP / proposal)."""
    from . import register
    d = register.part_detail(part_id, with_rm=False)
    if not is_fin(d):
        raise FinPartError("This part is not a fin part.")
    clean = {k: data[k] for k in TYPED if k in data and data[k] not in (None, "")}
    if "read" in data and data["read"]:
        clean["read"] = data["read"]
    if "read" not in data and (d.get("fin_inputs") or {}).get("read"):
        clean["read"] = d["fin_inputs"]["read"]
    fin_die.normalise({**fin_die.default_spec(), **{k: v for k, v in clean.items() if k != "read"}})   # validates the values
    register.update_part(part_id, {"fin_inputs": clean})
    return summary(part_id)


def summary(part_id: int) -> dict:
    """What the part panel shows: the spec, what was read, the proposal, the typed inputs, or why there is none."""
    try:
        f = spec_for(part_id)
    except (FinPartError, fin_die.FinDieError, fin_design.ReadError) as exc:
        return {"ok": False, "problem": str(exc), "spec_fields": fin_die.SPEC}
    return {"ok": True, "spec": f["spec"], "read": f["read"], "typed": f["typed"], "proposal": f["proposal"],
            "spec_fields": fin_die.SPEC, "patterns": [p["pattern"] for p in mould_db.tables()["fin_patterns"]],
            "presses": sorted(fin_die.press_rows()), "default_press": fin_die.default_press()}
