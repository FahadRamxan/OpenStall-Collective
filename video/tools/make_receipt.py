"""A demo courier booking receipt for the hosted sandbox demo's pay-on-proof step: a phone-photo-sized slip from a
made-up courier ("DemoPost Express"), with a tracking number that has never been used, so one receipt pays one share.
Marked as a demo on its face. Usage: make_receipt.py OUT.jpg [TRACKING]."""

import os
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Segoe UI and Consolas, from Windows; FONTS_DIR points elsewhere.
FONTS = Path(os.environ.get("FONTS_DIR", "C:/Windows/Fonts"))


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def main() -> None:
    out = Path(sys.argv[1])
    tracking = sys.argv[2] if len(sys.argv) > 2 else "DP" + "".join(random.choice("0123456789") for _ in range(10))
    width, height = 1200, 1600
    paper = Image.new("RGB", (width, height), (246, 244, 238))
    draw = ImageDraw.Draw(paper)

    # Header band.
    draw.rectangle([0, 0, width, 210], fill=(22, 78, 99))
    draw.text((70, 48), "DemoPost Express", font=font("segoeuib.ttf", 78), fill=(255, 255, 255))
    draw.text((74, 140), "Courier booking receipt  ·  Customer copy", font=font("segoeui.ttf", 36),
              fill=(214, 234, 240))

    bold, regular, small = font("segoeuib.ttf", 40), font("segoeui.ttf", 40), font("segoeui.ttf", 30)
    y = 270
    draw.text((70, y), "Tracking / consignment no.", font=small, fill=(90, 90, 90))
    draw.text((70, y + 40), " ".join([tracking[:2], tracking[2:6], tracking[6:10], tracking[10:]]).strip(),
              font=font("consolab.ttf", 96), fill=(20, 20, 20))
    y += 190
    rows = [
        ("Booked", "11 Nov 2026, 16:40"),
        ("Origin", "Lahore, Pakistan"),
        ("Destination", "Chicago, IL, United States"),
        ("Service", "International economy"),
        ("Pieces / weight", "1 parcel  ·  1.4 kg"),
        ("Contents", "Hand-embroidered textiles"),
        ("Declared value", "USD 30.00"),
    ]
    for label, value in rows:
        draw.line([70, y, width - 70, y], fill=(205, 200, 190), width=2)
        draw.text((70, y + 22), label, font=regular, fill=(95, 95, 95))
        draw.text((520, y + 22), value, font=bold, fill=(25, 25, 25))
        y += 98
    draw.line([70, y, width - 70, y], fill=(205, 200, 190), width=2)

    # A barcode drawn from the tracking number.
    y += 60
    x = 110
    rng = random.Random(tracking)
    while x < width - 110:
        bar = rng.choice([3, 4, 6, 8])
        draw.rectangle([x, y, x + bar, y + 190], fill=(15, 15, 15))
        x += bar + rng.choice([4, 5, 7, 9])
    draw.text((width // 2, y + 225), tracking, font=font("consola.ttf", 44), fill=(30, 30, 30), anchor="mm")

    draw.text((70, height - 120), "Demo receipt for the OpenStall Collective sandbox demo.", font=small,
              fill=(120, 120, 120))
    draw.text((70, height - 78), "Track at demopost.example", font=small, fill=(120, 120, 120))

    # Like a phone photo of a slip: a little rotation, a desk around it, a touch of softness.
    slip = paper.rotate(-2.2, resample=Image.BICUBIC, expand=True, fillcolor=(96, 74, 58))
    photo = Image.new("RGB", (slip.width + 120, slip.height + 160), (96, 74, 58))
    photo.paste(slip, (60, 80))
    photo = photo.filter(ImageFilter.GaussianBlur(0.6)).resize((1080, int(1080 * photo.height / photo.width)))
    photo.save(out, quality=90)
    print(out, tracking)


if __name__ == "__main__":
    main()
