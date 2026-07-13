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
import queue
import sys
import threading
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
    "  /quit /exit   back to the menu (Ctrl-C when idle does this too)",
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


def show_user(peer, text: str) -> None:
    """Mirror a line the Apple II user typed."""
    print(f"{GRAY}{time.strftime('%H:%M:%S')} · {peer or 'client'}{OFF} "
          f"{BOLD}> {text}{OFF}", flush=True)


def show_reply(peer, secs: float, nlines: int, mode: str) -> None:
    """Note that a reply went out - metadata only, not the text."""
    print(f"{GRAY}{time.strftime('%H:%M:%S')} · {peer or 'client'}{OFF} "
          f"{CORAL}< {mode} reply sent · {secs:.1f}s · {nlines} lines{OFF}",
          flush=True)


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


def print_banner(args, transport, pm=None) -> None:
    """The Claude Code welcome box, bridge edition: rounded border, the
    title in the top rule, coral accents. Content is (plain, styled)
    pairs so padding is computed on visible length; every stock line is
    budgeted to keep the whole box inside 40 columns."""
    rows: list = []

    def row(plain: str = "", styled: str | None = None) -> None:
        rows.append((plain, plain if styled is None else styled))

    if args.telnet:
        ip = _lan_ip()
        if ip:  # the address lives in the command - no need to say it twice
            row("one-time modem setup:",
                f"{GRAY}one-time modem setup:{OFF}")
            # one per line: &Z0= swallows the rest of its line, so
            # suggesting them side by side would store garbage
            row(f"AT&Z0={ip}:{args.port}",
                f"{BOLD}AT&Z0={ip}:{args.port}{OFF}")
            row("AT&W", f"{BOLD}AT&W{OFF}")
        else:
            row(f"listening on port {args.port}")
    else:
        row(transport.describe())
    if pm:
        row()
        row("pairing code:", f"{GRAY}pairing code:{OFF}")
        row(pm.code, f"{BOLD}{CORAL}{pm.code}{OFF}")
        if pm.ttl > 0:
            row(f"valid {int(pm.ttl // 60)} min for new devices",
                f"{GRAY}valid {int(pm.ttl // 60)} min for new devices{OFF}")
    elif args.telnet:  # --no-pair
        row()
        row("PAIRING OFF - anyone who can reach",
            f"{BOLD}{CORAL}PAIRING OFF - anyone who can reach{OFF}")
        row("this host gets a shell. Trusted LAN",
            f"{GRAY}this host gets a shell. Trusted LAN{OFF}")
        row("only.", f"{GRAY}only.{OFF}")

    title = " Apple II Terminal for Claude Code "
    ver = " v1.0.1 "
    inner = max([len(p) + 4 for p, _ in rows] + [38])  # box is 40 wide
    print()
    print(f"{CORAL}╭─{BOLD}{title}{OFF}{CORAL}"
          + "─" * (inner - len(title) - 1) + f"╮{OFF}")
    print(f"{CORAL}│{OFF}" + " " * inner + f"{CORAL}│{OFF}")
    for plain, styled in rows:
        pad = " " * (inner - len(plain) - 2)
        print(f"{CORAL}│{OFF}  {styled}{pad}{CORAL}│{OFF}")
    print(f"{CORAL}│{OFF}" + " " * inner + f"{CORAL}│{OFF}")
    print(f"{CORAL}╰" + "─" * (inner - len(ver) - 2)
          + f"{OFF}{GRAY}{ver}{OFF}{CORAL}──╯{OFF}")
    if args.telnet:
        # code mode hands callers a shell on this host; even chat mode spends
        # your API budget. Safe on a home LAN, never on the open internet.
        print(f"{CORAL}! Trusted LAN only.{OFF}{GRAY} This exposes a Claude "
              f"session on your network;{OFF}")
        print(f"{GRAY}  do NOT port-forward it or bind it to a public "
              f"interface.{OFF}")
    print(f"{GRAY}Ctrl-C to stop{OFF}")
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

# Lines a WiFi modem volunteers ON THE WIRE around a (re)connect - the
# WiModem announces "reconnected" into the session itself. Anything here,
# arriving before the user has typed a single real line, is the modem
# talking, not the human; forwarding it would burn a Claude turn.
_MODEM_CHATTER = ("RECONNECTED", "RING", "NO CARRIER", "NO ANSWER",
                  "NO DIALTONE", "BUSY", "ERROR")


