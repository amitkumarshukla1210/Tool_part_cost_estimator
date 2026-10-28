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


def _projected_grid(tri: np.ndarray, u: int, v: int) -> dict:
    projected = tri[:, :, [u, v]]
    bounds_min = projected.min(axis=1)
    bounds_max = projected.max(axis=1)
    lo, hi = bounds_min.min(axis=0), bounds_max.max(axis=0)
    span = hi - lo
    if not np.any(span > 0):
        return {"lo": lo, "span": span, "cell": 1.0, "nx": 1, "ny": 1, "buckets": {}, "oversized": []}
    cell = float(max(span) / min(512, max(32, int(np.sqrt(len(tri) / 8)))))
    nx, ny = max(1, int(np.ceil(span[0] / cell))), max(1, int(np.ceil(span[1] / cell)))
    cell_min = np.minimum((nx - 1, ny - 1), np.maximum(0, np.floor((bounds_min - lo) / cell).astype(int)))
    cell_max = np.minimum((nx - 1, ny - 1), np.floor((bounds_max - lo) / cell).astype(int))
    widths = cell_max - cell_min + 1
    counts = widths.prod(axis=1)
    oversized = np.flatnonzero(counts > 256)
    counts[oversized] = 0
    tri_ids = np.repeat(np.arange(len(tri), dtype=np.int32), counts)
    offsets = np.arange(len(tri_ids)) - np.repeat(np.cumsum(counts) - counts, counts)
    x_width = np.repeat(widths[:, 0], counts)
    x = np.repeat(cell_min[:, 0], counts) + offsets % x_width
    y = np.repeat(cell_min[:, 1], counts) + offsets // x_width
    keys = x * ny + y
    order = np.argsort(keys)
    sorted_keys = keys[order]
    starts = np.r_[0, np.flatnonzero(np.diff(sorted_keys)) + 1] if len(order) else []
    buckets = {int(sorted_keys[start]): tri_ids[order[start:end]]
               for start, end in zip(starts, np.r_[starts[1:], len(order)])}
    return {"lo": lo, "span": span, "cell": cell, "nx": nx, "ny": ny, "buckets": buckets, "oversized": oversized}


def _projected_candidates(grid: dict, point: np.ndarray) -> list[int]:
    lo, span, cell, nx, ny = grid["lo"], grid["span"], grid["cell"], grid["nx"], grid["ny"]
    if np.any(point < lo) or np.any(point > lo + span):
        return grid["oversized"]
    x, y = np.floor((point - lo) / cell).astype(int)
    x, y = min(nx - 1, x), min(ny - 1, y)
    bucket = np.asarray(grid["buckets"].get(x * ny + y, []), dtype=np.int32)
    return np.concatenate((bucket, np.asarray(grid["oversized"], dtype=np.int32)))


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
    p0, p1, p2 = tri[:, 0], tri[:, 1], tri[:, 2]
    grid = _projected_grid(tri, u, v)
    hit = np.zeros(len(tri), bool)
    for idx in cand:
        cen = tri[idx].mean(axis=0)
        sign = np.sign(n[idx, axis])
        overlaps = _projected_candidates(grid, cen[[u, v]])
        if not len(overlaps):
            continue
        q0, q1, q2 = p0[overlaps], p1[overlaps], p2[overlaps]
        d = ((q1[:, v] - q2[:, v]) * (q0[:, u] - q2[:, u])
             + (q2[:, u] - q1[:, u]) * (q0[:, v] - q2[:, v]))
        ok = np.abs(d) > 1e-12
        d = np.where(ok, d, 1.0)
        du, dv = cen[u] - q2[:, u], cen[v] - q2[:, v]
        l1 = ((q1[:, v] - q2[:, v]) * du + (q2[:, u] - q1[:, u]) * dv) / d
        l2 = ((q2[:, v] - q0[:, v]) * du + (q0[:, u] - q2[:, u]) * dv) / d
        l3 = 1 - l1 - l2
        inside = (l1 > 1e-9) & (l2 > 1e-9) & (l3 > 1e-9) & ok
        depth = l1 * q0[:, axis] + l2 * q1[:, axis] + l3 * q2[:, axis]
        start = cen[axis] + sign * offset
        hit[idx] = bool(np.any(inside & (sign * (depth - start) > 0)))
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
    if part_type not in ("plastic", "die_casting", "eps", "blow", "foundry"):
        raise ValueError("The concept analysis covers moulds, dies and patterns (plastic, die casting, EPS, blow moulding, foundry).")
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
