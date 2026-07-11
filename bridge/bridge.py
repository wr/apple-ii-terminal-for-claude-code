#!/usr/bin/env python3
"""The host half of Terminal for Claude Code (Apple II).

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
import json
import os
import sys
import time

from backends import ChatBackend, CodeBackend
from render import StreamFormatter
from terminal import Terminal, TermConfig
from transports import SerialTransport, TCPTransport, TCPClientTransport

BANNER = [
    "===================================",
    "  TERMINAL FOR CLAUDE CODE",
    "  on the Apple ][",
    "===================================",
    "Type /help for commands.",
    "",
]

HELP = [
    "COMMANDS:",
    "  /help         this list",
    "  /new /clear   start a fresh conversation",
    "  /mode chat    plain Q&A with Claude (safe)",
    "  /mode code    real Claude Code (edits files here!)",
    "  /model NAME   switch model (opus, sonnet, haiku...)",
    "  /quit         hang up",
    "code mode: other /commands go to Claude Code itself -",
    "  /cost /context /compact and skills work; TUI-only ones say so.",
    "",
]


# The host console doubles as a live transcript: plumbing is gray, the
# user's lines are bold, replies are mirrored gray as they're sent. Colors
# vanish when stdout isn't a terminal (piped/logged). Gray is a real
# mid-gray (256-color 245), not SGR dim - dim is unreadable on many themes.
_TTY = sys.stdout.isatty()
GRAY = "\x1b[38;5;245m" if _TTY else ""
BOLD = "\x1b[1m" if _TTY else ""
CORAL = "\x1b[38;5;209m" if _TTY else ""
OFF = "\x1b[0m" if _TTY else ""

def log(msg: str) -> None:
    """Plumbing chatter on the host console (never sent to the Apple II)."""
    print(f"{GRAY}{time.strftime('%H:%M:%S')} · {msg}{OFF}", flush=True)


def show_user(text: str) -> None:
    """Mirror a line the Apple II user typed."""
    print(f"{time.strftime('%H:%M:%S')} {BOLD}> {text}{OFF}", flush=True)


def show_reply(lines: list, secs: float, mode: str) -> None:
    """Mirror the reply the Apple II just received."""
    for line in lines:
        print(f"{GRAY}  {line}{OFF}")
    print(f"{CORAL}· {mode} replied in {secs:.1f}s "
          f"({len(lines)} lines){OFF}", flush=True)


def _lan_ip():
    """This host's LAN address - the IP the WiFi modem must dial."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # routing lookup only; nothing is sent
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def print_banner(args, transport) -> None:
    """The Claude Code welcome box, bridge edition: rounded border, the
    title in the top rule, coral accents. Content is (plain, styled)
    pairs so padding is computed on visible length; every stock line is
    budgeted to keep the whole box inside 40 columns."""
    rows: list = []

    def row(plain: str = "", styled: str | None = None) -> None:
        rows.append((plain, plain if styled is None else styled))

    if args.telnet:
        ip = _lan_ip()
        addr = f"{ip}:{args.port}" if ip else f"this machine, port {args.port}"
        row("Your Apple II dials:", f"{GRAY}Your Apple II dials:{OFF}")
        row(addr, f"{BOLD}{addr}{OFF}")
        if ip:
            row()
            row("one-time modem setup:",
                f"{GRAY}one-time modem setup:{OFF}")
            # one per line: &Z0= swallows the rest of its line, so
            # suggesting them side by side would store garbage
            row(f"AT&Z0={addr}")
            row("AT&W")
    else:
        row(transport.describe())
    if args.pair_code:
        row()
        row("pairing code:", f"{GRAY}pairing code:{OFF}")
        row(args.pair_code, f"{BOLD}{CORAL}{args.pair_code}{OFF}")

    title = " Terminal for Claude Code "
    ver = " v0.2.0 "
    inner = max([len(p) for p, _ in rows] + [len(title) + 2]) + 4
    print()
    print(f" {CORAL}╭─{BOLD}{title}{OFF}{CORAL}"
          + "─" * (inner - len(title) - 1) + f"╮{OFF}")
    print(f" {CORAL}│{OFF}" + " " * inner + f"{CORAL}│{OFF}")
    for plain, styled in rows:
        pad = " " * (inner - len(plain) - 2)
        print(f" {CORAL}│{OFF}  {styled}{pad}{CORAL}│{OFF}")
    print(f" {CORAL}│{OFF}" + " " * inner + f"{CORAL}│{OFF}")
    print(f" {CORAL}╰" + "─" * (inner - len(ver) - 2)
          + f"{OFF}{GRAY}{ver}{OFF}{CORAL}──╯{OFF}")
    print(f" {GRAY}Ctrl-C to stop{OFF}")
    print()


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


