"""Simulation & analysis v1 (roadmap stage 6) for plastic mouldings and die castings.

    mesh                -> wall thickness per face (ray from the face into the part), draft angle per face to the
                           opening direction, undercut faces (concept.py)
    maps + rules        -> thin / thick (sink-risk) / low-draft / undercut areas
    Simulation rules    -> cooling / solidification time -> cycle time; flow length / wall -> pressure -> clamp force
    clamp force         -> smallest machine of Parameters → trial_machine_process whose tonnage takes it
    all of it           -> "Corrections required" and a coloured PDF report

Every number comes from Mould & die database → Simulation rules (formulas evaluated in order, each may use the
ones before), Parameters, Insert moulding rules and the 3D file. Analytical estimates, not Moldflow accuracy.
"""

from __future__ import annotations

import io
import math

import numpy as np

from . import concept, costing_setup, formula, master_data, mould_db, register_setup

REQUIRED = ("min_draft_deg", "thin_ratio", "sink_ratio", "cycle_s", "clamp_t")
SIM_VARS = concept.CONCEPT_VARS | {
    "max_wall_mm": "Thickest wall: 95th percentile of the measured thickness, by area (mm)",
    "min_wall_mm": "Thinnest wall: 5th percentile of the measured thickness, by area (mm)",
    "flow_length_mm": "Flow length estimate = part_l + part_h (gate on one edge) (mm)",
    "shot_weight_g": "Shot weight = part weight (body only, inserts excluded) × cavities (g)",
    "inserts_per_shot": "Moulded-in inserts × cavities",
}


def sample_env(part_type: str) -> dict:
    """Variables a Simulation rule can use, with sample values (to check the rules)."""
    env = {k: 1.0 for k in SIM_VARS}
    env |= {k: float(v) for k, v in master_data.parameters(part_type).items() if isinstance(v, (int, float))}
    if part_type == "plastic":
        env |= {k: float(r["value"]) for k, r in register_setup.insert_rules().items()}
    return env


def _rules(part_type: str) -> list[dict]:
    rows = sorted((r for r in mould_db.tables()["simulation_rules"] if r["part_type"] == part_type), key=lambda r: r["step"])
    missing = [k for k in REQUIRED if k not in {r["name"] for r in rows}]
    if missing:
        raise ValueError(f"Mould & die database → Simulation rules has no {', '.join(missing)} for '{part_type}'.")
    return rows


