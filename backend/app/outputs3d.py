"""3D and drawing outputs (roadmap stage 20): meshes, STEP / STL, pictures, a self-contained 3D viewer page, orthographic
drawings (DXF + PDF) with dimensions, and the simulation video.

Free software only: CadQuery / OpenCascade (STEP, hidden-line views), matplotlib (pictures, video frames), ezdxf (DXF),
ReportLab (PDF), three.js (the viewer, bundled in frontend/vendor) and ffmpeg through imageio-ffmpeg (video).
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import struct
import tempfile
from pathlib import Path

import cadquery as cq
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "frontend" / "vendor" / "three"
MAX_RENDER_FACES = 14000


# ------------------------------------------------------------ meshes and files

def mesh(shape: cq.Shape, tol: float = 0.5, angular: float = 0.3) -> tuple[np.ndarray, np.ndarray]:
    v, t = shape.tessellate(tol, angular)
    if not v:
        return np.zeros((0, 3)), np.zeros((0, 3), int)
    return np.array([[p.x, p.y, p.z] for p in v], float), np.array(t, int)


def component_meshes(components: list[dict], tol: float | None = None) -> list[dict]:
    """[{name, group, color, v, f}] with a tolerance that follows the model size."""
    allbb = None
    for c in components:
        bb = c["shape"].BoundingBox()
        allbb = bb if allbb is None else allbb.add(bb)
    size = max(allbb.xlen, allbb.ylen, allbb.zlen) if allbb else 100.0
    tol = tol or max(0.2, size / 800)
    out = []
    for c in components:
        v, f = mesh(c["shape"], tol)
        if len(f):
            out.append({"name": c["name"], "group": c.get("group", ""), "color": c.get("color", (0.7, 0.7, 0.7)), "v": v, "f": f})
    return out


def solid_step_bytes(shape: cq.Shape) -> bytes:
    """One solid as a plain STEP file (no assembly wrapper): what a supplier or a CAD user opens and edits."""
    fd, path = tempfile.mkstemp(suffix=".step")
    os.close(fd)
    try:
        cq.exporters.export(cq.Workplane("XY").add(shape), path)
        return Path(path).read_bytes()
    finally:
        os.unlink(path)


def step_bytes(components: list[dict], name: str = "design") -> bytes:
    asm = cq.Assembly(name=f"{name}_assembly")
    for c in components:
        r, g, b = c.get("color", (0.7, 0.7, 0.7))
        asm.add(c["shape"], name=c["name"].replace(" ", "_"), color=cq.Color(r, g, b))
    fd, path = tempfile.mkstemp(suffix=".step")
    os.close(fd)
    try:
        asm.save(path)
        return Path(path).read_bytes()
    finally:
        os.unlink(path)


def stl_bytes(meshes: list[dict]) -> bytes:
    tris = [m["v"][m["f"]] for m in meshes if len(m["f"])]
    tri = np.concatenate(tris) if tris else np.zeros((0, 3, 3))
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]) if len(tri) else np.zeros((0, 3))
    n = n / np.where(np.linalg.norm(n, axis=1) > 0, np.linalg.norm(n, axis=1), 1)[:, None]
    buf = io.BytesIO()
    buf.write(b"Design to Cost STL".ljust(80, b" "))
    buf.write(struct.pack("<I", len(tri)))
    for k in range(len(tri)):
        buf.write(struct.pack("<12fH", *n[k], *tri[k].reshape(-1), 0))
    return buf.getvalue()


# ------------------------------------------------------------ pictures

def render_png(meshes: list[dict], title: str = "", elev: float = 24, azim: float = -58, size=(6.4, 4.8), dpi=100,
               bounds=None, caption: str = "", colors=None) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    fig = plt.figure(figsize=size, dpi=dpi)
    ax = fig.add_subplot(111, projection="3d")
    allv = np.concatenate([m["v"] for m in meshes]) if meshes else np.zeros((1, 3))
    lo, hi = (np.array(bounds[0]), np.array(bounds[1])) if bounds else (allv.min(0), allv.max(0))
    for k, m in enumerate(meshes):
        tri = m["v"][m["f"]]
        step = math.ceil(len(tri) / MAX_RENDER_FACES) if len(tri) > MAX_RENDER_FACES else 1
        tri = tri[::step]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n = n / np.where(np.linalg.norm(n, axis=1) > 0, np.linalg.norm(n, axis=1), 1)[:, None]
        light = np.clip(0.55 + 0.45 * (n @ np.array([0.4, -0.5, 0.75])), 0.25, 1.0)
        base = (np.asarray(colors[k])[::step] if colors is not None and colors[k] is not None
                else np.tile(np.array(m["color"])[None, :], (len(tri), 1)))
        ax.add_collection3d(Poly3DCollection(tri, facecolors=np.clip(base * light[:, None], 0, 1), edgecolor="none"))
    mid, r = (lo + hi) / 2, (hi - lo).max() / 2 or 1
    ax.set_xlim(mid[0] - r, mid[0] + r); ax.set_ylim(mid[1] - r, mid[1] + r); ax.set_zlim(mid[2] - r, mid[2] + r)
    ax.view_init(elev, azim)
    ax.set_axis_off()
    if title:
        ax.set_title(title, fontsize=9)
    if caption:
        fig.text(0.5, 0.03, caption, ha="center", fontsize=9, color="#152238")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ------------------------------------------------------------ 3D viewer page (one file, works offline)

def viewer_html(title: str, scenes: list[dict], notes: list[str] | None = None) -> bytes:
    """Self-contained page: rotate / zoom, scene selector, per-part visibility. scenes = [{name, meshes, explode_groups}]"""
    def pack(m):
        v = m["v"].astype("<f4")
        return {"name": m["name"], "group": m["group"], "color": "#%02x%02x%02x" % tuple(int(255 * c) for c in m["color"]),
                "v": base64.b64encode(v.tobytes()).decode(), "f": base64.b64encode(m["f"].astype("<u4").tobytes()).decode()}
    data = [{"name": s["name"], "parts": [pack(m) for m in s["meshes"]]} for s in scenes]
    three = (VENDOR / "three.module.js").read_text(encoding="utf-8")
    orbit = (VENDOR / "OrbitControls.js").read_text(encoding="utf-8")
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>:root{{--ink:#1b2a41;--brand:#0b6e99;--bg:#f5f7fa}}
body{{margin:0;font:14px system-ui,sans-serif;background:var(--bg);color:var(--ink);display:flex;height:100vh}}
#side{{width:280px;padding:12px;overflow:auto;background:#fff;border-right:1px solid #d5dbe3}}
#view{{flex:1;position:relative}} canvas{{display:block;width:100%;height:100%}}
h1{{font-size:16px;margin:0 0 8px;color:var(--brand)}} select,input[type=range]{{width:100%}}
label{{display:block;font-size:12px;margin:2px 0}} .n{{font-size:12px;color:#556}}
@media (max-width:700px){{body{{flex-direction:column}}#side{{width:auto;max-height:40vh}}}}</style></head>
<body><div id="side"><h1>{title}</h1><select id="scene"></select>
<p class="n">Drag to rotate, wheel to zoom, right-drag to pan.</p>
<label>Open / explode <input id="ex" type="range" min="0" max="1" step="0.01" value="0"></label>
<div id="parts"></div><div class="n">{'<br>'.join(notes or [])}</div></div><div id="view"></div>
<script type="text/plain" id="three-src">{three.replace('</script', '<\\/script')}</script>
<script type="text/plain" id="orbit-src">{orbit.replace('</script', '<\\/script')}</script>
<script>
const DATA={json.dumps(data)};
(async()=>{{
 const url=(s)=>URL.createObjectURL(new Blob([s],{{type:'text/javascript'}}));
 const tUrl=url(document.getElementById('three-src').textContent);
 const oSrc=document.getElementById('orbit-src').textContent.replace("from 'three'","from '"+tUrl+"'");
 const THREE=await import(tUrl); const {{OrbitControls}}=await import(url(oSrc));
 const el=document.getElementById('view'); const R=new THREE.WebGLRenderer({{antialias:true}}); el.appendChild(R.domElement);
 const S=new THREE.Scene(); S.background=new THREE.Color(0xf5f7fa);
 const C=new THREE.PerspectiveCamera(40,1,1,1e6); const O=new OrbitControls(C,R.domElement);
 S.add(new THREE.HemisphereLight(0xffffff,0x8899aa,1.1)); const L=new THREE.DirectionalLight(0xffffff,1.2); L.position.set(1,-1,2); S.add(L);
 S.rotation.x=-Math.PI/2; let group=null, meshes=[];
 const b64=(s,T)=>{{const b=atob(s),u=new Uint8Array(b.length);for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);return new T(u.buffer)}};
 function load(i){{ if(group)S.remove(group); group=new THREE.Group(); meshes=[];
  const box=new THREE.Box3(); const pd=document.getElementById('parts'); pd.innerHTML='';
  DATA[i].parts.forEach((p,k)=>{{const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.BufferAttribute(b64(p.v,Float32Array),3));
   g.setIndex(new THREE.BufferAttribute(b64(p.f,Uint32Array),1)); g.computeVertexNormals();
   const m=new THREE.Mesh(g,new THREE.MeshStandardMaterial({{color:p.color,metalness:.2,roughness:.55,side:THREE.DoubleSide}}));
   m.userData.group=p.group; group.add(m); meshes.push(m); box.expandByObject(m);
   const lb=document.createElement('label'); lb.innerHTML='<input type="checkbox" checked> '+p.name; lb.firstChild.onchange=e=>m.visible=e.target.checked; pd.appendChild(lb);}});
  S.add(group); const c=box.getCenter(new THREE.Vector3()), r=box.getSize(new THREE.Vector3()).length();
  group.userData.c=c; group.userData.span=r*.25; C.position.set(c.x+r*.8,c.z+r*.7,-c.y+r*1.1); O.target.set(c.x,c.z,-c.y); O.update(); ex(); }}
 function ex(){{ const k=+document.getElementById('ex').value; meshes.forEach(m=>{{m.position.z=m.userData.group==='upper'?k*(group.userData.span||0):0;}}); }}
 const sel=document.getElementById('scene'); DATA.forEach((d,i)=>sel.add(new Option(d.name,i))); sel.onchange=()=>load(+sel.value);
 document.getElementById('ex').oninput=ex; load(0);
 function rs(){{R.setSize(el.clientWidth,el.clientHeight);C.aspect=el.clientWidth/el.clientHeight;C.updateProjectionMatrix();}} addEventListener('resize',rs); rs();
 (function loop(){{requestAnimationFrame(loop);O.update();R.render(S,C)}})();
}})();
</script></body></html>"""
    return html.encode("utf-8")


