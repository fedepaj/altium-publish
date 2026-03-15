# altium-publish

**Publish your Altium Designer PCB projects as beautiful, interactive GitHub Pages.**

Turn your Altium OutJob release output into a professional project page — zero frontend code required.

> **Platform:** Currently tested on macOS only. Linux/Windows support is planned but not yet verified.

## Features

- **Schematic viewer** — zoomable vector SVG schematics with pan, zoom and multi-page navigation
- **Draftsman drawings** — PDF drawings converted to interactive SVG, viewable in the browser
- **3D PCB viewer** — interactive STEP/GLB model viewer powered by [Online3DViewer](https://github.com/nicolo-ribaudo/Online3DViewer), with automatic STEP→GLB conversion for faster loading
- **3D rotating GIF** — auto-generated animated preview of your PCB, ready for your project README
- **Interactive BOM** — searchable, sortable component table from Excel/CSV bill of materials
- **Gerber layer viewer** — multi-layer overlay with per-layer toggle, color coding, pan & zoom (aligned across all layers)
- **Downloads** — all release assets (Gerbers ZIP, STEP, BOM, Pick&Place, ODB++, NC Drill) organized and ready to download

## Prerequisites

- **Python 3.10+**
- **Node.js** (for Gerber rendering via `@tracespace/cli`)
- **pipx** (recommended on macOS)

### Why pipx?

On macOS, the system Python environment is externally managed and `pip install` will refuse to install packages globally. `pipx` solves this by installing each CLI tool in its own isolated virtual environment:

```bash
brew install pipx
pipx ensurepath
```

## Installation

### From source (recommended for now)

Clone the repo and install with all dependencies:

```bash
git clone https://github.com/user/altium-publish.git
cd altium-publish
pipx install -e ".[full]"
```

The `[full]` extra installs everything needed for all features:

| Package | Purpose |
|---------|---------|
| PyMuPDF | PDF → SVG conversion (schematics, draftsman) |
| Pillow | Image processing |
| openpyxl | Excel BOM reading |
| trimesh + cascadio | STEP → GLB 3D model conversion |
| pyrender | 3D GIF rendering (offscreen OpenGL) |
| scipy + numpy | Fast mesh processing |

### Future (once published to PyPI)

```bash
pipx install altium-publish[full]
```

## Quick Start

### 1. Initialize the config

Navigate to your Altium project repo and run:

```bash
cd ~/Documents/MyPCBProject
altium-publish init
```

This creates `altium-publish.yaml` with auto-detected project name and GitHub remote.

### 2. Edit the config

Open `altium-publish.yaml` and adjust the `files` section to match your OutJob folder structure. The default assumes:

```
Release/
├── DOCS/
│   ├── Schematic Print/    ← PDF schematics
│   ├── PCBDrawing/         ← Draftsman PDF
│   └── ExportSTEP/         ← 3D STEP model
└── FAB/
    ├── BOM/                ← Bill of Materials
    ├── Gerber/             ← Legacy Gerber (RS-274X)
    ├── GerberX2/           ← GerberX2 (preferred)
    ├── NC Drill/           ← Drill files
    ├── Pick Place/         ← Assembly files
    └── ODB/                ← ODB++ package
```

Change `path` and `patterns` for each group to match your actual OutJob output paths. See [`altium-publish.example.yaml`](altium-publish.example.yaml) for a fully commented template.

### 3. Run your Altium Release

Run your OutJob in Altium Designer as usual. The release files should land in the directory specified by `release_dir` in your config (default: `Release/`).

### 4. Verify with scan

Check that altium-publish finds all your files:

```bash
altium-publish scan
```

This lists every detected file grouped by type. If something is missing, adjust your config paths/patterns.

### 5. Build the site

```bash
altium-publish build
```

This will:
1. Convert schematics PDF → SVG (vector, zoomable)
2. Convert draftsman PDF → SVG
3. Parse the BOM Excel → interactive JSON table
4. Convert STEP → GLB (faster browser loading)
5. Generate a rotating 3D GIF preview
6. Render Gerber layers → aligned SVG overlays (via `@tracespace/cli`)
7. Package everything into a static site in `docs/`

### 6. Preview locally

```bash
altium-publish preview
```

Opens a local server at `http://localhost:8000` so you can check everything before publishing.

### 7. Release

When you're ready to publish:

```bash
altium-publish release
```

This will:
1. Build/update the site in `docs/`
2. Prompt for a version tag (auto-increments from latest, e.g. `v1.0.0` → `v1.0.1`)
3. Prompt for a changelog
4. Commit, tag, push, and create a GitHub Release

If the push fails (e.g. branch is behind remote), it won't crash — commit and tag are created locally and you get the manual push commands.

### GitHub Token (optional but recommended)

A `GITHUB_TOKEN` is needed to automatically create GitHub Releases and upload assets via the API. Without it, `altium-publish release` will still commit, tag, and push, but you'll need to create the release manually on GitHub.

Create a [Personal Access Token](https://github.com/settings/tokens) with `repo` scope:

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

Add it to your `~/.zshrc` or `~/.bashrc` to persist it across sessions.

## GitHub Pages Setup

1. Go to your repo → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: `main`, folder: `/docs`
4. Save

Your site will be live at `https://<username>.github.io/<repo>/`

## Configuration Reference

Everything is controlled by `altium-publish.yaml`:

### `project` — Project metadata

```yaml
project:
  name: "My PCB Project"           # Shown in the site header
  description: "Short description"  # Shown below the title
  author: "Your Name"
  repo: "username/my-pcb-project"   # GitHub owner/repo
  version_prefix: "v"              # Tag prefix (v1.0.0)
```

### `files` — OutJob folder mapping

Maps each output group to a subfolder under `release_dir`. Each group has a `path` (relative to `release_dir`) and `patterns` (glob patterns):

```yaml
release_dir: "Release"

files:
  schematics:
    path: "DOCS/Schematic Print"
    patterns: ["*.PDF", "*.pdf"]
  bom:
    path: "FAB/BOM"
    patterns: ["*.xlsx", "*.csv"]
  gerber_x2:
    path: "FAB/GerberX2"
    patterns: ["*.gbr"]
  step:
    path: "DOCS/ExportSTEP"
    patterns: ["*.step", "*.stp"]
```

### `convert` — Conversion settings

```yaml
convert:
  schematic_format: "svg"    # "svg" (vector) or "webp" (raster)
  pdf_dpi: 200               # DPI for raster fallback
  step_format: "glb"         # "glb" (auto-convert) or "keep" (serve STEP as-is)
  step_gif: true             # Generate rotating 3D preview GIF
  step_gif_frames: 36        # Number of frames (more = smoother but larger)
  step_gif_size: [640, 480]  # Resolution in pixels
  gerber_render: true         # Render Gerber layer previews
  gerber_tool: "auto"        # "auto", "tracespace", "gerbv", or "pygerber"
  bom_interactive: true       # Searchable/sortable BOM table
```

### `site` — Appearance

```yaml
site:
  theme: "dark"              # "dark" or "light"
  accent_color: "#00d4aa"    # Primary accent color
  sections:                  # Tabs shown in the UI (order matters)
    - schematics
    - draftsman
    - pcb3d
    - bom
    - gerbers
    - downloads
```

### `github` — Release settings

```yaml
github:
  create_release: true       # Create GitHub Release on publish
  draft: false               # Create as draft release
  upload_assets: true        # Attach files to the release
  asset_patterns: ["*.zip", "*.pdf", "*.step", "*.xlsx"]
  pages_branch: "gh-pages"
  pages_dir: "docs"
```

## CLI Reference

```
altium-publish init                     Initialize config in current directory
altium-publish scan                     Show discovered release files
altium-publish build                    Generate the GitHub Pages site
altium-publish build --clean            Clean output before building
altium-publish preview                  Start local preview server
altium-publish preview --port 3000      Custom preview port
altium-publish release                  Build + tag + push + GitHub Release
altium-publish release --version v2.0   Set version explicitly
altium-publish release --no-push        Build only, don't push
```

## External Tools

These are not Python packages — they are standalone tools that altium-publish calls if available:

| Feature | Tool | Install |
|---------|------|---------|
| Gerber → SVG (best quality) | `@tracespace/cli` | Requires Node.js. Auto-invoked via `npx` |
| Gerber → SVG (alternative) | `gerbv` | `brew install gerbv` |

If no Gerber renderer is found, layers are cataloged for download but no visual preview is generated.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `GITHUB_TOKEN` | GitHub API token for creating releases and uploading assets |
| `GH_TOKEN` | Alternative token variable (compatible with GitHub CLI) |

## How It Works

1. **Scan** — Reads `altium-publish.yaml` and finds all release files matching the configured patterns
2. **Convert** — Transforms source files into web-friendly formats:
   - PDF → SVG (vector schematics and draftsman drawings)
   - STEP → GLB (smaller, faster-loading 3D model)
   - GLB → GIF (rotating 3D preview animation)
   - Gerber → SVG (per-layer renders, normalized to a common coordinate system for overlay alignment)
   - Excel → JSON (interactive BOM table)
3. **Generate** — Produces a single `index.html` with all data embedded, plus assets in `docs/assets/`
4. **Publish** — Commits to git, tags, pushes, and optionally creates a GitHub Release with attached files

The generated site is fully static (no backend, no build step) and works with GitHub Pages out of the box.

## License

MIT