def run_app_session(term: Terminal, args, backend, backend_err, mode) -> None:
    """Protocol for the native clients (apple2gs/claude.s and
    apple2/claude2.s): the bridge stays silent (no banner, no prompts, no
    echo) and just relays the backend's reply, then sends EOT. The Apple II
    client draws all the UI itself."""
    cols = args.cols
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
        if user.upper().startswith("ATD"):
            # the client dials unconditionally at startup; when the modem was
            # already online the dial string comes through to us - swallow it
            log("modem dial string while already online - ignored")
            continue
        if not user or user == "\x03":
            if backend:      # session-open probe: refresh the real header
                send_header(term, backend)
            term.write(EOT)
            continue
        show_user(user)
        if user.startswith("/"):
            keep = handle_command(user, term, args, backend, mode)
            if keep is False:
                term.write(b"\x03")  # CMD_QUIT: the client returns to its menu
                term.write(EOT)
                return
            if keep != "pass":  # "pass" = forward to claude like a prompt
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
        t0 = time.monotonic()
        for chunk in backend.stream(user):
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
        show_reply(lines, time.monotonic() - t0, mode)


def _pairing_store() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "claude-ii-terminal", "paired.json")


def _load_paired() -> set:
    try:
        with open(_pairing_store()) as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def _save_paired(peers: set) -> None:
    path = _pairing_store()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(sorted(peers), f)
    except OSError as exc:
        log(f"pairing: could not persist ({exc})")


_paired_peers: set = _load_paired()


def require_pairing(term: Terminal, args) -> bool:
    """Gate a listening bridge behind a short code shown on the host.

    A --telnet bridge in code mode hands anyone on the LAN a `claude` CLI
    running on this machine, so an unpaired caller must type the code
    printed at startup before the session proceeds. Pairing sticks to the
    peer's IP for the life of the process (reconnects don't re-ask).
    Returns False if the caller hung up before pairing."""
    peer = getattr(term.ch, "peer", None)
    if peer in _paired_peers:
        return True
    log(f"pairing: waiting for code from {peer} (code: {args.pair_code})")
    # Don't push the prompt proactively: on a native client the connect
    # happens while the user is still on the boot menu, whose buffer
    # drain discards unsolicited bytes - the prompt would be eaten and
    # the lock would look silent. Instead, answer the FIRST real line
    # with the prompt (the client is in its reply-reader by then and
    # renders it), and end every answer with EOT so it never hangs.
    prompted = False
    while not term.closed:
        line = term.read_line()
        if line is None:
            return False
        line = line.strip()
        if line.upper().startswith("ATD"):
            continue  # the client's auto-dial isn't a guess
        if not line:
            # the client's session-open CR probe: answer with the lock
            # notice as a header frame - an idle client renders headers,
            # so the user sees LOCKED without having to type first
            if args.app and not prompted:
                term.write(b"\x0e")
                term.write_line("Terminal for Claude Code")
                term.write_line("LOCKED - type the pairing code")
                term.write_line("(it's on the bridge console)")
                prompted = True
            continue
        if line == args.pair_code:
            _paired_peers.add(peer)
            _save_paired(_paired_peers)  # survives bridge restarts
            log(f"pairing: {peer} paired (remembered)")
            term.write_line("Paired - go ahead.")
            if args.app:
                term.write(EOT)  # the client waits on end-of-reply
            return True
        msg = ("Wrong code." if prompted else "This bridge is locked.")
        term.write_line(f"{msg} Type the code shown on the bridge console.")
        if args.app:
            term.write(EOT)
        prompted = True
        log(f"pairing: {'wrong' if prompted else 'prompted'} code from {peer}")
        time.sleep(0.5)  # gentle throttle, not a hang
    return False


