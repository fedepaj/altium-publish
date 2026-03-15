"""GitHub integration: releases, tags, and pages deployment."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .config import Config


def prompt_changelog() -> str:
    """Interactively prompt the user for a changelog entry."""
    print("\n📝 Enter changelog for this release (press Enter twice to finish):")
    print("   Tip: Use markdown formatting for the GitHub release notes.\n")
    
    lines = []
    empty_count = 0
    while True:
        try:
            line = input("   ")
            if line == "":
                empty_count += 1
                if empty_count >= 2:
                    break
                lines.append("")
            else:
                empty_count = 0
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            break

    return "\n".join(lines).strip()


def prompt_version(config: Config) -> str:
    """Prompt for the version tag."""
    prefix = config.project.version_prefix

    # Try to detect the latest tag
    latest = _get_latest_tag(prefix)
    if latest:
        suggested = _increment_version(latest, prefix)
        print(f"\n🏷️  Latest tag: {latest}")
        version = input(f"   Version tag [{suggested}]: ").strip()
        return version if version else suggested
    else:
        print(f"\n🏷️  No existing tags found.")
        version = input(f"   Version tag (e.g. {prefix}1.0.0): ").strip()
        if not version:
            version = f"{prefix}1.0.0"
        return version


def create_release(
    config: Config,
    version: str,
    changelog: str,
    output_dir: Path,
    args_no_push: bool = False,
) -> bool:
    """
    Create a GitHub release with the given version and changelog.
    
    Steps:
    1. Commit the docs/ folder changes
    2. Create a git tag
    3. Push to remote
    4. Create a GitHub Release via API (if token available)
    """
    repo = config.project.repo
    if not repo:
        print("  ⚠️  No repo configured in altium-publish.yaml")
        return False

    print(f"\n🚀 Creating release {version}...")

    # Stage and commit
    print("  📤 Committing site changes...")
    _run_git(["add", str(output_dir)])
    _run_git(["add", "altium-publish.yaml"])  # also track config
    
    commit_msg = f"release: {version}\n\n{changelog}"
    _run_git(["commit", "-m", commit_msg, "--allow-empty"])

    # Tag
    print(f"  🏷️  Creating tag {version}...")
    _run_git(["tag", "-a", version, "-m", f"Release {version}\n\n{changelog}"])

    # Push
    push_ok = True
    if not args_no_push:
        print("  📤 Pushing to remote...")
        branch_push = _run_git(["push", "origin", "HEAD"], check=False)
        if branch_push.returncode != 0:
            push_ok = False
            print("  ⚠️  Branch push failed (local branch may be behind remote).")
            print("     Commit and tag were created locally. Push manually with:")
            print(f"       git push origin HEAD && git push origin {version}")
        else:
            tag_push = _run_git(["push", "origin", version], check=False)
            if tag_push.returncode != 0:
                push_ok = False
                print(f"  ⚠️  Tag push failed. Push it manually: git push origin {version}")

    # Create GitHub Release via API
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and push_ok and not args_no_push:
        _create_github_release(repo, version, changelog, token, config, output_dir)
    elif not token and push_ok and not args_no_push:
        print("  ℹ️  No GITHUB_TOKEN found, skipping API release creation.")
        print(f"     Create it manually at: https://github.com/{repo}/releases/new?tag={version}")
        print(f"     Or set GITHUB_TOKEN env var for automatic release creation.")

    # Summary
    if push_ok and not args_no_push:
        print(f"\n✅ Release {version} published!")
        if config.github.pages_branch == "gh-pages":
            print(f"   Pages will be served from the '{config.github.pages_dir}' folder on main branch")
        print(f"   🌐 https://{_get_pages_url(repo)}")
        print(f"   📦 https://github.com/{repo}/releases/tag/{version}")
    elif args_no_push:
        print(f"\n✅ Release {version} created locally (--no-push).")
        print(f"   Push when ready: git push origin HEAD && git push origin {version}")
    else:
        print(f"\n⚠️  Release {version} created locally but push failed.")
        print(f"   Push manually: git push origin HEAD && git push origin {version}")

    return True


def deploy_pages(config: Config, output_dir: Path) -> bool:
    """
    Deploy to GitHub Pages.
    
    Two strategies:
    1. Pages from docs/ folder on main branch (simpler, default)
    2. Pages from gh-pages branch (more separation)
    """
    if config.github.pages_branch == "gh-pages":
        return _deploy_ghpages_branch(config, output_dir)
    else:
        # docs/ folder strategy - just commit and push
        _run_git(["add", str(output_dir)])
        _run_git(["commit", "-m", "docs: update project page"])
        _run_git(["push", "origin", "HEAD"])
        return True


def _deploy_ghpages_branch(config: Config, output_dir: Path) -> bool:
    """Deploy using gh-pages branch."""
    try:
        # Use ghp-import if available
        import ghp_import
        ghp_import.ghp_import(str(output_dir), push=True)
        return True
    except ImportError:
        pass

    # Manual gh-pages deployment
    print("  Deploying to gh-pages branch...")
    _run_git(["checkout", "--orphan", "gh-pages"])
    _run_git(["rm", "-rf", "."])
    
    # Copy output files to root
    import shutil
    for item in output_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, ".")
        elif item.is_dir():
            shutil.copytree(item, item.name, dirs_exist_ok=True)
    
    _run_git(["add", "."])
    _run_git(["commit", "-m", "Deploy to GitHub Pages"])
    _run_git(["push", "origin", "gh-pages", "--force"])
    _run_git(["checkout", "-"])
    
    return True


def _create_github_release(
    repo: str,
    version: str,
    changelog: str,
    token: str,
    config: Config,
    output_dir: Path,
):
    """Create a release via GitHub API."""
    import urllib.request
    
    url = f"https://api.github.com/repos/{repo}/releases"
    data = {
        "tag_name": version,
        "name": f"{config.project.name} {version}",
        "body": changelog,
        "draft": config.github.draft,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github.v3+json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as response:
            release = json.loads(response.read())
            print(f"  ✅ GitHub Release created: {release['html_url']}")

            # Upload assets if configured
            if config.github.upload_assets:
                _upload_release_assets(release, token, output_dir, config)

    except Exception as e:
        print(f"  ⚠️  Failed to create GitHub Release: {e}")


def _upload_release_assets(release: dict, token: str, output_dir: Path, config: Config):
    """Upload files to a GitHub Release."""
    import fnmatch
    import urllib.request
    
    upload_url = release["upload_url"].replace("{?name,label}", "")
    assets_dir = output_dir / "assets"
    
    if not assets_dir.exists():
        return

    for pattern in config.github.asset_patterns:
        for fpath in assets_dir.rglob("*"):
            if fpath.is_file() and fnmatch.fnmatch(fpath.name, pattern):
                print(f"  📎 Uploading {fpath.name}...")
                try:
                    with open(fpath, "rb") as f:
                        file_data = f.read()
                    
                    req = urllib.request.Request(
                        f"{upload_url}?name={fpath.name}",
                        data=file_data,
                        headers={
                            "Authorization": f"token {token}",
                            "Content-Type": "application/octet-stream",
                        },
                        method="POST",
                    )
                    urllib.request.urlopen(req)
                except Exception as e:
                    print(f"  ⚠️  Failed to upload {fpath.name}: {e}")


def _run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command."""
    try:
        return subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, check=check,
        )
    except subprocess.CalledProcessError as e:
        print(f"  ⚠️  git {' '.join(args)} failed: {e.stderr.strip()}")
        if check:
            raise
        return e


def _get_latest_tag(prefix: str) -> Optional[str]:
    """Get the latest semver tag."""
    try:
        result = subprocess.run(
            ["git", "tag", "--list", f"{prefix}*", "--sort=-v:refname"],
            capture_output=True, text=True,
        )
        tags = result.stdout.strip().split("\n")
        return tags[0] if tags[0] else None
    except Exception:
        return None


def _increment_version(tag: str, prefix: str) -> str:
    """Increment the patch version of a tag."""
    # removeprefix treats prefix as a string, not a character set (unlike lstrip)
    version = tag.removeprefix(prefix) if tag.startswith(prefix) else tag
    parts = version.split(".")
    # Ensure we have at least 3 parts (major.minor.patch)
    while len(parts) < 3:
        parts.append("0")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except ValueError:
        parts[-1] = "1"
    return prefix + ".".join(parts)


def _get_pages_url(repo: str) -> str:
    """Get the GitHub Pages URL for a repo."""
    parts = repo.split("/")
    if len(parts) == 2:
        return f"{parts[0]}.github.io/{parts[1]}"
    return repo
