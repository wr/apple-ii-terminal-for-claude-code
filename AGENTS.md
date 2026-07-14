# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Source of truth
- GitHub: github.com/wr/apple-ii-terminal-for-claude-code
- Branch prefix: wells/
- PR mode: none (commit to main, push directly)

## What this is

A bridge that turns a real Apple II into a terminal for Claude Code. Three pieces that must stay in sync:

- **`bridge/`** — Python, runs on a modern host. Reads a line from the Apple II, sends it to Claude, streams the reply back flattened to 7-bit ASCII and word-wrapped to 40/80 cols.
- **`apple2gs/claude.s`** — the IIgs client: 65816, **Super Hi-Res 640 mode** (4 colors). Boot flow: hardware init → `scc_init` → boot menu (Connect / Hayes AT console / Instructions / Quit to BASIC) with the animated Clawd splash → Connect dials the modem and enters the session UI (scrolling transcript, static mascot, spinner, scrollback).
- **`apple2/claude2.s`** — the 8-bit client: plain 6502 (no 65C02 ops), text mode. Runs on IIe (80-col with an aux card, 40 without), IIc, IIc Plus, and II/II+. Same menu and session shape, inverse-block mascot (with a blink). Serial = 6551 ACIA at the slot-2 addresses (SSC in slot 2 == the IIc/IIc+ built-in modem port).

**Sound design is period-accurate and event-based** — no menu music (period comms tools were silent; a tune reads as toy-like). Three sounds only: a once-per-boot two-voice *wake* gesture on the menu; the Connect *dial theater* (the documented 1986 tone sequence — dial tone 350+440 Hz, DTMF spelling C-L-A-U-D-E, ringback, answer tone 2225 Hz, carrier buzz 1200+2400 Hz); and a *reply bell* rung only when a reply lands after a ≥15 s think (BEL semantics). A CONNECT verdict is latched and the theater plays to its storyboard end (a fast modem answering mid-theater made an old hard cut read as a glitch) — the silence *after* it is the Hayes ATM1 speaker arc; dial failures still cut it dead. GS = DOC two-voice streams in `gen_assets.py`; 8-bit = cycle-counted 1-bit versions (pulse-dial clicks instead of DTMF), which MUST poll `rb_poll` every half-cycle during the dial window.

**One disk boots everything**: `build.sh` assembles both clients into `CLAUDE.dsk`, and the disk's HELLO reads the ROM ID bytes (Apple II Misc TN #7, plus the `$FE1F` carry probe to split IIgs from enhanced IIe) and BRUNs `COBJ` (GS) or `COBJ8` (everything else).

The bridge sends **only** printable ASCII + CR/LF plus a small in-band control scheme (below). All layout and color live on the Apple II side.

## Commands

Build everything (from `apple2gs/`):

```bash
./build.sh                 # both clients -> inject into DOS 3.3 master -> CLAUDE.dsk (+ ~/Downloads copy for KEGS)
python3 gen_assets.py      # regenerate assets.inc (palettes, font, mascot, splash frames, sounds) only
python3 preview.py assets.inc out.png   # render the GS session screen to PNG WITHOUT an emulator
../tools/install-sd.sh     # put the built image on a FloppyEmu SD card safely
```

