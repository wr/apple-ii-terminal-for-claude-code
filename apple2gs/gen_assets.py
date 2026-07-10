#!/usr/bin/env python3
"""Generate 640-mode SHR assets for the Claude GS client.

640 mode: 4 pixels/byte, 2 bits each. Because the hardware picks the palette
entry from BOTH the pixel value and its column-within-byte, we replicate the 4
colors across all 16 palette slots so a 2-bit value means the same color
everywhere. 4 usable colors:  0 black, 1 gray, 2 coral, 3 yellow.
"""
COL_BLACK, COL_GRAY, COL_CORAL, COL_YELLOW = 0, 1, 2, 3
COLORS = {                       # value -> $0RGB (4 bits/channel)
    0: (0x0, 0x0, 0x0),          # black background
    1: (0x9, 0x9, 0x9),          # mid gray    (Claude replies + input box)
    2: (0xD, 0x7, 0x5),          # coral       (mascot / titles / spinner)
    3: (0xF, 0xF, 0xF),          # white       (user's submitted messages)
}

# ---- mascot art: chunky pixel critter, coral body + black square eyes + legs.
# One char = one source pixel; scaled up H/V in emit_mascot (640-mode pixels are
# narrow, so we stretch more horizontally to look square).
def mascot_frames():
    """Session mascot: the ORIGINAL hand-drawn critter, one static frame
    (no blinking, no hopping - per Wells)."""
    return [[
        "..CCCCCCCCCCCC..",
        "..CCCCCCCCCCCC..",
        "..CCKCCCCCCKCC..",
        "..CCKCCCCCCKCC..",
        "CCCCCCCCCCCCCCCC",
        "CCCCCCCCCCCCCCCC",
        "..CCCCCCCCCCCC..",
        "..CCCCCCCCCCCC..",
        "...C.C....C.C...",
        "...C.C....C.C...",
    ]]


MASCOT_HSCALE = 4      # source px -> N screen px horizontally
MASCOT_VSCALE = 2      # source px -> N scanlines vertically (640 px are narrow)
# . black, C coral body, K black (eyes), G gray (hardware), W white
MLEG = {".": 0, "C": 2, "K": 0, "G": 1, "W": 3, "S": 1}
MASCOT_FRAMES = mascot_frames()

# boot-phase palette (splash + menu): entry 1 = the sprite's shadow coral
# (doubles as dim menu text), entry 3 = platinum (computer, keyboard, bright
# menu text). The session palette (gray/white) is loaded at Connect.
COLORS_SPLASH = {0: (0x0, 0x0, 0x0), 1: (0xA, 0x5, 0x4),
                 2: (0xD, 0x7, 0x5), 3: (0xC, 0xC, 0xC)}


def pack640(pixels):
    """pixels: list of 2-bit values, length multiple of 4 -> bytes (4px each,
    leftmost pixel in bits 7-6)."""
    out = []
    for i in range(0, len(pixels), 4):
        p0, p1, p2, p3 = pixels[i:i + 4]
        out.append((p0 << 6) | (p1 << 4) | (p2 << 2) | p3)
    return out


def emit_palette():
    lines = ["shr_palette:"]
    # 16 entries; entry n uses color (n & 3)
    for n in range(16):
        r, g, b = COLORS[n & 3]
        lines.append(f"    .word ${(r<<8)|(g<<4)|b:04X}")
    lines.append("shr_palette_splash:   ; shadow coral + laptop gray variant")
    for n in range(16):
        r, g, b = COLORS_SPLASH[n & 3]
        lines.append(f"    .word ${(r<<8)|(g<<4)|b:04X}")
    return "\n".join(lines)


# ---- splash: an EXACT port of clawd.gif (Clawd whips out a laptop, types,
# puts it away). All 47 frames are extracted at build time from clawd.gif at
# its native 5.75px pitch and played with the gif's own frame timing. The
# client draws them 4x (each source pixel = 16px wide, 8 scanlines).
# Colors: 0 black (bg + eyes), 1 shadow coral, 2 coral, 3 laptop gray.
# Requires Pillow (pip install pillow) at build time.
SPLASH_SRC = "clawd.gif"