def is_modem_chatter(line: str) -> bool:
    u = line.upper()
    if u in _MODEM_CHATTER or u == "CONNECT":
        return True
    # "CONNECT 2400" yes; "connect to the db" is a person talking
    return u.startswith("CONNECT ") and u[8:].strip().isdigit()


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
    peer = getattr(term.ch, "peer", None)
    if backend_err:
        term.write_line(f"[chat unavailable: {backend_err}]")
        term.write(EOT)
    if backend:  # learn the model/cwd/version, then show the header at boot
        backend.prime()
        send_header(term, backend)
    fresh = True  # no real user input yet: modem chatter is still expected
    while not term.closed:
        user = term.read_line()  # no prompt, echo off - the app echoes locally
        if user is None:
            log("channel closed by peer")
            return
        user = user.strip()
        if user.upper().startswith("ATD"):
            # Connect on the client's menu dials unconditionally; when the
            # modem was already online the dial string comes through to us
            # as data - swallow it
            log("modem dial string while already online - ignored")
            continue
        if not user or user == "\x03":
            if backend:      # session-open probe: refresh the real header
                send_header(term, backend)
            term.write(EOT)
            continue
        if fresh and is_modem_chatter(user):
            log(f"modem chatter ignored: {user!r}")
            continue
        fresh = False
        show_user(peer, user)
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
        # The backend streams on a thread so the transport can be watched for
        # a bare Ctrl-C (0x03) from the client - that cancels the turn; the
        # partial reply still lands below, tagged as interrupted.
        fmt = StreamFormatter(cols - 2)
        lines: list[str] = []
        t0 = time.monotonic()
        chunks: queue.Queue = queue.Queue()

        def _pump(b=backend, u=user) -> None:
            try:
                for chunk in b.stream(u):
                    chunks.put(chunk)
            except Exception as exc:
                log(f"stream error: {exc}")
                chunks.put("\n[bridge error: reply failed]")
            finally:
                chunks.put(None)

        threading.Thread(target=_pump, daemon=True).start()
        interrupted = False
        while True:
            try:
                chunk = chunks.get(timeout=0.2)
            except queue.Empty:
                # a lull: the only moment we touch the wire mid-turn
                if not interrupted and term.poll_ctrl_c():
                    interrupted = True
                    backend.cancel()
                if term.closed:
                    backend.cancel()
                    return
                continue
            if chunk is None:
                break
            lines.extend(fmt.feed(chunk))
        lines.extend(fmt.flush())
        send_header(term, backend)  # real header, drawn once by the client
        if lines:
            term.write(b"\x02 ")  # bullet + space, first line beside it
            term.write_line(lines[0])
            for out_line in lines[1:]:
                term.write_line("  " + out_line if out_line else "")
        if interrupted:
            term.write_line("")
            term.write(b"\x01\x01")      # gray
            term.write_line("* Interrupted by user")
        else:
            foot = backend.footer()
            if foot:
                term.write_line("")      # blank line before the footer
                term.write(b"\x01\x01")  # gray (reply may have ended mid-color)
                term.write_line("* " + foot)
        term.write(EOT)
        show_reply(peer, time.monotonic() - t0, len(lines), mode)


def _pairing_store() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "claude-ii-terminal", "paired.json")


# Pairing codes are typed on the Apple II keyboard, so the alphabet is
# uppercase + digits with the look-alikes (I/L/O, 0/1) dropped. 31 symbols,
# ~4.95 bits each: a 6-char code is 31**6 ~ 8.9e8, vs the old 4-digit 10**4.
_PAIR_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_PAIR_LEN = 6


def gen_pair_code(n: int = _PAIR_LEN) -> str:
    import secrets
    return "".join(secrets.choice(_PAIR_ALPHABET) for _ in range(n))


