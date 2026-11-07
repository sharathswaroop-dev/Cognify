"""Record a walkthrough video of the talk (1440x900, no voice) to docs/demo/walkthrough.webm.

    python backend/app.py            # in one terminal (real Hindsight + Groq keys in .env)
    python scripts/record_demo.py    # in another

It drives the real page through the four scenes: intro, the problem (no memory), the demo (agents recall and check, you open the
Diagnostician to read how it searched, the self-correction trail, the failed fix retained, the same alarm briefed again) and the wrap-up.
Whatever the agents do on the day is what the video shows, so run it when the model budget is available (a Verifier veto is the best footage),
and on a fresh memory (the page's "reset the demo memory" link, then wait for Hindsight to finish ingesting). Then add your voice-over.
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
        time.sleep(6)                                              # scene 1: intro
        pg.mouse.move(700, 500, steps=20)
        point(pg, ".intro .btn.pri")
        pg.click(".intro .btn.pri")                                # scene 2: the problem
        time.sleep(2.5)
        point(pg, "#probrun")
        pg.click("#probrun")
        pg.wait_for_selector("#prob .ps.bad, #prob .ps.good, #prob .err", timeout=360000)
        time.sleep(5)
        point(pg, '#steps button[data-scene="demo"]')              # scene 3: the demo
        pg.click('#steps button[data-scene="demo"]')
        time.sleep(3)
        point(pg, "#run")
        pg.click("#run")
        pg.wait_for_selector("#outcome.on", timeout=420000)
        time.sleep(3)
        for node in ("dispatcher", "diagnostician", "verifier"):   # open the agents: how each one searched
            glide(pg, "#flow", 0.2)
            point(pg, f'.nd[data-n="{node}"] .ndh')
            pg.click(f'.nd[data-n="{node}"] .ndh')
            glide(pg, ".under", 3.5)
        glide(pg, ".corr", 5)                                      # the self-correction trail
        pg.evaluate("window.scrollBy({top:420,behavior:'smooth'})")
        time.sleep(4)
        glide(pg, ".demo2", 1.0)                                   # retain, then ask again
        point(pg, "#teachbtn")
        pg.click("#teachbtn")
        pg.wait_for_selector("#l1out .delta, #l1out .err", timeout=120000)
        time.sleep(5)
        point(pg, "#rebrief")
        pg.click("#rebrief")
        pg.wait_for_selector("#l2out .diffbox, #l2out .err", timeout=420000)
        time.sleep(6)
        point(pg, '#steps button[data-scene="wrap"]')              # scene 4: wrap-up
        pg.click('#steps button[data-scene="wrap"]')
        time.sleep(9)
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
