"""Generate the LinkedIn/social preview card (og-image.png).

Run after changing the branding or the headline. Committed to the repo so the
published page can reference it — social scrapers need a real image URL, they
cannot render the dashboard itself.

1200x630 is the size LinkedIn, Twitter/X and Facebook all crop cleanly from.
"""
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
NAVY = (0, 59, 106)
GREEN = (174, 209, 54)
WHITE = (255, 255, 255)
MUTED = (176, 196, 214)

OUT = "og-image.png"


def font(size, bold=False):
    """Calibri matches the dashboard's own stack; fall back if unavailable."""
    for name in (["calibrib.ttf", "arialbd.ttf"] if bold else ["calibri.ttf", "arial.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


img = Image.new("RGB", (W, H), NAVY)
d = ImageDraw.Draw(img)

# Brand rule along the bottom, mirroring the dashboard header.
d.rectangle([0, H - 14, W, H], fill=GREEN)

d.text((70, 92), "Regulatory update tracker", font=font(62, bold=True), fill=WHITE)
# Font stepped down from 34 to 30 to fit the longer three-audience subtitle
# within the card at x=70.
d.text((70, 182), "Community banks, credit unions & fintechs", font=font(30), fill=GREEN)

lines = [
    "US federal & state regulators, one page.",
    "Plain-English summaries, comment deadlines,",
    "and effective dates — updated daily.",
]
y = 268
for line in lines:
    d.text((70, y), line, font=font(30), fill=MUTED)
    y += 46

d.text((70, H - 118), "Built by Alexander Smith, CRCM, CFE",
       font=font(28, bold=True), fill=WHITE)
d.text((70, H - 78), "Risk Advisory Services  ·  Kaufman Rossin",
       font=font(26), fill=MUTED)

img.save(OUT, "PNG", optimize=True)
print(f"Wrote {OUT} ({W}x{H})")
