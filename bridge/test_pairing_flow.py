import time
import types
import bridge as bridge_module
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
    pm = PairingManager("ABC123", store_path=str(tmp_path / "p.json"))
    tok = pm.issue_token("10.0.0.5")
    term = _FakeTerm([tok])
    assert require_pairing(term, _args(), pm) == "token"


def test_first_run_code_issues_token_frame(tmp_path):
    pm = PairingManager("ABC123", store_path=str(tmp_path / "p.json"))
    term = _FakeTerm(["", "ABC123"])  # blank line (prompt), then the code
    assert require_pairing(term, _args(), pm) == "code"
    # A CMD_TOKEN frame (0x05 + 32 chars + CR) was written to the client.
    assert bytes(CMD_TOKEN) in term.written
    idx = term.written.index(CMD_TOKEN[0])
    frame = term.written[idx + 1: idx + 1 + 32]
    assert len(frame) == 32
    assert pm.check_token(frame.decode("ascii")) is True


def test_wrong_token_falls_through_to_code(tmp_path):
    pm = PairingManager("ABC123", store_path=str(tmp_path / "p.json"))
    term = _FakeTerm(["ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ", "ABC123"])
    assert require_pairing(term, _args(), pm)


def test_per_ip_code_shown_only_when_a_device_needs_it(tmp_path):
    # A paired device presents its token and never triggers a code, so its IP
    # never enters the per-IP map. An unpaired device does.
    pm = PairingManager(store_path=str(tmp_path / "p.json"))  # per-IP (unpinned)
    tok = pm.issue_token("10.0.0.5")
    term = _FakeTerm([tok])
    term.ch.peer = "10.0.0.5"
    assert require_pairing(term, _args(), pm) == "token"
    assert "10.0.0.5" not in pm._codes           # paired device: no code minted

    # A different, unpaired device gets a code minted for its IP.
    code = pm.code_for("10.0.0.9")
    term2 = _FakeTerm(["", code])
    term2.ch.peer = "10.0.0.9"
    assert require_pairing(term2, _args(), pm) == "code"


def test_code_is_consumed_after_pairing(tmp_path):
    # A generated code is single-use: once it pairs one device, the same code
    # can't enroll another from that IP - the next one is fresh.
    pm = PairingManager(store_path=str(tmp_path / "p.json"))  # per-IP
    code = pm.code_for("10.0.0.7")
    term = _FakeTerm(["", code])
    term.ch.peer = "10.0.0.7"
    assert require_pairing(term, _args(), pm) == "code"
    assert pm.code_for("10.0.0.7") != code   # consumed; a new code was minted


def test_raw_telnet_code_is_consumed_after_pairing(tmp_path):
    pm = PairingManager(store_path=str(tmp_path / "p.json"))
    code = pm.code_for("10.0.0.8")
    term = _FakeTerm([code], peer="10.0.0.8")

    assert require_pairing(term, _args(app=False), pm) == "token"
    assert bytes(CMD_TOKEN) not in term.written
    assert pm.code_for("10.0.0.8") != code


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


def test_direct_app_dial_gets_connect_and_ato_is_swallowed():
    term = _FakeTerm([])
    assert hasattr(bridge_module, "_ack_direct_dial")
    ack_direct_dial = bridge_module._ack_direct_dial

    assert ack_direct_dial(term, "ATDS=0", app=True) is True
    assert term.lines_out == ["CONNECT"]
    assert ack_direct_dial(term, "ATO", app=True) is True
    assert term.lines_out == ["CONNECT"]


def test_run_app_session_swallows_direct_dial_commands():
    term = _FakeTerm(["ATDS=0", "ATO", "hello", None])
    backend = _FakeBackend()

    run_app_session(term, _args(cols=80), backend, None, "code")

    assert term.lines_out[0] == "CONNECT"
    assert term.lines_out.count("CONNECT") == 1
    assert backend.prompts == ["hello"]


def test_direct_dial_connect_precedes_blocking_backend_prime():
    events = []

    class _OrderedTerm(_FakeTerm):
        def write_line(self, text=""):
            events.append(("write_line", text))
            super().write_line(text)

    class _BlockingPrimeBackend(_FakeBackend):
        def prime(self):
            # Model a backend probe that takes longer than the native dial
            # window. CONNECT must already be on the transport when it starts.
            events.append(("prime", None))
            assert events[0] == ("write_line", "CONNECT")

    term = _OrderedTerm(["ATDS=0", None])
    run_app_session(term, _args(cols=80), _BlockingPrimeBackend(), None, "code")

    assert events[:2] == [("write_line", "CONNECT"), ("prime", None)]


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
    pm = PairingManager("ABC123", store_path=str(tmp_path / "p.json"))
    stale = gen_token()  # a token pm has never issued
    term = _FakeTerm([stale, "ABC123"])  # stale token, then the real code
    assert require_pairing(term, _args(), pm)
    assert pm._fails.get("10.0.0.5") is None            # no strike burned
    assert 0x0E in term.written                          # LOCKED header pushed
    assert bytes(CMD_TOKEN) in term.written              # fresh token issued


def test_only_first_stale_token_is_exempt_from_guess_cap(tmp_path):
    pm = PairingManager("ABC123", store_path=str(tmp_path / "p.json"))
    pm.SLEEP_CAP = 0
    stale = gen_token()
    lines = [stale] + [gen_token() for _ in range(pm.MAX_TRIES)] + ["ABC123"]
    term = _FakeTerm(lines)

    assert require_pairing(term, _args(), pm) is False
    assert pm._fails["10.0.0.5"][0] == pm.MAX_TRIES
    assert not pm.devices


def test_stale_token_exemption_does_not_reset_on_reconnect(tmp_path):
    pm = PairingManager("ABC123", store_path=str(tmp_path / "p.json"))
    pm.SLEEP_CAP = 0
    peer = "10.0.0.5"

    assert require_pairing(_FakeTerm([gen_token()], peer), _args(), pm) is False
    assert pm._fails.get(peer) is None

    for _ in range(pm.MAX_TRIES):
        assert require_pairing(
            _FakeTerm([gen_token()], peer), _args(), pm
        ) is False

    term = _FakeTerm(["ABC123"], peer)
    assert require_pairing(term, _args(), pm) is False
    assert pm._fails[peer][0] == pm.MAX_TRIES


def test_token_shaped_pinned_code_is_checked_before_stale_token(tmp_path):
    code = gen_token()
    pm = PairingManager(code, store_path=str(tmp_path / "p.json"))
    term = _FakeTerm([code])

    assert require_pairing(term, _args(app=False), pm) == "token"
    assert pm._fails.get("10.0.0.5") is None


def test_code_pairing_defers_eot_to_after_header(tmp_path):
    # Bug E: require_pairing must send the CMD_TOKEN frame WITHOUT a trailing
    # EOT on the code path (an EOT here would end the client's recv_reply before
    # the version-string header). It returns "code" so run_app_session knows to
    # terminate later.
    pm = PairingManager("ABC123", store_path=str(tmp_path / "p.json"))
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
