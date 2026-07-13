"""Regression tests for render.py's emphasis reduction (punchlist #5).

The old reducer stripped every * and __ unconditionally, corrupting literal
text and code: `*.py` -> `.py`, `2 * 3` -> `2  3`, `__init__` -> `init`.
This checks that emphasis markers vanish only when they're real delimiters,
that literal * / _ survive (especially inside code spans), and that the
in-band white control bytes still bracket code spans.

Plain assert-script style to match tests/test_interrupt.py (no pytest here).
Run: python3 test_render_markdown.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from render import _inline, _WHITE_ON, _WHITE_OFF


def check(got, want, label):
    assert got == want, f"{label}: got {got!r}, want {want!r}"


def test_literals_survive():
    # The three verified failures from the bug report.
    check(_inline("*.py"), "*.py", "glob star")
    check(_inline("2 * 3"), "2 * 3", "multiplication")
    check(_inline("__init__"), "__init__", "dunder")
    # Other bare tokens that must stay intact.
    check(_inline("a_b_c"), "a_b_c", "underscore ident")
    check(_inline("snake_case_name"), "snake_case_name", "snake_case")
    check(_inline("**kwargs"), "**kwargs", "kwargs splat")
    check(_inline("*args"), "*args", "args splat")
    check(_inline("__name__"), "__name__", "dunder name")
    check(_inline("see *.py and *.txt"), "see *.py and *.txt", "two globs")


def test_real_emphasis_stripped():
    check(_inline("*hi*"), "hi", "italic star")
    check(_inline("**bold**"), "bold", "bold star")
    check(_inline("_em_"), "em", "italic underscore")
    check(_inline("a **bold** word"), "a bold word", "bold in prose")
    check(_inline("some *italic* here"), "some italic here", "italic in prose")
    check(_inline("this is _em_ text"), "this is em text", "underscore em prose")
    check(_inline("__two words__"), "two words", "multiword bold underscore")


def test_code_spans_preserve_and_color():
    got = _inline("run `2 * 3` now")
    check(got, "run " + _WHITE_ON + "2 * 3" + _WHITE_OFF + " now", "code * preserved")

    got = _inline("call `__init__` here")
    check(got, "call " + _WHITE_ON + "__init__" + _WHITE_OFF + " here", "code __ preserved")

    # Emphasis outside a code span still strips; the span stays verbatim.
    got = _inline("**bold** and `*.py`")
    check(got, "bold and " + _WHITE_ON + "*.py" + _WHITE_OFF, "mix strip + code")


def test_control_bytes_intact():
    # The white markers are exactly \x01\x03 (on) and \x01\x01 (off): two
    # bytes each, both below EOT, and must bracket the code content unbroken.
    got = _inline("x `code` y")
    assert _WHITE_ON in got and _WHITE_OFF in got, "markers missing"
    on = got.index(_WHITE_ON)
    off = got.index(_WHITE_OFF)
    assert got[on + len(_WHITE_ON) : off] == "code", "content between markers wrong"
    for ch in got:
        assert ord(ch) < 0x04 or ord(ch) >= 0x20, f"stray control byte {ord(ch)}"


def run():
    for fn in (
        test_literals_survive,
        test_real_emphasis_stripped,
        test_code_spans_preserve_and_color,
        test_control_bytes_intact,
    ):
        fn()
        print(f"PASS: {fn.__name__}")


if __name__ == "__main__":
    run()
    print("ALL PASS")
