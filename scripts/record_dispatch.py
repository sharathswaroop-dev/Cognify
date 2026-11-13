"""Record the dispatch walkthrough (1440x900, no voice) to docs/demo/dispatch-walkthrough.webm.

    python backend/app.py                  # in one terminal
    python scripts/record_dispatch.py      # in another

Uses the live dispatch screen and almost no model budget. Three scenes:
  A  Demo mode, "accept after 7 decline": the city fleet joins, rejections count up, the best match wins, OTP, work, resolved.
  B  Manual mode: you reject one technician, accept another, enter the OTP yourself.
  C  The "how matching works" page.
Add your voice-over after.
"""
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record_demo import CURSOR, mclick, point  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "demo"
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")


def left_has(pg, text, timeout=120):
    """Wait until the left panel mentions `text`; never abort the recording if it does not show up."""
    try:
        pg.wait_for_function("t => (document.querySelector('#left')||{innerText:''}).innerText.toLowerCase().includes(t.toLowerCase())", arg=text, timeout=timeout * 1000)
        return True
    except Exception:
        print("  (did not see:", text, ")")
        return False


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / "_raw_dispatch"
    shutil.rmtree(raw, ignore_errors=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, record_video_dir=str(raw), record_video_size={"width": 1440, "height": 900})
        ctx.add_init_script(CURSOR)
        pg = ctx.new_page()

        # A. Demo mode, the request is accepted only after 7 technicians decline
        pg.goto(BASE + "/dispatch")
        time.sleep(5)
        point(pg, "#plan")
        pg.select_option("#plan", "7")
        time.sleep(1.5)
        mclick(pg, "#sim")
        time.sleep(22)                          # layers, the city fleet, rejections counting up
        left_has(pg, "Confirmed", 90)
        time.sleep(7)                           # the confirmation and the counts
        left_has(pg, "Resolved", 150)
        time.sleep(5)

        # B. Manual mode: the presenter answers for the technicians
        mclick(pg, "#m-man")
        time.sleep(1.5)
        mclick(pg, "#sim")
        try:
            pg.wait_for_selector(".mb.no[data-resp]", timeout=30000)
        except Exception:
            print("  (no manual buttons)")
        time.sleep(4)
        mclick(pg, pg.locator(".mb.no[data-resp]").first)       # reject the first technician
        time.sleep(3)
        mclick(pg, pg.locator(".mb.ok[data-resp]").first)       # accept the next one
        left_has(pg, "Confirmed", 40)
        time.sleep(6)
        try:
            pg.wait_for_selector(".mb.ok[data-otp]", timeout=120000)
            time.sleep(5)                                       # the OTP the customer reads out
            mclick(pg, pg.locator(".mb.ok[data-otp]").first)    # the correct OTP: work starts
        except Exception:
            print("  (no OTP button)")
        time.sleep(6)
        left_has(pg, "Resolved", 90)
        time.sleep(5)

        # C. How matching works
        pg.goto(BASE + "/how-matching-works")
        time.sleep(9)
        pg.mouse.wheel(0, 700)
        time.sleep(6)

        vid = pg.video
        ctx.close()
        src = Path(vid.path())
        dest = OUT / "dispatch-walkthrough.webm"
        shutil.move(str(src), str(dest))
        b.close()
    shutil.rmtree(raw, ignore_errors=True)
    print("saved", dest)


if __name__ == "__main__":
    main()