class PairingManager:
    """Access control for a listening bridge.

    A --telnet bridge in code mode hands anyone who can reach it a `claude`
    CLI running on this machine, so an unpaired caller must type the code
    printed at startup before the session proceeds. This bundles the brakes:

      * a shared code that expires (the pairing WINDOW closes after `ttl`),
      * per-peer exponential backoff and a hard guess cap (no brute force),
      * a persisted set of already-paired peer IPs (reconnects don't re-ask).

    Attempt state is keyed by peer IP and lives for the process, so a peer
    that hangs up and redials keeps its strike count - it can't reset the
    counter by reconnecting."""

    FREE_TRIES = 3       # wrong guesses before backoff kicks in
    BACKOFF_BASE = 2.0   # seconds, doubling each further miss
    BACKOFF_CAP = 60.0   # ceiling on the computed wait
    SLEEP_CAP = 8.0      # never actually block a connection longer than this
    MAX_TRIES = 10       # hard stop per peer per bridge run

    def __init__(self, code: str, ttl_secs: float,
                 store_path: str | None = None) -> None:
        self.code = code
        self.ttl = ttl_secs                 # 0 = the window never closes
        self.born = time.monotonic()
        self.store_path = store_path or _pairing_store()
        self.paired = self._load()
        self._fails: dict = {}              # peer -> [count, locked_until]

    # -- persistence -------------------------------------------------------- #
    def _load(self) -> set:
        try:
            with open(self.store_path) as f:
                return set(json.load(f))
        except (OSError, ValueError):
            return set()

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
            with open(self.store_path, "w") as f:
                json.dump(sorted(self.paired), f)
        except OSError as exc:
            log(f"pairing: could not persist ({exc})")

    def clear_paired(self) -> int:
        """Revoke every remembered peer. Returns how many were dropped."""
        n = len(self.paired)
        self.paired = set()
        self._save()
        return n

    # -- window / state queries -------------------------------------------- #
    def window_open(self) -> bool:
        return self.ttl <= 0 or (time.monotonic() - self.born) < self.ttl

    def is_paired(self, peer) -> bool:
        return peer in self.paired

    def locked_for(self, peer) -> float:
        """Seconds this peer must still wait before its next guess counts."""
        st = self._fails.get(peer)
        return max(0.0, st[1] - time.monotonic()) if st else 0.0

    def exhausted(self, peer) -> bool:
        st = self._fails.get(peer)
        return bool(st) and st[0] >= self.MAX_TRIES

    # -- guesses ------------------------------------------------------------ #
    def record_failure(self, peer) -> float:
        """Count a miss; return the backoff (seconds) now owed by this peer."""
        st = self._fails.setdefault(peer, [0, 0.0])
        st[0] += 1
        wait = 0.0
        if st[0] > self.FREE_TRIES:
            over = st[0] - self.FREE_TRIES
            wait = min(self.BACKOFF_BASE * (2 ** (over - 1)), self.BACKOFF_CAP)
            st[1] = time.monotonic() + wait
        return wait

    def check(self, peer, guess: str) -> bool:
        """Constant-time compare; on a match the peer is remembered as paired."""
        import secrets
        ok = (self.window_open()
              and secrets.compare_digest(guess, self.code))
        if ok:
            self.paired.add(peer)
            self._fails.pop(peer, None)
            self._save()  # survives bridge restarts
        return ok


def _lock_header(term: Terminal, lines) -> None:
    """Push a LOCKED notice as a header frame - an idle native client renders
    headers even unsolicited, so the user sees it without typing first."""
    term.write(b"\x0e")
    for line in lines:
        term.write_line(line)


