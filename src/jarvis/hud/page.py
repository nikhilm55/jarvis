"""The HUD page (HTML, CSS and JS in one file, no external requests)."""

from pathlib import Path

PAGE_PATH = Path(__file__).with_name("page.html")


def read_page() -> str:
    """Return the HUD page text."""
    return PAGE_PATH.read_text(encoding="utf-8")
