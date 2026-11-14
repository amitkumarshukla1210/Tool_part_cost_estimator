"""FEA of the fin die (roadmap stage 59): the load-carrying fin die parts at the full press capacity.

    plates    real FEA (Gmsh + CalculiX, fea.check_part of stage 45) of the pierce sub-die plate (with its button holes), the
              first draw sub-die plate and the lower die plate (die set). Load = the press capacity (tonnage of the fin press of the
              design × g) on the plate's working area (one stroke: feed × foil width; the lower plate: the whole die area); support:
              the sub-die plates sit on their back face, the lower die plate rests on two strips along its long edges
              (fea_support_strip_mm). Limits fea_max_deflection_mm and fea_allow_stress_mpa (Design rules fin, EXAMPLE)
    punches   buckling by formula (draw, pierce & burr, ironing, reflare punches): load per punch = press capacity ÷ every working
              punch (holes per stroke × punch stations); free length = punch length × fea_punch_free_share; effective length
              K × free length (fea_punch_k: guided by the stripper); Euler P = π² E I ÷ (K L)², Johnson below the transition
              slenderness (yield fea_punch_yield_mpa); safety = P ÷ load ≥ fea_punch_sf_min; compressive stress ≤ fea_punch_allow_mpa
    failing   a plate that fails is analysed again with thicker plates (× fea_thicken_steps, rounded up to 5 mm) and the first
              thickness that passes is suggested; a punch that fails gets the longest free length that passes. Only you change
              the Sizing rules.

Every run is stored (fin_fea_runs, append only) with its picture; the latest runs of the current fin spec go into the PO pack.
"""

from __future__ import annotations

import hashlib
import json
import math

from sqlalchemy import select

from . import fea, fin_die, fin_die_draw, mould_db
from . import projects_db as db

G = 9.80665
PT = fin_die.PART_TYPE
# Design rules of part type fin for the FEA (EXAMPLE until you replace them): name, value, text, unit, description
RULES = [
    ("fea_e_mpa", 210000, "", "MPa", "FEA: Young's modulus of the die steel"),
    ("fea_poisson", 0.3, "", "-", "FEA: Poisson's ratio of the die steel"),
    ("fea_mesh_mm", 20, "", "mm", "FEA: largest element size of the fin die plates"),
    ("fea_max_deflection_mm", 0.02, "", "mm", "FEA: largest allowed deflection of a fin die plate (fin dies work to ±0.005 mm)"),
    ("fea_allow_stress_mpa", 300, "", "MPa", "FEA: largest allowed von Mises stress of a fin die plate (PX-5 / P20 yield ÷ safety)"),
    ("fea_support_strip_mm", 100, "", "mm", "FEA: width of the press bed strips under the lower die plate, along its long edges"),
    ("fea_max_elements", 250000, "", "elements", "FEA: largest mesh the solver may get (about 1 GB per 130,000 elements)"),
    ("fea_mesh_per_circle", 6, "", "elements", "FEA: elements around a button hole (more = finer and slower)"),
    ("fea_parts", None, "Pierce sub-die plate, Draw sub-die plate, Lower die plate", "", "FEA: fin die parts checked"),
    ("fea_punch_k", 0.5, "", "-", "Punch buckling: effective length factor K (0.5 = guided by the stripper at both ends)"),
    ("fea_punch_free_share", 0.6, "", "× length", "Punch buckling: free (unguided) length as a share of the punch length"),
    ("fea_punch_yield_mpa", 2500, "", "MPa", "Punch buckling: compressive yield of the punch steel (HAP40 / SKH51 hardened)"),
    ("fea_punch_allow_mpa", 1200, "", "MPa", "Punch: largest allowed compressive stress"),
    ("fea_punch_sf_min", 3, "", "×", "Punch buckling: smallest safety factor (buckling load ÷ load per punch)"),
    ("fea_thicken_steps", None, "1.25, 1.5, 2", "", "A plate that fails is analysed again at these multiples of its thickness"),
    ("fea_lower_support", None, "full", "", "Lower die plate support: full = on the whole press table (the table is bigger than the die set and the "
     "slugs are blown out, no opening under the die); strips = two strips of fea_support_strip_mm along the long edges (on parallels)"),
    ("fea_slice_rows", 4, "", "rows", "Sub-die plates: FEA of a slice of this many rows (the holes repeat row by row and the load is even, "
     "so the slice deflects and is stressed as the whole plate; it carries its share of the press force)"),
]
PUNCHES = {"draw": "Draw punch", "pierce": "Pierce & burring punch", "iron": "Ironing punch", "reflare": "Reflare punch"}


