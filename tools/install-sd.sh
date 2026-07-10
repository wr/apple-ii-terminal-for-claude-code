#!/bin/bash
# Install or update the Claude Code ][ disk image on a FloppyEmu SD card.
#
# FloppyEmu requires each image file to be CONTIGUOUS on the card's FAT
# filesystem, and macOS makes that surprisingly hard (verified by reading
# the FAT directly - see tools/fatmap.py):
#   - macOS's FAT driver allocates first-fit from the front of the card, so
#     once deleted files have left holes, a fresh copy is shredded into them.
#   - Spotlight/.fseventsd/AppleDouble "._*" writes interleave with a copy
#     and split it even on an otherwise-clean card.
# Strategy:
#   - update:  if the image already exists on the card at the same size,
#              overwrite IN PLACE (dd conv=notrunc). Cluster layout is
#              reused, so a file the Emu already loads keeps loading.
#   - install: copy with xattrs stripped (no "._*" twin) + dot_clean.
#   - repair:  copy every file off, wipe (except SIP-protected dirs), copy
#              back in one pass. Frees holes and repacks contiguously.
#              Run once if the Emu reports "file not contiguous".
#
# Usage:
#   tools/install-sd.sh [image.dsk] [/Volumes/CARD]
#   tools/install-sd.sh --repair [/Volumes/CARD]
set -u

die() { echo "error: $*" >&2; exit 1; }

find_card() {
    local cards=()
    while IFS= read -r line; do
        cards+=("$line")
    done < <(mount | awk '/msdos|exfat/ {sub(/^.* on /,""); sub(/ \(.*/,""); print}')
    [ ${#cards[@]} -gt 0 ] || die "no FAT-formatted volume mounted - insert the SD card"
    [ ${#cards[@]} -eq 1 ] || die "several FAT volumes mounted (${cards[*]}) - pass the card path explicitly"
    echo "${cards[0]}"
}

quiet_card() {  # stop macOS services from allocating clusters mid-copy
    mdutil -i off "$1" >/dev/null 2>&1 || true       # may need sudo; best-effort
    touch "$1/.fseventsd/no_log" 2>/dev/null || true
}

repair=false
if [ "${1:-}" = "--repair" ]; then
    repair=true
    shift
fi

if $repair; then
    card="${1:-$(find_card)}" || exit 1
    [ -d "$card" ] || die "no such volume: $card"
    echo "This repacks EVERY file on $card (copy off, wipe, copy back)."
    read -r -p "Continue? [y/N] " a
    [ "$a" = "y" ] || [ "$a" = "Y" ] || exit 1
    tmp=$(mktemp -d) || die "mktemp failed"
    echo "copying card contents to $tmp ..."
    rsync -a --exclude='._*' --exclude='.Spotlight-V100' --exclude='.fseventsd' \
          --exclude='.Trashes' --exclude='.DS_Store' "$card/" "$tmp/" \
        || die "backup to $tmp failed - card untouched"
    quiet_card "$card"
    echo "wiping card (keeping SIP-protected system dirs) ..."
    find "$card" -mindepth 1 -maxdepth 1 \
         ! -name '.Spotlight-V100' ! -name '.fseventsd' ! -name '.Trashes' \
         -exec rm -rf {} +   # tolerate stragglers; backup is safe in $tmp
    echo "copying back in one pass ..."
    if ! rsync -a "$tmp/" "$card/"; then
        die "restore failed - your files are safe in $tmp"
    fi
    dot_clean -m "$card" 2>/dev/null || true
    sync
    echo "done - files repacked contiguously (backup kept at $tmp until you delete it)"
    exit 0
fi

script_dir=$(cd "$(dirname "$0")" && pwd)
image="${1:-$script_dir/../apple2gs/CLAUDEG.dsk}"
[ -f "$image" ] || die "image not found: $image (run apple2gs/build.sh first?)"
card="${2:-$(find_card)}" || exit 1
[ -d "$card" ] || die "no such volume: $card"

dest="$card/$(basename "$image")"
if [ -f "$dest" ] && [ "$(stat -f%z "$image")" -eq "$(stat -f%z "$dest")" ]; then
    dd if="$image" of="$dest" conv=notrunc status=none || die "dd failed"
    rm -f "$card/._$(basename "$image")"
    sync
    echo "updated in place: $dest (cluster layout reused)"
    echo "note: this preserves the file's existing layout - if the Emu already"
    echo "loads it, the update is safe; if it was refused, run --repair first"
else
    quiet_card "$card"
    cp -X "$image" "$dest" || die "copy failed"
    dot_clean -m "$card" 2>/dev/null || true
    rm -f "$card/._$(basename "$image")"
    sync
    echo "installed: $dest"
    echo "if FloppyEmu says 'file not contiguous', run: $0 --repair"
fi
