"""Draw the app icon (assets/soe.ico) with no image library: a glowing orange gem on a dark tile.

Writes a multi-size .ico whose images are PNGs (supported since Windows Vista).
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "soe.ico"


def _png(size: int, pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    raw = b"".join(b"\x00" + b"".join(struct.pack("BBBB", *p) for p in row) for row in pixels)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def draw(size: int) -> bytes:
    s = size
    px = []
    bg_top, bg_bot = (40, 34, 28), (18, 15, 12)
    gem_light, gem_mid, gem_dark = (255, 214, 140), (232, 138, 60), (150, 62, 22)
    for y in range(s):
        row = []
        for x in range(s):
            # rounded square tile
            u, v = (x + 0.5) / s, (y + 0.5) / s
            r = 0.2
            dx = max(abs(u - 0.5) - (0.5 - r), 0)
            dy = max(abs(v - 0.5) - (0.5 - r), 0)
            d = math.hypot(dx, dy) - r
            alpha = max(0.0, min(1.0, 0.5 - d * s))
            col = _mix(bg_top, bg_bot, v)
            # soft glow behind the gem
            g = math.exp(-(((u - 0.5) ** 2 + (v - 0.52) ** 2) / 0.05))
            col = _mix(col, (120, 60, 20), g * 0.6)
            # gem: diamond with a flat top (crown + pavilion)
            cx, top, mid, bot, half = 0.5, 0.22, 0.42, 0.82, 0.30
            inside = False
            facet = 0.0
            if top <= v <= mid:
                w = half * (0.55 + 0.45 * (v - top) / (mid - top))
                inside = abs(u - cx) <= w
                facet = 0.15 + 0.35 * (1 - (v - top) / (mid - top)) + (0.25 if u < cx else 0)
            elif mid < v <= bot:
                w = half * (1 - (v - mid) / (bot - mid))
                inside = abs(u - cx) <= w
                facet = 0.55 + (0.3 if u > cx else 0) + 0.15 * (v - mid) / (bot - mid)
            if inside:
                gcol = _mix(gem_light, gem_mid, min(1, facet)) if facet < 0.6 else _mix(gem_mid, gem_dark, min(1, (facet - 0.6) / 0.4))
                # thin bright edge on the girdle line
                if abs(v - mid) < 0.012:
                    gcol = _mix(gcol, (255, 236, 200), 0.7)
                col = gcol
            row.append((*col, round(alpha * 255)))
        px.append(row)
    return _png(s, px)


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, blobs = b"", b""
    for s, img in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
        blobs += img
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(header + entries + blobs)
    (OUT.parent / "soe-256.png").write_bytes(images[-1])
    print(OUT)


if __name__ == "__main__":
    main()
