"""Mould / die concept v1 (roadmap stage 5): opening direction, undercuts -> slides / lifters, and rule-based proposals.

    mesh + opening axis -> faces that are shadowed along the opening direction (ray casting) = undercut faces
    undercut faces      -> connected regions; outward-facing ones are slides, inward-facing ones are lifters (plastic)
    part facts          -> gate / runner / cooling / ejection / insert proposals from Mould & die database -> Concept rules

Thresholds are Sizing rules rows (undercut_*), proposals are Concept rules rows: nothing is fixed in the code.
Everything here is a PROPOSAL for the engineer to check (ray casting on the tessellation, not a tool design).
"""

from __future__ import annotations

import numpy as np

from . import formula, mould_db

AXES = ("x", "y", "z")
PARAMS = ("undercut_vertical_cos", "undercut_offset_mm", "undercut_min_area_mm2", "undercut_max_faces")
TOPICS = mould_db.TOPICS
CONCEPT_VARS = {
    "part_weight_g": "Net weight of one part (g)", "wall_mm": "Most common wall (mm), 0 if unknown",
    "part_l": "Part length across the parting plane (mm)", "part_w": "Part width across the parting plane (mm)",
    "part_h": "Part height along the opening direction (mm)", "projected_area_cm2": "Shadow area along the opening direction (cm²)",
    "volume_cm3": "Part volume (cm³)", "cavities": "Cavities per tool", "slides": "Slides per cavity (detected or typed)",
    "lifters": "Lifters per cavity (detected or typed)", "undercut_area_cm2": "Undercut face area (cm²)",
    "inserts": "Moulded-in inserts per part",
}


def _rules(part_type: str) -> dict:
    rules = mould_db.sizing_rules(part_type)
    missing = [k for k in PARAMS if k not in rules]
    if missing:
        raise ValueError(f"Mould & die database → Sizing rules has no {', '.join(missing)} for '{part_type}'.")
    return {k: rules[k]["value"] for k in PARAMS} | {"is_example": any(rules[k]["is_example"] for k in PARAMS)}


def _shadowed(tri: np.ndarray, axis: int, cos_min: float, offset: float, max_faces: int):
    """Per triangle: True when a ray from the face along its own side of the opening direction hits the part."""
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    cross = np.cross(b - a, c - a)
    twice = np.linalg.norm(cross, axis=1)
    area = twice / 2
    n = cross / np.where(twice > 0, twice, 1)[:, None]
    cand = np.where((np.abs(n[:, axis]) > cos_min) & (area > 0))[0]
    step = max(1, int(np.ceil(len(cand) / max_faces)))
    cand = cand[::step]
    u, v = [i for i in range(3) if i != axis]
    # 2D barycentric set-up of every triangle in the plane normal to the axis
    p0, p1, p2 = tri[:, 0], tri[:, 1], tri[:, 2]
    d = (p1[:, v] - p2[:, v]) * (p0[:, u] - p2[:, u]) + (p2[:, u] - p1[:, u]) * (p0[:, v] - p2[:, v])
    ok = np.abs(d) > 1e-12
    d = np.where(ok, d, 1.0)
    hit = np.zeros(len(tri), bool)
    for s in range(0, len(cand), 128):
        idx = cand[s:s + 128]
        cen = tri[idx].mean(axis=1)
        sign = np.sign(n[idx, axis])
        du, dv = cen[:, u, None] - p2[None, :, u], cen[:, v, None] - p2[None, :, v]
        l1 = ((p1[None, :, v] - p2[None, :, v]) * du + (p2[None, :, u] - p1[None, :, u]) * dv) / d[None]
        l2 = ((p2[None, :, v] - p0[None, :, v]) * du + (p0[None, :, u] - p2[None, :, u]) * dv) / d[None]
        l3 = 1 - l1 - l2
        inside = (l1 > 1e-9) & (l2 > 1e-9) & (l3 > 1e-9) & ok[None]
        depth = l1 * p0[None, :, axis] + l2 * p1[None, :, axis] + l3 * p2[None, :, axis]
        start = (cen[:, axis] + sign * offset)[:, None]
        hit[idx] = (inside & (sign[:, None] * (depth - start) > 0)).any(axis=1)
    return hit, area, n, step