# ------------------------------------------------------------ orthographic drawing

def _edges_2d(compound) -> list[list[tuple[float, float]]]:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    out = []
    if compound is None or compound.IsNull():
        return out
    ex = TopExp_Explorer(compound, TopAbs_EDGE)
    while ex.More():
        e = ex.Current()
        try:
            c = BRepAdaptor_Curve(TopoDS.Edge_s(e))
            d = GCPnts_QuasiUniformDeflection(c, 0.05)
            pts = [(c.Value(d.Parameter(i)).X(), c.Value(d.Parameter(i)).Y()) for i in range(1, d.NbPoints() + 1)]
            if len(pts) >= 2:
                out.append(pts)
        except Exception:
            pass
        ex.Next()
    return out


HLR_SECONDS = 25.0          # hidden-line removal of a very complex tool insert can take minutes: past this the view is simplified
HLR_FACES = 150


def _hlr_guarded(shape: cq.Shape, direction: tuple, xdir: tuple, flip_v: bool) -> dict:
    """hlr_view in a forked process for complex shapes: on a timeout the view is the bounding rectangle, marked as simplified."""
    import multiprocessing as mp
    ctx = mp.get_context("fork")
    q = ctx.Queue()

    def work():
        try:
            q.put(_hlr_exact(shape, direction, xdir, flip_v))
        except Exception as exc:
            q.put({"error": str(exc)})
    p = ctx.Process(target=work, daemon=True)
    p.start()
    try:
        out = q.get(timeout=HLR_SECONDS)
    except Exception:
        out = None
    if p.is_alive():
        p.terminate()
    p.join(2)
    if out and "error" not in out:
        return out
    bb = shape.BoundingBox()
    ext = {"x": (bb.xmin, bb.xmax), "y": (bb.ymin, bb.ymax), "z": (bb.zmin, bb.zmax)}
    u = {(1, 0, 0): "x", (0, 1, 0): "y"}.get(tuple(abs(int(c)) for c in xdir), "x")
    d = "z" if abs(direction[2]) else ("y" if abs(direction[1]) else "x")
    v = next(a for a in "xyz" if a not in (u, d)) if u != d else "y"
    (u0, u1), (v0, v1) = ext[u], ext[v]
    if flip_v:
        v0, v1 = -v1, -v0
    rect = [(u0, v0), (u1, v0), (u1, v1), (u0, v1), (u0, v0)]
    return {"visible": [rect], "hidden": [], "bounds": (u0, v0, u1, v1), "simplified": True}


