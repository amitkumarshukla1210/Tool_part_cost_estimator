"""Design to Cost: web server for the Part Cost Estimator module (Stages A to C, rate library and MHR, part register).

Run from the repository root:
    uvicorn backend.app.main:app --reload
then open http://127.0.0.1:8000 in a browser.
"""

from __future__ import annotations

import os
from datetime import datetime
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from .geometry import PART_TYPES, analyze, blank_estimate, load_step, sheet_thickness, tessellate
from . import bom_extract as bom_extract_mod
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
        from .geometry import developed_blank
        db_ = developed_blank(shape, metrics.volume_mm3, metrics.bbox_mm, wall)
        sheet = {"thickness_mm": wall, "blank_mm": {"length": db_["length"], "width": db_["width"]},
                 "blank_method": db_["method"], "blank_options": db_["options"]}

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


@app.get("/api/rates/updates")
def rates_updates():
    """Log of the monthly rate update runs (roadmap stage 12)."""
    from . import rate_update
    return {"runs": rate_update.runs()}


@app.post("/api/rates/fetch-now")
def rates_fetch_now():
    """Fetch the free official sources now; everything arrives as Drafts on the Rate review page."""
    from . import rate_update
    return rate_update.run_update(user=register.user())


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


# ---------- drawing settings: logo, company, signatures (roadmap stage 27) ----------

DRAWING_KEYS = ("drawing_company", "drawing_projection", "drawing_drawn_by", "drawing_checked_by", "drawing_approved_by",
                "drawing_notes")


@app.get("/api/register-setup/drawing")
def drawing_settings_get():
    s = register_setup.settings()
    rows = {r["key"]: r for r in register_setup.tables()["register_settings"]}
    return {"settings": {k: s.get(k, "") for k in DRAWING_KEYS}, "labels": {k: (rows.get(k) or {}).get("description", k) for k in DRAWING_KEYS},
            "logo": s.get("drawing_logo") or "default"}


@app.put("/api/register-setup/drawing")
def drawing_settings_put(data: dict):
    t = register_setup.tables()
    have = {r["key"]: r for r in t["register_settings"]}
    for k in DRAWING_KEYS:
        if k in data:
            v = str(data[k]).strip() or "-"
            if k in have:
                have[k]["value"] = v
            else:
                t["register_settings"].append({"key": k, "value": v, "description": f"Drawings: {k}"})
    try:
        register_setup.write(t)
    except register_setup.RegisterSetupError as exc:
        raise HTTPException(400, str(exc)) from None
    return drawing_settings_get()


@app.post("/api/register-setup/drawing/logo")
async def drawing_logo_upload(file: UploadFile = File(...)):
    from . import drawing_style
    try:
        drawing_style.save_logo(await file.read())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return drawing_settings_get()


@app.delete("/api/register-setup/drawing/logo")
def drawing_logo_reset():
    from . import drawing_style
    drawing_style.reset_logo()
    return drawing_settings_get()


@app.get("/api/drawing-logo.png")
def drawing_logo():
    from . import drawing_style
    return Response(drawing_style.logo_path().read_bytes(), media_type="image/png", headers={"Cache-Control": "no-store"})


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


@app.delete("/api/projects/{project_id}")
def projects_delete(project_id: int, confirm: str = ""):
    """Delete a project and its parts; `confirm` must be the project code. A backup ZIP is made first."""
    return register.delete_project(project_id, confirm)


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


@app.get("/api/projects/{project_id}/leader")
def projects_leader(project_id: int):
    """Project leader view: BOM cost vs target, CAPEX, CAPEX plan, open corrections (roadmap stage 13)."""
    from . import leader
    return leader.view(project_id)


@app.get("/api/projects/{project_id}/leader.xlsx")
def projects_leader_xlsx(project_id: int):
    from . import leader
    return _xlsx(leader.to_excel(project_id), f"{register.get_project(project_id)['code']}_project_leader.xlsx")


