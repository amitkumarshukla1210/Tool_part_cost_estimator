"""Sheet-metal forming simulation report: PDF and video (roadmap stage 27).

    model      the flat pattern of the part (unfold.py: outline, holes, bend lines with angle, radius, up / down) as a
               plate of the sheet thickness, cut along every bend line; a bend is formed by turning everything on its far
               side about the bend line (bends nested in another bend's far side are turned first)
    stages     the operations in order (Sheet-metal tools): blanking shows the blank leaving the strip, piercing the
               holes, bending the flanges folding up to their angle; the bend that fails the bend-radius check is red
    PDF        A4: result (corrections required / none), every formability check with OK / FAIL and its value, blank
               and material yield, the stages with force and press, a picture after every stage, flat pattern with bend
               lines, analytical-method note
    video      MP4 (H.264, imageio-ffmpeg; else the ffmpeg on the PATH) of the stages with captions; animated GIF when no
               ffmpeg is found
Analytical estimate from the master-data rules, not a finite-element forming simulation.
"""

from __future__ import annotations

import io
import math
import os
import shutil
import subprocess
import tempfile

import cadquery as cq
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Point, Polygon

from . import drawing_style, render3d

BLUE, RED, GREY, GREEN = (0.35, 0.55, 0.8), (0.86, 0.2, 0.18), (0.75, 0.78, 0.82), (0.3, 0.7, 0.4)


class FoldModel:
    """The flat part cut along its bend lines; positions of every piece at any forming progress (0 = flat, 1 = formed)."""

    def __init__(self, fp: dict, t: float, with_holes: bool = True):
        self.fp, self.t = fp, t
        poly = cq.Workplane("XY").polyline([tuple(p) for p in fp["outline"][:-1]]).close().extrude(t)
        if with_holes:
            for h in fp["holes"]:
                poly = poly.cut(cq.Workplane("XY").workplane(offset=-0.1).polyline([tuple(p) for p in h[:-1]]).close().extrude(t + 0.2))
        solid = poly.val()
        self.bends = fp.get("bends") or []
        self.zone = max(2 * t, 3.0)          # half width of the bend zone shown (red when the bend fails its check)
        for b in self.bends:
            (x1, y1), (x2, y2) = b["line"]
            d = np.array([x2 - x1, y2 - y1, 0.0])
            n = np.cross(d, [0, 0, 1])
            n /= np.linalg.norm(n)
            big = 4 * (fp["length_mm"] + fp["width_mm"])
            for off in (0.0, -self.zone, self.zone):
                plane = cq.Face.makePlane(big, big, cq.Vector(x1 + n[0] * off, y1 + n[1] * off, 0), cq.Vector(*n))
                solid = solid.split(plane)
        self.pieces = list(solid.Solids())
        self.meshes = [render3d.mesh(p, tol=0.2) for p in self.pieces]
        # nesting: a bend whose line lies on the far side of another bend is turned first
        for b in self.bends:
            b["_far_poly"] = self._half_plane(b)
        for b in self.bends:
            mid = Point((b["line"][0][0] + b["line"][1][0]) / 2, (b["line"][0][1] + b["line"][1][1]) / 2)
            b["_depth"] = sum(1 for o in self.bends if o is not b and o["_far_poly"].contains(mid))

    def _half_plane(self, b):
        (x1, y1), (x2, y2) = b["line"]
        d = np.array([x2 - x1, y2 - y1])
        d = d / (np.linalg.norm(d) or 1)
        n = np.array([-d[1], d[0]])
        fx, fy = b["far_side"]
        if (np.array([fx, fy]) - [x1, y1]) @ n < 0:
            n = -n
        big = 1e5
        p1, p2 = np.array([x1, y1]) - d * big, np.array([x1, y1]) + d * big
        return Polygon([tuple(p1), tuple(p2), tuple(p2 + n * big), tuple(p1 + n * big)])

    def _rotate(self, pts, b, progress):
        (x1, y1), (x2, y2) = b["line"]
        a = np.array([x2 - x1, y2 - y1, 0.0])
        a /= np.linalg.norm(a)
        z_axis = self.t if b["up"] > 0 else 0.0
        o = np.array([x1, y1, z_axis])
        ang = math.radians(b["angle_deg"]) * progress
        # turn direction: the far side goes up (+z) for an 'up' bend, down for a 'down' bend
        fx, fy = b["far_side"]
        probe = np.array([fx, fy, z_axis]) - o
        sgn = 1 if ((_rot(a, 0.2) @ probe)[2]) * b["up"] > 0 else -1
        R = _rot(a, sgn * ang)
        return (pts - o) @ R.T + o

    def items(self, progress: float = 1.0, risk: set | None = None, color=BLUE):
        """Render items at a forming progress; pieces next to a bend in `risk` (indices) are red."""
        out = []
        order = sorted(range(len(self.bends)), key=lambda i: -self.bends[i]["_depth"])
        for piece, (v, t) in zip(self.pieces, self.meshes):
            c = piece.Center()
            col = color
            pts = v.copy()
            for i in order:
                b = self.bends[i]
                if b["_far_poly"].contains(Point(c.x, c.y)):
                    pts = self._rotate(pts, b, progress)
            for i in risk or ():
                b = self.bends[i]
                (x1, y1), (x2, y2) = b["line"]
                dist = abs((x2 - x1) * (y1 - c.y) - (x1 - c.x) * (y2 - y1)) / max(math.hypot(x2 - x1, y2 - y1), 1e-9)
                if dist < self.zone:
                    col = RED
            out.append((pts, t, col))
        return out


