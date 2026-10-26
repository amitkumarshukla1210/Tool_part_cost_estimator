"""A tolerance on every dimension of the tool detail drawings, in mm or µm (roadmap stage 32).

The defaults come from the Design rules of the part type (Mould & die database), so the drawing says what the design already
assumes, and the limits of a fit from the new table *Fit tolerances* (ISO 286):

    overall length / width        general tolerance (ISO 2768 class of the drawing, by size: General tolerances)
    thickness of a plate          plate_thk_tol (e.g. ±0.02); other parts: general
    fitted hole (kind fit)        the hole fit in its label (H7 of "m6 / H7"), limits from Fit tolerances; position: position_tol
    tapped hole                   thread_class (6H)
    other holes (through, c'bore) hole_clear_tol (general = ISO 2768 by the diameter); position: general by the coordinate
    opening (wire cut, profile)   the opening's own tolerance (die_opening_tol), else general
Every one can be changed per dimension (L, W, H, H1, H1@pos, O1 …) on the part panel or in the Excel drawing data sheet: `general`,
`class` (the fit of the label), a fit (H7, g6, k6 …), ±0.02, +0.02/-0.01 or a thread class (6H). Shown in mm or µm per part.
"""

from __future__ import annotations

import re

from . import auth, mould_db

FIT_RANGES = ((0, 3), (3, 6), (6, 10), (10, 18), (18, 30), (30, 50), (50, 80), (80, 120), (120, 180), (180, 250), (250, 315), (315, 400), (400, 500))
_IT = {6: (6, 8, 9, 11, 13, 16, 19, 22, 25, 29, 32, 36, 40), 7: (10, 12, 15, 18, 21, 25, 30, 35, 40, 46, 52, 57, 63),
       8: (14, 18, 22, 27, 33, 39, 46, 54, 63, 72, 81, 89, 97)}
_FD = {"g": (-2, -4, -5, -6, -7, -9, -10, -12, -14, -15, -17, -18, -20), "f": (-6, -10, -13, -16, -20, -25, -30, -36, -43, -50, -56, -62, -68),
       "k": (0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 5), "m": (2, 4, 6, 7, 8, 9, 11, 13, 15, 17, 20, 21, 23)}
FIT_EXAMPLE = "EXAMPLE - ISO 286-2 values as remembered: check them against your copy of the standard"
NEW_RULES = {"thread_class": ("6H", "Tapped holes: thread tolerance class on the detail drawing (stage 32)"),
             "hole_clear_tol": ("general", "Through / counterbored holes: size tolerance (general = ISO 2768 by the diameter, or a fit / ± value)")}
UNITS = ("mm", "µm")
KEY_RE = re.compile(r"(L|W|H|H\d+(@pos)?|O\d+)")
SPEC_RE = re.compile(r"^(general|class|[A-Za-z]{1,2}\d{1,2}|±\d*\.?\d+|[+-]?\d*\.?\d+/[+-]?\d*\.?\d+|\d[A-Ha-h])$")


# ---------- master data ----------

def fit_rows() -> list[dict]:
    rows = []
    for i, (lo, hi) in enumerate(FIT_RANGES):
        it6, it7, it8 = _IT[6][i], _IT[7][i], _IT[8][i]
        fits = {"H6": (it6, 0), "H7": (it7, 0), "H8": (it8, 0), "h6": (0, -it6), "h7": (0, -it7), "g6": (_FD["g"][i], _FD["g"][i] - it6),
                "f7": (_FD["f"][i], _FD["f"][i] - it7), "k6": (_FD["k"][i] + it6, _FD["k"][i]), "m6": (_FD["m"][i] + it6, _FD["m"][i])}
        rows += [{"fit": f, "from_mm": lo, "to_mm": hi, "upper_um": f"{u:+d}" if u else "0", "lower_um": f"{l:+d}" if l else "0",
                  "is_example": True, "notes": FIT_EXAMPLE} for f, (u, l) in fits.items()]
    return rows


def seed() -> int:
    """Add the missing Fit tolerances rows and the new Design rules rows (existing rows are never changed)."""
    d = mould_db.tables()
    have = {(r["fit"], r["from_mm"]) for r in d["fit_tolerances"]}
    new = [r for r in fit_rows() if (r["fit"], r["from_mm"]) not in have]
    d["fit_tolerances"] += new
    types = sorted({r["part_type"] for r in d["design_rules"]})
    rules = {(r["part_type"], r["parameter"]) for r in d["design_rules"]}
    add = [{"part_type": pt, "parameter": k, "value": None, "text": v, "unit": "", "description": desc, "is_example": True}
           for pt in types for k, (v, desc) in NEW_RULES.items() if (pt, k) not in rules]
    d["design_rules"] += add
    if new or add:
        mould_db.write(d)
    return len(new) + len(add)


