"""Fallback: load template from the installed package."""

from pathlib import Path


def get_template() -> str:
    """Load the index.html template."""
    template_path = Path(__file__).parent / "templates" / "index.html"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Template not found at {template_path}")
