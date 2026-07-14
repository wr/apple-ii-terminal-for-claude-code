# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each release ships `CLAUDE.dsk`, a bootable 140K DOS 3.3 disk image. Release
artifacts carry a SHA-256 so you can verify the download.

## [Unreleased]

## [1.1.0] - 2026-07-13

Device pairing that survives reboots, plus real turn cancellation and CI.

### Added
- **Disk-stored device token pairing.** After you type the pairing code once,
  the bridge hands the client a private device token, which it saves to a
  reserved sector on its boot disk and presents automatically on every future
  connect — so a paired Apple II never needs the code again, even across
  reboots. The host stores only a SHA-256 of the token, never the token itself.
- **Per-device pairing codes.** By default each connecting IP gets its own
  code, printed to the bridge console the moment that device connects, so a
  code seen for one device can't enroll another. `--pair-code` still pins one
  shared code for everyone.
- **Real Ctrl-C cancellation** of an in-flight turn, and a `--idle-timeout` so
  an unpaired or idle peer can't hold the single listener slot open.
- A tested-model **compatibility matrix** (`docs/COMPATIBILITY.md`) and a
  `SECURITY.md` covering the trusted-LAN model and exactly what's stored.
- **CI** with a disk-catalog release gate: every release disk must carry both
  `COBJ` (IIgs) and `COBJ8` (8-bit).

### Changed
- Pairing trust is now a **client-held device token, not a peer IP**, closing
  the DHCP-lease-reuse and persisted-loopback holes of the old IP model.
- `build.sh` no longer copies the built disk to `~/Downloads` by default; set
  `COPY_TO_DOWNLOADS=1` to opt in (convenience for the KEGS boot path).

### Fixed
- 8-bit clients (IIe, IIc, IIc Plus, II/II+) captured the device token at the
  wrong buffer offset, so token pairing never persisted there — the code had to
  be re-typed on every boot. Fixed; token pairing now works on every model.

SHA-256: `fa2654f87a54e577553210b2531a07a9b83b818ed8e6b58b92ebd5a1d2596c9d`

## [1.0.1] - 2026-07-13

Maintenance release. One disk still boots every Apple II (IIgs + 8-bit); both
`COBJ` and `COBJ8` are on it.

### Fixed
- The DOS 3.3 base disk is now vendored, so a clean `git clone` builds with
  nothing to fetch (the v1.0.0 source archive couldn't).
- Onboarding docs: where to get `CLAUDE.dsk`, and KEGS's ROM requirement.

### Changed
- README rewritten with a real demo of the client running on a IIgs CRT.
- Honest third-party provenance in `THIRD-PARTY-NOTICES.md`.
- Bridge dependency floor raised to `anthropic>=0.77.0` so the chat backend
  can't install against a version missing the effort argument.

SHA-256: `edb82784210888f1ffc5637a31acce36e077db2d12598bf0ca9c0053514f489c`

## [1.0.0] - 2026-07-13

The public 1.0. One 140K disk boots every Apple II in the family.

### Fixed
- v0.2.0 shipped a disk with only the IIgs binary (`COBJ`), so 8-bit machines
  (IIe, IIc, IIc Plus, II/II+) couldn't boot it. `CLAUDE.dsk` now carries both
  `COBJ` (IIgs) and `COBJ8` (everything else); HELLO reads the ROM ID and BRUNs
  the right one.
- 8-bit client checks carrier before sending, so a dropped line no longer
  reaches the modem's command parser.
- Reply rendering stopped eating literal `*` and `_`; text like `*.py`, `2 * 3`,
  and `__init__` now survives intact.

### Changed
- Bridge pairing hardened: a 6-character code, guess backoff and a hard cap,
  code expiry and peer revocation, bounded input.

### Added
- Provenance docs: `THIRD-PARTY-NOTICES.md` and a LICENSE carve-out cover the
  bundled DOS 3.3 master and the Clawd art; the README explains how to obtain
  and verify the base disk.

SHA-256: `55725ddb927daff7ccba8e5a9faeb908922382da5b4e7ce81d32545970399ceb`

## [0.2.0] - 2026-07-10

The launch build.

### Added
- Menu chiptune on the Ensoniq DOC (plays once per menu visit).
- Bridge pairing-code gate in listening mode.
- Claude Code slash commands (`/cost`, `/context`, `/compact`, skills) pass
  through in code mode.

### Changed
- `/quit` returns to the menu even with no connection; Esc aborts a stuck wait.
- Autodial flushes modem junk first and reacts to CONNECT/ERROR/BUSY.
- Instructions page shows the real repo URL.

### Fixed
- Splash polish: inter-loop rest pose and art fixes.

## [0.1.0] - 2026-07-10

First release: Claude Code on a real Apple IIgs.

### Added
- `CLAUDE.dsk`, a bootable 140K DOS 3.3 disk image with the native Super Hi-Res
  client: boot menu, animated Clawd splash with music, and a Claude Code-style
  session UI. Boots KEGS (slot 6), a FloppyEmu in 5.25" mode, and real drives.
- `tools/install-sd.sh` to write the image to a FloppyEmu SD card (with a
  `--repair` path for the "file not contiguous" case).

[Unreleased]: https://github.com/wr/apple-ii-terminal-for-claude-code/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/wr/apple-ii-terminal-for-claude-code/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/wr/apple-ii-terminal-for-claude-code/compare/v0.2.0...v1.0.0
[0.2.0]: https://github.com/wr/apple-ii-terminal-for-claude-code/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/wr/apple-ii-terminal-for-claude-code/releases/tag/v0.1.0