def validate(clean: dict) -> None:
    for i, r in enumerate(clean.get("fit_tolerances", []), start=2):
        try:
            u, lo = float(r["upper_um"]), float(r["lower_um"])
        except ValueError:
            raise mould_db.MouldDbError(f"Fit tolerances row {i}: deviations are numbers in µm with their sign (+15, -7, 0).") from None
        if u < lo or r["to_mm"] <= r["from_mm"]:
            raise mould_db.MouldDbError(f"Fit tolerances row {i}: upper must not be below lower, 'to' above 'from'.")


# ---------- one tolerance ----------

def _fits() -> list[dict]:
    return mould_db.tables()["fit_tolerances"] or fit_rows()


def fit_limits(fit: str, size: float) -> tuple[float, float] | None:
    """(upper, lower) deviation in mm of an ISO 286 tolerance class at a size."""
    for r in _fits():
        if r["fit"] == fit and (r["from_mm"] < size <= r["to_mm"] or (r["from_mm"] == 0 and 0 < size <= r["to_mm"])):
            return float(r["upper_um"]) / 1000, float(r["lower_um"]) / 1000
    return None


def general(cls: str, size: float) -> float | None:
    from .drawing_data import tolerance_table
    rows = tolerance_table(cls, "linear")
    for r in rows:
        if r["from"] < size <= r["to"]:
            return r["value"]
    if rows:
        return rows[0]["value"] if size <= rows[0]["from"] else rows[-1]["value"]
    return None


def check_spec(spec) -> str:
    s = str(spec).strip().replace("+/-", "±").replace("+-", "±").replace(" ", "")
    if re.fullmatch(r"\d*\.?\d+", s):
        s = "±" + s                                   # a bare number is a ± value
    if not SPEC_RE.match(s):
        raise auth.AuthError(f"Tolerance '{spec}' is not understood: write general, class, a fit (H7, g6), ±0.02, +0.02/-0.01 or a thread class (6H).", 400)
    if re.fullmatch(r"[A-Za-z]{1,2}\d{1,2}", s) and s not in {r["fit"] for r in _fits()}:
        raise auth.AuthError(f"Fit {s} is not in Mould & die database → Fit tolerances.", 400)
    return s


def resolve(spec: str, size: float, cls: str, label: str = "") -> dict:
    """{spec, kind (general / fit / sym / asym / thread / text), upper, lower (mm)} of a tolerance at a nominal size."""
    s = str(spec or "general").strip().replace("+/-", "±").replace("+-", "±").replace(" ", "").replace("−", "-")
    if s == "class":
        m = re.search(r"\b([A-Z]\d{1,2})\b", label or "")
        s = m.group(1) if m else "general"
    if s == "general":
        v = general(cls, size)
        return {"spec": f"ISO 2768-{cls}", "kind": "general", "upper": v, "lower": -v if v is not None else None}
    if re.fullmatch(r"\d[A-Ha-h]", s):
        return {"spec": s, "kind": "thread", "upper": None, "lower": None}
    if re.fullmatch(r"[A-Za-z]{1,2}\d{1,2}", s):
        lim = fit_limits(s, size)
        return {"spec": s, "kind": "fit", "upper": lim[0] if lim else None, "lower": lim[1] if lim else None}
    try:
        if s.startswith("±"):
            v = float(s[1:])
            return {"spec": s, "kind": "sym", "upper": v, "lower": -v}
        if "/" in s:
            a, b = (float(x) for x in s.split("/"))
            return {"spec": s, "kind": "asym", "upper": max(a, b), "lower": min(a, b)}
    except ValueError:
        pass
    return {"spec": s, "kind": "text", "upper": None, "lower": None}


def _num(v: float, unit: str) -> str:
    if unit == "µm":
        n = round(v * 1000)
        return "0" if n == 0 else f"{n:+d}"
    return "0" if abs(v) < 1e-9 else f"{v:+.3f}".rstrip("0").rstrip(".")