def _rot(axis, ang):
    a = axis / np.linalg.norm(axis)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(ang) * k + (1 - math.cos(ang)) * (k @ k)


def _risk(res: dict, fp: dict) -> set:
    """Bends that fail the bend-radius check."""
    failed = {c["check"] for c in res.get("checks", []) if not c["passed"]}
    if "bend_radius" not in failed:
        return set()
    lim = res["material_values"].get("min_bend_r_factor", 1) * res["features"]["t"]
    return {i for i, b in enumerate(fp.get("bends") or []) if b["inner_radius_mm"] < lim} or set(range(len(fp.get("bends") or [])))


def stages(res: dict) -> list[dict]:
    return [{"code": o["code"], "name": o["name"], "force_t": o["force_t"],
             "press": (o.get("press") or {}).get("machine_id") or ((res.get("press") or {}).get("all stations") or {}).get("machine_id") or "-"}
            for o in res["operations"]]


def _strip_items(fp, t):
    L, W = fp["length_mm"], fp["width_mm"]
    e = max(2.0, 1.5 * t)
    v, tri = render3d.mesh(cq.Solid.makeBox(L + 4 * e + L * 0.6, W + 2 * e, t * 0.98, cq.Vector(-2 * e - L * 0.3, -e, 0.01)), 0.5)
    return [(v, tri, GREY)]


def stage_pictures(res: dict, fp: dict, size=(900, 560)) -> list[tuple[str, bytes]]:
    """A picture after every stage (same camera)."""
    t = res["features"]["t"]
    full = FoldModel(fp, t, True)
    blank = FoldModel(fp, t, False) if fp["holes"] else full
    risk = _risk(res, fp)
    bounds = render3d.projected_bounds(full.items(1.0) + full.items(0.0) + _strip_items(fp, t))
    out, pierced, bent = [], False, False
    for st in stages(res):
        if st["code"] in ("pierce",):
            pierced = True
        if st["code"] in ("bend", "form", "flange", "draw"):
            bent = True
        model = full if pierced or not fp["holes"] else blank
        items = model.items(1.0 if bent else 0.0, risk if bent else None)
        img = render3d.render(items, size=size, bounds=bounds)
        out.append((f"After {st['name']}", render3d.png(img)))
    return out


# ---------- video ----------

def _font(size):
    for f in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _caption(img: Image.Image, title: str, line2: str, bad: bool) -> Image.Image:
    d = ImageDraw.Draw(img)
    W, H = img.size
    d.rectangle([0, H - 64, W, H], fill=(14, 26, 44))
    d.text((16, H - 58), title, fill=(255, 255, 255), font=_font(22))
    d.text((16, H - 28), line2, fill=(255, 120, 110) if bad else (180, 220, 255), font=_font(16))
    return img