class FinFeaError(ValueError):
    pass


def seed() -> int:
    d = mould_db.tables()
    have = {(r["part_type"], r["parameter"]) for r in d["design_rules"]}
    add = [{"part_type": PT, "parameter": k, "value": v, "text": text, "unit": unit, "description": f"{desc} (stage 59)", "is_example": True}
           for k, v, text, unit, desc in RULES if (PT, k) not in have]
    if add:
        d["design_rules"] += add
        mould_db.write(d)
    return len(add)


def rules() -> dict:
    R = fea.rules(PT)
    r = mould_db.design_rules(PT)
    for k, *_ in RULES:
        if k.startswith("fea_punch") or k in ("fea_thicken_steps", "fea_slice_rows", "fea_lower_support"):
            row = r.get(k)
            if row is None:
                raise FinFeaError(f"Mould & die database → Design rules has no {k} for fin (run the stage 59 seed).")
            R[k] = row["text"] if k in ("fea_thicken_steps", "fea_lower_support") else float(row["value"])
    if str(R["fea_lower_support"]).strip().lower() not in ("full", "strips"):
        raise FinFeaError("Design rules fin → fea_lower_support must be 'full' or 'strips'.")
    R["thicken"] = [float(x) for x in str(R["fea_thicken_steps"]).split(",") if x.strip()]
    return R