def _triangle_grid(tri: np.ndarray, resolution: int = 96) -> dict:
    bounds_min, bounds_max = tri.min(axis=1), tri.max(axis=1)
    lo, hi = bounds_min.min(axis=0), bounds_max.max(axis=0)
    span = hi - lo
    cell = float(max(span) / resolution)
    dims = np.maximum(1, np.ceil(span / cell).astype(int))
    cell_min = np.minimum(dims - 1, np.maximum(0, np.floor((bounds_min - lo) / cell).astype(int)))
    cell_max = np.minimum(dims - 1, np.floor((bounds_max - lo) / cell).astype(int))
    widths = cell_max - cell_min + 1
    counts = widths.prod(axis=1)
    oversized = np.flatnonzero(counts > 512)
    counts[oversized] = 0
    tri_ids = np.repeat(np.arange(len(tri), dtype=np.int32), counts)
    offsets = np.arange(len(tri_ids)) - np.repeat(np.cumsum(counts) - counts, counts)
    x_width = np.repeat(widths[:, 0], counts)
    y_width = np.repeat(widths[:, 1], counts)
    x = np.repeat(cell_min[:, 0], counts) + offsets % x_width
    y = np.repeat(cell_min[:, 1], counts) + (offsets // x_width) % y_width
    z = np.repeat(cell_min[:, 2], counts) + offsets // (x_width * y_width)
    ny, nz = int(dims[1]), int(dims[2])
    keys = (x * ny + y) * nz + z
    order = np.argsort(keys)
    sorted_keys = keys[order]
    starts = np.r_[0, np.flatnonzero(np.diff(sorted_keys)) + 1] if len(order) else []
    buckets = {int(sorted_keys[start]): tri_ids[order[start:end]]
               for start, end in zip(starts, np.r_[starts[1:], len(order)])}
    return {"lo": lo, "hi": hi, "span": span, "cell": cell, "dims": dims,
            "buckets": buckets, "oversized": oversized}


def _ray_box(origin: np.ndarray, direction: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> tuple[float, float] | None:
    near, far = 0.0, math.inf
    for axis in range(3):
        if abs(direction[axis]) < 1e-15:
            if origin[axis] < lo[axis] or origin[axis] > hi[axis]:
                return None
            continue
        a = (lo[axis] - origin[axis]) / direction[axis]
        b = (hi[axis] - origin[axis]) / direction[axis]
        near = max(near, min(a, b))
        far = min(far, max(a, b))
        if far < near:
            return None
    return near, far


def _ray_triangles(origin: np.ndarray, direction: np.ndarray, tri: np.ndarray) -> tuple[float, int]:
    p0 = tri[:, 0]
    e1 = tri[:, 1] - p0
    e2 = tri[:, 2] - p0
    h = np.cross(np.broadcast_to(direction, e2.shape), e2)
    det = np.einsum("ij,ij->i", e1, h)
    valid = np.abs(det) > 1e-12
    inv_det = 1 / np.where(valid, det, 1)
    s = origin - p0
    u = inv_det * np.einsum("ij,ij->i", s, h)
    q = np.cross(s, e1)
    v = inv_det * np.einsum("j,ij->i", direction, q)
    distance = inv_det * np.einsum("ij,ij->i", e2, q)
    hit = valid & (u >= 0) & (v >= 0) & (u + v <= 1) & (distance > 1e-6)
    if not np.any(hit):
        return math.inf, -1
    k = int(np.argmin(np.where(hit, distance, math.inf)))
    return float(distance[k]), k


def thickness(tri: np.ndarray, n: np.ndarray, idx: np.ndarray, offset: float) -> np.ndarray:
    """Distance from sampled face centroids along inward normals to the next mesh face."""
    return thickness_hits(tri, n, idx, offset)[0]


def thickness_hits(tri: np.ndarray, n: np.ndarray, idx: np.ndarray, offset: float,
                   dirs: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """thickness() and the face each ray hits (-1 = none): the opposite skin of the wall. dirs: other ray directions
    (one per face of idx) instead of the inward normal."""
    if not len(idx):
        return np.empty(0), np.empty(0, int)
    grid = _triangle_grid(tri)
    lo, hi, cell, dims = grid["lo"], grid["hi"], grid["cell"], grid["dims"]
    out = np.full(len(idx), np.nan)
    opp = np.full(len(idx), -1)
    for out_i, face_i in enumerate(idx):
        origin = tri[face_i].mean(axis=0) - n[face_i] * offset
        direction = -n[face_i] if dirs is None else dirs[out_i]
        interval = _ray_box(origin, direction, lo, hi)
        if interval is None:
            continue
        current, exit_t = interval
        current += max(cell * 1e-10, 1e-12)
        position = origin + direction * current
        cell_pos = np.floor((position - lo) / cell).astype(int)
        cell_pos = np.minimum(np.maximum(cell_pos, 0), dims - 1)
        ray_step = np.sign(direction).astype(int)
        next_boundary = lo + (cell_pos + (ray_step > 0)) * cell
        t_max = np.divide(next_boundary - origin, direction,
                          out=np.full(3, math.inf), where=np.abs(direction) > 1e-15)
        t_delta = np.divide(cell, np.abs(direction),
                            out=np.full(3, math.inf), where=np.abs(direction) > 1e-15)
        best, best_face = math.inf, -1
        seen = set()
        oversized = grid["oversized"]
        if len(oversized):
            best, k = _ray_triangles(origin, direction, tri[oversized])
            best_face = int(oversized[k]) if k >= 0 else -1
            seen.update(oversized.tolist())
        while np.all((cell_pos >= 0) & (cell_pos < dims)) and current <= exit_t and current < best:
            key = (cell_pos[0] * dims[1] + cell_pos[1]) * dims[2] + cell_pos[2]
            faces = grid["buckets"].get(int(key))
            if faces is not None:
                new_faces = [int(face) for face in faces if int(face) not in seen]
                if new_faces:
                    seen.update(new_faces)
                    d, k = _ray_triangles(origin, direction, tri[new_faces])
                    if d < best:
                        best, best_face = d, new_faces[k]
            axis = int(np.argmin(t_max))
            current = t_max[axis]
            if current >= best:
                break
            cell_pos[axis] += ray_step[axis]
            t_max[axis] += t_delta[axis]
        if math.isfinite(best):
            out[out_i] = best + offset
            opp[out_i] = best_face
    return out, opp


def _machine(part_type: str, force_t: float) -> dict:
    process = master_data.parameters(part_type).get("trial_machine_process")
    ms = [m for m in costing_setup.tables()["machines"] if m["process"] == process]
    fits = sorted((m for m in ms if (m["tonnage_t"] or 0) >= force_t), key=lambda m: m["tonnage_t"])
    if fits:
        return {"machine_id": fits[0]["machine_id"], "name": fits[0]["name"], "tonnage_t": fits[0]["tonnage_t"],
                "process": process, "is_example": fits[0]["is_example"]}
    return {"machine_id": None, "process": process,
            "biggest_t": max((m["tonnage_t"] or 0 for m in ms), default=0)}


def run(vertices, triangles, part_type: str, facts: dict, projected_area_mm2: dict,
        concept_result: dict | None = None) -> dict:
    rules = _rules(part_type)
    c = dict(concept_result) if concept_result is not None else concept.analyze(vertices, triangles, part_type, projected_area_mm2)
    p = c["rules"]
    v = np.asarray(vertices, float)
    tri = v[np.asarray(triangles, int)]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    twice = np.linalg.norm(cross, axis=1)
    area = twice / 2
    n = cross / np.where(twice > 0, twice, 1)[:, None]
    ax = concept.AXES.index(c["opening_axis"])
    draft = np.degrees(np.arcsin(np.clip(np.abs(n[:, ax]), 0, 1)))
    step = max(1, math.ceil(len(tri) / p["undercut_max_faces"]))
    idx = np.arange(0, len(tri), step)
    th = np.full(len(tri), np.nan)
    th[idx] = thickness(tri, n, idx, p["undercut_offset_mm"])
    ok = ~np.isnan(th)
    meas = th[ok]
    w_area = area[ok]

    def pct(q):        # area-weighted percentile: many small faces (rims, fillets) must not outweigh the walls
        if not len(meas):
            return 0.0
        o = np.argsort(meas)
        cum = np.cumsum(w_area[o]) / max(w_area.sum(), 1e-12)
        return float(meas[o][min(np.searchsorted(cum, q / 100), len(meas) - 1)])
    wall = facts.get("wall_mm") or pct(50)
    env = sample_env(part_type) | {k: 0.0 for k in SIM_VARS}
    env |= {k: float(x) for k, x in facts.items() if k in SIM_VARS}
    env |= {"wall_mm": wall, "max_wall_mm": pct(95) if len(meas) else wall,
            "min_wall_mm": pct(5) if len(meas) else wall,
            "flow_length_mm": facts["part_l"] + facts["part_h"],
            "shot_weight_g": facts["part_weight_g"] * facts["cavities"],
            "inserts_per_shot": facts.get("inserts", 0) * facts["cavities"],
            "undercut_area_cm2": c["undercut_area_cm2"]}
    steps = []
    for r in rules:
        try:
            env[r["name"]] = float(formula.evaluate(r["formula"], env))
        except (ArithmeticError, ValueError) as exc:
            raise ValueError(f"Simulation rule '{r['name']}' ({r['formula']}): {exc}") from None
        steps.append({"name": r["name"], "label": r["label"], "formula": r["formula"], "unit": r["unit"],
                      "value": env[r["name"]], "is_example": r["is_example"]})
    low = draft < env["min_draft_deg"]
    thin = th < env["thin_ratio"] * wall
    thick = th > env["sink_ratio"] * wall
    undercut = c.pop("_mask")
    # thickness is measured on every step-th face only, so its areas are scaled back up
    maps = {"draft_low_cm2": float(area[low].sum()) / 100, "thin_cm2": float(area[thin].sum()) * step / 100,
            "sink_risk_cm2": float(area[thick].sum()) * step / 100,
            "undercut_cm2": c["undercut_area_cm2"], "surface_cm2": float(area.sum()) / 100}
    machine = _machine(part_type, env["clamp_t"])
    corr = []
    if maps["draft_low_cm2"] > 0:
        corr.append(f"Add draft of at least {env['min_draft_deg']:g}° on {maps['draft_low_cm2']:.1f} cm² of walls along the opening direction {c['opening_axis'].upper()}.")
    if maps["sink_risk_cm2"] > 0:
        corr.append(f"Core out thick sections: {maps['sink_risk_cm2']:.1f} cm² is thicker than {env['sink_ratio']:g} × the {wall:.2f} mm wall (sink / porosity risk).")
    if maps["thin_cm2"] > 0:
        corr.append(f"Check thin walls: {maps['thin_cm2']:.1f} cm² is thinner than {env['thin_ratio']:g} × the {wall:.2f} mm wall (short-shot risk).")
    if c["slides"] or c["lifters"]:
        corr.append(f"Undercuts ({maps['undercut_cm2']:.1f} cm²) need {c['slides']} slide(s) / {c['lifters']} lifter(s), or a design change.")
    if not machine["machine_id"]:
        corr.append(f"No '{machine['process']}' machine takes {env['clamp_t']:.0f} t (largest {machine['biggest_t']:g} t): fewer cavities or a larger machine.")
    plan = master_data.parameters(part_type).get("cycle_time_s")
    if plan and env["cycle_s"] > plan:
        corr.append(f"Estimated cycle {env['cycle_s']:.1f} s is longer than the planned {plan:g} s (Parameters → cycle_time_s).")
    return {"part_type": part_type, "opening_axis": c["opening_axis"], "wall_mm": wall, "steps": steps, "results": env,
            "maps": maps, "machine": machine, "concept": c, "corrections": corr, "sampled": step > 1,
            "is_example": any(s["is_example"] for s in steps),
            "_faces": {"tri": tri, "thickness": th, "draft": draft, "low": low, "thick": thick, "thin": thin, "undercut": undercut}}


def pictures(res: dict) -> list[tuple[str, bytes]]:
    """Coloured maps (PNG): wall thickness, draft, and risk areas (sink / thin / undercut)."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    f = res["_faces"]
    tri = f["tri"]
    out = []
    risk = np.full((len(tri), 4), (0.82, 0.85, 0.88, 1.0))
    risk[f["thin"]] = (0.15, 0.45, 0.85, 1)
    risk[f["low"]] = (0.95, 0.65, 0.1, 1)
    risk[f["thick"]] = (0.85, 0.15, 0.15, 1)
    risk[f["undercut"]] = (0.55, 0.2, 0.7, 1)
    th = f["thickness"]
    cmap = plt.get_cmap("viridis")
    lo, hi = (np.nanmin(th), np.nanmax(th)) if np.isfinite(th).any() else (0, 1)
    wall = np.where(np.isnan(th), 0, (th - lo) / max(hi - lo, 1e-9))
    wall_c = cmap(wall)
    wall_c[np.isnan(th)] = (0.82, 0.85, 0.88, 1)
    draft_c = plt.get_cmap("RdYlGn")(np.clip(f["draft"] / max(3 * res["results"]["min_draft_deg"], 1e-9), 0, 1))
    for title, col in ((f"Wall thickness {lo:.2f}–{hi:.2f} mm (yellow = thick)", wall_c),
                       (f"Draft to {res['opening_axis'].upper()} (red = below {res['results']['min_draft_deg']:g}°)", draft_c),
                       ("Risk: red sink, blue thin, orange low draft, purple undercut", risk)):
        fig = plt.figure(figsize=(4.2, 3.4), dpi=110)
        a = fig.add_subplot(111, projection="3d")
        a.add_collection3d(Poly3DCollection(tri, facecolors=col, edgecolor="none"))
        mn, mx = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
        r = (mx - mn).max() / 2
        mid = (mx + mn) / 2
        a.set_xlim(mid[0] - r, mid[0] + r); a.set_ylim(mid[1] - r, mid[1] + r); a.set_zlim(mid[2] - r, mid[2] + r)
        a.set_axis_off()
        a.set_title(title, fontsize=7)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        out.append((title, buf.getvalue()))
    return out


def public(res: dict) -> dict:
    """The result without the per-face arrays (for the API)."""
    out = {k: v for k, v in res.items() if k != "_faces"}
    out["results"] = {k: v for k, v in res["results"].items() if k in SIM_VARS or k in {s["name"] for s in res["steps"]}}
    return out
