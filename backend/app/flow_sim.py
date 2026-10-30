"""Flow simulation (roadmap stage 39): filling, pressure, temperature, cooling / solidification and the defects they cause, for
plastic injection moulding, die casting, foundry (gravity sand casting), EPS moulding and PET stretch blow moulding.

Method: a 2.5D "dual-domain" solver on the surface mesh of the 3D model (the way Moldflow Dual Domain works, much simpler):
    mesh      the triangles are welded into a graph (neighbour triangles) and each wall's two skins are linked through the
              thickness (ray from every sampled face to the opposite face; simulation.thickness_hits); h = local wall thickness
    gate      typed by you (a point) or found: the gate that fills the part with the least flow resistance (Dijkstra from up to
              16 candidate gates); more gates are added where the flow resistance is highest
    filling   flow resistance of a path = Σ length / (h / h_ref)^k  (Hele-Shaw: thin walls fill slowly; plastic k = 1 + 1/n of the
              power-law melt, metal k small). Faces fill in the order of their resistance; fill time = filled volume share × the
              fill time of Flow rules (plastic, EPS: a formula; die casting: the NADCA fill-time formula; foundry: from the bottom
              upwards, by height, pour time = a formula of the casting weight)
    pressure  Hele-Shaw pressure drop along the flow path: dp = 12 · η(γ̇) · v · L / h²; η(γ̇) = η_ref · (γ̇ / γ̇_ref)^(n-1);
              γ̇ = 6 v / h; v = front speed from the fill time map → injection pressure, pressure map, clamp force from the
              pressure on the projected area (or the hold / intensification pressure, whichever is higher)
    thermal   plastic: cooling time t = h² / (π² α) · ln(4/π · (Tm − Tw) / (Te − Tw)) and freeze-off time (Te → no-flow temperature);
              metal / EPS: solidification time t = B · (h / 2)²  (Chvorinov, modulus of a wall = h / 2); flow-front temperature
              T = Tm − (Tm − T_noflow) · f · t_arrival / t_freeze
    defects   weld lines / cold shuts: flow fronts from different directions meet (angle > weld_angle_deg) — weak or visible where
              the front is cooler than the melt by weld_drop_c (metal: near the no-flow temperature → cold shut)
              air traps (plastic) / gas porosity, blow holes (castings): last-to-fill faces (no neighbour fills later); foundry also
              downward-facing pockets where gas collects under the metal
              short shot / hesitation: a thin section is crossed for longer than its freeze-off time, or the injection pressure is
              above the machine's
              sink marks / voids (plastic), shrinkage porosity (castings): hot spots (cooling / solidification time above
              hot_spot_ratio × typical) that cannot be fed: every path from the gate solidifies earlier (feed_tolerance)
              stress areas: sharp inside corners (adjacent faces turn by more than sharp_corner_deg) and large differences of
              cooling time between neighbours (residual stress, warpage)
    machine   clamp force, injection / intensification pressure, shot volume and weight → the smallest machine of Parameters →
              trial_machine_process that takes it, and the production machine of stage 33 when one is saved

Inputs: Mould & die database → Flow materials (viscosity, diffusivity, no-flow / solidus / liquidus temperature, Chvorinov and
NADCA constants …), Flow rules (formulas per part type, evaluated in order), Process windows (melt, mould, ejection temperature)
and the 3D model. All seeded rows are EXAMPLE values. A physics estimate for design decisions, not a certified Moldflow / MAGMA
result: for the tool release of a critical part attach the report of such a program to the run.
"""

from __future__ import annotations

import heapq
import math

import numpy as np
from scipy import sparse
from scipy.sparse import csgraph

from . import concept, formula, master_data, mould_db, simulation

PART_TYPES = ("plastic", "die_casting", "foundry", "eps", "blow")
EXAMPLE = "EXAMPLE - typical value: replace with your material data sheet, supplier data or trial results"
MATERIAL_FIELDS = ("family", "viscosity_pa_s", "shear_index_n", "ref_shear_1_s", "diffusivity_mm2_s", "no_flow_c", "solidus_c",
                   "liquidus_c", "chvorinov_s_mm2", "nadca_k_s_mm", "nadca_z_c_pct", "shrinkage_pct", "modulus_mpa", "max_shear_1_s",
                   "bead_mm", "stretch_max")
