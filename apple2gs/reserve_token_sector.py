#!/usr/bin/env python3
"""Reserve the device-token sector (T=0x12 S=0x0F) on a DOS 3.3 disk image so
neither DOS nor dos33fsprogs ever allocates it, and zero it (no token yet).

DOS 3.3: 35 tracks x 16 sectors x 256 bytes. VTOC is track 0x11 sector 0.
The free-sector bitmap starts at VTOC offset 0x38, 4 bytes per track:
bytes [0],[1] = sectors 15..8 / 7..0 as bits (1 = free)."""
import sys

TRACK, SECTOR = 0x12, 0x0F
SECTOR_SIZE = 256
SECTORS_PER_TRACK = 16


def offset(track: int, sector: int) -> int:
    return (track * SECTORS_PER_TRACK + sector) * SECTOR_SIZE


def main(path: str) -> int:
    with open(path, "r+b") as f:
        img = bytearray(f.read())
        vtoc = offset(0x11, 0)
        # bitmap entry for TRACK: 4 bytes at vtoc+0x38+track*4
        bm = vtoc + 0x38 + TRACK * 4
        # sector 15..8 in byte 0 (bit 7..0), 7..0 in byte 1. S=0x0F -> byte0 bit7.
        if SECTOR >= 8:
            bit_set = bool(img[bm] & (1 << (SECTOR - 8)))
        else:
            bit_set = bool(img[bm + 1] & (1 << SECTOR))
        if not bit_set:
            # Already allocated: something else grew into our reserved sector.
            # Fail loudly at build time instead of silently corrupting a file.
            print(
                f"error: T={TRACK:#x} S={SECTOR:#x} is already allocated "
                f"(VTOC free bit clear) in {path} - refusing to overwrite",
                file=sys.stderr,
            )
            return 1
        if SECTOR >= 8:
            img[bm] &= ~(1 << (SECTOR - 8)) & 0xFF
        else:
            img[bm + 1] &= ~(1 << SECTOR) & 0xFF
        # zero the sector itself
        so = offset(TRACK, SECTOR)
        img[so:so + SECTOR_SIZE] = b"\x00" * SECTOR_SIZE
        f.seek(0)
        f.write(img)
    print(f"reserved token sector T={TRACK:#x} S={SECTOR:#x} in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