def spec_hash(spec: dict) -> str:
    return hashlib.sha1(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()[:16]


def capacity_n(des: dict) -> tuple[float, str]:
    m = des["die"]["trial"]["machine"]
    if not m:
        raise FinFeaError("The design has no fin press, so there is no press capacity to check with.")
    return float(m["tonnage_t"]) * 1000 * G, f"{m['machine_id']}: {m['tonnage_t']:g} t × g (full press capacity)"


# ---------------------------------------------------------------- punches (formula) ----------

def punch_checks(des: dict, R: dict | None = None) -> list[dict]:
    R = R or rules()
    force, how = capacity_n(des)
    kinds = [st["kind"] for st in des["stations"] if st["kind"] in PUNCHES]
    n = len(kinds) * des["die"]["die"]["holes_per_stroke"]
    load = force / n
    out = []
    for kind in dict.fromkeys(kinds):
        p = next(x for x in des["parts"] if x["name"] == PUNCHES[kind])
        d, length = p["dims"]
        E, K, sy = R["fea_e_mpa"], R["fea_punch_k"], R["fea_punch_yield_mpa"]
        L = length * R["fea_punch_free_share"]
        A, I = math.pi * d ** 2 / 4, math.pi * d ** 4 / 64
        r_g = math.sqrt(I / A)
        slender = K * L / r_g
        transition = math.sqrt(2 * math.pi ** 2 * E / sy)
        euler = math.pi ** 2 * E * I / (K * L) ** 2
        johnson = A * (sy - (sy * slender / (2 * math.pi)) ** 2 / E)
        pcr = euler if slender >= transition else johnson
        sf, stress = pcr / load, load / A
        ok = sf >= R["fea_punch_sf_min"] and stress <= R["fea_punch_allow_mpa"]
        # longest free length that keeps the safety factor (Euler), for a punch that fails
        l_max = math.sqrt(math.pi ** 2 * E * I / (R["fea_punch_sf_min"] * load)) / K
        out.append({"item": p["drawing"], "name": p["name"], "d_mm": round(d, 3), "free_mm": round(L, 1), "load_n": round(load, 1),
                    "load_how": f"{how} ÷ {int(n)} working punches ({len(kinds)} punch stations × {int(des['die']['die']['holes_per_stroke'])} holes)",
                    "slenderness": round(slender, 1), "transition": round(transition, 1), "method": "Euler" if slender >= transition else "Johnson",
                    "buckling_n": round(pcr, 0), "safety": round(sf, 2), "stress_mpa": round(stress, 1), "ok": ok,
                    "limits": {"sf_min": R["fea_punch_sf_min"], "allow_mpa": R["fea_punch_allow_mpa"]},
                    "formula": "P = π² E I ÷ (K L)² (Euler) or A (σy − (σy λ ÷ 2π)² ÷ E) (Johnson), λ = K L ÷ √(I ÷ A); safety = P ÷ load",
                    "inputs": {"E_mpa": E, "K": K, "L_free_mm": round(L, 2), "d_mm": d, "yield_mpa": sy},
                    "suggest": None if ok else (f"Guide the punch closer: free length ≤ {l_max:.1f} mm (now {L:.1f} mm)"
                                                if stress <= R["fea_punch_allow_mpa"] else
                                                f"Compressive stress {stress:.0f} MPa > {R['fea_punch_allow_mpa']:g} MPa: the press capacity is too high for these punches")})
    return out


# ---------------------------------------------------------------- plates (FEA) ----------

def _plate(L, W, H, holes=()):
    import cadquery as cq
    wp = cq.Workplane("XY").box(L, W, H, centered=False)
    if holes:
        by_d: dict = {}
        for x, y, d in holes:
            by_d.setdefault(round(d, 3), []).append((x, y))
        for d, pts in by_d.items():
            wp = wp.faces(">Z").workplane(origin=(0, 0, H)).pushPoints(pts).hole(d)
    return wp.val()


def targets(des: dict, slice_rows: float = 4, lower_support: str = "full") -> list[dict]:
    dd = des["dims"]
    sts = des["stations"]
    pick = []
    pierce = next((st for st in sts if st["kind"] == "pierce"), None)
    draw = next((st for st in sts if st["kind"] == "draw"), None)
    s = des["spec"]
    n = max(2, int(slice_rows))
    n += n % 2 if s["staggered"] else 0                    # whole stagger periods
    n = min(n, s["die_rows"])
    sw = n * s["row_pitch_mm"]
    for st, label in ((pierce, "Pierce sub-die plate"), (draw, "Draw sub-die plate")):
        if st:
            p = next(x for x in des["parts"] if x["no"] == st["subdie"])
            L, W, H = p["dims"]
            y0 = (W - dd["foil_w"]) / 2 + dd["trim"]           # first row edge
            holes = [(x, y - y0, d) for x, y, d in p["holes"] if y0 <= y < y0 + sw]
            pick.append({"key": label, "item": p["drawing"], "name": f"{label} (station {st['no']}, slice of {n} rows)", "dims": (L, sw, H),
                         "holes": holes, "patch": (des["die"]["die"]["feed_mm"], sw), "strip": None, "rule": "subdie_h_mm",
                         "share": sw / dd["foil_w"], "slice": f"{n} of {s['die_rows']} rows ({sw:g} of {dd['foil_w']:g} mm): load × {sw / dd['foil_w']:.4f}"})
    lower = next(x for x in des["parts"] if x["name"].startswith("Lower die plate"))
    L, W, H = lower["dims"]
    pick.append({"key": "Lower die plate", "item": lower["drawing"], "name": "Lower die plate (die set)", "dims": (L, W, H), "holes": lower["holes"],
                 "patch": (dd["die_l"], dd["die_w"]), "strip": str(lower_support).strip().lower() == "strips", "rule": f"Mould bases fin {des['die']['base']['size_code']} clamp_plates_mm",
                 "share": 1.0, "slice": ""})
    return pick


def check_plate(t: dict, force: float, R: dict, H: float | None = None) -> dict:
    L, W, H0 = t["dims"]
    H = H or H0
    shape = _plate(L, W, H, t["holes"])
    strip = R["fea_support_strip_mm"] if t["strip"] else None
    try:
        res = fea.check_part(shape, (L, W, H), force * t["share"], t["patch"], strip, R, f"{t['name']} · {H:g} mm")
        return res | {"slice": t["slice"], "press_force_n": round(force, 1)}
    except fea.FeaError as exc:
        raise FinFeaError(f"{t['name']}: {exc}") from None


def compute(des: dict, progress=None) -> tuple[list, list, str]:
    """The FEA of a fin die design (plates at the full press capacity, thicker when failing) and the punch buckling."""
    R = rules()
    av = fea.available()
    if not av["available"]:
        raise FinFeaError(av["message"])
    force, how = capacity_n(des)
    tg = [t for t in targets(des, R["fea_slice_rows"], R["fea_lower_support"]) if any(t["key"].lower().startswith(x) or x.startswith(t["key"].lower()) for x in R["parts"])]
    say = progress or (lambda pct, text: None)
    results = []
    for i, t in enumerate(tg):
        say(5 + 85 * i / max(len(tg), 1), f"FEA {t['name']} ({i + 1} of {len(tg)})")
        res = check_plate(t, force, R)
        res |= {"force_how": how, "thickness_mm": t["dims"][2], "rule": t["rule"], "suggest": None}
        if not res["ok"]:
            for f in R["thicken"]:
                H2 = math.ceil(t["dims"][2] * f / 5) * 5
                say(5 + 85 * (i + 0.5) / max(len(tg), 1), f"{t['name']}: trying {H2:g} mm")
                r2 = check_plate(t, force, R, H2)
                if r2["ok"]:
                    res["suggest"] = {"thickness_mm": H2, "max_deflection_mm": r2["max_deflection_mm"], "max_von_mises_mpa": r2["max_von_mises_mpa"],
                                      "text": f"{H2:g} mm passes ({r2['max_deflection_mm']:.4f} mm, {r2['max_von_mises_mpa']:.0f} MPa): change {t['rule']}"}
                    break
            else:
                res["suggest"] = {"thickness_mm": None, "text": f"Still failing at {math.ceil(t['dims'][2] * max(R['thicken']) / 5) * 5:g} mm: "
                                                                    "add support under the plate or check the load"}
        results.append((t, res))
    say(92, "Punch buckling")
    return results, punch_checks(des, R), how


def _store(table, owner: dict, h: str, results: list, punches: list, how: str) -> list[int]:
    from . import auth
    who = auth.username() or ""
    ids = []
    with db.engine().begin() as conn:
        for t, res in results:
            png = res.pop("png", None)
            ids.append(conn.execute(table.insert().values(**owner, spec_hash=h, item=t["item"], name=t["name"], kind="plate",
                                                          result=res, png=png, by=who)).inserted_primary_key[0])
        ids.append(conn.execute(table.insert().values(**owner, spec_hash=h, item="PUNCHES", name="Punch buckling", kind="punches",
                                                      result={"punches": punches, "force_how": how}, by=who)).inserted_primary_key[0])
    return ids


def run(fid: int, progress=None) -> dict:
    """FEA of a saved fin die (stage 59 page): every result stored."""
    rec = fin_die.get(fid)
    des = fin_die_draw.build(rec["spec"], fid, rec["name"])
    results, punches, how = compute(des, progress)
    return {"runs": _store(db.fin_fea_runs, {"fin_die_id": fid}, spec_hash(rec["spec"]), results, punches, how)}


def run_part(part_id: int, progress=None) -> dict:
    """Stage 60: FEA of a fin part's die (its confirmed fin spec); every result stored per part."""
    from . import fin_part
    des = fin_part.design(part_id)
    results, punches, how = compute(des, progress)
    return {"runs": _store(db.fin_fea_part_runs, {"part_id": part_id}, spec_hash(des["spec"]), results, punches, how)}


def _latest(table, col, owner_id: int, h: str) -> dict:
    with db.engine().connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(select(table.c.id, table.c.spec_hash, table.c.item, table.c.name, table.c.kind,
                                                              table.c.result, table.c.by, table.c.at)
                                                       .where(col == owner_id).order_by(table.c.id))]
    cur = {}
    for r in rows:
        if r["spec_hash"] == h:
            cur[r["item"]] = r | {"at": str(r["at"])[:19]}
    runs = list(cur.values())
    plates = [r for r in runs if r["kind"] == "plate"]
    punch = next((r for r in runs if r["kind"] == "punches"), None)
    ok = bool(runs) and all(r["result"]["ok"] for r in plates) and all(p["ok"] for p in (punch or {}).get("result", {}).get("punches", []))
    return {"available": fea.available(), "runs": runs, "ok": ok if runs else None, "out_of_date": bool(rows) and not runs, "count_all": len(rows)}


