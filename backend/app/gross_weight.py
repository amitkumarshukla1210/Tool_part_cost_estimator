"""Stage B: gross weight, material yield and raw-material cost per part.

Works only on Stage A numbers plus the process inputs below, so it does not
need the STEP file again.

Moulding / casting (plastic, die casting, foundry)
    gross    = net × (1 + runner %)          plastic
             = net ÷ casting yield %          die casting, foundry
    returns  = gross − net                    runners, biscuit, overflows, risers
    input    = gross × (1 + process loss %)   purge / start-up / melt loss
    RM cost  = input (kg) × material rate
    credit   = returns (kg) × scrap / returns rate
    net RM   = RM cost − credit

Sheet metal
    blank pitch  = (blank L + gap) × (blank W + gap)
    parts/sheet  = best of the two blank orientations on the sheet
    gross        = sheet weight ÷ parts per sheet
    scrap        = gross − net                skeleton, edge trim, punched holes
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from . import master_data

# Inputs that come from master data when the request leaves them out.
DEFAULT_KEYS = {
    "plastic": ["runner_pct", "process_loss_pct"],
    "die_casting": ["yield_pct", "process_loss_pct"],
    "foundry": ["yield_pct", "process_loss_pct"],
    "sheet_metal": ["sheet_length_mm", "sheet_width_mm", "gap_mm", "edge_mm"],
}


def defaults(part_type: str) -> dict:
    params = master_data.parameters(part_type)
    keys = DEFAULT_KEYS[part_type] + ["currency"]
    return {k: master_data.require(params, k, part_type) for k in keys}


class GrossWeightInput(BaseModel):
    part_type: Literal["plastic", "die_casting", "foundry", "sheet_metal"]
    net_weight_g: float = Field(gt=0)
    density_g_cm3: float = Field(gt=0)
    material_rate_per_kg: float = Field(0, ge=0)
    scrap_rate_per_kg: float = Field(0, ge=0)
    currency: Optional[str] = None

    # Moulding / casting
    runner_pct: Optional[float] = Field(None, ge=0, le=500)
    yield_pct: Optional[float] = Field(None, gt=0, le=100)
    process_loss_pct: Optional[float] = Field(None, ge=0, le=50)

    # Sheet metal
    thickness_mm: Optional[float] = Field(None, gt=0)
    blank_length_mm: Optional[float] = Field(None, gt=0)
    blank_width_mm: Optional[float] = Field(None, gt=0)
    sheet_length_mm: Optional[float] = Field(None, gt=0)
    sheet_width_mm: Optional[float] = Field(None, gt=0)
    gap_mm: Optional[float] = Field(None, ge=0)
    edge_mm: Optional[float] = Field(None, ge=0)

    @model_validator(mode="after")
    def fill_defaults(self):
        for key, value in defaults(self.part_type).items():
            if getattr(self, key) is None:
                setattr(self, key, value)
        if self.part_type == "sheet_metal":
            missing = [k for k in ("thickness_mm", "blank_length_mm", "blank_width_mm") if getattr(self, k) is None]
            if missing:
                raise ValueError(f"Sheet metal needs: {', '.join(missing)}.")
        return self


def grid_fit(area_l: float, area_w: float, item_l: float, item_w: float, gap: float) -> dict:
    """Best straight-grid layout of a rectangle in an area, trying both orientations."""

    def count(il, iw):
        # n items need n × size + (n − 1) gaps
        return int((area_l + gap) // (il + gap)), int((area_w + gap) // (iw + gap))

    options = [count(item_l, item_w), count(item_w, item_l)]
    along, across = max(options, key=lambda o: o[0] * o[1])
    return {"along": along, "across": across, "per_sheet": along * across, "rotated": options.index((along, across)) == 1}


def nest_on_sheet(inp: GrossWeightInput) -> dict:
    """Rectangular grid nesting of the blank on the sheet, both orientations."""
    nest = grid_fit(
        inp.sheet_length_mm - 2 * inp.edge_mm,
        inp.sheet_width_mm - 2 * inp.edge_mm,
        inp.blank_length_mm,
        inp.blank_width_mm,
        inp.gap_mm,
    )
    if nest["per_sheet"] == 0:
        raise ValueError("The blank does not fit on the sheet. Check blank and sheet sizes.")
    return nest


def calculate(inp: GrossWeightInput) -> dict:
    net_g = inp.net_weight_g
    result: dict = {"part_type": inp.part_type, "currency": inp.currency, "net_weight_g": net_g}

    if inp.part_type == "sheet_metal":
        nest = nest_on_sheet(inp)
        sheet_g = inp.sheet_length_mm * inp.sheet_width_mm * inp.thickness_mm / 1000 * inp.density_g_cm3
        blank_g = inp.blank_length_mm * inp.blank_width_mm * inp.thickness_mm / 1000 * inp.density_g_cm3
        gross_g = sheet_g / nest["per_sheet"]
        input_g = gross_g
        result.update(
            sheet_weight_kg=round(sheet_g / 1000, 3),
            blank_weight_g=round(blank_g, 3),
            nesting=nest,
            sheet_utilisation_pct=round(100 * net_g * nest["per_sheet"] / sheet_g, 2),
        )
    else:
        if inp.part_type == "plastic":
            gross_g = net_g * (1 + inp.runner_pct / 100)
        else:
            gross_g = net_g / (inp.yield_pct / 100)
        input_g = gross_g * (1 + inp.process_loss_pct / 100)
        result["process_loss_g"] = round(input_g - gross_g, 3)

    returns_g = gross_g - net_g
    rm_cost = input_g / 1000 * inp.material_rate_per_kg
    credit = returns_g / 1000 * inp.scrap_rate_per_kg

    result.update(
        gross_weight_g=round(gross_g, 3),
        gross_weight_kg=round(gross_g / 1000, 5),
        returns_scrap_g=round(returns_g, 3),
        material_input_g=round(input_g, 3),
        material_yield_pct=round(100 * net_g / input_g, 2),
        rm_cost=round(rm_cost, 4),
        scrap_credit=round(credit, 4),
        net_rm_cost=round(rm_cost - credit, 4),
        inputs=inp.model_dump(),
    )
    return result
