"""Made-up media for fake mode and tests: a small embroidery-pattern photo (PNG), a short voice note (WAV), and a
courier receipt photo (PNG) for pay-on-proof.

All are generated, so the repo holds no binary files for them, and the same bytes come out every time for the same
input, so the media store keeps each once.
"""

import hashlib
import math
import struct
import zlib
from functools import cache

from openstall_agents.adapters import Transcript
from openstall_agents.receipt_reader import fixture_receipt_text

# What fake mode hears in fixture_voice_note(), the sample voice note: Amina's words from the story (spec section 2,
# step 1) as she would say them in Urdu. "Embroidered cushion covers, in three colours, 18 dollars each. I can make
# 15 a week."
SAMPLE_VOICE_NOTE_SAYS = Transcript(
    "کڑھائی والے کشن کور، تین رنگوں میں، اٹھارہ ڈالر کا ایک۔ میں ہفتے میں پندرہ بنا سکتی ہوں۔", "ur"
)


def known_voice_notes() -> dict[str, Transcript]:
    """What fake mode's speech to text hears in each sample voice note, by the file's sha256."""
    return {hashlib.sha256(fixture_voice_note()).hexdigest(): SAMPLE_VOICE_NOTE_SAYS}

CREAM = (247, 240, 226)
TEAL = (14, 110, 100)
RED = (178, 54, 54)
GOLD = (214, 160, 54)
PAPER = (252, 251, 247)
INK = (38, 38, 38)
GREY = (196, 196, 190)


def _png(width: int, height: int, rows: list[bytes], text: bytes | None = None) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + row for row in rows)  # filter type 0 on every row
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    comment = chunk(b"tEXt", b"Comment\x00" + text) if text is not None else b""
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + comment
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


# Made-up couriers and tracking numbers for fake mode's receipt photos, by the maker's country. Fictional, like the
# seeded makers; any other country gets the last.
DEMO_SHIPMENTS = {
    "PK": ("TCS", "7712345678"),
    "IN": ("India Post", "EE123456789IN"),
    "MX": ("Estafeta", "8055241529"),
    "GB": ("Royal Mail", "RN123456789GB"),
    "US": ("USPS", "9400111899223197428490"),
}
DEFAULT_SHIPMENT = ("DHL", "1234567890")


def demo_shipment(country: str | None) -> tuple[str, str]:
    """The made-up courier and tracking number on fake mode's receipt photo for a maker in this country."""
    return DEMO_SHIPMENTS.get(country or "", DEFAULT_SHIPMENT)


@cache
def fixture_receipt(carrier: str, tracking_number: str) -> bytes:
    """A 240 × 320 courier slip: a dark header band, grey lines of print, and a barcode drawn from the tracking
    number. What it "says" (the courier and the number) is in its PNG text chunk, which fake mode's stand-in model
    reads; Claude in sandbox mode would read a real photo's print instead."""
    width, height = 240, 320
    bars = []
    for char in tracking_number:
        code = ord(char)
        bars += [1 + code % 3, 1 + (code // 3) % 2, 1 + (code // 7) % 3, 1]  # bar, gap, bar, gap widths
    rows = []
    for y in range(height):
        row = bytearray()
        x_bar, bar_index, dark = 20, 0, True
        for x in range(width):
            if y < 44:
                colour = TEAL if 6 < y < 38 and 12 < x < 228 else INK
            elif 64 <= y < 260 and (y - 64) % 22 < 6 and 20 <= x < (200 if (y // 22) % 2 else 160):
                colour = GREY  # lines of print
            elif 268 <= y < 306 and 20 <= x < 220:
                while bar_index < len(bars) and x >= x_bar + bars[bar_index]:
                    x_bar += bars[bar_index]
                    bar_index += 1
                    dark = not dark
                colour = INK if dark and bar_index < len(bars) else PAPER
            else:
                colour = PAPER
            row += bytes(colour)
        rows.append(bytes(row))
    return _png(width, height, rows, fixture_receipt_text(carrier, tracking_number))


@cache
def fixture_photo() -> bytes:
    """A 240 × 240 cushion cover: a red border and a diamond lattice in teal and gold on cream."""
    size = 240
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            edge = min(x, y, size - 1 - x, size - 1 - y)
            if edge < 10:
                colour = RED
            elif edge < 14:
                colour = GOLD
            else:
                u, v = (x + y) % 40, (x - y) % 40
                colour = TEAL if u < 4 or v < 4 else GOLD if (u - 20) ** 2 + (v - 20) ** 2 < 30 else CREAM
            row += bytes(colour)
        rows.append(bytes(row))
    return _png(size, size, rows)


@cache
def fixture_voice_note() -> bytes:
    """A 1.5 second, 8 kHz mono WAV: a soft hum that rises and falls, like a short spoken phrase."""
    rate, seconds = 8000, 1.5
    samples = bytearray()
    for n in range(int(rate * seconds)):
        t = n / rate
        envelope = math.sin(math.pi * t / seconds) ** 2
        tone = math.sin(2 * math.pi * (180 + 40 * math.sin(2 * math.pi * 1.5 * t)) * t)
        samples += struct.pack("<h", int(9000 * envelope * tone))
    header = b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(samples))
    return header + bytes(samples)