def _ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def video(res: dict, fp: dict, part: dict, fps: int = 15, size=(960, 540)) -> tuple[bytes, str]:
    """(content, extension) of the forming video: mp4 when ffmpeg is found, else gif."""
    t = res["features"]["t"]
    full = FoldModel(fp, t, True)
    blank = FoldModel(fp, t, False) if fp["holes"] else full
    risk = _risk(res, fp)
    probs = [c for c in res.get("checks", []) if not c["passed"]]
    sph = render3d.sphere_of(full.items(1.0) + full.items(0.0))
    frames = []
    view = dict(size=(size[0], size[1] + 64), sphere=(sph[0], sph[1] * 0.85), margin=0.04)

    def add(items, title, line2, bad=False, n=1, az=-50):
        img = render3d.render(items, az=az, **view)
        img = _caption(img, title, line2, bad)
        frames.extend([img] * n)

    head = f"{part['part_code']} · {part['name']} · t {t:g} mm · {res['material']}"
    add(blank.items(0.0), head, "Forming simulation (analytical) - stages in order", n=fps)
    pierced = False
    progress = 0.0
    for k, st in enumerate(stages(res), start=1):
        model = full if pierced or not fp["holes"] else blank
        label = f"Stage {k}: {st['name']} · {st['force_t']:.1f} t · press {st['press']}"
        if st["code"] == "blank":
            add(_strip_items(fp, t) + blank.items(0.0), label, "Blank cut from the strip", n=fps // 2)
            add(blank.items(0.0), label, f"Blank {fp['length_mm']:.1f} × {fp['width_mm']:.1f} mm", n=fps // 2)
        elif st["code"] == "pierce":
            pierced = True
            add(full.items(progress), label, f"{len(fp['holes'])} hole(s) pierced", n=fps)
        elif st["code"] in ("bend", "form", "flange") and fp.get("bends"):
            bad = bool(risk)
            steps = max(12, fps * 2)
            for i in range(1, steps + 1):
                progress = i / steps
                line2 = (" ; ".join(c["message"] for c in probs if c["check"] == "bend_radius")[:110] if bad else
                         f"{len(fp['bends'])} bend(s) to {', '.join(f'{b['angle_deg']:g}°' for b in fp['bends'])}")
                add(model.items(progress, risk), label, line2, bad=bad, az=-50 + 20 * progress)
        else:
            add(model.items(progress, risk if progress else None), label, "", n=fps // 2)
    final = "Result: " + (f"{len(probs)} correction(s) required - " + probs[0]["message"][:90] if probs else "no corrections required")
    for i in range(fps * 3):
        add(full.items(1.0 if fp.get("bends") else 0.0, risk), head, final, bad=bool(probs), az=-30 - 120 * i / (fps * 3))
    return _encode(frames, fps)


# ---------- PDF ----------

def pdf(res: dict, fp: dict, part: dict, rev: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from .pdf_report import _table, _theme
    theme = _theme()
    ss = getSampleStyleSheet()
    st = {"h1": ParagraphStyle("h1", parent=ss["Title"], fontSize=15, alignment=0, textColor=theme["ink"]),
          "k": ParagraphStyle("k", parent=ss["Normal"], fontSize=8, textColor=theme["brand"]),
          "h2": ParagraphStyle("h2", parent=ss["Heading3"], textColor=theme["ink"], spaceBefore=6, spaceAfter=3),
          "n": ParagraphStyle("n", parent=ss["Normal"], fontSize=8.5, leading=11),
          "s": ParagraphStyle("s", parent=ss["Normal"], fontSize=7.5, leading=9.5, textColor=theme["grey"])}
    checks = res.get("checks", [])
    probs = [c for c in checks if not c["passed"]] + [p for p in res["problems"] if p["check"] == "press"]
    W = 182 * mm
    story = [drawing_style.pdf_header(st, "FORMING SIMULATION REPORT (SHEET METAL)", f"{part['part_code']} · {part['name']} · rev {rev}")]
    verdict = (f"<font color='#b91c1c'><b>{len(probs)} CORRECTION(S) REQUIRED</b></font>" if probs
               else "<font color='#15803d'><b>NO CORRECTIONS REQUIRED</b></font>")
    story += [Paragraph(f"Result: {verdict}", st["h1"])]
    for p in probs:
        story.append(Paragraph(f"• {p['message']}", st["n"]))
    f = res["features"]
    story += [Spacer(1, 3 * mm), Paragraph("Formability checks", st["h2"]),
              _table([["Check", "Result", "Detail"]] + [[c["check"].replace("_", " "), "OK" if c["passed"] else "FAIL",
                                                        Paragraph(c["message"] if not c["passed"] else f"passed (rule: {c['condition']})", st["s"])]
                                                       for c in checks], theme, [32 * mm, 16 * mm, 134 * mm])]
    b = res.get("blank") or {}
    rows = [["Item", "Value"], ["Material / thickness", f"{res['material']} · {f['t']:g} mm"],
            ["Flat pattern", f"{fp['length_mm']:.2f} × {fp['width_mm']:.2f} mm, {len(fp['holes'])} hole(s), {len(fp.get('bends') or [])} bend(s)"],
            ["Blank (costing)", f"{b.get('length', 0):.1f} × {b.get('width', 0):.1f} mm · {b.get('method', '')}"],
            ["Inside bend radius", f"{f['bend_radius']:.2f} mm (minimum {res['material_values'].get('min_bend_r_factor', 1):g} × t)"],
            ["Smallest hole", f"{f['min_hole_d']:.2f} mm" if f["hole_count"] else "no holes"]]
    for o in (b.get("options") or []):
        rows.append([f"Blank option: {o['name']}", f"{o['length']:.1f} × {o['width']:.1f} mm · yield {o['yield_pct']:.1f} %"])
    rows = [rows[0]] + [[Paragraph(a, st["s"]), Paragraph(b_, st["s"])] for a, b_ in rows[1:]]
    story += [Paragraph("Part and blank", st["h2"]), _left(_table(rows, theme, [70 * mm, 112 * mm]))]
    story += [Paragraph("Stages", st["h2"]),
              _left(_table([["#", "Operation", "Force (t)", "Press"]] + [[str(i), s["name"], f"{s['force_t']:.1f}", s["press"]]
                                                                     for i, s in enumerate(stages(res), start=1)],
                           theme, [10 * mm, 80 * mm, 30 * mm, 62 * mm]))]
    pics = stage_pictures(res, fp)
    cells = [[RLImage(io.BytesIO(png), 88 * mm, 88 * mm * 560 / 900), Paragraph(title, st["s"])] for title, png in pics]
    grid = []
    for i in range(0, len(cells), 2):
        pair = cells[i:i + 2] + [["", ""]] * (2 - len(cells[i:i + 2]))
        grid += [[pair[0][0], pair[1][0]], [pair[0][1], pair[1][1]]]
    story += [Paragraph("Part after every stage (red = bend that fails the bend-radius check)", st["h2"]),
              Table(grid, colWidths=[91 * mm, 91 * mm], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))]
    story += [Paragraph("Flat pattern with bend lines", st["h2"]), _flat_drawing(fp, theme, W, 70 * mm),
              Spacer(1, 3 * mm),
              Paragraph("Method: analytical checks and forces from the formulas in Master data (Sheet checks, Sheet operations, Sheet "
                        "materials); flat pattern unfolded from the 3D model with the k-factor of the Design rules. Not a finite-element "
                        "forming simulation: thinning, wrinkling and exact springback need a CAE run for critical parts.", st["s"]),
              Spacer(1, 3 * mm),
              drawing_style.pdf_title_block(W, [("Part", part["part_code"]), ("Revision", rev), ("Material", res["material"]),
                                                ("Thickness", f"{f['t']:g} mm")], "sheet_metal", "-", "1 / 1",
                                            f"{part['part_code']}-SIM", rev)]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=10 * mm, bottomMargin=10 * mm,
                            title=f"Forming simulation {part['part_code']}", author=drawing_style.settings()["company"])
    doc.build(story)
    return buf.getvalue()


def _left(t):
    from reportlab.platypus import TableStyle
    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "LEFT")]))
    return t


