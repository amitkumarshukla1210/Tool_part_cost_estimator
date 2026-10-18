"""Mould / die sizing and BOM from the mould database.

    cavities + part size  ->  cavity layout (rows × columns)
    layout + insert walls ->  insert size per cavity and insert pocket
    insert pocket         ->  smallest standard mould base it fits in
    part, layout and base ->  BOM: quantity, weight, hours and cost per line

All sizes, walls, rates and BOM rules come from the mould database, so the
result changes when the database is edited, without code changes.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from . import formula, mould_db

SIZING_KEYS = ("insert_wall_mm", "insert_gap_mm", "insert_backing_mm", "plate_floor_mm")


class MouldInput(BaseModel):
    part_type: Literal["plastic", "die_casting", "foundry", "sheet_metal"]
    cavities: int = Field(gt=0, le=256)
    part_length_mm: float = Field(gt=0)
    part_width_mm: float = Field(gt=0)
    part_height_mm: float = Field(gt=0)
    projected_area_cm2: float = Field(0, ge=0)
    part_weight_g: float = Field(0, ge=0)
    hot_runner: bool = False
    slides_per_cavity: int = Field(0, ge=0, le=20)
    lifters_per_cavity: int = Field(0, ge=0, le=20)
    inserts_per_cavity: int = Field(0, ge=0, le=50)


def cavity_layouts(n: int, item_l: float, item_w: float, gap: float) -> list[dict]:
    """Every rows × columns grid that holds n cavities without an empty row."""
    layouts = []
    for rows in range(1, n + 1):
        cols = math.ceil(n / rows)
        if (rows - 1) * cols >= n:
            continue
        layouts.append({
            "rows": rows, "cols": cols, "empty": rows * cols - n,
            "pocket_l": cols * item_l + (cols - 1) * gap,
            "pocket_w": rows * item_w + (rows - 1) * gap,
        })
    return layouts


def select_base(part_type: str, pocket_l: float, pocket_w: float) -> tuple[dict, bool]:
    """Smallest mould base whose insert pocket takes the inserts (either way round)."""
    fits = []
    for base in mould_db.tables()["mould_bases"]:
        if base["part_type"] != part_type:
            continue
        bl, bw = base["max_insert_length_mm"], base["max_insert_width_mm"]
        straight = pocket_l <= bl and pocket_w <= bw
        turned = pocket_l <= bw and pocket_w <= bl
        if straight or turned:
            fits.append((base["length_mm"] * base["width_mm"], base["cost"], base, not straight))
    if not fits:
        raise ValueError(
            f"No {part_type} mould base in the database takes an insert pocket of "
            f"{pocket_l:.0f} × {pocket_w:.0f} mm. Add a larger size under Mould bases, or use fewer cavities."
        )
    _, _, base, turned = min(fits, key=lambda f: (f[0], f[1]))
    return base, turned


def estimate(inp: MouldInput) -> dict:
    db = mould_db.tables()
    rules = mould_db.sizing_rules(inp.part_type)
    missing = [k for k in SIZING_KEYS if k not in rules]
    if missing:
        raise ValueError(f"Sizing rules for {inp.part_type} are missing: {', '.join(missing)}.")
    wall, gap, backing, floor = (rules[k]["value"] for k in SIZING_KEYS)

    each_l = inp.part_length_mm + 2 * wall
    each_w = inp.part_width_mm + 2 * wall
    half_h = inp.part_height_mm / 2 + backing
    # Try every layout and keep the one that needs the smallest standard base;
    # ties go to fewer empty positions, then the squarer pocket.
    options = []
    for lay in cavity_layouts(inp.cavities, each_l, each_w, gap):
        try:
            base, turned = select_base(inp.part_type, lay["pocket_l"], lay["pocket_w"])
        except ValueError:
            continue
        aspect = max(lay["pocket_l"], lay["pocket_w"]) / min(lay["pocket_l"], lay["pocket_w"])
        options.append(((base["length_mm"] * base["width_mm"], base["cost"], lay["empty"], aspect), lay, base, turned))
    if not options:
        smallest = min(cavity_layouts(inp.cavities, each_l, each_w, gap), key=lambda l: max(l["pocket_l"], l["pocket_w"]))
        select_base(inp.part_type, smallest["pocket_l"], smallest["pocket_w"])  # raises with a clear message
    _, layout, base, turned = min(options, key=lambda o: o[0])

    warnings = []
    plate = min(base["a_plate_mm"], base["b_plate_mm"])
    if half_h + floor > plate:
        warnings.append(
            f"Insert height {half_h:.0f} mm + {floor:.0f} mm floor is more than the {plate:.0f} mm A/B plate "
            f"of base {base['size_code']}. Choose thicker plates for this base."
        )

    env = dict(formula.SAMPLE)  # every variable defined, then overwritten below
    env.update(
        cavities=inp.cavities, layout_rows=layout["rows"], layout_cols=layout["cols"],
        part_l=inp.part_length_mm, part_w=inp.part_width_mm, part_h=inp.part_height_mm,
        projected_area_cm2=inp.projected_area_cm2, part_weight_g=inp.part_weight_g,
        insert_each_l=each_l, insert_each_w=each_w, insert_half_h=half_h,
        pocket_l=layout["pocket_l"], pocket_w=layout["pocket_w"],
        base_l=base["length_mm"], base_w=base["width_mm"], base_stack_h=base["stack_height_mm"],
        base_weight_kg=base["weight_kg"], hot_runner=int(inp.hot_runner),
        slides_per_cavity=inp.slides_per_cavity, lifters_per_cavity=inp.lifters_per_cavity,
        inserts_per_cavity=inp.inserts_per_cavity,
    )
    materials = {m["code"]: m for m in db["tool_materials"]}
    processes = {p["code"]: p for p in db["process_rates"]}

    lines = [{
        "element": f"Mould base {base['series']} {base['size_code']}",
        "category": "bought_out", "quantity": 1, "material": "", "weight_each_kg": base["weight_kg"],
        "material_cost": 0, "bought_out_cost": base["cost"], "process": "", "hours": 0, "process_cost": 0,
        "total": base["cost"], "is_example": base["is_example"],
    }]
    for el in db["bom_elements"]:
        if el["part_type"] != inp.part_type:
            continue
        mat = materials.get(el["material_code"])
        proc = processes.get(el["process_code"])
        row_env = env | {"density": mat["density_g_cm3"] if mat else 0}

        def rule(col):
            try:
                return formula.evaluate(el[col], row_env)
            except formula.FormulaError as exc:
                raise ValueError(f"BOM element '{el['element']}', {col}: {exc}") from None

        qty = rule("quantity_rule")
        if qty <= 0:
            continue
        weight = rule("weight_rule")
        hours = rule("hours_rule")
        unit_cost = rule("unit_cost_rule")
        material_cost = qty * weight * (mat["rate_per_kg"] if mat else 0)
        bought = qty * unit_cost
        process_cost = qty * hours * (proc["rate_per_hour"] if proc else 0)
        lines.append({
            "element": el["element"], "category": el["category"], "quantity": round(qty, 3),
            "material": el["material_code"], "weight_each_kg": round(weight, 3),
            "material_cost": round(material_cost, 2), "bought_out_cost": round(bought, 2),
            "process": el["process_code"], "hours": round(qty * hours, 2), "process_cost": round(process_cost, 2),
            "total": round(material_cost + bought + process_cost, 2),
            "is_example": bool(el["is_example"] or (mat and mat["is_example"]) or (proc and proc["is_example"])),
        })

    totals = {k: round(sum(line[k] for line in lines), 2)
              for k in ("material_cost", "bought_out_cost", "process_cost", "hours", "total")}
    sizing_examples = any(r["is_example"] for r in rules.values())
    return {
        "layout": layout | {"each_l": each_l, "each_w": each_w, "half_h": half_h},
        "base": base,
        "base_turned": turned,
        "lines": lines,
        "totals": totals,
        "example_lines": sum(1 for line in lines if line["is_example"]),
        "sizing_rules_are_examples": sizing_examples,
        "warnings": warnings,
    }
