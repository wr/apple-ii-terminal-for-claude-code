"""Source-contract tests for issue #6: distinct modem dial verdicts.

Both native clients (apple2gs/claude.s, apple2/claude2.s) must classify a
modem result line into a SPECIFIC verdict and show a distinct, actionable
message. Rather than boot an emulator, this pins the cross-client contract:

  * the five DR_* verdict constants exist with identical values in both,
  * the four failure messages exist, are actionable, and fit the 8-bit
    40-col fallback (drawn from col 2 -> <=38 chars),
  * dfail_ptrs lists the messages in verdict order (DR_ERR..DR_NOANS),
  * a model of the byte-at-a-time state machine maps real modem lines to the
    right verdict (CONNECT/ERROR/BUSY/NO CARRIER/NO ANSWER), and leaves
    silence at 0 so the emulator/already-online path still proceeds.

Plain assert-script (not pytest), like the other bridge tests. If cc65 is on
PATH it also assembles + links both clients as a final gate.
"""
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GS = os.path.join(ROOT, "apple2gs", "claude.s")
EIGHT = os.path.join(ROOT, "apple2", "claude2.s")

EXPECTED_CONSTS = {
    "DR_CONN": 1, "DR_ERR": 2, "DR_BUSY": 3, "DR_NOCAR": 4, "DR_NOANS": 5,
}
# label -> (verdict const, required leading token). Order here is verdict order.
MESSAGES = [
    ("str_derr", "DR_ERR", "ERROR"),
    ("str_dbusy", "DR_BUSY", "BUSY"),
    ("str_dnocar", "DR_NOCAR", "NO CARRIER"),
    ("str_dnoans", "DR_NOANS", "NO ANSWER"),
]
MAX_MSG_LEN = 38  # drawn at col 2 on a 40-col screen


def _read(path):
    with open(path) as f:
        return f.read()


def check(name, ok):
    print(("PASS" if ok else "FAIL") + ": " + name)
    if not ok:
        raise AssertionError(name)


def _const(src, label):
    m = re.search(rf"^{label}\s*=\s*(\d+)", src, re.M)
    return int(m.group(1)) if m else None


def _msg(src, label):
    m = re.search(rf'^{re.escape(label)}:\s*\.byte\s*"([^"]*)"', src, re.M)
    return m.group(1) if m else None


def check_client(path, label):
    src = _read(path)
    for k, v in EXPECTED_CONSTS.items():
        check(f"{label}: {k} = {v}", _const(src, k) == v)
    for lbl, _const_name, token in MESSAGES:
        msg = _msg(src, lbl)
        check(f"{label}: {lbl} defined", msg is not None)
        check(f"{label}: {lbl} starts with {token!r}", msg.startswith(token))
        check(f"{label}: {lbl} fits 40-col (<= {MAX_MSG_LEN})", len(msg) <= MAX_MSG_LEN)
    # dfail_ptrs lists the four messages in verdict order. Scan a window from
    # the label (inline comments would defeat a whitespace-only run regex).
    check(f"{label}: dfail_ptrs table present", "dfail_ptrs:" in src)
    window = src[src.index("dfail_ptrs:"):][:400]
    ptrs = re.findall(r"\.addr\s+(\w+)", window)[:len(MESSAGES)]
    check(f"{label}: dfail_ptrs in verdict order",
          ptrs == [m[0] for m in MESSAGES])


# --------------------------------------------------------------------------- #
# Model of the byte-at-a-time classifier (dial_byte), used to prove the token
# -> verdict mapping. Mirrors the assembly's mdm_c1 phase machine exactly.
# --------------------------------------------------------------------------- #
def classify(line):
    """Feed a modem line (as the client would, incl. the trailing CR) and
    return the resulting dialres (0 = no verdict)."""
    dialres = 0
    phase = 0  # 0 start, ord('C'/'N'/'M'), or 0xFF (done)
    for ch in line:
        b = ord(ch) & 0x7F
        if b == 0x0D:            # CR: line boundary
            phase = 0
            continue
        if b < 0x20:             # other control byte
            continue
        c = chr(b)
        if phase == 0xFF:
            continue
        if phase == ord('C'):
            if c == 'O':
                dialres = EXPECTED_CONSTS["DR_CONN"]
            phase = 0xFF
            continue
        if phase == ord('N'):
            phase = ord('M') if c == 'O' else 0xFF
            continue
        if phase == ord('M'):
            if c == ' ':
                continue         # skip spaces after "NO"
            if c == 'C':
                dialres = EXPECTED_CONSTS["DR_NOCAR"]
            elif c == 'A':
                dialres = EXPECTED_CONSTS["DR_NOANS"]
            else:
                dialres = EXPECTED_CONSTS["DR_NOCAR"]  # NO DIALTONE / other
            phase = 0xFF
            continue
        # phase 0: first letter
        if c == ' ':
            continue
        if c == 'E':
            dialres = EXPECTED_CONSTS["DR_ERR"]; phase = 0xFF
        elif c == 'B':
            dialres = EXPECTED_CONSTS["DR_BUSY"]; phase = 0xFF
        elif c == 'C':
            phase = ord('C')
        elif c == 'N':
            phase = ord('N')
        else:
            phase = 0xFF         # OK / RING / echo / other
    return dialres


def test_classifier():
    cases = {
        "CONNECT\r": "DR_CONN",
        "CONNECT 9600\r": "DR_CONN",
        "ERROR\r": "DR_ERR",
        "BUSY\r": "DR_BUSY",
        "NO CARRIER\r": "DR_NOCAR",
        "NO ANSWER\r": "DR_NOANS",
        "NO DIALTONE\r": "DR_NOCAR",   # other NO x -> carrier-class
    }
    for line, want in cases.items():
        got = classify(line)
        check(f"classify {line.strip()!r} -> {want}", got == EXPECTED_CONSTS[want])
    # non-verdict chatter and the dial echo must leave dialres at 0 (silence)
    for noise in ("OK\r", "RING\r", "ATDS=0\r", "\r\n"):
        check(f"classify {noise.strip()!r} -> silence", classify(noise) == 0)
    # a full transcript: echo, then RING, then the real verdict
    check("classify echo+RING+CONNECT -> CONNECT",
          classify("ATDS=0\r\nRING\r\nCONNECT 9600\r") == EXPECTED_CONSTS["DR_CONN"])


def test_assembles():
    if not (shutil.which("ca65") and shutil.which("ld65")):
        print("SKIP: cc65 not on PATH (assemble gate)")
        return
    builds = [
        ("GS", "apple2gs", ["ca65", "--cpu", "65816", "-o", "/tmp/dv_gs.o", "claude.s"],
         ["ld65", "-C", "claude.cfg", "-o", "/tmp/dv_gs.obj", "/tmp/dv_gs.o"]),
        ("8bit", "apple2", ["ca65", "--cpu", "6502", "-o", "/tmp/dv_8.o", "claude2.s"],
         ["ld65", "-C", "claude2.cfg", "-o", "/tmp/dv_8.obj", "/tmp/dv_8.o"]),
    ]
    for name, sub, asm, link in builds:
        cwd = os.path.join(ROOT, sub)
        for cmd in (asm, link):
            r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
            check(f"{name}: {cmd[0]} ok", r.returncode == 0)


if __name__ == "__main__":
    check_client(GS, "GS")
    check_client(EIGHT, "8bit")
    test_classifier()
    test_assembles()
    print("ALL PASS")
