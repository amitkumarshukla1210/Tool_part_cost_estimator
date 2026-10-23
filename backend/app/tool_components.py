"""Production data of a tool design (roadmap stage 21): everything a supplier needs to buy steel and machine the parts.

For every component of the 3D tool design:
    class          Component classes (master data): steel, stock allowance, grinding allowance, hardness, tolerances, route
    features       holes (Ø, depth, position), openings and pockets (size, depth, wire-cut length), fillet radii, read from the solid
    raw stock      finished size + allowances, rounded up; weight; steel cost from the approved tool-steel rate of the tool country
    machining      operations from the class (saw, rough, finish, grind, drill, wire, edm, polish, heat), hours from the Process time
                   parameters, priced like the tool cost (MHR + operators × labour rate; unit rates with minimum charge)
    bill of mat.   made parts (drawing each), bought-out standard parts (tool BOM and Standard parts), assembly steps
    checks         valid solid, interference between components, fit of every part against its neighbours
Nothing is typed into the code: classes, standard parts and assembly steps are master-data rows (EXAMPLE values until replaced).
"""

from __future__ import annotations

import math
from collections import defaultdict

import cadquery as cq
import numpy as np

from . import corrections, formula, master_data, mould_db, rate_engine, rates

KIND_MADE, KIND_STD = "made", "standard"
NON_TOOL = ("work", "part", "proposal")             # shown in the viewer, not in the BOM
INTERFERENCE_MM3 = 5.0
MOULD_VARS = ("cavities", "base_l_mm", "base_w_mm", "plate_a_mm", "plate_b_mm", "pillar_dia_mm", "pillars", "part_h_mm")
TIME_DEFAULTS = {"drill_mm_per_h": 600.0, "drill_hole_setup_h": 0.05}