# pixel-perfect poses from the official spritesheet (native 5px pitch),
# used to overwrite any gif frame that matches one - the gif is a lossy
# half-res render, the sheet is ground truth. Chars: C coral, S shadow,
# K eye, G laptop, . empty.
_CHV = {".": 0, "C": 2, "S": 1, "K": 0, "G": 3, "W": 3}
_SHEET_ART_SRC = [
    [  # stand, 24x16
        "....CCCCCCCCCCCCCCCC....",
        "....CCCCCCCCCCCCCCCC....",
        "....CCKKCCCCCCCCKKCC....",
        "....CCKKCCCCCCCCKKCC....",
        "CCCCCCCCCCCCCCCCCCCCCCCC",
        "CCCCCCCCCCCCCCCCCCCCCCCC",
        "CCCCCCCCCCCCCCCCCCCCCCCC",
        "CCCCCCCCCCCCCCCCCCCCCCCC",
        "....CCCCCCCCCCCCCCCC....",
        "....CCCCCCCCCCCCCCCC....",
        "....CCCCCCCCCCCCCCCC....",
        "....CCCCCCCCCCCCCCCC....",
        "....CC..CC....CC..CC....",
        "....CC..CC....CC..CC....",
        "....CC..CC....CC..CC....",
        "....CC..CC....CC..CC....",
    ],
    [  # typing A
        "...........CCCCCCCCCCCCSSSS.",
        "...........CCCCCCCCCCCCSSSS.",
        "...........CCCCCCCCCCCCSSSS.",
        "...........KKCCCCCCKKCCSSSS.",
        "...........KKCCCCCCKKCCSSSS.",
        "........CCCCCCCCCCCCCCCSSSS.",
        "........CCCCCCCCCCCCCCCSSSS.",
        "........CCCCCCCCCCCCCCCSSSS.",
        "G.......CCCCCCCCCCCCCCCSSSS.",
        "GG.........CCCCCCCCCCCCSSSS.",
        ".GG....SSSSCCCCCCCCCCCCSSSS.",
        "..GG...SSSSCC..CC....CC..SS.",
        "...GG..SSSSCCC.CCC...CCC.SSS",
        "....GGGGGG..CC..CC....CC..SS",
    ],
    [  # typing B
        "...........CCCCCCCCCCCCSSSS.",
        "...........CCCCCCCCCCCCSSSS.",
        "...........CCCCCCCCCCCCSSSS.",
        "...........KKCCCCCCKKCCSSSS.",
        "...........KKCCCCCCKKCCSSSS.",
        ".......SSSSCCCCCCCCCCCCSSSS.",
        ".......SSSSCCCCCCCCCCCCSSSS.",
        ".......SCCCCCCCCCCCCCCCSSSS.",
        "G......SCCCCCCCCCCCCCCCSSSS.",
        "GG.....SCCCCCCCCCCCCCCCSSSS.",
        ".GG.....CCCCCCCCCCCCCCCSSSS.",
        "..GG....CCCCC..CC....CC..SS.",
        "...GG......CCC.CCC...CCC.SSS",
        "....GGGGGG..CC..CC....CC..SS",
    ],
    [  # typing C
        "...........CCCCCCCCCCCCSSSS.",
        "...........CCCCCCCCCCCCSSSS.",
        "...........CCCCCCCCCCCCSSSS.",
        "...........KKCCCCCCKKCCSSSS.",
        "...........KKCCCCCCKKCCSSSS.",
        "...........CCCCCCCCCCCCSSSS.",
        "........CCCCCCCCCCCCCCCSSSS.",
        "G......SCCCCCCCCCCCCCCCSSSS.",
        "GG.....SCCCCCCCCCCCCCCCSSSS.",
        ".GG....SCCCCCCCCCCCCCCCSSSS.",
        "..GG...SSSSCCCCCCCCCCCCSSSS.",
        "..GG...SSSSCC..CC....CC..SS.",
        "...GG..SSSSCCC.CCC...CCC.SSS",
        "....GGGGGG..CC..CC....CC..SS",
    ],
]
# substitution uses ONLY the typing poses: matching the stand art against
# the intro/outro frames collapsed their subtle acting into one rigid pose
SHEET_ARTS = [[[_CHV[c] for c in row] for row in art] for art in _SHEET_ART_SRC[1:]]


