"""Mould / die sizing from the mould database.

    cavities + part size  ->  cavity layout (rows × columns)
    layout + insert walls ->  insert size per cavity and insert pocket
    insert pocket         ->  smallest standard mould base it fits in

The BOM on this mould and its cost (traced, with country rates) are worked out
by the tool cost engine (tool_cost.py). All sizes and walls come from the mould
database, so the result changes when the database is edited, without code changes.
"""

from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import mould_db

SIZING_KEYS = ("insert_wall_mm", "insert_gap_mm", "insert_backing_mm", "plate_floor_mm")


class MouldInput(BaseModel):
    part_type: Literal["plastic", "die_casting", "foundry", "sheet_metal", "eps", "blow"]
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
    machine: Optional[dict] = None          # the machine the tool will run on (machine_spec): the base must suit it


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


def select_base(part_type: str, pocket_l: float, pocket_w: float, suits=None) -> tuple[dict, bool]:
    """Smallest mould base whose insert pocket takes the inserts (either way round) and that suits the typed machine (suits(base) → bool)."""
    fits = []
    for base in mould_db.tables()["mould_bases"]:
        if base["part_type"] != part_type or (suits and not suits(base)):
            continue
        bl, bw = base["max_insert_length_mm"], base["max_insert_width_mm"]
        straight = pocket_l <= bl and pocket_w <= bw
        turned = pocket_l <= bw and pocket_w <= bl
        if straight or turned:
            fits.append((base["length_mm"] * base["width_mm"], base["cost"], base, not straight))
    if not fits:
        raise ValueError(
            f"No {part_type} mould base in the database takes an insert pocket of "
            f"{pocket_l:.0f} × {pocket_w:.0f} mm" + (" that also passes the tie bars, fits the platen and the mould height of the typed machine. Use fewer cavities, a bigger machine, "
                                                      "or add a base under Mould bases" if suits else ". Add a larger size under Mould bases, or use fewer cavities.")
        )
    _, _, base, turned = min(fits, key=lambda f: (f[0], f[1]))
    return base, turned


def size(inp: MouldInput) -> dict:
    """Cavity layout, insert size and the smallest standard mould base (the BOM is priced in tool_cost.py)."""
    from . import machine_spec
    suits = machine_spec.base_constraint(inp.machine)
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
            base, turned = select_base(inp.part_type, lay["pocket_l"], lay["pocket_w"], suits)
        except ValueError:
            continue
        aspect = max(lay["pocket_l"], lay["pocket_w"]) / min(lay["pocket_l"], lay["pocket_w"])
        options.append(((base["length_mm"] * base["width_mm"], base["cost"], lay["empty"], aspect), lay, base, turned))
    if not options:
        smallest = min(cavity_layouts(inp.cavities, each_l, each_w, gap), key=lambda l: max(l["pocket_l"], l["pocket_w"]))
        select_base(inp.part_type, smallest["pocket_l"], smallest["pocket_w"], suits)  # raises with a clear message
    _, layout, base, turned = min(options, key=lambda o: o[0])

    warnings = []
    plate = min(base["a_plate_mm"], base["b_plate_mm"])
    if half_h + floor > plate:
        warnings.append(
            f"Insert height {half_h:.0f} mm + {floor:.0f} mm floor is more than the {plate:.0f} mm A/B plate "
            f"of base {base['size_code']}. Choose thicker plates for this base."
        )
    return {
        "layout": layout | {"each_l": each_l, "each_w": each_w, "half_h": half_h},
        "base": base,
        "base_turned": turned,
        "rules": rules,
        "sizing_rules_are_examples": any(r["is_example"] for r in rules.values()),
        "warnings": warnings,
    }