CLASS_NOTE = "EXAMPLE - replace with your steel supplier / toolroom practice"
_P = "Mould base steel (4140 / 1.7225)"
_C = "C45 / S50C"
_MILL = "Saw stock, mill six faces, grind faces, CNC pockets and holes, deburr"
SEED_CLASSES = [
    # code, name, kind, steel, allow, grind, round, hardness, ops, Ra, tolerance, route
    ("base_plate", "Mould / die plate (A, B)", "made", _P, 3, 0.6, 5, "28-32 HRC pre-hardened", "saw,rough,finish,grind,drill", 1.6,
     "ISO 2768-m; pockets and bores H7; flatness and parallelism 0.02", _MILL),
    ("clamp_plate", "Clamp plate", "made", _C, 3, 0.4, 5, "annealed", "saw,rough,grind,drill", 3.2, "ISO 2768-m; parallelism 0.05",
     "Saw, mill, grind faces, drill and tap, deburr"),
    ("support_plate", "Support plate", "made", _P, 3, 0.5, 5, "28-32 HRC pre-hardened", "saw,rough,grind,drill", 1.6,
     "ISO 2768-m; flatness and parallelism 0.02", "Saw, mill, grind faces, drill, deburr"),
    ("spacer_block", "Spacer block", "made", _C, 3, 0.4, 5, "annealed", "saw,rough,grind,drill", 3.2,
     "ISO 2768-m; height equal within 0.02 across blocks", "Saw, mill, grind to common height, drill and tap"),
    ("ejector_plate", "Ejector plate", "made", _C, 3, 0.4, 5, "annealed", "saw,rough,grind,drill", 3.2,
     "ISO 2768-m; pin holes H7 where marked", "Saw, mill, grind faces, drill and counterbore"),
    ("insert_a", "Cavity / core insert (A side)", "made", "P20 (1.2311)", 4, 0.4, 5, "30-36 HRC pre-hardened",
     "saw,rough,finish,grind,drill,edm,polish", 0.4, "ISO 2768-f; forming surface per 3D model ±0.02; fits H7", 
     "Saw, rough mill, finish mill, EDM details, grind faces, polish, texture as specified"),
    ("insert_b", "Core / cavity insert (B side)", "made", "P20 (1.2311)", 4, 0.4, 5, "30-36 HRC pre-hardened",
     "saw,rough,finish,grind,drill,edm,polish", 0.4, "ISO 2768-f; forming surface per 3D model ±0.02; fits H7",
     "Saw, rough mill, finish mill, EDM details, grind faces, polish, texture as specified"),
    ("insert_a_hot", "Die insert (A side, hot work)", "made", "H13 (1.2344)", 4, 0.4, 5, "44-48 HRC",
     "saw,rough,finish,heat,grind,drill,edm,polish", 0.4, "ISO 2768-f; forming surface per 3D model ±0.02; fits H7",
     "Saw, rough mill, vacuum harden and temper, finish mill, EDM, grind, polish, nitride if specified"),
    ("insert_b_hot", "Die insert (B side, hot work)", "made", "H13 (1.2344)", 4, 0.4, 5, "44-48 HRC",
     "saw,rough,finish,heat,grind,drill,edm,polish", 0.4, "ISO 2768-f; forming surface per 3D model ±0.02; fits H7",
     "Saw, rough mill, vacuum harden and temper, finish mill, EDM, grind, polish, nitride if specified"),
    ("insert_a_alu", "Mould block (A side, aluminium)", "made", "Aluminium 7075-T6", 4, 0.4, 5, "T6", "saw,rough,finish,drill,polish", 0.8,
     "ISO 2768-m; forming surface per 3D model ±0.05", "Saw, mill, finish mill, bead blast / polish as specified"),
    ("insert_b_alu", "Mould block (B side, aluminium)", "made", "Aluminium 7075-T6", 4, 0.4, 5, "T6", "saw,rough,finish,drill,polish", 0.8,
     "ISO 2768-m; forming surface per 3D model ±0.05", "Saw, mill, finish mill, bead blast / polish as specified"),
    ("shoe", "Die shoe (upper, lower)", "made", _C, 3, 0.5, 5, "annealed", "saw,rough,grind,drill", 3.2,
     "ISO 2768-m; flatness and parallelism 0.03; pillar and bush bores H7", _MILL),
    ("die_block", "Die block / buttons", "made", "D2 (1.2379)", 3, 0.4, 5, "58-62 HRC", "saw,rough,wire,heat,grind,drill,polish", 0.8,
     "ISO 2768-f; openings per drawing, wire-cut after hardening; clearance as stated", "Saw, rough mill and drill, vacuum harden, grind faces, wire cut openings, polish"),
    ("stripper", "Stripper plate", "made", _P, 3, 0.5, 5, "28-32 HRC pre-hardened", "saw,rough,wire,grind,drill", 1.6,
     "ISO 2768-m; openings per drawing, guided fit to punches H7/g6", "Saw, mill, grind faces, wire cut openings, drill and tap"),
    ("punch_plate", "Punch plate", "made", _C, 3, 0.4, 5, "annealed", "saw,rough,wire,grind,drill", 1.6,
     "ISO 2768-m; punch seats H7", "Saw, mill, grind faces, wire cut punch seats, drill and tap"),
    ("backing_plate", "Backing plate", "made", "D2 (1.2379)", 3, 0.3, 5, "50-55 HRC", "saw,rough,heat,grind,drill", 1.6,
     "ISO 2768-m; flatness and parallelism 0.01", "Saw, mill, harden, grind faces, drill"),
    ("punch", "Punch", "made", "D2 (1.2379)", 3, 0.3, 5, "58-62 HRC", "saw,rough,wire,heat,grind,polish", 0.4,
     "ISO 2768-f; cutting edge sharp, profile per drawing", "Saw, rough mill, wire cut profile, vacuum harden, grind, polish cutting edges"),
    ("guide_pillar", "Guide pillar", "standard", "", 0, 0, 0, "", "", None, "h6 / catalogue", "Catalogue part"),
    ("guide_bush", "Guide bush", "standard", "", 0, 0, 0, "", "", None, "H7 / catalogue", "Catalogue part"),
    ("locating_ring", "Locating ring", "standard", "", 0, 0, 0, "", "", None, "catalogue", "Catalogue part"),
    ("sprue_bush", "Sprue bush", "standard", "", 0, 0, 0, "", "", None, "catalogue", "Catalogue part"),
]
SEED_STANDARD = [
    # group, item, spec, quantity rule, unit cost INR, unit
    ("mould", "Socket head cap screw", "M{screw_dia_mm:.0f} × length for the plate stack, 12.9", "4 * ceil(base_l_mm / 150) + 8", 28, "pcs"),
    ("mould", "Dowel pin", "Ø{dowel_dia_mm:.0f} h6 hardened", "8", 18, "pcs"),
    ("mould", "Eye bolt", "M{screw_dia_mm:.0f} lifting", "2", 150, "pcs"),
    ("sheet_metal", "Guide pillar", "Ø{pillar_dia_mm:.0f} h6, ground, press-fit in the lower shoe", "pillars", 650, "pcs"),
    ("sheet_metal", "Guide bush", "Ø{pillar_dia_mm:.0f} H7, self-lubricating, in the upper shoe", "pillars", 450, "pcs"),
    ("sheet_metal", "Stripper spring", "Die spring, rated {spring_rating_kgf:.0f} kgf at working stroke", "springs", 95, "pcs"),
    ("sheet_metal", "Socket head cap screw", "M{screw_dia_mm:.0f}, 12.9", "screws", 28, "pcs"),
    ("sheet_metal", "Dowel pin", "Ø{dowel_dia_mm:.0f} h6 hardened", "dowels", 18, "pcs"),
    ("sheet_metal", "Stripper bolt", "Shoulder bolt for the stripper plate", "4", 60, "pcs"),
]
SEED_STEPS = [
    ("mould", 1, "Check every machined part against its drawing and the inspection list; record the key dimensions.", "0.5"),
    ("mould", 2, "Fit guide pillars into the B plate and guide bushes into the A plate; check the plates slide freely.", "1.0"),
    ("mould", 3, "Fit the core and cavity inserts in their plate pockets; blue the parting faces and spot them to the drawing.", "6 + base_l_mm / 100"),
    ("mould", 4, "Assemble the ejector plates with the ejector and return pins; check ejection travel.", "2.0"),
    ("mould", 5, "Fit the support plate, spacer blocks and bottom clamp plate; fit the sprue bush and locating ring.", "1.5"),
    ("mould", 6, "Connect cooling and test for leaks; fit slides, lifters and hot runner where designed.", "3.0"),
    ("mould", 7, "Close the mould, check the parting line seal and shut-off faces, then send for try-out.", "2.0"),
    ("sheet_metal", 1, "Check every machined part against its drawing and the inspection list.", "0.5"),
    ("sheet_metal", 2, "Fit the guide pillars into the lower shoe and the bushes into the upper shoe.", "1.0"),
    ("sheet_metal", 3, "Fit the die block (and buttons) on the lower shoe; dowel and screw it.", "3 + die_set_l_mm / 150"),
    ("sheet_metal", 4, "Fit the punch plate, backing plate and punches to the upper shoe; check the punch-to-die clearance all round.", "4 + die_set_l_mm / 150"),
    ("sheet_metal", 5, "Fit the stripper plate and springs; set the stripper to the stated height.", "1.5"),
    ("sheet_metal", 6, "Close the die, check shut height and parallelism, then send for try-out.", "2.0"),
]
SEED_STAGE_RULES = [
    ("all", "spring_rating_kgf", "60", "kgf", "Rating of one stripper spring at working stroke"),
    ("all", "springs", "max(4, 2 * ceil(strip_force_t * 1000 / spring_rating_kgf / 2))", "pcs", "Stripper springs (an even number, at least 4)"),
    ("all", "screw_dia_mm", "max(8, round(die_block_t_mm / 4))", "mm", "Socket head screw size"),
    ("all", "screws", "4 * max(2, ceil(max(die_set_l_mm, die_set_w_mm) / 150))", "pcs", "Screws fixing the plates of the die set"),
    ("all", "dowel_dia_mm", "max(8, screw_dia_mm)", "mm", "Dowel pin diameter"),
    ("all", "dowels", "4", "pcs", "Dowel pins fixing the plates of the die set"),
]


