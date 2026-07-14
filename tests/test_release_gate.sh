#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOS33="${DOS33:-${DOS33FSPROGS:-/tmp/dos33fsprogs}/utils/dos33fs-utils/dos33}"
CHECK="$ROOT/tools/check-release-disk.sh"
DISK="${1:-$ROOT/apple2gs/CLAUDE.dsk}"

"$CHECK" "$DISK" >/dev/null

tmp="$(mktemp "${TMPDIR:-/tmp}/claude-gate.XXXXXX.dsk")"
trap 'rm -f "$tmp"' EXIT
cp "$DISK" "$tmp"
"$DOS33" -y "$tmp" DELETE COBJ8 >/dev/null

if "$CHECK" "$tmp" >/dev/null 2>&1; then
  echo "release gate test: accepted disk after COBJ8 deletion" >&2
  exit 1
fi

echo "release gate test: valid disk accepted; missing COBJ8 rejected"
