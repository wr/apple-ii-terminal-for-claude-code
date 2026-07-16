from pathlib import Path


def test_gs_buffers_the_complete_header_before_drawing_it():
    source = Path("apple2gs/claude.s").read_text()
    header = source.split("do_header:", 1)[1].split("check_incoming:", 1)[0]
    reader = header.split("hdr_readline:", 1)[1].split("check_incoming:", 1)[0]

    assert "HEADER_LINES = 3" in source
    assert "HDRBUF" in source
    assert header.index("jsr     hdr_capture") < header.index("rep     #$20            ; save cursor")
    assert "getbyte" not in reader
    assert "inc     hdr_pos\n        lda     hdr_pos\n        tay" in reader


def test_gs_header_capture_drains_each_complete_cr_terminated_line():
    source = Path("apple2gs/claude.s").read_text()
    capture = source.split("hdr_capture:", 1)[1].split("hdr_advance:", 1)[0]

    assert "cmp     #$0D\n        beq     hc_done" in capture
    assert "bcs     hc_byte" in capture
    assert "lda     #HEADER_LINES\n        sta     hdr_row" in capture


def test_gs_glyph_drawing_keeps_draining_the_scc():
    source = Path("apple2gs/claude.s").read_text()
    putchar = source.split("putchar:", 1)[1].split("draw_bullet:", 1)[0]

    assert "pc_row:\n        jsr     rb_poll" in putchar


def test_gs_spinner_can_force_local_recovery_after_remote_cancel():
    # A dead link must not trap the GS client in the spinner: the first
    # Esc/Ctrl-C asks the bridge to stop, and a second key, DCD loss, or a
    # bounded timeout returns locally to the menu (matches the 8-bit + Codex).
    source = Path("apple2gs/claude.s").read_text()
    spinner = source.split("spinner:", 1)[1].split("recv_reply:", 1)[0]

    assert "second Esc/Ctrl-C forces a local return" in spinner
    assert "jsr     check_carrier" in spinner
    assert "spin_wait" in spinner
    assert "lda     #EOT" in spinner
    assert "sta     quitflag" in spinner