class ProductionError(ValueError):
    pass


# ------------------------------------------------------------ master data

def seed() -> dict:
    """Component classes, standard parts, assembly steps, spring / screw rules and the drill time parameters (EXAMPLE values)."""
    from . import tool_design
    out = {"classes": 0, "standard_parts": 0, "assembly_steps": 0, "stage_rules": 0, "time_parameters": 0}
    db = mould_db.tables()
    have = {r["code"] for r in db["component_classes"]}
    for code, name, kind, steel, allow, grind, rnd, hard, ops, ra, tol, route in SEED_CLASSES:
        if code not in have:
            db["component_classes"].append({"code": code, "name": name, "kind": kind, "steel": steel, "stock_allow_mm": allow,
                                            "grind_allow_mm": grind, "round_mm": rnd, "hardness": hard, "ops": ops,
                                            "finish_ra": ra or 0, "tolerance": tol, "route": route, "is_example": 1, "notes": CLASS_NOTE})
            out["classes"] += 1
    have = {(r["tool_group"], r["item"]) for r in db["standard_parts"]}
    for g, item, spec, qty, cost, unit in SEED_STANDARD:
        if (g, item) not in have:
            db["standard_parts"].append({"tool_group": g, "item": item, "spec": spec, "quantity_rule": qty, "unit_cost": cost, "unit": unit,
                                         "is_example": 1, "notes": CLASS_NOTE})
            out["standard_parts"] += 1
    have = {(r["tool_group"], r["step"]) for r in db["assembly_steps"]}
    for g, step, text, hours in SEED_STEPS:
        if (g, step) not in have:
            db["assembly_steps"].append({"tool_group": g, "step": step, "text": text, "hours": hours, "is_example": 1, "notes": CLASS_NOTE})
            out["assembly_steps"] += 1
    have = {(r["op"], r["name"]) for r in db["stage_rules"]}
    top = max((r["step"] for r in db["stage_rules"]), default=0)
    for i, (op, name, f, unit, label) in enumerate(SEED_STAGE_RULES, start=1):
        if (op, name) not in have:
            db["stage_rules"].append({"op": op, "step": top + i, "name": name, "formula": f, "unit": unit, "label": label,
                                      "is_example": 1, "notes": tool_design.EXAMPLE})
            out["stage_rules"] += 1
    # process time parameters for the part types that had none (copied from plastic) and the drilling rates
    tp = db["time_parameters"]
    plastic = [r for r in tp if r["part_type"] == "plastic"]
    for pt in ("sheet_metal", "foundry"):
        if not any(r["part_type"] == pt for r in tp):
            for r in plastic:
                tp.append(dict(r, part_type=pt, is_example=1))
                out["time_parameters"] += 1
    for pt in {r["part_type"] for r in tp}:
        for k, v in TIME_DEFAULTS.items():
            if not any(r["part_type"] == pt and r["parameter"] == k for r in tp):
                tp.append({"part_type": pt, "parameter": k, "value": v, "unit": "mm/h" if "mm" in k else "h",
                           "description": "Drilling rate / set-up per hole for the component machining estimate", "is_example": 1})
                out["time_parameters"] += 1
    if any(out.values()):
        mould_db.write(db)
    return out