def require_pairing(term: Terminal, args, pm: PairingManager) -> bool:
    """Gate a listening bridge behind the manager's code. Returns False if the
    caller hung up, was locked out, or the pairing window had already closed."""
    peer = getattr(term.ch, "peer", None)
    if pm.is_paired(peer):
        return True
    if not pm.window_open():
        log(f"pairing: window closed; refusing new device {peer}")
        if args.app:
            _lock_header(term, ("Terminal for Claude Code",
                                "PAIRING CLOSED - restart the bridge",
                                "to enroll a new device"))
            term.write(EOT)
        else:
            term.write_line("Pairing window closed - restart the bridge.")
        return False
    log(f"pairing: waiting for code from {peer} (code: {pm.code})")
    # Don't push the prompt proactively: on a native client the connect
    # happens while the user is still on the boot menu, whose buffer drain
    # discards unsolicited bytes - the prompt would be eaten and the lock
    # would look silent. Instead, answer the FIRST real line with the prompt
    # (the client is in its reply-reader by then and renders it), and end
    # every answer with EOT so it never hangs.
    prompted = False
    while not term.closed:
        line = term.read_line()
        if line is None:
            return False
        line = line.strip()
        if line.upper().startswith("ATD"):
            continue  # the client's auto-dial isn't a guess
        if is_modem_chatter(line):
            log(f"pairing: modem chatter ignored: {line!r}")
            continue  # ...and neither is the modem's own announcement
        if not line:
            if args.app and not prompted:
                _lock_header(term, ("Terminal for Claude Code",
                                    "LOCKED - type the pairing code",
                                    "(it's on the bridge console)"))
                prompted = True
            continue
        if pm.exhausted(peer):
            log(f"pairing: {peer} hit the guess cap - locked out")
            term.write_line("Too many wrong codes. Restart the bridge to retry.")
            if args.app:
                term.write(EOT)
            return False
        if pm.check(peer, line.upper()):  # code alphabet is uppercase-only
            log(f"pairing: {peer} paired (remembered)")
            term.write_line("Paired - go ahead.")
            if args.app:
                term.write(EOT)  # the client waits on end-of-reply
            return True
        wait = pm.record_failure(peer)
        strikes = pm._fails[peer][0]
        left = pm.MAX_TRIES - strikes
        msg = ("Wrong code." if prompted else "This bridge is locked.")
        tail = f" {left} left." if left <= pm.FREE_TRIES else ""
        term.write_line(f"{msg} Type the code from the bridge console.{tail}")
        if args.app:
            term.write(EOT)
        prompted = True
        log(f"pairing: wrong code from {peer} "
            f"(strike {strikes}/{pm.MAX_TRIES}, backoff {wait:.0f}s)")
        time.sleep(min(wait, pm.SLEEP_CAP))  # bounded throttle, not a hang
    return False


class _IdleGuard:
    """Wraps a Channel with an idle-read timeout for a listening bridge.

    A --telnet bridge serves one peer at a time. A peer that connects and then
    sends nothing - a half-dead socket, or an unpaired caller that never types
    the code - would hold that single slot open indefinitely (TCP keepalive
    only reaps a truly dead link, ~75s, and never notices a live-but-silent
    one). A watchdog thread here closes the underlying channel once `timeout`
    seconds pass with no byte received; every real byte resets the clock, so a
    human typing a pairing code or a prompt slowly is never cut off. Once the
    peer owns a live session, `disarm()` stops the watchdog - long quiet spells
    (Claude thinking, the user reading a long reply) are legitimate then and
    must not drop the line."""

    def __init__(self, ch, timeout: float, peer=None) -> None:
        self._ch = ch
        self._timeout = timeout
        self._last = time.monotonic()
        self._done = threading.Event()
        self._armed = True
        self.is_network = getattr(ch, "is_network", False)
        self.peer = peer if peer is not None else getattr(ch, "peer", None)
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def _watch(self) -> None:
        while not self._done.wait(0.5):
            if self._armed and time.monotonic() - self._last >= self._timeout:
                log(f"idle timeout: dropping {self.peer or 'peer'} after "
                    f"{self._timeout}s of silence")
                try:
                    self._ch.close()  # unblocks the reader with a closed channel
                except Exception:
                    pass
                self._done.set()
                return

    def read_byte(self):
        b = self._ch.read_byte()
        if b is not None and b != -1:  # a real byte, not a timeout or EOF
            self._last = time.monotonic()
        return b

    def write(self, data: bytes) -> None:
        self._ch.write(data)

    def close(self) -> None:
        self._done.set()
        try:
            self._ch.close()
        except Exception:
            pass

    def disarm(self) -> None:
        """Stop enforcing the idle timeout - the peer now owns a live session."""
        self._armed = False
        self._done.set()


def run_session(term: Terminal, args, pm: PairingManager | None = None) -> None:
    # A listening bridge serves one peer at a time; an idle or never-pairing
    # peer would otherwise hold that slot forever. Guard the pre-session window
    # with an idle-read timeout, then disarm once the peer owns a live session.
    guard = None
    if args.telnet and getattr(args, "idle_timeout", 0) > 0:
        guard = _IdleGuard(term.ch, args.idle_timeout)
        term.ch = guard
    try:
        _run_session(term, args, pm, guard)
    finally:
        if guard:
            guard.disarm()


