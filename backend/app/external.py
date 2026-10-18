"""Scanned drawings and DWG (roadmap stage 16): optional external tools, used when they are installed.

    OCR       Tesseract (open source, https://github.com/tesseract-ocr/tesseract): scanned PDF pages and images -> words with
              positions and confidence -> a table -> the same BOM lines as a text PDF, each cell carrying the OCR confidence
    DXF       ezdxf reads TEXT / MTEXT / ATTRIB entities with positions -> a table -> BOM lines
    DWG       converted to DXF first by ODA File Converter (free, proprietary licence) or LibreDWG's dwg2dxf (GPL), then as DXF

Nothing is bundled: if a tool is missing the message says what to install and the app keeps working with the other formats.
Set DTC_TESSERACT / DTC_DWG_CONVERTER to the full path of a tool that is not on the PATH.
"""

from __future__ import annotations

import io
import os
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path

from . import bom_extract
from .bom_extract import ExtractError, _map_header, table_to_lines

OCR_DPI = 300
TIMEOUT = 180


def _tool(env: str, *names: str) -> str | None:
    path = os.environ.get(env)
    if path and Path(path).exists():
        return path
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    return None


def tesseract() -> str | None:
    return _tool("DTC_TESSERACT", "tesseract")


def dwg_converter() -> tuple[str, str] | None:
    path = os.environ.get("DTC_DWG_CONVERTER")
    if path and Path(path).exists():
        return path, "oda" if "oda" in Path(path).name.lower() else "libredwg"
    for name, kind in (("ODAFileConverter", "oda"), ("dwg2dxf", "libredwg")):
        found = shutil.which(name)
        if found:
            return found, kind
    return None


def tools_status() -> dict:
    t, d = tesseract(), dwg_converter()
    return {"tesseract": t, "dwg_converter": d[0] if d else None, "dwg_converter_kind": d[1] if d else None,
            "ocr_help": "Install Tesseract OCR (Windows: the UB Mannheim installer; Linux: apt install tesseract-ocr), then restart the app. Optionally set DTC_TESSERACT to its path.",
            "dwg_help": "Install ODA File Converter (free) or LibreDWG (dwg2dxf), or export DXF from your CAD system. Optionally set DTC_DWG_CONVERTER to its path."}


# ---------- words/boxes -> table ----------

def grid_from_boxes(boxes: list[tuple]) -> tuple[list[list[str]], list[list[float]]]:
    """boxes: (x, y, h, text, conf) with y increasing downwards. Rows by y, cells by horizontal gaps, columns by the header row."""
    boxes = [b for b in boxes if b[3].strip()]
    if not boxes:
        return [], []
    h = statistics.median(b[2] for b in boxes) or 1.0
    rows: list[list[tuple]] = []
    for b in sorted(boxes, key=lambda b: (b[1], b[0])):
        if rows and abs(b[1] - statistics.mean(x[1] for x in rows[-1])) <= 0.6 * h:
            rows[-1].append(b)
        else:
            rows.append([b])
    cells_rows = []
    for r in rows:
        cells, cur = [], None
        for b in sorted(r, key=lambda b: b[0]):
            width = len(b[3]) * h * 0.55
            if cur and b[0] - cur["end"] <= 1.2 * h:
                cur["text"] += " " + b[3]
                cur["conf"] = min(cur["conf"], b[4])
                cur["end"] = b[0] + width
            else:
                if cur:
                    cells.append(cur)
                cur = {"x": b[0], "text": b[3], "conf": b[4], "end": b[0] + width}
        cells.append(cur)
        cells_rows.append(cells)
    head = next((i for i, cs in enumerate(cells_rows) if len(_map_header([c["text"] for c in cs])) >= 3), None)
    if head is None:
        return [[c["text"] for c in cs] for cs in cells_rows], [[c["conf"] for c in cs] for cs in cells_rows]
    anchors = [c["x"] for c in cells_rows[head]]
    table, conf = [], []
    for cs in cells_rows[head:]:
        row, rc = [""] * len(anchors), [1.0] * len(anchors)
        for c in cs:
            j = max((i for i, a in enumerate(anchors) if a <= c["x"] + 0.8 * h), default=0)
            row[j] = (row[j] + " " + c["text"]).strip()
            rc[j] = min(rc[j], c["conf"])
        table.append(row)
        conf.append(rc)
    return table, conf


# ---------- OCR ----------

def _tsv_boxes(tsv: str) -> list[tuple]:
    boxes = []
    for ln in tsv.splitlines()[1:]:
        f = ln.split("\t")
        if len(f) < 12 or not f[11].strip():
            continue
        try:
            conf = float(f[10])
        except ValueError:
            continue
        if conf < 0:
            continue
        boxes.append((float(f[6]), float(f[7]) + float(f[9]) / 2, float(f[9]), f[11].strip(), conf / 100))
    return boxes


