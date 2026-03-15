"""Convert PDF files to web-friendly formats: SVG (schematics) and raster (thumbnails)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..config import Config


def convert_pdf_to_svg(
    pdf_path: Path,
    output_dir: Path,
) -> list[dict]:
    """
    Convert a PDF to per-page SVG files (vector, infinite zoom).
    
    Returns list of dicts with page info:
      [{"page": 1, "svg": Path, "width": float, "height": float}, ...]
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print(f"  ⚠️  PyMuPDF not installed, skipping SVG conversion for {pdf_path.name}")
        print("     Install with: pip install PyMuPDF")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    pages = []

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        print(f"  ⚠️  Failed to open {pdf_path.name}: {e}")
        return []

    for page_num in range(len(doc)):
        page = doc[page_num]
        rect = page.rect

        svg_content = page.get_svg_image(matrix=fitz.Identity)
        svg_content = _patch_svg_for_web(svg_content, rect.width, rect.height)

        if len(doc) > 1:
            out_name = f"{stem}_p{page_num + 1}.svg"
        else:
            out_name = f"{stem}.svg"

        out_path = output_dir / out_name
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(svg_content)

        pages.append({
            "page": page_num + 1,
            "svg": out_path,
            "svg_name": out_name,
            "width": rect.width,
            "height": rect.height,
        })

    doc.close()
    return pages


def convert_pdf_to_raster(
    pdf_path: Path,
    output_dir: Path,
    config: Config,
) -> list[Path]:
    """Convert a PDF to raster preview images. Used for draftsman and thumbnails."""
    try:
        import fitz
    except ImportError:
        print(f"  ⚠️  PyMuPDF not installed, skipping conversion for {pdf_path.name}")
        print("     Install with: pip install PyMuPDF")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    fmt = config.convert.pdf_format
    dpi = config.convert.pdf_dpi
    zoom = dpi / 72.0
    generated = []

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        print(f"  ⚠️  Failed to open {pdf_path.name}: {e}")
        return []

    for page_num in range(len(doc)):
        page = doc[page_num]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        if len(doc) > 1:
            out_name = f"{stem}_p{page_num + 1}.{fmt}"
        else:
            out_name = f"{stem}.{fmt}"

        out_path = output_dir / out_name
        if fmt == "webp":
            try:
                from PIL import Image
                import io
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                img.save(str(out_path), "WEBP", quality=85)
            except ImportError:
                out_path = out_path.with_suffix(".png")
                pix.save(str(out_path))
        else:
            pix.save(str(out_path))
        generated.append(out_path)

    doc.close()
    return generated


def generate_pdf_thumbnails(
    pdf_path: Path,
    output_dir: Path,
    thumb_width: int = 400,
) -> list[Path]:
    """Generate small raster thumbnails for gallery/nav view."""
    try:
        import fitz
        from PIL import Image
        import io
    except ImportError:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    thumbnails = []

    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return []

    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        ratio = thumb_width / img.width
        new_size = (thumb_width, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

        if len(doc) > 1:
            out_name = f"{stem}_thumb_p{page_num + 1}.webp"
        else:
            out_name = f"{stem}_thumb.webp"

        out_path = output_dir / out_name
        img.save(str(out_path), "WEBP", quality=75)
        thumbnails.append(out_path)

    doc.close()
    return thumbnails


def get_pdf_page_count(pdf_path: Path) -> int:
    """Get number of pages in a PDF."""
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        count = len(doc)
        doc.close()
        return count
    except Exception:
        return 0


def _patch_svg_for_web(svg_content: str, width: float, height: float) -> str:
    """
    Patch PyMuPDF SVG for clean web display:
    - Set viewBox for responsive sizing
    - Add white background
    - Remove fixed width/height
    """
    # Add viewBox
    svg_content = re.sub(
        r'<svg\s',
        f'<svg viewBox="0 0 {width:.2f} {height:.2f}" '
        f'preserveAspectRatio="xMidYMid meet" ',
        svg_content,
        count=1,
    )
    # Remove fixed width/height so CSS controls sizing
    svg_content = re.sub(r'\s+width="[^"]*"', '', svg_content, count=1)
    svg_content = re.sub(r'\s+height="[^"]*"', '', svg_content, count=1)
    # White background
    svg_content = re.sub(
        r'(<svg[^>]*>)',
        r'\1\n<rect width="100%" height="100%" fill="white"/>',
        svg_content,
        count=1,
    )
    return svg_content
