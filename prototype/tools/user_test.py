"""Click through the running prototype like a user (Playwright, real browser, real server):
live run of all six steps (Person A, editor pick with a steering note, Person C), a send-back round on r1,
the downloads, then Demo mode. Screenshots of every state go to --out.

    ./run_prototype.sh --server.headless true &
    python prototype/tools/user_test.py [--base http://localhost:8501] [--out prototype/screenshots/user_test]
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout, expect, sync_playwright

STEPS = ["Trend evidence", "Five proposals", "Editor choice", "Recipes", "Review & nutrition", "Cards & impact"]


class User:
    def __init__(self, page, out: Path):
        self.page, self.out, self.n = page, out, 0
        self.log: list[str] = []

    def say(self, msg):
        self.log.append(msg)
        print(msg, flush=True)

    def shot(self, name: str):
        self.n += 1
        path = self.out / f"{self.n:02d}-{name}.png"
        self.settle()
        self.page.screenshot(path=str(path), full_page=True)
        self.say(f"  screenshot {path}")

    def settle(self, seconds: float = 1.5):
        try:
            self.page.wait_for_load_state("networkidle", timeout=30_000)
        except PWTimeout:
            pass
        time.sleep(seconds)

    def wait_for(self, pattern: str, timeout_s: int):
        """Wait for the visible result of an action (the page hides Streamlit's running indicator, so the outcome is the signal)."""
        self.page.get_by_text(re.compile(pattern, re.I)).first.wait_for(state="visible", timeout=timeout_s * 1000)
        self.settle(1.0)

    def no_error(self, where: str):
        if self.page.locator('[data-testid="stException"]').count():
            raise AssertionError(f"{where}: a Streamlit exception is on the page")
        alerts = self.page.locator('[data-testid="stAlert"]').all_inner_texts()
        bad = [a for a in alerts if "could not finish" in a or "failed" in a.lower() or "rejected" in a.lower()]
        if bad:
            raise AssertionError(f"{where}: error box shown: {bad[0][:200]}")

    def goto_step(self, n: int):
        self.page.get_by_text(f"{n} · {STEPS[n - 1]}", exact=True).click()
        self.settle(1.0)
        expect(self.page.get_by_role("heading", name=re.compile(rf"^{n} · "))).to_be_visible(timeout=20_000)

    def click(self, name: str, timeout: int = 20_000):
        self.page.get_by_role("button", name=name, exact=False).first.click(timeout=timeout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8501")
    ap.add_argument("--out", default="prototype/screenshots/user_test")
    ap.add_argument("--pick-text", default="Grünkohl")
    ap.add_argument("--notes", default="alltagstauglich, keine exotischen Zutaten")
    ap.add_argument("--sendback", default="weniger deftig, alltagstauglicher")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page = ctx.new_page()
        u = User(page, out)
        page.goto(a.base, wait_until="domcontentloaded", timeout=90_000)
        u.settle(3)
        u.no_error("start")
        expect(page.get_by_text("Rezept-Werkstatt · from trend to recipe card")).to_be_visible()
        u.say("1 · page open (live mode)")
        u.shot("step1-empty")

        u.click("Run Person A now")
        u.wait_for("schema valid|could not finish", 300)
        u.no_error("Person A")
        u.say("1 · Person A finished: " + page.locator("text=/\\d+ proposals · \\d+ rejected/").first.inner_text())
        u.shot("step1-evidence")

        u.goto_step(2)
        cards = [c for c in page.locator("h3").all_inner_texts() if c != "Rezept-Werkstatt"][:5]
        u.say(f"2 · five proposals: {cards}")
        assert len(cards) == 5, "fewer than five proposal titles"
        fallback = [c for c in cards if re.search(r"\((Food|Vegetable|Cabbage|Cake|Dish)\)", c)]
        if fallback:
            u.say(f"  WARNING template fallback for {len(fallback)} pitch(es): {fallback}")
        assert len(fallback) <= 1, "LLM titles failed for more than one pitch"
        u.shot("step2-proposals")

        u.goto_step(3)
        page.get_by_text(re.compile(a.pick_text)).first.click()
        page.get_by_label("Steering notes for the recipe agent").fill(a.notes)
        u.shot("step3-pick")
        u.click("Hand off to Person C")
        u.wait_for(r"^4 · Recipes|rejected the batch", 60)
        u.no_error("hand-off")
        u.say("3 · handed off; decision trail: " + " | ".join(t for t in page.locator("text=/You chose/").all_inner_texts()))
        u.goto_step(3)
        expect(page.locator(".ds-kicker", has_text=re.compile("^Selected$"))).to_be_visible()
        u.shot("step3-selected")
        u.goto_step(4)

        u.click("Generate the two recipes")
        u.wait_for(r"r1 · version \d|could not finish", 900)      # the recipe kicker, not the steering note in the sidebar
        u.no_error("Person C")
        titles = page.locator("h3").all_inner_texts()
        u.say(f"4 · recipes: {titles[:2]}")
        assert page.locator("img").count() >= 2, "recipe images missing"
        u.shot("step4-recipes")

        page.get_by_text("Send back to the Recipe Agent", exact=False).first.click()
        box = page.get_by_label("Your comment (required)").first
        box.fill(a.sendback)
        box.press("Tab")                       # Streamlit commits a text area on blur
        u.settle(1.5)
        u.click("Send back and revise")
        u.wait_for(r"r1 · version [2-9]|editor round failed", 900)
        u.no_error("send-back")
        kick = page.locator("text=/R1 · VERSION/i").first.inner_text()
        u.say("4 · send-back done: " + kick)
        assert "VERSION 1" not in kick.upper(), "r1 version did not increase"
        u.shot("step4-after-sendback")

        u.goto_step(5)
        expect(page.get_by_text("Round 1", exact=False).first).to_be_visible()
        rounds = page.locator("text=/Round \\d+ · (auto|editor)/").all_inner_texts()
        u.say(f"5 · review rounds r1 tab: {rounds}")
        assert any("editor" in r for r in rounds), "editor round not shown"
        expect(page.get_by_text("Nutrition per serving")).to_be_visible()
        u.shot("step5-review")

        u.goto_step(6)
        expect(page.get_by_text("Seconds per stage")).to_be_visible()
        pages_tile = page.locator("text=/pages per card/").first.locator("xpath=..").inner_text()
        u.say("6 · impact tile: " + " ".join(pages_tile.split()))
        with page.expect_download(timeout=30_000) as dl:
            u.click("Download HTML")
        d = dl.value
        html_path = out / d.suggested_filename
        d.save_as(str(html_path))
        n_pages = len(re.findall(r'class="page"', html_path.read_text(encoding="utf-8")))
        u.say(f"6 · downloaded {d.suggested_filename}: {html_path.stat().st_size // 1024} KB, {n_pages} page(s)")
        assert n_pages == 1, "downloaded card is not one page"
        if page.get_by_role("button", name="Prepare PDF").count():
            u.click("Prepare PDF")
            page.get_by_role("button", name="Download PDF").wait_for(state="visible", timeout=180_000)
            with page.expect_download(timeout=30_000) as dl2:
                u.click("Download PDF")
            pdf = dl2.value
            pdf_path = out / pdf.suggested_filename
            pdf.save_as(str(pdf_path))
            u.say(f"6 · downloaded {pdf.suggested_filename}: {pdf_path.stat().st_size // 1024} KB, starts with {pdf_path.read_bytes()[:5]!r}")
        u.shot("step6-cards")

        page.get_by_text("Demo mode", exact=False).first.click()
        u.wait_for("demo · cached run", 60)
        u.no_error("demo mode")
        u.goto_step(4)
        assert page.get_by_role("button", name="Generate the two recipes").count() == 0, "live button offered in demo mode"
        u.say("demo · cached run shown, no live buttons")
        u.shot("demo-step4")
        page.get_by_text("Demo mode", exact=False).first.click()
        page.locator(".ds-pill", has_text=re.compile("^live$", re.I)).wait_for(state="visible", timeout=30_000)
        u.say("demo off · back to live")
        browser.close()
    print("USER TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
