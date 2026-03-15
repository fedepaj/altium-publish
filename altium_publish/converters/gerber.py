"""Convert Gerber files to preview images."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from ..config import Config

# Map common Gerber extensions to layer names
# Colors chosen to be visible on dark (#1a1a1a) overlay background
LAYER_MAP = {
    ".gtl": ("Top Copper", "copper", "#ff4444"),
    ".gbl": ("Bottom Copper", "copper", "#4444ff"),
    ".gts": ("Top Soldermask", "mask", "#00cc66"),
    ".gbs": ("Bottom Soldermask", "mask", "#6666cc"),
    ".gto": ("Top Silkscreen", "silk", "#ffff00"),
    ".gbo": ("Bottom Silkscreen", "silk", "#cccc00"),
    ".gtp": ("Top Paste", "paste", "#999999"),
    ".gbp": ("Bottom Paste", "paste", "#777777"),
    ".gko": ("Board Outline", "outline", "#ffcc00"),
    ".gm1": ("Mechanical 1", "mech", "#ff66ff"),
    ".gm2": ("Mechanical 2", "mech", "#ff66ff"),
    ".drl": ("Drill", "drill", "#ffffff"),
    ".xln": ("Drill", "drill", "#ffffff"),
}

# GerberX2 naming patterns (Altium's GerberX2 output uses descriptive filenames)
# NOTE: NPTH_Drill must come before PTH_Drill to avoid false substring match
GERBERX2_PATTERNS = [
    ("Copper_Signal_Top",     "Top Copper",          "copper",  "#ff4444"),
    ("Copper_Signal_Bot",     "Bottom Copper",        "copper",  "#4444ff"),
    ("Soldermask_Top",        "Top Soldermask",       "mask",    "#00cc66"),
    ("Soldermask_Bot",        "Bottom Soldermask",    "mask",    "#6666cc"),
    ("Legend_Top",            "Top Silkscreen",       "silk",    "#ffff00"),
    ("Legend_Bot",            "Bottom Silkscreen",    "silk",    "#cccc00"),
    ("Paste_Top",             "Top Paste",            "paste",   "#999999"),
    ("Paste_Bot",             "Bottom Paste",         "paste",   "#777777"),
    ("Profile",               "Board Outline",        "outline", "#ffcc00"),
    ("Drawing",               "Drawing",              "mech",    "#ff66ff"),
    ("Drillmap",              "Drill Map",            "drill",   "#aaaaaa"),
    ("NPTH_Drill",            "NPTH Drill",           "drill",   "#cccccc"),
    ("PTH_Drill",             "PTH Drill",            "drill",   "#ffffff"),
]


def _detect_layer(filepath: Path) -> tuple[str, str, str]:
    """Detect layer info from filename. Returns (layer_name, layer_type, color)."""
    ext = filepath.suffix.lower()
    name = filepath.stem

    # Try legacy extension first
    if ext in LAYER_MAP:
        return LAYER_MAP[ext]

    # Try GerberX2 name patterns
    for pattern, layer_name, layer_type, color in GERBERX2_PATTERNS:
        if pattern.lower() in name.lower():
            return (layer_name, layer_type, color)

    return ("Unknown", "other", "#aaaaaa")


def convert_gerbers(
    gerber_files: list[Path],
    output_dir: Path,
    config: Config,
) -> list[dict]:
    """
    Convert Gerber files to preview images.
    
    Tries multiple backends:
    1. tracespace CLI (npx @tracespace/cli) - best quality
    2. gerbv command line
    3. pygerber Python library
    
    Returns list of layer info dicts with preview paths.
    """
    if not gerber_files:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    tool = config.convert.gerber_tool

    layers = []
    for gf in gerber_files:
        layer_info = _detect_layer(gf)
        layers.append({
            "file": gf.name,
            "path": str(gf),
            "layer_name": layer_info[0],
            "layer_type": layer_info[1],
            "color": layer_info[2],
            "preview": None,
        })

    if tool == "auto":
        # Try each tool in order
        if not _try_tracespace(gerber_files, output_dir, layers):
            if not _try_gerbv(gerber_files, output_dir, layers):
                _try_pygerber(gerber_files, output_dir, layers)
    elif tool == "tracespace":
        _try_tracespace(gerber_files, output_dir, layers)
    elif tool == "gerbv":
        _try_gerbv(gerber_files, output_dir, layers)
    elif tool == "pygerber":
        _try_pygerber(gerber_files, output_dir, layers)

    # If no tool worked, just catalog the files
    if not any(l["preview"] for l in layers):
        print("  ⚠️  No Gerber renderer available. Layers cataloged but no previews generated.")
        print("     Install one of: npx @tracespace/cli, gerbv, pip install pygerber")

    # Normalize SVGs to a common coordinate system for overlay alignment
    _normalize_svg_coordinates(output_dir, layers)

    # Save layer catalog as JSON for the web viewer
    catalog_path = output_dir / "gerber_layers.json"
    with open(catalog_path, "w") as f:
        json.dump(layers, f, indent=2)

    return layers


def _try_tracespace(files: list[Path], output_dir: Path, layers: list[dict]) -> bool:
    """Try rendering with tracespace CLI.

    Renders ALL gerber files in a single pass so that tracespace uses
    a consistent coordinate system across layers, ensuring alignment.
    """
    try:
        # Check if npx is available
        result = subprocess.run(
            ["npx", "--yes", "@tracespace/cli", "--version"],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            return False

        # Render ALL gerber files in one invocation for aligned output
        render_dir = output_dir / "_tracespace_render"
        all_gerber_paths = [Path(l["path"]) for l in layers]
        cmd = (
            ["npx", "--yes", "@tracespace/cli"]
            + [str(p) for p in all_gerber_paths]
            + ["-o", str(render_dir)]
        )
        subprocess.run(cmd, capture_output=True, timeout=180)

        # If tracespace created a directory, collect individual layer SVGs
        all_svgs: list[Path] = []
        if render_dir.is_dir():
            all_svgs = list(render_dir.rglob("*.svg"))
        elif render_dir.with_suffix(".svg").is_file():
            # Single file output (unlikely with multiple inputs)
            all_svgs = [render_dir.with_suffix(".svg")]

        if not all_svgs:
            if render_dir.is_dir():
                shutil.rmtree(render_dir, ignore_errors=True)
            return False

        # Map output SVGs back to input layers by filename similarity
        used_svgs: set[Path] = set()
        for layer in layers:
            gf = Path(layer["path"])
            gf_norm = _normalize_stem(gf.stem)

            best_match = None
            best_score = 0
            for svg_path in all_svgs:
                if svg_path in used_svgs:
                    continue
                svg_norm = _normalize_stem(svg_path.stem)

                # Skip composite board views
                if svg_norm in ("top", "bottom", "all", "board"):
                    continue

                # Score by longest common substring match
                score = 0
                if gf_norm == svg_norm:
                    score = len(gf_norm) * 2
                elif gf_norm in svg_norm:
                    score = len(gf_norm)
                elif svg_norm in gf_norm:
                    score = len(svg_norm)

                if score > best_score:
                    best_score = score
                    best_match = svg_path

            if best_match and best_score > 3:
                dest = output_dir / f"{gf.stem}.svg"
                shutil.copy2(best_match, dest)
                layer["preview"] = dest.name
                used_svgs.add(best_match)

        # Clean up render directory
        if render_dir.is_dir():
            shutil.rmtree(render_dir, ignore_errors=True)

        if any(l["preview"] for l in layers):
            print(f"  🔲 Rendered Gerbers with tracespace")
            return True
        return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _normalize_stem(name: str) -> str:
    """Normalize a filename stem for fuzzy comparison."""
    return name.lower().replace(" ", "").replace("-", "").replace("_", "")


def _normalize_svg_coordinates(output_dir: Path, layers: list[dict]) -> None:
    """Normalize all gerber SVGs to a common coordinate system.

    Tracespace renders individual layers with different viewBoxes and Y-flip
    transforms. This function computes the effective bounds in a common
    (Y-down) coordinate system and rewrites each SVG with a unified viewBox.
    """
    svg_infos = []
    for layer in layers:
        if not layer.get("preview"):
            continue
        svg_path = output_dir / layer["preview"]
        if not svg_path.exists():
            continue
        content = svg_path.read_text()

        # Parse viewBox
        vb_match = re.search(r'viewBox="([^"]+)"', content)
        if not vb_match:
            continue
        parts = vb_match.group(1).strip().split()
        if len(parts) != 4:
            continue
        vx, vy, vw, vh = [float(p) for p in parts]
        if vw <= 0 or vh <= 0:
            continue

        # Detect Y-flip transform: translate(0, ty) scale(1,-1)
        # Tracespace uses this to convert Gerber Y-up to SVG Y-down coords.
        # Search the full content — all layer SVGs from tracespace use it.
        ty = None
        tf_match = re.search(
            r'transform="translate\(\s*0\s*,\s*([\d.]+)\s*\)\s*scale\(\s*1\s*,\s*-1\s*\)"',
            content,
        )
        if tf_match:
            ty = float(tf_match.group(1))

        # Compute effective bounds in common Y-down coordinate system
        if ty is not None:
            # Content visible in Y-down: x=[vx, vx+vw], y=[ty-vy-vh, ty-vy]
            eff_y = ty - vy - vh
            eff_h = vh
        else:
            eff_y = vy
            eff_h = vh

        svg_infos.append({
            "layer": layer,
            "path": svg_path,
            "content": content,
            "vx": vx, "vy": vy, "vw": vw, "vh": vh,
            "ty": ty,
            "eff_x": vx, "eff_y": eff_y, "eff_w": vw, "eff_h": eff_h,
        })

    if len(svg_infos) < 2:
        return

    # Compute union bounds in Y-down space
    ux1 = min(s["eff_x"] for s in svg_infos)
    uy1 = min(s["eff_y"] for s in svg_infos)
    ux2 = max(s["eff_x"] + s["eff_w"] for s in svg_infos)
    uy2 = max(s["eff_y"] + s["eff_h"] for s in svg_infos)
    uw, uh = ux2 - ux1, uy2 - uy1

    print(f"    📐 Normalizing {len(svg_infos)} layer viewBoxes for alignment")
    print(f"       Union bounds: x=[{ux1:.0f},{ux2:.0f}] y=[{uy1:.0f},{uy2:.0f}]")

    # Rewrite each SVG with the common viewBox
    for s in svg_infos:
        content = s["content"]
        if s["ty"] is not None:
            # Has Y-flip: new viewBox maps union bounds through the transform
            # transform: y_transformed = ty - y_content
            # Union y range [uy1, uy2] in content → [ty-uy2, ty-uy1] in transformed
            new_vy = s["ty"] - uy2
            new_vb = f"{ux1} {new_vy} {uw} {uh}"
        else:
            # No transform: viewBox = union bounds directly
            new_vb = f"{ux1} {uy1} {uw} {uh}"

        old_vb = f"{s['vx']} {s['vy']} {s['vw']} {s['vh']}"
        print(f"       {s['path'].name}: ty={s['ty']} old=({old_vb}) new=({new_vb})")

        # Replace viewBox
        content = re.sub(r'viewBox="[^"]*"', f'viewBox="{new_vb}"', content, count=1)
        s["path"].write_text(content)


def _try_gerbv(files: list[Path], output_dir: Path, layers: list[dict]) -> bool:
    """Try rendering with gerbv."""
    if not shutil.which("gerbv"):
        return False

    try:
        for layer in layers:
            gf = Path(layer["path"])
            svg_out = output_dir / f"{gf.stem}.svg"
            result = subprocess.run(
                ["gerbv", "-x", "svg", "-o", str(svg_out),
                 "-f", layer["color"], "-b", "#000000", str(gf)],
                capture_output=True, timeout=30,
            )
            if svg_out.exists() and svg_out.stat().st_size > 0:
                layer["preview"] = svg_out.name

        print(f"  🔲 Rendered Gerbers with gerbv")
        return True
    except Exception:
        return False


def _try_pygerber(files: list[Path], output_dir: Path, layers: list[dict]) -> bool:
    """Try rendering with pygerber."""
    try:
        from pygerber.gerberx3.api.v2 import GerberFile

        for layer in layers:
            gf = Path(layer["path"])
            try:
                parsed = GerberFile.from_file(gf)
                svg_out = output_dir / f"{gf.stem}.svg"
                parsed.render_with_pillow().save(str(svg_out))
                if svg_out.exists():
                    layer["preview"] = svg_out.name
            except Exception:
                continue

        print(f"  🔲 Rendered Gerbers with pygerber")
        return True
    except ImportError:
        return False
