# HANDOFF — Claude Code ][ (2026-07-09)

State of the project after the bring-up marathon. Written for whoever picks
this up next (human or Claude). CLAUDE.md has the standing gotchas; this doc
is the snapshot: what exists, what's where, what's pending, and the exact
procedures that work.

## What this is

Claude Code on a real Apple IIgs. A Python bridge on the Mac runs the
`claude` CLI and talks to the IIgs over a Hayes WiFi modem; a 65816 client in
Super Hi-Res 640 mode draws a boot menu, an animated Clawd splash, and a
Claude Code-style session UI (transcript, scrollback, spinner, pinned input).

## Current status — read this first

- **Everything works end to end.** Serial, dial, session, splash, menu — all
  proven. The boot experience is Wells-approved as of tonight.
- **The real IIgs is running an OLD build.** All menu/splash/gif-port work
  from this evening was tested in KEGS only. The last binary installed on
  hardware predates the menu. **First task next session: install the current
  build on the metal** (procedure below) and sanity-check it — the splash
  draw loop and menu key handling have never run on a real SCC/CPU.
- The repo is **not a git repo yet**. Wells wants to open-source it (badly).
  No history exists — be careful with destructive edits.

## Hardware

- Apple IIgs with an **AppleSqueezer** accelerator (fast; timing loops in the
  client are VBL-based so speed doesn't matter).
- **WiModem 232 Pro** on the modem port (mini-DIN-8). 9600 8N1. Configured:
  phone book entry 0 = `10.0.1.188:6400` (the Mac), autodial-on-power-up
  (`AT*A1`), saved with `AT&W`.
- **FloppyEmu** as the disk drive, booting a **ProDOS** volume `/UTILITIES`.
  The SD card is never written from the Mac (FloppyEmu "file not contiguous"
  trap — two lost hours, do not retry). Everything ships over serial.
- On the ProDOS disk: `COBJ` (the client binary), `LOADER` (serial installer,
  BASIC), `TERM` (mini terminal, BASIC), `STARTUP` (auto-BRUNs COBJ with an
  any-key-for-BASIC escape window), LAUNCHER/SYSUTIL/FASTCOPY renamed `.SYS`
  so BASIC.SYSTEM boots first.
- Wells' monitor runs in B&W mode (photographs blue; color mode is
  misconverged). Don't chase palette bugs from photos.

## Daily flow

```
Mac:   cd ~/Projects/appleii-claude/bridge
       python3 bridge.py --telnet --app --backend code --cols 80
IIgs:  power on (modem autodials the bridge), boot FloppyEmu
       -> menu -> 1. Connect
```
No `--pace-cps` needed for this client (it has a ring buffer); the flag still
matters for the plain BASIC clients in `apple2/`.

## Installing / updating the client

```
Mac:   cd apple2gs && ./build.sh          # deploys ~/Downloads/CLAUDEG.dsk for KEGS too
       cd ../bridge
       python3 bridge.py --telnet --app --backend code --cols 80 --bootstrap ../apple2gs/COBJ
IIgs:  reboot; press any key during the STARTUP window to land in BASIC
       RUN LOADER
```
LOADER dials if needed, receives the binary, verifies a checksum sent over
the wire, and BSAVEs — **no build-specific numbers on the IIgs side, ever**.
A bad transfer is retried by just RUNning again. The bridge re-reads COBJ per
transfer, so you can rebuild between attempts without restarting it.
Listing + protocol: `apple2gs/BOOTSTRAP.bas.txt`.

KEGS iteration loop: `./build.sh`, then Ctrl-⌘-Reset in KEGS (boots
`~/Downloads/CLAUDEG.dsk` via `~/config.kegs`). Bridge for KEGS:
`python3 bridge.py --connect 127.0.0.1:6502 --app --backend code --cols 80`.
Serial-timing bugs do NOT reproduce in KEGS (see CLAUDE.md). Also: KEGS
launched in the background gets App-Napped by macOS and freezes — run it
in the foreground.

## Architecture map

