import time
import types
from bridge import PairingManager, require_pairing, CMD_TOKEN


class _FakeCh:
    def __init__(self, peer="10.0.0.5"):
        self.peer = peer


class _FakeTerm:
    """Scriptable terminal: yields prepared lines, records raw writes."""
    def __init__(self, lines, peer="10.0.0.5"):
        self._lines = list(lines)
        self.ch = _FakeCh(peer)
        self.closed = False
        self.written = bytearray()
        self.lines_out = []

    def read_line(self, prompt="", deadline=None):
        if self._lines:
            return self._lines.pop(0)
        self.closed = True
        return None

    def write(self, data: bytes):
        self.written.extend(data)

    def write_line(self, text=""):
        self.lines_out.append(text)


def _args(**kw):
    d = dict(app=True, idle_timeout=60)
    d.update(kw)
    return types.SimpleNamespace(**d)


def test_valid_token_first_line_pairs_without_code(tmp_path):
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(tmp_path / "p.json"))
    tok = pm.issue_token("10.0.0.5")
    term = _FakeTerm([tok])
    assert require_pairing(term, _args(), pm) is True


def test_first_run_code_issues_token_frame(tmp_path):
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(tmp_path / "p.json"))
    term = _FakeTerm(["", "ABC123"])  # blank line (prompt), then the code
    assert require_pairing(term, _args(), pm) is True
    # A CMD_TOKEN frame (0x05 + 32 chars + CR) was written to the client.
    assert bytes(CMD_TOKEN) in term.written
    idx = term.written.index(CMD_TOKEN[0])
    frame = term.written[idx + 1: idx + 1 + 32]
    assert len(frame) == 32
    assert pm.check_token(frame.decode("ascii")) is True


def test_wrong_token_falls_through_to_code(tmp_path):
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(tmp_path / "p.json"))
    term = _FakeTerm(["ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ", "ABC123"])
    assert require_pairing(term, _args(), pm) is True


def test_valid_token_pairs_after_window_closes(tmp_path):
    # A previously-paired device presenting its stored token must still get
    # in after the pairing window has expired - the window only gates NEW
    # (code-based) pairing, never token presentation.
    pm = PairingManager("ABC123", ttl_secs=60, store_path=str(tmp_path / "p.json"))
    tok = pm.issue_token("10.0.0.5")
    pm.born = time.monotonic() - 3600   # force the window closed
    assert pm.window_open() is False
    term = _FakeTerm([tok])
    assert require_pairing(term, _args(), pm) is True
