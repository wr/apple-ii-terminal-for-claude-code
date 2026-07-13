import time
import types
from bridge import (PairingManager, require_pairing, CMD_TOKEN, EOT,
                     run_app_session, _looks_like_token, gen_token, _TOKEN_LEN)


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

    def poll_ctrl_c(self) -> bool:
        return False


class _FakeBackend:
    """Minimal stand-in for backends.CodeBackend/ChatBackend: records every
    prompt it's asked to stream, so a test can assert a stale token never
    reached it."""
    def __init__(self):
        self.prompts = []

    def prime(self):
        pass

    def header(self):
        return None  # send_header() no-ops

    def stream(self, user):
        self.prompts.append(user)
        return iter(["ok"])

    def footer(self):
        return ""

    def cancel(self):
        pass


def _args(**kw):
    d = dict(app=True, idle_timeout=60)
    d.update(kw)
    return types.SimpleNamespace(**d)


def test_valid_token_first_line_pairs_without_code(tmp_path):
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(tmp_path / "p.json"))
    tok = pm.issue_token("10.0.0.5")
    term = _FakeTerm([tok])
    assert require_pairing(term, _args(), pm) == "token"


def test_first_run_code_issues_token_frame(tmp_path):
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(tmp_path / "p.json"))
    term = _FakeTerm(["", "ABC123"])  # blank line (prompt), then the code
    assert require_pairing(term, _args(), pm) == "code"
    # A CMD_TOKEN frame (0x05 + 32 chars + CR) was written to the client.
    assert bytes(CMD_TOKEN) in term.written
    idx = term.written.index(CMD_TOKEN[0])
    frame = term.written[idx + 1: idx + 1 + 32]
    assert len(frame) == 32
    assert pm.check_token(frame.decode("ascii")) is True


def test_wrong_token_falls_through_to_code(tmp_path):
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(tmp_path / "p.json"))
    term = _FakeTerm(["ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ", "ABC123"])
    assert require_pairing(term, _args(), pm)


def test_valid_token_pairs_after_window_closes(tmp_path):
    # A previously-paired device presenting its stored token must still get
    # in after the pairing window has expired - the window only gates NEW
    # (code-based) pairing, never token presentation.
    pm = PairingManager("ABC123", ttl_secs=60, store_path=str(tmp_path / "p.json"))
    tok = pm.issue_token("10.0.0.5")
    pm.born = time.monotonic() - 3600   # force the window closed
    assert pm.window_open() is False
    term = _FakeTerm([tok])
    assert require_pairing(term, _args(), pm)


def test_looks_like_token_shape():
    assert _looks_like_token(gen_token()) is True
    assert _looks_like_token("hello") is False
    assert _looks_like_token("a" * _TOKEN_LEN) is False   # lowercase not in alphabet
    assert _looks_like_token("ABCDEFGHJKMNPQRSTUVWXYZ23456789") is False  # 30 chars, wrong len


def test_run_app_session_swallows_stale_token_on_ungated_transport():
    # A client whose disk holds a token from an earlier --telnet pairing
    # reconnects through an ungated transport (--connect/--serial/--no-pair),
    # where require_pairing never runs. Its auto-sent token line must be
    # swallowed as the FIRST line, not forwarded to the backend as a prompt.
    tok = gen_token()
    term = _FakeTerm([tok, "hello", None])
    backend = _FakeBackend()
    args = _args(cols=80)
    run_app_session(term, args, backend, None, "code")
    assert backend.prompts == ["hello"], (
        f"stale token leaked through to the backend: {backend.prompts!r}")


def test_run_app_session_swallows_token_on_live_reconnect():
    # Bug C: the WiModem keeps the TCP link up across a client Ctrl-C -> menu
    # -> Connect, so the bridge stays mid-session (fresh is already False)
    # while the client re-runs session_start and auto-sends its stored token.
    # That token line must be swallowed (and the header re-sent, since the
    # client cleared its screen) - never forwarded to Claude as a prompt.
    tok = gen_token()
    term = _FakeTerm(["hello", tok, "world", None])
    backend = _FakeBackend()
    args = _args(cols=80)
    run_app_session(term, args, backend, None, "code")
    assert backend.prompts == ["hello", "world"], (
        f"a reconnect token leaked to the backend: {backend.prompts!r}")
    # the swallow path writes an EOT so the reconnected client isn't left waiting
    assert term.written.count(EOT[0]) >= 1


def test_stale_token_prompts_for_code_without_strike(tmp_path):
    # Bug D: after --clear-paired the client still auto-sends its old token as
    # the first line. The bridge doesn't recognize it - but must NOT count it
    # as a wrong-code strike (the idle client can't see plain text); it must
    # push the LOCKED header prompt so the user can type the code.
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(tmp_path / "p.json"))
    stale = gen_token()  # a token pm has never issued
    term = _FakeTerm([stale, "ABC123"])  # stale token, then the real code
    assert require_pairing(term, _args(), pm)
    assert pm._fails.get("10.0.0.5") is None            # no strike burned
    assert 0x0E in term.written                          # LOCKED header pushed
    assert bytes(CMD_TOKEN) in term.written              # fresh token issued


def test_code_pairing_defers_eot_to_after_header(tmp_path):
    # Bug E: require_pairing must send the CMD_TOKEN frame WITHOUT a trailing
    # EOT on the code path (an EOT here would end the client's recv_reply before
    # the version-string header). It returns "code" so run_app_session knows to
    # terminate later.
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(tmp_path / "p.json"))
    term = _FakeTerm(["", "ABC123"])
    assert require_pairing(term, _args(), pm) == "code"
    assert bytes(CMD_TOKEN) in term.written
    idx = term.written.index(CMD_TOKEN[0])
    assert EOT[0] not in term.written[idx:]   # no terminating EOT in require_pairing


def test_run_app_session_code_pairing_sends_header_before_eot():
    # run_app_session must emit the header frame, THEN the terminating EOT, when
    # pair_via == "code" - so the client renders the version string before its
    # deferred token write goes deaf.
    class _BE(_FakeBackend):
        def header(self):
            return ("Claude Code v1", "Opus", "~/x")
    term = _FakeTerm([None])
    run_app_session(term, _args(cols=80), _BE(), None, "code", pair_via="code")
    w = bytes(term.written)
    assert 0x0E in w                       # header frame written
    assert EOT[0] in w                     # terminated
    assert w.index(0x0E) < w.index(EOT[0]) # header BEFORE the terminating EOT
    assert any("Paired" in ln for ln in term.lines_out)  # explicit confirmation text