def _flat_drawing(fp, theme, W, H):
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
    d = Drawing(W, H)
    sc = min((W - 20) / max(fp["length_mm"], 1), (H - 20) / max(fp["width_mm"], 1))
    ox, oy = 10, 10
    P = lambda pts: [v for x, y in pts for v in (ox + x * sc, oy + y * sc)]
    d.add(PolyLine(P(fp["outline"]), strokeColor=theme["ink"], strokeWidth=0.8))
    for h in fp["holes"]:
        d.add(PolyLine(P(h), strokeColor=theme["ink"], strokeWidth=0.5))
    for b in fp.get("bends") or []:
        (x1, y1), (x2, y2) = b["line"]
        d.add(Line(ox + x1 * sc, oy + y1 * sc, ox + x2 * sc, oy + y2 * sc, strokeColor=theme["brand"], strokeWidth=0.8,
                   strokeDashArray=[4, 2]))
        d.add(String(ox + x1 * sc + 3, oy + max(y1, y2) * sc - 9, f"{'UP' if b['up'] > 0 else 'DOWN'} {b['angle_deg']:g}° R{b['inner_radius_mm']:g}",
                     fontSize=7, fillColor=theme["brand"]))
    return d


# ---------- moulded parts (plastic, die casting): video of the analysis maps ----------

