"""Scan Altium release directory and categorize files."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, FileGroupConfig


@dataclass
class FoundFile:
    """A discovered file with metadata."""
    path: Path
    relative: str          # relative to release_dir
    group: str             # e.g. "schematics", "bom", "gerbers"
    size: int = 0
    
    def __post_init__(self):
        if self.path.exists():
            self.size = self.path.stat().st_size

    @property
    def size_human(self) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if self.size < 1024:
                return f"{self.size:.1f} {unit}"
            self.size /= 1024
        return f"{self.size:.1f} TB"


@dataclass
class ScanResult:
    """Result of scanning a release directory."""
    files: list[FoundFile] = field(default_factory=list)
    release_dir: Path = field(default_factory=Path)
    warnings: list[str] = field(default_factory=list)

    def by_group(self, group: str) -> list[FoundFile]:
        return [f for f in self.files if f.group == group]

    @property
    def groups(self) -> list[str]:
        seen = []
        for f in self.files:
            if f.group not in seen:
                seen.append(f.group)
        return seen

    def summary(self) -> str:
        lines = [f"📁 Release directory: {self.release_dir}"]
        for group in self.groups:
            group_files = self.by_group(group)
            lines.append(f"  {_group_icon(group)} {group}: {len(group_files)} file(s)")
            for f in group_files:
                lines.append(f"      {f.path.name}")
        if self.warnings:
            lines.append("")
            for w in self.warnings:
                lines.append(f"  ⚠️  {w}")
        return "\n".join(lines)


def scan(config: Config) -> ScanResult:
    """Scan the release directory and categorize all files."""
    release_dir = Path(config.release_dir).resolve()
    result = ScanResult(release_dir=release_dir)

    if not release_dir.exists():
        result.warnings.append(f"Release directory not found: {release_dir}")
        return result

    # Build group definitions from config
    groups: dict[str, FileGroupConfig] = {}
    files_cfg = config.files
    for group_name in files_cfg.__dataclass_fields__:
        group_cfg: FileGroupConfig = getattr(files_cfg, group_name)
        if group_cfg.enabled:
            groups[group_name] = group_cfg

    # Track which files have been claimed to avoid duplicates
    claimed: set[Path] = set()

    # Scan each group
    for group_name, group_cfg in groups.items():
        search_dir = release_dir / group_cfg.path if group_cfg.path else release_dir

        if not search_dir.exists():
            # Try case-insensitive search
            search_dir = _find_dir_icase(release_dir, group_cfg.path)
            if not search_dir:
                continue

        # Recursively find matching files
        for pattern in group_cfg.patterns:
            for fpath in _glob_recursive(search_dir, pattern):
                if fpath in claimed:
                    continue
                if fpath.is_file():
                    claimed.add(fpath)
                    result.files.append(FoundFile(
                        path=fpath,
                        relative=str(fpath.relative_to(release_dir)),
                        group=group_name,
                    ))

    # Sort files within each group by name
    result.files.sort(key=lambda f: (f.group, f.path.name.lower()))

    # Warnings for empty expected groups
    for group_name, group_cfg in groups.items():
        if not result.by_group(group_name):
            result.warnings.append(f"No {group_name} files found (expected in '{group_cfg.path}')")

    return result


def _glob_recursive(directory: Path, pattern: str) -> list[Path]:
    """Recursively glob for files matching a pattern (case-insensitive on name)."""
    matches = []
    if not directory.exists():
        return matches
    for fpath in directory.rglob("*"):
        if fpath.is_file() and _match_pattern(fpath.name, pattern):
            matches.append(fpath)
    return matches


def _match_pattern(name: str, pattern: str) -> bool:
    """Case-insensitive fnmatch."""
    return fnmatch.fnmatch(name.lower(), pattern.lower())


def _find_dir_icase(base: Path, rel_path: str) -> Path | None:
    """Find a directory with case-insensitive path matching."""
    if not rel_path:
        return base
    parts = Path(rel_path).parts
    current = base
    for part in parts:
        found = None
        if current.is_dir():
            for child in current.iterdir():
                if child.is_dir() and child.name.lower() == part.lower():
                    found = child
                    break
        if found is None:
            return None
        current = found
    return current


def _group_icon(group: str) -> str:
    icons = {
        "schematics": "📄",
        "draftsman": "📐",
        "bom": "📋",
        "gerbers": "🔲",
        "gerber_x2": "🔳",
        "nc_drill": "🔩",
        "step": "📦",
        "pick_place": "🎯",
        "odb": "📀",
        "extra_docs": "📑",
    }
    return icons.get(group, "📎")
