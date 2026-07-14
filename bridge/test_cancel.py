"""Tests for W-528: real Ctrl-C cancellation + idle-connection timeout.

Plain assert-script (not pytest). Covers what's exercisable without a live
`claude` process or a real Apple II:

  * _kill_process_group takes down a whole process group (no orphaned child),
  * and escalates SIGTERM -> SIGKILL when the leader ignores SIGTERM,
  * CodeBackend.cancel routes through the group kill,
  * ChatBackend.cancel closes the in-flight stream (aborts a stalled turn),
  * _IdleGuard drops a silent peer, resets on bytes, and stops on disarm.
"""
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backends
import bridge


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal


def _wait_dead(pid: int, timeout: float = 3.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if not _alive(pid):
            return True
        time.sleep(0.02)
    return not _alive(pid)


# --------------------------------------------------------------------------- #
# _kill_process_group: whole-group kill, no orphans
# --------------------------------------------------------------------------- #
def test_kill_group_no_orphans() -> None:
    # A parent that forks a child, prints the child's PID, then sleeps. Both
    # live in the parent's process group (start_new_session gives the parent a
    # fresh one). Killing the group must take out the child too.
    parent_src = (
        "import subprocess, sys, time;"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(999)']);"
        "print(c.pid, flush=True);"
        "time.sleep(999)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", parent_src],
        stdout=subprocess.PIPE, text=True, start_new_session=True,
    )
    child_pid = int(proc.stdout.readline())
    assert _alive(proc.pid) and _alive(child_pid), "parent+child should be up"

    backends._kill_process_group(proc, grace=2.0)

    assert _wait_dead(proc.pid), "parent (claude -p stand-in) survived the kill"
    assert _wait_dead(child_pid), "CHILD orphaned - group kill missed it"
    print("PASS: _kill_process_group takes down the whole group (no orphans)")


def test_kill_group_escalates_to_sigkill() -> None:
    # A process that ignores SIGTERM and has no children: SIGTERM alone can't
    # stop it, so the helper must wait the grace and then SIGKILL.
    ign_src = (
        "import signal, time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "time.sleep(999)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", ign_src], start_new_session=True,
    )
    time.sleep(0.3)  # let it install the SIG_IGN handler
    assert _alive(proc.pid)

    grace = 0.5
    t0 = time.monotonic()
    backends._kill_process_group(proc, grace=grace)
    elapsed = time.monotonic() - t0

    assert _wait_dead(proc.pid), "SIGTERM-ignoring process was never SIGKILLed"
    assert elapsed >= grace, (
        f"returned in {elapsed:.2f}s (< grace {grace}s) - it did not wait out "
        "SIGTERM before escalating")
    print(f"PASS: SIGTERM ignored -> SIGKILL after {elapsed:.2f}s grace")


def test_kill_group_already_dead() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    backends._kill_process_group(proc)  # must not raise
    print("PASS: _kill_process_group no-ops on an already-dead process")


def test_codebackend_cancel_uses_group_kill() -> None:
    # Point a CodeBackend at a long-lived process-group leader and confirm its
    # cancel() tears the group down (proving cancel routes through the group
    # kill, not a lone terminate()).
    be = backends.CodeBackend(cols=80)
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(999)"],
        start_new_session=True,
    )
    be._proc = proc
    be.cancel()
    assert be._cancelled is True
    assert _wait_dead(proc.pid), "CodeBackend.cancel did not kill the turn"
    print("PASS: CodeBackend.cancel kills the process group")


def test_kill_group_when_leader_exits_but_child_ignores_term() -> None:
    child_src = (
        "import signal,time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "print('ready', flush=True);"
        "time.sleep(999)"
    )
    parent_src = (
        "import subprocess,sys,time;"
        "c=subprocess.Popen([sys.executable,'-c',sys.argv[1]]);"
        "print(c.pid, flush=True);"
        "time.sleep(999)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", parent_src, child_src],
        stdout=subprocess.PIPE, text=True, start_new_session=True,
    )
    assert proc.stdout is not None
    child_pid = int(proc.stdout.readline())
    time.sleep(0.3)
    backends._kill_process_group(proc, grace=0.2)
    assert _wait_dead(proc.pid), "group leader survived"
    assert _wait_dead(child_pid), "SIGTERM-ignoring child survived leader exit"


def test_codebackend_cancel_during_process_publication(monkeypatch) -> None:
    real_popen = backends.subprocess.Popen
    spawned = threading.Event()
    publish = threading.Event()
    holder = {}

    def delayed_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        holder["proc"] = proc
        spawned.set()
        assert publish.wait(2)
        return proc

    be = backends.CodeBackend(cols=80, claude_bin=sys.executable)
    be._build_cmd = lambda _text: [
        sys.executable, "-c", "import time; time.sleep(999)"
    ]
    monkeypatch.setattr(backends.subprocess, "Popen", delayed_popen)
    worker = threading.Thread(target=lambda: list(be.stream("hello")), daemon=True)
    worker.start()
    assert spawned.wait(2)
    be.cancel()
    publish.set()
    worker.join(3)
    proc = holder["proc"]
    assert not worker.is_alive(), "stream stayed blocked after startup cancel"
    assert _wait_dead(proc.pid), "process published after cancel survived"


