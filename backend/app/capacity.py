"""Stage C: number of cavities per tool and number of tools.

Uses the part footprint from Stage A (or the flat blank from Stage B for
sheet metal) plus volume and process inputs.

    available h/yr   = days × shifts × hours per shift × OEE   (OEE used once)
    parts per hour   = annual volume ÷ available h/yr
    cavities needed  = parts per hour × cycle time (s) ÷ 3600
    cavities / tool  = needed, rounded up to a standard layout, but no more
                       than fit on the tool plate or the practical maximum
    tools (capacity) = ceil(cavities needed ÷ cavities per tool)
    tools (life)     = ceil(programme shots ÷ tool life)
    tools to buy     = max of the two above

For sheet metal a "cavity" is a part per stroke and every die set has one
die per operation (blank, pierce, bend, ...).
"""

from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from . import master_data
from .rm_cost import grid_fit

# Inputs that come from master data when the request leaves them out.
COMMON_KEYS = ["annual_volume", "working_days", "shifts_per_day", "hours_per_shift", "programme_years"]
PROCESS_KEYS = ["cycle_time_s", "oee_pct", "max_cavities", "plate_length_mm", "plate_width_mm", "spacing_mm", "tool_life_shots"]


def defaults(part_type: str) -> dict:
    params = master_data.parameters(part_type)
    keys = COMMON_KEYS + PROCESS_KEYS + (["operations"] if part_type == "sheet_metal" else [])
    return {k: master_data.require(params, k, part_type) for k in keys}


TERMS = {
    "plastic": {"cavity": "cavities", "tool": "moulds", "shot": "shots"},
    "die_casting": {"cavity": "cavities", "tool": "dies", "shot": "shots"},
    "foundry": {"cavity": "castings per mould", "tool": "pattern sets", "shot": "moulds"},
    "sheet_metal": {"cavity": "parts per stroke", "tool": "die sets", "shot": "strokes"},
    "eps": {"cavity": "cavities", "tool": "moulds", "shot": "shots"},
    "blow": {"cavity": "cavities", "tool": "blow moulds", "shot": "shots"},
}


def plastic_cycle_estimate(wall_mm: float) -> float:
    """Rule of thumb: cycle = base (fill, open, eject) + cooling factor × wall²."""
    params = master_data.parameters("plastic")
    base = master_data.require(params, "cycle_base_s", "plastic")
    factor = master_data.require(params, "cooling_factor_s_per_mm2", "plastic")
    return round(base + factor * wall_mm**2, 1)


class CapacityInput(BaseModel):
    part_type: Literal["plastic", "die_casting", "foundry", "sheet_metal", "eps", "blow"]
    footprint_length_mm: float = Field(gt=0, description="Part size across the parting plane, or blank length")
    footprint_width_mm: float = Field(gt=0)

    annual_volume: Optional[int] = Field(None, gt=0)
    working_days: Optional[int] = Field(None, gt=0, le=366)
    shifts_per_day: Optional[int] = Field(None, gt=0, le=4)
    hours_per_shift: Optional[float] = Field(None, gt=0, le=24)
    programme_years: Optional[int] = Field(None, gt=0, le=30)

    cycle_time_s: Optional[float] = Field(None, gt=0)
    oee_pct: Optional[float] = Field(None, gt=0, le=100)
    max_cavities: Optional[int] = Field(None, gt=0, le=256)
    plate_length_mm: Optional[float] = Field(None, gt=0)
    plate_width_mm: Optional[float] = Field(None, gt=0)
    spacing_mm: Optional[float] = Field(None, ge=0)
    tool_life_shots: Optional[int] = Field(None, gt=0)
    operations: Optional[int] = Field(None, gt=0, le=20)

    @model_validator(mode="after")
    def fill_defaults(self):
        for key, value in defaults(self.part_type).items():
            if getattr(self, key) is None:
                setattr(self, key, value)
        if self.part_type != "sheet_metal":
            self.operations = 1
        return self


def choose_cavities(part_type: str, needed: float, limit: int) -> int:
    """Smallest allowed count covering the need, never above the limit.

    Allowed counts are the part type's 'standard_cavities' in master data,
    or any whole number when it has none.
    """
    standard = master_data.parameters(part_type).get("standard_cavities") or range(1, limit + 1)
    options = [n for n in standard if n <= limit] or [1]
    return next((n for n in options if n >= needed), options[-1])


def calculate(inp: CapacityInput) -> dict:
    # OEE is applied exactly once: planned hours -> productive hours.
    oee = inp.oee_pct / 100
    planned_hours = inp.working_days * inp.shifts_per_day * inp.hours_per_shift
    hours = planned_hours * oee
    parts_per_hour = inp.annual_volume / hours
    needed = parts_per_hour * inp.cycle_time_s / 3600

    # Cavities that physically fit, with spacing between them and round the edge.
    layout = grid_fit(
        inp.plate_length_mm - 2 * inp.spacing_mm,
        inp.plate_width_mm - 2 * inp.spacing_mm,
        inp.footprint_length_mm,
        inp.footprint_width_mm,
        inp.spacing_mm,
    )
    fit = layout["per_sheet"]
    if fit == 0:
        raise ValueError("The part does not fit on the tool plate. Check the plate size and spacing.")

    limit = min(fit, inp.max_cavities)
    cavities = choose_cavities(inp.part_type, needed, limit)
    if cavities >= math.ceil(needed):
        limited_by = None
    elif fit < inp.max_cavities:
        limited_by = "plate size"
    else:
        limited_by = "maximum cavities"

    tools_capacity = math.ceil(needed / cavities)
    shots_per_year = math.ceil(inp.annual_volume / cavities)
    programme_shots = shots_per_year * inp.programme_years
    tools_life = math.ceil(programme_shots / inp.tool_life_shots)
    tool_sets = max(tools_capacity, tools_life)

    # Machine time booked = pure run time grossed up for OEE losses, compared
    # with the planned (not OEE-reduced) hours of the machines in use.
    machine_hours = shots_per_year * inp.cycle_time_s / 3600 / oee

    return {
        "part_type": inp.part_type,
        "terms": TERMS[inp.part_type],
        "planned_hours_per_year": round(planned_hours, 1),
        "available_hours_per_year": round(hours, 1),
        "required_parts_per_hour": round(parts_per_hour, 2),
        "cavities_needed": round(needed, 3),
        "cavities_fit_on_plate": fit,
        "layout": {k: layout[k] for k in ("along", "across", "rotated")},
        "cavities_per_tool": cavities,
        "limited_by": limited_by,
        "output_per_tool_per_hour": round(cavities * 3600 / inp.cycle_time_s * oee, 1),
        "tools_for_capacity": tools_capacity,
        "shots_per_year": shots_per_year,
        "programme_shots": programme_shots,
        "tools_for_life": tools_life,
        "tool_sets_over_programme": tool_sets,
        "dies_per_set": inp.operations,
        "total_dies": tool_sets * inp.operations,
        "machine_hours_per_year": round(machine_hours, 1),
        "machine_utilisation_pct": round(100 * machine_hours / (planned_hours * tools_capacity), 1),
        "inputs": inp.model_dump(),
    }
