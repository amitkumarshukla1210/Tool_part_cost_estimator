"""FastAPI web server for the part cost estimator (Stage A).

Run from the repository root:
    uvicorn backend.app.main:app --reload
then open http://127.0.0.1:8000 in a browser.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .geometry import PART_TYPES, analyze, load_step, tessellate

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
MAX_UPLOAD_MB = 100

app = FastAPI(title="Tool & Part Cost Estimator", version="0.1.0 (Stage A)")


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

    return {
        "file_name": file.filename,
        "part_type_label": PART_TYPES[part_type],
        "metrics": metrics.to_dict(),
        # Flat arrays are what three.js BufferGeometry expects.
        "mesh": {
            "positions": [c for v in vertices for c in v],
            "indices": [i for t in triangles for i in t],
        },
    }


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
