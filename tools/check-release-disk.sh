#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DISK="${1:-$ROOT/apple2gs/CLAUDE.dsk}"
DOS33="${DOS33:-${DOS33FSPROGS:-/tmp/dos33fsprogs}/utils/dos33fs-utils/dos33}"

if [ ! -x "$DOS33" ]; then
  echo "release gate: dos33 executable not found: $DOS33" >&2
  exit 1
fi

if [ ! -f "$DISK" ]; then
  echo "release gate: disk image not found: $DISK" >&2
  exit 1
fi

catalog="$("$DOS33" "$DISK" CATALOG)"
printf '%s\n' "$catalog"

for name in COBJ COBJ8; do
  if ! printf '%s\n' "$catalog" | awk -v name="$name" \
    '$1 == "B" && $3 == name { found=1 } END { exit !found }'; then
    echo "release gate: $DISK is missing binary catalog entry $name" >&2
    exit 1
  fi
done

echo "release gate: disk contains COBJ and COBJ8"
