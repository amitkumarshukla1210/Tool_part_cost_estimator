"""Fin simulation (roadmap stage 61): strip progression, collar forming checks and collar forming FEA of a fin part, with a
report (PDF) and a video, saved as a simulation run of the part like every other simulation.

    checks      by formula (Design rules fin, EXAMPLE): hole-edge strain ln((collar Ø + t) ÷ pierce Ø) ≤ fin_edge_strain_max;
                draw depth per draw step ≤ fin_draw_step_max × collar Ø; collar height (fin pitch − t) ≥ fin_collar_min_mm;
                press: die force ≤ tonnage, SPM in the press range, feed ≤ press feed (sucking) length, foil width ≤ press
                material width, coil OD ≤ press coil OD
    FEA         CalculiX, nonlinear (NLGEOM) axisymmetric model of the foil around one hole (CAX4, pierce Ø to half the smaller
                pitch, fin_form_rings × fin_form_layers elements), elastic-plastic foil σ = K (ε0 + εp)^n (fin_foil_*), outer edge
                held, the pierced edge drawn up and turned into the collar wall (collar Ø, collar height). Results: largest
                equivalent plastic strain (the first fin_form_skip_rings element ring at the drawn edge carries the boundary
                condition itself and is left out) and collar wall thinning (the smaller principal strain in the r-z plane is the
                thickness strain; volume constancy −(hoop + meridional) gives the same) against fin_form_strain_max and fin_thinning_max_pct
    strip       one picture per station (plan of the strip at that station + the collar section after it) and a video of the
                strip feeding through the die (MP4, GIF without ffmpeg)
EXAMPLE material data and limits until you replace them with your foil supplier's data and your trials.
"""

from __future__ import annotations

import io
import math
import re
import subprocess
import tempfile
from pathlib import Path

from . import fea, fin_die, mould_db

PT = fin_die.PART_TYPE
RULES = [
    ("fin_edge_strain_max", 0.6, "", "-", "Collar: largest hole-edge strain ln((collar Ø + t) ÷ pierce Ø) of the foil (H24 / H26 aluminium)"),
    ("fin_draw_step_max", 0.15, "", "× collar Ø", "Collar: largest draw depth per draw step"),
    ("fin_collar_min_mm", 0.8, "", "mm", "Collar: smallest collar height (fin pitch − foil thickness) the die can form and reflare"),
    ("fin_foil_e_mpa", 70000, "", "MPa", "Forming FEA: Young's modulus of the fin foil"),
    ("fin_foil_nu", 0.33, "", "-", "Forming FEA: Poisson's ratio of the fin foil"),
    ("fin_foil_yield_mpa", 120, "", "MPa", "Forming FEA: yield strength of the fin foil (H24)"),
    ("fin_foil_k_mpa", 180, "", "MPa", "Forming FEA: strength coefficient K of the foil, σ = K (ε0 + εp)^n"),
    ("fin_foil_n", 0.08, "", "-", "Forming FEA: strain-hardening exponent n of the foil"),
    ("fin_form_strain_max", 1.2, "", "-", "Forming FEA: largest allowed equivalent plastic strain in the collar"),
    ("fin_thinning_max_pct", 50, "", "%", "Forming FEA: largest allowed collar wall thinning (collar wall at least half the foil; replace with your trials)"),
    ("fin_form_rings", 60, "", "elements", "Forming FEA: elements from the hole edge outward"),
    ("fin_form_layers", 3, "", "elements", "Forming FEA: elements through the foil thickness"),
    ("fin_form_skip_rings", 1, "", "rings", "Forming FEA: element rings at the drawn edge left out of the result (they carry the boundary condition)"),
]


class FinSimError(ValueError):
    pass


def seed() -> int:
    d = mould_db.tables()
    have = {(r["part_type"], r["parameter"]) for r in d["design_rules"]}
    add = [{"part_type": PT, "parameter": k, "value": v, "text": text, "unit": unit, "description": f"{desc} (stage 61)", "is_example": True}
           for k, v, text, unit, desc in RULES if (PT, k) not in have]
    if add:
        d["design_rules"] += add
        mould_db.write(d)
    return len(add)