# material: family, η (Pa·s at the melt temperature and γ̇_ref), n, γ̇_ref (1/s), α (mm²/s), no-flow / min. flow °C, solidus °C, liquidus °C,
# Chvorinov B (s/mm²), NADCA K (s/mm), NADCA Z (°C per % solid), shrinkage %, E (MPa), max shear rate (1/s), bead Ø (mm), max stretch ratio
SEED_MATERIALS = [
    ("PP (polypropylene)", "plastic", 150, 0.30, 1000, 0.085, 140, 0, 0, 0, 0, 0, 1.6, 1300, 100000, 0, 0),
    ("PP copolymer (impact)", "plastic", 170, 0.32, 1000, 0.085, 140, 0, 0, 0, 0, 0, 1.5, 1100, 100000, 0, 0),
    ("PP talc filled 20 %", "plastic", 200, 0.32, 1000, 0.10, 145, 0, 0, 0, 0, 0, 1.1, 2200, 100000, 0, 0),
    ("ABS", "plastic", 250, 0.30, 1000, 0.09, 120, 0, 0, 0, 0, 0, 0.5, 2300, 50000, 0, 0),
    ("ABS flame retardant V0", "plastic", 280, 0.30, 1000, 0.09, 120, 0, 0, 0, 0, 0, 0.5, 2400, 40000, 0, 0),
    ("PC (polycarbonate)", "plastic", 400, 0.55, 1000, 0.10, 170, 0, 0, 0, 0, 0, 0.6, 2350, 40000, 0, 0),
    ("PC/ABS", "plastic", 300, 0.40, 1000, 0.095, 140, 0, 0, 0, 0, 0, 0.6, 2300, 40000, 0, 0),
    ("PA6", "plastic", 120, 0.45, 1000, 0.10, 200, 0, 0, 0, 0, 0, 1.2, 2800, 60000, 0, 0),
    ("PA66 GF30", "plastic", 160, 0.40, 1000, 0.11, 230, 0, 0, 0, 0, 0, 0.5, 9000, 60000, 0, 0),
    ("PA66 GF30 heat stabilised", "plastic", 160, 0.40, 1000, 0.11, 230, 0, 0, 0, 0, 0, 0.5, 9000, 60000, 0, 0),
    ("PBT GF30", "plastic", 180, 0.40, 1000, 0.11, 200, 0, 0, 0, 0, 0, 0.6, 9500, 50000, 0, 0),
    ("POM (acetal)", "plastic", 200, 0.40, 1000, 0.09, 150, 0, 0, 0, 0, 0, 2.0, 2800, 40000, 0, 0),
    ("PET preform grade", "plastic", 250, 0.60, 1000, 0.10, 220, 0, 0, 0, 0, 0, 0.4, 2500, 50000, 0, 0),
    ("Aluminium ADC12 / A383", "metal", 0, 0, 0, 0, 570, 515, 580, 0.9, 0.0346, 4.8, 0.6, 71000, 0, 0, 0),
    ("Aluminium A380", "metal", 0, 0, 0, 0, 575, 540, 595, 0.9, 0.0346, 4.8, 0.6, 71000, 0, 0, 0),
    ("Aluminium AlSi10Mg (EN AC-43400)", "metal", 0, 0, 0, 0, 585, 555, 595, 0.9, 0.0346, 4.8, 0.6, 71000, 0, 0, 0),
    ("Zinc Zamak 3", "metal", 0, 0, 0, 0, 390, 381, 387, 0.6, 0.0124, 2.5, 0.6, 85000, 0, 0, 0),
    ("Magnesium AZ91D", "metal", 0, 0, 0, 0, 540, 470, 595, 0.7, 0.0252, 3.8, 0.7, 45000, 0, 0, 0),
    ("Grey cast iron FG260", "metal", 0, 0, 0, 0, 1200, 1150, 1200, 2.5, 0, 0, 1.0, 110000, 0, 0, 0),
    ("SG / ductile iron", "metal", 0, 0, 0, 0, 1180, 1120, 1160, 2.5, 0, 0, 1.0, 169000, 0, 0, 0),
    ("Cast steel", "metal", 0, 0, 0, 0, 1510, 1450, 1510, 2.0, 0, 0, 2.0, 200000, 0, 0, 0),
    ("Aluminium LM6 / A356", "metal", 0, 0, 0, 0, 600, 575, 585, 1.8, 0, 0, 1.3, 71000, 0, 0, 0),
    ("Bronze", "metal", 0, 0, 0, 0, 1000, 900, 1000, 2.0, 0, 0, 1.5, 100000, 0, 0, 0),
    ("EPS bead grade S (20 kg/m3)", "eps", 0, 0, 0, 0, 0, 0, 0, 0.07, 0, 0, 0.5, 5, 0, 1.0, 0),
    ("EPS bead grade F, flame retardant (25 kg/m3)", "eps", 0, 0, 0, 0, 0, 0, 0, 0.07, 0, 0, 0.5, 6, 0, 1.0, 0),
    ("PET bottle grade (IV 0.80)", "pet", 0, 0, 0, 0.10, 0, 0, 0, 0, 0, 0, 0.4, 2500, 0, 0, 12),
    ("rPET food grade", "pet", 0, 0, 0, 0.10, 0, 0, 0, 0, 0, 0, 0.4, 2500, 0, 0, 11),
]
# part type, name, formula, unit, meaning (evaluated in order; each may use the ones before)
SEED_RULES = [
    ("plastic", "mesh_size_mm", "max(wall_mm, 2)", "mm", "Mesh size of the solver (triangles are split down to this)"),
    ("plastic", "mesh_faces", "150000", "-", "Most triangles of the solver mesh (the mesh size grows to keep below; more = finer, slower)"),
    ("plastic", "fill_time_s", "max(0.4, 0.5 + 0.12 * sqrt(shot_volume_cm3))", "s", "Injection (fill) time"),
    ("plastic", "pack_pct", "60", "%", "Hold pressure in the cavity, % of the cavity filling pressure"),
    ("plastic", "pack_time_s", "max(1, 1.5 * wall_mm)", "s", "Hold (pack) time"),
    ("plastic", "feed_drop_pct", "20", "%", "Pressure lost in the sprue, runner and gate, % of the cavity pressure"),
    ("plastic", "runner_pct", "8", "%", "Runner volume, % of the parts (cold runner; 0 for a hot runner)"),
    ("plastic", "max_injection_bar", "1800", "bar", "Highest injection pressure of the machine"),
    ("plastic", "thickness_exponent", "2", "-", "k of the flow resistance length / (h / h_ref)^k (Hele-Shaw: flow speed ∝ h² under the same pressure gradient)"),
    ("plastic", "front_cooling_factor", "0.25", "-", "Share of the freeze-off cooling that reaches the flow front (fresh melt keeps it hot)"),
    ("plastic", "weld_angle_deg", "120", "°", "Fronts meeting at more than this angle make a weld line"),
    ("plastic", "weld_drop_c", "15", "°C", "Weld line weak / visible when the front is this much cooler than the melt"),
    ("plastic", "thin_ratio", "0.6", "-", "Thin section = thinner than this × the wall (hesitation check)"),
    ("plastic", "hot_spot_ratio", "1.6", "-", "Hot spot (sink mark / void) = cooling time above this × the typical cooling time"),
    ("plastic", "feed_tolerance", "0.9", "-", "A hot spot is packed when a path from the gate stays molten this long (share of its time)"),
    ("plastic", "max_wall_ratio", "8", "-", "Thickness above this × the wall is taken as this"),
    ("plastic", "min_defect_cm2", "0.2", "cm²", "Defect areas smaller than this are not reported (mesh noise)"),
    ("plastic", "sharp_corner_deg", "60", "°", "Inside corner sharper than this (no radius) = stress concentration"),
    ("plastic", "stress_gradient", "0.5", "-", "Cooling-time difference to a neighbour above this share = residual stress / warpage"),
    ("plastic", "clamp_safety_pct", "10", "%", "Clamp force safety margin"),
    ("plastic", "open_eject_s", "3 + part_h / 100", "s", "Mould open, eject, close"),
    ("die_casting", "mesh_size_mm", "max(wall_mm, 2)", "mm", "Mesh size of the solver (triangles are split down to this)"),
    ("die_casting", "mesh_faces", "150000", "-", "Most triangles of the solver mesh (the mesh size grows to keep below; more = finer, slower)"),
    ("die_casting", "solids_pct", "25", "%", "Solid fraction allowed at the end of filling (NADCA S)"),
    ("die_casting", "fill_time_s", "nadca_k_s_mm * (melt_c - no_flow_c + solids_pct * nadca_z_c_pct) / max(no_flow_c - mould_c, 1) * wall_mm", "s",
     "Fill time, NADCA: K · (Ti − Tf + S·Z) / (Tf − Td) · T"),
    ("die_casting", "intensification_bar", "800", "bar", "Metal pressure in the cavity at intensification"),
    ("die_casting", "overflow_pct", "25", "%", "Overflows, runner and biscuit: added to the shot volume and the projected area"),
    ("die_casting", "thickness_exponent", "0.5", "-", "k of the flow resistance (metal: turbulent, thickness matters little)"),
    ("die_casting", "front_cooling_factor", "0.5", "-", "Share of the cooling to the minimum flow temperature that reaches the front"),
    ("die_casting", "weld_angle_deg", "120", "°", "Fronts meeting at more than this angle make a cold-shut line"),
    ("die_casting", "weld_drop_c", "40", "°C", "Cold shut when the meeting fronts are this close to the minimum flow temperature"),
    ("die_casting", "thin_ratio", "0.5", "-", "Thin section = thinner than this × the wall"),
    ("die_casting", "hot_spot_ratio", "1.6", "-", "Hot spot = solidification time above this × the typical time"),
    ("die_casting", "feed_tolerance", "0.9", "-", "Fed when a path from the gate stays liquid this long (share of the hot spot's time)"),
    ("die_casting", "max_wall_ratio", "8", "-", "Thickness above this × the wall is taken as this"),
    ("die_casting", "min_defect_cm2", "0.1", "cm²", "Defect areas smaller than this are not reported (mesh noise)"),
    ("die_casting", "sharp_corner_deg", "60", "°", "Inside corner sharper than this = stress concentration / hot tear"),
    ("die_casting", "stress_gradient", "0.5", "-", "Solidification-time difference to a neighbour above this share = residual stress"),
    ("die_casting", "clamp_safety_pct", "10", "%", "Clamp force safety margin"),
    ("die_casting", "die_open_s", "6 + part_h / 100", "s", "Die open, extract, close"),
    ("die_casting", "spray_s", "5", "s", "Die spray and blow-off"),
    ("foundry", "mesh_size_mm", "max(wall_mm, 2)", "mm", "Mesh size of the solver (triangles are split down to this)"),
    ("foundry", "mesh_faces", "150000", "-", "Most triangles of the solver mesh (the mesh size grows to keep below; more = finer, slower)"),
    ("foundry", "gating_pct", "30", "%", "Gating and risers, % of the casting weight (poured weight)"),
    ("foundry", "fill_time_s", "2.2 * sqrt(part_weight_g / 1000 * (1 + gating_pct / 100))", "s", "Pouring time, K · √(poured kg)"),
    ("foundry", "thickness_exponent", "0", "-", "Gravity filling from the bottom (thickness does not steer the order)"),
    ("foundry", "front_cooling_factor", "0.5", "-", "Share of the cooling to the minimum flow temperature that reaches the front"),
    ("foundry", "weld_angle_deg", "120", "°", "Fronts meeting at more than this angle make a cold-shut line"),
    ("foundry", "weld_drop_c", "50", "°C", "Cold shut when the meeting fronts are this close to the minimum flow temperature"),
    ("foundry", "thin_ratio", "0.5", "-", "Thin section = thinner than this × the wall (misrun check)"),
    ("foundry", "hot_spot_ratio", "1.5", "-", "Hot spot = solidification time above this × the typical time"),
    ("foundry", "feed_tolerance", "0.95", "-", "Fed when a path from the gate / riser stays liquid this long"),
    ("foundry", "riser_modulus_factor", "1.2", "-", "Riser modulus = this × the modulus of the hot spot it feeds"),
    ("foundry", "max_wall_ratio", "8", "-", "Thickness above this × the wall is taken as this"),
    ("foundry", "min_defect_cm2", "0.5", "cm²", "Defect areas smaller than this are not reported (mesh noise)"),
    ("foundry", "sharp_corner_deg", "60", "°", "Inside corner sharper than this = hot tear / stress concentration"),
    ("foundry", "stress_gradient", "0.5", "-", "Solidification-time difference to a neighbour above this share = residual stress"),
    ("foundry", "sprue_height_mm", "part_h + 100", "mm", "Height of the metal in the sprue above the parting line"),
    ("foundry", "cope_safety_pct", "50", "%", "Safety on the weight that keeps the cope down"),
    ("eps", "mesh_size_mm", "max(wall_mm, 2)", "mm", "Mesh size of the solver (triangles are split down to this)"),
    ("eps", "mesh_faces", "150000", "-", "Most triangles of the solver mesh (the mesh size grows to keep below; more = finer, slower)"),
    ("eps", "fill_time_s", "2 + 0.002 * volume_cm3", "s", "Bead filling time"),
    ("eps", "steam_bar", "1.2", "bar", "Steam pressure in the mould"),
    ("eps", "min_wall_beads", "3", "-", "A wall needs at least this many bead diameters to fill and fuse"),
    ("eps", "thickness_exponent", "1", "-", "k of the flow resistance (beads blown by air)"),
    ("eps", "front_cooling_factor", "0", "-", "No melt front (beads)"),
    ("eps", "weld_angle_deg", "150", "°", "Bead streams meeting at more than this angle: fusion line"),
    ("eps", "weld_drop_c", "0", "°C", "-"),
    ("eps", "thin_ratio", "0.5", "-", "Thin section = thinner than this × the wall"),
    ("eps", "hot_spot_ratio", "2", "-", "Thick zone = cooling time above this × the typical (post-expansion, long cycle)"),
    ("eps", "feed_tolerance", "0", "-", "No feeding check (beads)"),
    ("eps", "max_wall_ratio", "8", "-", "Thickness above this × the wall is taken as this"),
    ("eps", "min_defect_cm2", "0.5", "cm²", "Defect areas smaller than this are not reported (mesh noise)"),
    ("eps", "sharp_corner_deg", "75", "°", "Inside corner sharper than this = weak corner"),
    ("eps", "stress_gradient", "0.6", "-", "Cooling-time difference to a neighbour above this share = distortion"),
    ("eps", "clamp_safety_pct", "20", "%", "Clamp force safety margin"),
    ("eps", "open_eject_s", "8", "s", "Mould open, eject, close"),
    ("blow", "mesh_size_mm", "max(wall_mm, 2)", "mm", "Mesh size of the solver (triangles are split down to this)"),
    ("blow", "mesh_faces", "150000", "-", "Most triangles of the solver mesh (the mesh size grows to keep below; more = finer, slower)"),
    ("blow", "blow_bar", "35", "bar", "Blow pressure"),
    ("blow", "preform_od_mm", "max(15, 0.3 * min(max(part_l, part_h), max(part_w, min(part_l, part_h))))", "mm", "Preform outside diameter (0.3 × the bottle diameter)"),
    ("blow", "preform_len_mm", "0.35 * max(part_l, part_w, part_h)", "mm", "Preform length below the neck (0.35 × the bottle length)"),
    ("blow", "thin_ratio", "0.6", "-", "Thin = thinner than this × the average wall"),
    ("blow", "sharp_corner_deg", "60", "°", "Corner sharper than this = thin, stressed corner (rounded base and shoulder)"),
    ("blow", "clamp_safety_pct", "20", "%", "Clamp force safety margin"),
]
RULE_VARS = {
    "volume_cm3": "Part volume (cm³)", "shot_volume_cm3": "Shot volume = (part + runner / overflow) × cavities (cm³)",
    "part_weight_g": "Part weight (g)", "wall_mm": "Main wall (mm)", "part_l": "Part length across the opening (mm)",
    "part_w": "Part width across the opening (mm)", "part_h": "Part height along the opening (mm)", "cavities": "Cavities",
    "projected_area_cm2": "Projected area along the opening (cm²)", "melt_c": "Melt / metal / pour temperature (Process windows, °C)",
    "mould_c": "Mould / die temperature (Process windows, °C)", "eject_c": "Ejection temperature (Process windows, °C)",
} | {f: f"Flow materials → {f}" for f in MATERIAL_FIELDS if f != "family"}


