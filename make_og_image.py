#!/usr/bin/env python3
"""Generate og-image.png, the card X and Slack show when the board is shared.

Run by hand, not by the daily workflow, and deliberately carrying no counts. Social
platforms cache og:image for days, so a number baked in here would be wrong in the
card far more often than it was right -- and a stale "363 roles" reads worse than no
number at all. Colours are the site's own tokens, not new choices.
"""
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG, CARD = "#f4f6f8", "#ffffff"
INK, INK2, INK3, BORDER = "#101418", "#4a5561", "#6b7683", "#dfe3e8"
ACCENT = "#1a5fd0"
# tier tokens, straight from :root
CHIPS = [("Frontier lab", "#2a78d6", "#e9f1fd"), ("Big tech", "#1baf7a", "#e6f7f0"),
         ("Startup", "#a86f00", "#fdf3e0"), ("Research org", "#eb6834", "#fdeee8"),
         ("Infra & chips", "#b5487a", "#fdeef4")]

B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
f = lambda p, s: ImageFont.truetype(p, s)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
d.rounded_rectangle([48, 48, W - 48, H - 48], 26, fill=CARD, outline=BORDER, width=2)

# mark + wordmark
d.rounded_rectangle([104, 104, 168, 168], 15, fill=INK)
d.text((136, 134), "P", font=f(B, 38), fill="#ffffff", anchor="mm")
d.text((188, 136), "PhD Intern Board", font=f(B, 52), fill=INK, anchor="lm")

d.text((104, 246), "AI research internships, updated every day.", font=f(B, 36), fill=INK, anchor="lm")
d.text((104, 300), "Research interns, student researchers, fellowships,", font=f(R, 27), fill=INK2, anchor="lm")
d.text((104, 340), "AI residencies and predoctoral roles.", font=f(R, 27), fill=INK2, anchor="lm")

x, y, fc = 104, 402, f(B, 21)
for label, ink, bg in CHIPS:
    w = int(d.textlength(label, font=fc)) + 34
    d.rounded_rectangle([x, y, x + w, y + 44], 22, fill=bg)
    d.text((x + w // 2, y + 22), label, font=fc, fill=ink, anchor="mm")
    x += w + 12

d.line([104, 502, W - 104, 502], fill=BORDER, width=2)
d.text((104, 542), "Read straight from public job-board APIs. New postings flagged.",
       font=f(R, 24), fill=INK3, anchor="lm")
d.text((W - 104, 542), "dion-jy.github.io/phd-intern-board", font=f(B, 24), fill=ACCENT, anchor="rm")

img.save("og-image.png", optimize=True)
print("wrote og-image.png %dx%d" % img.size)
