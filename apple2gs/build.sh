#!/bin/bash
# Build the SHR graphics client disk. Run from apple2gs/.
set -e
cd "$(dirname "$0")"
DOS33=/tmp/dos33fsprogs/utils/dos33fs-utils/dos33
TOK=/tmp/dos33fsprogs/utils/asoft_basic-utils/tokenize_asoft
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

# dos33 (BSD getopt) needs flags BEFORE the disk, and no '.' in filenames.
printf '10 PRINT CHR$(4);"BRUN COBJ"\n' > hello.bas
$TOK < hello.bas > HH
cp claude.obj COBJ

cp "$BASE" CLAUDEG.dsk
$DOS33 CLAUDEG.dsk UNLOCK HELLO
$DOS33 -y CLAUDEG.dsk DELETE HELLO
$DOS33 -y CLAUDEG.dsk SAVE A HH HELLO
$DOS33 -a 0x4000 CLAUDEG.dsk BSAVE COBJ COBJ
$DOS33 CLAUDEG.dsk CATALOG
cp CLAUDEG.dsk /Users/wells/Downloads/CLAUDEG.dsk
echo "=== deployed Downloads/CLAUDEG.dsk (master-based, FloppyEmu-ready) ==="