def hlr_view(shape: cq.Shape, direction: tuple, xdir: tuple, flip_v: bool = False) -> dict:
    if len(shape.Faces()) > HLR_FACES:
        return _hlr_guarded(shape, direction, xdir, flip_v)
    return _hlr_exact(shape, direction, xdir, flip_v)


def _hlr_exact(shape: cq.Shape, direction: tuple, xdir: tuple, flip_v: bool = False) -> dict:
    """Visible and hidden edges of `shape` seen along `direction` (2D coordinates of the view plane).
    flip_v mirrors the vertical axis (OpenCascade's Y of the top view is -Y of the model)."""
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
    algo = HLRBRep_Algo()
    algo.Add(shape.wrapped)
    algo.Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*direction), gp_Dir(*xdir))))
    algo.Update()
    algo.Hide()
    h = HLRBRep_HLRToShape(algo)
    vis = _edges_2d(h.VCompound()) + _edges_2d(h.Rg1LineVCompound()) + _edges_2d(h.OutLineVCompound())
    hid = _edges_2d(h.HCompound()) + _edges_2d(h.Rg1LineHCompound()) + _edges_2d(h.OutLineHCompound())
    if flip_v:
        vis = [[(x, -y) for x, y in pl] for pl in vis]
        hid = [[(x, -y) for x, y in pl] for pl in hid]
    xs = [p[0] for pl in vis + hid for p in pl] or [0]
    ys = [p[1] for pl in vis + hid for p in pl] or [0]
    return {"visible": vis, "hidden": hid, "bounds": (min(xs), min(ys), max(xs), max(ys))}


