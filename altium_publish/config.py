"""Configuration loader and schema for altium-publish."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ProjectConfig:
    """Top-level project metadata."""
    name: str = "My PCB Project"
    description: str = ""
    author: str = ""
    license: str = ""
    repo: str = ""                    # e.g. "username/repo"
    url: str = ""                     # custom domain or auto-generated
    version_prefix: str = "v"         # tag prefix, e.g. v1.0.0


@dataclass
class FileGroupConfig:
    """Mapping for a group of release files."""
    path: str = ""
    patterns: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class FilesConfig:
    """All file group mappings."""
    schematics: FileGroupConfig = field(default_factory=lambda: FileGroupConfig(
        path="DOCS/Schematic Print", patterns=["*.pdf", "*.PDF"]
    ))
    draftsman: FileGroupConfig = field(default_factory=lambda: FileGroupConfig(
        path="DOCS/PCBDrawing", patterns=["*.pdf", "*.PDF"]
    ))
    bom: FileGroupConfig = field(default_factory=lambda: FileGroupConfig(
        path="FAB/BOM", patterns=["*.xlsx", "*.csv", "*BOM*", "*bom*"]
    ))
    gerbers: FileGroupConfig = field(default_factory=lambda: FileGroupConfig(
        path="FAB/Gerber", patterns=[
            "*.GBL", "*.GBO", "*.GBP", "*.GBS",
            "*.GTL", "*.GTO", "*.GTP", "*.GTS",
            "*.GKO", "*.GM1", "*.GM2",
        ]
    ))
    gerber_x2: FileGroupConfig = field(default_factory=lambda: FileGroupConfig(
        path="FAB/GerberX2", patterns=["*.gbr"]
    ))
    nc_drill: FileGroupConfig = field(default_factory=lambda: FileGroupConfig(
        path="FAB/NC Drill", patterns=["*.TXT", "*.DRR", "*.LDP"]
    ))
    step: FileGroupConfig = field(default_factory=lambda: FileGroupConfig(
        path="DOCS/ExportSTEP", patterns=["*.step", "*.stp", "*.STEP", "*.STP"]
    ))
    pick_place: FileGroupConfig = field(default_factory=lambda: FileGroupConfig(
        path="FAB/Pick Place", patterns=["*Pick*Place*", "*pick*place*", "*.pos", "*.csv", "*.txt"]
    ))
    odb: FileGroupConfig = field(default_factory=lambda: FileGroupConfig(
        path="FAB/ODB", patterns=["*.tgz", "*.zip"],
        enabled=True
    ))
    ibom: FileGroupConfig = field(default_factory=lambda: FileGroupConfig(
        path="DOCS/IBOM", patterns=["*.html", "*.htm"],
        enabled=True
    ))
    extra_docs: FileGroupConfig = field(default_factory=lambda: FileGroupConfig(
        path="DOCS", patterns=["*.pdf", "*.PDF"],
        enabled=False
    ))


@dataclass
class ConvertConfig:
    """Conversion settings."""
    schematic_format: str = "svg"     # svg (vector, zoomable) or raster (webp/png)
    pdf_dpi: int = 200
    pdf_format: str = "webp"          # webp or png (for draftsman/raster)
    step_format: str = "glb"          # glb or keep (serve STEP as-is)
    bom_interactive: bool = True
    gerber_render: bool = True
    gerber_tool: str = "auto"         # auto, tracespace, gerbv, pygerber
    step_gif: bool = True             # generate rotating 3D preview GIF
    step_gif_frames: int = 36         # number of frames in the GIF
    step_gif_size: list[int] = field(default_factory=lambda: [640, 480])


@dataclass
class SiteConfig:
    """GitHub Pages site generation settings."""
    title: str = ""                   # defaults to project.name
    theme: str = "dark"               # dark or light
    accent_color: str = "#00d4aa"
    accent_color_dark: str = ""       # if empty, uses accent_color for dark too
    logo: str = ""                    # path to project logo
    sections: list[str] = field(default_factory=lambda: [
        "overview", "schematics", "draftsman", "pcb3d", "bom", "gerbers", "downloads"
    ])
    custom_css: str = ""
    custom_sections: list[dict] = field(default_factory=list)


@dataclass
class GithubConfig:
    """GitHub release settings."""
    create_release: bool = True
    draft: bool = False
    upload_assets: bool = True        # attach zip to release
    asset_patterns: list[str] = field(default_factory=lambda: [
        "*.zip", "*.pdf", "*.step", "*.xlsx"
    ])
    pages_branch: str = "gh-pages"
    pages_dir: str = "docs"           # or root "/"


@dataclass
class Config:
    """Root configuration object."""
    project: ProjectConfig = field(default_factory=ProjectConfig)
    files: FilesConfig = field(default_factory=FilesConfig)
    convert: ConvertConfig = field(default_factory=ConvertConfig)
    site: SiteConfig = field(default_factory=SiteConfig)
    github: GithubConfig = field(default_factory=GithubConfig)
    release_dir: str = "Release"
    output_dir: str = "docs"

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        """Load config from YAML file, merging with defaults."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path) as f:
            raw = yaml.safe_load(f) or {}

        config = cls()
        _merge_dataclass(config, raw)
        
        # Auto-fill site title from project name
        if not config.site.title:
            config.site.title = config.project.name

        return config

    def save(self, path: str | Path) -> None:
        """Save config to YAML file."""
        path = Path(path)
        data = _dataclass_to_dict(self)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _merge_dataclass(obj, data: dict):
    """Recursively merge a dict into a dataclass instance."""
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if not hasattr(obj, key):
            continue
        current = getattr(obj, key)
        if hasattr(current, "__dataclass_fields__"):
            _merge_dataclass(current, value)
        else:
            setattr(obj, key, value)


def _dataclass_to_dict(obj) -> dict:
    """Recursively convert dataclass to dict."""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for k in obj.__dataclass_fields__:
            val = getattr(obj, k)
            if val is not None:
                result[k] = _dataclass_to_dict(val)
        return result
    elif isinstance(obj, list):
        return [_dataclass_to_dict(i) for i in obj]
    return obj


CONFIG_FILE_NAME = "altium-publish.yaml"


def find_config(start_dir: str | Path = ".") -> Optional[Path]:
    """Walk up directories looking for config file."""
    current = Path(start_dir).resolve()
    while current != current.parent:
        candidate = current / CONFIG_FILE_NAME
        if candidate.exists():
            return candidate
        current = current.parent
    return None
