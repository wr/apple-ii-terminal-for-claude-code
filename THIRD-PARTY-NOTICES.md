# Third-Party Notices

This project's own code is MIT-licensed (see [LICENSE](LICENSE), Copyright (c)
2026 Wells Riley). The MIT grant covers Wells's original work only. The build
and the release disk also pull in third-party material that Wells does not own
and cannot relicense. This file inventories every such component, where it comes
from, who holds the copyright, its license status, and how it's used.

Where a component's redistribution status is unsettled, this file says so
plainly. Nothing here should be read as a grant of rights the upstream holder
hasn't given.

## What ends up where

- "In repo" — the file is checked into this git repository.
- "In release" — the file (or something derived from it) ships inside
  `CLAUDE.dsk` on the GitHub Releases page.

## Components

### Apple DOS 3.3 System Master (January 1983)

- File: `apple2gs/dos33-master-jan83.dsk` (143,360 bytes)
- SHA-256: `70986935d95c4a918852700364ac107607eb861a7d93a69c2b5caf44a696b17a`
- Copyright: (c) Apple Computer, Inc.
- License / status: Apple's copyrighted operating system. Apple has never
  placed DOS 3.3 in the public domain or issued a redistribution license. It
  is distributed widely across the retrocomputing community by convention,
  not by permission — the same January 1983 System Master is bundled by the
  AppleWin emulator and hosted openly by the Internet Archive and the Asimov
  archive. It is vendored here in good faith for interoperability and
  preservation, with no claim of ownership and no affiliation with Apple, and
  will be removed on a rights holder's request.
- In repo: yes, vendored at `apple2gs/dos33-master-jan83.dsk` (the
  `apple2gs/*.dsk` gitignore has an explicit `!` exception for it, so build
  outputs stay ignored while the base image is tracked).
- In release: yes. `apple2gs/build.sh` copies this master, replaces
  its `HELLO` program, and injects the two client binaries (`COBJ`, `COBJ8`) to
  produce `CLAUDE.dsk`. The DOS 3.3 boot code and file system in `CLAUDE.dsk`
  are Apple's. The GitHub release ships `CLAUDE.dsk`.
- How to obtain / verify: see the "Base disk image" section of the README. The
  SHA-256 above pins the exact image `build.sh` expects.

### "Clawd" mascot artwork (Anthropic)

- File: `apple2gs/clawd.gif` (38,060 bytes)
- SHA-256: `64e5be759758c0a9465bb023cd58d22aedef3631cc6208ff7923ec59bfde0533`
- Copyright: (c) Anthropic PBC. "Claude" and the crab mascot are Anthropic's.
- License / status: Anthropic intellectual property. No redistribution or
  derivative-work permission has been established for this project. Included as
  a fan work; the README states the project is not affiliated with or endorsed
  by Anthropic.
- In repo: yes.
- In release: yes, as derived art. `apple2gs/gen_assets.py` decodes this GIF at
  build time into the Super Hi-Res splash-animation frames baked into the IIgs
  client, which ships inside `CLAUDE.dsk`.
- Note: the session-screen mascot is a separate, original drawing and is not
  derived from this file.

### unscii-8 bitmap font

- File: `apple2gs/unscii-8.hex`
- SHA-256: `03094f7fbab7085cf6a6b624cee61e47e71ce5d0c2f308c2f4436afdc17f776c`
- Author: Viljami Salminen (Viznut) — http://viznut.fi/unscii/
- License / status: CC0 / public domain. Redistribution and modification are
  unrestricted.
- In repo: yes.
- In release: yes, as derived data. `gen_assets.py` rasterizes selected glyphs
  into the client font table baked into both clients.

### dos33fsprogs (build tool only)

- Source: https://github.com/deater/dos33fsprogs by Vince Weaver.
- License / status: GPL. Used only as a host build tool (`dos33`,
  `tokenize_asoft`), which the builder installs separately; `build.sh` points
  `DOS33FSPROGS` at that checkout.
- In repo: no.
- In release: no. These programs write our files into the disk image; none of
  their own code is copied into `CLAUDE.dsk`. The GPL therefore does not reach
  the released disk.

### Tools referenced but not bundled

Neither of these is redistributed by this project; they're the user's own
install.

- cc65 (`ca65` / `ld65`) — the 65816/6502 assembler and linker. zlib license.
- KEGS — the IIgs emulator used to run and preview the client. Its own license.

## Maintenance

When a bundled or build-time input changes, update its SHA-256 here. The DOS 3.3
master's checksum also appears in the README (the "Building from source"
section) so users can verify the exact base image.
