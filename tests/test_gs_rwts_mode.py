from pathlib import Path


def test_gs_session_never_calls_dos_rwts_on_real_hardware_paths():
    source = Path("apple2gs/claude.s").read_text()
    session_open = source.split("session_start:", 1)[1].split("main:", 1)[0]
    turn_loop = source.split("main:", 1)[1].split("quit_to_menu:", 1)[0]
    token_receive = source.split("do_token:", 1)[1].split("cout:", 1)[0]

    assert "token_read" not in session_open
    assert "tok_valid" not in session_open
    assert "token_flush" not in turn_loop
    assert "token_pending" not in token_receive
    assert "jsr     RWTS" not in source