def rules() -> dict:
    r = mould_db.design_rules(PT)
    miss = [k for k, *_ in RULES if k not in r]
    if miss:
        raise FinSimError(f"Mould & die database → Design rules has no {', '.join(miss)} for fin (run the stage 61 seed).")
    return {k: float(r[k]["value"]) for k, *_ in RULES} | {"is_example": any(r[k]["is_example"] for k, *_ in RULES)}


# ---------------------------------------------------------------- checks by formula ----------

def geometry(des: dict) -> dict:
    s = des["spec"]
    pierce = fin_die._param("fin_pierce_factor")["value"] * s["hole_d_mm"]
    pitch = 25.4 / s["fpi"]
    return {"d": s["hole_d_mm"], "t": s["foil_t_mm"], "d0": pierce, "pitch": pitch, "h": pitch - s["foil_t_mm"],
            "cell_r": min(s["row_pitch_mm"], s["hole_pitch_mm"]) / 2, "draw_steps": int(des["die"]["pattern"]["draw_steps"])}


def checks(des: dict, R: dict | None = None) -> list[dict]:
    R = R or rules()
    g = geometry(des)
    m, line = des["die"]["trial"]["machine"], des["die"]["trial"].get("line") or {}
    s = des["spec"]
    out = []

    def add(name, value, limit, unit, ok, formula, note=""):
        out.append({"name": name, "value": round(value, 4), "limit": limit, "unit": unit, "ok": bool(ok), "formula": formula, "note": note})
    edge = math.log((g["d"] + g["t"]) / g["d0"])
    add("Hole-edge strain", edge, f"≤ {R['fin_edge_strain_max']:g}", "-", edge <= R["fin_edge_strain_max"],
        "ln((collar Ø + t) ÷ pierce Ø)", f"pierce Ø {g['d0']:.2f} mm → collar Ø {g['d']:g} mm")
    step = g["h"] / max(g["draw_steps"], 1)
    lim = R["fin_draw_step_max"] * g["d"]
    add("Draw depth per draw step", step, f"≤ {lim:.3f}", "mm", step <= lim, "(fin pitch − t) ÷ draw steps", f"{g['draw_steps']} draw steps")
    add("Collar height", g["h"], f"≥ {R['fin_collar_min_mm']:g}", "mm", g["h"] >= R["fin_collar_min_mm"], "25.4 ÷ FPI − t", f"fin pitch {g['pitch']:.3f} mm")
    if m:
        f = des["die"]["trial"]["force_t"]
        add("Die force vs press tonnage", f, f"≤ {m['tonnage_t']:g}", "t", f <= m["tonnage_t"], "Cost formulas fin_force", m["machine_id"])
        spm = s["spm"] or min(fin_die._param("fin_spm")["value"] * des["die"]["pattern"]["spm_factor"], line.get("spm_max") or 1e9)
        add("Press speed", spm, f"{line.get('spm_min', 0):g}-{line.get('spm_max', 0):g}", "SPM", line.get("spm_min", 0) <= spm <= line.get("spm_max", 1e9),
            "typed SPM, else fin_spm × pattern factor")
        feed = des["die"]["die"]["feed_mm"]
        if line.get("feed_length_mm"):
            add("Feed per stroke vs press feed length", feed, f"≤ {line['feed_length_mm']:g}", "mm", feed <= line["feed_length_mm"], "progressions × hole pitch")
        fw = des["dims"]["foil_w"]
        add("Foil width vs press material width", fw, f"≤ {line.get('max_foil_width_mm', 0):g}", "mm", fw <= line.get("max_foil_width_mm", 0), "foil width")
    return out


# ---------------------------------------------------------------- collar forming FEA ----------