def three_views(shape: cq.Shape) -> dict:
    bb = shape.BoundingBox()
    return {"front": hlr_view(shape, (0, -1, 0), (1, 0, 0)), "top": hlr_view(shape, (0, 0, -1), (1, 0, 0), flip_v=True),
            "right": hlr_view(shape, (1, 0, 0), (0, 1, 0)),
            "size": (bb.xlen, bb.ylen, bb.zlen)}


def drawing_dxf(views: dict, title: str) -> bytes:
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.layers.add("VISIBLE", color=7)
    doc.layers.add("HIDDEN", color=8, linetype="DASHED")
    doc.layers.add("DIM", color=3)
    msp = doc.modelspace()
    L, W, H = views["size"]
    gap = max(L, W, H) * 0.35
    origins = {"front": (0, 0), "top": (0, H + gap), "right": (L + gap, 0)}
    for name, (ox, oy) in origins.items():
        v = views[name]
        x0, y0 = v["bounds"][0], v["bounds"][1]
        for layer, key in (("VISIBLE", "visible"), ("HIDDEN", "hidden")):
            for pl in v[key]:
                msp.add_lwpolyline([(x - x0 + ox, y - y0 + oy) for x, y in pl], dxfattribs={"layer": layer})
        w, h = v["bounds"][2] - x0, v["bounds"][3] - y0
        msp.add_linear_dim(base=(ox, oy - 12), p1=(ox, oy), p2=(ox + w, oy), dimstyle="EZDXF", dxfattribs={"layer": "DIM"}).render()
        msp.add_linear_dim(base=(ox - 12, oy), p1=(ox, oy), p2=(ox, oy + h), angle=90, dimstyle="EZDXF", dxfattribs={"layer": "DIM"}).render()
        msp.add_text(name.upper(), dxfattribs={"height": 5}).set_placement((ox, oy + h + 6))
    msp.add_text(title, dxfattribs={"height": 6}).set_placement((0, -35))
    s = io.StringIO()
    doc.write(s)
    return s.getvalue().encode()