def _run_session(term: Terminal, args, pm, guard) -> None:
    if pm and not require_pairing(term, args, pm):
        return
    if guard:
        guard.disarm()  # authenticated (or no gate): the peer owns the session
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

    fresh = True  # no real user input yet: modem chatter is still expected
    while not term.closed:
        user = term.read_line(prompt="\r\nYou> ")
        if user is None:
            log("channel closed by peer")
            return  # channel closed
        user = user.strip()
        if not user or user == "\x03":
            continue
        if fresh and is_modem_chatter(user):
            log(f"modem chatter ignored: {user!r}")
            continue
        fresh = False
        show_user(getattr(term.ch, "peer", None), user)

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
        nlines = 0
        t0 = time.monotonic()
        for chunk in backend.stream(user):
            for out_line in fmt.feed(chunk):
                term.write_line(out_line)
                nlines += 1
            if term.closed:
                return
        for out_line in fmt.flush():
            term.write_line(out_line)
            nlines += 1
        show_reply(getattr(term.ch, "peer", None),
                   time.monotonic() - t0, nlines, mode)


def handle_command(cmd: str, term: Terminal, args, backend, mode):
    """Return None to keep going, False to disconnect, or (backend, mode)."""
    parts = cmd.split()
    name = parts[0].lower()

    if name == "/help":
        for line in HELP:
            term.write_line(line)
        return None

    if name in ("/quit", "/exit"):
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
        description="Terminal for Claude Code - the host bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="SECURITY: --telnet exposes a Claude session (in code mode, a\n"
               "shell on this host) to your network. It is meant for a TRUSTED\n"
               "HOME LAN only - never port-forward it or bind it to a public\n"
               "interface. Callers are gated by a one-time pairing code with\n"
               "attempt lockout and an expiring window; --no-pair removes that\n"
               "gate (trusted, isolated networks only).")

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

    p.add_argument("--host", default="0.0.0.0",
                   help="telnet bind address (default 0.0.0.0: all interfaces, "
                        "needed so the WiFi modem can reach the host over the "
                        "LAN; set to a specific IP or 127.0.0.1 to narrow it)")
    p.add_argument("--port", type=int, default=6400, help="telnet port (default 6400)")
    p.add_argument("--pair-code", default="",
                   help="pairing code callers must type once per device "
                        "(telnet default: a random 6-char code; see --no-pair)")
    p.add_argument("--pair-ttl", type=int, default=15, metavar="MIN",
                   help="minutes the pairing window stays open to NEW devices "
                        "(default 15; 0 = never expires). Paired devices are "
                        "unaffected.")
    p.add_argument("--clear-paired", action="store_true",
                   help="forget all remembered (paired) devices at startup, "
                        "forcing every caller to re-pair")
    p.add_argument("--no-pair", action="store_true",
                   help="telnet: skip the pairing gate ENTIRELY - anyone who "
                        "can reach the host gets in (trusted networks only)")
    p.add_argument("--idle-timeout", type=int, default=60, metavar="SECS",
                   help="telnet: drop a connected peer that sends nothing for "
                        "this many seconds before its session is under way "
                        "(default 60; 0 disables). Frees the single listener "
                        "from an idle or never-pairing peer; the clock resets "
                        "on every byte, so slow typing is never cut off.")
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

    # Pairing only guards a listener. A --serial cable or a --connect dial-out
    # is a point-to-point link the user physically owns, so neither is gated.
    pm = None
    if args.telnet and not args.no_pair:
        if not args.pair_code:
            args.pair_code = gen_pair_code()
        pm = PairingManager(args.pair_code, ttl_secs=args.pair_ttl * 60)
        if args.clear_paired:
            n = pm.clear_paired()
            log(f"pairing: revoked {n} remembered device(s)")
    elif args.clear_paired:
        # honour --clear-paired even alongside --no-pair or a re-run to reset
        n = PairingManager("", 0).clear_paired()
        log(f"pairing: revoked {n} remembered device(s)")

    print_banner(args, transport, pm)
    if args.telnet:
        log("waiting for the Apple II to connect...")

    try:
        for channel in transport.channels():
            peer = getattr(channel, "peer", None) or "client"
            note = f"{peer} connected"
            if pm:
                note += (" · known device" if pm.is_paired(peer)
                         else " · NEW device - will ask for the pairing code")
            log(note)
            t0 = time.monotonic()
            term = Terminal(channel, cfg)
            try:
                run_session(term, args, pm)
            except Exception as exc:  # one peer must never take down the listener
                log(f"session error for {peer}: {exc}")
            finally:
                channel.close()
                log(f"{peer} disconnected after {time.monotonic() - t0:.0f}s")
    except KeyboardInterrupt:
        print()
        log("shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
