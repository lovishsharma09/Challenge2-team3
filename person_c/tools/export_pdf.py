#!/usr/bin/env python3
"""Export the rendered cards to PDF (needs: pip install playwright && playwright install chromium).
   python tools/export_pdf.py output/cards/das_schmeckt_rezepte.html"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

src = Path(sys.argv[1]).resolve()
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto(src.as_uri())
    out = src.with_suffix(".pdf")
    pg.pdf(path=str(out), prefer_css_page_size=True, print_background=True)
    b.close()
print("written", out)
