"""Made-up media for fake mode and tests: a small embroidery-pattern photo (PNG) and a short voice note (WAV).

Both are generated, so the repo holds no binary files for them, and the same bytes come out every time, so the media
store keeps each once.
"""

import math
import struct
import zlib
from functools import cache

CREAM = (247, 240, 226)
TEAL = (14, 110, 100)
RED = (178, 54, 54)
GOLD = (214, 160, 54)


def _png(width: int, height: int, rows: list[bytes]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + row for row in rows)  # filter type 0 on every row
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


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
