"""Full-page screenshots of every step (Playwright). The server must be running:

    ./run_prototype.sh                          # or: streamlit run prototype/app.py --server.headless true
    python prototype/tools/screenshots.py [--base http://localhost:8501] [--mode demo|live] [--out prototype/screenshots]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

STEPS = {1: "signals", 2: "proposals", 3: "decision", 4: "recipes", 5: "result"}


def settle(page, seconds: float = 2.5):
    """Streamlit renders progressively: wait for the running indicator to disappear, then a little longer for iframes."""
    page.wait_for_load_state("networkidle", timeout=60_000)
    for _ in range(40):
        if page.locator('[data-testid="stStatusWidget"]').count() == 0:
            break
        time.sleep(0.5)
    time.sleep(seconds)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8501")
    ap.add_argument("--mode", default="demo", choices=["demo", "live"])
    ap.add_argument("--out", default="prototype/screenshots")
    ap.add_argument("--width", type=int, default=1440)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": a.width, "height": 900}, device_scale_factor=1)
        for n, name in STEPS.items():
            page.goto(f"{a.base}/?mode={a.mode}&step={n}", wait_until="domcontentloaded", timeout=90_000)
            settle(page, 3.5 if n in (4, 5) else 2.5)
            path = out / f"step{n}-{name}.png"
            page.screenshot(path=str(path), full_page=True)
            print(f"saved {path} ({page.evaluate('document.body.scrollHeight')} px high)")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
