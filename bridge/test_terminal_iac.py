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