# --------------------------------------------------------------------------- #
# ChatBackend.cancel: abort the stream even mid-stall
# --------------------------------------------------------------------------- #
def test_chatbackend_cancel_closes_stream() -> None:
    # Build the backend without touching the anthropic SDK / a live client.
    be = backends.ChatBackend.__new__(backends.ChatBackend)
    be._cancel = False
    be._state_lock = threading.Lock()
    be._cancel_event = threading.Event()
    closed = []

    class FakeStream:
        def close(self):
            closed.append(True)

    be._stream = FakeStream()
    be.cancel()
    assert be._cancel is True, "cancel must still set the flag"
    assert closed == [True], "cancel must close the in-flight stream"

    # With no active stream it must be a harmless no-op.
    be._stream = None
    be.cancel()
    print("PASS: ChatBackend.cancel closes the stream (and no-ops when idle)")


def test_chatbackend_cancel_during_stream_publication() -> None:
    entered = threading.Event()
    publish = threading.Event()
    closed = threading.Event()

    class BlockingText:
        def __iter__(self):
            closed.wait(3)
            return iter(())

    class FakeStream:
        text_stream = BlockingText()
        def close(self):
            closed.set()
        def get_final_message(self):
            raise AssertionError("cancelled stream must not request a final message")

    class StreamContext:
        def __enter__(self):
            entered.set()
            assert publish.wait(2)
            return FakeStream()
        def __exit__(self, *_args):
            return False

    class Messages:
        def stream(self, **_kwargs):
            return StreamContext()

    be = backends.ChatBackend.__new__(backends.ChatBackend)
    be._client = type("Client", (), {"messages": Messages()})()
    be._model = "test"
    be._effort = "low"
    be._max_tokens = 32
    be._system = "test"
    be._messages = []
    be._cancel = False
    be._stream = None
    be._state_lock = threading.Lock()
    be._cancel_event = threading.Event()

    worker = threading.Thread(target=lambda: list(be.stream("hello")), daemon=True)
    worker.start()
    assert entered.wait(2)
    be.cancel()
    publish.set()
    worker.join(3)
    assert closed.is_set(), "stream published after cancel was not closed"
    assert not worker.is_alive(), "chat stream stayed blocked after startup cancel"


# --------------------------------------------------------------------------- #
# _IdleGuard: drop a silent peer, but never a slow-typing one
# --------------------------------------------------------------------------- #
class _FakeChannel:
    is_network = True
    peer = "test-peer"

    def __init__(self):
        self.closed = False
        self._feed = []  # queued real bytes to hand back

    def feed(self, b: int):
        self._feed.append(b)

    def read_byte(self):
        if self.closed:
            return None
        if self._feed:
            return self._feed.pop(0)
        time.sleep(0.05)
        return -1  # nothing available (a read timeout)

    def write(self, data):
        pass

    def close(self):
        self.closed = True


def test_idle_guard_drops_silent_peer() -> None:
    ch = _FakeChannel()
    guard = bridge._IdleGuard(ch, timeout=0.3)
    # A reader that just keeps polling, like Terminal.read_line does.
    end = time.time() + 2.0
    while time.time() < end and not ch.closed:
        if guard.read_byte() is None:
            break
    assert ch.closed, "idle peer was not dropped"
    guard.disarm()
    print("PASS: _IdleGuard drops a peer that stays silent past the timeout")


def test_idle_guard_resets_on_bytes() -> None:
    ch = _FakeChannel()
    guard = bridge._IdleGuard(ch, timeout=0.5)
    # Deliver a byte every 0.2s for ~1.2s (each shorter than the 0.5s timeout).
    t0 = time.time()
    while time.time() - t0 < 1.2:
        ch.feed(ord("A"))
        assert guard.read_byte() == ord("A")
        time.sleep(0.2)
    assert not ch.closed, "steady slow typing was wrongly dropped"
    guard.disarm()
    print("PASS: _IdleGuard resets on every byte (slow typing survives)")


def test_idle_guard_disarm_stops_watchdog() -> None:
    ch = _FakeChannel()
    guard = bridge._IdleGuard(ch, timeout=0.3)
    guard.disarm()
    time.sleep(0.8)  # well past the timeout
    assert not ch.closed, "disarmed guard still dropped the peer"
    print("PASS: _IdleGuard.disarm stops the watchdog (live session kept)")


if __name__ == "__main__":
    test_kill_group_no_orphans()
    test_kill_group_escalates_to_sigkill()
    test_kill_group_already_dead()
    test_codebackend_cancel_uses_group_kill()
    test_chatbackend_cancel_closes_stream()
    test_idle_guard_drops_silent_peer()
    test_idle_guard_resets_on_bytes()
    test_idle_guard_disarm_stops_watchdog()
    print("ALL PASS")