def _encode(frames: list, fps: int) -> tuple[bytes, str]:
    exe = _ffmpeg()
    if exe:
        with tempfile.TemporaryDirectory() as tmp:
            for i, f in enumerate(frames):
                f.save(os.path.join(tmp, f"f{i:05d}.png"))
            out = os.path.join(tmp, "out.mp4")
            r = subprocess.run([exe, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(tmp, "f%05d.png"),
                                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], capture_output=True)
            if r.returncode == 0 and os.path.exists(out):
                with open(out, "rb") as fh:
                    return fh.read(), "mp4"
    buf = io.BytesIO()
    small = [f.resize((f.width // 2, f.height // 2)) for f in frames[::2]]
    small[0].save(buf, "GIF", save_all=True, append_images=small[1:], duration=int(2000 / fps), loop=0)
    return buf.getvalue(), "gif"


def turntable(tri: np.ndarray, n: int, size=(960, 540), el: float = 25, progress=None) -> list[dict]:
    """n views of the mesh around the vertical axis (render3d.face_view), drawn once and painted for every map."""
    sph = render3d.sphere_of([(tri.reshape(-1, 3), np.arange(len(tri) * 3).reshape(-1, 3), (0, 0, 0))])
    views = []
    for i in range(n):
        views.append(render3d.face_view(tri, size=(size[0], size[1] + 64), az=-60 + 360 * i / n, el=el, sphere=sph, margin=0.04))
        if progress:
            progress(i + 1, n)
    return views


def moulding_maps(res: dict) -> list[tuple[np.ndarray, np.ndarray, str]]:
    """(face colours m × 3, outline key per face, caption) of the wall-thickness, draft and risk maps."""
    f = res["_faces"]
    th = f["thickness"]
    lo, hi = (np.nanmin(th), np.nanmax(th)) if np.isfinite(th).any() else (0, 1)
    ramp = np.array([(0.27, 0.0, 0.33), (0.23, 0.32, 0.55), (0.13, 0.57, 0.55), (0.37, 0.79, 0.38), (0.75, 0.87, 0.15), (0.99, 0.91, 0.14)])
    bins = np.clip(np.nan_to_num((th - lo) / max(hi - lo, 1e-9) * 5).astype(int), 0, 5)
    wall_key = np.where(np.isnan(th), -1, bins)
    wall = np.where(np.isnan(th)[:, None], GREY, ramp[bins])
    lim = res["results"]["min_draft_deg"]
    dk = np.where(f["draft"] < lim, 0, np.where(f["draft"] < 2 * lim, 1, 2))
    draft = np.array([RED, (0.95, 0.65, 0.1), GREEN])[dk]
    rk = np.zeros(len(th), int)
    for k, m in enumerate(("thin", "low", "thick", "undercut"), start=1):
        rk[f[m]] = k
    risk = np.array([GREY, (0.15, 0.45, 0.85), (0.95, 0.65, 0.1), RED, (0.55, 0.2, 0.7)])[rk]
    return [(wall, wall_key, f"Wall thickness {lo:.2f} – {hi:.2f} mm (yellow = thick, sink risk)"),
            (draft, dk, f"Draft to {res['opening_axis'].upper()}: red below {lim:g}°, orange below {2 * lim:g}°"),
            (risk, rk, "Risk: red sink, blue thin, orange low draft, purple undercut")]


def moulding_video(res: dict, part: dict, fps: int = 12, size=(960, 540), progress=None) -> tuple[bytes, str]:
    """Turntable of the wall-thickness, draft and risk maps of the simulation & analysis (simulation.py), with captions.
    Each view is drawn once (render3d.face_view) and painted for the three maps, so a detailed model takes minutes, not hours."""
    tri = res["_faces"]["tri"]
    n = fps * 3
    views = turntable(tri, n, size, progress=progress)
    head = f"{part['part_code']} · {part['name']} · opening {res['opening_axis'].upper()}"
    r = res["results"]
    corr = res.get("corrections") or []
    frames = []
    maps = moulding_maps(res)
    for k, (col, key, line) in enumerate(maps):
        bad = k == len(maps) - 1 and bool(corr)
        frames += [_caption(render3d.paint(v, col, edge_key=key), head, line, bad) for v in views]
    final = (f"Result: {len(corr)} correction(s) - {corr[0][:90]}" if corr else "Result: no corrections required") + \
            f" · cycle {r.get('cycle_s', 0):.1f} s · clamp {r.get('clamp_t', 0):.0f} t"
    img = _caption(render3d.paint(views[0], maps[-1][0], edge_key=maps[-1][1]), head, final, bool(corr))
    frames += [img] * (fps * 3)
    return _encode(frames, fps)
