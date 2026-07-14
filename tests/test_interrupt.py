"""Integration test for W-516: Ctrl-C interrupt + /exit in run_app_session.

Fakes the transport and the backend; runs the real Terminal + run_app_session.
"""
import os, sys, threading, time, queue

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "bridge"))

import bridge
from terminal import Terminal, TermConfig


class FakeChannel:
    is_network = False
    peer = None

    def __init__(self):
        self.rx = queue.Queue()   # bytes the "Apple II" sends us
        self.tx = bytearray()     # bytes we send the "Apple II"
        self.tx_lock = threading.Lock()
        self.closed = False

    def feed(self, data: bytes):
        for b in data:
            self.rx.put(b)

    def read_byte(self):
        if self.closed:
            return None
        try:
            return self.rx.get(timeout=0.05)
        except queue.Empty:
            return -1

    def write(self, data: bytes):
        with self.tx_lock:
            self.tx.extend(data)

    def close(self):
        self.closed = True


class SlowBackend:
    """Streams forever until cancelled - a stand-in for a long claude turn."""
    name = "code"

    def __init__(self):
        self.cancelled = False

    def prime(self): pass
    def header(self): return ("Claude Code vTEST", "Opus test", "~/x")
    def footer(self): return None if self.cancelled else "Worked for 1s"
    def reset(self): pass

    def cancel(self):
        self.cancelled = True

    def stream(self, user):
        yield "partial text before the interrupt. "
        for _ in range(200):           # ~20s unless cancelled
            if self.cancelled:
                return
            time.sleep(0.1)
        yield "SHOULD NEVER ARRIVE"


class BusyBackend(SlowBackend):
    def __init__(self):
        super().__init__()
        self.cancel_event = threading.Event()
        self.stop_event = threading.Event()

    def cancel(self):
        self.cancelled = True
        self.cancel_event.set()

    def stream(self, _user):
        while not self.cancel_event.is_set() and not self.stop_event.is_set():
            yield "x"
            time.sleep(0.01)


class Args:
    cols = 80
    app = True


def test_ctrl_c_is_polled_while_chunks_are_continuous():
    ch = FakeChannel()
    term = Terminal(ch, TermConfig(width=80, echo=False, telnet=False))
    backend = BusyBackend()
    worker = threading.Thread(
        target=bridge.run_app_session,
        args=(term, Args(), backend, None, "code"),
        daemon=True,
    )
    worker.start()
    time.sleep(0.2)
    ch.feed(b"hello\r")
    time.sleep(0.2)
    ch.feed(b"\x03")
    try:
        assert backend.cancel_event.wait(1), (
            "continuous chunks starved Ctrl-C polling")
    finally:
        backend.stop_event.set()
        ch.feed(b"/exit\r")
        worker.join(3)


def test_disconnect_cancels_and_joins_reply_worker():
    ch = FakeChannel()
    term = Terminal(ch, TermConfig(width=80, echo=False, telnet=False))
    backend = BusyBackend()
    session = threading.Thread(
        target=bridge.run_app_session,
        args=(term, Args(), backend, None, "code"),
        daemon=True,
    )
    session.start()
    ch.feed(b"hello\r")
    time.sleep(0.2)
    ch.close()
    session.join(3)
    assert not session.is_alive(), "session survived channel close"
    assert backend.cancel_event.is_set(), "disconnect did not cancel backend"


def test_host_interrupt_cancels_and_joins_reply_worker():
    ch = FakeChannel()
    ch.feed(b"hello\r")
    term = Terminal(ch, TermConfig(width=80, echo=False, telnet=False))
    backend = SlowBackend()

    def host_interrupt():
        raise KeyboardInterrupt

    term.poll_ctrl_c = host_interrupt
    with pytest.raises(KeyboardInterrupt):
        bridge.run_app_session(term, Args(), backend, None, "code")
    assert backend.cancelled, "host Ctrl-C left backend work running"


def test_non_app_interrupt_cancels_synchronous_stream(monkeypatch):
    class InterruptingBackend(SlowBackend):
        def stream(self, _user):
            yield "partial text"
            raise KeyboardInterrupt

    class PlainArgs:
        telnet = False
        idle_timeout = 0
        backend = "code"
        app = False
        cols = 80

    ch = FakeChannel()
    ch.feed(b"hello\r")
    term = Terminal(ch, TermConfig(width=80, echo=False, telnet=False))
    backend = InterruptingBackend()
    monkeypatch.setattr(bridge, "make_backend", lambda *_args: backend)

    with pytest.raises(KeyboardInterrupt):
        bridge.run_session(term, PlainArgs())
    assert backend.cancelled, "non-app unwind left backend work running"


def run():
    ch = FakeChannel()
    term = Terminal(ch, TermConfig(width=80, echo=False, telnet=False))
    backend = SlowBackend()

    t = threading.Thread(
        target=bridge.run_app_session,
        args=(term, Args(), backend, None, "code"),
        daemon=True,
    )
    t.start()
    time.sleep(0.3)          # boot header goes out

    # --- turn 1: a prompt, then Ctrl-C mid-generation -----------------
    ch.feed(b"hello\r")
    time.sleep(1.0)          # generation under way
    ch.feed(b"\x03")         # the client's Ctrl-C
    deadline = time.time() + 5
    while time.time() < deadline and not backend.cancelled:
        time.sleep(0.05)
    assert backend.cancelled, "backend.cancel() was never called"
    time.sleep(1.0)          # let the reply flush
    out = bytes(ch.tx)
    assert b"Interrupted by user" in out, f"no interrupt marker in {out!r}"
    assert b"partial text before the interrupt" in out, "partial reply lost"
    assert b"SHOULD NEVER ARRIVE" not in out, "stream was not stopped"
    assert b"Worked for" not in out, "footer should be skipped on interrupt"
    eot_at = out.rindex(b"\x04")
    assert eot_at > out.index(b"Interrupted"), "EOT must close the reply"
    print("PASS: Ctrl-C mid-generation -> cancel + partial + marker + EOT")

    # --- turn 2: /exit behaves exactly like /quit ----------------------
    before = len(ch.tx)
    ch.feed(b"/exit\r")
    t.join(timeout=5)
    assert not t.is_alive(), "session did not end on /exit"
    tail = bytes(ch.tx[before:])
    assert b"Goodbye." in tail, f"no goodbye: {tail!r}"
    assert b"\x03" in tail, "no CMD_QUIT byte"
    assert tail.rindex(b"\x04") > tail.index(b"\x03"), "CMD_QUIT then EOT"
    print("PASS: /exit -> Goodbye + CMD_QUIT + EOT, session closed")


if __name__ == "__main__":
    test_ctrl_c_is_polled_while_chunks_are_continuous()
    test_disconnect_cancels_and_joins_reply_worker()
    test_host_interrupt_cancels_and_joins_reply_worker()
    run()
    print("ALL PASS")