def page_tsv(png: bytes) -> str:
    """Tesseract word boxes of one page image (TSV)."""
    exe = tesseract()
    if not exe:
        raise ExtractError("This is a scan and needs OCR, but Tesseract is not installed. " + tools_status()["ocr_help"])
    with tempfile.TemporaryDirectory() as d:
        img = Path(d) / "page.png"
        img.write_bytes(png)
        try:
            r = subprocess.run([exe, str(img), "stdout", "--psm", "6", "tsv"], capture_output=True, text=True, timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExtractError(f"Tesseract could not be run: {exc}") from None
    if r.returncode != 0:
        raise ExtractError(f"Tesseract failed: {r.stderr.strip()[:200]}")
    return r.stdout


def _ocr_pages(images: list[bytes], label: str) -> list[dict]:
    out, found = [], False
    for pno, png in enumerate(images, start=1):
        table, conf = grid_from_boxes(_tsv_boxes(page_tsv(png)))
        lines = table_to_lines(table, f"{label} page {pno} (OCR)", conf) if table else None
        if lines is not None:
            found = True
            out += lines
    if not found:
        raise ExtractError("OCR ran but found no BOM table with a quantity or part number column. Check the scan quality (300 dpi, straight, dark text) and the table headers.")
    return out


def ocr_pdf(content: bytes) -> list[dict]:
    if not tesseract():
        raise ExtractError("This PDF has no text (a scan) and needs OCR, but Tesseract is not installed. " + tools_status()["ocr_help"] +
                           " Or use a text PDF or the KBL / VEC export.")
    import pypdfium2 as pdfium
    try:
        pdf = pdfium.PdfDocument(content)
        images = []
        for page in pdf:
            buf = io.BytesIO()
            page.render(scale=OCR_DPI / 72).to_pil().save(buf, format="PNG")
            images.append(buf.getvalue())
    except Exception as exc:
        raise ExtractError(f"The scanned PDF could not be rendered: {exc}") from None
    return _ocr_pages(images, "scan")


def ocr_image(content: bytes) -> list[dict]:
    from PIL import Image
    try:
        buf = io.BytesIO()
        Image.open(io.BytesIO(content)).convert("RGB").save(buf, format="PNG")
    except Exception as exc:
        raise ExtractError(f"The image could not be read: {exc}") from None
    return _ocr_pages([buf.getvalue()], "image")


# ---------- DXF / DWG ----------

def dxf_boxes(doc) -> list[tuple]:
    boxes = []

    def add(e, text):
        p = e.dxf.insert
        h = getattr(e.dxf, "height", None) or getattr(e.dxf, "char_height", None) or 2.5
        boxes.append((float(p.x), -float(p.y), float(h), text, 1.0))     # DXF y points up, grid_from_boxes wants down

    msp = doc.modelspace()
    for e in msp:
        t = e.dxftype()
        if t == "TEXT":
            add(e, e.dxf.text)
        elif t == "MTEXT":
            add(e, e.plain_text().replace("\n", " "))
        elif t == "INSERT":
            for a in e.attribs:
                add(a, a.dxf.text)
    return boxes


def parse_dxf(content: bytes) -> list[dict]:
    import ezdxf
    try:
        doc = ezdxf.read(io.StringIO(content.decode("utf-8", errors="replace")))
    except Exception as exc:
        raise ExtractError(f"The DXF file could not be read: {exc}") from None
    table, _ = grid_from_boxes(dxf_boxes(doc))
    lines = table_to_lines(table, "DXF text table") if table else None
    if not lines:
        raise ExtractError("No BOM table was found in the drawing text (a header row with a quantity or part number column, plus rows of TEXT / MTEXT / attributes).")
    return lines


def dwg_to_dxf(content: bytes) -> bytes:
    conv = dwg_converter()
    if not conv:
        raise ExtractError("A DWG file needs a converter, but none is installed. " + tools_status()["dwg_help"])
    exe, kind = conv
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "in", Path(d) / "out"
        src.mkdir()
        out.mkdir()
        (src / "drawing.dwg").write_bytes(content)
        cmd = ([exe, str(src), str(out), "ACAD2018", "DXF", "0", "1"] if kind == "oda" else [exe, "-o", str(out / "drawing.dxf"), str(src / "drawing.dwg")])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExtractError(f"The DWG converter could not be run: {exc}") from None
        made = next(out.glob("*.dxf"), None) or next(out.glob("*.DXF"), None)
        if not made:
            raise ExtractError(f"The DWG converter produced no DXF file. {r.stderr.strip()[:200]}")
        return made.read_bytes()


def parse_drawing(content: bytes, name: str) -> list[dict]:
    return parse_dxf(dwg_to_dxf(content) if name.endswith(".dwg") else content)