def _inp(g: dict, R: dict) -> tuple[str, dict]:
    nr, nt = int(R["fin_form_rings"]), int(R["fin_form_layers"])
    r0, r1, t, d, h = g["d0"] / 2, max(g["cell_r"], g["d0"] / 2 + 3 * g["t"]), g["t"], g["d"], g["h"]
    grid, lines = {}, ["*NODE"]
    nid = 0
    for i in range(nr + 1):
        r = r0 + (r1 - r0) * (i / nr) ** 1.6                    # finer at the hole edge
        for j in range(nt + 1):
            nid += 1
            grid[i, j] = nid
            lines.append(f"{nid},{r:.6f},{j * t / nt:.6f},0")
    lines.append("*ELEMENT,TYPE=CAX4,ELSET=E")
    eid = 0
    for i in range(nr):
        for j in range(nt):
            eid += 1
            lines.append(f"{eid},{grid[i, j]},{grid[i + 1, j]},{grid[i + 1, j + 1]},{grid[i, j + 1]}")
    E, nu, sy, K, n = R["fin_foil_e_mpa"], R["fin_foil_nu"], R["fin_foil_yield_mpa"], R["fin_foil_k_mpa"], R["fin_foil_n"]
    e0 = (sy / K) ** (1 / n)
    lines += ["*NSET,NSET=OUT", ",".join(str(grid[nr, j]) for j in range(nt + 1)), "*MATERIAL,NAME=FOIL", "*ELASTIC", f"{E},{nu}", "*PLASTIC"]
    for ep in (0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4, 0.7, 1.0, 1.5, 2.5):
        lines.append(f"{max(sy, K * (e0 + ep) ** n):.3f},{ep}")
    lines += ["*SOLID SECTION,ELSET=E,MATERIAL=FOIL", "*STEP,NLGEOM,INC=2000", "*STATIC", "0.02,1,1e-6,0.05", "*BOUNDARY", "OUT,1,2,0"]
    for j in range(nt + 1):                                  # the drawn edge: the thickness turns into the collar wall
        lines.append(f"{grid[0, j]},1,1,{(d / 2 + j * t / nt) - r0:.6f}")
        lines.append(f"{grid[0, j]},2,2,{h - j * t / nt:.6f}")
    lines += ["*EL PRINT,ELSET=E", "PEEQ", "*EL PRINT,ELSET=E", "E", "*NODE PRINT,NSET=NALL", "U", "*END STEP"]
    lines.insert(lines.index("*MATERIAL,NAME=FOIL"), "*NSET,NSET=NALL,GENERATE")
    lines.insert(lines.index("*MATERIAL,NAME=FOIL"), f"1,{nid},1")
    return "\n".join(lines) + "\n", {"grid": grid, "nr": nr, "nt": nt, "r0": r0, "r1": r1, "t": t}


def _blocks(txt: str, title: str) -> list[list[float]]:
    part = txt.split(title)[-1]
    rows = []
    for line in part.splitlines()[1:]:
        if not line.strip():
            if rows:
                break
            continue
        if not re.match(r"\s*\d", line):
            break
        rows.append([float(x) for x in line.split()])
    return rows