def _sheet_substitute(m):
    """If a quantized gif frame matches a spritesheet pose (>=80% cell
    agreement, size within 1 cell), replace it with the sheet's exact
    pixels, anchored at the frame's bottom-right (feet stay planted)."""
    # anchor on the CORAL body only: gray (keyboard) cells wander from
    # frame to frame and made the substituted art - and his head - bob
    pts = [(x, y) for y, row in enumerate(m) for x, v in enumerate(row) if v in (1, 2)]
    if not pts:
        return m
    bx1 = max(p[0] for p in pts); by1 = max(p[1] for p in pts)
    bx0 = min(p[0] for p in pts); by0 = min(p[1] for p in pts)
    bw, bh = bx1 - bx0 + 1, by1 - by0 + 1
    best, best_score, best_off = None, 0.0, (0, 0)
    for art in SHEET_ARTS:
        apts = [(x, y) for y, row in enumerate(art) for x, v in enumerate(row)
                if v in (1, 2)]
        ax1 = max(p[0] for p in apts); ay1 = max(p[1] for p in apts)
        ax0 = min(p[0] for p in apts); ay0 = min(p[1] for p in apts)
        if abs((ax1 - ax0) - (bx1 - bx0)) > 2 or abs((ay1 - ay0) - (by1 - by0)) > 2:
            continue
        ox, oy = bx1 - ax1, by1 - ay1       # align the BODIES bottom-right
        total = match = 0
        for y in range(len(art)):
            for x in range(len(art[0])):
                gy, gx = oy + y, ox + x
                g = m[gy][gx] if 0 <= gy < len(m) and 0 <= gx < len(m[0]) else 0
                a = art[y][x]
                if a in (1, 2) or g in (1, 2):
                    total += 1
                    if a == g:
                        match += 1
        score = match / total if total else 0.0
        if score > best_score:              # BEST art wins, not the first
            best, best_score, best_off = art, score, (ox, oy)
    if best and best_score >= 0.72:
        ox, oy = best_off
        out = [[0] * len(m[0]) for _ in m]
        for y in range(len(best)):
            for x in range(len(best[0])):
                gy, gx = oy + y, ox + x
                if best[y][x] and 0 <= gy < len(m) and 0 <= gx < len(m[0]):
                    out[gy][gx] = best[y][x]
        return out, True
    return m, False