class FlowError(ValueError):
    pass


# ---------- master data ----------

def seed() -> dict:
    """Add the missing Flow materials and Flow rules rows (existing rows are never changed)."""
    d = mould_db.tables()
    out = {"materials": 0, "rules": 0}
    have = {r["material"] for r in d["flow_materials"]}
    for m, *vals in SEED_MATERIALS:
        if m not in have:
            d["flow_materials"].append(dict(zip(("material",) + MATERIAL_FIELDS, (m, *vals))) | {"is_example": True, "notes": EXAMPLE})
            out["materials"] += 1
    have = {(r["part_type"], r["name"]) for r in d["flow_rules"]}
    step = {}
    for pt, name, f, unit, label in SEED_RULES:
        step[pt] = step.get(pt, 0) + 1
        if (pt, name) not in have:
            d["flow_rules"].append({"part_type": pt, "step": step[pt], "name": name, "formula": f, "unit": unit, "label": label,
                                    "is_example": True, "notes": EXAMPLE})
            out["rules"] += 1
    if any(out.values()):
        mould_db.write(d)
    return out


def sample_env(part_type: str) -> dict:
    env = {k: 1.0 for k in RULE_VARS}
    env |= {k: float(v) for k, v in master_data.parameters(part_type).items() if isinstance(v, (int, float))}
    return env


def validate(clean: dict) -> None:
    """Flow rules: one-word names, formulas that evaluate with sample values (called by the Mould & die database check)."""
    for pt in PART_TYPES:
        env = sample_env(pt)
        for i, r in sorted(((i, r) for i, r in enumerate(clean.get("flow_rules", []), start=2) if r["part_type"] == pt),
                           key=lambda x: x[1]["step"]):
            if not r["name"].isidentifier():
                raise mould_db.MouldDbError(f"Flow rules row {i}: '{r['name']}' must be one word (letters, digits and _).")
            try:
                env[r["name"]] = formula.evaluate(r["formula"], env)
            except formula.FormulaError as exc:
                raise mould_db.MouldDbError(f"Flow rules row {i} ({r['name']}): {exc}") from None
            except (ArithmeticError, ValueError):
                env[r["name"]] = 1.0
    for i, r in enumerate(clean.get("flow_materials", []), start=2):
        if r.get("family") not in ("plastic", "metal", "eps", "pet"):
            raise mould_db.MouldDbError(f"Flow materials row {i} ({r['material']}): family must be plastic, metal, eps or pet.")


def material(name: str) -> dict | None:
    return next((r for r in mould_db.tables()["flow_materials"] if r["material"] == name), None)


def _rules(part_type: str) -> list[dict]:
    return sorted((r for r in mould_db.tables()["flow_rules"] if r["part_type"] == part_type), key=lambda r: r["step"])


# ---------- mesh graph ----------

def _weld(tri: np.ndarray) -> np.ndarray:
    """Vertex numbers (m × 3) after merging the vertices that the CAD faces share."""
    v = tri.reshape(-1, 3)
    span = float(np.ptp(v, axis=0).max()) or 1.0
    _, inv = np.unique(np.round(v / (span * 1e-6)).astype(np.int64), axis=0, return_inverse=True)
    return inv.reshape(-1, 3)