def forming_fea(des: dict, R: dict | None = None) -> dict:
    R = R or rules()
    av = fea.available()
    if not av["ccx"]:
        raise FinSimError(av["message"] or fea.INSTALL)
    g = geometry(des)
    text, mesh = _inp(g, R)
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp) / "collar"
        job.with_suffix(".inp").write_text(text)
        try:
            run = subprocess.run([av["ccx"], "-i", str(job)], cwd=tmp, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            raise FinSimError("The collar forming FEA took more than 10 minutes.") from None
        dat = job.with_suffix(".dat")
        msg = (run.stdout + run.stderr).splitlines()
        if run.returncode != 0 or not dat.exists() or any("*ERROR" in m for m in msg):
            raise FinSimError("CalculiX stopped: " + (next((m for m in msg if "ERROR" in m), msg[-1] if msg else ""))[:300])
        txt = dat.read_text(errors="replace")
    pe = _blocks(txt, "equivalent plastic strain")
    st = _blocks(txt, "strains (elem, integ.pnt.,exx,eyy,ezz,exy,exz,eyz)")
    disp = {int(r[0]): r[1:3] for r in _blocks(txt, "displacements (vx,vy,vz)")}
    nt, skip = mesh["nt"], int(R["fin_form_skip_rings"])
    ring = lambda e: (int(e) - 1) // nt
    peeq, thin = {}, {}
    for r in pe:
        peeq[int(r[0])] = max(peeq.get(int(r[0]), 0.0), r[2])
    for r in st:
        e = int(r[0])
        exx, eyy, ezz, exy = r[2], r[3], r[4], r[5]
        log = lambda x: 0.5 * math.log(max(1e-9, 1 + 2 * x))       # Green-Lagrange → logarithmic
        c, rad = (exx + eyy) / 2, math.sqrt(((exx - eyy) / 2) ** 2 + exy ** 2)
        e_thk = log(c - rad)                                          # smaller principal strain in the r-z plane = through the thickness
        thin[e] = max(thin.get(e, 0.0), (1 - math.exp(e_thk)) * 100)
    keep = [e for e in peeq if ring(e) >= skip]
    pmax = max(peeq[e] for e in keep) if keep else 0.0
    tmax = max(thin.get(e, 0.0) for e in keep) if keep else 0.0
    vals = sorted(peeq[e] for e in keep)
    p95 = vals[int(0.95 * (len(vals) - 1))] if vals else 0.0
    ok_s, ok_t = pmax <= R["fin_form_strain_max"], tmax <= R["fin_thinning_max_pct"]
    return {"peeq_max": round(pmax, 4), "peeq_p95": round(p95, 4), "thinning_max_pct": round(tmax, 2),
            "limit_peeq": R["fin_form_strain_max"], "limit_thinning_pct": R["fin_thinning_max_pct"], "ok_strain": ok_s, "ok_thinning": ok_t,
            "ok": ok_s and ok_t, "elements": len(peeq), "skipped_rings": skip, "geometry": {k: round(v, 4) for k, v in g.items()},
            "material": {k: R[k] for k in ("fin_foil_e_mpa", "fin_foil_yield_mpa", "fin_foil_k_mpa", "fin_foil_n")},
            "png": _fea_picture(mesh, disp, peeq, skip), "is_example": R["is_example"]}


def _fea_picture(mesh, disp, peeq, skip) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    grid, nr, nt = mesh["grid"], mesh["nr"], mesh["nt"]
    polys, vals, coords = [], [], {}
    for (i, j), nid in grid.items():                       # deformed position = node + displacement
        u = disp.get(nid, (0.0, 0.0))
        r = mesh["r0"] + (mesh["r1"] - mesh["r0"]) * (i / nr) ** 1.6
        coords[nid] = (r + u[0], j * mesh["t"] / nt + u[1])
    eid = 0
    for i in range(nr):
        for j in range(nt):
            eid += 1
            quad = [grid[i, j], grid[i + 1, j], grid[i + 1, j + 1], grid[i, j + 1]]
            polys.append([coords[q] for q in quad])
            vals.append(peeq.get(eid, 0.0))
    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=110)
    pc = PolyCollection(polys, array=vals, cmap="viridis", edgecolors="k", linewidths=0.1)
    kept = [v for k, v in enumerate(vals, start=1) if (k - 1) // nt >= skip]
    pc.set_clim(0, max(kept) if kept else 1)                # the colour scale of the result (the edge ring is the boundary)
    ax.add_collection(pc)
    ax.autoscale()
    ax.set_aspect("equal")
    ax.set_xlabel("r (mm)")
    ax.set_ylabel("z (mm)")
    ax.set_title("Collar forming: equivalent plastic strain")
    fig.colorbar(pc, ax=ax, label="equivalent plastic strain")
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------- strip progression pictures and video ----------

def _section(draw, box, kind: str, k: int, g: dict, ds: int):
    """Half section of one collar after the station (left = axis)."""
    x0, y0, x1, y1 = box
    sc = min((x1 - x0) / (g["cell_r"] * 1.05), (y1 - y0 - 30) / (g["h"] * 1.3 + g["t"] * 4))
    X = lambda r: x0 + r * sc
    Y = lambda z: y1 - 10 - z * sc
    draw.text((x0, y0), "Collar section after this station (half, axis at left)", fill=(91, 104, 120))
    t = max(g["t"] * sc, 2)
    pts = []
    if kind == "draw":
        hdome = g["h"] * 0.85 * k / max(ds, 1)
        R0 = g["d"] * 0.75
        for i in range(31):
            r = R0 * i / 30
            pts.append((X(r), Y(hdome * (1 - (r / R0) ** 2))))
        pts.append((X(g["cell_r"]), Y(0)))
    elif kind == "pierce":
        pts = [(X(g["d0"] / 2), Y(g["h"] * 0.85)), (X(g["d"] * 0.75), Y(0)), (X(g["cell_r"]), Y(0))]
    else:
        flare = kind in ("reflare", "trim", "pilot", "rowslit", "feed", "cutoff")
        top = g["h"]
        pts = [(X(g["d"] / 2 + (g["t"] * 3 if flare else 0)), Y(top)), (X(g["d"] / 2), Y(top - (g["t"] * 3 if flare else 0))),
               (X(g["d"] / 2), Y(0)), (X(g["cell_r"]), Y(0))]
    draw.line(pts, fill=(14, 26, 44), width=int(t))
    draw.line([(X(0), y0), (X(0), y1)], fill=(150, 150, 150), width=1)


def station_picture(des: dict, k: int, size=(960, 540)):
    from PIL import Image, ImageDraw
    from .sim_report import _caption
    s, sts = des["spec"], des["stations"]
    g = geometry(des)
    img = Image.new("RGB", size, "white")
    dr = ImageDraw.Draw(img)
    W, H = size
    n = len(sts)
    rows = min(6, s["die_rows"])
    sx = (W - 60) / n
    top, band = 20, 200
    for i, st in enumerate(sts):
        x = 30 + i * sx
        fill = (230, 240, 252) if i == k else (246, 247, 249)
        dr.rectangle([x, top, x + sx - 4, top + band], fill=fill, outline=(37, 99, 235) if i == k else (190, 196, 204), width=3 if i == k else 1)
        dr.text((x + 4, top + 4), f"{st['no']} {st['name'][:12]}", fill=(14, 26, 44))
        if i <= k:
            for r in range(rows):
                for p in range(s["progressions"]):
                    cx = x + (p + 0.5) * (sx - 4) / s["progressions"] + (((sx - 4) / s["progressions"]) / 2 if s["staggered"] and r % 2 else 0) * 0.5
                    cy = top + 30 + (r + 0.5) * (band - 40) / rows
                    rad = 5
                    kind = st["kind"]
                    if kind == "draw":
                        dr.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=(100, 116, 139))
                    elif kind in ("pierce", "iron", "louver", "slit", "wave", "reflare", "trim", "pilot", "rowslit", "feed", "cutoff"):
                        dr.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(14, 26, 44) if kind == "pierce" else None, outline=(14, 26, 44), width=2)
                        if kind in ("louver",):
                            dr.line([cx - rad, cy + rad + 4, cx + rad, cy + rad + 4], fill=(37, 99, 235), width=2)
    st = sts[k]
    _section(dr, (60, top + band + 20, W - 60, H - 72), st["kind"], int(st["code"][-1]) if st["kind"] == "draw" else 0, g, g["draw_steps"])
    return _caption(img, f"Station {st['no']} of {n}: {st['name']}", f"Ø{s['tube_od_mm']:g} × {s['die_rows']}R × {s['progressions']}P · feed "
                    f"{des['die']['die']['feed_mm']:g} mm · collar Ø{g['d']:g} × {g['h']:.2f} mm", False)


