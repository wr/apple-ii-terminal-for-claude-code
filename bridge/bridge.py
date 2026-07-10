#!/usr/bin/env python3
"""claude-bridge - talk to Claude from a real Apple IIgs or IIc.

The Apple II is a dumb terminal. This program sits on a modern host, reads the
line you type, sends it to Claude, and streams the reply back word-wrapped for a
40- or 80-column screen.

  Serial (a USB-serial cable into the II's serial port):
      python bridge.py --serial /dev/tty.usbserial-XXXX --baud 9600

  Telnet / WiFi modem (the II dials out over TCP):
      python bridge.py --telnet --port 6400

Backends:
      --backend chat   direct Q&A with Claude (default). Nothing runs on host.
      --backend code   the real `claude` CLI. Edits files and runs commands
                       ON THIS HOST. Switch live with `/mode code`.

Type `/help` on the Apple II once connected.
"""

from __future__ import annotations

import argparse
import sys
import time

from backends import ChatBackend, CodeBackend
from render import StreamFormatter
from terminal import Terminal, TermConfig
from transports import SerialTransport, TCPTransport, TCPClientTransport

BANNER = [
    "===================================",
    "  CLAUDE ][  -  Apple II <-> Claude",
    "===================================",
    "Type /help for commands.",
    "",
]

HELP = [
    "COMMANDS:",
    "  /help         this list",
    "  /new          start a fresh conversation",
    "  /mode chat    plain Q&A with Claude (safe)",
    "  /mode code    real Claude Code (edits files here!)",
    "  /quit         hang up",
    "",
]


def log(msg: str) -> None:
    """Print to the bridge's own console (the host Terminal), not the Apple II."""
    print(f"[bridge] {msg}", flush=True)


def make_backend(mode: str, cols: int, args) -> object:
    if mode == "code":
        return CodeBackend(
            cols=cols,
            model=args.model or None,
            permission_mode=args.permission_mode,
            claude_bin=args.claude_bin,
            cwd=args.workdir,
            show_tools=not args.app,  # app keeps a spinner up until the answer
        )
    return ChatBackend(
        cols=cols,
        model=args.model or "claude-opus-4-8",
        effort=args.effort,
    )


EOT = b"\x04"  # app mode: marks end of a reply so the client stops its spinner


def send_header(term, backend) -> None:
    """Push the client's header frame: 0x0E then one CR-terminated line each."""
    hdr = backend.header() if backend else None
    if not hdr:
        return
    term.write(b"\x0e")
    for line in hdr:
        term.write_line(line)


def run_bootstrap(term: Terminal, path: str) -> None:
    """Stream a raw binary into the IIgs's memory at $4000 over the serial link.

    Protocol (peer is apple2gs/BOOTSTRAP.bas.txt):
      IIgs -> bridge: CR            link probe; we answer 0x06 so the loader
                                    knows it's connected and skips auto-dialing
      IIgs -> bridge: 'R'           ready to receive
      bridge -> IIgs: sum_lo sum_mid sum_hi len_lo len_hi, then the raw bytes
    The 5-byte preamble carries the checksum and length, so the loader on the
    IIgs never contains build-specific constants. The file is re-read on every
    'R', so rebuilds are picked up without restarting the bridge."""
    with open(path, "rb") as f:
        data = f.read()
    log("bootstrap: waiting for the loader's ready byte ('R') on the IIgs...")
    while not term.closed:
        b = term.ch.read_byte()
        if b is None or b < 0:
            continue
        b &= 0x7F  # ignore stray bytes (modem CONNECT text, etc.)
        if b == 0x0D:
            term.ch.write(b"\x06")  # probe ack
            continue
        if b == ord("R"):
            log(f"bootstrap: got ready - streaming {len(data)} bytes to $4000")
            break
    if term.closed:
        return
    total = sum(data)
    preamble = bytes([total & 0xFF, (total >> 8) & 0xFF, (total >> 16) & 0xFF,
                      len(data) & 0xFF, (len(data) >> 8) & 0xFF])
    for byte in preamble + data:
        term.ch.write(bytes([byte]))
        time.sleep(0.002)  # ~400 B/s: the loader's ML receive loop keeps up with
        # full 9600 easily; stay below wire rate so the WiModem's buffers never fill
    log(f"bootstrap: sent {len(data)} bytes + checksum {total} - "
        "the loader verifies and BSAVEs; RUN again to retry")


