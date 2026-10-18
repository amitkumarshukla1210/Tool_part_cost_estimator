"""Design to Cost: web server for the Part Cost Estimator module (Stages A to C, rate library and MHR, part register).

Run from the repository root:
    uvicorn backend.app.main:app --reload
then open http://127.0.0.1:8000 in a browser.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from .geometry import PART_TYPES, analyze, blank_estimate, load_step, sheet_thickness, tessellate
from . import (capacity, costing_setup, country_rates, file_store, gross_weight, master_data, mould, mould_db, rate_engine, rates,
               register, register_setup, rm_cost, tool_cost, example_values)
from . import projects_db

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
THEME_DIR = Path(__file__).resolve().parents[2] / "theme"
MAX_UPLOAD_MB = 100

app = FastAPI(title="Design to Cost — Part Cost Estimator", version="0.9.0 (tool cost engine)")


@app.get("/api/part-types")
def part_types():
    return PART_TYPES


@app.post("/api/analyze")
async def analyze_part(
    file: UploadFile = File(...),
    part_type: str = Form(...),
    density: float = Form(..., description="Material density in g/cm³"),
):
    if not file.filename or not file.filename.lower().endswith((".step", ".stp")):
        raise HTTPException(400, "Please upload a .step or .stp file.")
    if part_type not in PART_TYPES:
        raise HTTPException(400, f"Part type must be one of: {', '.join(PART_TYPES)}.")
    if density <= 0:
        raise HTTPException(400, "Density must be greater than zero.")

    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD_MB} MB.")

    # The STEP reader needs a real file on disk.
    fd, tmp_path = tempfile.mkstemp(suffix=".step")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        try:
            shape = load_step(tmp_path)
        except Exception as exc:  # OCC raises a variety of exception types
            raise HTTPException(422, f"Could not read STEP file: {exc}") from exc
    finally:
        os.remove(tmp_path)

    vertices, triangles = tessellate(shape)
    metrics = analyze(shape, part_type, density, mesh=(vertices, triangles))

    # Most common wall: sheet thickness for sheet metal, wall for mouldings.
    wall = sheet_thickness(shape)
    sheet = None
    if part_type == "sheet_metal":
        sheet = {"thickness_mm": wall, "blank_mm": blank_estimate(metrics.volume_mm3, metrics.bbox_mm, wall)}

    # Part size across the parting plane, i.e. the two axes other than the pull.
    across = sorted((v for a, v in metrics.bbox_axes_mm.items() if a != metrics.pull_direction), reverse=True)
    process = {
        "wall_thickness_mm": wall,
        "footprint_mm": {"length": across[0], "width": across[1]},
        "cycle_time_s_estimate": capacity.plastic_cycle_estimate(wall) if part_type == "plastic" else None,
    }

    return {
        "file_name": file.filename,
        "part_type_label": PART_TYPES[part_type],
        "metrics": metrics.to_dict(),
        "sheet_metal": sheet,
        "process": process,
        # Flat arrays are what three.js BufferGeometry expects.
        "mesh": {
            "positions": [c for v in vertices for c in v],
            "indices": [i for t in triangles for i in t],
        },
    }


@app.get("/api/gross-weight/defaults")
def gross_weight_defaults():
    """Per part type: the master-data defaults of the inputs you can type over, and the list of those inputs."""
    return {pt: gross_weight.defaults(pt) for pt in PART_TYPES}


@app.get("/api/rm/meta")
def rm_meta():
    """Choices for the RM section of the Estimate page and the part panel (all from master data)."""
    return {"default_country": gross_weight.default_country(),
            "countries": [{"code": c["code"], "name": c["name"], "currency": c["currency"]}
                          for c in costing_setup.tables()["countries"]],
            "inputs": {pt: gross_weight.inputs(pt) for pt in PART_TYPES},
            "month": rates.current_month()}


@app.post("/api/gross-weight")
def gross_weight_calc(inp: gross_weight.GrossWeightInput):
    try:
        return gross_weight.calculate(inp)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/capacity/defaults")
def capacity_defaults():
    return {"by_part_type": {pt: capacity.defaults(pt) for pt in PART_TYPES}, "terms": capacity.TERMS}


@app.post("/api/capacity")
def capacity_calc(inp: capacity.CapacityInput):
    try:
        return capacity.calculate(inp)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/master-data")
def master_data_get():
    return master_data.tables()


@app.put("/api/master-data")
def master_data_put(data: dict):
    master_data.write(data)
    return master_data.tables()


@app.get("/api/master-data/download")
def master_data_download():
    return Response(
        master_data.path().read_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="master_data.xlsx"'},
    )


@app.post("/api/master-data/upload")
async def master_data_upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Please upload an Excel .xlsx file.")
    notes = master_data.replace_from_upload(await file.read())
    return master_data.tables() | ({"_notes": notes} if notes else {})


@app.get("/api/mould-db/schema")
def mould_db_schema():
    return mould_db.schema()


@app.get("/api/mould-db")
def mould_db_get():
    return mould_db.tables()


@app.put("/api/mould-db")
def mould_db_put(data: dict):
    mould_db.write(data)
    return mould_db.tables()


@app.get("/api/mould-db/download")
def mould_db_download():
    return Response(
        mould_db.to_excel(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="mould_db.xlsx"'},
    )


@app.post("/api/mould-db/upload")
async def mould_db_upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Please upload an Excel .xlsx file.")
    mould_db.from_excel(await file.read())
    return mould_db.tables()


@app.post("/api/mould/estimate")
def mould_estimate(inp: mould.MouldInput):
    """Mould size only (layout, inserts, base). The priced BOM is POST /api/tool-cost."""
    try:
        return mould.size(inp)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/examples")
def examples_checklist(as_of: Optional[str] = None):
    """Every value still marked EXAMPLE: library rates by category and country, master-data rows by table."""
    return example_values.checklist(as_of)


@app.get("/api/examples/export.xlsx")
def examples_excel(as_of: Optional[str] = None):
    return _xlsx(example_values.to_excel(as_of), "replace_example_values.xlsx")


class ReplaceRateIn(BaseModel):
    rate_id: int
    value: Optional[float] = None   # None = keep the value, just confirm it is real
    source: str = ""
    comment: str = ""


@app.post("/api/examples/rate")
def examples_replace_rate(inp: ReplaceRateIn):
    return example_values.replace_rate(inp.rate_id, inp.value, inp.source, inp.comment)


class ReplaceRowIn(BaseModel):
    set: str
    table: str
    key: dict
    value: Optional[float] = None   # None = keep the row, just clear its Example flag


@app.post("/api/examples/row")
def examples_replace_row(inp: ReplaceRowIn):
    return example_values.replace_row(inp.set, inp.table, inp.key, inp.value)


@app.get("/api/tool-cost/meta")
def tool_cost_meta():
    return {"default_country": tool_cost.default_country(), "part_types": list(tool_cost.PART_TYPES),
            "later": tool_cost.LATER, "month": rates.current_month(),
            "countries": [{"code": c["code"], "name": c["name"], "currency": c["currency"]}
                          for c in costing_setup.tables()["countries"]]}


@app.post("/api/tool-cost")
def tool_cost_calc(inp: tool_cost.ToolInput):
    """Traced tool cost of a mould / die (Estimate page): BOM, processes with MHR + labour, trial, overhead, profit, ..."""
    return tool_cost.run(inp)


@app.post("/api/tool-cost/export.xlsx")
def tool_cost_excel(inp: tool_cost.ToolInput):
    return _xlsx(register.tool_cost_excel(tool_cost.run(inp)), "tool_cost.xlsx")


@app.post("/api/tool-cost/export.pdf")
def tool_cost_pdf(inp: tool_cost.ToolInput):
    from .pdf_report import tool_cost_pdf as pdf
    return Response(pdf(tool_cost.run(inp)), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="tool_cost.pdf"'})


# ---------- costing setup: countries, machines, labour grades, formulas ----------

@app.get("/api/costing-setup/schema")
def costing_setup_schema():
    return costing_setup.schema()


@app.get("/api/costing-setup")
def costing_setup_get():
    return costing_setup.tables()


@app.put("/api/costing-setup")
def costing_setup_put(data: dict):
    costing_setup.write(data)
    return costing_setup.tables()


@app.get("/api/costing-setup/download")
def costing_setup_download():
    return _xlsx(costing_setup.to_excel(), "costing_setup.xlsx")


@app.post("/api/costing-setup/upload")
async def costing_setup_upload(file: UploadFile = File(...)):
    _require_xlsx(file)
    costing_setup.from_excel(await file.read())
    return costing_setup.tables()


# ---------- rate library ----------

class RateIn(BaseModel):
    category: str
    item: str
    country: str = ""
    value: float
    unit: str = ""
    currency: str = ""
    month: Optional[str] = None
    source: str = ""
    source_url: str = ""
    fetched_date: str = ""
    comment: str = ""
    is_example: bool = False
    approve: bool = False


class StatusIn(BaseModel):
    ids: list[int]
    status: str
    comment: str = ""


@app.get("/api/rates")
def rates_current(as_of: Optional[str] = None, country: Optional[str] = None, category: Optional[str] = None):
    return {"as_of": as_of or rates.current_month(), "rows": rates.current(as_of, country, category)}


@app.get("/api/rates/grid")
def rates_grid(as_of: Optional[str] = None):
    """Material and process rates as an item × country grid (roadmap stage 3)."""
    return country_rates.grid(as_of)


class ProposeIn(BaseModel):
    month: Optional[str] = None


@app.post("/api/rates/propose-from-index")
def rates_propose(inp: ProposeIn):
    """Drafts for countries that have no rate yet: base-country value × country index ÷ forex."""
    country_rates.sync_base(inp.month)
    return country_rates.propose(inp.month)


@app.get("/api/rates/history")
def rates_history(category: str, item: str, country: str = ""):
    return rates.history(category, item, country)


@app.post("/api/rates")
def rates_create(inp: RateIn):
    data = inp.model_dump()
    approve = data.pop("approve")
    return rates.create(data, approve=approve)


@app.put("/api/rates/{rate_id}")
def rates_update(rate_id: int, inp: RateIn):
    data = inp.model_dump()
    approve = data.pop("approve")
    return rates.update(rate_id, data, approve=approve)


@app.post("/api/rates/status")
def rates_status(inp: StatusIn):
    return rates.set_status(inp.ids, inp.status, inp.comment)


@app.get("/api/rates/review")
def rates_review():
    return rates.review()


@app.get("/api/settings")
def settings_get():
    return rates.settings()


@app.put("/api/settings")
def settings_put(data: dict):
    return rates.save_settings(data)


@app.get("/api/rates/download")
def rates_download():
    return _xlsx(rates.to_excel(), "rate_library.xlsx")


@app.post("/api/rates/upload")
async def rates_upload(file: UploadFile = File(...)):
    _require_xlsx(file)
    created = rates.import_excel(await file.read())
    return {"drafts_created": len(created)}


# ---------- machine hour rates and labour rates ----------

@app.get("/api/mhr")
def mhr_overview(country: str = "IN", as_of: Optional[str] = None):
    return rate_engine.overview(country.upper(), as_of)


@app.get("/api/mhr/{machine_id}")
def mhr_one(machine_id: str, country: str = "IN", as_of: Optional[str] = None):
    return rate_engine.mhr(machine_id, country.upper(), as_of)


@app.get("/api/labour-rate/{grade}")
def labour_one(grade: str, country: str = "IN", as_of: Optional[str] = None):
    return rate_engine.labour_rate(grade, country.upper(), as_of)


# ---------- part register: setup ----------

@app.get("/api/register-setup/schema")
def register_setup_schema():
    return register_setup.schema()


@app.get("/api/register-setup")
def register_setup_get():
    return register_setup.tables()


@app.put("/api/register-setup")
def register_setup_put(data: dict):
    register_setup.write(data)
    return register_setup.tables()


@app.get("/api/register-setup/download")
def register_setup_download():
    return _xlsx(register_setup.to_excel(), "part_register_setup.xlsx")


@app.post("/api/register-setup/upload")
async def register_setup_upload(file: UploadFile = File(...)):
    _require_xlsx(file)
    register_setup.from_excel(await file.read())
    return register_setup.tables()


@app.get("/api/register-meta")
def register_meta():
    """Choices for the register pages, all from master data."""
    return {
        "processes": list(register_setup.processes().values()),
        "statuses": register_setup.statuses(),
        "sourcing": list(register_setup.sourcing().values()),
        "materials": [m["material"] for m in master_data.tables()["Materials"]],
        "insert_materials": list(register_setup.insert_materials().values()),
        "insert_shapes": list(register_setup.insert_shapes().values()),
        "insert_default_sourcing": register_setup.settings()["insert_default_sourcing"],
        "part_code_pattern": register_setup.settings()["part_code_pattern"],
    }


class SuggestIn(BaseModel):
    metrics: Optional[dict] = None
    material: str = ""
    insert_count: float = 0


@app.post("/api/suggest-process")
def suggest_process(inp: SuggestIn):
    """Process suggestion with its reason: material first, then geometry rules, then inserts."""
    return register.suggest_process(inp.metrics, inp.material, inp.insert_count)


# ---------- part register: projects & variants ----------

@app.get("/api/projects")
def projects_list():
    return register.list_projects()


@app.post("/api/projects")
def projects_create(data: dict):
    return register.create_project(data)


@app.get("/api/projects/{project_id}")
def projects_get(project_id: int):
    return register.get_project(project_id)


@app.put("/api/projects/{project_id}")
def projects_update(project_id: int, data: dict):
    return register.update_project(project_id, data)


@app.post("/api/projects/{project_id}/variants")
def variants_create(project_id: int, data: dict):
    return register.create_variant(project_id, data)


@app.put("/api/variants/{variant_id}")
def variants_update(variant_id: int, data: dict):
    return register.update_variant(variant_id, data)


@app.get("/api/variants/{variant_id}/bom")
def variants_bom(variant_id: int):
    return register.variant_bom(variant_id)


@app.get("/api/projects/{project_id}/dashboard")
def projects_dashboard(project_id: int):
    return register.dashboard(project_id)


@app.get("/api/projects/{project_id}/dashboard.pdf")
def projects_dashboard_pdf(project_id: int):
    code = register.get_project(project_id)["code"]
    return Response(register.export_dashboard_pdf(project_id), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{code}_project_summary.pdf"'})


# ---------- part register: parts ----------

def _filters(q, project_id, process, status, sourcing, rev, file_missing, target_min, target_max,
             rm_min=None, rm_max=None, rm_missing=None, tool_min=None, tool_max=None, tool_missing=None):
    flag = lambda v: None if v in (None, "") else v.lower() in ("1", "true", "yes")
    return dict(q=q, project_id=project_id, process=process, status=status, sourcing=sourcing, rev=rev,
                file_missing=flag(file_missing), target_min=target_min, target_max=target_max,
                rm_min=rm_min, rm_max=rm_max, rm_missing=flag(rm_missing), tool_min=tool_min, tool_max=tool_max,
                tool_missing=flag(tool_missing))


@app.get("/api/parts")
def parts_search(q: str = "", project_id: Optional[int] = None, process: str = "", status: str = "", sourcing: str = "",
                 rev: str = "", file_missing: Optional[str] = None, target_min: Optional[float] = None,
                 target_max: Optional[float] = None, rm_min: Optional[float] = None, rm_max: Optional[float] = None,
                 rm_missing: Optional[str] = None, tool_min: Optional[float] = None, tool_max: Optional[float] = None,
                 tool_missing: Optional[str] = None, sort: str = "part_code", limit: int = 50, offset: int = 0):
    return register.search(**_filters(q, project_id, process, status, sourcing, rev, file_missing, target_min, target_max,
                                      rm_min, rm_max, rm_missing, tool_min, tool_max, tool_missing),
                           sort=sort, limit=limit, offset=offset)


@app.get("/api/parts/export.xlsx")
def parts_export(q: str = "", project_id: Optional[int] = None, process: str = "", status: str = "", sourcing: str = "",
                 rev: str = "", file_missing: Optional[str] = None, target_min: Optional[float] = None,
                 target_max: Optional[float] = None, rm_min: Optional[float] = None, rm_max: Optional[float] = None,
                 rm_missing: Optional[str] = None, tool_min: Optional[float] = None, tool_max: Optional[float] = None,
                 tool_missing: Optional[str] = None):
    return _xlsx(register.export_parts_excel(**_filters(q, project_id, process, status, sourcing, rev, file_missing,
                                                         target_min, target_max, rm_min, rm_max, rm_missing,
                                                         tool_min, tool_max, tool_missing)),
                 "part_register.xlsx")


@app.get("/api/parts/{part_id}")
def parts_get(part_id: int):
    return register.part_detail(part_id)


@app.put("/api/parts/{part_id}")
def parts_update(part_id: int, data: dict):
    return register.update_part(part_id, data)


@app.post("/api/parts/{part_id}/inserts")
def parts_link_insert(part_id: int, data: dict):
    return register.link_insert(part_id, data)


@app.delete("/api/parts/{part_id}/inserts/{link_id}")
def parts_unlink_insert(part_id: int, link_id: int):
    return register.unlink_insert(part_id, link_id)


@app.get("/api/parts/{part_id}/trace")
def parts_trace(part_id: int, revision_id: Optional[int] = None):
    return register.revision_trace(part_id, revision_id)


@app.get("/api/parts/{part_id}/rm-cost")
def parts_rm_versions(part_id: int):
    return register.rm_versions(part_id)


@app.post("/api/parts/{part_id}/rm-cost")
def parts_rm_calculate(part_id: int, data: dict):
    """Calculate (or recalculate with the latest approved rates). With `rm_inputs`, `country` or `costing_month`
    they are saved on the part first (this is what "Save to part" on the Estimate page sends)."""
    reason = str(data.get("reason") or "recalculated by you").strip()
    if any(k in data for k in ("rm_inputs", "country", "costing_month")):
        res = register.set_rm_inputs(part_id, data.get("rm_inputs"), data.get("country"), data.get("costing_month"), reason)
        return res
    return register.compute_rm(part_id, reason) | {"part": register.part_detail(part_id)}


@app.get("/api/parts/{part_id}/rm-cost/trace")
def parts_rm_trace(part_id: int, version: Optional[int] = None):
    return register.rm_trace(part_id, version)


@app.get("/api/parts/{part_id}/rm-cost/export.xlsx")
def parts_rm_excel(part_id: int, version: Optional[int] = None):
    return _xlsx(register.export_rm_excel(part_id, version), f"rm_cost_part_{part_id}.xlsx")


@app.get("/api/parts/{part_id}/rm-cost/export.pdf")
def parts_rm_pdf(part_id: int, version: Optional[int] = None):
    return Response(register.export_rm_pdf(part_id, version), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="rm_cost_part_{part_id}.pdf"'})


@app.post("/api/projects/{project_id}/rm-cost/recalculate")
def projects_rm_recalculate(project_id: int):
    return register.recalculate_project(project_id)


@app.get("/api/parts/{part_id}/concept")
def parts_concept(part_id: int):
    """Mould / die concept v1: opening direction, undercuts -> slides / lifters, proposals (roadmap stage 5)."""
    try:
        return register.mould_concept(part_id)
    except register.ToolNotApplicable as exc:
        raise HTTPException(400, str(exc)) from None


class StatusChangeIn(BaseModel):
    status: str
    comment: str = ""


@app.get("/api/parts/{part_id}/design-loop")
def parts_design_loop(part_id: int):
    return register.design_loop(part_id)


@app.post("/api/parts/{part_id}/status")
def parts_status(part_id: int, inp: StatusChangeIn):
    register.set_status(part_id, inp.status, inp.comment)
    return register.design_loop(part_id)


@app.get("/api/parts/{part_id}/piece-cost")
def parts_piece_cost(part_id: int):
    """Part cost: latest stored version, versions, outdated flag and the live (traced) result (roadmap stage 8)."""
    return register.piece_summary(part_id)


@app.post("/api/parts/{part_id}/piece-cost")
def parts_piece_compute(part_id: int, data: dict):
    """Store a new part cost version. With `piece_inputs` they are saved on the part first."""
    reason = data.get("reason") or "calculated"
    if "piece_inputs" in data:
        return register.set_piece_inputs(part_id, data["piece_inputs"], reason)
    return register.compute_piece(part_id, reason)


@app.get("/api/parts/{part_id}/piece-cost/trace")
def parts_piece_trace(part_id: int, version: Optional[int] = None):
    return register.piece_trace(part_id, version)


@app.get("/api/parts/{part_id}/piece-cost/export.xlsx")
def parts_piece_xlsx(part_id: int, version: Optional[int] = None):
    return _xlsx(register.piece_excel(part_id, version), f"part_cost_{part_id}.xlsx")


@app.get("/api/parts/{part_id}/piece-cost/export.pdf")
def parts_piece_pdf(part_id: int, version: Optional[int] = None):
    return Response(register.piece_pdf(part_id, version), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="part_cost_{part_id}.pdf"'})


@app.get("/api/parts/{part_id}/simulation")
def parts_simulation(part_id: int):
    """Simulation & analysis v1: maps, cycle time, clamp force, machine, corrections required (roadmap stage 6)."""
    try:
        return register.simulation_result(part_id)
    except register.ToolNotApplicable as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/parts/{part_id}/simulation/report.pdf")
def parts_simulation_pdf(part_id: int):
    try:
        content = register.simulation_pdf(part_id)
    except register.ToolNotApplicable as exc:
        raise HTTPException(400, str(exc)) from None
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="simulation_part_{part_id}.pdf"'})


@app.get("/api/parts/{part_id}/tool-cost")
def parts_tool_versions(part_id: int):
    return register.tool_versions(part_id)


@app.post("/api/parts/{part_id}/tool-cost")
def parts_tool_calculate(part_id: int, data: dict):
    """Calculate (or recalculate with the latest approved rates). With `tool_inputs` or `tool_country` they are saved
    on the part first (the part panel's Tool features and the Estimate page's "Save to part")."""
    reason = str(data.get("reason") or "recalculated by you").strip()
    if any(k in data for k in ("tool_inputs", "tool_country")):
        return register.set_tool_inputs(part_id, data.get("tool_inputs"), data.get("tool_country"), reason)
    return register.compute_tool(part_id, reason) | {"part": register.part_detail(part_id)}


@app.get("/api/parts/{part_id}/tool-cost/trace")
def parts_tool_trace(part_id: int, version: Optional[int] = None):
    return register.tool_trace(part_id, version)


@app.get("/api/parts/{part_id}/tool-cost/export.xlsx")
def parts_tool_excel(part_id: int, version: Optional[int] = None):
    return _xlsx(register.export_tool_excel(part_id, version), f"tool_cost_part_{part_id}.xlsx")


@app.get("/api/parts/{part_id}/tool-cost/export.pdf")
def parts_tool_pdf(part_id: int, version: Optional[int] = None):
    return Response(register.export_tool_pdf(part_id, version), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="tool_cost_part_{part_id}.pdf"'})


@app.post("/api/projects/{project_id}/tool-cost/recalculate")
def projects_tool_recalculate(project_id: int):
    return register.recalculate_project_tools(project_id)


@app.post("/api/parts/{part_id}/revisions")
async def parts_new_revision(part_id: int, file: UploadFile = File(...), rev: str = Form(""), change_note: str = Form("")):
    if not (file.filename or "").lower().endswith((".step", ".stp")):
        raise HTTPException(400, "Please upload a .step or .stp file.")
    return register.new_revision_from_upload(part_id, await file.read(), file.filename, rev, change_note)


@app.get("/api/files/{file_id}")
def files_get(file_id: int):
    from sqlalchemy import select
    with projects_db.engine().connect() as conn:
        row = conn.execute(select(projects_db.files).where(projects_db.files.c.id == file_id)).mappings().first()
    if not row:
        raise HTTPException(404, "File not found.")
    path = file_store.path_of(dict(row))
    if not path.exists():
        raise HTTPException(404, f"The file is registered but missing from the storage folder ({row['stored_path']}).")
    inline = row["kind"] == "thumbnail"
    return FileResponse(path, filename=None if inline else row["original_name"],
                        media_type="image/png" if inline else "application/octet-stream")


# ---------- part register: import ----------

class CommitIn(BaseModel):
    project_id: int
    variant_id: Optional[int] = None
    rev: str = ""
    change_note: str = ""
    items: dict = {}


@app.post("/api/import/step")
async def import_step(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith((".step", ".stp")):
        raise HTTPException(400, "Please upload a .step or .stp file.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD_MB} MB.")
    return register.import_preview(data, file.filename)


@app.get("/api/import/{token}/thumb/{key}")
def import_thumb(token: str, key: str):
    return FileResponse(register.import_thumbnail(token, key), media_type="image/png")


@app.post("/api/import/{token}/commit")
def import_commit(token: str, inp: CommitIn):
    return register.import_commit(token, inp.project_id, inp.variant_id, inp.items, inp.rev, inp.change_note)


@app.get("/api/import/template.xlsx")
def import_template():
    return _xlsx(register.excel_template(), "part_register_template.xlsx")


@app.post("/api/import/excel")
async def import_excel(project_id: int = Form(...), excel: UploadFile = File(...),
                       files: list[UploadFile] = File(default=[])):
    _require_xlsx(excel)
    uploads = [(f.filename or "", await f.read()) for f in files if f.filename]
    return register.bulk_upload(project_id, await excel.read(), uploads)


def _xlsx(content: bytes, name: str) -> Response:
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _require_xlsx(file: UploadFile) -> None:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Please upload an Excel .xlsx file.")


@app.exception_handler(rm_cost.RMError)
@app.exception_handler(tool_cost.ToolCostError)
@app.exception_handler(example_values.ExampleError)
@app.exception_handler(master_data.MasterDataError)
@app.exception_handler(mould_db.MouldDbError)
@app.exception_handler(costing_setup.SetupError)
@app.exception_handler(rates.RateError)
@app.exception_handler(rate_engine.EngineError)
@app.exception_handler(register.RegisterError)
@app.exception_handler(register_setup.RegisterSetupError)
def master_data_error(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/master-data/examples")
def examples_page():
    return FileResponse(FRONTEND_DIR / "examples.html")


@app.get("/master-data")
def master_data_page():
    return FileResponse(FRONTEND_DIR / "master-data.html")


@app.get("/rates")
def rates_page():
    return FileResponse(FRONTEND_DIR / "rates.html")


@app.get("/dashboard")
def dashboard_page():
    return FileResponse(FRONTEND_DIR / "dashboard.html")


@app.get("/parts")
def parts_page():
    return FileResponse(FRONTEND_DIR / "parts.html")


@app.get("/import")
def import_page():
    return FileResponse(FRONTEND_DIR / "import.html")


@app.get("/help")
def help_page():
    return FileResponse(FRONTEND_DIR / "help.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/theme", StaticFiles(directory=THEME_DIR), name="theme")
