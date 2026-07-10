# CLAUDE ][

Talk to Claude from a real Apple IIgs or IIc.

The Apple II can't do TLS or JSON, so it can't reach the Claude API on its own.
Instead it acts as a glass terminal: a small Python bridge runs on a modern
machine, reads the line you type on the II, calls Claude, and streams the reply
back word-wrapped for a 40- or 80-column screen.

```
 [Apple IIgs / IIc]  <-- serial or telnet -->  [bridge.py]  <-- HTTPS -->  [Claude]
   dumb terminal                                your Mac / a Pi
```

## Two ways to connect

- **Serial** — a USB-serial cable straight into the II's serial port. Works on
  both machines, no extra hardware. Start here.
- **Telnet** — a WiFi modem (ESP-based) or an Uthernet card on the IIgs. The II
  "dials out" over TCP. Slicker, but needs the modem configured.

## Two things Claude can do

- **chat** (default) — plain Q&A. Nothing runs on the host. Safe and bounded.
- **code** — the real `claude` CLI. It reads files, edits them, and runs
  commands **on the bridge host**. Switch to it live with `/mode code`.

## Setup

```sh
cd bridge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...        # only needed for chat mode
```

Code mode uses the `claude` CLI already on this machine — no API key needed for
that path (it uses whatever `claude` is logged in as).

## Run it

Serial (find your device with `ls /dev/tty.usb*` on a Mac):

```sh
python3 bridge.py --serial /dev/tty.usbserial-1420 --baud 9600 --cols 80
```

Telnet / WiFi modem:

```sh
python3 bridge.py --telnet --port 6400 --cols 80
```

Then bring up a terminal program on the Apple II and connect. See
[apple2/TERMINAL-SETUP.md](apple2/TERMINAL-SETUP.md) for cabling, baud, and
per-machine terminal settings.

Once connected, type `/help`.

## Testing with KEGS (no hardware)

KEGS emulates the IIgs and its serial ports over TCP — great for trying this
before you wire up the real machine.

1. In KEGS, press **F4** → Serial Port Configuration → set **Slot 2** to
   **Incoming**. KEGS now listens on TCP **6502**.
2. Dial into it from the bridge:

   ```sh
   python3 bridge.py --connect 127.0.0.1:6502 --cols 80
   ```

   (If the bridge starts first, it waits and connects once KEGS is listening.)
3. Inside KEGS, boot a terminal program (ProTERM/Spectrum from a disk image) set
   to the modem port (Slot 2), or from Applesoft BASIC just type `IN#2` then
   `PR#2` for a bare terminal. You'll see the `CLAUDE ][` banner.

Alternatively, use KEGS's built-in modem: set Slot 2 to **Virtual modem** (F4),
run the bridge as a server (`python3 bridge.py --telnet --port 8888`), and from
the IIgs terminal type `ATDT 127.0.0.1:8888` to dial out. Incoming mode is
simpler — no AT commands.

## On-screen commands

| Command      | What it does                                   |
|--------------|------------------------------------------------|
| `/help`      | list commands                                  |
| `/new`       | start a fresh conversation                     |
| `/mode chat` | plain Q&A with Claude (safe)                    |
| `/mode code` | real Claude Code — **edits files on the host** |
| `/quit`      | hang up                                         |

## Useful flags

| Flag                     | Why                                                         |
|--------------------------|-------------------------------------------------------------|
| `--cols 40`              | 40-column screen instead of 80                              |
| `--baud 19200`           | faster serial (IIc 6551 tops out ~19200; IIgs goes higher)  |
| `--rtscts`               | hardware flow control (best at high baud, if your cable has RTS/CTS wired) |
| `--xonxoff`              | software flow control (fallback)                            |
| `--pace-cps 800`         | throttle output to N chars/sec when you have no flow control and see dropped characters |
| `--no-echo`              | bridge stops echoing; turn ON local echo on the II instead  |
| `--backend code`         | start in code mode                                          |
| `--workdir ~/project`    | code mode: which directory Claude works in                  |
| `--permission-mode acceptEdits` | code mode: let Claude edit without prompting (headless can't ask you) |
| `--effort medium`        | chat mode: more thinking, slower replies (default `low`)    |

## Dropped or doubled characters?

- **Doubled characters** while typing → the II is echoing locally *and* the
  bridge is echoing. Turn off local echo on the II, or run the bridge with
  `--no-echo` and turn local echo on.
- **Dropped characters** in Claude's replies at higher baud → the II can't keep
  up. Add flow control (`--rtscts` if wired, else `--xonxoff`) or throttle with
  `--pace-cps 600`.
- **Garbage / high-bit characters** → set the terminal program to 8 data bits,
  no parity, 1 stop bit, and strip/mask the high bit (most do by default).

## Layout

```
bridge/
  bridge.py        entry point: CLI, session loop, /commands
  transports.py    serial + TCP byte plumbing
  terminal.py      line editing, echo, telnet, output pacing
  render.py        Markdown -> ASCII, word-wrap, streaming formatter
  backends.py      chat (Messages API) + code (claude CLI)
  requirements.txt
apple2/
  TERMINAL-SETUP.md  wiring, pinouts, per-machine terminal config
```

## How the pieces fit

`bridge.py` picks a **transport** (serial/TCP) and a **backend** (chat/code),
wraps the connection in a `Terminal` (line editing + echo + pacing), and loops:
read a line, stream it through the backend, and feed each chunk to a
`StreamFormatter` that emits finished 40/80-column lines back to the II.