def run_app_session(term: Terminal, args, backend, backend_err, mode) -> None:
    """Protocol for the native clients (apple2gs/claude.s, or the simpler
    apple2/CLAUDE.APP.bas.txt): the bridge stays silent (no banner, no prompts,
    no echo) and just relays the backend's reply, then sends EOT. The Apple II
    app draws all the UI itself."""
    cols = args.cols
    if getattr(args, "bootstrap", None):
        # Install-only mode: serve the binary on every ready byte so the IIgs
        # loader can retry with a plain RUN after a bad checksum. Nothing else
        # is sent (no header/prime), so no stray bytes can pollute a retry.
        # Restart without --bootstrap to serve the client for real.
        while not term.closed:
            run_bootstrap(term, args.bootstrap)
        return
    if backend_err:
        term.write_line(f"[chat unavailable: {backend_err}]")
        term.write(EOT)
    if backend:  # learn the model/cwd/version, then show the header at boot
        backend.prime()
        send_header(term, backend)
    while not term.closed:
        user = term.read_line()  # no prompt, echo off - the app echoes locally
        if user is None:
            log("channel closed by peer")
            return
        user = user.strip()
        log(f"recv: {user!r}")
        if user.upper().startswith("ATD"):
            # the client dials unconditionally at startup; when the modem was
            # already online the dial string comes through to us - swallow it
            log("modem dial string while already online - ignored")
            continue
        if not user or user == "\x03":
            term.write(EOT)
            continue
        if user.startswith("/"):
            keep = handle_command(user, term, args, backend, mode)
            if keep is False:
                term.write(b"\x03")  # CMD_QUIT: the client returns to its menu
                term.write(EOT)
                return
            term.write(EOT)
            if isinstance(keep, tuple):
                backend, mode = keep
            continue
        if backend is None:
            term.write_line("[no backend]")
            term.write(EOT)
            continue
        # Buffer the whole reply, then send it after generation finishes. The
        # client receives nothing until then, so its thinking spinner runs for
        # the entire think instead of stopping at the first streamed byte.
        # Width is cols-2: the reply renders as a Claude Code-style block, two
        # cells of bullet/indent in front of every line.
        fmt = StreamFormatter(cols - 2)
        lines: list[str] = []
        n = 0
        for chunk in backend.stream(user):
            n += 1
            lines.extend(fmt.feed(chunk))
            if term.closed:
                return
        lines.extend(fmt.flush())
        send_header(term, backend)  # real header, drawn once by the client
        if lines:
            term.write(b"\x02 ")  # bullet + space, first line beside it
            term.write_line(lines[0])
            for out_line in lines[1:]:
                term.write_line("  " + out_line if out_line else "")
        foot = backend.footer()
        if foot:
            term.write_line("")          # blank line before the footer
            term.write(b"\x01\x01")      # gray (reply may have ended mid-color)
            term.write_line("* " + foot)
        term.write(EOT)
        log(f"reply done ({n} chunks from {mode})")


def run_session(term: Terminal, args) -> None:
    cols = args.cols
    mode = args.backend
    backend = None
    backend_err = None
    try:
        backend = make_backend(mode, cols, args)
    except Exception as exc:  # e.g. missing API key for chat mode
        backend_err = str(exc)

    if args.app:
        return run_app_session(term, args, backend, backend_err, mode)

    for line in BANNER:
        term.write_line(line)
    if backend_err:
        term.write_line(f"[chat unavailable: {backend_err}]")
        term.write_line("Try /mode code, or set ANTHROPIC_API_KEY and reconnect.")
        term.write_line("")

    while not term.closed:
        user = term.read_line(prompt="\r\nYou> ")
        if user is None:
            log("channel closed by peer")
            return  # channel closed
        user = user.strip()
        log(f"recv: {user!r}")
        if not user or user == "\x03":
            continue

        if user.startswith("/"):
            keep = handle_command(user, term, args, backend, mode)
            if keep is False:
                return
            if isinstance(keep, tuple):  # (new_backend, new_mode)
                backend, mode = keep
            continue

        if backend is None:
            term.write_line("[no backend - use /mode code or set an API key]")
            continue

        term.write_line("")
        term.write_line(f"Claude ({mode})>")
        fmt = StreamFormatter(cols)
        nchunks = 0
        for chunk in backend.stream(user):
            nchunks += 1
            for out_line in fmt.feed(chunk):
                term.write_line(out_line)
            if term.closed:
                return
        for out_line in fmt.flush():
            term.write_line(out_line)
        log(f"reply done ({nchunks} chunks from {mode})")


