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
