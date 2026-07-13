# Apple II Terminal for Claude Code

A real Apple II, as a terminal for Claude Code.

![The IIgs session screen: coral mascot, header, and a scrolling transcript in Super Hi-Res 640 mode](docs/session-preview.png)

Boot a 140K floppy, dial a WiFi modem, and your Apple II becomes a terminal for
the real `claude` CLI running on a modern machine. Claude reads files, edits
code, and runs commands, driven from a 40-year-old keyboard with the results
streaming back at 9600 baud. One disk boots every model from the IIgs down to
the II+. No Apple II? It runs in an emulator in about five minutes.

It's not a chat toy. The backend is the actual agentic Claude Code, not a Q&A
wrapper, and the clients are bare-metal 65816 and 6502 that draw the whole UI
themselves from a tiny 7-bit ASCII protocol. A IIgs gets a Super Hi-Res client
with an animated splash, scrolling transcript, and thinking spinner; a IIe,
IIc, IIc Plus, or II+ gets a text-mode client with the same shape. Press
Connect and it plays the 1986 dial-up soundscape: dial tone, touch-tones that
spell C-L-A-U-D-E on the keypad, ring, answer tone, carrier buzz, then the
silence of a Hayes with its speaker on.

## Try it in an emulator (5 minutes, no hardware)

