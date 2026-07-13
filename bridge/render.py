"""Turn Claude's modern, Unicode-happy Markdown into something an Apple II can
actually display: 7-bit ASCII, word-wrapped to 40 or 80 columns, no fancy glyphs.

The Apple II character ROM has uppercase, lowercase (IIe/IIc/IIgs), digits, and
the standard ASCII punctuation. It has no em-dash, no smart quotes, no bullets,
no box-drawing. Anything outside printable 7-bit ASCII becomes a best-effort
substitute or a plain '?'.
"""

from __future__ import annotations

import re
import textwrap

# Unicode -> ASCII substitutions for the characters Claude reaches for most.
_SUBS = {
    "—": "--", "–": "-", "―": "--",
    "‘": "'", "’": "'", "‚": ",",
    "“": '"', "”": '"', "„": '"',
    "…": "...", "•": "*", "·": "*", "◦": "*",
    "→": "->", "←": "<-", "⇒": "=>",
    "≥": ">=", "≤": "<=", "×": "x", "÷": "/",
    " ": " ",  # non-breaking space
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "à": "a", "á": "a", "â": "a",
    "ü": "u", "ù": "u", "ö": "o", "ô": "o", "ä": "a", "ñ": "n", "ç": "c",
    "©": "(c)", "®": "(r)", "™": "(tm)", "°": "deg",
}

# In-band color markers understood by the native client (kept out of to_ascii's
# stripping). 0x01 <n> selects a color; we use it to draw code spans in white.
COLOR = "\x01"          # next char is a color index
C_GRAY = "\x01"         # 1 - normal reply text
C_WHITE = "\x03"        # 3 - inline/fenced code
_WHITE_ON = COLOR + C_WHITE
_WHITE_OFF = COLOR + C_GRAY

# `code` spans -> white; emphasis (** __ * _) is stripped, but ONLY when the
# markers are actually acting as matched delimiters around a span. Literal
# asterisks/underscores in prose and code must survive: `*.py`, `2 * 3`,
# `__init__`, `a_b_c`, `**kwargs`. The rules below mirror CommonMark flanking
# (a delimiter can't open with whitespace on its inner side, or close with
# whitespace on it) plus a guard against intraword underscores.
_CODE = re.compile(r"`([^`]+)`")

# **bold** / *italic* — inner side must be non-space; italic ignores ** runs.
_BOLD_STAR = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_EM_STAR = re.compile(r"(?<!\*)\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)")
# __bold__ / _italic_ — must sit on word boundaries so identifiers survive.
_BOLD_UND = re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)")
_EM_UND = re.compile(r"(?<!\w)_(?=[^\s_])(.+?)(?<=[^\s_])_(?!\w)")


def _und_bold(m: re.Match) -> str:
    """Strip __bold__ but leave dunder identifiers (__init__, __name__) alone."""
    inner = m.group(1)
    return m.group(0) if re.fullmatch(r"\w+", inner) else inner


def _strip_emphasis(text: str) -> str:
    """Remove emphasis/bold delimiters acting as such; keep literal * and _."""
    text = _BOLD_STAR.sub(r"\1", text)
    text = _BOLD_UND.sub(_und_bold, text)
    text = _EM_STAR.sub(r"\1", text)
    text = _EM_UND.sub(r"\1", text)
    return text


def _inline(text: str) -> str:
    """Color `code` spans white via in-band markers, strip other emphasis.

    Emphasis is stripped only outside code spans, and the white control bytes
    are injected after stripping so they're never eaten or misaligned.
    """
    out: list[str] = []
    pos = 0
    for m in _CODE.finditer(text):
        out.append(_strip_emphasis(text[pos : m.start()]))
        out.append(_WHITE_ON + m.group(1) + _WHITE_OFF)  # code kept verbatim
        pos = m.end()
    out.append(_strip_emphasis(text[pos:]))
    return "".join(out)


def to_ascii(text: str) -> str:
    """Collapse a Unicode string down to printable 7-bit ASCII."""
    out = []
    for ch in text:
        if ch in _SUBS:
            out.append(_SUBS[ch])
            continue
        o = ord(ch)
        if ch == "\n":
            out.append(ch)
        elif ch == "\t":
            out.append("    ")
        elif 32 <= o <= 126:
            out.append(ch)
        elif o in (1, 2, 3):
            out.append(ch)  # in-band color marker/value, keep for the client
        elif o < 32:
            pass  # drop stray control chars; they'd garble a dumb terminal
        else:
            out.append("?")
    return "".join(out)


def wrap(text: str, width: int) -> list[str]:
    """Word-wrap to `width` columns, preserving blank lines and indentation.

    Over-long tokens (a URL, a long path) are hard-broken so nothing ever
    exceeds the column count and wraps unpredictably on the Apple II side.
    """
    out: list[str] = []
    for para in text.split("\n"):
        if not para.strip():
            out.append("")
            continue
        indent = para[: len(para) - len(para.lstrip())]
        wrapped = textwrap.wrap(
            para,
            width=width,
            initial_indent=indent,
            subsequent_indent=indent,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=True,
            drop_whitespace=True,
        )
        out.extend(wrapped or [""])
    return out


class StreamFormatter:
    """Incrementally format a streaming reply, emitting complete display lines.

    Feed it raw chunks as they arrive from Claude; it buffers until it has whole
    source lines, transforms the Markdown, sanitizes to ASCII, wraps to width,
    and returns the finished lines. Call `flush()` at the end for the tail.
    """

    def __init__(self, width: int) -> None:
        self.width = width
        self._buf = ""
        self._in_fence = False

    def feed(self, chunk: str) -> list[str]:
        self._buf += chunk
        out: list[str] = []
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            out.extend(self._emit(line))
        return out

    def flush(self) -> list[str]:
        out: list[str] = []
        if self._buf:
            out.extend(self._emit(self._buf))
            self._buf = ""
        return out

    def _emit(self, line: str) -> list[str]:
        transformed = self._transform(line)
        if transformed is None:
            return []
        return wrap(to_ascii(transformed), self.width)

    def _transform(self, line: str) -> str | None:
        """One source line of Markdown -> one plain line (or None to drop it)."""
        line = line.rstrip("\r")
        # Model text must not carry the in-band control bytes the client acts
        # on; to_ascii passes 0x01-0x03 through, so strip them here BEFORE we
        # inject our own color markers. 0x04/0x0E are already dropped downstream.
        line = line.translate({1: None, 2: None, 3: None})

        if line.lstrip().startswith("```"):
            self._in_fence = not self._in_fence
            return None  # swallow the fence marker itself

        if self._in_fence:
            return _WHITE_ON + "  " + line + _WHITE_OFF  # code block, in white

        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            return m.group(2).strip().upper()

        m = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if m:
            return f"{m.group(1)}* {_inline(m.group(2))}"

        return _inline(line)


def format_reply(text: str, width: int) -> str:
    """Non-streaming convenience: whole reply -> CR/LF terminated block."""
    fmt = StreamFormatter(width)
    lines = fmt.feed(text)
    lines += fmt.flush()
    return "\r\n".join(lines)
