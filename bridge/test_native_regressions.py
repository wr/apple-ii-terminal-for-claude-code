"""Source and behavior contracts for native-client metal regressions.

These checks deliberately avoid an emulator: they pin the small assembly
shapes that keep the 6551 drained, bound dead-link cancellation, and keep the
elapsed clock inside its displayable range. The pure models cover the state
transitions that are awkward to exercise from Python against native code.
"""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
EIGHT_PATH = ROOT / "apple2" / "claude2.s"
GS_PATH = ROOT / "apple2gs" / "claude.s"


def _read(path):
    return path.read_text()


def _section(src, start, end):
    return src[src.index(start):src.index(end, src.index(start))]


def _cancel_step(cancel_requested, *, key=None, carrier=True, waited_frames=0):
    """Model one 8-bit spinner pass after a link has stopped answering."""
    if key in ("esc", "ctrl-c"):
        if cancel_requested:
            return True, "local-menu"
        return True, "send-ctrl-c"
    if not carrier or (cancel_requested and waited_frames >= 600):
        return cancel_requested, "local-menu"
    return cancel_requested, "wait"


def test_8bit_dead_link_cancel_has_local_recovery_paths():
    src = _read(EIGHT_PATH)
    spinner = _section(src, "spinner:", "; sp_draw_pulse")

    assert re.search(r"cmp\s+#\$1B\s+beq\s+@cancel", spinner)
    assert re.search(r"cmp\s+#\$03\s+bne\s+@nk\s+@cancel:", spinner)
    assert re.search(
        r"lda\s+spin_cancel.*?bne\s+@force.*?inc\s+spin_cancel"
        r".*?lda\s+#\$03.*?jsr\s+aciaput",
        spinner,
        re.S,
    )
    assert re.search(r"jsr\s+check_carrier.*?bcc\s+@force", spinner, re.S)
    assert "#>600" in spinner and "#<600" in spinner
    assert re.search(
        r"@force:\s*lda\s+#1\s+sta\s+quitflag\s+lda\s+#EOT"
        r".*?jmp\s+@stash",
        spinner,
        re.S,
    )

    requested, action = _cancel_step(False, key="ctrl-c")
    assert (requested, action) == (True, "send-ctrl-c")
    assert _cancel_step(requested, key="esc") == (True, "local-menu")
    assert _cancel_step(requested, key="ctrl-c") == (True, "local-menu")
    assert _cancel_step(False, carrier=False) == (False, "local-menu")
    assert _cancel_step(True, carrier=False) == (True, "local-menu")
    assert _cancel_step(True, waited_frames=599) == (True, "wait")
    assert _cancel_step(True, waited_frames=600) == (True, "local-menu")


def test_8bit_draw_str_polls_before_each_character():
    src = _read(EIGHT_PATH)
    draw = _section(src, "draw_str:", "; setstr macro-ish helper")
    loop = draw[draw.index("@l:"):]

    poll = loop.index("jsr     rb_poll")
    load = loop.index("lda     (src),y")
    back_edge = loop.index("bne     @l")
    assert poll < load < back_edge
    assert loop.count("jsr     rb_poll") == 1


def _tick_elapsed(state):
    """Increment decimal h:mm:ss digits, clamped at 9:59:59."""
    h, m10, m1, s10, s1 = state
    if state == (9, 5, 9, 5, 9):
        return state
    total = h * 3600 + (m10 * 10 + m1) * 60 + s10 * 10 + s1 + 1
    total = min(total, 9 * 3600 + 59 * 60 + 59)
    h, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return h, minutes // 10, minutes % 10, seconds // 10, seconds % 10


def test_native_elapsed_timer_rollover_and_saturation_model():
    assert _tick_elapsed((0, 0, 0, 5, 8)) == (0, 0, 0, 5, 9)
    assert _tick_elapsed((0, 0, 0, 5, 9)) == (0, 0, 1, 0, 0)
    assert _tick_elapsed((0, 5, 9, 5, 9)) == (1, 0, 0, 0, 0)
    assert _tick_elapsed((9, 5, 9, 5, 8)) == (9, 5, 9, 5, 9)
    assert _tick_elapsed((9, 5, 9, 5, 9)) == (9, 5, 9, 5, 9)


def test_native_elapsed_timer_source_contracts():
    eight = _read(EIGHT_PATH)
    spinner = _section(eight, "spinner:", "; sp_draw_pulse")
    tick8 = _section(eight, "sp_tick_second:", "; sp_draw_secs")

    for counter in ("sp_sub", "sp_s1", "sp_s10", "sp_m1", "sp_m10", "sp_h"):
        assert re.search(rf"^\s*{counter}:\s+\.res\s+1", eight, re.M)
        assert re.search(rf"sta\s+{counter}", spinner)
    assert re.search(r"cmp\s+#60.*?jsr\s+sp_tick_second", spinner, re.S)
    assert "jsr     sp_draw_line" in spinner
    assert tick8.index("cmp     #9") < tick8.index("inc     sp_s1")
    max_guard8 = tick8[:tick8.index("@inc:")]
    for counter, maximum in (
        ("sp_h", 9), ("sp_m10", 5), ("sp_m1", 9),
        ("sp_s10", 5), ("sp_s1", 9),
    ):
        assert re.search(
            rf"lda\s+{counter}.*?cmp\s+#{maximum}", max_guard8, re.S)
    assert tick8.count("cmp     #10") >= 2
    assert tick8.count("cmp     #6") >= 2
    assert "inc     sp_h" in tick8

    gs = _read(GS_PATH)
    tick_gs = _section(gs, "tick_second:", "; draw_secs")
    for counter in ("sp_s1", "sp_s10", "sp_m1", "sp_m10", "sp_h"):
        assert re.search(rf"^\s*{counter}:\s+\.res\s+1", gs, re.M)
    max_guard_gs = tick_gs[:tick_gs.index("ts_inc:")]
    for counter, maximum in (
        ("sp_h", 9), ("sp_m10", 5), ("sp_m1", 9),
        ("sp_s10", 5), ("sp_s1", 9),
    ):
        assert re.search(
            rf"lda\s+{counter}.*?cmp\s+#{maximum}", max_guard_gs, re.S)
    assert tick_gs.count("cmp     #10") >= 2
    assert tick_gs.count("cmp     #6") >= 2
    assert re.search(
        r"lda\s+sp_h\s+cmp\s+#9.*?(?:bcs|beq)\s+\w+.*?inc\s+sp_h",
        tick_gs,
        re.S,
    )
