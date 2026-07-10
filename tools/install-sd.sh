#!/bin/bash
# Put the built disk image on a FloppyEmu SD card.
#
# Thin wrapper: the real tool is femu-sd (vendored in this directory,
# maintained at https://github.com/wr/floppyemu-sd), which handles the
# FloppyEmu "file not contiguous" problem properly. This wrapper just
# defaults the image to this project's build output.
#
#   tools/install-sd.sh                     push the built CLAUDE.dsk
#   tools/install-sd.sh other.po            push something else
#   tools/install-sd.sh check|repair|list   card maintenance
set -u
here=$(cd "$(dirname "$0")" && pwd)
case "${1:-}" in
    check|repair|list|eject) exec "$here/femu-sd" "$@" ;;
    "") exec "$here/femu-sd" push "$here/../apple2gs/CLAUDE.dsk" ;;
    *)  exec "$here/femu-sd" push "$@" ;;
esac