def fmt(t: dict, unit: str = "mm") -> str:
    """Text after a dimension: ±0.2, H7 +0.015/0, +15/0 µm, 6H …"""
    if t["kind"] in ("thread", "text") or t["upper"] is None:
        return t["spec"]
    u = " µm" if unit == "µm" else ""
    if abs(t["upper"] + t["lower"]) < 1e-9:
        body = f"±{abs(round(t['upper'] * 1000)) if unit == 'µm' else _num(t['upper'], 'mm').lstrip('+')}{u}"
    else:
        body = f"{_num(t['upper'], unit)}/{_num(t['lower'], unit)}{u}"
    return f"{t['spec']} {body}" if t["kind"] == "fit" else body


# ---------- every dimension of one part ----------

def for_component(c, part_type: str, cls: str, overrides: dict | None = None, unit: str = "mm") -> dict:
    """{"unit", "overall": {L, W, H}, "holes": {H1: {size, pos}}, "openings": {O1: {size}}}; each value has text, spec, changed."""
    rules = {k: (r["text"] or (f"{r['value']:g}" if r["value"] is not None else "")) for k, r in mould_db.design_rules(part_type).items()} if part_type else {}
    ov = overrides or {}

    def t(spec, size, key, label=""):
        r = resolve(ov.get(key) or spec, size, cls, label)
        r["text"], r["key"], r["changed"] = fmt(r, unit), key, key in ov
        return r

    L, W, H = c.size
    out = {"unit": unit, "overall": {"L": t("general", L, "L"), "W": t("general", W, "W"),
                                     "H": t(rules.get("plate_thk_tol") or "general" if c.drawing == "plate" else "general", H, "H")},
           "holes": {}, "openings": {}}
    for i, h in enumerate(c.holes, start=1):
        key = f"H{i}"
        if h["kind"] == "fit":
            size = t("class", h["d"], key, h.get("label", ""))
            pos = t(rules.get("position_tol") or "general", max(abs(h["x"]), abs(h["y"])) or 1, key + "@pos")
        else:
            size = t(rules.get("thread_class") or "6H" if h["kind"] == "tap" else rules.get("hole_clear_tol") or "general", h["d"], key)
            pos = t("general", max(abs(h["x"]), abs(h["y"])) or 1, key + "@pos")
        out["holes"][key] = {"size": size, "pos": pos}
    for i, o in enumerate(c.openings, start=1):
        key = f"O{i}"
        xs = [p[0] for p in o.get("pts") or []] or [0]
        ys = [p[1] for p in o.get("pts") or []] or [0]
        own = (o.get("tol") or rules.get("die_opening_tol") or "general")
        try:
            own = check_spec(own)
        except auth.AuthError:
            own = "general"
        out["openings"][key] = {"size": t(own, max(max(xs) - min(xs), max(ys) - min(ys)) or 1, key), "label": o.get("label", "")}
    return out


def rows(dims: dict, c) -> list[dict]:
    """Flat list for the form and the Excel sheet: [{key, what, tolerance, changed}]."""
    out = [{"key": k, "what": {"L": "Overall length", "W": "Overall width", "H": "Thickness / height"}[k], "tolerance": v["text"], "changed": v["changed"]}
           for k, v in dims["overall"].items()]
    for i, h in enumerate(c.holes, start=1):
        k = f"H{i}"
        out.append({"key": k, "what": f"Hole Ø{h['d']:g} {h.get('label') or h['kind']}"[:60], "tolerance": dims["holes"][k]["size"]["text"],
                    "changed": dims["holes"][k]["size"]["changed"]})
        out.append({"key": k + "@pos", "what": f"Hole {k} position (X, Y)", "tolerance": dims["holes"][k]["pos"]["text"],
                    "changed": dims["holes"][k]["pos"]["changed"]})
    for k, o in dims["openings"].items():
        out.append({"key": k, "what": f"Opening {k} {o['label']}"[:60], "tolerance": o["size"]["text"], "changed": o["size"]["changed"]})
    return out


def clean_overrides(v) -> dict:
    out = {}
    for key, spec in (v or {}).items():
        if not KEY_RE.fullmatch(str(key)):
            raise auth.AuthError(f"'{key}' is not a dimension of a detail drawing (L, W, H, H1, H1@pos, O1 …).", 400)
        if spec not in (None, ""):
            out[str(key)] = check_spec(spec)
    return out


def clean_unit(v) -> str:
    s = str(v or "").strip().lower()
    if s in ("µm", "um", "μm", "micron", "microns"):
        return "µm"
    if s == "mm":
        return "mm"
    raise auth.AuthError("Tolerances are shown in mm or µm.", 400)
