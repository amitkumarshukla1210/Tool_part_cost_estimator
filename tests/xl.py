"""Test helper (stage 67): open a downloaded Excel without its brand rows (logo rows on top, copyright line under the data),
so a test checks the exporter's own cells where the exporter put them."""

from openpyxl import load_workbook as _load

from backend.app import branding


def load_workbook(src, *args, **kw):
    kw.pop("read_only", None)
    wb = _load(src, *args, **kw)
    if branding.MARK in (wb.properties.keywords or ""):
        for ws in wb.worksheets:
            if ws.cell(ws.max_row, 1).value == branding.FOOTER:
                ws.delete_rows(ws.max_row - 1, 2)
            if getattr(ws, "_images", None):
                ws.delete_rows(1, branding.HEAD_ROWS)
    return wb