`build.sh` needs the `cc65` toolchain (`ca65`/`ld65`), a [dos33fsprogs](https://github.com/deater/dos33fsprogs) build (default `/tmp/dos33fsprogs`, override with `DOS33FSPROGS`), and Python with **Pillow** (`gen_assets.py` decodes `clawd.gif` at build time to generate the splash frames). The output disk is the vendored DOS 3.3 System Master (`dos33-master-jan83.dsk`) with HELLO replaced and the client binaries added — never a from-scratch image (from-scratch images have burned us).

Run the bridge against KEGS (KEGS F4 → Serial Slot 2 → **Incoming**, which listens on TCP 6502):

```bash
cd bridge
python3 bridge.py --connect 127.0.0.1:6502 --app --backend code --cols 80
```

- `--app` enables the native-client protocol (bridge stays silent, frames replies with `EOT` = `0x04`). Required for both native clients.
- `--backend code` runs the real `claude` CLI on the host; `--backend chat` (default) is Messages-API Q&A.
- Serial hardware instead of KEGS: `--serial /dev/tty.usbserial-XXXX --baud 9600`.
- A listening bridge (`--telnet`) locks itself behind a 6-character pairing code (attempt backoff, expiry, revocation). Trust is a client-held device token, not a peer IP: a correct code mints a 32-char token (issued once, in `--app` mode, via a `CMD_TOKEN` frame), and only its SHA-256 hash persists in `~/.config/claude-ii-terminal/paired.json` — presenting that token as the session's first line pairs a reconnect without re-asking for the code. The 6-char code is per-device by default (each source IP gets its own, printed to the console when that device connects, via `code_for`); `--pair-code` fixes one shared code instead. `--no-pair` disables.

## The edit → see-it loop

- **GS client, fast path: `preview.py`.** It reproduces `claude.s`'s exact SHR pixel math at KEGS's real display geometry (640×200 stretched to 4:3 → pixels are ~0.42 wide : 1 tall). What the PNG shows is what KEGS shows. It writes a full screen and a zoomed `*_mascot.png`.
- **GS client, full loop**: `./build.sh`, then **Ctrl-⌘-Reset** in KEGS (boots `~/Downloads/CLAUDE.dsk` via `~/config.kegs`). No bridge restart needed.
- **8-bit client**: MAME, fully scripted. `mame apple2ee -sl2 ssc -sl2:ssc:rs232 null_modem -bitbanger socket.127.0.0.1:6502 -flop1 CLAUDE.dsk` wires an emulated Super Serial Card to the bridge's socket; `-autoboot_script` (Lua) types keys and takes snapshots, and Lua read/write taps on memory are how the hard bugs here were actually found. The IIc is `mame apple2c` with `-modem null_modem`. ROMs aren't distributable; the romset was assembled from Asimov parts + a keyboard ROM synthesized from MAME's own matrix source.
- **Bridge change** (`bridge/*.py`): restart the `python3 bridge.py` process.
- **Real hardware** (Wells: IIgs + IIc, WiModem 232 Pro, FloppyEmu): `tools/install-sd.sh` — in-place overwrite of the card's existing image (can't fragment). The tool is [wr/floppyemu-sd](https://github.com/wr/floppyemu-sd), vendored in `tools/`.

## Rendering pipeline (bridge → client)

`backends.py` (`ChatBackend` / `CodeBackend`) yields clean text → `render.py` `StreamFormatter` reduces Markdown, `to_ascii` sanitizes to 7-bit, `wrap` word-wraps → `bridge.py` `run_app_session` writes lines and terminates with `EOT`. `terminal.py`/`transports.py` are byte plumbing.

`CodeBackend` runs `claude -p <prompt> --output-format stream-json --verbose`, one fresh process per turn, no PTY; continuity is faked with `--resume <session_id>`. **Consequence:** Claude Code's interactive TUI (real slash commands, the `●` bullet, the `✻ Worked for Xs` footer, lavender colors) does **not** exist in this transport — those must be *synthesized*, not recovered. The footer is built from the `result` event's `duration_ms`; the bullet and code-coloring are injected by the bridge.

## In-band control scheme

The reply stream carries a few control bytes the native clients interpret (kept below `EOT`=`0x04`):

- `0x01 <n>` — set text color: `1`=gray (reply/input), `2`=coral (mascot/titles/footer), `3`=white (your messages, inline code). The 8-bit client maps 3 → inverse video, others → normal.
- `0x02` — draw the reply bullet.
- `0x03` — session over (bridge-side `/quit`): the client returns to its menu.
- `0x0E` — header frame follows (3 CR-terminated lines); sent in reply to the client's session-open CR probe and before each reply. An **unpaired** peer's probe is answered with a LOCKED header instead — that's how the pairing prompt reaches the screen (idle clients discard unsolicited text but always render headers).
- `0x05 <token> CR` — (bridge → client, app mode) a freshly issued device token; the native client writes it to a reserved disk sector and auto-sends it as its first line on every future connect, so pairing survives reboots. `to_ascii` drops 0x05 from model text, so a reply can't forge it.

These are injected in `bridge.py:run_app_session` (bullet, footer) and inside `render.py` (inline/fenced `code` spans → white). `to_ascii` deliberately **passes through bytes 1–3** rather than dropping them; the clients' `recv_reply`/`spinner` intercept them before `cout`. Color markers currently count toward wrap width, so code-dense lines may wrap a few columns early.

## The splash pipeline (GS)

`gen_assets.py` machine-ports `clawd.gif` into SHR frames at build time. Rules encoded there were each learned the hard way — violating them reintroduces fixed bugs:

- Frames are quantized at **half the gif's 5.75px pitch** (the spritesheet's true art grid).
- Typing poses are substituted from the spritesheet by **best-match, anchored on coral body cells only** — first-match substitution and prop-anchoring both produced wrong frames. Never substitute the stand pose (it kills the intro/outro acting).
- Gif colors are darker than sheet colors — the classifier's lum≥118 split is gif-tuned.
- All gray cells are erased (anti-aliasing artifacts) and a rigid keyboard sprite is stamped instead: parked on the table during typing (`rest_x`, deliberately 1 column nearer Clawd), tilted in flight.
- The inter-loop pause holds a dedicated frame (`SPLASH_HOLD`): the stand pose with the arms 1px taller.
- The session mascot is the original hand-drawn critter, **deliberately static** — Wells does not want it animated. (The 8-bit *menu* mascot blinks; that's intentional.)

## Non-obvious constraints & gotchas

The theme of this list: **KEGS and MAME forgive what real chips don't.** Every entry below was a working-in-emulation, broken-on-metal bug.

Both clients:
- **Never go deaf to the serial port.** The GS's SCC FIFO is 3 bytes; the 8-bit 6551 buffers ONE byte — at 9600 that's ~1ms of slack. Both clients keep a 256-byte ring buffer (`rb_poll`/`getbyte`/`havebyte`) and every loop that can run longer than ~600 cycles calls `rb_poll` inside it (scrolls, row clears, VBL waits, do_header's pad loop). Any new slow loop MUST do the same; the symptom of forgetting is dropped bytes on metal that emulators never show.
- **Local `/quit` (and any client-side command) must be matched BEFORE transmitting** — a line sent with no carrier reaches the modem's command processor.
- **Zero page must dodge live Applesoft/DOS state.** Users Ctrl-Reset from the client back into BASIC; any ZP the client scribbles is corruption BASIC resumes with. $B1-$C8 is CHRGET (executable code — trashing it = "everything is a syntax error"), $D6 auto-RUN, $D8 ONERR. Known-safe: $06-$09, $FA-$FE.

GS client (`claude.s`):
- **640-mode palette is full at 4 colors** (black/gray/coral/white). A 5th needs 320 mode, which halves to 40 columns.
- **Real hardware needs `scc_init`** — a IIgs never initializes the SCC at power-on (Apple TN #018); KEGS works without it.
- **A real 8530 latches Rx overrun and can wedge the status poll** — `rb_poll` bounds its drain (4 bytes) and ends every pass with WR0 = $30 (Error Reset). Never write a raw `lda SCC_STAT` loop. Boot breadcrumbs remain in `start`: border flashes white→red→yellow→black through init; a stuck color names the hung stage.
- **The real Sound GLU raises a busy bit around DOC cycles and drops accesses made while it's set** — all DOC access goes through `glu_wait`+`doc_wr`. KEGS doesn't model it. Also: DOC register `$E1` (osc enable) = oscillator count × 2.
- **65816 mode tracking**: after `jsr`ing a routine that changes M/X width, put `.a8`/`.a16` after the call or operands mis-assemble into a `BRK`. `mvn` also corrupts KEGS state — `scroll_up` uses a plain `[dp],y` copy.
- Connect dials `ATDS=0` without probing (a connected-probe can't work — the modem echoes it); the bridge swallows `ATD…` lines, and the dial window classifies modem verdicts (CONNECT/ERROR/BUSY/NO x) while echoing responses on row 22. Both clients skip the dial entirely when DCD reads carrier AND `dcd_trust` is set (the pin has read "no carrier" at least once, proving it's live, not strapped) — KEGS, MAME, and DCD-less modems never arm the skip and dial every time.

8-bit client (`claude2.s`):
- **Don't use IRQ-driven serial.** The enhanced IIe/IIc ROM interrupt dispatcher doesn't follow the II+'s "A saved at $45" convention; a handler assuming it corrupts the ROM's banking restore (80STORE drops, even columns garble, eventual crash). The client is 100% polled.
- **Inverse text with ALTCHARSET on**: screen codes $40-$5F are **MouseText**, not inverse uppercase — fold to $00-$1F. Without ALTCHARSET, $40-$7F flash.
- **80-col writes**: even columns live in aux RAM via 80STORE+PAGE2 ($C001 + $C055/$C054); odd columns in main. An IIe without an aux card is probed (`aux_test`) and falls back to 40-col.
- **Don't trust $C019**: the IIe's VBLBAR free-runs; the IIc's is interrupt plumbing that may sit still. The client probes it at boot and falls back to cycle-counted delays (scaled ×4 on the 4MHz IIc Plus via `$FBBF`).
- 6551 TX polls TDRE with a timeout because new-production W65C51N chips never set the bit.

Environment:
- **KEGS reads `~/config.kegs`** (home dir, not the app folder — macOS translocation). `s6d1` points at `~/Downloads/CLAUDE.dsk`, which `build.sh` refreshes; a leading `#` on the path means "ejected".
- **Slash commands**: `bridge.py:handle_command` handles `/new`/`/clear`, `/mode`, `/model` (remembered bridge-side and re-passed as `--model` — a passthrough `/model` wouldn't stick across the per-turn process boundary), `/help`, `/quit`/`/exit` (both also matched client-side before transmit). In code mode every other `/command` passes through to `claude -p`, which executes most of them natively (`/cost`, `/context`, `/compact`, skills); TUI-only ones answer "isn't available in this environment". In chat mode unknown commands are rejected (the Messages API has no commands).
- **Ctrl-C**: at an idle prompt = local quit-to-menu. During a think, the client sends a bare `0x03`; `run_app_session` pumps `backend.stream()` through a thread, polls the transport in stream lulls (`Terminal.poll_ctrl_c`), and on Ctrl-C calls `backend.cancel()` (terminates the `claude -p` process), then sends the partial reply + "Interrupted by user" + EOT. During a printing reply the client just mutes (`muteflag`) and drains to EOT locally.
