"""Capture the README screenshots of the running app into docs/screenshots (1440x900).

    python backend/app.py             # in one terminal (real Hindsight + Groq keys in .env)
    python scripts/seed_demo.py       # once, so the Library and Company knowledge have data
    python scripts/take_screenshots.py
"""
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(BASE + "/")
        pg.wait_for_timeout(6500)
        pg.screenshot(path=str(OUT / "01-landing.png"))
        pg.goto(BASE + "/architecture")
        pg.wait_for_timeout(1500)
        pg.click(".cn[data-k='recall']")
        pg.wait_for_timeout(600)
        pg.screenshot(path=str(OUT / "02-architecture.png"))
        pg.goto(BASE + "/memory")
        pg.wait_for_timeout(1200)
        pg.click("#frun")
        pg.wait_for_timeout(20000)
        pg.screenshot(path=str(OUT / "03-memory-on.png"))
        pg.click('#fseg button[data-m="off"]')
        pg.click("#frun")
        pg.wait_for_timeout(15000)
        pg.screenshot(path=str(OUT / "04-memory-off.png"))
        pg.goto(BASE + "/how-it-works")
        pg.wait_for_timeout(1500)
        pg.click("#go")
        pg.wait_for_timeout(30000)
        pg.evaluate("window.scrollTo(0, 260)")
        pg.wait_for_timeout(600)
        pg.screenshot(path=str(OUT / "05-agents.png"))
        pg.goto(BASE + "/chat")
        pg.wait_for_timeout(1500)
        pg.get_by_text("Try the demo company").click()
        pg.wait_for_timeout(1500)
        pg.fill("#cin", "why does M-07 keep tripping on high pressure")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(16000)
        pg.screenshot(path=str(OUT / "06-chat.png"))
        pg.click("#liblink")
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(OUT / "07-library.png"))
        pg.click("#libx")
        pg.click("#cside a[data-view='company']")
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(OUT / "08-company-knowledge.png"))
        pg.goto(BASE + "/phone")
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(OUT / "09-technician-phone.png"))
        pg.goto(BASE + "/evaluation")
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(OUT / "10-evaluation.png"))
        b.close()
    print("saved", len(list(OUT.glob("*.png"))), "screenshots")


if __name__ == "__main__":
    main()
