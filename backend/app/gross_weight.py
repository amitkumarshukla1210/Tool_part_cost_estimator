"""Stage B on the Estimate page: gross weight, material yield and RM cost per part.

The calculation is the traced RM engine (rm_cost.py): the formulas and their
inputs are in master data, the material rate is the APPROVED rate-library
version of the producing country for the costing month. Anything you type
(runner %, yield %, a sheet size, even a material rate) replaces that input and
is traced as your input.

The request may name the inputs with their own field (runner_pct, yield_pct,
thickness_mm, material_rate_per_kg, ...) or send them in `given` by their
formula-input variable name. Values estimated from the 3D model (sheet
thickness, flat blank) are listed in `estimated`, so the trace shows them as
coming from the 3D file rather than from you.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from . import costing_setup, register_setup, rm_cost

PART_FIELDS = ("thickness_mm", "blank_length_mm", "blank_width_mm")
# API field -> rate category of the formula input it replaces
RATE_FIELDS = {"material_rate_per_kg": "material", "scrap_rate_per_kg": "material_scrap"}


def defaults(part_type: str) -> dict:
    """Inputs you can type over for this family, with their master-data defaults."""
    out = {i["variable"]: i["default"] for i in rm_cost.overridable(part_type) if i["default"] is not None}
    return out


def inputs(part_type: str) -> list[dict]:
    return rm_cost.overridable(part_type)


def default_country() -> str:
    code = register_setup.settings().get("default_country", "").strip().upper()
    if not code:
        raise rm_cost.RMError("Set default_country in Master data → Part register setup → Register settings.")
    return code


class GrossWeightInput(BaseModel):
    part_type: Literal["plastic", "die_casting", "foundry", "sheet_metal", "eps", "blow"]
    net_weight_g: float = Field(gt=0)
    density_g_cm3: float = Field(gt=0)
    material: str = ""
    country: str = ""
    as_of: Optional[str] = None
    material_rate_per_kg: Optional[float] = Field(None, ge=0)
    scrap_rate_per_kg: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = None  # kept for older callers; the currency is the producing country's

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

    given: dict[str, float] = {}
    estimated: list[str] = []

    @model_validator(mode="after")
    def check_sheet(self):
        if self.part_type == "sheet_metal":
            missing = [k for k in PART_FIELDS if getattr(self, k) is None]
            if missing:
                raise ValueError(f"Sheet metal needs: {', '.join(missing)}.")
        for k, v in self.given.items():
            if v is None or v < 0:
                raise ValueError(f"{k} must be a number of 0 or more.")
        return self


def calculate(inp: GrossWeightInput) -> dict:
    family = inp.part_type
    rows = [r for r in costing_setup.tables()["formula_inputs"] if r["scope"] == rm_cost.scope(family)]
    variables = {r["variable"] for r in rows}
    given = {k: v for k, v in inp.given.items() if k in variables}
    for field, value in inp.model_dump().items():
        if value is None or field in PART_FIELDS + ("net_weight_g", "density_g_cm3") or field in inp.estimated:
            continue
        if field in RATE_FIELDS:
            for r in rows:
                if r["source"] == "rate" and r["category"] == RATE_FIELDS[field]:
                    given[r["variable"]] = value
        elif field in variables and isinstance(value, (int, float)):
            given[field] = value

    cad = {"type": "cad", "note": "Estimated from the uploaded 3D model on the Estimate page"}
    you = {"type": "user", "note": "Typed on the Estimate page"}
    part = {"net_weight_g": {"value": inp.net_weight_g, "unit": "g", "label": "Net part weight",
                             "source": {"type": "cad", "note": "Stage A: CAD volume × density"}},
            "density_g_cm3": {"value": inp.density_g_cm3, "unit": "g/cm³", "label": "Material density",
                              "source": {"type": "user", "note": "Density on the Estimate page"
                                         + (f" (material {inp.material})" if inp.material else "")}}}
    for k in PART_FIELDS:
        v = getattr(inp, k)
        if v is not None:
            part[k] = {"value": v, "unit": "mm", "source": cad if k in inp.estimated else you}
    r = rm_cost.run(family, country=(inp.country or default_country()).upper(), as_of=inp.as_of,
                    material=inp.material, part=part, given=given, given_source=you)

    # Named results kept for older callers of this API (they follow the formula names in master data).
    n = r["named"]
    legacy = {"gross_weight_g": n.get("gross_g"), "returns_scrap_g": n.get("returns_g"),
              "material_input_g": n.get("input_g"), "material_yield_pct": n.get("material_yield_pct"),
              "rm_cost": n.get("rm_cost"), "scrap_credit": -n["scrap_credit"] if "scrap_credit" in n else None,
              "net_rm_cost": n.get("net_rm_cost"), "process_loss_g": n.get("loss_g"),
              "sheet_weight_kg": n["sheet_weight_g"] / 1000 if "sheet_weight_g" in n else None,
              "sheet_utilisation_pct": n.get("utilisation_pct"), "net_weight_g": inp.net_weight_g,
              "part_type": family}
    return r | {k: v for k, v in legacy.items() if v is not None} | {"inputs_given": given}
