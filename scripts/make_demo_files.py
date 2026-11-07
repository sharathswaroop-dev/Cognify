"""Create the sample PDF and picture that the walkthrough video uploads (docs/demo/). Sample data, drawn from HTML with the same browser the recording uses."""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "demo"
PDF = """<html><body style="font:15px/1.55 Arial;padding:40px;max-width:760px"><h2>Inspection report (sample data)</h2>
<p><b>Site:</b> Skyline Residency Clubhouse &nbsp; <b>Unit:</b> M-121, Daikin VRV IV RXYQ10 (rooftop outdoor unit)</p>
<p><b>Reported:</b> unit not cooling, display shows E3 (high-pressure / compressor protection trip) three times in one week.</p>
<h3>Findings</h3><ul><li>Supply voltage measured at 189 V under load, below the 200 V the unit expects.</li>
<li>Compressor contactor coil scorched; contacts pitted.</li><li>Refrigerant pressures normal. Compressor draws normal current when it runs.</li></ul>
<h3>Actions</h3><ol><li>Replaced the compressor relay board. The unit tripped again the same afternoon.</li>
<li>Replaced the compressor contactor (DK-CTR-24V). The unit ran for the whole test period without a trip.</li></ol>
<p><b>Recommendation:</b> raise the supply voltage issue with the building electrician. Do not replace the relay board on this model for an E3 trip.</p></body></html>"""
IMG = """<html><body style="margin:0;background:#1b1d22;font:600 22px Arial;color:#e8e8e8;width:720px;height:420px;position:relative">
<div style="position:absolute;left:30px;top:26px;font-size:15px;color:#9aa">PHOTO (sample) - Skyline Clubhouse rooftop unit M-121</div>
<div style="position:absolute;left:60px;top:90px;width:280px;height:200px;border-radius:14px;background:#3a3f48;border:3px solid #555"></div>
<div style="position:absolute;left:92px;top:130px;width:110px;height:110px;border-radius:50%;background:radial-gradient(circle,#111 30%,#6b3b1e 70%,#c0521e);box-shadow:0 0 30px #e0561f"></div>
<div style="position:absolute;left:230px;top:150px;width:90px;height:60px;background:#222;border:2px dashed #aa6633"></div>
<div style="position:absolute;left:380px;top:100px;font-size:20px;line-height:1.7">Compressor contactor<br><span style="color:#ff9966">scorched coil, pitted contacts</span><br>DK-CTR-24V</div></body></html>"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 720, "height": 420})
        pg.set_content(PDF)
        pg.pdf(path=str(OUT / "inspection_report.pdf"), format="A4")
        pg.set_content(IMG)
        pg.screenshot(path=str(OUT / "contactor_photo.png"))
        b.close()
    print("saved", [f.name for f in OUT.glob("*") if f.suffix in (".pdf", ".png")])


if __name__ == "__main__":
    main()
