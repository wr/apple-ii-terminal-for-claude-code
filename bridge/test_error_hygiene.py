import backends


def test_code_backend_bad_exit_hides_stderr(monkeypatch, capsys):
    be = backends.CodeBackend(cols=80, claude_bin="/definitely/not/here/claude")
    # FileNotFoundError path yields a generic, path-free message.
    out = "".join(be.stream("hi"))
    assert "not found" in out.lower()
    # The exact bogus path must not be reflected to the peer.
    assert "/definitely/not/here" not in out
