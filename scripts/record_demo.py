"""Record the walkthrough video (1440x900, no voice) to docs/demo/walkthrough.webm.

    python backend/app.py            # in one terminal (real Hindsight + Groq keys in .env)
    python scripts/record_demo.py    # in another

It drives the real pages: the landing page, the architecture traced, the memory ON / OFF flow (each node shows its real
result), a live agent run, then a conversation in the chat: a greeting, a question the memory can answer, and one it cannot (labelled general guidance).
Whatever the services return on the day is what the video shows, so record it while the model budget is available. Add your voice-over after.
Needs: pip install playwright && playwright install chromium
"""
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "demo"
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")


def glide(pg, selector, pause=1.0, block="start"):
    pg.evaluate("([s,b])=>document.querySelector(s).scrollIntoView({behavior:'smooth',block:b})", [selector, block])
    time.sleep(pause + 0.8)


def point(pg, selector, pause=0.5):
    box = pg.locator(selector).first.bounding_box()
    if box:
        pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + min(24, box["height"] / 2), steps=26)
    time.sleep(pause)


def ask(pg, text, wait=16):
    pg.click("#cin")
    pg.keyboard.type(text, delay=38)
    time.sleep(0.6)
    pg.keyboard.press("Enter")
    time.sleep(wait)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / "_raw"
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, record_video_dir=str(raw), record_video_size={"width": 1440, "height": 900})
        pg = ctx.new_page()
        # 1. landing: the idea
        pg.goto(BASE + "/")
        time.sleep(7)
        glide(pg, ".preview", 1.5, "center")
        time.sleep(6)
        glide(pg, "#live", 1.0)
        # 2. the architecture, traced
        pg.goto(BASE + "/architecture")
        time.sleep(2.5)
        point(pg, "#run")
        pg.click("#run")
        time.sleep(12)
        # 3. memory ON / OFF: one question, two paths
        pg.goto(BASE + "/memory")
        time.sleep(2)
        point(pg, "#frun")
        pg.click("#frun")                                           # memory ON
        pg.wait_for_function("document.querySelector('#flout h5') && document.querySelector('#flout h5').textContent.includes('Memory ON')", timeout=90000)
        time.sleep(5)
        point(pg, '#fseg button[data-m="off"]')
        pg.click('#fseg button[data-m="off"]')                      # memory OFF
        time.sleep(1.5)
        pg.click("#frun")
        pg.wait_for_function("document.querySelector('#flout h5') && document.querySelector('#flout h5').textContent.includes('Memory OFF')", timeout=90000)
        time.sleep(5)
        # 3b. people and agents on one map: a real job
        pg.goto(BASE + "/how-it-works")
        time.sleep(2)
        glide(pg, ".stage", 1.0, "center")
        point(pg, "#go")
        pg.click("#go")
        time.sleep(22)
        # 4. the chat
        pg.goto(BASE + "/chat")
        time.sleep(2)
        pg.get_by_text("Try the demo company").click()
        time.sleep(2.5)
        ask(pg, "hi", 8)
        ask(pg, "why does M-07 keep tripping on high pressure", 18)
        ask(pg, "how do I reset a router password", 18)
        time.sleep(2)
        pg.click("#liblink")                                        # the library: uploads and sample incident records
        time.sleep(5)
        pg.mouse.wheel(0, 500)
        time.sleep(3)
        pg.click("#libx")
        time.sleep(1)
        pg.click("#cside a[data-view='company']")                   # company knowledge
        time.sleep(6)
        vid = pg.video.path()
        ctx.close()
        b.close()
    dest = OUT / "walkthrough.webm"
    shutil.move(vid, dest)
    shutil.rmtree(raw, ignore_errors=True)
    print("saved", dest)


if __name__ == "__main__":
    main()
