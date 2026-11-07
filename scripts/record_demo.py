"""Record a walkthrough video of the live demo (1440x900, no voice) to docs/demo/walkthrough.webm.

    python backend/app.py            # in one terminal (real Hindsight + Groq keys in .env)
    python scripts/record_demo.py    # in another

It drives the real page: home, send an alarm, watch the agents on the node canvas, open the Diagnostician to read how it searched, read the
self-correction trail, switch Hindsight off for one run, teach it a failed fix, and finish on the accuracy section. Whatever the agents do
on the day is what the video shows, so run it when the model budget is available (a model veto is the best footage), then add your voice-over.
Needs: pip install playwright && playwright install chromium
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "demo"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"


def glide(pg, selector, pause=1.2, block="start"):
    pg.evaluate("([s,b])=>document.querySelector(s).scrollIntoView({behavior:'smooth',block:b})", [selector, block])
    time.sleep(pause + 0.8)


def point(pg, selector, steps=28, pause=0.6):
    box = pg.locator(selector).first.bounding_box()
    if box:
        pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + min(30, box["height"] / 2), steps=steps)
    time.sleep(pause)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, record_video_dir=str(OUT / "_raw"), record_video_size={"width": 1440, "height": 900})
        pg = ctx.new_page()
        pg.goto(URL)
        time.sleep(4.5)
        pg.mouse.move(700, 500, steps=20)
        pg.evaluate("document.querySelector('.sec').scrollIntoView({behavior:'smooth'})")
        time.sleep(3)
        glide(pg, ".crew", 1.5)
        pg.evaluate("scrollTo({top:0,behavior:'smooth'})")
        time.sleep(1.5)
        point(pg, '.hero .btn.pri')
        pg.click('.hero .btn.pri')
        time.sleep(2)
        # act 1: the alarm
        point(pg, '.sc[data-id="LIVE-4"]')
        pg.click('.sc[data-id="LIVE-4"]')
        time.sleep(1.2)
        point(pg, "#run")
        pg.click("#run")
        glide(pg, ".flow", 0.5)
        pg.wait_for_selector("#cmp .cmp", timeout=360000)
        time.sleep(2)
        # act 2: open the agents
        for node, wait in (("dispatcher", 2.5), ("diagnostician", 3), ("verifier", 3)):
            glide(pg, ".flow", 0.2)
            point(pg, f'.nd[data-n="{node}"] .ndh')
            pg.click(f'.nd[data-n="{node}"] .ndh')
            glide(pg, "#ndv", wait)
            pg.evaluate("document.querySelector('#ndv').scrollBy({top:0})")
        pg.evaluate("document.querySelector('#ndv > div:nth-child(2)').scrollIntoView({behavior:'smooth',block:'center'})")
        time.sleep(3)
        glide(pg, ".corr", 4)
        pg.evaluate("window.scrollBy({top:420,behavior:'smooth'})")
        time.sleep(4)
        # act 3: with and without
        glide(pg, ".board", 5)
        glide(pg, "#cmp", 3, "center")
        # act 4: switch Hindsight off for one run
        glide(pg, "#drills", 1.0, "center")
        point(pg, '.drill[data-d="memory"]')
        pg.click('.drill[data-d="memory"]')
        time.sleep(1)
        pg.click("#run")
        glide(pg, ".flow", 0.5)
        pg.wait_for_selector("#cmp .cmp", timeout=360000)
        time.sleep(2)
        glide(pg, ".lanes", 3)
        # act 5: it learns
        glide(pg, ".learn", 1.0)
        point(pg, "#teachbtn")
        pg.click("#teachbtn")
        pg.wait_for_selector("#l1out .delta, #l1out .err", timeout=120000)
        time.sleep(4)
        point(pg, "#rebrief")
        pg.click("#rebrief")
        pg.wait_for_selector("#l2out .diffbox, #l2out .err", timeout=360000)
        time.sleep(5)
        # act 6: accuracy
        glide(pg, "#accpanel", 7, "center")
        ctx.close()
        vid = next((OUT / "_raw").glob("*.webm"))
        target = OUT / "walkthrough.webm"
        target.unlink(missing_ok=True)
        vid.rename(target)
        for f in (OUT / "_raw").glob("*"):
            f.unlink()
        (OUT / "_raw").rmdir()
        b.close()
    print("saved", target, f"{target.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
