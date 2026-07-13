# Compatibility

What the disk is claimed to run on, versus what has actually been exercised. The
clients are written to cover every model from the IIgs down to the II+, but real
coverage is narrower than that reach. This table is honest about the gap.

Two clients ship on the one disk. The HELLO reads the ROM ID bytes at boot and
BRUNs the right one:

- **GS SHR** — the 65816 Super Hi-Res client (`apple2gs/claude.s`). IIgs only.
- **8-bit text** — the plain-6502 text client (`apple2/claude2.s`). Everything else.

| Machine | Client | Emulator-tested | Metal-tested | Notes |
|---|---|---|---|---|
| **IIgs** | GS SHR | Yes — KEGS | Yes — author's IIgs | Real hardware needs `scc_init` (a IIgs never inits the SCC at power-on); KEGS runs without it. |
| **IIe, 80-col (aux card)** | 8-bit text | Yes — MAME `apple2ee` (enhanced IIe) | Not yet | Needs a Super Serial Card in slot 2. This is the enhanced-IIe path the harness actually drives. |
| **IIe, 40-col (no aux card)** | 8-bit text | Not yet | Not yet | Aux-less IIe is detected by `aux_test` and falls back to 40 columns. The fallback code exists but the harness runs `apple2ee` with an aux card, so the 40-col path is unexercised. Needs an SSC. |
| **IIc** | 8-bit text | Yes — MAME `apple2c` | Yes — author's IIc | Built-in serial port (slot-2 addresses); no SSC needed. |
| **IIc Plus** | 8-bit text | Not yet | Not yet | 4 MHz part; the client scales its cycle-counted delays ×4 via `$FBBF`. That path has not been run on an emulator or on metal. |
| **II / II+** | 8-bit text | Not yet | Not yet | Plain 6502, 40-col text. Needs a Super Serial Card in slot 2. Should work; untested on emulator or hardware. |

## Tested vs. untested, at a glance

- **Tested on real hardware:** IIgs, IIc (author's machines).
- **Tested in emulation only:** IIe 80-col (MAME `apple2ee`).
- **Untested anywhere — "should work":** IIe 40-col (aux-less fallback), IIc Plus, II/II+.

## On the emulator coverage

The 8-bit MAME harness needs a romset that **is not distributable**. It was
assembled per the W-482 recipe — Asimov parts plus a keyboard ROM synthesized
from MAME's own key-matrix source — so the emulator results above can't be
reproduced from a clean checkout without rebuilding that romset yourself. The
GS path uses KEGS, which needs an Apple IIgs ROM you supply.

Emulators forgive timing and buffering that real chips don't (the whole
"Non-obvious constraints & gotchas" section of AGENTS.md is bugs that passed in
emulation and failed on metal). Read an "emulator-tested" cell as "the logic
runs," not "proven on the corresponding hardware."