def pictures(des: dict) -> list[tuple[str, bytes]]:
    out = []
    for k, st in enumerate(des["stations"]):
        buf = io.BytesIO()
        station_picture(des, k).save(buf, format="PNG")
        out.append((f"{st['no']:02d} {st['name']}", buf.getvalue()))
    return out


def video(des: dict, fps: int = 6) -> tuple[bytes, str]:
    from .sim_report import _encode
    frames = []
    for k in range(len(des["stations"])):
        frames += [station_picture(des, k)] * 4             # each station shown for 4 frames
    return _encode(frames, fps)


# ---------------------------------------------------------------- report and run ----------

def report_pdf(des: dict, ck: list[dict], fe: dict | None, pics: list, title: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer
    from . import drawing_style
    from .pdf_report import _example_banner, _table, _theme
    theme, ss = _theme(), getSampleStyleSheet()
    st = {"k": ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8),
          "h1": ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=16, alignment=0)}
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=11, spaceBefore=8, spaceAfter=4)
    cell = ParagraphStyle("c", parent=ss["Normal"], fontSize=8, leading=10)
    P = lambda x: Paragraph(str(x).replace("&", "&amp;").replace("<", "&lt;"), cell)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm, title=title)
    W = A4[0] - 30 * mm
    bad = [c for c in ck if not c["ok"]] + ([{"name": "Collar forming FEA"}] if fe and not fe["ok"] else [])
    story = [drawing_style.pdf_header(st, "FIN SIMULATION", title), Spacer(1, 2 * mm), _example_banner(ss, "Material data and limits are EXAMPLE rules."),
             Paragraph("Result: " + ("<font color='#15803d'><b>no correction required</b></font>" if not bad else
                                     "<font color='#b91c1c'><b>check: " + ", ".join(c["name"] for c in bad) + "</b></font>"), cell),
             Paragraph("Collar forming and press checks", h2),
             _table([["Check", "Value", "Limit", "Unit", "Result", "Formula"]] +
                    [[P(c["name"]), f"{c['value']:g}", P(c["limit"]), c["unit"], "OK" if c["ok"] else "FAIL", P(c["formula"] + (f" · {c['note']}" if c["note"] else ""))]
                     for c in ck], theme, [40 * mm, 18 * mm, 22 * mm, 14 * mm, 12 * mm, W - 106 * mm])]
    if fe:
        story += [Paragraph("Collar forming FEA (CalculiX, axisymmetric, elastic-plastic, large deformation)", h2),
                  _table([["Result", "Value", "Limit", "Status"],
                          ["Largest equivalent plastic strain", f"{fe['peeq_max']:.3f}", f"{fe['limit_peeq']:g}", "OK" if fe["ok_strain"] else "FAIL"],
                          ["95 % of the collar below", f"{fe['peeq_p95']:.3f}", "", ""],
                          ["Largest collar wall thinning", f"{fe['thinning_max_pct']:.1f} %", f"{fe['limit_thinning_pct']:g} %", "OK" if fe["ok_thinning"] else "FAIL"]],
                         theme, [70 * mm, 30 * mm, 30 * mm, 20 * mm]),
                  P(f"{fe['elements']} elements; the first {fe['skipped_rings']} ring(s) at the drawn edge carry the boundary condition and are left out. "
                    f"Foil: E {fe['material']['fin_foil_e_mpa']:g} MPa, yield {fe['material']['fin_foil_yield_mpa']:g} MPa, K {fe['material']['fin_foil_k_mpa']:g} MPa, "
                    f"n {fe['material']['fin_foil_n']:g}."),
                  RLImage(io.BytesIO(fe["png"]), width=W * 0.8, height=W * 0.8 * 0.6)]
    story.append(PageBreak())
    story.append(Paragraph("Strip progression, station by station", h2))
    for name, png in pics:
        story += [P(name), RLImage(io.BytesIO(png), width=W * 0.85, height=W * 0.85 * 540 / 960), Spacer(1, 3 * mm)]
    doc.build(story)
    return buf.getvalue()