def refine(tri: np.ndarray, size_mm: float, max_faces: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Split triangles at the middle of their longest edge until no edge is longer than the mesh size, so the solver works on
    an even mesh (a flat wall of the CAD tessellation is often only 2 long triangles). Returns (triangles, source triangle,
    size used); the size grows when the mesh would have more than max_faces triangles."""
    def longest(t):
        return np.stack([np.linalg.norm(t[:, 1] - t[:, 0], axis=1), np.linalg.norm(t[:, 2] - t[:, 1], axis=1),
                         np.linalg.norm(t[:, 0] - t[:, 2], axis=1)], 1)
    e = longest(tri).max(1)
    area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2
    s = max(size_mm, 1e-3)
    while True:   # estimate: a split triangle ends as about area / (s² / 2) pieces, at least longest edge / s
        est = np.where(e > s, np.maximum(np.ceil(e / s), 2 * area / (s * s)), 1).sum()
        if est <= max_faces or s > e.max():
            break
        s *= 1.2
    for _ in range(6):                    # the estimate is rough: grow the size until the real mesh fits
        out = _bisect(tri, s, longest)
        if len(out[0]) <= 1.2 * max_faces or s > e.max():
            return out + (s,)
        s *= math.sqrt(len(out[0]) / max_faces)
    return out + (s,)


def _bisect(tri, s, longest):
    t, src = tri, np.arange(len(tri))
    done_t, done_s = [], []
    for _ in range(60):
        L = longest(t)
        big = L.max(1) > s
        done_t.append(t[~big])
        done_s.append(src[~big])
        if not big.any():
            break
        t, src, L = t[big], src[big], L[big]
        k = L.argmax(1)                                   # edge k runs from corner k to corner k+1
        p0 = t[np.arange(len(t)), k]
        p1 = t[np.arange(len(t)), (k + 1) % 3]
        p2 = t[np.arange(len(t)), (k + 2) % 3]
        mid = (p0 + p1) / 2
        t = np.concatenate([np.stack([p0, mid, p2], 1), np.stack([mid, p1, p2], 1)])
        src = np.concatenate([src, src])
    return np.concatenate(done_t), np.concatenate(done_s)


def _adjacency(tri0: np.ndarray, tri: np.ndarray, cen: np.ndarray, src: np.ndarray, s: float) -> tuple[np.ndarray, np.ndarray]:
    """Neighbour pairs of the refined triangles: triangles that share a corner point, and centres closer than 1.5 × the mesh
    size (at most 12 each) whose source triangles touch, so walls that only come close (two ribs, a gap) are not joined."""
    from scipy.spatial import cKDTree
    f0 = _weld(tri0)
    m0 = len(tri0)
    inc = sparse.csr_matrix((np.ones(f0.size), (np.repeat(np.arange(m0), 3), f0.ravel())), shape=(m0, int(f0.max()) + 1))
    touch = (inc @ inc.T).tocoo()
    ok = np.unique(touch.row.astype(np.int64) * m0 + touch.col)
    dist, nb = cKDTree(cen).query(cen, k=13, distance_upper_bound=1.5 * s)
    rows = np.repeat(np.arange(len(cen)), nb.shape[1])
    nb, dist = nb.ravel(), dist.ravel()
    good = np.isfinite(dist) & (nb != rows) & (nb < len(cen))
    pairs = np.stack([rows[good], nb[good]], 1)
    if len(pairs):
        key = src[pairs[:, 0]].astype(np.int64) * m0 + src[pairs[:, 1]]
        pairs = pairs[np.isin(key, ok)]
    # shared corner points of the refined mesh (also across CAD faces, whose tessellations meet at the same points)
    f = _weld(tri)
    m = len(tri)
    order = np.argsort(f.ravel(), kind="stable")
    vert, face = f.ravel()[order], np.repeat(np.arange(m), 3)[order]
    starts = np.r_[0, np.flatnonzero(np.diff(vert)) + 1, len(vert)]
    deg = np.diff(starts)
    share = []
    for d in np.unique(deg[deg > 1]):                       # every pair of faces around a point, grouped by how many there are
        st = starts[:-1][deg == d]
        grp = face[st[:, None] + np.arange(d)[None, :]]
        i, j = np.triu_indices(int(min(d, 40)), 1)
        share.append(np.stack([grp[:, i].ravel(), grp[:, j].ravel()], 1))
    allp = np.concatenate([pairs.reshape(-1, 2)] + share) if share else pairs.reshape(-1, 2)
    allp = allp[allp[:, 0] != allp[:, 1]]
    allp = np.unique(np.sort(allp, axis=1), axis=0)
    return allp[:, 0], allp[:, 1]


def _bridge(cen: np.ndarray, a: np.ndarray, b: np.ndarray, length: np.ndarray, s: float):
    """Join islands of the neighbour graph (left by the 12-neighbour limit in dense spots) to the nearest face of the rest."""
    from scipy.spatial import cKDTree
    m = len(cen)
    for _ in range(3):
        n, lab = csgraph.connected_components(sparse.coo_matrix((np.ones(len(a)), (a, b)), shape=(m, m)), directed=False)
        if n == 1:
            break
        main = np.bincount(lab).argmax()
        inside = np.nonzero(lab == main)[0]
        out = np.nonzero(lab != main)[0]
        d, j = cKDTree(cen[inside]).query(cen[out], distance_upper_bound=3 * s)
        ok = np.isfinite(d)
        if not ok.any():
            break
        # one bridge per island: its face nearest to the main part
        o = np.argsort(d[ok])
        isl = lab[out[ok]][o]
        _, first = np.unique(isl, return_index=True)
        fa, fb = out[ok][o][first], inside[j[ok][o][first]]
        a, b = np.r_[a, fa], np.r_[b, fb]
        length = np.r_[length, np.linalg.norm(cen[fa] - cen[fb], axis=1)]
    return a, b, length


def _csr(m: int, a: np.ndarray, b: np.ndarray, w: np.ndarray):
    w = np.maximum(w, 1e-9)
    g = sparse.coo_matrix((np.r_[w, w], (np.r_[a, b], np.r_[b, a])), shape=(m, m)).tocsr()
    g.sum_duplicates()
    return g


def _fill_nearest(m: int, a: np.ndarray, b: np.ndarray, length: np.ndarray, known: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Values on every face from the nearest face (along the surface) that has one."""
    src = np.nonzero(known)[0]
    if not len(src) or known.all():
        return values
    _, _, sources = csgraph.dijkstra(_csr(m, a, b, length), indices=src, min_only=True, return_predecessors=True)
    out = values.copy()
    reach = sources >= 0
    out[reach & ~known] = values[sources[reach & ~known]]
    return out


def _farthest_points(points: np.ndarray, k: int) -> list[int]:
    if not len(points):
        return []
    pick = [int(np.argmin(np.linalg.norm(points - points.mean(0), axis=1)))]
    d = np.linalg.norm(points - points[pick[0]], axis=1)
    while len(pick) < min(k, len(points)):
        i = int(np.argmax(d))
        pick.append(i)
        d = np.minimum(d, np.linalg.norm(points - points[i], axis=1))
    return pick


def _maximin(g, sources: list[int], value: np.ndarray) -> np.ndarray:
    """For every face the best 'bottleneck' along a path from a source: max over paths of min(value on the path) (feeding)."""
    best = np.full(len(value), -np.inf)
    heap = []
    for s in sources:
        best[s] = value[s]
        heap.append((-value[s], s))
    heapq.heapify(heap)
    indptr, indices = g.indptr, g.indices
    while heap:
        nb, u = heapq.heappop(heap)
        nb = -nb
        if nb < best[u]:
            continue
        for v in indices[indptr[u]:indptr[u + 1]]:
            c = min(nb, value[v])
            if c > best[v]:
                best[v] = c
                heapq.heappush(heap, (-c, v))
    return best


def _clusters(flag: np.ndarray, a: np.ndarray, b: np.ndarray, cen: np.ndarray, area: np.ndarray, top: int = 8,
              min_cm2: float = 0.0) -> list[dict]:
    """Groups of neighbouring flagged faces: area (cm²), centre and span (mm), largest first; smaller than min_cm2 left out."""
    idx = np.nonzero(flag)[0]
    if not len(idx):
        return []
    pos = np.full(len(flag), -1)
    pos[idx] = np.arange(len(idx))
    keep = flag[a] & flag[b]
    g = sparse.coo_matrix((np.ones(keep.sum()), (pos[a[keep]], pos[b[keep]])), shape=(len(idx), len(idx)))
    n, lab = csgraph.connected_components(g, directed=False)
    out = []
    for c in range(n):
        f = idx[lab == c]
        ar = float(area[f].sum())
        if ar / 100 < min_cm2:
            continue
        out.append({"area_cm2": ar / 100, "centre_mm": [round(float(x), 1) for x in (cen[f] * area[f, None]).sum(0) / max(ar, 1e-12)],
                    "span_mm": [round(float(x)) for x in np.ptp(cen[f], axis=0)], "faces": int(len(f))})
    out.sort(key=lambda x: -x["area_cm2"])
    return out[:top]


# ---------- the solver ----------

def run(vertices, triangles, part_type: str, mat: dict, window: dict, facts: dict, opening_axis: str, gates: int = 1,
        gate_point: list | None = None, progress=None) -> dict:
    """Flow simulation of one part (see the module text). facts: wall_mm, part_l / part_w / part_h, volume_cm3, part_weight_g,
    cavities, projected_area_cm2, density_g_cm3; window: melt_c, mould_c, eject_c (Process windows)."""
    say = progress or (lambda pct, text: None)
    if part_type not in PART_TYPES:
        raise FlowError(f"No flow simulation for {part_type.replace('_', ' ')} parts (plastic, die casting, foundry, EPS, blow moulding).")
    if not mat:
        raise FlowError("The material is not in Mould & die database → Flow materials: add its flow data there.")
    rules = _rules(part_type)
    if not rules:
        raise FlowError(f"Mould & die database → Flow rules has no rows for {part_type.replace('_', ' ')}.")
    v = np.asarray(vertices, float)
    tri0 = v[np.asarray(triangles, int)]
    area0 = np.linalg.norm(np.cross(tri0[:, 1] - tri0[:, 0], tri0[:, 2] - tri0[:, 0]), axis=1) / 2
    wall = float(facts.get("wall_mm") or 0) or 2 * float(facts.get("volume_cm3") or 0) * 1000 / max(area0.sum(), 1e-9)
    env = sample_env(part_type) | {k: 0.0 for k in RULE_VARS}
    env |= {k: float(mat.get(k) or 0) for k in MATERIAL_FIELDS if k != "family"}
    env |= {k: float(window.get(k) or 0) for k in ("melt_c", "mould_c", "eject_c")}
    env |= {k: float(facts.get(k) or 0) for k in ("volume_cm3", "part_weight_g", "part_l", "part_w", "part_h", "cavities",
                                                  "projected_area_cm2")}
    env["wall_mm"] = wall
    env["shot_volume_cm3"] = env["volume_cm3"] * max(env["cavities"], 1)
    steps = []
    for r in rules:
        try:
            env[r["name"]] = float(formula.evaluate(r["formula"], env))
        except (ArithmeticError, ValueError) as exc:
            raise FlowError(f"Flow rule '{r['name']}' ({r['formula']}): {exc}") from None
        steps.append({"name": r["name"], "label": r["label"], "formula": r["formula"], "unit": r["unit"], "value": env[r["name"]],
                      "is_example": bool(r["is_example"])})
        if r["name"] in ("overflow_pct", "runner_pct"):
            env["shot_volume_cm3"] = env["volume_cm3"] * max(env["cavities"], 1) * (1 + env[r["name"]] / 100)
    say(3, "Meshing")
    tri, src, mesh_mm = refine(tri0, env.get("mesh_size_mm") or max(wall, 1.0), int(env.get("mesh_faces") or 150000))
    m = len(tri)
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    twice = np.linalg.norm(cross, axis=1)
    area = twice / 2
    n = cross / np.where(twice > 0, twice, 1)[:, None]
    cen = tri.mean(axis=1)
    ax = concept.AXES.index(opening_axis)
    is_metal = mat["family"] == "metal"
    try:
        sim_p = {k: float(x) for k, x in concept._rules(part_type).items() if k != "is_example"}
    except (KeyError, ValueError, TypeError):
        sim_p = {}
    a, b = _adjacency(tri0, tri, cen, src, mesh_mm)
    say(8, "Measuring the wall thickness")
    max_rays = int(env.get("max_rays") or sim_p.get("undercut_max_faces") or 20000)
    step = max(1, math.ceil(m / max_rays))
    idx = np.arange(0, m, step)
    off = sim_p.get("undercut_offset_mm", 0.01)
    th, opp = simulation.thickness_hits(tri, n, idx, off)
    # a long ray may run along a wall (from a rim, an edge, through an opening) instead of across it: 4 more rays tilted by
    # 40° tell a rim (thin sideways) from a thick section (thick every way). Two opposite tilted rays leaving a section of
    # width W through its sides run d1 + d2 = W / sin 40° wherever the face is: the width is the smaller pair, never more than
    # the straight ray; only a straight ray that agrees with it links the two skins
    typical = float(np.nanmedian(th[np.isfinite(th)])) if np.isfinite(th).any() else wall
    sus = np.nonzero(~np.isfinite(th) | (th > 1.5 * max(typical, wall)))[0]
    tmin = th.copy()
    if len(sus):
        nn = n[idx[sus]]
        helper = np.where(np.abs(nn[:, [0]]) < 0.9, [[1.0, 0, 0]], [[0, 1.0, 0]])
        u = np.cross(nn, helper)
        u /= np.linalg.norm(u, axis=1)[:, None]
        w = np.cross(nn, u)
        c, sn = math.cos(math.radians(40)), math.sin(math.radians(40))
        tilted = np.stack([simulation.thickness_hits(tri, n, idx[sus], off, -nn * c + side * sn)[0] for side in (u, -u, w, -w)], 1)
        tilted = np.where(np.isfinite(tilted), tilted, np.inf)
        width = np.minimum(tilted[:, 0] + tilted[:, 1], tilted[:, 2] + tilted[:, 3]) * sn
        tmin[sus] = np.fmin(np.where(np.isfinite(th[sus]), th[sus], np.inf), width)
        tmin[sus] = np.where(np.isfinite(tmin[sus]), tmin[sus], np.nan)
    cap = float(env.get("max_wall_ratio") or 4) * wall
    tmin = np.where(np.isfinite(tmin), np.minimum(tmin, cap), np.nan)
    good = np.isfinite(tmin) & (opp >= 0)
    h = np.full(m, np.nan)
    h[idx[good]] = tmin[good]
    link = good & (th <= 1.5 * tmin)
    oa, ob, od = idx[link], opp[link], th[link]
    length = np.linalg.norm(cen[a] - cen[b], axis=1)
    a, b, length = _bridge(cen, a, b, length, mesh_mm)
    h = _fill_nearest(m, a, b, length, np.isfinite(h), h)
    h = np.clip(np.nan_to_num(h, nan=wall), 0.05 * wall, cap)
    deg = np.bincount(np.r_[a, b], minlength=m)
    for _ in range(3):
        mean = np.bincount(np.r_[a, b], weights=np.r_[h[b], h[a]], minlength=m) / np.maximum(deg, 1)
        h = np.where(deg > 0, np.minimum(h, 1.5 * mean), h)
    hf = np.clip(h, 0.2 * wall, cap)                                   # thickness the flow and the heat see (mm)
    out = {"part_type": part_type, "opening_axis": opening_axis, "wall_mm": wall, "faces": m, "cad_faces": len(tri0),
           "mesh_mm": mesh_mm, "rays": len(idx), "steps": steps,
           "material": {k: mat.get(k) for k in ("material",) + MATERIAL_FIELDS} | {"is_example": bool(mat.get("is_example"))},
           "window": {k: env[k] for k in ("melt_c", "mould_c", "eject_c")}}
    if part_type == "blow":
        return out | _blow(tri, area, n, cen, a, b, hf, env, facts, steps, say)
    say(25, "Finding the gate")
    k_exp = env.get("thickness_exponent", 1.0)
    href = float(np.median(hf))
    hm = (hf[a] + hf[b]) / 2
    w_flow = length / np.power(hm / href, k_exp)
    w_thru = od / np.power(np.maximum(od, 1e-6) / href, k_exp)
    aa, bb = np.r_[a, oa], np.r_[b, ob]
    flow_g = _csr(m, aa, bb, np.r_[w_flow, w_thru])
    geo_g = _csr(m, aa, bb, np.r_[length, od])
    up = np.zeros(3)
    up[ax] = 1.0
    gate_faces, gate_note = [], ""
    if part_type == "foundry":
        R = np.dot(cen, up) - np.dot(cen, up).min()                     # gravity: fills from the bottom
        gate_faces = [int(np.argmin(np.dot(cen, up)))]
        gate_note = "bottom of the casting (gravity filling from the bottom up)"
        pred = np.full(m, -9999)
        _, pred = csgraph.dijkstra(geo_g, indices=gate_faces, min_only=True, return_predecessors=True)[:2]
    else:
        if gate_point:
            gate_faces = [int(np.argmin(np.linalg.norm(cen - np.asarray(gate_point, float), axis=1)))]
            gate_note = f"typed gate point {', '.join(f'{x:g}' for x in gate_point)} mm"
        else:
            cand = np.nonzero((np.abs(n[:, ax]) > 0.9) & (area > 0))[0]
            if not len(cand):
                cand = np.arange(m)
            pick = cand[_farthest_points(cen[cand], 16)]
            dist = csgraph.dijkstra(flow_g, indices=pick)
            worst = np.where(np.isfinite(dist), dist, 0).max(axis=1)
            reached = np.isfinite(dist).sum(axis=1)
            best = int(np.lexsort((worst, -reached))[0])
            gate_faces = [int(pick[best])]
            gate_note = "found: least flow resistance to the last point to fill"
        for _ in range(max(1, int(gates)) - 1):                          # more gates: where the resistance is highest
            d = csgraph.dijkstra(flow_g, indices=gate_faces, min_only=True)
            gate_faces.append(int(np.argmax(np.where(np.isfinite(d), d, -1))))
        R, pred = csgraph.dijkstra(flow_g, indices=gate_faces, min_only=True, return_predecessors=True)[:2]
    say(40, "Filling")
    reach = np.isfinite(R)
    vol = area * hf / 2                                                 # each skin carries half of the wall
    order = np.argsort(np.where(reach, R, np.inf), kind="stable")
    t_fill = float(env["fill_time_s"])
    cum = np.cumsum(np.where(reach, vol, 0)[order])
    t = np.full(m, np.nan)
    t[order] = cum / max(cum[-1], 1e-12) * t_fill
    t[~reach] = np.nan
    has_pred = pred >= 0
    pp = np.where(has_pred, pred, np.arange(m))
    seg = np.linalg.norm(cen - cen[pp], axis=1)
    dt = np.maximum(np.nan_to_num(t - t[pp]), t_fill * 1e-6)
    geo_len = np.zeros(m)
    for i in order:                                                    # path length from the gate
        if has_pred[i]:
            geo_len[i] = geo_len[pred[i]] + seg[i]
    vmean = max(float(np.nanmax(geo_len)), wall) / max(t_fill, 1e-9) / 1000          # m/s
    vel = np.clip(seg / dt / 1000, vmean / 20, vmean * 20)
    vel[~has_pred] = vmean
    # pressure (plastic: power-law Hele-Shaw; metal / EPS: not the limit, intensification / steam pressure is)
    drop = np.zeros(m)
    gamma = np.zeros(m)
    if part_type == "plastic":
        eta_ref, nn, gref = env["viscosity_pa_s"], max(env["shear_index_n"], 0.1), max(env["ref_shear_1_s"], 1.0)
        hm_m = hf / 1000
        gamma = np.clip(6 * vel / hm_m, 1.0, 1e6)
        eta = eta_ref * np.power(gamma / gref, nn - 1)
        dp = 12 * eta * vel * (seg / 1000) / hm_m ** 2 / 1e5                     # bar
        for i in order:
            if has_pred[i]:
                drop[i] = drop[pred[i]] + dp[i]
    p_cav = float(np.nanmax(np.where(reach, drop, 0)))
    p_end = np.where(reach, p_cav - drop, 0.0)
    say(55, "Cooling and solidification")
    Tm, Tw, Te = env["melt_c"], env["mould_c"], env["eject_c"]
    res = {}
    if part_type == "plastic":
        alpha = max(env["diffusivity_mm2_s"], 1e-6)
        lg = lambda T: math.log(max(4 / math.pi * (Tm - Tw) / max(T - Tw, 1e-6), 1.0001))
        tau = hf ** 2 / (math.pi ** 2 * alpha)
        t_cool = tau * lg(Te)
        t_freeze = tau * lg(env["no_flow_c"])
        T_front = Tm - (Tm - env["no_flow_c"]) * np.clip(np.nan_to_num(t) / t_freeze, 0, 1) * env["front_cooling_factor"]
        weak_front = T_front < Tm - env["weld_drop_c"]
        solid = t_cool
    elif is_metal:
        B = max(env["chvorinov_s_mm2"], 1e-6)
        t_solid = B * (hf / 2) ** 2
        rng = max(Tm - env["solidus_c"], 1.0)
        t_freeze = t_solid * np.clip((Tm - env["no_flow_c"]) / rng, 0.02, 1)
        T_front = Tm - (Tm - env["no_flow_c"]) * np.clip(np.nan_to_num(t) / t_freeze, 0, 1) * env["front_cooling_factor"]
        weak_front = T_front < env["no_flow_c"] + env["weld_drop_c"]
        solid = t_solid
        t_cool = t_solid
    else:                                                              # EPS: cooling ∝ h², no melt front
        t_cool = max(env["chvorinov_s_mm2"], 1e-6) * hf ** 2
        t_freeze = np.full(m, np.inf)
        T_front = np.full(m, np.nan)
        weak_front = np.zeros(m, bool)
        solid = t_cool
    say(65, "Defects")
    # weld lines: neighbours not on each other's flow path whose flow directions meet head-on
    anc = pp.copy()                                                    # flow direction over ~6 faces of the path (less noise)
    for _ in range(5):
        anc = pp[anc]
    dirs = cen - cen[anc]
    dn = np.linalg.norm(dirs, axis=1)
    dirs = dirs / np.where(dn > 0, dn, 1)[:, None]
    cosw = math.cos(math.radians(env["weld_angle_deg"]))
    not_tree = (pred[a] != b) & (pred[b] != a) & has_pred[a] & has_pred[b] & reach[a] & reach[b]
    together = np.abs(np.nan_to_num(t[a]) - np.nan_to_num(t[b])) < 0.02 * t_fill    # the fronts arrive at the same time
    meet = not_tree & together & (np.einsum("ij,ij->i", dirs[a], dirs[b]) < cosw)
    weld = np.zeros(m, bool)
    weld[a[meet]] = True
    weld[b[meet]] = True
    # last to fill: no neighbour fills later → trapped air / gas
    tt = np.nan_to_num(t, nan=-1)
    ring = tt.copy()                                                   # latest fill time within two rings of neighbours
    for _ in range(2):
        nxt = ring.copy()
        np.maximum.at(nxt, a, ring[b])
        np.maximum.at(nxt, b, ring[a])
        ring = nxt
    trap = reach & (tt >= ring) & (tt > 0.5 * t_fill)
    if part_type == "foundry":
        # gas rises to the mould surfaces above the metal (faces looking up); it is trapped where every way to the top of
        # the casting (vents, risers) first goes down: the best path's lowest point is below the face
        z = np.dot(cen, up)
        top = list(np.nonzero(z >= z.max() - 0.02 * np.ptp(z))[0])
        escape = _maximin(geo_g, top, z)
        trap = (np.dot(n, up) > 0.5) & (escape < z - 0.5 * wall)
    # short shot / hesitation: a thin section crossed for longer than its freeze-off time
    thin = hf < env["thin_ratio"] * wall
    stall = np.zeros(m)
    for i in order:
        if has_pred[i] and thin[i]:
            stall[i] = stall[pred[i]] + dt[i]
    short = reach & thin & (stall > t_freeze)
    if part_type == "eps":
        short |= hf < env["min_wall_beads"] * max(env["bead_mm"], 0.1)
    p_machine = p_cav * (1 + env.get("feed_drop_pct", 0) / 100)
    if part_type == "plastic" and p_machine > env["max_injection_bar"]:
        short |= reach & (tt >= np.nanquantile(np.where(reach, tt, np.nan), 0.97))
    short |= ~reach
    # hot spots and feeding (sink marks / voids, shrinkage porosity)
    typical = float(np.median(solid))
    hot = solid > env["hot_spot_ratio"] * typical
    porosity = np.zeros(m, bool)
    if env.get("feed_tolerance", 0) > 0 and hot.any():
        feed = _maximin(geo_g, gate_faces, solid)
        porosity = hot & (feed < env["feed_tolerance"] * solid)
    # stress: sharp inside corners and cooling-time jumps between neighbours
    cosc = math.cos(math.radians(env["sharp_corner_deg"]))
    turn = np.einsum("ij,ij->i", n[a], n[b]) < cosc
    concave = np.einsum("ij,ij->i", cen[b] - cen[a], n[a]) > 1e-6
    sharp = turn & concave
    corner = np.zeros(m, bool)
    corner[a[sharp]] = True
    corner[b[sharp]] = True
    jump = np.abs(solid[a] - solid[b]) / np.maximum(np.maximum(solid[a], solid[b]), 1e-9) > env["stress_gradient"]
    grad = np.zeros(m, bool)
    grad[a[jump]] = True
    grad[b[jump]] = True
    stress = corner | grad | (weld & weak_front)
    say(75, "Machine")
    A_proj = float(facts.get("projected_area_cm2") or 0)
    cav = max(int(env["cavities"] or 1), 1)
    one_side = n[:, ax] > 0.3
    w_side = area[one_side] * n[one_side, ax]
    p_avg = float((p_end[one_side] * w_side).sum() / max(w_side.sum(), 1e-9)) if one_side.any() else 0.0
    if part_type == "plastic":
        p_clamp = max(p_avg, env["pack_pct"] / 100 * p_cav)
        clamp_t = A_proj * cav * p_clamp * (1 + env["clamp_safety_pct"] / 100) / 1000
        cycle = t_fill + env["pack_time_s"] + float(np.quantile(t_cool, 0.95)) + env["open_eject_s"]
        res |= {"injection_bar": p_machine, "cavity_bar": p_cav, "hold_bar": env["pack_pct"] / 100 * p_cav,
                "cooling_s": float(np.quantile(t_cool, 0.95))}
    elif part_type == "die_casting":
        clamp_t = A_proj * (1 + env["overflow_pct"] / 100) * cav * env["intensification_bar"] * (1 + env["clamp_safety_pct"] / 100) / 1000
        cycle = t_fill + float(np.quantile(t_solid, 0.95)) + env["die_open_s"] + env["spray_s"]
        res |= {"intensification_bar": env["intensification_bar"], "solidification_s": float(np.quantile(t_solid, 0.95)),
                "front_speed_m_s": vmean}
    elif part_type == "foundry":
        rho = float(facts.get("density_g_cm3") or 7.0)
        head_m = env["sprue_height_mm"] / 1000
        lift_kg = rho * 1000 * head_m * A_proj / 1e4 * cav
        clamp_t = 0.0
        cycle = float(np.max(t_solid))
        res |= {"cope_weight_kg": lift_kg * (1 + env["cope_safety_pct"] / 100), "solidification_s": float(np.max(t_solid)),
                "metallostatic_bar": rho * 9.81 * head_m / 100}
    else:
        clamp_t = A_proj * cav * env["steam_bar"] * (1 + env["clamp_safety_pct"] / 100) / 1000
        cycle = t_fill + float(np.quantile(t_cool, 0.95)) + env["open_eject_s"]
        res |= {"steam_bar": env["steam_bar"], "cooling_s": float(np.quantile(t_cool, 0.95))}
    shot_cm3 = env["shot_volume_cm3"]
    rho = float(facts.get("density_g_cm3") or 1.0)
    machine = simulation._machine(part_type, clamp_t) if clamp_t > 0 else {"machine_id": None, "process": None}
    risers = []
    if part_type in ("foundry", "die_casting"):
        for c in _clusters(porosity | hot, a, b, cen, area, 6):
            f_near = int(np.argmin(np.linalg.norm(cen - np.asarray(c["centre_mm"]), axis=1)))
            M = float(hf[f_near]) / 2
            Mr = env.get("riser_modulus_factor", 1.2) * M
            risers.append(c | {"modulus_mm": M, "riser_modulus_mm": Mr, "riser_d_mm": Mr / 0.214})
    maps = {"weld": weld, "weak_weld": weld & weak_front, "air_trap": trap, "short_shot": short, "hot_spot": hot,
            "porosity": porosity, "corner": corner, "stress": stress}
    res |= {"fill_time_s": t_fill, "clamp_t": clamp_t, "cycle_s": cycle, "shot_volume_cm3": shot_cm3, "shot_weight_g": shot_cm3 * rho,
            "flow_length_mm": float(np.nanmax(geo_len)), "front_temp_min_c": float(np.nanmin(T_front)) if np.isfinite(T_front).any() else None,
            "unfilled_cm2": float(area[~reach].sum()) / 100}
    clusters = {k: _clusters(f, a, b, cen, area, min_cm2=env.get("min_defect_cm2", 0)) for k, f in maps.items()}
    out |= {"gates": [{"face": g, "at_mm": [round(float(x), 1) for x in cen[g]]} for g in gate_faces], "gate_note": gate_note,
            "results": res, "machine": machine, "risers": risers, "areas_cm2": {k: float(area[f].sum()) / 100 for k, f in maps.items()},
            "clusters": clusters,
            "_faces": {"tri": tri, "pred": pred, "geo": geo_len, "h": hf, "t": t, "p": p_end, "T": T_front, "solid": solid, "shear": gamma, **maps}}
    out["corrections"] = _corrections(part_type, out, env)
    out["is_example"] = bool(mat.get("is_example")) or any(s["is_example"] for s in steps)
    say(80, "Result ready")
    return out


def _blow(tri, area, n, cen, a, b, hf, env, facts, steps, say) -> dict:
    """PET stretch blow moulding: wall thickness after stretching (hoop × axial stretch of the preform; mass kept)."""
    say(40, "Stretching the preform")
    axes = np.ptp(tri.reshape(-1, 3), axis=0)
    ax = int(np.argmax(axes))                                           # bottle axis = longest side
    c = (tri.reshape(-1, 3).min(0) + tri.reshape(-1, 3).max(0)) / 2
    radial = cen - c
    radial[:, ax] = 0
    r = np.linalg.norm(radial, axis=1)
    hoop = np.maximum(r / max(env["preform_od_mm"] / 2, 1e-3), 1.0)
    axial = max(axes[ax] / max(env["preform_len_mm"], 1e-3), 1.0)
    stretch = hoop * axial
    rel = 1 / stretch
    avg = float(facts.get("wall_mm") or np.median(hf))
    wall = rel / max(float((rel * area).sum() / area.sum()), 1e-12) * avg
    thin = wall < env["thin_ratio"] * avg
    over = stretch > max(env.get("stretch_max") or 0, 1e-9) if env.get("stretch_max") else np.zeros(len(tri), bool)
    cosc = math.cos(math.radians(env["sharp_corner_deg"]))
    sharp = (np.einsum("ij,ij->i", n[a], n[b]) < cosc)
    corner = np.zeros(len(tri), bool)
    corner[a[sharp]] = True
    corner[b[sharp]] = True
    A_proj = float(facts.get("projected_area_cm2") or 0)
    clamp_t = A_proj * max(int(facts.get("cavities") or 1), 1) * env["blow_bar"] * (1 + env["clamp_safety_pct"] / 100) / 1000
    maps = {"thin": thin, "over_stretch": over, "corner": corner, "stress": over | corner}
    res = {"stretch_max": float(stretch.max()), "hoop_max": float(hoop.max()), "axial": axial, "wall_min_mm": float(wall.min()),
           "wall_max_mm": float(wall.max()), "clamp_t": clamp_t, "blow_bar": env["blow_bar"]}
    out = {"gates": [], "gate_note": "preform on the bottle axis", "results": res,
           "machine": simulation._machine("blow", clamp_t), "risers": [],
           "areas_cm2": {k: float(area[f].sum()) / 100 for k, f in maps.items()},
           "clusters": {k: _clusters(f, a, b, cen, area) for k, f in maps.items()},
           "_faces": {"tri": tri, "h": wall, "stretch": stretch, **maps}}
    corr = []
    if thin.any():
        corr.append(f"Thin wall after stretching on {out['areas_cm2']['thin']:.1f} cm² (below {env['thin_ratio']:g} × the {avg:.2f} mm "
                    f"average, thinnest {wall.min():.2f} mm): a preform with more material there, or less stretch (larger preform).")
    if over.any():
        corr.append(f"Stretch ratio {stretch.max():.1f} is above the material's {env['stretch_max']:g} on {out['areas_cm2']['over_stretch']:.1f} cm²: "
                    "stress whitening / burst risk — a larger or longer preform.")
    if corner.any():
        corr.append(f"Sharp corners on {out['areas_cm2']['corner']:.1f} cm² stretch thin: round the base and shoulder.")
    out["corrections"] = corr
    out["is_example"] = any(s["is_example"] for s in steps)
    say(80, "Result ready")
    return out


def _where(cl: list[dict]) -> str:
    def one(c):
        big = max(c["span_mm"]) > 50
        return (f"{c['area_cm2']:.1f} cm² " + ("around" if big else "at") + f" ({', '.join(f'{x:g}' for x in c['centre_mm'])})"
                + (f" over {' × '.join(f'{x:g}' for x in c['span_mm'])} mm" if big else ""))
    return "; ".join(one(c) for c in cl[:3])


def _corrections(part_type: str, r: dict, env: dict) -> list[str]:
    cl, res = r["clusters"], r["results"]
    a = {k: (sum(c["area_cm2"] for c in cl.get(k, [])) if cl.get(k) else 0.0) for k in r["areas_cm2"]}   # noise left out
    metal = part_type in ("die_casting", "foundry")
    out = []
    if res["unfilled_cm2"] > 0:
        out.append(f"{res['unfilled_cm2']:.1f} cm² is not connected to the gate (a separate body in the 3D file?): check the model or add a gate.")
    if a["short_shot"] > 0 and part_type == "eps":
        out.append(f"Walls too thin to fill and fuse with beads on {a['short_shot']:.1f} cm² ({_where(cl['short_shot'])}): at least "
                   f"{env['min_wall_beads']:g} bead diameters ({env['min_wall_beads'] * env['bead_mm']:g} mm), or a smaller bead grade; a fill gun near it.")
    elif a["short_shot"] > 0:
        what = "Misrun" if metal else "Short shot / hesitation"
        out.append(f"{what} risk on {a['short_shot']:.1f} cm² ({_where(cl['short_shot'])}): thicken the thin section, add a gate near it, "
                   + ("raise the metal / die temperature or the shot speed." if metal else "hotter melt / mould, faster injection."))
    if part_type == "plastic" and res.get("injection_bar", 0) > env["max_injection_bar"]:
        out.append(f"Injection pressure {res['injection_bar']:.0f} bar is above the machine's {env['max_injection_bar']:g} bar: more gates "
                   "(or a hot runner), thicker walls, or a hotter, easier-flowing grade.")
    if a["air_trap"] > 0:
        if metal:
            out.append(f"Gas porosity / blow-hole risk at the last-filled areas, {a['air_trap']:.1f} cm² ({_where(cl['air_trap'])}): "
                       + ("place overflows and vents (or vacuum) there." if part_type == "die_casting" else
                          "vents / whistlers and a riser there; vent the cores; dry sand and cores."))
        else:
            out.append(f"Air traps on {a['air_trap']:.1f} cm² ({_where(cl['air_trap'])}): vent there (parting line, ejector pin, insert), "
                       "or move the gate so this area does not fill last (burn marks, short shot).")
    if a["weld"] > 0:
        if metal:
            if a["weak_weld"] > 0:
                out.append(f"Cold-shut risk where the metal fronts meet, {a['weak_weld']:.1f} cm² ({_where(cl['weak_weld'])}): hotter metal / die, "
                           "faster fill, or an overflow at the meeting line.")
        elif a["weak_weld"] > 0:
            out.append(f"Weak / visible weld lines on {a['weak_weld']:.1f} cm² ({_where(cl['weak_weld'])}): move the gate, hotter melt / mould, "
                       "a vent at the weld; keep them away from loaded or visible faces.")
        else:
            out.append(f"Weld lines on {a['weld']:.1f} cm² ({_where(cl['weld'])}): fronts still hot (good strength); check they are not on a visible face.")
    if a["porosity"] > 0:
        out.append(("Shrinkage porosity" if metal else "Sink mark / void") + f" risk on {a['porosity']:.1f} cm² ({_where(cl['porosity'])}): "
                   + ("the hot spot solidifies after its feed path — core it out, or a riser / local squeeze pin / cooling there."
                      if metal else "the thick section freezes after its pack path — core it out (rib ≤ 0.6 × wall) or gate into the thick section."))
    elif a["hot_spot"] > 0:
        out.append(f"Thick sections ({a['hot_spot']:.1f} cm²) cool slowest and set the cycle: core out or cool them locally.")
    if a["corner"] > 0:
        out.append(f"Sharp inside corners on {a['corner']:.1f} cm² ({_where(cl['corner'])}): stress concentration"
                   + (" / hot tear" if metal else "") + " — add a radius of at least 0.5 × the wall.")
    if a["stress"] - a["corner"] > 0.5:
        out.append("Large differences in cooling time between neighbouring areas: residual stress and warpage — keep the wall even, "
                   "cool the thick areas harder.")
    m = r["machine"]
    if res["clamp_t"] > 0 and not m.get("machine_id"):
        out.append(f"No '{m.get('process')}' machine takes the {res['clamp_t']:.0f} t needed (largest {m.get('biggest_t', 0):g} t): fewer cavities or a bigger machine.")
    if part_type == "foundry" and r["risers"]:
        rr = r["risers"][0]
        out.append(f"Riser at ({', '.join(f'{x:g}' for x in rr['centre_mm'])}): hot-spot modulus {rr['modulus_mm']:.1f} mm → riser modulus "
                   f"{rr['riser_modulus_mm']:.1f} mm, cylinder Ø {rr['riser_d_mm']:.0f} mm × {1.5 * rr['riser_d_mm']:.0f} mm.")
    return out


def public(res: dict) -> dict:
    return {k: v for k, v in res.items() if k != "_faces"}


# ---------- pictures, video ----------

def _ramp(x: np.ndarray, invalid=None) -> np.ndarray:
    """Blue → cyan → green → yellow → red (0..1); grey where invalid."""
    stops = np.array([(0.13, 0.30, 0.85), (0.10, 0.75, 0.90), (0.20, 0.75, 0.30), (0.98, 0.85, 0.10), (0.85, 0.15, 0.15)])
    x = np.clip(np.nan_to_num(x), 0, 1) * (len(stops) - 1)
    i = np.minimum(x.astype(int), len(stops) - 2)
    f = (x - i)[:, None]
    c = stops[i] * (1 - f) + stops[i + 1] * f
    if invalid is not None:
        c[invalid] = (0.80, 0.82, 0.85)
    return c


def maps(res: dict) -> list[tuple[np.ndarray, np.ndarray, str]]:
    """(face colours, outline key, caption) of every map of the result."""
    f = res["_faces"]
    m = len(f["tri"])
    grey = np.tile((0.80, 0.82, 0.85), (m, 1))

    def scaled(x, unit, title, lo=None, hi=None):
        ok = np.isfinite(x)
        lo = float(np.nanmin(x)) if lo is None and ok.any() else (lo or 0.0)
        hi = float(np.nanmax(x)) if hi is None and ok.any() else (hi or 1.0)
        s = (x - lo) / max(hi - lo, 1e-12)
        return _ramp(s, ~ok), np.where(ok, np.clip(np.nan_to_num(s) * 8, 0, 8).astype(int), -1), f"{title} {lo:.3g} – {hi:.3g} {unit} (blue → red)"
    out = []
    if res["part_type"] == "blow":
        out.append(scaled(f["h"], "mm", "Wall thickness after stretching"))
        out.append(scaled(f["stretch"], "", "Stretch ratio (hoop × axial)"))
        risk = grey.copy()
        key = np.zeros(m, int)
        for k, (name, col) in enumerate((("corner", (0.95, 0.55, 0.1)), ("thin", (0.15, 0.45, 0.85)), ("over_stretch", (0.85, 0.15, 0.15))), 1):
            risk[f[name]] = col
            key[f[name]] = k
        out.append((risk, key, "Risk: blue thin, red over-stretched, orange sharp corner"))
        return out
    metal = res["part_type"] in ("die_casting", "foundry")
    out.append(scaled(f["t"], "s", "Fill time"))
    if res["part_type"] == "plastic":
        out.append(scaled(f["p"], "bar", "Pressure at the end of filling"))
    if np.isfinite(f["T"]).any():
        out.append(scaled(f["T"], "°C", "Flow-front temperature"))
    out.append(scaled(f["solid"], "s", "Solidification time" if metal else "Cooling time"))
    risk = grey.copy()
    key = np.zeros(m, int)
    legend = ((("weld", (0.95, 0.75, 0.1)), ("weak_weld", (0.95, 0.45, 0.05)), ("air_trap", (0.55, 0.2, 0.7)),
               ("hot_spot", (0.98, 0.6, 0.6)), ("porosity", (0.85, 0.1, 0.1)), ("short_shot", (0.15, 0.45, 0.85))))
    for k, (name, col) in enumerate(legend, 1):
        risk[f[name]] = col
        key[f[name]] = k
    out.append((risk, key, ("Defects: purple gas / blow hole, red shrinkage porosity, pink hot spot, yellow / orange weld / cold shut, blue misrun"
                            if metal else "Defects: purple air trap, red void / sink, pink hot spot, yellow weld, orange weak weld, blue short shot")))
    st = grey.copy()
    st[f["stress"]] = (0.85, 0.15, 0.15)
    st[f["corner"]] = (0.95, 0.55, 0.1)
    out.append((st, f["stress"].astype(int) + f["corner"].astype(int), "Stress areas: orange sharp inside corner, red residual stress / weak weld"))
    return out


def pictures(res: dict, size=(900, 560)) -> list[tuple[str, bytes]]:
    """One PNG per map (iso view)."""
    from . import render3d, sim_report
    tri = res["_faces"]["tri"]
    view = sim_report.turntable(tri, 1, size)[0]
    return [(cap, render3d.png(render3d.paint(view, col, edge_key=key))) for col, key, cap in maps(res)]


def video(res: dict, part: dict, fps: int = 12, size=(960, 540), progress=None) -> tuple[bytes, str]:
    """Filling animation from the gate (fill time), then a turntable of every map, with captions."""
    from . import render3d, sim_report
    say = progress or (lambda pct, text: None)
    f = res["_faces"]
    tri = f["tri"]
    n_turn = fps * 2
    views = sim_report.turntable(tri, n_turn, size, progress=lambda i, n: say(82 + 10 * i / n, "Drawing the video"))
    head = f"{part['part_code']} · {part['name']} · flow simulation"
    frames = []
    ms = maps(res)
    if res["part_type"] != "blow":
        col, key, _ = ms[0]
        t = f["t"]
        T = float(np.nanmax(t)) if np.isfinite(t).any() else 1.0
        empty = np.tile((0.92, 0.93, 0.95), (len(tri), 1))
        for i in range(fps * 4 + 1):
            now = T * i / (fps * 4)
            done = np.nan_to_num(t, nan=np.inf) <= now
            c = np.where(done[:, None], col, empty)
            frames.append(sim_report._caption(render3d.paint(views[0], c, edge_key=np.where(done, key, -2)), head,
                                              f"Filling {now:.3g} s of {T:.3g} s ({100 * i / (fps * 4):.0f} %)", False))
    for k, (col, key, cap) in enumerate(ms):
        bad = k >= len(ms) - 2 and bool(res["corrections"])
        frames += [sim_report._caption(render3d.paint(v, col, edge_key=key), head, cap, bad) for v in views]
    say(94, "Encoding the video")
    r = res["results"]
    final = (f"Result: {len(res['corrections'])} correction(s) - {res['corrections'][0][:90]}" if res["corrections"] else "Result: no corrections required")
    final += f" · clamp {r.get('clamp_t', 0):.0f} t"
    frames += [sim_report._caption(render3d.paint(views[0], ms[-2][0], edge_key=ms[-2][1]), head, final, bool(res["corrections"]))] * (fps * 3)
    return sim_report._encode(frames, fps)
