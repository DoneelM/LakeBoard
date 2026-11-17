"""Builds an Excel workbook from rows a page already holds (kit.xlsx posts them to /api/xlsx).

People edit and print these files, so each sheet gets a bold frozen header, sensible column widths, wrapped text
and a landscape page that fits the columns to one page wide.
"""
from __future__ import annotations

import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

MAX_SHEETS = 10
MAX_ROWS = 50_000
MAX_COLUMNS = 60
BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
LINK_RE = re.compile(r"^https://[^\s]+$")


class XlsxError(ValueError):
    pass


def safe_filename(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(name or "export")).strip(" .")[:80] or "export"
    return stem if stem.lower().endswith(".xlsx") else stem + ".xlsx"


def build(sheets: list[dict]) -> bytes:
    """sheets: [{name, columns: [{key, label, width, link}], rows: [{key: value}], landscape}]"""
    if not isinstance(sheets, list) or not 1 <= len(sheets) <= MAX_SHEETS:
        raise XlsxError(f"Between 1 and {MAX_SHEETS} sheets are needed")
    wb = Workbook()
    wb.remove(wb.active)
    for i, sheet in enumerate(sheets):
        if not isinstance(sheet, dict):
            raise XlsxError("Each sheet must be an object")
        columns = sheet.get("columns")
        rows = sheet.get("rows", [])
        if rows is None:
            rows = []
        if not isinstance(columns, list) or not columns or len(columns) > MAX_COLUMNS:
            raise XlsxError(f"A sheet needs between 1 and {MAX_COLUMNS} columns")
        for col in columns:
            if not isinstance(col, dict) or not isinstance(col.get("key"), str):
                raise XlsxError("Each column must be an object with a text key")
            if col.get("label") is not None and not isinstance(col.get("label"), str):
                raise XlsxError("A column label must be text")
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise XlsxError("Rows must be a list of objects")
        if len(rows) > MAX_ROWS:
            raise XlsxError(f"A sheet can hold at most {MAX_ROWS:,} rows")
        if sheet.get("name") is not None and not isinstance(sheet.get("name"), str):
            raise XlsxError("A sheet name must be text")
        title = BAD_SHEET_CHARS.sub(" ", str(sheet.get("name") or f"Sheet{i + 1}")).strip()[:31] or f"Sheet{i + 1}"
        ws = wb.create_sheet(title)
        for c, col in enumerate(columns, 1):
            cell = ws.cell(row=1, column=c)
            _set_text(cell, str(col.get("label") or col.get("key") or ""))
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="004851")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            width = col.get("width")
            ws.column_dimensions[get_column_letter(c)].width = float(width) if isinstance(width, (int, float)) and 2 <= width <= 120 else 18
        for r, row in enumerate(rows, 2):
            for c, col in enumerate(columns, 1):
                value = row.get(col["key"])
                cell = ws.cell(row=r, column=c)
                if isinstance(value, bool) or value is None:
                    cell.value = None if value is None else str(value)
                elif isinstance(value, (int, float)):
                    cell.value = value
                else:
                    _set_text(cell, str(value))
                    if col.get("link") and LINK_RE.match(str(value)):
                        cell.hyperlink = str(value)
                        cell.font = Font(color="00606B", underline="single")
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        ws.freeze_panes = "A2"
        ws.print_title_rows = "1:1"
        ws.page_setup.orientation = "landscape" if sheet.get("landscape", True) else "portrait"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _set_text(cell, text: str) -> None:
    """Always text: a value such as "=1+1" or "+64…" typed into a comment must never become a formula."""
    cell.value = text
    cell.data_type = "s"
