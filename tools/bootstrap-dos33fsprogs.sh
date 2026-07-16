#!/bin/bash
set -eu

DOS33_COMMIT=78fc3bd4b24a6b792f49f311e85412e0cccc272c
DEST="${DEST:-$HOME/dos33fsprogs}"

if [ ! -d "$DEST/.git" ]; then
  git clone https://github.com/deater/dos33fsprogs.git "$DEST"
fi
git -C "$DEST" fetch origin "$DOS33_COMMIT"
git -C "$DEST" checkout --detach "$DOS33_COMMIT"
make -C "$DEST/utils/dos33fs-utils"
make -C "$DEST/utils/asoft_basic-utils"
git -C "$DEST" rev-parse HEAD