def latest_part(part_id: int, spec: dict) -> dict:
    return _latest(db.fin_fea_part_runs, db.fin_fea_part_runs.c.part_id, part_id, spec_hash(spec))


def picture_part(part_id: int, run_id: int) -> bytes:
    with db.engine().connect() as conn:
        r = conn.execute(select(db.fin_fea_part_runs.c.png).where(db.fin_fea_part_runs.c.id == run_id,
                                                                  db.fin_fea_part_runs.c.part_id == part_id)).first()
    if not r or not r[0]:
        raise FinFeaError("No picture for this FEA run.")
    return r[0]


def pictures_part(part_id: int, spec: dict) -> list[tuple[str, bytes]]:
    out = []
    for r in latest_part(part_id, spec)["runs"]:
        if r["kind"] == "plate":
            try:
                out.append((f"{r['item']}_FEA.png", picture_part(part_id, r["id"])))
            except FinFeaError:
                pass
    return out


def latest(fid: int) -> dict:
    """The latest FEA of the fin die's current spec (one per plate + punches), and whether older runs exist for another spec."""
    rec = fin_die.get(fid)
    h = spec_hash(rec["spec"])
    with db.engine().connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(select(db.fin_fea_runs.c.id, db.fin_fea_runs.c.spec_hash, db.fin_fea_runs.c.item,
                                                              db.fin_fea_runs.c.name, db.fin_fea_runs.c.kind, db.fin_fea_runs.c.result,
                                                              db.fin_fea_runs.c.by, db.fin_fea_runs.c.at)
                                                       .where(db.fin_fea_runs.c.fin_die_id == fid).order_by(db.fin_fea_runs.c.id))]
    cur = {}
    for r in rows:
        if r["spec_hash"] == h:
            cur[r["item"]] = r | {"at": str(r["at"])[:19]}
    runs = list(cur.values())
    plates = [r for r in runs if r["kind"] == "plate"]
    punch = next((r for r in runs if r["kind"] == "punches"), None)
    ok = bool(runs) and all(r["result"]["ok"] for r in plates) and all(p["ok"] for p in (punch or {}).get("result", {}).get("punches", []))
    return {"available": fea.available(), "runs": runs, "ok": ok if runs else None,
            "out_of_date": bool(rows) and not runs, "count_all": len(rows)}


def picture(fid: int, run_id: int) -> bytes:
    with db.engine().connect() as conn:
        r = conn.execute(select(db.fin_fea_runs.c.png).where(db.fin_fea_runs.c.id == run_id, db.fin_fea_runs.c.fin_die_id == fid)).first()
    if not r or not r[0]:
        raise FinFeaError("No picture for this FEA run.")
    return r[0]


def pictures(fid: int) -> list[tuple[str, bytes]]:
    out = []
    for r in latest(fid)["runs"]:
        if r["kind"] == "plate":
            try:
                out.append((f"{r['item']}_FEA.png", picture(fid, r["id"])))
            except FinFeaError:
                pass
    return out
