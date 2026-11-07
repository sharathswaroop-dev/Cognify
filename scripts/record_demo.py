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


CURSOR = """
(() => {
  const d = document.createElement('div');
  d.style.cssText = 'position:fixed;left:0;top:0;width:24px;height:24px;margin:-5px 0 0 -5px;border-radius:50%;background:rgba(139,92,246,.4);border:2px solid #fff;box-shadow:0 0 0 2px rgba(139,92,246,.95),0 6px 16px rgba(0,0,0,.55);pointer-events:none;z-index:2147483647;opacity:0;transition:width .12s,height .12s,background .12s,opacity .2s';
  const put = (x, y) => { d.style.transform = 'translate(' + x + 'px,' + y + 'px)'; d.style.opacity = 1; try { sessionStorage.setItem('__cur', x + ',' + y) } catch (e) {} };
  const add = () => { document.documentElement.appendChild(d); try { const v = sessionStorage.getItem('__cur'); if (v) { const [x, y] = v.split(',').map(Number); put(x, y) } } catch (e) {} };
  if (document.documentElement) add(); else addEventListener('DOMContentLoaded', add);
  addEventListener('mousemove', e => put(e.clientX, e.clientY), true);
  addEventListener('mousedown', () => { d.style.background = 'rgba(34,211,238,.85)'; d.style.width = d.style.height = '34px' }, true);
  addEventListener('mouseup', () => { d.style.background = 'rgba(139,92,246,.4)'; d.style.width = d.style.height = '24px' }, true);
})();
"""


def glide(pg, selector, pause=1.0, block="start"):
    pg.evaluate("([s,b])=>document.querySelector(s).scrollIntoView({behavior:'smooth',block:b})", [selector, block])
    time.sleep(pause + 0.8)


def point(pg, target, pause=0.5):
    loc = pg.locator(target).first if isinstance(target, str) else target
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    if box:
        pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + min(24, box["height"] / 2), steps=26)
    time.sleep(pause)


def mclick(pg, target, pause=0.35):
    """Glide the (visible) pointer to the target, then click it."""
    point(pg, target, pause)
    (pg.locator(target).first if isinstance(target, str) else target).click()


def ask(pg, text, wait=16):
    mclick(pg, "#cin")
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
        ctx.add_init_script(CURSOR)
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
        mclick(pg, "#run")
        time.sleep(12)
        # 3. memory ON / OFF: one question, two paths
        pg.goto(BASE + "/memory")
        time.sleep(2)
        point(pg, "#frun")
        mclick(pg, "#frun")                                           # memory ON
        pg.wait_for_function("document.querySelector('#flout h5') && document.querySelector('#flout h5').textContent.includes('Memory ON')", timeout=90000)
        time.sleep(5)
        point(pg, '#fseg button[data-m="off"]')
        mclick(pg, '#fseg button[data-m="off"]')                      # memory OFF
        time.sleep(1.5)
        mclick(pg, "#frun")
        pg.wait_for_function("document.querySelector('#flout h5') && document.querySelector('#flout h5').textContent.includes('Memory OFF')", timeout=90000)
        time.sleep(5)
        # 3a. how an answer is made, without and with memory, step by step
        pg.goto(BASE + "/how-it-works#steps")
        time.sleep(2.5)
        pg.evaluate("document.querySelectorAll('.rv').forEach(e=>e.classList.add('in'))")
        glide(pg, "#steps", 1.0)
        time.sleep(4)
        pg.mouse.wheel(0, 700)
        time.sleep(4)
        glide(pg, "#cmpt", 1.0)
        time.sleep(5)
        glide(pg, "#lvf", 1.0, "center")
        mclick(pg, "#lvf button")                                   # run both paths live
        time.sleep(20)
        # 3b. people and agents on one map: a real job
        pg.goto(BASE + "/how-it-works")
        time.sleep(2)
        glide(pg, ".stage", 1.0, "center")
        point(pg, "#go")
        mclick(pg, "#go")
        time.sleep(22)
        # 4. the chat
        pg.goto(BASE + "/chat")
        time.sleep(2)
        mclick(pg, pg.get_by_text("Try the demo company"))
        time.sleep(2.5)
        ask(pg, "hi", 8)
        ask(pg, "how are you", 8)
        ask(pg, "why does M-07 keep tripping on high pressure", 18)       # answered from memory, with the records behind it
        pg.set_input_files("#cfile", str(ROOT / "docs" / "demo" / "inspection_report.pdf"))   # upload a PDF: it is read, learned and analysed straight away
        time.sleep(28)
        pg.set_input_files("#cfile", str(ROOT / "docs" / "demo" / "contactor_photo.png"))     # upload a picture: say what it shows, then it is analysed too
        pg.wait_for_selector("#capmodal:not([hidden])", timeout=20000)
        time.sleep(1.5)
        mclick(pg, "#captext")
        pg.keyboard.type("The burnt compressor contactor on the Skyline Clubhouse rooftop unit M-121: scorched coil and pitted contacts.", delay=30)
        time.sleep(1)
        mclick(pg, "#capok")
        time.sleep(28)
        ask(pg, "Write a short brief for the technician going to unit M-121: likely cause, what to skip, and which part to bring", 24)   # ask for a brief
        ask(pg, "Remember: on the Riverside rooftop units, check the evening supply voltage before blaming the compressor.", 10)   # teach it
        ask(pg, "what should I check first on the Riverside rooftop units", 18)                   # and it recalls what was just taught
        mclick(pg, pg.locator('button[data-act="up"]').last)                                           # feedback on the answer
        time.sleep(2)
        ask(pg, "how do I reset a router password", 18)                                           # not in memory: labelled general guidance
        time.sleep(2)
        mclick(pg, "#liblink")                                        # the library: uploads and sample incident records
        time.sleep(5)
        pg.mouse.wheel(0, 500)
        time.sleep(3)
        mclick(pg, "#libx")
        time.sleep(1)
        mclick(pg, "#cside a[data-view='company']")                   # company knowledge
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