def _env_names() -> dict:
    from . import tool_design
    env = {k: 1.0 for k in tool_design.STAGE_VARS + MOULD_VARS}
    env |= {k: 1.0 for k in ("springback_deg", "draw_ratio", "progressive_ok")}
    env |= {k: float(v) for k, v in master_data.parameters("sheet_metal").items() if isinstance(v, (int, float))}
    env |= {"dowel_dia_mm": 8.0, "spring_rating_kgf": 60.0, "screw_dia_mm": 10.0, "springs": 4.0, "screws": 8.0, "dowels": 4.0,
            "die_set_l_mm": 300.0, "die_set_w_mm": 200.0, "strip_force_t": 1.0, "die_block_t_mm": 40.0, "pillars": 4.0, "pillar_dia_mm": 25.0}
    return env


def validate(clean: dict) -> None:
    env = _env_names() | {r["name"]: 1.0 for r in clean.get("stage_rules", [])}
    steels = {r["code"] for r in clean["tool_materials"]}
    for i, r in enumerate(clean.get("component_classes", []), start=2):
        if r["kind"] == KIND_MADE and r["steel"] not in steels:
            raise mould_db.MouldDbError(f"Component classes row {i}: steel '{r['steel']}' is not in Tool materials.")
        bad = [t for t in (x.strip() for x in (r["ops"] or "").split(",")) if t and t not in OPS]
        if bad:
            raise mould_db.MouldDbError(f"Component classes row {i}: unknown operation '{bad[0]}' (use {', '.join(OPS)}).")
    for i, r in enumerate(clean.get("standard_parts", []), start=2):
        try:
            formula.evaluate(r["quantity_rule"], env)
        except formula.FormulaError as exc:
            raise mould_db.MouldDbError(f"Standard parts row {i}, quantity: {exc}") from None
        except ArithmeticError:
            pass
        try:
            r["spec"].format(**env)
        except (KeyError, IndexError, ValueError) as exc:
            raise mould_db.MouldDbError(f"Standard parts row {i}, specification: unknown name {exc}.") from None
    for i, r in enumerate(clean.get("assembly_steps", []), start=2):
        try:
            formula.evaluate(r["hours"], env)
        except formula.FormulaError as exc:
            raise mould_db.MouldDbError(f"Assembly steps row {i}, hours: {exc}") from None
        except ArithmeticError:
            pass


