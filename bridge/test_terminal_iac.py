import time

from terminal import Terminal, TermConfig
from transports import Channel


class _ScriptChannel(Channel):
    """Feeds a fixed byte script, then reports the connection gone (None)."""
    is_network = True

    def __init__(self, script: bytes):
        self._bytes = list(script)
        self.written = bytearray()

    def read_byte(self):
        if self._bytes:
            return self._bytes.pop(0)
        return None  # peer gone

    def write(self, data: bytes) -> None:
        self.written.extend(data)


def test_partial_iac_do_does_not_raise():
    # IAC DO (255, 253) then the socket dies before the option byte arrives.
    ch = _ScriptChannel(bytes([255, 253]))
    term = Terminal(ch, TermConfig(telnet=True))
    # read_line must return None (closed), not raise TypeError.
    assert term.read_line() is None


class _TrickleChannel(Channel):
    """Always 'timeout' (-1): a live peer that sends no completable line."""
    is_network = True

    def read_byte(self):
        return -1

    def write(self, data: bytes) -> None:
        pass


def test_read_line_honors_deadline():
    term = Terminal(_TrickleChannel(), TermConfig())
    t0 = time.monotonic()
    result = term.read_line(deadline=t0 + 0.3)
    assert result is None
    assert time.monotonic() - t0 < 2.0  # returned promptly, didn't hang


class _IacThenSilentChannel(Channel):
    """Sends one IAC byte, then 'times out' (-1) forever without closing.

    Models a peer that starts a telnet negotiation and then goes quiet
    mid-sequence: _handle_iac's internal reads must honor the deadline
    passed down from read_line, not block on it forever.
    """
    is_network = True

    def __init__(self):
        self._sent_iac = False

    def read_byte(self):
        if not self._sent_iac:
            self._sent_iac = True
            return 255  # IAC
        return -1  # timeout tick, peer never closes

    def write(self, data: bytes) -> None:
        pass


def test_handle_iac_honors_deadline():
    # Before the fix, _handle_iac's internal _raw_byte_blocking() calls had
    # no deadline, so a peer that sends IAC then goes silent hung read_line
    # forever (well past its deadline).
    term = Terminal(_IacThenSilentChannel(), TermConfig(telnet=True))
    t0 = time.monotonic()
    result = term.read_line(deadline=t0 + 0.3)
    assert result is None
    assert time.monotonic() - t0 < 2.0  # returned promptly, didn't hang


def test_poll_ctrl_c_is_bounded_under_flood():
    class _Flood(Channel):
        is_network = True
        def read_byte(self): return 0x41  # 'A' forever, never a timeout
        def write(self, d): pass
    term = Terminal(_Flood(), TermConfig())
    # Must return (False) rather than loop forever on an endless byte stream.
    assert term.poll_ctrl_c() is False