def _regions(tri: np.ndarray, flagged: np.ndarray) -> list[np.ndarray]:
    """Connected groups of flagged triangles (shared vertices, rounded to 0.01 mm)."""
    parent: dict = {}

    def find(k):
        while parent.setdefault(k, k) != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    keys = np.round(tri[flagged] * 100).astype(np.int64)
    for row in keys:
        ks = [tuple(p) for p in row]
        for k in ks[1:]:
            parent[find(k)] = find(ks[0])
    groups: dict = {}
    for i, row in zip(flagged, keys):
        groups.setdefault(find(tuple(row[0])), []).append(i)
    return [np.array(g) for g in groups.values()]


def analyze(vertices, triangles, part_type: str, projected_area_mm2: dict) -> dict:
    """Opening-direction ranking, undercut regions and the slide / lifter proposal for a tessellated part."""
    if part_type not in ("plastic", "die_casting"):
        raise ValueError("Concept v1 covers plastic moulds and die-casting dies.")
    p = _rules(part_type)
    v = np.asarray(vertices, float)
    tri = v[np.asarray(triangles, int)]
    centre = (v.min(axis=0) + v.max(axis=0)) / 2
    ranking = []
    for ax, name in enumerate(AXES):
        hit, area, n, step = _shadowed(tri, ax, p["undercut_vertical_cos"], p["undercut_offset_mm"], int(p["undercut_max_faces"]))
        ranking.append({"axis": name, "undercut_area_mm2": float(area[hit].sum() * step), "hit": hit, "area": area, "n": n,
                        "projected_area_mm2": projected_area_mm2[name], "step": step})
    ranking.sort(key=lambda r: (round(r["undercut_area_mm2"], 3), -r["projected_area_mm2"]))
    best = ranking[0]
    ax = AXES.index(best["axis"])
    regions = []
    for idx in _regions(tri, np.where(best["hit"])[0]) if best["hit"].any() else []:
        a = best["area"][idx]
        if a.sum() < p["undercut_min_area_mm2"]:
            continue
        nrm = (best["n"][idx] * a[:, None]).sum(axis=0) / a.sum()
        cen = (tri[idx].mean(axis=1) * a[:, None]).sum(axis=0) / a.sum()
        lateral = [i for i in range(3) if i != ax]
        outward = float(np.dot(nrm[lateral], (cen - centre)[lateral])) >= 0
        kind = "slide" if outward or part_type != "plastic" else "lifter"
        regions.append({"kind": kind, "area_mm2": float(a.sum() * 1.0), "centre_mm": [round(float(x), 2) for x in cen],
                        "reason": ("faces outward from the part, shadowed along the opening direction: side action (slide)"
                                   if kind == "slide" and outward else
                                   "faces inward (inside the part) and is shadowed: lifter" if kind == "lifter" else
                                   "inward undercut in a die: a core slide is needed (no lifters in dies)")})
    regions.sort(key=lambda r: -r["area_mm2"])
    return {"part_type": part_type, "opening_axis": best["axis"],
            "ranking": [{k: r[k] for k in ("axis", "undercut_area_mm2", "projected_area_mm2")} for r in ranking],
            "regions": regions, "slides": sum(r["kind"] == "slide" for r in regions),
            "lifters": sum(r["kind"] == "lifter" for r in regions),
            "undercut_area_cm2": best["undercut_area_mm2"] / 100, "rules": p, "triangles": len(tri),
            "sampled": best["step"] > 1, "_mask": best["hit"]}


def proposals(part_type: str, facts: dict) -> list[dict]:
    """First Concept rule (by step) of each topic whose condition is true for the part."""
    env = {k: 0.0 for k in CONCEPT_VARS} | {k: float(v) for k, v in facts.items() if k in CONCEPT_VARS}
    rows = [r for r in mould_db.tables()["concept_rules"] if r["part_type"] == part_type]
    out = []
    for topic in TOPICS:
        for r in sorted((r for r in rows if r["topic"] == topic), key=lambda r: r["step"]):
            if formula.evaluate(r["condition"], env):
                out.append({"topic": topic, "proposal": r["proposal"], "rule": f"{topic} step {r['step']:g}: {r['condition']}",
                            "is_example": r["is_example"]})
                break
    return out