def handle_command(cmd: str, term: Terminal, args, backend, mode):
    """Return None to keep going, False to disconnect, or (backend, mode)."""
    parts = cmd.split()
    name = parts[0].lower()

    if name == "/help":
        for line in HELP:
            term.write_line(line)
        return None

    if name == "/quit":
        term.write_line("Goodbye.")
        return False

    if name == "/new":
        if backend:
            backend.reset()
        term.write_line("[new conversation]")
        return None

    if name == "/mode":
        if len(parts) < 2 or parts[1] not in ("chat", "code"):
            term.write_line("Usage: /mode chat | /mode code")
            return None
        new_mode = parts[1]
        try:
            new_backend = make_backend(new_mode, args.cols, args)
        except Exception as exc:
            term.write_line(f"[cannot switch: {exc}]")
            return None
        warn = " (edits files on the host!)" if new_mode == "code" else ""
        term.write_line(f"[mode: {new_mode}{warn}]")
        return (new_backend, new_mode)

    term.write_line(f"[unknown command: {name} - try /help]")
    return None


def parse_hostport(value: str, default_host: str = "127.0.0.1") -> tuple[str, int]:
    if ":" in value:
        host, _, port = value.rpartition(":")
        return (host or default_host, int(port))
    return (default_host, int(value))


def build_transport(args):
    if args.serial:
        return SerialTransport(
            port=args.serial, baud=args.baud,
            rtscts=args.rtscts, xonxoff=args.xonxoff,
        )
    if args.connect:
        host, port = parse_hostport(args.connect)
        return TCPClientTransport(host=host, port=port)
    return TCPTransport(host=args.host, port=args.port)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Apple II <-> Claude bridge")

    tr = p.add_mutually_exclusive_group()
    tr.add_argument("--serial", metavar="PORT",
                    help="serial device, e.g. /dev/tty.usbserial-1420")
    tr.add_argument("--telnet", action="store_true",
                    help="listen for a TCP/telnet client (WiFi modem)")
    tr.add_argument("--connect", metavar="HOST:PORT",
                    help="dial OUT to a listening host (KEGS Incoming mode, port 6502)")

    p.add_argument("--baud", type=int, default=9600, help="serial baud (default 9600)")
    p.add_argument("--rtscts", action="store_true", help="hardware flow control")
    p.add_argument("--xonxoff", action="store_true", help="software flow control")

    p.add_argument("--host", default="0.0.0.0", help="telnet bind address")
    p.add_argument("--port", type=int, default=6400, help="telnet port (default 6400)")
    p.add_argument("--telnet-negotiate", action="store_true",
                   help="do telnet IAC negotiation (for a raw `telnet` client)")

    p.add_argument("--cols", type=int, default=80, choices=(40, 80),
                   help="screen width (default 80)")
    p.add_argument("--pace-cps", type=int, default=0,
                   help="cap output chars/sec (0=off); needed for the plain BASIC/"
                        "terminal clients only - the IIgs client has a ring buffer")
    p.add_argument("--no-echo", action="store_true",
                   help="don't echo typed chars (turn ON local echo on the II)")

    p.add_argument("--app", action="store_true",
                   help="native-client protocol: no echo/banner/prompts, EOT after "
                        "each reply (for apple2gs/claude.s or apple2/CLAUDE.APP.bas.txt)")
    p.add_argument("--bootstrap", metavar="FILE",
                   help="app mode: stream this raw binary to $4000 on the IIgs and "
                        "run it (a diskless RAM-load), then serve it")
    p.add_argument("--backend", default="chat", choices=("chat", "code"))
    p.add_argument("--model", default="", help="override the Claude model id")
    p.add_argument("--effort", default="low",
                   choices=("low", "medium", "high", "xhigh", "max"),
                   help="chat thinking effort (default low, for responsiveness)")
    p.add_argument("--permission-mode", default="default",
                   help="code mode: claude --permission-mode value")
    p.add_argument("--claude-bin", default="claude", help="path to the claude CLI")
    p.add_argument("--workdir", default=None, help="code mode: working directory")

    args = p.parse_args(argv)
    if not args.serial and not args.telnet and not args.connect:
        p.error("choose a transport: --serial PORT, --telnet, or --connect HOST:PORT")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    transport = build_transport(args)
    cfg = TermConfig(
        width=args.cols,
        echo=(not args.no_echo) and not args.app,  # app echoes locally
        pace_cps=args.pace_cps,
        telnet=args.telnet and args.telnet_negotiate,
        newline="\r" if args.app else "\r\n",  # app uses bare CR
    )

    print(f"[bridge] {transport.describe()}")
    print(f"[bridge] {args.cols} cols, backend={args.backend}"
          f"{', app protocol' if args.app else ''}. Ctrl-C to stop.")
    if args.telnet:
        print("[bridge] waiting for the Apple II to connect...")

    try:
        for channel in transport.channels():
            print("[bridge] connected")
            term = Terminal(channel, cfg)
            try:
                run_session(term, args)
            finally:
                channel.close()
                print("[bridge] disconnected")
    except KeyboardInterrupt:
        print("\n[bridge] shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