def run_session(term: Terminal, args) -> None:
    if args.pair_code and not require_pairing(term, args):
        return
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
        if not user or user == "\x03":
            continue
        show_user(user)

        if user.startswith("/"):
            keep = handle_command(user, term, args, backend, mode)
            if keep is False:
                return
            if keep != "pass":  # "pass" = forward to claude like a prompt
                if isinstance(keep, tuple):  # (new_backend, new_mode)
                    backend, mode = keep
                continue

        if backend is None:
            term.write_line("[no backend - use /mode code or set an API key]")
            continue

        term.write_line("")
        term.write_line(f"Claude ({mode})>")
        fmt = StreamFormatter(cols)
        mirror: list[str] = []
        t0 = time.monotonic()
        for chunk in backend.stream(user):
            for out_line in fmt.feed(chunk):
                term.write_line(out_line)
                mirror.append(out_line)
            if term.closed:
                return
        for out_line in fmt.flush():
            term.write_line(out_line)
            mirror.append(out_line)
        show_reply(mirror, time.monotonic() - t0, mode)


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

    if name in ("/new", "/clear"):
        if backend:
            backend.reset()
        term.write_line("[new conversation]")
        return None

    if name == "/model" and len(parts) > 1:
        # each code-mode turn is a fresh `claude -p` process, so a /model
        # passed through would not stick - remember it bridge-side instead
        if backend:
            backend._model = parts[1]
            if hasattr(backend, "_last_model"):
                backend._last_model = None  # header shows the new model
        term.write_line(f"[model: {parts[1]} from the next message]")
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

    if mode == "code":
        return "pass"  # `claude -p` runs many slash commands natively
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
    p = argparse.ArgumentParser(
        description="Terminal for Claude Code - the host bridge")

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
    p.add_argument("--pair-code", default="",
                   help="pairing code callers must type once per bridge run "
                        "(telnet default: random; see --no-pair)")
    p.add_argument("--no-pair", action="store_true",
                   help="telnet: skip the pairing gate (trusted networks only)")
    p.add_argument("--telnet-negotiate", action="store_true",
                   help="do telnet IAC negotiation (for a raw `telnet` client)")

    p.add_argument("--cols", type=int, default=80, choices=(40, 80),
                   help="screen width (default 80)")
    p.add_argument("--pace-cps", type=int, default=0,
                   help="cap output chars/sec (0=off); for plain terminal programs "
                        "without flow control - the native clients don't need it")
    p.add_argument("--no-echo", action="store_true",
                   help="don't echo typed chars (turn ON local echo on the II)")

    p.add_argument("--app", action="store_true",
                   help="native-client protocol: no echo/banner/prompts, EOT after "
                        "each reply (for the native clients on the boot disk)")
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

    if args.telnet and not args.no_pair:
        if not args.pair_code:
            import secrets
            args.pair_code = f"{secrets.randbelow(10000):04d}"
    elif not args.pair_code:
        args.pair_code = ""

    print_banner(args, transport)
    if args.telnet:
        log("waiting for the Apple II to connect...")

    try:
        for channel in transport.channels():
            peer = getattr(channel, "peer", None)
            log(f"connected ({peer})" if peer else "connected")
            t0 = time.monotonic()
            term = Terminal(channel, cfg)
            try:
                run_session(term, args)
            finally:
                channel.close()
                log(f"disconnected after {time.monotonic() - t0:.0f}s")
    except KeyboardInterrupt:
        print()
        log("shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