```
bridge/
  bridge.py      CLI, session loops, bootstrap serving, slash commands
  backends.py    ChatBackend (Messages API) / CodeBackend (claude CLI per turn,
                 --resume for continuity, header/footer synthesis)
  render.py      Markdown -> 7-bit ASCII, word wrap (cols-2 for the app client;
                 replies render as a bullet + 2-space-indented block)
  terminal.py    line I/O, echo, pacing, telnet IAC
  transports.py  serial / TCP-listen (WiFi modem) / TCP-connect (KEGS)
apple2gs/
  claude.s       the whole client (65816, one file)
  gen_assets.py  generates assets.inc at build time: palette(s), font
                 (unscii-8.hex), session mascot, AND the splash animation --
                 machine-ported from clawd.gif (requires Pillow + clawd.gif)
  build.sh       gen_assets -> ca65/ld65 -> DOS 3.3 disk (KEGS) ; COBJ = binary
  BOOTSTRAP.bas.txt  the LOADER listing + wire protocol (canonical copy)
apple2/          older 40/80-col BASIC clients + TERM listing (IIgs-poke based)
```

Client boot flow: hardware init → `scc_init` (border breadcrumbs: white→
red→black; a stuck color names a hung stage) → splash palette → menu with the
Clawd act looping behind it (`splash_seq` walked by the menu key loop) →
Connect: dial + spinner → session palette → session UI. Menu also has a live
Hayes AT console (works with any Hayes modem) and an instructions page (a
GitHub URL placeholder sits in `str_ins_b1`).

Wire protocol (app mode): CR-terminated lines up; replies down as ASCII +
control bytes `0x01 <n>` color, `0x02` bullet, `0x0E` header frame, `0x04`
EOT. Bootstrap: client sends CR probe (bridge ACKs 0x06) then `R`; bridge
sends sum_lo/mid/hi + len_lo/hi + data at ~500 B/s.

## The splash pipeline (the unusual part)

`gen_assets.py` decodes `clawd.gif` at build time, quantizes every frame at
**half the gif's 5.75px pitch** (= the true art grid; the spritesheet in
`~/Downloads/clawd-laptop-codex-pet/` proved the gif is a half-res render),
substitutes the spritesheet's three typing poses via **best-match, body-
anchored** comparison, erases all gray cells (kills AA artifacts) and stamps
a rigid keyboard sprite (parked on the table when typing, tilted in flight),
composites the hand-drawn IIgs CRT prop (screen strip flashes between the
two corals only on typing frames), and emits frames + a (frame, vblanks)
storyboard preserving the gif's own timing. The client draws each stored
pixel as 2 bytes × 3 scanlines via the `expand4_*` tables.

Hard-won rules encoded in that pipeline (violations reintroduce fixed bugs):
best-match not first-match; anchor on coral body cells only; never
substitute the stand pose (kills the intro/outro acting); gif colors are
darker than sheet colors (classify split lum ≥118); Clawd sits 1 down-left
of the raw crop (art direction).

## Session UI notes

- Session mascot = the ORIGINAL hand-drawn critter, deliberately static.
  Wells explicitly does not want it animated. Header scrolls away after the
  first long reply; that's known and accepted.
- Spinner pulses `* + : +`; footer synthesized from the CLI result event.
- Exiting: Ctrl-Reset (menu item 4 does a clean text-mode reset too).

## Zero-page map (client) — collisions here have burned us twice

`$06-$07` tmp2, `$08-$09` srcp, `$FD-$FE` srcrow, `$FA-$FC` bufptr,
`$D0-$DF` misc (skips $D6 and $D8 deliberately), `$E0-$EE` draw state.
Forbidden: `$B0-$C8` (Applesoft CHRGET code), `$D6` (auto-RUN flag),
`$D8` (ONERR). The client is Ctrl-Reset'd back into live BASIC constantly.

## Backlog (Linear: project "Claude Code ][", team Personal)

- W-469 code tidy (high) — known dead code listed in the issue
- W-470 docs review (high) — README rewrite = open-source landing page
- W-471 bridge: app + bootstrap without restarts
- W-472 client `/update` (depends W-471; design questions in issue)
- W-473 Claude Code slash-command support (research `claude -p` first)
- W-474 append-system-prompt "user is on an Apple II" FYI (quick win)

Un-ticketed ideas Wells has floated: IIc support via a text-mode client
port; `CLAUDE.SYSTEM` direct boot (skip BASIC.SYSTEM); publishing the repo.

## Fastest ways to break this

- Insert code after a `jsr` without checking the routine's exit M/X width
  (assembler width lies → BRK; see CLAUDE.md).
- Poll the SCC in a new loop without `rb_poll`'s bounded-drain + Error Reset.
- Trust KEGS on anything involving serial timing, SCC errors, or palettes.
- Copy a disk image to the FloppyEmu SD card from the Mac.
- "Improve" the splash extraction without re-reading the pipeline rules above.
