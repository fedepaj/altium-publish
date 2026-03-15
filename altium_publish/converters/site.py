"""Generate the GitHub Pages static site from processed files."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from ..config import Config
from ..scanner import ScanResult
from .pdf import convert_pdf_to_svg, convert_pdf_to_raster, generate_pdf_thumbnails
from .bom import convert_bom
from .step import convert_step, generate_step_gif
from .gerber import convert_gerbers


def build_site(config: Config, scan: ScanResult) -> Path:
    """
    Process all files and generate the GitHub Pages site.
    Returns path to the output directory.
    """
    output_dir = Path(config.output_dir).resolve()
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    site_data = {
        "project": {
            "name": config.project.name,
            "description": config.project.description,
            "author": config.project.author,
            "license": config.project.license,
            "repo": config.project.repo,
            "repo_url": f"https://github.com/{config.project.repo}" if config.project.repo else "",
        },
        "site": {
            "title": config.site.title or config.project.name,
            "theme": config.site.theme,
            "accent_color": config.site.accent_color,
        },
        "schematics": [],
        "schematic_format": config.convert.schematic_format,  # "svg" or "raster"
        "draftsman": [],
        "draftsman_format": "svg",  # "svg" or "raster"
        "bom": None,
        "step": None,
        "step_glb": None,
        "step_format": "step",
        "gerber_layers": [],
        "ibom": None,
        "downloads": [],
    }

    # ── Process Schematics (SVG or raster) ──────────────────
    schem_files = scan.by_group("schematics")
    if schem_files:
        print("\n📄 Processing schematics...")
        schem_dir = assets_dir / "schematics"
        schem_dir.mkdir(parents=True, exist_ok=True)

        for sf in schem_files:
            print(f"  Converting {sf.path.name}...")

            if config.convert.schematic_format == "svg":
                # SVG: vector, zoomable, navigable
                pages = convert_pdf_to_svg(sf.path, schem_dir)
                for pg in pages:
                    site_data["schematics"].append({
                        "name": sf.path.stem + (f" — Page {pg['page']}" if len(pages) > 1 else ""),
                        "page_num": pg["page"],
                        "total_pages": len(pages),
                        "svg": f"assets/schematics/{pg['svg_name']}",
                        "width": pg["width"],
                        "height": pg["height"],
                        "source_pdf": sf.path.name,
                    })
                if pages:
                    print(f"    ✓ {len(pages)} page(s) → SVG")
            else:
                # Raster fallback
                previews = convert_pdf_to_raster(sf.path, schem_dir, config)
                thumbs = generate_pdf_thumbnails(sf.path, schem_dir / "thumbs")
                for i, preview in enumerate(previews):
                    thumb = thumbs[i] if i < len(thumbs) else None
                    site_data["schematics"].append({
                        "name": sf.path.stem + (f" (p{i+1})" if len(previews) > 1 else ""),
                        "preview": f"assets/schematics/{preview.name}",
                        "thumbnail": f"assets/schematics/thumbs/{thumb.name}" if thumb else None,
                        "source_pdf": sf.path.name,
                    })

            # Copy original PDF for download
            shutil.copy2(sf.path, schem_dir / sf.path.name)
            site_data["downloads"].append({
                "name": sf.path.name,
                "path": f"assets/schematics/{sf.path.name}",
                "type": "Schematic PDF",
                "size": sf.size,
            })

    # ── Process Draftsman ───────────────────────────────────
    draft_files = scan.by_group("draftsman")
    if draft_files:
        print("\n📐 Processing draftsman drawings...")
        draft_dir = assets_dir / "draftsman"
        draft_dir.mkdir(parents=True, exist_ok=True)

        for df in draft_files:
            print(f"  Converting {df.path.name}...")
            # Try SVG first for the interactive viewer
            try:
                pages = convert_pdf_to_svg(df.path, draft_dir)
                for pg in pages:
                    site_data["draftsman"].append({
                        "name": df.path.stem + (f" — Page {pg['page']}" if len(pages) > 1 else ""),
                        "page_num": pg["page"],
                        "total_pages": len(pages),
                        "svg": f"assets/draftsman/{pg['svg_name']}",
                        "width": pg["width"],
                        "height": pg["height"],
                        "source_pdf": df.path.name,
                    })
                if pages:
                    site_data["draftsman_format"] = "svg"
                    print(f"    ✓ {len(pages)} page(s) → SVG")
            except Exception:
                # Fallback to raster
                previews = convert_pdf_to_raster(df.path, draft_dir, config)
                thumbs = generate_pdf_thumbnails(df.path, draft_dir / "thumbs")
                for i, preview in enumerate(previews):
                    thumb = thumbs[i] if i < len(thumbs) else None
                    site_data["draftsman"].append({
                        "name": df.path.stem + (f" (p{i+1})" if len(previews) > 1 else ""),
                        "preview": f"assets/draftsman/{preview.name}",
                        "thumbnail": f"assets/draftsman/thumbs/{thumb.name}" if thumb else None,
                    })
                site_data["draftsman_format"] = "raster"

            shutil.copy2(df.path, draft_dir / df.path.name)
            site_data["downloads"].append({
                "name": df.path.name,
                "path": f"assets/draftsman/{df.path.name}",
                "type": "Draftsman Drawing",
                "size": df.size,
            })

    # ── Process BOM ─────────────────────────────────────────
    bom_files = scan.by_group("bom")
    if bom_files:
        print("\n📋 Processing BOM...")
        bom_dir = assets_dir / "bom"
        bom_dir.mkdir(parents=True, exist_ok=True)
        bf = bom_files[0]
        print(f"  Converting {bf.path.name}...")
        bom_json = convert_bom(bf.path, bom_dir)
        if bom_json:
            site_data["bom"] = f"assets/bom/{bom_json.name}"
        shutil.copy2(bf.path, bom_dir / bf.path.name)
        site_data["downloads"].append({
            "name": bf.path.name,
            "path": f"assets/bom/{bf.path.name}",
            "type": "Bill of Materials",
            "size": bf.size,
        })

    # ── Process STEP ────────────────────────────────────────
    step_files = scan.by_group("step")
    if step_files:
        print("\n📦 Processing 3D model...")
        step_dir = assets_dir / "3d"
        step_dir.mkdir(parents=True, exist_ok=True)
        sf = step_files[0]

        # Copy original STEP for download
        shutil.copy2(sf.path, step_dir / sf.path.name)
        site_data["downloads"].append({
            "name": sf.path.name,
            "path": f"assets/3d/{sf.path.name}",
            "type": "3D Model (STEP)",
            "size": sf.size,
        })

        # Try STEP → GLB conversion (reuse cached GLB if available)
        glb_path = step_dir / f"{sf.path.stem}.glb"
        if not glb_path.exists():
            convert_result = convert_step(sf.path, step_dir, config)
            if convert_result and convert_result.suffix == ".glb":
                glb_path = convert_result
            else:
                glb_path = None
        else:
            print(f"  📦 Reusing cached {glb_path.name}")

        # Always provide the STEP path; add GLB as preferred format if available
        site_data["step"] = f"assets/3d/{sf.path.name}"
        site_data["step_format"] = "step"
        if glb_path and glb_path.exists():
            site_data["step_glb"] = f"assets/3d/{glb_path.name}"
            site_data["step_format"] = "glb"
        else:
            site_data["step_glb"] = None
            print(f"  📦 Using {sf.path.name} as-is (browser-rendered via Online3DViewer)")

        # Generate rotating GIF preview from GLB (fast) or STEP (slow)
        if config.convert.step_gif:
            gif_path = step_dir / "preview.gif"
            model_for_gif = glb_path if (glb_path and glb_path.exists()) else sf.path
            result = generate_step_gif(model_for_gif, gif_path, config)
            if result:
                site_data["step_gif"] = f"assets/3d/preview.gif"

    # ── Process Gerbers ─────────────────────────────────────
    # Prefer GerberX2 if available, fall back to legacy Gerber
    gerber_x2_files = scan.by_group("gerber_x2")
    gerber_files = scan.by_group("gerbers")
    active_gerbers = gerber_x2_files if gerber_x2_files else gerber_files
    gerber_label = "GerberX2" if gerber_x2_files else "Gerber"

    if active_gerbers:
        print(f"\n🔲 Processing {gerber_label}...")
        gerber_dir = assets_dir / "gerbers"
        gerber_dir.mkdir(parents=True, exist_ok=True)

        layers = convert_gerbers(
            [gf.path for gf in active_gerbers],
            gerber_dir,
            config,
        )
        for layer in layers:
            if layer.get("preview"):
                layer["preview"] = f"assets/gerbers/{layer['preview']}"
        site_data["gerber_layers"] = layers

        # Copy and zip
        for gf in active_gerbers:
            shutil.copy2(gf.path, gerber_dir / gf.path.name)

        # Also copy legacy Gerbers if we used X2 for rendering
        all_gerber_for_zip = list(active_gerbers)
        if gerber_x2_files and gerber_files:
            for gf in gerber_files:
                shutil.copy2(gf.path, gerber_dir / gf.path.name)
                all_gerber_for_zip.append(gf)

        _create_gerber_zip(all_gerber_for_zip, assets_dir)
        site_data["downloads"].append({
            "name": "Gerbers.zip",
            "path": "assets/Gerbers.zip",
            "type": "Fabrication Files",
            "size": (assets_dir / "Gerbers.zip").stat().st_size
            if (assets_dir / "Gerbers.zip").exists() else 0,
        })

    # ── NC Drill ────────────────────────────────────────────
    nc_files = scan.by_group("nc_drill")
    if nc_files:
        print("\n🔩 Processing NC Drill files...")
        drill_dir = assets_dir / "drill"
        drill_dir.mkdir(parents=True, exist_ok=True)
        for nf in nc_files:
            shutil.copy2(nf.path, drill_dir / nf.path.name)

        _create_zip(nc_files, assets_dir / "NC_Drill.zip")
        site_data["downloads"].append({
            "name": "NC_Drill.zip",
            "path": "assets/NC_Drill.zip",
            "type": "NC Drill Files",
            "size": (assets_dir / "NC_Drill.zip").stat().st_size
            if (assets_dir / "NC_Drill.zip").exists() else 0,
        })

    # ── Pick & Place ────────────────────────────────────────
    pp_files = scan.by_group("pick_place")
    if pp_files:
        pp_dir = assets_dir / "assembly"
        pp_dir.mkdir(parents=True, exist_ok=True)
        for pf in pp_files:
            shutil.copy2(pf.path, pp_dir / pf.path.name)
            site_data["downloads"].append({
                "name": pf.path.name,
                "path": f"assets/assembly/{pf.path.name}",
                "type": "Pick & Place",
                "size": pf.size,
            })

    # ── ODB ─────────────────────────────────────────────────
    odb_files = scan.by_group("odb")
    if odb_files:
        odb_dir = assets_dir / "odb"
        odb_dir.mkdir(parents=True, exist_ok=True)
        for of in odb_files:
            shutil.copy2(of.path, odb_dir / of.path.name)
            site_data["downloads"].append({
                "name": of.path.name,
                "path": f"assets/odb/{of.path.name}",
                "type": "ODB++ Package",
                "size": of.size,
            })

    # ── Process IBOM (Interactive BOM HTML) ──────────────────
    ibom_files = scan.by_group("ibom")
    if ibom_files:
        print("\n⚡ Processing Interactive BOM...")
        ibom_dir = assets_dir / "ibom"
        ibom_dir.mkdir(parents=True, exist_ok=True)
        ibf = ibom_files[0]
        shutil.copy2(ibf.path, ibom_dir / ibf.path.name)
        site_data["ibom"] = f"assets/ibom/{ibf.path.name}"
        print(f"  ✓ Copied {ibf.path.name}")

    # ── Generate HTML ───────────────────────────────────────
    print("\n🌐 Generating site...")
    site_data_json = json.dumps(site_data, indent=2, default=str)

    template_path = Path(__file__).parent.parent / "templates" / "index.html"
    if template_path.exists():
        with open(template_path) as f:
            template = f.read()
    else:
        from ..template import get_template
        template = get_template()

    accent_dark = config.site.accent_color_dark or config.site.accent_color

    html = template.replace("{{SITE_DATA}}", site_data_json)
    html = html.replace("{{PROJECT_NAME}}", site_data["project"]["name"])
    html = html.replace("{{PROJECT_DESCRIPTION}}", site_data["project"]["description"])
    html = html.replace("{{ACCENT_COLOR}}", site_data["site"]["accent_color"])
    html = html.replace("{{ACCENT_COLOR_DARK}}", accent_dark)
    html = html.replace("{{THEME}}", site_data["site"]["theme"])

    index_path = output_dir / "index.html"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)

    (output_dir / ".nojekyll").touch()

    print(f"\n✅ Site generated at: {output_dir}")
    print(f"   Open {index_path} to preview locally")

    return output_dir


def _create_gerber_zip(gerber_files, assets_dir: Path):
    """Create a ZIP archive of all Gerber files."""
    zip_path = assets_dir / "Gerbers.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for gf in gerber_files:
            zf.write(gf.path, gf.path.name)


def _create_zip(files, zip_path: Path):
    """Create a ZIP archive from a list of FoundFile objects."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f.path, f.path.name)
