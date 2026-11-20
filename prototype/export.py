"""Card export: the HTML is the deliverable; PDF only when Playwright + Chromium are installed (optional)."""
from __future__ import annotations

from pathlib import Path


def pdf_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def html_to_pdf(html_path: str | Path, timeout_ms: int = 60_000) -> bytes | None:
    """A4 PDF of a card file at 100 % (same as the template's print setting). None when not possible."""
    if not pdf_available():
        return None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(Path(html_path).resolve().as_uri(), wait_until="load", timeout=timeout_ms)
            page.emulate_media(media="print")
            pdf = page.pdf(format="A4", print_background=True, margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                           prefer_css_page_size=True)
            browser.close()
            return pdf
    except Exception:  # noqa: BLE001 – the HTML download always remains
        return None


PRINT_HELP = ("Open the HTML card in Chrome → Drucken / PDF → A4, scale 100 %, no browser headers/footers. "
              "To enable one-click PDFs here: `pip install playwright && python -m playwright install chromium`.")
