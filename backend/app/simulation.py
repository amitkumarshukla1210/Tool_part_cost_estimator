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
    "max_wall_mm": "Thickest wall: 95th percentile of the measured thickness (mm)",
    "min_wall_mm": "Thinnest wall: 5th percentile of the measured thickness (mm)",
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


def thickness(tri: np.ndarray, n: np.ndarray, idx: np.ndarray, offset: float) -> np.ndarray:
    """Distance from each face centroid (idx) along its inward normal to the next face of the part (Möller–Trumbore)."""
    p0, e1, e2 = tri[:, 0], tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    out = np.full(len(idx), np.nan)
    for s in range(0, len(idx), 128):
        k = idx[s:s + 128]
        o = tri[k].mean(axis=1) - n[k] * offset
        d = -n[k]
        h = np.cross(d[:, None, :], e2[None])
        a = (e1[None] * h).sum(-1)
        ok = np.abs(a) > 1e-12
        f = 1 / np.where(ok, a, 1)
        sv = o[:, None, :] - p0[None]
        u = f * (sv * h).sum(-1)
        q = np.cross(sv, e1[None])
        v = f * (d[:, None, :] * q).sum(-1)
        t = f * (e2[None] * q).sum(-1)
        good = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-6)
        t = np.where(good, t, np.inf).min(axis=1)
        out[s:s + 128] = np.where(np.isfinite(t), t + offset, np.nan)
    return out


def local_thickness(tri: np.ndarray, area: np.ndarray, n: np.ndarray, idx: np.ndarray, ray: np.ndarray, offset: float, samples: int = 20000) -> np.ndarray:
    """Thickness at each face: the ray length, cut down to the section the midpoint really sits in.

    A ray along a rim or boss end runs the whole length of the wall (30 mm for a 2.5 mm wall). The point halfway along the ray is
    then close to the wall's side faces, so local thickness = min(ray, 2 × distance from the midpoint to the nearest surface),
    the diameter of the sphere that fits at the midpoint. Surface distance is measured to evenly spread sample points.
    """
    rng = np.random.default_rng(0)
    pick = rng.choice(len(tri), size=samples, p=area / area.sum())
    r1, r2 = rng.random((2, samples))
    flip = r1 + r2 > 1
    r1, r2 = np.where(flip, 1 - r1, r1), np.where(flip, 1 - r2, r2)
    t = tri[pick]
    pts = t[:, 0] + r1[:, None] * (t[:, 1] - t[:, 0]) + r2[:, None] * (t[:, 2] - t[:, 0])
    out = ray.copy()
    ok = np.where(~np.isnan(ray))[0]
    for s0 in range(0, len(ok), 256):
        k = ok[s0:s0 + 256]
        c = tri[idx[k]].mean(axis=1)
        mid = c - n[idx[k]] * (offset + ray[k] / 2)[:, None]
        d2 = ((mid[:, None, :] - pts[None]) ** 2).sum(-1).min(axis=1)
        out[k] = np.minimum(ray[k], 2 * np.sqrt(d2))
    return out


def _machine(part_type: str, force_t: float) -> dict:
    process = master_data.parameters(part_type).get("trial_machine_process")
    ms = [m for m in costing_setup.tables()["machines"] if m["process"] == process]
    fits = sorted((m for m in ms if (m["tonnage_t"] or 0) >= force_t), key=lambda m: m["tonnage_t"])
    if fits:
        return {"machine_id": fits[0]["machine_id"], "name": fits[0]["name"], "tonnage_t": fits[0]["tonnage_t"],
                "process": process, "is_example": fits[0]["is_example"]}
    return {"machine_id": None, "process": process,
            "biggest_t": max((m["tonnage_t"] or 0 for m in ms), default=0)}


def run(vertices, triangles, part_type: str, facts: dict, projected_area_mm2: dict) -> dict:
    rules = _rules(part_type)
    c = concept.analyze(vertices, triangles, part_type, projected_area_mm2)
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
    th[idx] = local_thickness(tri, area, n, idx, thickness(tri, n, idx, p["undercut_offset_mm"]), p["undercut_offset_mm"])
    meas = th[~np.isnan(th)]
    wall = facts.get("wall_mm") or (float(np.median(meas)) if len(meas) else 0)
    env = sample_env(part_type) | {k: 0.0 for k in SIM_VARS}
    env |= {k: float(x) for k, x in facts.items() if k in SIM_VARS}
    env |= {"wall_mm": wall, "max_wall_mm": float(np.percentile(meas, 95)) if len(meas) else wall,
            "min_wall_mm": float(np.percentile(meas, 5)) if len(meas) else wall,
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
    floor = env.get("report_min_area_cm2", 0.1)           # smaller areas are mesh noise, not a correction (Simulation rules)
    if maps["draft_low_cm2"] > floor:
        corr.append(f"Add draft of at least {env['min_draft_deg']:g}° on {maps['draft_low_cm2']:.1f} cm² of walls along the opening direction {c['opening_axis'].upper()}.")
    if maps["sink_risk_cm2"] > floor:
        corr.append(f"Core out thick sections: {maps['sink_risk_cm2']:.1f} cm² is thicker than {env['sink_ratio']:g} × the {wall:.2f} mm wall (sink / porosity risk).")
    if maps["thin_cm2"] > floor:
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
