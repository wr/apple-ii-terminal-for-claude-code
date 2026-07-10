#!/bin/bash
# Build the SHR graphics client disk. Run from apple2gs/.
set -e
cd "$(dirname "$0")"
DOS33=/tmp/dos33fsprogs/utils/dos33fs-utils/dos33
TOK=/tmp/dos33fsprogs/utils/asoft_basic-utils/tokenize_asoft
EMPTY=/tmp/dos33fsprogs/empty_disk/empty.dsk

python3 gen_assets.py
ca65 --cpu 65816 -o claude.o claude.s
ld65 -C claude.cfg -o claude.obj claude.o

# dos33 (BSD getopt) needs flags BEFORE the disk, and no '.' in filenames.
printf '10 PRINT CHR$(4);"BRUN COBJ"\n' > hello.bas
$TOK < hello.bas > HH
cp claude.obj COBJ

cp "$EMPTY" CLAUDEG.dsk
$DOS33 -y CLAUDEG.dsk DELETE HELLO >/dev/null 2>&1 || true
$DOS33 -y CLAUDEG.dsk SAVE A HH HELLO
$DOS33 -a 0x4000 CLAUDEG.dsk BSAVE COBJ COBJ
$DOS33 CLAUDEG.dsk CATALOG
cp CLAUDEG.dsk /Users/wells/Downloads/CLAUDEG.dsk
echo "=== deployed Downloads/CLAUDEG.dsk ==="
