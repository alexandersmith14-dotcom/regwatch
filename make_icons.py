"""Generate the favicon and home-screen icons.

Run after changing the branding, same as make_og_image.py. Output is committed
so the published page can reference it.

The design deliberately echoes og-image.png: navy field, white monogram, green
rule along the bottom. Someone who saw the LinkedIn card should recognise the
tab icon as the same thing.

Two things are handled differently from the social card, both because of size:

- The card's green rule is 14px of 630 (2%). At 16px that would be a third of a
  pixel, i.e. invisible. The rule here is a proportion of the icon (10%) so it
  survives at tab size.
- Each PNG is rendered natively at its final size rather than by shrinking one
  big image. A 16px "R" drawn as 16px is legible; a 512px "R" resampled down to
  16px turns to mush.
"""
import json

from PIL import Image, ImageDraw, ImageFont

NAVY = (0, 59, 106)
GREEN = (174, 209, 54)
WHITE = (255, 255, 255)

MARK = "R"
RULE_FRACTION = 0.10      # green bar height, as a share of the icon
CAP_FRACTION = 0.66       # target height of the letter, as a share of the icon


def font_for(cap_px):
    """Largest Calibri/Arial bold whose cap height is about cap_px.

    Point size and rendered height are not the same number, and the gap varies
    by font, so measure the glyph rather than assuming a ratio.
    """
    for name in ("calibrib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        best = None
        for pt in range(4, 700):
            try:
                f = ImageFont.truetype(name, pt)
            except OSError:
                break
            box = f.getbbox(MARK)
            if (box[3] - box[1]) > cap_px:
                break
            best = f
        if best is not None:
            return best
    return ImageFont.load_default()


def render(size, padding=0.0):
    """One icon. `padding` insets the artwork for maskable (croppable) icons."""
    img = Image.new("RGB", (size, size), NAVY)
    d = ImageDraw.Draw(img)

    inset = round(size * padding)
    inner = size - 2 * inset

    rule = max(1, round(inner * RULE_FRACTION))
    d.rectangle([inset, size - inset - rule, size - inset, size - inset - 1], fill=GREEN)

    f = font_for(inner * CAP_FRACTION)
    box = d.textbbox((0, 0), MARK, font=f)
    # Centre on the field above the rule, using the glyph's real ink bounds --
    # textbbox origin is not the visual top-left and ignoring that leaves the
    # letter visibly low and off-centre at small sizes.
    field_top, field_bottom = inset, size - inset - rule
    x = inset + (inner - (box[2] - box[0])) / 2 - box[0]
    y = field_top + ((field_bottom - field_top) - (box[3] - box[1])) / 2 - box[1]
    d.text((x, y), MARK, font=f, fill=WHITE)
    return img


def main():
    written = []

    # Multi-size .ico still has the broadest support, and is what a browser
    # reaches for when no <link rel="icon"> matches.
    ico = render(48)
    ico.save("favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    written.append("favicon.ico")

    for size in (16, 32, 180, 192, 512):
        # 180 is Apple's home-screen size; iOS rounds the corners itself and
        # composites on black, so the artwork must stay full-bleed and opaque.
        name = "apple-touch-icon.png" if size == 180 else f"icon-{size}.png"
        render(size).save(name, "PNG", optimize=True)
        written.append(name)

    # Android masks icons to whatever shape the launcher uses and can crop up to
    # 20% off each edge. The padded variant keeps the monogram inside that safe
    # zone; without it the R loses its edges on a circular launcher.
    render(512, padding=0.20).save("icon-maskable-512.png", "PNG", optimize=True)
    written.append("icon-maskable-512.png")

    manifest = {
        "name": "Regulatory update tracker — community banks & fintechs",
        "short_name": "RegWatch",
        "description": "Daily federal regulatory updates for community banks and "
                       "fintechs, in plain English.",
        # Relative, because the site is served from a /regwatch/ subpath rather
        # than a domain root. An absolute "/" would break the installed app.
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": "#003b6a",
        "theme_color": "#003b6a",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "icon-maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }
    with open("site.webmanifest", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    written.append("site.webmanifest")

    print("Wrote " + ", ".join(written))


if __name__ == "__main__":
    main()