OPS = ("saw", "rough", "finish", "grind", "drill", "wire", "edm", "polish", "heat", "vacuum")


def class_row(cls: str, part_type: str) -> dict | None:
    rows = {r["code"]: r for r in mould_db.tables()["component_classes"]}
    suffix = {"die_casting": "_hot", "eps": "_alu", "blow": "_alu"}.get(part_type, "")
    return rows.get(cls + suffix) or rows.get(cls)


# ------------------------------------------------------------ geometry features

def _cyl(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    c = BRepAdaptor_Surface(face.wrapped).Cylinder()
    ax, loc = c.Axis().Direction(), c.Axis().Location()
    return c.Radius(), cq.Vector(ax.X(), ax.Y(), ax.Z()), cq.Vector(loc.X(), loc.Y(), loc.Z())


def features(shape: cq.Shape) -> dict:
    """Holes, openings, pockets and fillet radii of a component, in its own datum (bounding-box minimum corner = 0)."""
    bb = shape.BoundingBox()
    o = np.array([bb.xmin, bb.ymin, bb.zmin])
    size = np.array([bb.xlen, bb.ylen, bb.zlen])
    holes, fillets, openings, pockets = defaultdict(list), [], [], []
    surface = 0.0
    box_area = 0.0
    for f in shape.Faces():
        a = f.Area()
        surface += a
        if f.geomType() == "PLANE":
            n = f.normalAt()
            c = f.Center()
            for ax, (nv, cv, lo, hi) in enumerate(((n.x, c.x, bb.xmin, bb.xmax), (n.y, c.y, bb.ymin, bb.ymax), (n.z, c.z, bb.zmin, bb.zmax))):
                if abs(nv) > 0.999 and (abs(cv - lo) < 1e-3 or abs(cv - hi) < 1e-3):
                    box_area += a
                    break
            continue
        if f.geomType() != "CYLINDER":
            continue
        r, axis, loc = _cyl(f)
        verts, _ = f.tessellate(0.1)
        pts = np.array([[v.x, v.y, v.z] for v in verts])
        along = pts @ np.array([axis.x, axis.y, axis.z])
        height = float(along.max() - along.min())
        p = corrections.sample_point(f)
        n = f.normalAt(p)
        radial = cq.Vector(loc.x - p.x, loc.y - p.y, loc.z - p.z)
        radial = radial - axis * radial.dot(axis)
        concave = n.dot(radial) > 0
        full = a > 0.9 * 2 * math.pi * r * height
        mid = float((along.max() + along.min()) / 2)
        base = np.array([loc.x, loc.y, loc.z]) + np.array([axis.x, axis.y, axis.z]) * (mid - np.array([loc.x, loc.y, loc.z]) @ np.array([axis.x, axis.y, axis.z]))
        ax_i = int(np.argmax(np.abs([axis.x, axis.y, axis.z])))
        extent = float(size[ax_i])
        if full and concave:
            key = (round(2 * r, 3), round(height, 2), ax_i)
            holes[key].append((base - o).round(3).tolist())
        else:
            fillets.append({"radius_mm": round(r, 3), "convex": not concave, "length_mm": round(height, 2),
                            "at_mm": (base - o).round(2).tolist()})
    hole_rows = []
    for (d, depth, ax_i), where in sorted(holes.items()):
        extent = float(size[ax_i])
        hole_rows.append({"dia_mm": d, "depth_mm": depth, "axis": "xyz"[ax_i], "through": depth >= extent - 0.01, "count": len(where),
                          "positions_mm": where})
    # openings and pockets seen from the top (+Z): inner wires of the top face, and pocket floors below the top
    top_faces = [f for f in shape.Faces() if f.geomType() == "PLANE" and f.normalAt().z > 0.999]
    zmax = bb.zmax
    for f in top_faces:
        fz = f.Center().z
        if abs(fz - zmax) < 1e-3:
            for w in f.innerWires():
                edges = w.Edges()
                if len(edges) == 1 and edges[0].geomType() == "CIRCLE":
                    continue                                       # a round hole: already listed
                wb = w.BoundingBox()
                openings.append({"x_mm": round(wb.xmin - o[0], 2), "y_mm": round(wb.ymin - o[1], 2), "length_mm": round(wb.xlen, 2),
                                 "width_mm": round(wb.ylen, 2), "perimeter_mm": round(w.Length(), 1),
                                 "area_mm2": round(cq.Face.makeFromWires(w).Area(), 1)})
        elif zmax - fz > 0.5 and f.Area() > 4.0:
            fb = f.BoundingBox()
            pockets.append({"x_mm": round(fb.xmin - o[0], 2), "y_mm": round(fb.ymin - o[1], 2), "length_mm": round(fb.xlen, 2),
                            "width_mm": round(fb.ylen, 2), "depth_mm": round(zmax - fz, 2), "area_mm2": round(f.Area(), 1)})
    # an opening is 'through' when the bottom face has the same outline
    bottom = [f for f in shape.Faces() if f.geomType() == "PLANE" and f.normalAt().z < -0.999 and abs(f.Center().z - bb.zmin) < 1e-3]
    for op in openings:
        op["through"] = any(abs(w.BoundingBox().xlen - op["length_mm"]) < 0.05 and abs(w.BoundingBox().ylen - op["width_mm"]) < 0.05
                            for f in bottom for w in f.innerWires())
    return {"size_mm": size.round(3).tolist(), "datum": "bounding-box minimum corner", "holes": hole_rows,
            "hole_count": sum(h["count"] for h in hole_rows), "openings": openings, "pockets": pockets,
            "fillets": sorted(fillets, key=lambda x: -x["radius_mm"])[:40], "surface_cm2": round(surface / 100, 2),
            "box_face_cm2": round(box_area / 100, 2), "forming_cm2": round(max(surface - box_area, 0) / 100, 2)}


# ------------------------------------------------------------ stock, machining, prices

def _density(steel: str) -> float:
    row = next((r for r in mould_db.tables()["tool_materials"] if r["code"] == steel), None)
    return row["density_g_cm3"] if row else 7.85


def stock(shape: cq.Shape, cls: dict) -> dict:
    """Raw stock: the finished bounding box plus the class allowances, rounded up. Weights by the steel's density."""
    bb = shape.BoundingBox()
    dims = [bb.xlen, bb.ylen, bb.zlen]
    allow, grind, step = cls["stock_allow_mm"] or 0, cls["grind_allow_mm"] or 0, cls["round_mm"] or 1
    raw = [d + 2 * allow for d in dims]
    z = int(np.argmin(dims))
    raw[z] += grind                                                    # grinding stock on the thickness
    raw = [math.ceil(d / step) * step for d in raw]
    dens = _density(cls["steel"])
    vol = raw[0] * raw[1] * raw[2]
    return {"size_mm": [round(x, 1) for x in raw], "weight_kg": round(vol * dens / 1e6, 2),
            "finished_weight_kg": round(shape.Volume() * dens / 1e6, 2), "removed_cm3": round((vol - shape.Volume()) / 1000, 1),
            "steel": cls["steel"], "density": dens}


def _lookup(category: str, item: str, country: str, month: str) -> float | None:
    try:
        return float(rates.lookup(category, item, country, month)["value"])
    except Exception:
        return None


def process_price(process: str, amount: float, country: str, month: str) -> dict:
    """Price of `amount` hours (machine / labour processes) or units (unit processes) like the tool cost engine does it."""
    row = next((r for r in mould_db.tables()["tool_processes"] if r["code"] == process), None)
    if not row:
        return {"cost": None, "note": f"'{process}' is not in Tool processes"}
    try:
        if row["pricing"] == "unit":
            rate = rates.lookup("process_unit", process, country, month)["value"]
            try:
                minimum = rates.lookup("process_min_charge", process, country, month)["value"]
            except Exception:
                minimum = 0.0
            return {"cost": max(amount * rate, minimum if amount > 0 else 0), "rate": rate, "min": minimum}
        if row["pricing"] == "labour_hour":
            lab = rate_engine.labour_rate(row["labour_grade"], country, month)["value"]
            return {"cost": amount * lab * (row["operators"] or 1), "rate": lab}
        mhr = rate_engine.mhr(row["machine_id"], country, month)["value"]
        lab = rate_engine.labour_rate(row["labour_grade"], country, month)["value"] if row["operators"] else 0.0
        rate = mhr + (row["operators"] or 0) * lab
        return {"cost": amount * rate, "rate": rate}
    except Exception as exc:
        return {"cost": None, "note": str(exc)[:80]}


def machining(shape: cq.Shape, feats: dict, cls: dict, stk: dict, part_type: str, country: str, month: str) -> list[dict]:
    """Operations of a made component with hours (or amounts) from the class and the Process time parameters, and their cost."""
    rows = mould_db.tables()["time_parameters"]
    use = part_type if any(x["part_type"] == part_type for x in rows) else "plastic"
    tp = {**TIME_DEFAULTS, **{r["parameter"]: r["value"] for r in rows if r["part_type"] == use}}
    ops = {t.strip() for t in (cls["ops"] or "").split(",") if t.strip()}
    out = []

    def add(code, label, amount, unit, price_as=None):
        if amount and amount > 0:
            p = process_price(price_as or code, amount, country, month)
            out.append({"process": price_as or code, "label": label, "amount": round(amount, 2), "unit": unit,
                        "cost": None if p["cost"] is None else round(p["cost"]), "note": p.get("note", "")})
    if "saw" in ops:
        add("Cutting (per kg)", "Saw the stock", stk["weight_kg"], "kg")
    forming = feats["forming_cm2"]
    if "rough" in ops:
        add("CNC milling", "Rough milling and set-up", stk["removed_cm3"] / max(tp.get("cnc_rough_cm3_per_h", 300), 1e-9) + tp.get("cnc_setup_h", 2), "h")
    if "finish" in ops:
        add("CNC milling", "Finish milling of formed surfaces", forming / max(tp.get("cnc_finish_cm2_per_h", 40), 1e-9), "h")
    if "grind" in ops:
        add("Grinding", "Grind faces", feats["box_face_cm2"] / max(tp.get("grind_cm2_per_h", 600), 1e-9) + tp.get("grind_setup_h", 0.5), "h")
    if "drill" in ops and feats["hole_count"]:
        depth = sum(h["depth_mm"] * h["count"] for h in feats["holes"])
        add("CNC milling", f"Drill, bore and ream {feats['hole_count']} hole(s)", depth / tp.get("drill_mm_per_h", 600) +
            feats["hole_count"] * tp.get("drill_hole_setup_h", 0.05), "h")
    if "wire" in ops and feats["openings"]:
        area = sum(o["perimeter_mm"] * feats["size_mm"][2] for o in feats["openings"]) / 100
        add("Wire cut (per cm²)", f"Wire cut {len(feats['openings'])} opening(s)", area, "cm²")
    if "edm" in ops and forming:
        add("EDM", "EDM of details", tp.get("edm_share_pct", 15) / 100 * forming / max(tp.get("edm_cm2_per_h", 8), 1e-9) + tp.get("edm_setup_h", 2), "h")
    if "polish" in ops and forming:
        add("Polishing", "Polish formed surfaces", tp.get("polish_share_pct", 50) / 100 * forming / max(tp.get("polish_cm2_per_h", 40), 1e-9), "h")
    if "heat" in ops:
        add("Heat treatment (per kg)", "Harden and temper", stk["finished_weight_kg"] * 1.0, "kg")
    if "vacuum" in ops:
        add("Vacuum heat treatment (per kg)", "Vacuum harden and temper", stk["finished_weight_kg"], "kg")
    return out


def component_info(shape: cq.Shape, cls_code: str, part_type: str, country: str, month: str) -> dict:
    """Everything the drawing, BOM and PO need about one made component."""
    cls = class_row(cls_code, part_type)
    if cls is None or cls["kind"] != KIND_MADE:
        raise ProductionError(f"No made-component class '{cls_code}' in Component classes.")
    feats = features(shape)
    stk = stock(shape, cls)
    ops = machining(shape, feats, cls, stk, part_type, country, month)
    rate = _lookup("tool_material", cls["steel"], country, month)
    bb = shape.BoundingBox()
    return {"class": cls["code"], "class_name": cls["name"], "steel": cls["steel"], "hardness": cls["hardness"], "tolerance": cls["tolerance"],
            "route": cls["route"], "finish_ra": cls["finish_ra"], "ops_codes": cls["ops"],
            "bbox_mm": [round(bb.xlen, 2), round(bb.ylen, 2), round(bb.zlen, 2)],
            "bbox_min": [round(bb.xmin, 2), round(bb.ymin, 2), round(bb.zmin, 2)], "volume_cm3": round(shape.Volume() / 1000, 2),
            "features": feats, "stock": stk, "operations": ops, "steel_rate": rate,
            "material_cost": None if rate is None else round(stk["weight_kg"] * rate),
            "machining_cost": round(sum(o["cost"] or 0 for o in ops)), "is_example": bool(cls["is_example"])}


# ------------------------------------------------------------ bill of materials

def standard_lines(tool_group: str, env: dict) -> list[dict]:
    """Bought-out parts from the Standard parts rows of the tool group: quantity by rule, spec filled in."""
    out = []
    for r in mould_db.tables()["standard_parts"]:
        if r["tool_group"] != tool_group:
            continue
        try:
            qty = formula.evaluate(r["quantity_rule"], env)
            spec = r["spec"].format(**env)
        except (formula.FormulaError, KeyError, ArithmeticError, ValueError):
            continue
        if qty > 0:
            out.append({"item": r["item"], "spec": spec, "quantity": round(float(qty)), "unit": r["unit"], "unit_cost_inr": r["unit_cost"],
                        "amount_inr": round(float(qty) * r["unit_cost"]), "source": "Standard parts", "is_example": bool(r["is_example"])})
    return out


def bom_standard_lines(tool: dict) -> list[dict]:
    """Bought-out lines of the tool cost BOM (pillars, bushes, ejector pins, hot runner …) with their catalogue prices."""
    out = []
    for l in tool.get("lines", []):
        if l.get("category") != "bought_out" or l.get("is_base") or not l.get("quantity"):
            continue
        out.append({"item": l["element"], "spec": "per tool-cost BOM", "quantity": round(l["quantity"]), "unit": "pcs",
                    "unit_cost_inr": round(l["bought_out_cost"] / l["quantity"], 2) if l["quantity"] else 0,
                    "amount_inr": round(l["bought_out_cost"]), "source": "Tool cost BOM", "is_example": bool(l.get("is_example"))})
    return out


def assembly_steps(tool_group: str, env: dict) -> list[dict]:
    rows = sorted((r for r in mould_db.tables()["assembly_steps"] if r["tool_group"] == tool_group), key=lambda r: r["step"])
    out = []
    for r in rows:
        try:
            h = float(formula.evaluate(r["hours"], env))
        except (formula.FormulaError, ArithmeticError):
            h = 0.0
        out.append({"step": int(r["step"]), "text": r["text"], "hours": round(h, 1), "is_example": bool(r["is_example"])})
    return out


# ------------------------------------------------------------ checks

def interference(items: list[dict]) -> list[dict]:
    """Pairs of components whose solids overlap by more than INTERFERENCE_MM3. items = [{id, name, shape}]."""
    boxes = [(it, it["shape"].BoundingBox()) for it in items]
    out = []
    for i in range(len(boxes)):
        a, ba = boxes[i]
        for j in range(i + 1, len(boxes)):
            b, bb = boxes[j]
            if ba.xmax < bb.xmin or bb.xmax < ba.xmin or ba.ymax < bb.ymin or bb.ymax < ba.ymin or ba.zmax < bb.zmin or bb.zmax < ba.zmin:
                continue
            try:
                v = a["shape"].intersect(b["shape"]).Volume()
            except Exception:
                continue
            if v > INTERFERENCE_MM3:
                out.append({"a": a["id"], "b": b["id"], "a_name": a["name"], "b_name": b["name"], "volume_mm3": round(v, 1)})
    return sorted(out, key=lambda x: -x["volume_mm3"])