def drawing_pdf(pages: list[dict]) -> bytes:
    """A3 landscape drawing sheets, one per page = {views, title, subtitle, notes}: front / top / right with overall dimensions."""
    from reportlab.graphics import renderPDF
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from .pdf_report import _theme
    theme = _theme()
    page = landscape(A3)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=page)
    for pg in pages:
        views, title, subtitle, notes = pg["views"], pg["title"], pg.get("subtitle", ""), pg.get("notes", [])
        L, W, H = views["size"]
        gap = max(L, W, H) * 0.3
        total_w, total_h = L + gap + max(W, 1), H + gap + max(W, 1)
        sc = min((page[0] - 60 * mm) / total_w, (page[1] - 100 * mm) / total_h)
        d = Drawing(page[0], page[1])
        origins = {"front": (30 * mm, 40 * mm), "top": (30 * mm, 40 * mm + (H + gap) * sc),
                   "right": (30 * mm + (L + gap) * sc, 40 * mm)}
        for name, (ox, oy) in origins.items():
            v = views[name]
            x0, y0, x1, y1 = v["bounds"]
            for pl in v["hidden"]:
                d.add(PolyLine([k for x, y in pl for k in (ox + (x - x0) * sc, oy + (y - y0) * sc)], strokeColor=theme["grey"],
                               strokeWidth=0.3, strokeDashArray=[2, 2]))
            for pl in v["visible"]:
                d.add(PolyLine([k for x, y in pl for k in (ox + (x - x0) * sc, oy + (y - y0) * sc)], strokeColor=theme["ink"], strokeWidth=0.7))
            w, h = (x1 - x0) * sc, (y1 - y0) * sc
            for (ax, ay, bx, by, label, vert) in ((ox, oy - 8 * mm, ox + w, oy - 8 * mm, f"{x1 - x0:.1f}", False),
                                                  (ox - 8 * mm, oy, ox - 8 * mm, oy + h, f"{y1 - y0:.1f}", True)):
                d.add(Line(ax, ay, bx, by, strokeColor=theme["brand"], strokeWidth=0.5))
                if vert:
                    d.add(Line(ax - 2, ay, ax + 2, ay, strokeColor=theme["brand"])); d.add(Line(bx - 2, by, bx + 2, by, strokeColor=theme["brand"]))
                    d.add(String(ax - 3, (ay + by) / 2, label, fontSize=8, textAnchor="end", fillColor=theme["brand"]))
                else:
                    d.add(Line(ax, ay - 2, ax, ay + 2, strokeColor=theme["brand"])); d.add(Line(bx, by - 2, bx, by + 2, strokeColor=theme["brand"]))
                    d.add(String((ax + bx) / 2, ay - 10, label, fontSize=8, textAnchor="middle", fillColor=theme["brand"]))
            d.add(String(ox, oy + h + 4 * mm, name.upper(), fontSize=9, fillColor=theme["brand"]))
        renderPDF.draw(d, c, 0, 0)
        c.setFillColor(theme["ink"]); c.setFont("Helvetica-Bold", 14); c.drawString(30 * mm, page[1] - 20 * mm, title)
        c.setFont("Helvetica", 9); c.setFillColor(theme["grey"]); c.drawString(30 * mm, page[1] - 27 * mm, subtitle)
        y = 26 * mm
        c.setFont("Helvetica", 8)
        for n in notes[:4]:
            c.drawString(30 * mm, y, n[:170]); y -= 4.5 * mm
        c.setStrokeColor(theme["border"]); c.rect(15 * mm, 12 * mm, page[0] - 30 * mm, page[1] - 24 * mm)
        c.showPage()
    c.save()
    return buf.getvalue()


# ------------------------------------------------------------ video

def video_mp4(frames: list[bytes], fps: int = 12) -> bytes:
    """Encode PNG frames to an H.264 MP4 with the ffmpeg that imageio-ffmpeg ships (or the one on the PATH)."""
    import subprocess
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ff = "ffmpeg"
    with tempfile.TemporaryDirectory() as d:
        for i, f in enumerate(frames):
            Path(d, f"f{i:04d}.png").write_bytes(f)
        out = Path(d, "out.mp4")
        subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(Path(d, "f%04d.png")),
                        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
        return out.read_bytes()