def live(part_id: int) -> dict:
    from . import fin_part, register
    des = fin_part.design(part_id)
    ck = checks(des)
    runs = [r for r in register.sim_runs(part_id) if r["kind"] == "fin_sim"]
    return {"checks": ck, "ok": all(c["ok"] for c in ck), "runs": runs, "fea_available": fea.available()}


def run_part(part_id: int, progress=None) -> int:
    """The full fin simulation of a fin part (checks, collar forming FEA, strip pictures and video, report), saved as a run."""
    from . import fin_part, register
    say = progress or (lambda pct, text: None)
    say(3, "Designing the fin die")
    des = fin_part.design(part_id)
    d = register.part_detail(part_id, with_rm=False)
    R = rules()
    ck = checks(des, R)
    say(15, "Collar forming FEA (CalculiX)")
    fe = None
    try:
        fe = forming_fea(des, R)
    except FinSimError as exc:
        ck.append({"name": "Collar forming FEA", "value": 0, "limit": "", "unit": "", "ok": False, "formula": "CalculiX", "note": str(exc)})
    say(45, "Strip progression pictures")
    pics = pictures(des)
    say(60, "Strip progression video")
    vid, ext = video(des)
    say(85, "Report")
    title = f"{d['part_code']} rev {d['rev']} · fin simulation"
    pdf = report_pdf(des, ck, fe, pics, title)
    summary = {"checks": ck, "fea": {k: v for k, v in (fe or {}).items() if k != "png"} or None,
               "corrections": [c["name"] for c in ck if not c["ok"]] + (["Collar forming FEA"] if fe and not fe["ok"] else []),
               "results": {"peeq_max": (fe or {}).get("peeq_max"), "thinning_max_pct": (fe or {}).get("thinning_max_pct")}}
    say(95, "Saving")
    return register._save_sim_run(part_id, d["rev"] or "", "fin_sim", "Fin simulation (strip, collar forming, FEA)", summary,
                                  (pdf, f"{d['part_code']}_rev{d['rev']}_fin_simulation.pdf"),
                                  (vid, f"{d['part_code']}_rev{d['rev']}_fin_strip.{ext}"), True)
