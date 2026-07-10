"""Raw byte plumbing between the Apple II and the bridge.

Two ways in, same interface:

  * SerialTransport - a USB-serial cable into the IIc/IIgs serial port.
  * TCPTransport    - a listening socket for a WiFi modem or telnet client.

A transport hands out `Channel` objects (one per connection). A Channel only
knows how to move bytes; line editing, echo, and telnet live in terminal.py.

Channel.read_byte() return values:
    0..255  a real byte
    -1      nothing available yet (timeout) - caller should keep waiting
    None    the connection is gone
"""

from __future__ import annotations

import socket
import time
from typing import Iterator, Optional


class Channel:
    is_network = False

    def read_byte(self) -> Optional[int]:
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


# --------------------------------------------------------------------------- #
# Serial
# --------------------------------------------------------------------------- #
class _SerialChannel(Channel):
    is_network = False

    def __init__(self, ser) -> None:
        self._ser = ser

    def read_byte(self) -> Optional[int]:
        try:
            b = self._ser.read(1)  # honours the port's read timeout
        except Exception:
            return None
        if not b:
            return -1
        return b[0]

    def write(self, data: bytes) -> None:
        self._ser.write(data)
        self._ser.flush()

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


class SerialTransport:
    """Wraps a single serial port. Yields exactly one long-lived channel."""

    def __init__(self, port: str, baud: int, rtscts: bool, xonxoff: bool) -> None:
        self.port = port
        self.baud = baud
        self.rtscts = rtscts
        self.xonxoff = xonxoff

    def describe(self) -> str:
        flow = "RTS/CTS" if self.rtscts else ("XON/XOFF" if self.xonxoff else "none")
        return f"serial {self.port} @ {self.baud} 8N1, flow={flow}"

    def channels(self) -> Iterator[Channel]:
        import serial  # imported lazily so TCP-only users don't need pyserial

        ser = serial.Serial(
            port=self.port,
            baudrate=self.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.2,
            rtscts=self.rtscts,
            xonxoff=self.xonxoff,
        )
        try:
            yield _SerialChannel(ser)
        finally:
            ser.close()


# --------------------------------------------------------------------------- #
# TCP (telnet / WiFi modem)
# --------------------------------------------------------------------------- #
class _TCPChannel(Channel):
    is_network = True

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._sock.settimeout(0.2)

    def read_byte(self) -> Optional[int]:
        try:
            b = self._sock.recv(1)
        except socket.timeout:
            return -1
        except OSError:
            return None
        if b == b"":
            return None  # peer closed
        return b[0]

    def write(self, data: bytes) -> None:
        try:
            self._sock.sendall(data)
        except OSError:
            pass

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class TCPTransport:
    """Listens for one client at a time. Good for a WiFi modem or `telnet`."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._srv: Optional[socket.socket] = None

    def describe(self) -> str:
        shown = self.host or "0.0.0.0"
        return f"tcp/telnet listening on {shown}:{self.port}"

    def channels(self) -> Iterator[Channel]:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(1)
        self._srv = srv
        try:
            while True:
                conn, addr = srv.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                yield _TCPChannel(conn)
        finally:
            srv.close()


class TCPClientTransport:
    """Dials OUT to a listening host. Use for KEGS (Slot -> Incoming, port 6502),
    or any telnet host that expects you to connect to it."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    def describe(self) -> str:
        return f"tcp client -> {self.host}:{self.port}"

    def channels(self) -> Iterator[Channel]:
        waiting = False
        while True:
            try:
                conn = socket.create_connection((self.host, self.port), timeout=5)
            except (ConnectionRefusedError, socket.timeout, OSError):
                if not waiting:
                    print(f"[bridge] waiting for {self.host}:{self.port} to accept...")
                    waiting = True
                time.sleep(1.0)
                continue
            waiting = False
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            yield _TCPChannel(conn)
            # Session ended; loop and reconnect (KEGS goes back to listening).
