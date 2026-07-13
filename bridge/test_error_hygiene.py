import backends


def test_code_backend_missing_binary_hides_path(capsys):
    be = backends.CodeBackend(cols=80, claude_bin="/definitely/not/here/claude")
    # FileNotFoundError path yields a generic, path-free message.
    out = "".join(be.stream("hi"))
    assert "not found" in out.lower()
    # The exact bogus path must not be reflected to the peer.
    assert "/definitely/not/here" not in out
    # ...but the detail does go to the console/stderr, for the operator.
    captured = capsys.readouterr()
    assert "/definitely/not/here" in captured.err
