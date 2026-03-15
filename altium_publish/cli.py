"""Command-line interface for altium-publish."""

from __future__ import annotations

import argparse
import http.server
import os
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__
from .config import Config, CONFIG_FILE_NAME, find_config


BANNER = r"""
   ___  ____  _                 ___       __   ___     __  
  / _ |/ / /_(_)_ ____ _       / _ \__ __/ /  / (_)__ / /  
 / __ / / __/ / // /  ' \     / ___/ // / _ \/ / (_-</ _ \ 
/_/ |_/_/\__/_/\_,_/_/_/_/   /_/   \_,_/_.__/_/_/___/_//_/ 
"""


def main():
    parser = argparse.ArgumentParser(
        prog="altium-publish",
        description="Publish Altium Designer projects to GitHub Pages",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ── init ────────────────────────────────────────────────
    init_parser = sub.add_parser("init", help="Initialize a new altium-publish config")
    init_parser.add_argument("--release-dir", default="Release",
                             help="Path to Altium release directory")
    init_parser.add_argument("--repo", default="",
                             help="GitHub repo (owner/name)")

    # ── scan ────────────────────────────────────────────────
    sub.add_parser("scan", help="Scan release directory and show found files")

    # ── build ───────────────────────────────────────────────
    build_parser = sub.add_parser("build", help="Build the GitHub Pages site")
    build_parser.add_argument("--clean", action="store_true",
                              help="Clean output directory before building")

    # ── release ─────────────────────────────────────────────
    release_parser = sub.add_parser("release",
                                    help="Build site + create GitHub release")
    release_parser.add_argument("--version", dest="tag_version",
                                help="Version tag (e.g. v1.0.0)")
    release_parser.add_argument("--changelog", default="",
                                help="Changelog text (prompted if empty)")
    release_parser.add_argument("--no-push", action="store_true",
                                help="Don't push to GitHub")

    # ── preview ─────────────────────────────────────────────
    preview_parser = sub.add_parser("preview", help="Preview the site locally")
    preview_parser.add_argument("--port", type=int, default=8080,
                                help="Port for local server")

    args = parser.parse_args()

    if not args.command:
        print(BANNER)
        parser.print_help()
        return

    if args.command == "init":
        cmd_init(args)
    elif args.command == "scan":
        cmd_scan(args)
    elif args.command == "build":
        cmd_build(args)
    elif args.command == "release":
        cmd_release(args)
    elif args.command == "preview":
        cmd_preview(args)


def cmd_init(args):
    """Initialize config file."""
    print(BANNER)
    config_path = Path(CONFIG_FILE_NAME)
    if config_path.exists():
        print(f"⚠️  {CONFIG_FILE_NAME} already exists. Overwrite? [y/N] ", end="")
        if input().strip().lower() != "y":
            return

    config = Config()
    config.release_dir = args.release_dir

    # Try to detect project name from directory
    project_dir = Path.cwd()
    config.project.name = project_dir.name

    # Try to detect repo from git remote
    import subprocess
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True,
        )
        remote_url = result.stdout.strip()
        if "github.com" in remote_url:
            # Parse owner/repo from URL
            if remote_url.startswith("git@"):
                repo = remote_url.split(":")[-1].replace(".git", "")
            else:
                parts = remote_url.rstrip("/").split("/")
                repo = "/".join(parts[-2:]).replace(".git", "")
            config.project.repo = repo
    except Exception:
        pass

    if args.repo:
        config.project.repo = args.repo

    config.save(config_path)
    print(f"✅ Created {CONFIG_FILE_NAME}")
    print(f"   Project: {config.project.name}")
    print(f"   Repo: {config.project.repo or '(not set)'}")
    print(f"   Release dir: {config.release_dir}")
    print(f"\n   Edit the config file to customize file paths and settings.")
    print(f"   Then run: altium-publish scan")


def cmd_scan(args):
    """Scan and display found files."""
    config = _load_config()
    from .scanner import scan
    result = scan(config)
    print(BANNER)
    print(result.summary())


def cmd_build(args):
    """Build the site."""
    config = _load_config()
    print(BANNER)
    print(f"🔨 Building site for: {config.project.name}\n")

    if args.clean:
        import shutil
        output_dir = Path(config.output_dir)
        if output_dir.exists():
            shutil.rmtree(output_dir)
            print(f"  🗑️  Cleaned {output_dir}")

    from .scanner import scan
    from .converters.site import build_site

    result = scan(config)
    print(result.summary())
    build_site(config, result)


def cmd_release(args):
    """Build + release."""
    import os
    config = _load_config()
    print(BANNER)
    print(f"🚀 Release pipeline for: {config.project.name}\n")

    # Check for GitHub token early
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token and not args.no_push:
        print("  ⚠️  GITHUB_TOKEN not set. Release will commit, tag, and push,")
        print("     but won't create a GitHub Release via API.")
        print("     Set it with: export GITHUB_TOKEN=ghp_your_token_here\n")

    # Build first
    from .scanner import scan
    from .converters.site import build_site
    from .github import create_release, prompt_changelog, prompt_version

    result = scan(config)
    print(result.summary())
    output_dir = build_site(config, result)

    # Get version
    version = args.tag_version or prompt_version(config)

    # Get changelog
    changelog = args.changelog or prompt_changelog()

    create_release(config, version, changelog, output_dir, args_no_push=args.no_push)


def cmd_preview(args):
    """Start a local preview server."""
    config = _load_config()
    output_dir = Path(config.output_dir)
    if not (output_dir / "index.html").exists():
        print("⚠️  No site found. Run 'altium-publish build' first.")
        return

    port = args.port
    os.chdir(output_dir)

    handler = http.server.SimpleHTTPRequestHandler
    server = http.server.HTTPServer(("", port), handler)

    url = f"http://localhost:{port}"
    print(f"🌐 Preview server at: {url}")
    print("   Press Ctrl+C to stop\n")

    # Open in browser
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        print("\n   Server stopped.")


def _load_config() -> Config:
    """Find and load config, or exit with error."""
    config_path = find_config()
    if not config_path:
        print(f"❌ No {CONFIG_FILE_NAME} found.")
        print(f"   Run 'altium-publish init' to create one.")
        sys.exit(1)
    return Config.load(config_path)


if __name__ == "__main__":
    main()
