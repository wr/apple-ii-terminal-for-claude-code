# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Source of truth
- GitHub: none (not yet a git repo; open-sourcing planned)
- Linear project: Claude Code ][ (id: c0d9d65f-0a87-4f10-81ab-bd1ad619fd16, team Personal)
- Branch prefix: wells/
- PR mode: none

## What this is

A bridge that turns a real Apple IIe/IIc/IIgs into a terminal for Claude. Two halves that must stay in sync:

- **`bridge/`** — Python, runs on a modern host. Reads a line from the Apple II, sends it to Claude, streams the reply back flattened to 7-bit ASCII and word-wrapped to 40/80 cols.
- **`apple2gs/claude.s`** — the primary client: a 65816 assembly program running in IIgs **Super Hi-Res 640 mode** (4 colors) that draws the whole Claude Code–style UI (scrolling transcript, mascot, pinned input box). `apple2/*.bas` are simpler text-mode BASIC clients; a stock serial terminal also works as a fallback.

The bridge sends **only** printable ASCII + CR/LF plus a small in-band control scheme (below). All layout and color live on the Apple II side.

## Commands

Build/preview/run the IIgs client (from `apple2gs/`):

```bash
./build.sh                 # gen_assets.py -> ca65/ld65 -> DOS 3.3 disk -> ~/Downloads/CLAUDEG.dsk
python3 gen_assets.py      # regenerate assets.inc (font + mascot + bullet) only
python3 preview.py assets.inc out.png   # render the SHR screen to PNG WITHOUT an emulator
```

`build.sh` needs the `cc65` toolchain (`ca65`/`ld65`) and the dos33fsprogs utilities at `/tmp/dos33fsprogs/…`.

Run the bridge against KEGS (KEGS F4 → Serial Slot 2 → **Incoming**, which listens on TCP 6502):

```bash
cd bridge
python3 bridge.py --connect 127.0.0.1:6502 --app --backend code --cols 80
```

- `--app` enables the native-client protocol (bridge stays silent, frames replies with `EOT` = `0x04`). Required for `claude.s`.
- `--backend code` runs the real `claude` CLI on the host; `--backend chat` (default) is Messages-API Q&A.
- Serial hardware instead of KEGS: `--serial /dev/tty.usbserial-XXXX --baud 9600`.

## The edit → see-it loop

- **`preview.py` is the fast path.** It reproduces `claude.s`'s exact SHR pixel math and renders at KEGS's real display geometry (640×200 stretched to 4:3 → pixels are ~0.42 wide : 1 tall, i.e. narrow/tall). What the PNG shows is what KEGS shows. Use it before booting the emulator. It writes both a full screen and a zoomed `*_mascot.png`.
- **Client change** (`claude.s`/`gen_assets.py`): `./build.sh`, then **Ctrl-⌘-Reset** in KEGS to reboot from the updated disk. No bridge restart.
- **Bridge change** (`bridge/*.py`): restart the `python3 bridge.py` process.
- **Real hardware** (Wells' IIgs: WiModem 232 Pro on the modem port, FloppyEmu as disk): updates go over serial, never via the SD card (FloppyEmu "file not contiguous" trap). Run the bridge with `--bootstrap ../apple2gs/COBJ`, then on the IIgs `RUN LOADER` (typed-in program, listing in `apple2gs/BOOTSTRAP.bas.txt`). The loader auto-dials, receives, verifies a transmitted checksum, and BSAVEs — no build-specific constants on the IIgs side; the bridge re-reads COBJ on every transfer.

## Rendering pipeline (bridge → client)

`backends.py` (`ChatBackend` / `CodeBackend`) yields clean text → `render.py` `StreamFormatter` reduces Markdown, `to_ascii` sanitizes to 7-bit, `wrap` word-wraps → `bridge.py` `run_app_session` writes lines and terminates with `EOT`. `terminal.py`/`transports.py` are byte plumbing.

`CodeBackend` runs `claude -p <prompt> --output-format stream-json --verbose`, one fresh process per turn, no PTY; continuity is faked with `--resume <session_id>`. **Consequence:** Claude Code's interactive TUI (real slash commands, the `●` bullet, the `✻ Worked for Xs` footer, lavender colors) does **not** exist in this transport — those must be *synthesized*, not recovered. The footer is built from the `result` event's `duration_ms`; the bullet and code-coloring are injected by the bridge.

## In-band control scheme

The reply stream carries a few control bytes the native client interprets (kept below `EOT`=`0x04`):

- `0x01 <n>` — set text color: `1`=gray (reply/input), `2`=coral (mascot/titles/footer), `3`=white (your messages, inline code).
- `0x02` — draw the white reply bullet.

These are injected in `bridge.py:run_app_session` (bullet, footer) and inside `render.py` (inline/fenced `code` spans → white). `to_ascii` deliberately **passes through bytes 1–3** rather than dropping them; the client's `recv_reply`/`spinner` intercept them before `cout`. Color markers currently count toward wrap width, so code-dense lines may wrap a few columns early.

## Non-obvious constraints & gotchas

- **640-mode palette is full at 4 colors** (black/gray/coral/white). A 5th color (e.g. a true lavender) is impossible without switching to 320 mode, which also halves to 40 columns. Text mode can't do multiple simultaneous colors at all — that's why this is a graphics client.
- **Font must be a real bitmap** (`unscii-8.hex`, CC0, loaded verbatim in `gen_assets.py`). Rasterizing a TTF down to 8×8 produces unreadable mush — don't.
- **Real hardware needs `scc_init`.** A real IIgs only hardware-resets the SCC at power-on — the modem port moves no bytes until a program sets clocks and enables Rx/Tx (Apple IIgs TN #018). `claude.s` does this itself at startup (9600 8N1; change `SCC_BAUD_TC` to 4 for 19200). KEGS works with or without it, so "works in KEGS" proves nothing about serial on real metal.
- **The SCC Rx FIFO is 3 bytes — never go deaf to the port.** The client keeps a 256-byte ring buffer (`rb_poll`/`getbyte`/`havebyte` in claude.s): slow loops (`scroll_up`, `clear_rowA`, `vbl_edge`) drain the port mid-work, and every reader pulls buffered bytes first. Any new long-running loop MUST call `rb_poll` at least every couple of ms or real hardware drops bytes (symptom: mangled text; KEGS won't show it). `--pace-cps` is not needed for this client — only for the plain BASIC/terminal clients, which have no buffer.
- **A real 8530 latches Rx overrun and can wedge the status poll** — an unbounded drain-until-empty loop then spins forever (overrun is *guaranteed* at boot: the modem's dial echo arrives while the client draws the mascot). `rb_poll` therefore bounds its drain (4 bytes max) and ends every pass with WR0 = $30 (Error Reset). Route ALL SCC reads through `rb_poll`/`getbyte`; never write a new raw `lda SCC_STAT` poll loop. KEGS models none of this — this class of bug only manifests on real metal. (Boot breadcrumbs remain in `start`: border flashes white→red→yellow→black through init stages; a stuck colored border names the hung stage.) The client auto-dials at startup — `modem_dial` sends `ATDS=0` **unconditionally** (a connected-probe can't work: in command mode the modem echoes the probe, indistinguishable from an answer); when already online the bridge recognizes `ATD…` lines and swallows them.
- **65816 assembler mode tracking:** after `jsr`ing a routine that changes the M/X flag width (e.g. `put_common` returns in `.a8`), you MUST put a `.a8`/`.a16` directive after the call so operand widths assemble correctly. Getting this wrong silently emits an extra byte that executes as `BRK` (crash). `mvn` block-move also corrupts KEGS state — `scroll_up` uses a plain `[dp],y` copy instead.
- **KEGS reads `~/config.kegs`** (home dir), not the one in the KEGS app folder — the app runs translocated under macOS quarantine so its CWD isn't the folder. The IIgs boots the DOS 3.3 disk from **slot 6** (`s6d1`); a leading `#` on the path means "ejected". `build.sh` writes to `~/Downloads/CLAUDEG.dsk`, which the config points to — don't move that file.
- **Client zero page must dodge live Applesoft/ProDOS state.** The user Ctrl-Resets from the running client back into BASIC (ProDOS BASIC.SYSTEM on the FloppyEmu disk) — any ZP the client scribbles on is corruption BASIC resumes with. Already learned the hard way: $B1-$C8 is CHRGET (executable code — trashing it breaks ALL of BASIC until reboot, symptom "everything is a syntax error"), $D6 is the auto-RUN lock, $D8 is ONERR. Known-safe homes: $06-$09, $FA-$FD. The disk's STARTUP has a press-a-key-for-BASIC window so LOADER updates always run on a fresh interpreter.
- **Slash commands** are intercepted locally in `bridge.py:handle_command` (`/new`, `/mode`, `/help`, `/quit`); everything else is passed to Claude. Real Claude Code TUI slash commands would require a persistent PTY-driven `claude` session (a `CodeBackend` rewrite).
