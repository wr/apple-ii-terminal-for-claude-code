"""A line-oriented terminal on top of a raw Channel.

Handles the things a dumb Apple II terminal needs from the other side:
  * reading a line (CR-terminated), with backspace editing
  * optional server-side echo (so you can turn OFF local echo on the Apple II)
  * output pacing for serial lines with no hardware flow control
  * minimal telnet (IAC) handling so a real `telnet` client behaves and its
    negotiation bytes never show up as garbage on screen
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from transports import Channel

# Control bytes we care about.
CR = 0x0D
LF = 0x0A
BS = 0x08
DEL = 0x7F
CTRL_C = 0x03
CTRL_U = 0x15  # kill line
ESC = 0x1B

# Telnet.
IAC = 255
DO, DONT, WILL, WONT, SB, SE = 253, 254, 251, 252, 250, 240
OPT_ECHO = 1
OPT_SGA = 3


@dataclass
class TermConfig:
    width: int = 80
    echo: bool = True          # bridge echoes typed chars (local echo OFF on II)
    pace_cps: int = 0          # chars/sec cap on output; 0 = as fast as possible
    newline: str = "\r\n"      # what we send at end of each line
    telnet: bool = False       # negotiate telnet options on a network channel
    max_line: int = 4096       # cap a single input line; a peer that never
                               # sends CR can't grow the buffer without bound


class Terminal:
    def __init__(self, channel: Channel, cfg: TermConfig) -> None:
        self.ch = channel
        self.cfg = cfg
        self._closed = False
        self._skip_eol: int | None = None  # swallow the LF that trails a CR (or vice-versa)
        if cfg.telnet and channel.is_network:
            self._negotiate()

    # -- telnet ------------------------------------------------------------- #
    def _negotiate(self) -> None:
        # Tell the client: I will echo, and suppress go-ahead (char-at-a-time).
        self.ch.write(bytes([IAC, WILL, OPT_ECHO, IAC, WILL, OPT_SGA]))

    def _handle_iac(self) -> None:
        verb = self._raw_byte_blocking()
        if verb is None:
            return  # peer gone mid-sequence
        if verb in (DO, DONT, WILL, WONT):
            opt = self._raw_byte_blocking()
            if opt is None:
                return  # peer gone before the option byte
            # Politely refuse anything we didn't ask for; stay in char mode.
            if verb == DO:
                self.ch.write(bytes([IAC, WONT, opt]))
            elif verb == WILL:
                self.ch.write(bytes([IAC, DONT, opt]))
        elif verb == SB:
            # Skip a sub-negotiation block up to IAC SE, bounded so a peer
            # that never sends SE can't park us here forever.
            prev = None
            for _ in range(512):
                b = self._raw_byte_blocking()
                if b is None:
                    return
                if prev == IAC and b == SE:
                    return
                prev = b
            return  # oversized subnegotiation: give up, stay in char mode

    # -- low level ---------------------------------------------------------- #
    def _raw_byte_blocking(self) -> int | None:
        while True:
            b = self.ch.read_byte()
            if b is None:
                self._closed = True
                return None
            if b == -1:
                continue
            return b

    def _read_cooked_byte(self) -> int | None:
        """One byte with telnet IAC sequences transparently consumed."""
        while True:
            b = self._raw_byte_blocking()
            if b is None:
                return None
            if b == IAC and self.ch.is_network and self.cfg.telnet:
                self._handle_iac()
                continue
            return b

    # -- public ------------------------------------------------------------- #
    @property
    def closed(self) -> bool:
        return self._closed

    def write(self, data: bytes) -> None:
        if self.cfg.pace_cps <= 0:
            self.ch.write(data)
            return
        # Pace in small blocks so a flow-control-less Apple II keeps up.
        block = max(1, self.cfg.pace_cps // 10)
        delay = block / self.cfg.pace_cps
        for i in range(0, len(data), block):
            self.ch.write(data[i : i + block])
            time.sleep(delay)

    def write_text(self, text: str) -> None:
        self.write(text.replace("\n", self.cfg.newline).encode("ascii", "replace"))

    def write_line(self, text: str = "") -> None:
        self.write_text(text)
        self.write(self.cfg.newline.encode("ascii"))

    def poll_ctrl_c(self) -> bool:
        """Drain whatever is waiting on the channel and report whether a
        Ctrl-C (0x03) was in it. Called while a reply is generating - the
        native client sends a bare 0x03 to cancel the turn. Anything else
        arriving mid-generation is type-ahead we don't support, or modem
        chatter; either way it's discarded. Costs at most one read timeout
        (~0.2s) when the line is quiet."""
        seen = False
        while True:
            b = self.ch.read_byte()
            if b is None:
                self._closed = True
                return seen
            if b == -1:
                return seen
            if (b & 0x7F) == CTRL_C:
                seen = True

    def read_line(self, prompt: str = "") -> str | None:
        """Read one CR-terminated line. Returns None if the channel closed.

        A bare Ctrl-C returns the sentinel string '\\x03' so the caller can treat
        it as an interrupt; Ctrl-U clears the current line.
        """
        if prompt:
            self.write_text(prompt)
        buf: list[str] = []
        while True:
            b = self._read_cooked_byte()
            if b is None:
                return None
            if not buf and b == self._skip_eol:
                self._skip_eol = None  # paired CR/LF from a CRLF terminal
                continue
            self._skip_eol = None
            if b in (CR, LF):
                self._skip_eol = LF if b == CR else CR
                self.write(self.cfg.newline.encode("ascii"))
                return "".join(buf)
            if b in (BS, DEL):
                if buf:
                    buf.pop()
                    if self.cfg.echo:
                        self.write(b"\b \b")
                continue
            if b == CTRL_U:
                if self.cfg.echo:
                    self.write(b"\b \b" * len(buf))
                buf.clear()
                continue
            if b == CTRL_C:
                return "\x03"
            if b < 32:
                continue  # ignore other control chars
            if self.cfg.max_line and len(buf) >= self.cfg.max_line:
                continue  # line is over budget: drop printables until CR
            ch = chr(b & 0x7F)  # Apple II often sets the high bit; mask it off
            buf.append(ch)
            if self.cfg.echo:
                self.write(bytes([b & 0x7F]))
