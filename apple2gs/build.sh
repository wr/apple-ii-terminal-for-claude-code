#!/bin/bash
# Build the SHR graphics client disk. Run from apple2gs/.
set -e
cd "$(dirname "$0")"
# dos33fsprogs checkout (https://github.com/deater/dos33fsprogs, `make` in
# utils/dos33fs-utils and utils/asoft_basic-utils). Override with DOS33FSPROGS.
DOS33FSPROGS="${DOS33FSPROGS:-/tmp/dos33fsprogs}"
DOS33="$DOS33FSPROGS/utils/dos33fs-utils/dos33"
TOK="$DOS33FSPROGS/utils/asoft_basic-utils/tokenize_asoft"
[ -x "$DOS33" ] || { echo "dos33fsprogs not found at $DOS33FSPROGS - clone+make it or set DOS33FSPROGS" >&2; exit 1; }
# Base image: pristine Apple DOS 3.3 System Master (Jan 1983). We inject our
# files into it instead of generating a disk from scratch - a master-based
# image is proven to boot on both KEGS and real hardware via FloppyEmu.
# (FloppyEmu gotcha: update the SD card with `dd conv=notrunc` over the
# existing image file - a fresh copy can land fragmented and the Emu
# refuses non-contiguous files.)
BASE=dos33-master-jan83.dsk

python3 gen_assets.py
ca65 --cpu 65816 -o claude.o claude.s
ld65 -C claude.cfg -o claude.obj claude.o

# 8-bit client (IIe/IIc/IIc+/II+) shares the disk
ca65 --cpu 6502 -o ../apple2/claude2.o ../apple2/claude2.s
ld65 -C ../apple2/claude2.cfg -o COBJ8 ../apple2/claude2.o

# HELLO picks the client for the machine: IIgs -> COBJ (SHR), everything
# else -> COBJ8 (text). GS vs enhanced IIe ($FBB3=6, $FBC0=$E0 on both)
# is split by the GS id hook: SEC / JSR $FE1F / carry clear = GS. The
# stub POKEd at $300 stores the carry at 783.
# dos33 (BSD getopt) needs flags BEFORE the disk, and no '.' in filenames.
cat > hello.bas <<'BAS'
10 P1 = PEEK(64435): IF P1 <> 6 THEN 100
20 P2 = PEEK(64448): IF P2 = 0 OR P2 = 234 THEN 100
30 POKE 768,56: POKE 769,32: POKE 770,31: POKE 771,254: POKE 772,169: POKE 773,0: POKE 774,42: POKE 775,141: POKE 776,15: POKE 777,3: POKE 778,96: CALL 768
40 IF PEEK(783) = 0 THEN PRINT CHR$(4);"BRUN COBJ"
100 PRINT CHR$(4);"BRUN COBJ8"
BAS
$TOK < hello.bas > HH
cp claude.obj COBJ

cp "$BASE" CLAUDE.dsk
$DOS33 CLAUDE.dsk UNLOCK HELLO
$DOS33 -y CLAUDE.dsk DELETE HELLO
$DOS33 -y CLAUDE.dsk SAVE A HH HELLO
$DOS33 -a 0x4000 CLAUDE.dsk BSAVE COBJ COBJ
$DOS33 -a 0x2000 CLAUDE.dsk BSAVE COBJ8 COBJ8
$DOS33 CLAUDE.dsk CATALOG
# convenience deploy for KEGS (~/config.kegs boots this path); harmless if absent
cp CLAUDE.dsk "$HOME/Downloads/CLAUDE.dsk" 2>/dev/null || true
echo "=== built CLAUDE.dsk (master-based, boots KEGS + FloppyEmu + real drives) ==="