def splash_extract():
    from PIL import Image
    from collections import Counter
    # HALF the gif's 5.75px pixel pitch: the spritesheet proves the true art
    # grid is twice as fine as the gif renders it (sheet body = 24x16, gif
    # body = 12x8). Sampling at sheet resolution keeps the laptop line - a
    # single fine cell wide - from flickering in and out between frames.
    P = 2.875

    def classify(p):
        r, g, b = p[:3]
        lum = (r + g + b) / 3
        if r - b > 30 and r > 120:           # warm -> coral family
            return 2 if lum >= 118 else 1    # gif body lum ~128, shadow ~109
        if lum < 110:                        # bg, slab edge (~95), eyes
            return 0
        if abs(r - g) < 22 and abs(g - b) < 22:
            return 3                         # NEUTRAL gray only = the prop
        return 0                             # anti-aliased fringe: drop it

    gif = Image.open(SPLASH_SRC)
    frames_px, durs = [], []
    for i in range(gif.n_frames):
        gif.seek(i)
        durs.append(gif.info.get("duration", 70))
        frames_px.append(gif.convert("RGB"))

    # fixed crop shared by every frame: the union of all body pixels, plus
    # laptop pixels no lower than his feet (that excludes the slab + logo)
    body_y, all_x, all_y = [], [], []
    for im in frames_px:
        px = im.load()
        for y in range(im.height):
            for x in range(im.width):
                if classify(px[x, y]) in (1, 2):
                    all_x.append(x); all_y.append(y); body_y.append(y)
    feet = max(body_y)
    for im in frames_px:
        px = im.load()
        for y in range(0, feet + 2):    # laptop pixels; +2 excludes the slab
            for x in range(im.width):   # edge highlight under his feet
                if classify(px[x, y]) == 3:
                    all_x.append(x); all_y.append(y)
    x0, y0 = min(all_x), min(all_y)
    x1, y1 = max(all_x), min(feet + 2, max(all_y))
    w = round((x1 - x0) / P) + 1
    h = round((y1 - y0) / P) + 1
    w += (-w) % 4                       # pack640 needs a multiple of 4
    mats = []
    for im in frames_px:
        px = im.load()
        m = []
        for cy in range(h):
            row = []
            for cx in range(w):
                votes = Counter()
                for fy in (0.35, 0.65):
                    for fx in (0.35, 0.65):
                        x, y = int(x0 + (cx + fx) * P), int(y0 + (cy + fy) * P)
                        if 0 <= x < im.width and y0 <= y <= y1:
                            votes[classify(px[x, y])] += 1
                row.append(votes.most_common(1)[0][0] if votes else 0)
            m.append(list(row))
        mats.append(m)

    def _degray(m):
        """A gray cell with no gray neighbour is an anti-aliasing artifact
        (eye rims, hand edges) - the real prop is always a connected line."""
        for y in range(h):
            for x in range(w):
                if m[y][x] != 3:
                    continue
                lonely = True
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= ny < h and 0 <= nx < w and m[ny][nx] == 3:
                        lonely = False
                if lonely:
                    m[y][x] = 0
        return m

    subbed = [_sheet_substitute(_degray(m)) for m in mats]
    mats = [s[0] for s in subbed]
    typing = [s[1] for s in subbed]

    # scoot Clawd one block down and left (art direction; the keyboard pass
    # below re-stamps from the shifted cells, and the prop stays put)
    for m in mats:
        for y in range(h - 1, -1, -1):
            for x in range(w):
                sy, sx = y - 1, x + 1
                m[y][x] = m[sy][sx] if (0 <= sy < h and 0 <= sx < w) else 0

    # keyboard: erase every gray cell (this also wipes the anti-aliasing
    # artifacts that were landing near his eyes and claws) and stamp a
    # rigid keyboard sprite - per Wells' sketch - centered where they were.
    KB = ["GGGGGG.",
          "GGGGGGG"]
    KB_TILT = ["....GGG",
               ".GGGGGG",
               "GGGG..."]
    frame_cells = []
    for m in mats:
        cells = [(x, y) for y in range(h) for x in range(w) if m[y][x] == 3]
        for x, y in cells:
            m[y][x] = 0
        frame_cells.append(cells)
    down_x = [round(sum(c[0] for c in cells) / len(cells))
              for cells in frame_cells
              if len(cells) >= 3 and sum(c[1] for c in cells) / len(cells) >= h - 6]
    # -2 (not the centering -3): parked one column nearer Clawd, per Wells
    rest_x = round(sum(down_x) / len(down_x)) - 2 if down_x else 4
    for m, cells in zip(mats, frame_cells):
        if len(cells) < 3:
            continue
        cy = sum(c[1] for c in cells) / len(cells)
        if cy >= h - 6:
            kx, ky = rest_x, h - 2          # parked flush on the table
            sprite = KB
        else:
            kx = round(sum(c[0] for c in cells) / len(cells)) - 3
            ky = round(cy) - 1
            sprite = KB_TILT                # a little swing in the carry
        for row_i, krow in enumerate(sprite):
            for col_i, ch in enumerate(krow):
                yy, xx = ky + row_i, kx + col_i
                if ch == "G" and 0 <= yy < h and 0 <= xx < w and m[yy][xx] == 0:
                    m[yy][xx] = 3

    # ---- the set piece (per sketch v2): square-cornered CRT, screen strip
    # facing Clawd, vent slot between tube and case, base lip at the front
    # only. Platinum body; the strip flashes between the corals during typing.
    PROP = [
        ".....GGGGG..",
        "GGGGGGGGGG..",
        "GGGGGGGGGGO.",
        "GGGGGGGGGGO.",
        "GGGGGGGGGGO.",
        "GGGGGGGGGGO.",
        "GGGGGGGGGGO.",
        "GGGGGGGGGGO.",
        "GGGGGGGGGGO.",
        "GGGGGGGGGG..",
        "GGGGGGGGGG..",
        ".GKKKKKKG...",
        "GGGGGGGGGG..",
        "GGGGGGGGGG..",
        "GGGGGGGGGG..",
        "GGGGGGGGGG..",
        "GGGGGGGGGGG.",
    ]
    pw = len(PROP[0])
    new_w = pw + 3 + w
    new_w += (-new_w) % 4
    ext = new_w - w
    out_mats = []
    for fi, m in enumerate(mats):
        kb_down = typing[fi]
        nm = [[0] * new_w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                nm[y][ext + x] = m[y][x]
        oy = h - len(PROP)                  # bottom-aligned with the floor
        strip = 2 if (not kb_down or fi & 1) else 1   # flash only while typing
        for py, prow in enumerate(PROP):
            for px_, chv in enumerate(prow):
                if chv == ".":
                    continue
                v = strip if chv == "O" else _CHV[chv]
                if 0 <= oy + py < h:
                    nm[oy + py][3 + px_] = v
        out_mats.append(nm)
    mats = out_mats
    w = new_w

    # art direction: erase the one-pixel "shoulder nub" - a coral cell that
    # sticks out exactly one column left of the head side, one row above a
    # wide arm row. It's quantization residue from the gif's rounded
    # shoulder, most visible on the stand pose the inter-loop pause holds.
    def _left_edge(m, y):
        for x in range(pw + 3, w):
            if m[y][x] == 2:
                return x
        return None
    for m in mats:
        edges = [_left_edge(m, y) for y in range(h)]
        for y in range(2, h - 1):
            a, b, c = edges[y - 2], edges[y - 1], edges[y]
            if (a is not None and b is not None and c is not None
                    and c <= b - 3 and b == a - 1):
                m[y - 1][b] = 0

    mats = [tuple(tuple(r) for r in m) for m in mats]

    uniq, idx = [], []
    for m in mats:
        if m in uniq:
            idx.append(uniq.index(m))
        else:
            uniq.append(m); idx.append(len(uniq) - 1)
    seq = []
    for i, j in enumerate(idx):
        vbl = max(2, round(durs[i] * 60 / 1000))
        if seq and seq[-1][0] == j and seq[-1][1] + vbl < 250:
            seq[-1] = (j, seq[-1][1] + vbl)
        else:
            seq.append((j, vbl))
    return uniq, seq, w, h


def emit_splash():
    uniq, seq, w, h = splash_extract()
    fsize = w * h // 4
    lines = [f"SPLASH_BYTES = {w // 4}",
             f"SPLASH_H = {h}",
             f"SPLASH_FSIZE = {fsize}   ; bytes per frame (stored 1x, drawn 4x)",
             f"; {len(uniq)} unique frames of {w}x{h} cells, "
             f"{len(seq)} storyboard entries",
             "splash_data:"]
    for fi, m in enumerate(uniq):
        lines.append(f"    ; frame {fi}")
        for row in m:
            packed = pack640(list(row))
            lines.append("    .byte " + ",".join(f"${b:02X}" for b in packed))
    lines.append("splash_off:")
    for i in range(len(uniq)):
        lines.append(f"    .word {i * fsize}")
    lines.append("splash_seq:   ; frame, vblanks, ... , $FF (the gif's timing)")
    for j, vbl in seq:
        lines.append(f"    .byte {j}, {vbl}")
    lines.append("    .byte $FF")
    # 4x horizontal expansion: table j maps a packed byte to the solid byte
    # for its j-th pixel (each 2-bit pixel becomes a full byte of 4 copies)
    solid = (0x00, 0x55, 0xAA, 0xFF)
    for j in range(4):
        shift = 6 - 2 * j
        lines.append(f"expand4_{j}:")
        vals = [solid[(b >> shift) & 3] for b in range(256)]
        for i in range(0, 256, 16):
            lines.append("    .byte " + ",".join(f"${v:02X}" for v in vals[i:i+16]))
    return "\n".join(lines)


def emit_mascot():
    hs, vs = MASCOT_HSCALE, MASCOT_VSCALE
    assert len({len(f) for f in MASCOT_FRAMES}) == 1, "frames must share a height"
    w = max(len(r) for f in MASCOT_FRAMES for r in f)
    # scaled width must be a multiple of 4 (pack640 packs 4 px/byte)
    scaled_w = (w * hs) - ((w * hs) % 4)
    bytes_per_row = scaled_w // 4
    frames_rows = []
    for frame in MASCOT_FRAMES:
        rows = [r.ljust(w, ".") for r in frame]
        out_rows = []
        for row in rows:
            px = []
            for ch in row:
                px += [MLEG.get(ch, 0)] * hs    # scale horizontally
            px = px[:bytes_per_row * 4]         # trim to packed width
            packed = pack640(px)
            out_rows += [packed] * vs           # scale vertically
        frames_rows.append(out_rows)
    h = len(frames_rows[0])
    lines = [f"MASCOT_H = {h}", f"MASCOT_BYTES = {bytes_per_row}",
             "mascot_data:"]
    for fi, out_rows in enumerate(frames_rows):
        lines.append(f"    ; frame {fi}")
        for packed in out_rows:
            lines.append("    .byte " + ",".join(f"${b:02X}" for b in packed))
    return "\n".join(lines)


def emit_expand():
    """EXPAND[color*16 + nibble] = byte with each of the nibble's 4 bits blown
    up to the 2-bit color (bit3 -> leftmost pixel)."""
    lines = ["expand_tbl:"]
    for c in range(4):
        row = []
        for n in range(16):
            b = 0
            if n & 8: b |= c << 6
            if n & 4: b |= c << 4
            if n & 2: b |= c << 2
            if n & 1: b |= c
            row.append(b)
        lines.append(f"    .byte " + ",".join(f"${b:02X}" for b in row))
    return "\n".join(lines)


def load_unscii(path="unscii-8.hex"):
    """Parse unscii-8.hex -> {codepoint: [8 row bytes]}. Each line is
    'codepoint:hexbitmap'; an 8x8 glyph is 16 hex chars = 8 bytes, one byte
    per row with bit7 = leftmost pixel (already the Apple II convention)."""
    glyphs = {}
    for line in open(path):
        line = line.strip()
        if not line or ":" not in line:
            continue
        cp, hx = line.split(":", 1)
        if len(hx) != 16:           # skip double-wide / non-8x8 glyphs
            continue
        rows = [int(hx[i:i + 2], 16) for i in range(0, 16, 2)]
        glyphs[int(cp, 16)] = rows
    return glyphs


# Claude Code's rotating "thinking" gerunds (a subset that fits the field).
SPIN_WORDS = [
    "Cogitating", "Pondering", "Ruminating", "Percolating", "Noodling",
    "Musing", "Simmering", "Brewing", "Conjuring", "Puzzling", "Marinating",
    "Vibing", "Schlepping", "Wrangling", "Reticulating", "Cerebrating",
]


def emit_spinwords():
    # Pointer table + variable-length " Word..." strings, so the client can draw
    # the elapsed-time counter right after the word instead of at a fixed column.
    lines = [f"SPIN_COUNT = {len(SPIN_WORDS)}", "spin_ptrs:"]
    for i in range(len(SPIN_WORDS)):
        lines.append(f"    .addr spin_w{i}")
    for i, w in enumerate(SPIN_WORDS):
        lines.append(f'spin_w{i}: .byte " {w}...",0')
    return "\n".join(lines)


def emit_bullet():
    # small filled dot, vertically centered in the 8x8 cell (bit7 = leftmost)
    rows = [0x00, 0x00, 0x3C, 0x7E, 0x7E, 0x3C, 0x00, 0x00]
    return "bullet_data:\n    .byte " + ",".join(f"${b:02X}" for b in rows)


def emit_font():
    glyphs = load_unscii()
    blank = [0] * 8
    lines = ["FONT_FIRST = 32", "font_data:"]
    for code in range(32, 127):
        rowbytes = glyphs.get(code, blank)
        lines.append(f"    ; '{chr(code)}'")
        lines.append("    .byte " + ",".join(f"${b:02X}" for b in rowbytes))
    return "\n".join(lines)


# ---- menu music: two-voice chiptunes for the Ensoniq DOC -------------------
# Note streams are (freq_lo, freq_hi, dur_vblanks) triplets; dur 0 wraps the
# voice. freq 0 = rest. With 2 oscillators scanned the DOC steps each one at
# 894886.25/(2+2) Hz; a 256-byte wave at resolution 0 repeats every 2^17
# accumulator counts, so freq_reg = f_hz * 2^17 / scan_rate.
DOC_SCAN = 894886.25 / 4

def _hz(name):
    semis = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4,
             "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9,
             "A#": 10, "Bb": 10, "B": 11}
    return 440.0 * 2 ** ((12 * (int(name[-1]) + 1) + semis[name[:-1]] - 69) / 12)