You need [KEGS](https://kegs.sourceforge.net/), Python 3 (stock, no pip or
venv), and the [`claude` CLI](https://claude.com/claude-code) logged in.

1. Download **CLAUDE.dsk** from
   [Releases](https://github.com/wr/apple-ii-terminal-for-claude-code/releases).
2. In KEGS, press **F4**: set **s6d1** to `CLAUDE.dsk`, and set Serial Port
   **Slot 2** to **Incoming** (KEGS then listens on TCP 6502).
3. Start the bridge, then reboot the emulator with Ctrl-⌘-Reset:

   ```sh
   git clone https://github.com/wr/apple-ii-terminal-for-claude-code
   cd apple-ii-terminal-for-claude-code/bridge
   python3 bridge.py --connect 127.0.0.1:6502 --app --backend code --workdir ~/your-project
   ```

4. On the boot menu pick **1. Connect**, then type. `--workdir` is the project
   Claude works in.

## On real hardware

What you need:

| Thing | Options |
|---|---|
| An Apple II | IIgs for the graphics client; IIe, IIc, IIc Plus, or II+ for the text client |
| A Hayes-compatible WiFi modem | [WiModem 232 Pro](https://www.cbmstuff.com/) auto-dials out of the box; WiFi232 and ESP8266 Zimodem/RetroWiFi builds (~$20–80) work with one manual step ([why](docs/MODEM-SETUP.md)). IIe and II+ also need a Super Serial Card in slot 2 |
| A way to boot a 5.25" image | [FloppyEmu](https://www.bigmessowires.com/floppy-emu/), or a real drive plus [ADTPro](https://adtpro.com/) to write the floppy |

Setup:

1. **Bridge**, on the machine with the `claude` CLI:

   ```sh
   python3 bridge.py --telnet --app --backend code --workdir ~/your-project
   ```

   It prints a 6-character pairing code and listens on TCP 6400. The first
   thing a new device sends must be that code; once paired, its IP is
   remembered across restarts.

   > **Trusted LAN only.** `--telnet` exposes a Claude session (in code mode, a
   > shell on the host) to your network. Run it on a home LAN you trust and
   > never port-forward it or bind it to a public interface. See
   > [pairing flags](#bridge-flags) to rotate, expire, or revoke access.

2. **Modem**: store the bridge's address as phone book entry 0, then save:

   ```
   AT&Z0=192.168.1.50:6400      (your host's LAN IP)
   AT&W
   ```

   Connect on the boot menu dials entry 0. The menu also has a live Hayes AT
   console for whatever your modem needs. Cables, per-device commands (a fresh
   WiModem ships at 300 baud and wants `AT*B9600` once), and a "modem plays
   dead" checklist are in [docs/MODEM-SETUP.md](docs/MODEM-SETUP.md).

3. **Disk**: copy `CLAUDE.dsk` to a FloppyEmu SD card (5.25" mode, boots from
   slot 6). On a Mac, `tools/install-sd.sh` does it safely; FloppyEmu rejects
   images that land fragmented, and macOS fragments more than you'd expect. If
   a card is already fragmented, `tools/install-sd.sh repair` fixes it once.

4. Power on and pick **Connect**. If the modem is still online from a previous
   session and drives DCD, Connect notices and skips the redial.

To update later, download the new release image and re-run `install-sd.sh`; it
overwrites the existing image in place, which can't fragment.

## Bridge flags

The bridge is one Python script. Pick a transport, a backend, and (for the
native clients) `--app`. Two commands cover almost everything:

```sh
# Emulator (KEGS in Incoming mode):
python3 bridge.py --connect 127.0.0.1:6502 --app --backend code --workdir ~/project

# Real hardware (WiFi modem listening):
python3 bridge.py --telnet --app --backend code --workdir ~/project
```

**Transport** (choose one):

| Flag | Use |
|---|---|
| `--connect HOST:PORT` | Dial out to a listening emulator (KEGS Incoming, port 6502) |
| `--telnet` | Listen for a WiFi modem or TCP client (port 6400) |
| `--serial PORT` | A serial cable, e.g. `/dev/tty.usbserial-1420` (pair with `--baud`, default 9600) |

**Backend:**

| Flag | Use |
|---|---|
| `--backend code` | The real agentic Claude Code. Edits files and runs commands on the host, in `--workdir`. That's the point, but know it |
| `--backend chat` | Plain Q&A via the Messages API. Needs `ANTHROPIC_API_KEY` and the one `pip install anthropic` (default backend) |
| `--workdir DIR` | Code mode: the project Claude works in |
| `--model ID` | Override the Claude model |
| `--effort LEVEL` | Chat thinking effort: low/medium/high/xhigh/max (default low) |

**Native client:**

| Flag | Use |
|---|---|
| `--app` | Native-client protocol. Required for the clients on the boot disk |
| `--cols 40\|80` | Screen width (default 80; use 40 for a II+ or a 40-column IIe) |

**Pairing** (telnet only):

| Flag | Use |
|---|---|
| `--pair-code CODE` | Set the code yourself (default: a random 6-char code) |
| `--pair-ttl MIN` | Minutes the code accepts new devices (default 15; `0` = never expires) |
| `--clear-paired` | Forget every remembered device at startup |
| `--no-pair` | Drop the pairing gate entirely (isolated networks only) |
| `--host ADDR` | Bind address (default `0.0.0.0`; set `127.0.0.1` to keep it local) |

Run `python3 bridge.py --help` for the rest (flow control, pacing, telnet
negotiation, permission mode).

## Also works as a plain terminal

Run the bridge without `--app` and it speaks ordinary 40/80-column text, so any
Apple II with a terminal program, or a stock IIc using the firmware's built-in
terminal over a serial cable, can talk to Claude with nothing installed on the
II. Wiring, pinouts, and per-machine settings are in
[apple2/TERMINAL-SETUP.md](apple2/TERMINAL-SETUP.md).

## In a session

Slash commands from the II: the bridge handles `/help`, `/new` or `/clear`,
`/mode chat|code`, `/model NAME`, and `/quit` or `/exit`. In code mode
everything else passes through to the CLI, so `/cost`, `/context`, `/compact`,
and your installed skills run for real. Ctrl-C interrupts a reply mid-think (the
bridge kills the turn and sends what it has); pressed at an idle prompt it quits
to the menu.

## Building from source

You don't need this to run it; the release disk is prebuilt. To hack on it you
need [cc65](https://cc65.github.io/) (`brew install cc65`),
[dos33fsprogs](https://github.com/deater/dos33fsprogs) (built anywhere, point
`DOS33FSPROGS` at it), and Python 3 with Pillow.

```sh
cd apple2gs && ./build.sh                 # both clients into one CLAUDE.dsk
python3 preview.py assets.inc out.png     # render the SHR screen, no emulator
```

`build.sh` starts from a pristine Apple DOS 3.3 System Master and injects both
clients plus a machine-detecting HELLO; that master-based image is the one
proven to boot KEGS, FloppyEmu, and real drives alike. The master is vendored at
`apple2gs/dos33-master-jan83.dsk` (the January 1983 System Master, 143,360
bytes), so a clean checkout builds with nothing to fetch. It's Apple's OS, not
ours; see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). Verify it:

```sh
shasum -a 256 apple2gs/dos33-master-jan83.dsk
# 70986935d95c4a918852700364ac107607eb861a7d93a69c2b5caf44a696b17a
```

Everything else is
generated at build time: the font from [unscii](http://viznut.fi/unscii/), the
splash animation machine-ported from a gif, the sounds from tone tables in
`gen_assets.py`. Provenance for the bundled material is in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

The 8-bit client has its own harness: MAME with an emulated Super Serial Card
mapped to a TCP socket, driven by Lua-scripted keystrokes, so the whole boot →
dial → session → reply loop runs unattended.

## How it works, and what bit us

The bridge reads a CR-terminated line, runs a turn of `claude -p --output-format
stream-json`, flattens the reply to word-wrapped 7-bit ASCII, and streams it
back with a tiny in-band vocabulary (`0x01 n` color, `0x02` bullet, `0x0E`
header, `0x03` session-over, `0x04` end-of-reply). Both clients keep a ring
buffer serviced from every loop, because the serial chips buffer almost nothing
at 9600 baud: 3 bytes on the IIgs's SCC, one byte on the 8-bit machines' 6551.

A few things exist only because real hardware is real:

- A IIgs never initializes its serial chip at power-on (Apple TN #018), so the
  port is dead until software programs it. Working in an emulator proves
  nothing.
- A real Zilog 8530 latches Rx-overrun errors and can wedge a naive status
  poll, so every read goes through a bounded drain with an error reset.
- FloppyEmu's "file not contiguous" turned out to be macOS's first-fit FAT
  allocator shredding fresh copies onto the card. Diagnosed by parsing the FAT
  raw, fixed in the installer, and it grew into its own tool:
  [wr/floppyemu-sd](https://github.com/wr/floppyemu-sd).

The full contributor gotcha list is in [AGENTS.md](AGENTS.md).

## Credits

Not affiliated with or endorsed by Anthropic; this is a fan project that gives
their excellent CLI a 1986 terminal. "Claude" and the splash-screen crab are
Anthropic's; the session mascot is original. Font:
[unscii](http://viznut.fi/unscii/) (CC0). Disk tooling:
[dos33fsprogs](https://github.com/deater/dos33fsprogs) by Vince Weaver.
Emulator: [KEGS](https://kegs.sourceforge.net/). And the Apple II community, who
kept all of this alive for forty years.

MIT license, covering this project's own code only. The build and the release
disk also include third-party material (Apple's DOS 3.3, the Clawd art, the
unscii font); provenance and status for each is in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