@app.get("/api/projects/{project_id}/leader.pdf")
def projects_leader_pdf(project_id: int):
    from . import leader
    return Response(leader.to_pdf(project_id), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{register.get_project(project_id)["code"]}_project_leader.pdf"'})


@app.post("/api/projects/{project_id}/piece-cost/recalculate")
def projects_piece_recalculate(project_id: int):
    from . import leader
    return leader.recalculate_pieces(project_id)


@app.post("/api/projects/{project_id}/capex/build")
def projects_capex_build(project_id: int):
    from . import leader
    return leader.build_plan(project_id)


@app.post("/api/projects/{project_id}/capex")
def projects_capex_add(project_id: int, data: dict):
    from . import leader
    return leader.add_item(project_id, data)


@app.put("/api/capex/{item_id}")
def capex_update(item_id: int, data: dict):
    from . import leader
    return leader.update_item(item_id, data)


@app.delete("/api/capex/{item_id}")
def capex_delete(item_id: int):
    from . import leader
    return leader.delete_item(item_id)


# ---------- harness and PCB BOM extraction (roadmap stage 14) ----------

def _bom(fn, *a):
    from . import bom_extract
    try:
        return fn(*a)
    except bom_extract.ExtractError as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/bom-extracts")
def bom_extracts(project_id: Optional[int] = None):
    from . import bom_extract
    return bom_extract.list_all(project_id)


@app.post("/api/bom-extracts")
async def bom_extract_create(file: UploadFile = File(...), cpl: Optional[UploadFile] = File(None), name: str = Form(""),
                             project_id: Optional[int] = Form(None), layers: str = Form(""), width_mm: str = Form(""),
                             height_mm: str = Form(""), thickness_mm: str = Form("")):
    from . import bom_extract
    typed = {k: bom_extract._num(v) for k, v in (("layers", layers), ("width_mm", width_mm), ("height_mm", height_mm), ("thickness_mm", thickness_mm)) if v}
    cpl_part = (await cpl.read(), cpl.filename) if cpl and cpl.filename else None
    content = await file.read()
    return _bom(bom_extract.create, content, file.filename or "upload", name, project_id, typed, cpl_part)


@app.get("/api/bom-extract-tools")
def bom_extract_tools():
    """Which optional external tools are installed (Tesseract for scans, a DWG converter) and how to install the rest."""
    from . import external
    return external.tools_status()


@app.get("/api/bom-extracts/{eid}")
def bom_extract_get(eid: int):
    from . import bom_extract
    return _bom(bom_extract.get, eid)


@app.post("/api/bom-extracts/{eid}/lines")
def bom_extract_line_add(eid: int, data: dict):
    from . import bom_extract
    return _bom(bom_extract.save_line, eid, None, data)


@app.put("/api/bom-extracts/{eid}/lines/{line_id}")
def bom_extract_line_edit(eid: int, line_id: int, data: dict):
    from . import bom_extract
    return _bom(bom_extract.save_line, eid, line_id, data)


@app.delete("/api/bom-extracts/{eid}/lines/{line_id}")
def bom_extract_line_delete(eid: int, line_id: int):
    from . import bom_extract
    return _bom(bom_extract.delete_line, eid, line_id)


@app.post("/api/bom-extracts/{eid}/status")
def bom_extract_status(eid: int, data: dict):
    from . import bom_extract
    return _bom(bom_extract.set_status, eid, data.get("status", ""))


@app.delete("/api/bom-extracts/{eid}")
def bom_extract_delete(eid: int):
    from . import bom_extract
    return _bom(bom_extract.delete, eid)


@app.get("/api/bom-extracts/{eid}/export.xlsx")
def bom_extract_xlsx(eid: int):
    from . import bom_extract
    return _xlsx(_bom(bom_extract.to_excel, eid), f"bom_extract_{eid}.xlsx")


def _electro(eid: int, country: Optional[str], month: Optional[str]) -> dict:
    from . import electro_cost
    try:
        return electro_cost.run(eid, country, month)
    except (electro_cost.ElectroError, bom_extract_mod.ExtractError, rates.RateError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/bom-extracts/{eid}/cost")
def bom_extract_cost(eid: int, country: Optional[str] = None, month: Optional[str] = None):
    """Cost per harness / per board from a BOM extract (roadmap stage 15)."""
    return _electro(eid, country, month)


@app.get("/api/bom-extracts/{eid}/cost.xlsx")
def bom_extract_cost_xlsx(eid: int, country: Optional[str] = None, month: Optional[str] = None):
    from . import electro_cost
    return _xlsx(electro_cost.to_excel(_electro(eid, country, month)), f"electro_cost_{eid}.xlsx")


@app.get("/api/bom-extracts/{eid}/cost.pdf")
def bom_extract_cost_pdf(eid: int, country: Optional[str] = None, month: Optional[str] = None):
    from . import electro_cost
    return Response(electro_cost.to_pdf(_electro(eid, country, month)), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="electro_cost_{eid}.pdf"'})


@app.get("/bom-extract")
def bom_extract_page():
    return FileResponse(FRONTEND_DIR / "bom.html")


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


@app.delete("/api/parts/{part_id}")
def parts_delete(part_id: int, confirm: str = ""):
    """Delete a part from the register; `confirm` must be the part code. A backup ZIP is made first."""
    return register.delete_part(part_id, confirm)


@app.post("/api/parts/{part_id}/remove-from-bom")
def parts_remove_from_bom(part_id: int):
    return register.remove_from_bom(part_id)


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


# ---------- drawings and PO pack (roadmap stage 26) ----------

def _drawing_response(fn, filename: str):
    try:
        data = fn()
    except (register.RegisterError, ValueError, register.ToolNotApplicable) as exc:
        raise HTTPException(400, str(exc)) from None
    kind = filename.rsplit(".", 1)[-1]
    return Response(data, media_type={"pdf": "application/pdf", "dxf": "application/dxf", "zip": "application/zip"}[kind],
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/parts/{part_id}/drawing.{kind}")
def parts_drawing(part_id: int, kind: str):
    """Part drawing: three views of the 3D model, overall dimensions, title block (PDF A3 or DXF)."""
    if kind not in ("pdf", "dxf"):
        raise HTTPException(404, "pdf or dxf")
    code = register.part_detail(part_id, with_rm=False)["part_code"]
    return _drawing_response(lambda: register.part_drawing(part_id, kind), f"{code}_part_drawing.{kind}")


@app.get("/api/parts/{part_id}/tool-drawing.{kind}")
def parts_tool_drawing(part_id: int, kind: str, die: Optional[str] = None):
    """Concept drawing of the mould, or of one die stage (?die=key): plan, plate stack, main BOM, title block."""
    if kind not in ("pdf", "dxf"):
        raise HTTPException(404, "pdf or dxf")
    code = register.part_detail(part_id, with_rm=False)["part_code"]
    return _drawing_response(lambda: register.tool_drawing(part_id, kind, die), f"{code}_tool_drawing{'_' + die if die else ''}.{kind}")


@app.get("/api/parts/{part_id}/po-pack.zip")
def parts_po_pack(part_id: int):
    """Everything for a quotation / PO: part STEP and drawing, tool drawings and cost sheets per stage, blank / strip, costs."""
    from . import drawings
    data, name = drawings.po_pack(part_id)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/parts/{part_id}/forming-simulation.{kind}")
def parts_forming_simulation(part_id: int, kind: str):
    """Sheet-metal forming simulation report: pdf, or video (MP4, GIF when no ffmpeg) of the stages."""
    if kind not in ("pdf", "video"):
        raise HTTPException(404, "pdf or video")
    try:
        data, media, name = register.forming_report(part_id, kind)
    except (register.RegisterError, ValueError, register.ToolNotApplicable) as exc:
        raise HTTPException(400, str(exc)) from None
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/parts/{part_id}/correction")
def parts_correction_preview(part_id: int, radius: Optional[float] = None, hole: Optional[float] = None, draft: Optional[float] = None):
    """What the software can correct in the 3D model after the simulation (bend radius, small holes; draft of moulded parts)."""
    try:
        return register.correction_preview(part_id, radius, hole, draft)
    except (register.RegisterError, register.ToolNotApplicable) as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/parts/{part_id}/correction.{kind}")
def parts_correction_file(part_id: int, kind: str, radius: Optional[float] = None, hole: Optional[float] = None,
                          draft: Optional[float] = None):
    """The corrected 3D model (step) or a before | after picture (png)."""
    if kind not in ("step", "png"):
        raise HTTPException(404, "step or png")
    try:
        data, media, name = register.correction_file(part_id, kind, radius, hole, draft)
    except (register.RegisterError, register.ToolNotApplicable) as exc:
        raise HTTPException(400, str(exc)) from None
    return Response(data, media_type=media, headers={"Content-Disposition": f'{"inline" if kind == "png" else "attachment"}; filename="{name}"'})


@app.post("/api/parts/{part_id}/correction")
def parts_correction_release(part_id: int, data: dict):
    """Release the corrected model as a new revision: {radius_mm?, hole_mm?, rev?, change_note?}."""
    try:
        return register.correction_release(part_id, data.get("radius_mm"), data.get("hole_mm"), data.get("rev") or "",
                                           data.get("change_note") or "", data.get("draft_deg"))
    except (register.RegisterError, register.ToolNotApplicable) as exc:
        raise HTTPException(400, str(exc)) from None


# ---------- detailed tool design: 3D, drawings, release pack (roadmap stage 27) ----------

def _design_error(fn):
    try:
        return fn()
    except (register.RegisterError, ValueError, register.ToolNotApplicable) as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/parts/{part_id}/tool-design")
def parts_tool_design(part_id: int):
    """Each tool (die stage or mould) designed in 3D: its parts with material, hardness, standard part."""
    return _design_error(lambda: register.tool_design_summary(part_id))


@app.get("/api/parts/{part_id}/tool-design.{kind}")
def parts_tool_design_file(part_id: int, kind: str, die: Optional[str] = None):
    """zip = release pack (3D STEP of the assembly and every part, PDF and DXF drawings, BOM) of all tools or one (?die=key);
    step = assembly of one tool; pdf = its drawing set; png = its iso picture."""
    if kind not in ("zip", "step", "pdf", "png"):
        raise HTTPException(404, "zip, step, pdf or png")
    data, media, name = _design_error(lambda: register.tool_design_file(part_id, kind, die))
    disp = "inline" if kind == "png" else "attachment"
    return Response(data, media_type=media, headers={"Content-Disposition": f'{disp}; filename="{name}"'})


# ---------- the production machine of the tool (roadmap stage 32) ----------

@app.get("/api/parts/{part_id}/machine")
def parts_machine(part_id: int):
    from . import machine_spec
    return _design_error(lambda: machine_spec.get(part_id))


@app.put("/api/parts/{part_id}/machine")
def parts_machine_save(part_id: int, data: dict):
    """data: {spec: {tonnage_t, tie_bar_h_mm, …, machine_id?} | null, skipped: bool}."""
    from . import machine_spec
    return _design_error(lambda: machine_spec.save(part_id, data.get("spec"), bool(data.get("skipped"))))


@app.get("/api/parts/{part_id}/machine-check")
def parts_machine_check(part_id: int):
    """Each tool against the typed machine (tool needs / machine has / ok), or the recommended machine."""
    from . import machine_spec
    return _design_error(lambda: machine_spec.evaluate(part_id))


# ---------- technical data, release and revision history of the tool drawings (roadmap stage 30) ----------

@app.get("/api/parts/{part_id}/drawing-data")
def parts_drawing_data(part_id: int):
    from . import drawing_data
    return _design_error(lambda: drawing_data.part_data(part_id))


@app.put("/api/parts/{part_id}/drawing-data")
def parts_drawing_data_save(part_id: int, data: dict):
    """data: {items: [{tool, item, fields: {heat_treatment, surface_treatment, tolerance_class, finish_ra}, notes: [...]}]}."""
    from . import drawing_data
    return _design_error(lambda: drawing_data.part_save(part_id, list(data.get("items") or [])))


@app.get("/api/parts/{part_id}/drawing-data.xlsx")
def parts_drawing_data_xlsx(part_id: int):
    from . import drawing_data
    content, name = _design_error(lambda: drawing_data.part_xlsx(part_id))
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/parts/{part_id}/drawing-data/upload")
async def parts_drawing_data_upload(part_id: int, file: UploadFile = File(...)):
    from . import drawing_data
    content = await file.read()
    return _design_error(lambda: drawing_data.part_upload(part_id, content))


@app.get("/api/parts/{part_id}/sheet-tools")
def parts_sheet_tools(part_id: int):
    """Sheet-metal tools I: operation sequence, die type, forces, tonnage, press, formability (roadmap stage 9)."""
    try:
        return register.sheet_tools_result(part_id)
    except register.ToolNotApplicable as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/parts/{part_id}/sheet-layout")
def parts_sheet_layout(part_id: int):
    """Flat pattern and progressive strip layout (roadmap stage 10)."""
    try:
        return register.sheet_layout_result(part_id)
    except register.ToolNotApplicable as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/parts/{part_id}/sheet-layout/{kind}")
def parts_sheet_layout_file(part_id: int, kind: str):
    """kind: blank.dxf, strip.dxf or tool-pack.pdf."""
    if kind not in ("blank.dxf", "strip.dxf", "tool-pack.pdf"):
        raise HTTPException(404, "Unknown file.")
    try:
        content, media = register.sheet_layout_file(part_id, kind)
    except register.ToolNotApplicable as exc:
        raise HTTPException(400, str(exc)) from None
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{kind.split(".")[0]}_part_{part_id}.{kind.split(".")[1]}"'})


def _comparison(part_id: int, countries: Optional[str], mode: str, use_fta: bool) -> dict:
    from . import landed
    if mode not in ("sea", "air"):
        raise HTTPException(400, "mode must be sea or air.")
    try:
        return landed.compare(part_id, [c for c in (countries or "").split(",") if c.strip()] or None, mode, use_fta)
    except (ValueError, register.RegisterError) as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/parts/{part_id}/country-comparison")
def parts_country_comparison(part_id: int, countries: Optional[str] = None, mode: str = "sea", use_fta: bool = True):
    """Part and tool made in each country, ex-works and landed in India with duties (roadmap stage 11)."""
    return _comparison(part_id, countries, mode, use_fta)


@app.get("/api/parts/{part_id}/country-comparison/export.xlsx")
def parts_country_comparison_xlsx(part_id: int, countries: Optional[str] = None, mode: str = "sea", use_fta: bool = True):
    from . import landed
    return _xlsx(landed.to_excel(_comparison(part_id, countries, mode, use_fta)), f"country_comparison_{part_id}.xlsx")


@app.get("/api/parts/{part_id}/country-comparison/export.pdf")
def parts_country_comparison_pdf(part_id: int, countries: Optional[str] = None, mode: str = "sea", use_fta: bool = True):
    from . import landed
    res = _comparison(part_id, countries, mode, use_fta)
    return Response(landed.to_pdf(res, register.part_detail(part_id, with_rm=False)), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="country_comparison_{part_id}.pdf"'})


@app.get("/api/parts/{part_id}/simulation")
def parts_simulation(part_id: int):
    """Simulation & analysis v1: maps, cycle time, clamp force, machine, corrections required (roadmap stage 6)."""
    try:
        return register.simulation_result(part_id)
    except register.ToolNotApplicable as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/parts/{part_id}/simulation/video")
def parts_simulation_video(part_id: int):
    """Video (MP4, GIF without ffmpeg) of the wall-thickness, draft and risk maps turning, with the result."""
    try:
        data, media, name = register.simulation_video(part_id)
    except (register.RegisterError, register.ToolNotApplicable, ValueError) as exc:
        raise HTTPException(400, str(exc)) from None
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


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
def parts_tool_excel(part_id: int, version: Optional[int] = None, die: Optional[str] = None):
    """Tool cost workbook; sheet-metal dies get a sheet per die (stage-wise); `die` = one die only."""
    try:
        data = register.export_tool_excel(part_id, version, die)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None
    return _xlsx(data, f"tool_cost_part_{part_id}{'_' + die if die else ''}.xlsx")


@app.get("/api/parts/{part_id}/tool-cost/export.pdf")
def parts_tool_pdf(part_id: int, version: Optional[int] = None, die: Optional[str] = None):
    """Tool cost sheet; sheet-metal dies: summary + one page per die (stage-wise); `die` = one die only."""
    try:
        data = register.export_tool_pdf(part_id, version, die)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="tool_cost_part_{part_id}{"_" + die if die else ""}.pdf"'})


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


# ---------- server mode: logins and roles (roadmap stage 17) ----------

from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from . import auth, scope  # noqa: E402


def _log_settings_change(request, response) -> None:
    """Master data and rate changes go to the activity log too (their own tables keep only the values)."""
    path = request.url.path
    if request.method in ("GET", "HEAD", "OPTIONS") or response.status_code >= 400:
        return
    entity = "master_data" if path.startswith(auth.MASTER_PATHS) else "rates" if path.startswith(auth.RATE_PATHS) else ""
    if not entity:
        return
    try:
        with projects_db.engine().begin() as conn:
            auth.log(conn, entity, 0, "saved", {"table": path.removeprefix("/api/"), "method": request.method})
    except Exception:  # the log must never break the save itself
        pass


class AuthMiddleware(BaseHTTPMiddleware):
    """Every page and API call needs a login (DTC_MODE=local: none). The first start, with no user yet, goes to /setup.
    Permissions (Admin → Permissions) decide who may change what."""

    async def dispatch(self, request, call_next):
        path = request.url.path
        if not auth.server_mode() or not auth.needs_login(path):
            response = await call_next(request)
            if not auth.server_mode():
                _log_settings_change(request, response)
            return response
        from fastapi.responses import RedirectResponse
        if not auth.has_users():
            if path.startswith("/api/"):
                return JSONResponse({"detail": "No user yet: create the first admin on /setup.", "setup": True}, status_code=401)
            return RedirectResponse("/setup", status_code=303)
        user = auth.user_of(request.cookies.get(auth.COOKIE))
        if user is None:
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Please log in."}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        why = auth.allowed(user, request.method, path)
        if why:
            return JSONResponse({"detail": why}, status_code=403)
        token = auth.set_current(user)
        why = scope.guard(path)             # data access by tool group (stage 29)
        if why:
            auth.reset(token)
            return JSONResponse({"detail": why}, status_code=403)
        try:
            response = await call_next(request)
            _log_settings_change(request, response)
            return response
        finally:
            auth.reset(token)


app.add_middleware(AuthMiddleware)


@app.exception_handler(auth.AuthError)
def auth_error_handler(_, exc: auth.AuthError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@app.on_event("startup")
def _server_startup():
    if auth.server_mode():
        projects_db.engine()
        auth.bootstrap_admin()       # optional: first admin from DTC_ADMIN_PASSWORD; otherwise /setup asks for it


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def auth_login(inp: LoginIn):
    token, user = auth.login(inp.username, inp.password)
    res = JSONResponse({"user": user})
    res.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax", max_age=auth.SESSION_HOURS * 3600,
                   secure=os.environ.get("DTC_COOKIE_SECURE", "").lower() in ("1", "true", "yes"))
    return res


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    auth.logout(request.cookies.get(auth.COOKIE))
    res = JSONResponse({"ok": True})
    res.delete_cookie(auth.COOKIE)
    return res


@app.get("/api/auth/me")
def auth_me():
    u = auth.current()
    return {"mode": "server" if auth.server_mode() else "local", "user": u}


@app.post("/api/auth/password")
def auth_password(data: dict):
    auth.change_password(auth.current(), data.get("old", ""), data.get("new", ""))
    return {"ok": True}


@app.get("/api/server/health")
def server_health():
    """Mode, database kind and storage check, for a load balancer or a quick look. No data is shown."""
    url = projects_db.database_url()
    storage = register_setup.storage_root()
    try:
        storage.mkdir(parents=True, exist_ok=True)
        probe = storage / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        writable = True
    except OSError:
        writable = False
    return {"mode": "server" if auth.server_mode() else "local", "database": url.split(":", 1)[0].split("+")[0], "storage_writable": writable}


@app.get("/api/users")
def users_list():
    return auth.list_users()


@app.post("/api/users")
def users_create(data: dict):
    return auth.create_user(data.get("username", ""), data.get("password", ""), data.get("role", "engineer"), data.get("name", ""),
                            data.get("groups") or [])


@app.put("/api/users/{uid}")
def users_update(uid: int, data: dict):
    return auth.update_user(uid, data, auth.current())


@app.post("/api/auth/setup")
def auth_setup(data: dict):
    """First start: create the first admin and log in."""
    auth.setup_first_admin(data.get("username", ""), data.get("password", ""), data.get("name", ""))
    return auth_login(LoginIn(username=data.get("username", ""), password=data.get("password", "")))


@app.get("/login")
def login_page():
    from fastapi.responses import RedirectResponse
    if auth.server_mode() and not auth.has_users():
        return RedirectResponse("/setup", status_code=303)
    return FileResponse(FRONTEND_DIR / "login.html")


@app.get("/setup")
def setup_page():
    from fastapi.responses import RedirectResponse
    if auth.has_users():
        return RedirectResponse("/login", status_code=303)
    return FileResponse(FRONTEND_DIR / "setup.html")


@app.get("/users")
def users_page():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/admin", status_code=303)


# ---------- admin page (roadmap stage 22) ----------

@app.get("/admin")
def admin_page():
    return FileResponse(FRONTEND_DIR / "admin.html")


@app.get("/api/admin/permissions")
def admin_permissions():
    me = auth.current()
    return {"roles": list(auth.ROLES), "groups": [{"key": g, "label": scope.LABELS[g]} for g in scope.GROUPS], "permissions": auth.permissions(), "me": me,
            "mine": {p["action"]: auth.may(p["action"], me) for p in auth.permissions()}}


@app.put("/api/admin/permissions")
def admin_permissions_save(data: dict):
    auth.require("admin")
    return {"permissions": auth.save_permissions(data.get("permissions", []), auth.current())}


def _activity_filters(entity, user, q, date_from, date_to):
    for d in (date_from, date_to):
        if d:
            try:
                datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(400, f"Date '{d}' must look like 2026-10-25.") from None
    return dict(entity=entity, user=user, q=q, date_from=date_from, date_to=date_to)


@app.get("/api/admin/activity")
def admin_activity(entity: str = "", user: str = "", q: str = "", date_from: str = "", date_to: str = "",
                   limit: int = 200, offset: int = 0):
    from . import admin
    return admin.activity(**_activity_filters(entity, user, q, date_from, date_to), limit=min(limit, 2000), offset=offset)


@app.get("/api/admin/activity.xlsx")
def admin_activity_xlsx(entity: str = "", user: str = "", q: str = "", date_from: str = "", date_to: str = ""):
    from . import admin
    return _xlsx(admin.activity_excel(**_activity_filters(entity, user, q, date_from, date_to)), "activity_log.xlsx")


@app.get("/api/admin/backups")
def admin_backups():
    from . import admin
    return admin.backups()


@app.post("/api/admin/backups")
def admin_backup_now():
    from . import admin
    return admin.make_backup()


@app.get("/api/admin/backups/{name}")
def admin_backup_download(name: str):
    from . import admin
    try:
        return FileResponse(admin.backup_file(name), media_type="application/zip", filename=name)
    except admin.AdminError as exc:
        raise HTTPException(404, str(exc)) from None


@app.get("/api/admin/about")
def admin_about():
    from . import admin
    return admin.about()


# ---------- suppliers (roadmap stage 22) ----------

@app.get("/suppliers")
def suppliers_page():
    return FileResponse(FRONTEND_DIR / "suppliers.html")


@app.get("/api/suppliers")
def suppliers_list(q: str = "", status: str = "", country: str = "", commodity: str = ""):
    from . import suppliers
    return {"suppliers": suppliers.search(q, status, country, commodity), "statuses": suppliers.settings()["statuses"]}


@app.get("/api/suppliers/export.xlsx")
def suppliers_export():
    from . import suppliers
    return _xlsx(suppliers.to_excel(), "suppliers.xlsx")


@app.post("/api/suppliers")
def suppliers_create(data: dict):
    from . import suppliers
    return suppliers.create(data)


@app.get("/api/suppliers/{sid}")
def suppliers_get(sid: int):
    from . import suppliers
    return suppliers.get(sid)


@app.put("/api/suppliers/{sid}")
def suppliers_update(sid: int, data: dict):
    from . import suppliers
    return suppliers.update(sid, data)


@app.delete("/api/suppliers/{sid}")
def suppliers_delete(sid: int):
    from . import suppliers
    return suppliers.delete(sid)


# ---------- tool BOM: grades, standard parts, your changes (roadmap stage 23) ----------

# ---------- editing from the traceability panel (roadmap stage 24) ----------

@app.put("/api/parts/{part_id}/trace-override")
def parts_trace_override(part_id: int, data: dict):
    """This part only: {scope: rm | tool | piece, node, value | formula, note}; {reset: true} removes your change."""
    from . import trace_edit
    if data.get("reset"):
        return trace_edit.reset_override(part_id, data.get("scope", ""), data.get("node", ""))
    return trace_edit.set_override(part_id, data.get("scope", ""), data.get("node", ""), data.get("value"),
                                   data.get("formula"), data.get("note", ""))


@app.post("/api/trace/save-default")
def trace_save_default(data: dict):
    """For the future: {ref | rate, value | formula, note} corrects the master-data row or adds a rate version."""
    from . import trace_edit
    return trace_edit.save_default(data.get("ref"), data.get("rate"), data.get("value"), data.get("formula"), data.get("note", ""))


@app.post("/api/master-rows/{store}/{table}")
def master_row_add(store: str, table: str, data: dict):
    from . import trace_edit
    return trace_edit.add_row(store, table, data.get("row") or {})


@app.get("/api/tool-bom/choices")
def tool_bom_choices():
    return register.bom_choices()


@app.put("/api/parts/{part_id}/tool-bom")
def parts_tool_bom(part_id: int, data: dict):
    """One BOM line: {key, line: {grade, make, qty, price_each, std_part}, as_default}. An empty line = back to suggested."""
    key = str(data.get("key") or "").strip()
    if not key:
        raise HTTPException(400, "Which BOM line? (key)")
    if data.get("as_default"):
        auth.require_perm("edit_master_data")
    return register.save_bom_line(part_id, key, data.get("line") or {}, bool(data.get("as_default")))


@app.put("/api/parts/{part_id}/tool-bom/grade")
def parts_tool_bom_grade(part_id: int, data: dict):
    """{keys: [BOM line keys], grade}: one steel grade for these lines (other changes of the lines stay)."""
    return register.set_bom_grade(part_id, data.get("keys") or [], str(data.get("grade") or "").strip())


@app.get("/api/tool-bom/grade-prices")
def tool_bom_grade_prices(country: str = "IN", as_of: Optional[str] = None):
    return register.grade_prices(country.upper(), as_of)


@app.post("/api/tool-materials")
def tool_material_add(data: dict):
    return register.add_tool_material(data)


@app.post("/api/standard-parts")
def standard_part_add(data: dict):
    return register.add_standard_part(data)


@app.get("/api/parts/{part_id}/suppliers")
def part_suppliers_get(part_id: int):
    from . import suppliers
    return suppliers.part_suppliers(part_id)


@app.post("/api/parts/{part_id}/suppliers")
def part_suppliers_add(part_id: int, data: dict):
    from . import suppliers
    return suppliers.link(part_id, data)


@app.put("/api/parts/{part_id}/suppliers/{link_id}")
def part_suppliers_edit(part_id: int, link_id: int, data: dict):
    from . import suppliers
    return suppliers.update_link(part_id, link_id, data)


@app.delete("/api/parts/{part_id}/suppliers/{link_id}")
def part_suppliers_remove(part_id: int, link_id: int):
    from . import suppliers
    return suppliers.unlink(part_id, link_id)


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/theme", StaticFiles(directory=THEME_DIR), name="theme")
