#!/usr/bin/env python3
"""Render a PNG that mimics the SHR client screen, so we can eyeball font
legibility without an emulator. Reproduces claude.s's putchar math.

Usage: python3 preview.py [assets.inc] [out.png]
Parses shr_palette + font_data (8 bytes/glyph, bit7=leftmost) from assets.inc
and lays out a sample transcript in the same colors the client uses.
"""
import re
import sys

from PIL import Image

MODE = "640"  # "640" (4px/byte, 2bit) or "320" (2px/byte, 4bit)


def parse_assets(path):
    text = open(path).read()

    # palette: 16 .word $0RGB after shr_palette:
    pal_block = text.split("shr_palette:")[1]
    words = re.findall(r"\.word\s+\$([0-9A-Fa-f]{4})", pal_block)[:16]
    palette = []
    for w in words:
        v = int(w, 16)
        r = (v >> 8) & 0xF
        g = (v >> 4) & 0xF
        b = v & 0xF
        palette.append((r * 17, g * 17, b * 17))  # 4-bit -> 8-bit

    # font: sequence of .byte rows after font_data:, 8 bytes per glyph
    font_block = text.split("font_data:")[1]
    nums = re.findall(r"\$([0-9A-Fa-f]{2})", font_block)
    allbytes = [int(n, 16) for n in nums]
    glyphs = [allbytes[i:i + 8] for i in range(0, len(allbytes) - 7, 8)]

    # mascot: MASCOT_H rows of MASCOT_BYTES 640-packed bytes (4px/byte, 2bit)
    m_h = int(re.search(r"MASCOT_H\s*=\s*(\d+)", text).group(1))
    m_bytes = int(re.search(r"MASCOT_BYTES\s*=\s*(\d+)", text).group(1))
    m_block = text.split("mascot_data:")[1]
    m_all = [int(n, 16) for n in re.findall(r"\$([0-9A-Fa-f]{2})", m_block)]
    mascot = []  # list of rows, each a list of 2-bit pixel values
    for r in range(m_h):
        rowbytes = m_all[r * m_bytes:(r + 1) * m_bytes]
        row = []
        for b in rowbytes:
            row += [(b >> 6) & 3, (b >> 4) & 3, (b >> 2) & 3, b & 3]
        mascot.append(row)
    return palette, glyphs, mascot


def glyph_for(glyphs, ch, first=32):
    idx = ord(ch) - first
    if 0 <= idx < len(glyphs):
        return glyphs[idx]
    return [0] * 8


def draw_char(px, x0, y0, glyph, color):
    """Set 8x8 pixels (color value 0..15) into px[] value grid at char cell."""
    for row in range(8):
        bits = glyph[row]
        for col in range(8):
            if bits & (0x80 >> col):
                px[(x0 + col, y0 + row)] = color


def draw_str(px, col, row, s, color, glyphs):
    x0 = col * 8
    y0 = row * 8
    for i, ch in enumerate(s):
        draw_char(px, x0 + i * 8, y0, glyph_for(glyphs, ch), color)


def main():
    assets = sys.argv[1] if len(sys.argv) > 1 else "assets.inc"
    out = sys.argv[2] if len(sys.argv) > 2 else "preview.png"
    palette, glyphs, mascot = parse_assets(assets)

    W, H = 640, 200  # SHR 640 mode logical grid (we render text at 8x8 cells)
    px = {}  # (x,y) -> color value

    # colors: 0 black, 1 gray, 2 coral, 3 white (matches gen_assets)
    GRAY, CORAL, WHITE = 1, 2, 3

    # mascot: drawn at scanline 8, pixel 8 (SHR_BASE + 8*160 + 2 bytes)
    for r, row in enumerate(mascot):
        for c, v in enumerate(row):
            if v:
                px[(8 + c, 8 + r)] = v

    # header (rows 1-3, col 15 to clear the mascot region)
    draw_str(px, 12, 1, "Claude Code v2.1.204", CORAL, glyphs)
    draw_str(px, 12, 2, "Opus 4.8 (1M) - high effort", GRAY, glyphs)
    draw_str(px, 12, 3, "Apple II <-> Claude Code", CORAL, glyphs)
    # transcript: submitted messages white, Claude replies gray
    draw_str(px, 0, 6, "> Testing", WHITE, glyphs)
    draw_str(px, 0, 8, "Working. What do you need?", GRAY, glyphs)
    draw_str(px, 0, 10, "> what time is it", WHITE, glyphs)
    draw_str(px, 0, 12, "The quick brown fox jumps over 13 lazy dogs.", GRAY, glyphs)

    # Build the logical 640x200 framebuffer, 1 output px per SHR px.
    img = Image.new("RGB", (W, H), palette[0])
    ip = img.load()
    for (x, y), v in px.items():
        if 0 <= x < W and 0 <= y < H:
            ip[x, y] = palette[v & 0xF]
    # KEGS displays 640x200 stretched to a 4:3 screen, so each SHR pixel is
    # ~0.42 wide : 1 tall. Resize to a 4:3 frame so the preview matches KEGS.
    full = img.resize((1280, 960), Image.NEAREST)
    full.save(out)
    # Also a zoomed crop of the mascot region for close comparison.
    crop = img.crop((0, 0, 120, 64)).resize((120 * 8, 64 * 19), Image.NEAREST)
    mout = out.rsplit(".", 1)[0] + "_mascot.png"
    crop.save(mout)
    print(f"wrote {out} ({full.size[0]}x{full.size[1]}) and {mout}")


if __name__ == "__main__":
    main()