def _voice(notes, bpm):
    """notes: (name_or_R, beats). Durations use cumulative rounding so both
    voices stay vblank-locked. Each melodic note gets a short articulation
    gap shaved off its tail - the DOC free-runs, so back-to-back notes
    otherwise smear together legato with no audible re-attack."""
    out, cum, prev = [], 0.0, 0
    for name, beats in notes:
        cum += beats
        end = round(cum * 3600 / bpm)      # 60 vblanks/sec, 60 s/min
        total = max(1, min(255, end - prev))
        prev = end
        if name == "R":
            out += [0, 0, total]
            continue
        f = max(1, min(0xFFFF, round(_hz(name) * 131072 / DOC_SCAN)))
        gap = 2 if total >= 10 else (1 if total >= 3 else 0)
        out += [f & 0xFF, f >> 8, total - gap]
        if gap:
            out += [0, 0, gap]
    out += [0, 0, 0]                        # terminator: end of tune
    return out

def _wave():
    """Rounded square: softer than a pure square, still chippy. A $00 sample
    HALTS a DOC oscillator, so floor at $01."""
    w = [0xD8 if i < 128 else 0x28 for i in range(256)]
    for _ in range(3):
        w = [(w[i - 1] + 2 * w[i] + w[(i + 1) % 256]) // 4 for i in range(256)]
    return [max(1, v) for v in w]

# The menu ditty: "GROOVE", winner of a 4-round audition (2026-07-09).
# Wells' bar spec: hit on 1, swung 2-e-&-a run, swung 3-&, beat 4 empty.
# Swing = triplet-feel durations (1/3 + 1/6 beat pairs, the & at 2/3).
# Played ONCE per menu visit, not looped.
MUS_BPM = 144
# the dooo-doot pair: dooo on 3, doot on the downbeat of 4. (The & of 3
# read too tight, the swung & of 4 too long - Wells, one round each.)
MUS_MEL = [("G4",.5),("R",.5),
           ("C5",1/3),("D5",1/6),("E5",1/3),("D5",1/6),
           ("C5",2/3),("R",1/3),("G4",1/3),("R",2/3),
           ("A4",.5),("R",.5),
           ("C5",1/3),("D5",1/6),("G5",1/3),("E5",1/6),
           ("D5",2/3),("R",1/3),("C5",1/3),("R",2/3)]
# bass on the downbeats only - a swung pickup on the "a" of 4 landed in
# the wrong-feeling spot (Wells, twice)
MUS_BASS = [("C3",1),("R",1),("G2",1),("R",1),
            ("A2",1),("R",1),("G2",1),("R",1)]

def emit_music():
    assert sum(b for _, b in MUS_MEL) == sum(b for _, b in MUS_BASS)
    wave = _wave()
    lines = ["wave_data:"]
    for i in range(0, 256, 16):
        lines.append("    .byte " + ",".join(f"${b:02X}" for b in wave[i:i + 16]))
    blob = _voice(MUS_MEL, MUS_BPM)
    lines.append("MUS_V0 = 0")
    lines.append(f"MUS_V1 = {len(blob)}")
    blob += _voice(MUS_BASS, MUS_BPM)
    lines.append("music_data:")
    for i in range(0, len(blob), 16):
        lines.append("    .byte " + ",".join(f"${b:02X}" for b in blob[i:i + 16]))
    return "\n".join(lines)


if __name__ == "__main__":
    with open("assets.inc", "w") as f:
        f.write("; generated by gen_assets.py (640 mode)\n")
        f.write(emit_palette() + "\n\n")
        f.write(emit_expand() + "\n\n")
        f.write(emit_mascot() + "\n\n")
        f.write(emit_splash() + "\n\n")
        f.write(emit_spinwords() + "\n\n")
        f.write(emit_bullet() + "\n\n")
        f.write(emit_music() + "\n\n")
        f.write(emit_font() + "\n")
    print("wrote assets.inc")
