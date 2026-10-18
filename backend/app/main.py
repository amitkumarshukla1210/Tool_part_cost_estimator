"""Design to Cost: web server for the Part Cost Estimator module (Stages A to C, rate library and MHR).

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
from . import capacity, costing_setup, gross_weight, master_data, mould, mould_db, rate_engine, rates

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
THEME_DIR = Path(__file__).resolve().parents[2] / "theme"
MAX_UPLOAD_MB = 100

app = FastAPI(title="Design to Cost — Part Cost Estimator", version="0.4.0 (rate library & MHR)")


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
    return {pt: gross_weight.defaults(pt) for pt in PART_TYPES}


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
    master_data.replace_from_upload(await file.read())
    return master_data.tables()


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
    try:
        return mould.estimate(inp)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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


def _xlsx(content: bytes, name: str) -> Response:
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _require_xlsx(file: UploadFile) -> None:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Please upload an Excel .xlsx file.")


@app.exception_handler(master_data.MasterDataError)
@app.exception_handler(mould_db.MouldDbError)
@app.exception_handler(costing_setup.SetupError)
@app.exception_handler(rates.RateError)
@app.exception_handler(rate_engine.EngineError)
def master_data_error(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/master-data")
def master_data_page():
    return FileResponse(FRONTEND_DIR / "master-data.html")


@app.get("/rates")
def rates_page():
    return FileResponse(FRONTEND_DIR / "rates.html")


@app.get("/help")
def help_page():
    return FileResponse(FRONTEND_DIR / "help.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/theme", StaticFiles(directory=THEME_DIR), name="theme")
