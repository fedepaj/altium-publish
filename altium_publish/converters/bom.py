"""Convert BOM files (Excel/CSV) to interactive HTML and JSON."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Optional


def convert_bom(
    bom_path: Path,
    output_dir: Path,
) -> Optional[Path]:
    """
    Convert a BOM file to a JSON data file for the web viewer.
    
    Supports .xlsx, .xls, .csv, .tsv formats.
    Returns path to the generated JSON file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    ext = bom_path.suffix.lower()
    rows: list[dict] = []
    headers: list[str] = []

    try:
        if ext in (".xlsx", ".xls"):
            headers, rows = _read_excel(bom_path)
        elif ext in (".csv", ".tsv"):
            headers, rows = _read_csv(bom_path, delimiter="\t" if ext == ".tsv" else ",")
        else:
            print(f"  ⚠️  Unsupported BOM format: {ext}")
            return None
    except Exception as e:
        print(f"  ⚠️  Failed to read BOM {bom_path.name}: {e}")
        return None

    if not rows:
        print(f"  ⚠️  BOM {bom_path.name} appears empty")
        return None

    # Normalize column names for common Altium BOM fields
    column_map = _detect_columns(headers)

    # Build structured BOM data
    bom_data = {
        "source": bom_path.name,
        "headers": headers,
        "column_map": column_map,
        "rows": rows,
        "stats": _compute_stats(rows, column_map),
    }

    out_path = output_dir / f"{bom_path.stem}_bom.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(bom_data, f, indent=2, ensure_ascii=False, default=str)

    return out_path


def _read_excel(path: Path) -> tuple[list[str], list[dict]]:
    """Read an Excel file, auto-detecting the header row."""
    try:
        import openpyxl
    except ImportError:
        print("  ⚠️  openpyxl not installed. Install with: pip install openpyxl")
        return [], []

    # Patch for openpyxl compatibility with some Excel files (xxid/xfId mismatch)
    try:
        from openpyxl.styles.cell_style import CellStyle
        _orig_init = CellStyle.__init__
        def _patched_init(self, **kw):
            if 'xxid' in kw:
                kw['xfId'] = kw.pop('xxid')
            _orig_init(self, **kw)
        CellStyle.__init__ = _patched_init
    except Exception:
        pass

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active

    all_rows = []
    for row in ws.iter_rows(values_only=True):
        all_rows.append([str(cell) if cell is not None else "" for cell in row])

    wb.close()

    if not all_rows:
        return [], []

    # Find header row - look for common BOM headers
    header_idx = _find_header_row(all_rows)
    headers = all_rows[header_idx]
    data_rows = []
    for row in all_rows[header_idx + 1:]:
        if any(cell.strip() for cell in row):  # skip empty rows
            data_rows.append(dict(zip(headers, row)))

    return headers, data_rows


def _read_csv(path: Path, delimiter: str = ",") -> tuple[list[str], list[dict]]:
    """Read a CSV/TSV file."""
    with open(path, "r", encoding="utf-8-sig") as f:
        # Sniff the dialect
        sample = f.read(8192)
        f.seek(0)
        
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = None

        if dialect:
            reader = csv.reader(f, dialect)
        else:
            reader = csv.reader(f, delimiter=delimiter)

        all_rows = [row for row in reader]

    if not all_rows:
        return [], []

    header_idx = _find_header_row(all_rows)
    headers = all_rows[header_idx]
    data_rows = []
    for row in all_rows[header_idx + 1:]:
        if any(cell.strip() for cell in row):
            # Pad row if shorter than headers
            padded = row + [""] * (len(headers) - len(row))
            data_rows.append(dict(zip(headers, padded[:len(headers)])))

    return headers, data_rows


def _find_header_row(rows: list[list[str]], max_check: int = 10) -> int:
    """
    Find the header row by looking for common BOM column names.
    Returns the row index.
    """
    bom_keywords = {
        "designator", "reference", "ref", "comment", "value",
        "footprint", "description", "quantity", "qty",
        "manufacturer", "mfr", "mpn", "part number",
        "supplier", "digikey", "mouser", "lcsc",
    }

    best_idx = 0
    best_score = 0

    for i, row in enumerate(rows[:max_check]):
        score = sum(
            1 for cell in row
            if cell.strip().lower() in bom_keywords
            or any(kw in cell.strip().lower() for kw in bom_keywords)
        )
        if score > best_score:
            best_score = score
            best_idx = i

    return best_idx


def _detect_columns(headers: list[str]) -> dict[str, str]:
    """
    Map semantic roles to actual column names.
    Returns {role: column_name}.
    """
    patterns = {
        "designator": r"(?i)(designator|reference|ref\s*des)",
        "value": r"(?i)(comment|value|val)$",
        "footprint": r"(?i)(footprint|package|case)",
        "description": r"(?i)(description|desc)",
        "quantity": r"(?i)(quantity|qty|count)",
        "manufacturer": r"(?i)(manufacturer|mfr|mfg)",
        "mpn": r"(?i)(mpn|part\s*number|mfr\s*part|manufacturer\s*part)",
        "supplier_pn": r"(?i)(supplier|digikey|mouser|lcsc|farnell|arrow)",
    }

    result = {}
    for role, pattern in patterns.items():
        for header in headers:
            if re.search(pattern, header.strip()):
                result[role] = header
                break

    return result


def _compute_stats(rows: list[dict], column_map: dict) -> dict:
    """Compute summary statistics from BOM data."""
    stats = {
        "total_lines": len(rows),
        "unique_parts": 0,
        "total_components": 0,
    }

    # Count unique values
    if "value" in column_map:
        val_col = column_map["value"]
        unique_vals = set(row.get(val_col, "") for row in rows)
        stats["unique_parts"] = len(unique_vals - {""})

    # Sum quantities
    if "quantity" in column_map:
        qty_col = column_map["quantity"]
        total = 0
        for row in rows:
            try:
                total += int(row.get(qty_col, 0))
            except (ValueError, TypeError):
                total += 1  # assume 1 if not parseable
        stats["total_components"] = total
    else:
        # If no quantity column, count designators
        if "designator" in column_map:
            des_col = column_map["designator"]
            total = 0
            for row in rows:
                des = row.get(des_col, "")
                # Designators might be comma-separated: "R1, R2, R3"
                total += len([d for d in des.split(",") if d.strip()])
            stats["total_components"] = total

    return stats
