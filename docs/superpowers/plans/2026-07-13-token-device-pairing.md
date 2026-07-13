# Token Device Pairing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace IP-based `--telnet` pairing with a client-held secret token stored on the Apple II boot disk and hashed at rest on the bridge.

**Architecture:** The bridge issues a 160-bit token after a successful first-run code entry, sends it downstream in a new `CMD_TOKEN` (`0x05`) frame, and stores only its SHA-256. The client writes the token to a reserved disk sector via RWTS and auto-sends it as its first line on every reconnect. IP is logged but never trusted.

**Tech Stack:** Python 3 (bridge, `pytest`), cc65 `ca65` 65816/6502 assembly (clients), dos33fsprogs (disk build), MAME Lua (client tests), KEGS (end-to-end).

## Global Constraints

- Pairing token: 160 bits `secrets` entropy, 32 chars from alphabet `ABCDEFGHJKMNPQRSTUVWXYZ23456789` (uppercase, no look-alikes). Pure 7-bit ASCII.
- Bridge stores only `sha256(token)` hex; compare with `secrets.compare_digest`. Never log or persist the plaintext token.
- New downstream control byte: `CMD_TOKEN = 0x05`. Existing: `CMD_COLOR=0x01`, `CMD_BULLET=0x02`, `CMD_QUIT=0x03`, `EOT=0x04`, `CMD_HEADER=0x0E`.
- `paired.json` v2 schema: `{"v": 2, "devices": [{"token_sha256": str, "first_ip": str, "paired_at": int}]}`. File mode `0600`, dir `0700`, written atomically (temp + `os.replace`).
- Reserved token sector: track `$12`, sector `$0F` on `CLAUDE.dsk`. Sector layout: magic `"CLDTK1"` (6B) + length (1B) + token (NB) + checksum (1B, 8-bit sum of preceding bytes) + zero fill.
- Token exchange is gated to `--app` sessions only. Serial and `--connect` transports remain ungated.
- Zero-page discipline (clients): only `$06-$09`, `$FA-$FE` are known-safe; never touch CHRGET `$B1-$C8`, `$D6`, `$D8`. RWTS sector buffer lives in the free `$9000-$95FF` gap.
- 8-bit client is plain 6502 (no 65C02 ops). GS client is 65816; annotate `.a8`/`.a16`/`.i8`/`.i16` after any `jsr` that changes register width.
- Never add a slow loop in the clients without calling `rb_poll` inside it (serial ring can overflow on real hardware).
- Bridge working dir for tests/commands: `bridge/`. Run tests with `python3 -m pytest`.

---

## Phase 0 — Companion hardening (independent, ships first)

These are from the security review, touch the same files, and de-risk the branch. Each is self-contained.

### Task 0.1: Guard the telnet IAC partial-sequence crash

**Files:**
- Modify: `bridge/terminal.py:59-77` (`_handle_iac`)
- Modify: `bridge/bridge.py:836-840` (per-session try/finally)
- Test: `bridge/test_terminal_iac.py` (create)

**Interfaces:**
- Consumes: `Terminal`, `TermConfig` from `terminal.py`; a fake channel.
- Produces: nothing new; hardens existing `_handle_iac`.

- [ ] **Step 1: Write the failing test**

Create `bridge/test_terminal_iac.py`:

```python
from terminal import Terminal, TermConfig
from transports import Channel


class _ScriptChannel(Channel):
    """Feeds a fixed byte script, then reports the connection gone (None)."""
    is_network = True

    def __init__(self, script: bytes):
        self._bytes = list(script)
        self.written = bytearray()

    def read_byte(self):
        if self._bytes:
            return self._bytes.pop(0)
        return None  # peer gone

    def write(self, data: bytes) -> None:
        self.written.extend(data)


def test_partial_iac_do_does_not_raise():
    # IAC DO (255, 253) then the socket dies before the option byte arrives.
    ch = _ScriptChannel(bytes([255, 253]))
    term = Terminal(ch, TermConfig(telnet=True))
    # read_line must return None (closed), not raise TypeError.
    assert term.read_line() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bridge && python3 -m pytest test_terminal_iac.py -v`
Expected: FAIL with `TypeError: 'NoneType' object cannot be interpreted as an integer`.

- [ ] **Step 3: Fix `_handle_iac`**

In `bridge/terminal.py`, replace the body of `_handle_iac` (lines 59-77) with:

```python
    def _handle_iac(self) -> None:
        verb = self._raw_byte_blocking()
        if verb is None:
            return  # peer gone mid-sequence
        if verb in (DO, DONT, WILL, WONT):
            opt = self._raw_byte_blocking()
            if opt is None:
                return  # peer gone before the option byte
            # Politely refuse anything we didn't ask for; stay in char mode.
            if verb == DO:
                self.ch.write(bytes([IAC, WONT, opt]))
            elif verb == WILL:
                self.ch.write(bytes([IAC, DONT, opt]))
        elif verb == SB:
            # Skip a sub-negotiation block up to IAC SE, bounded so a peer
            # that never sends SE can't park us here forever.
            prev = None
            for _ in range(512):
                b = self._raw_byte_blocking()
                if b is None:
                    return
                if prev == IAC and b == SE:
                    return
                prev = b
            return  # oversized subnegotiation: give up, stay in char mode
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd bridge && python3 -m pytest test_terminal_iac.py -v`
Expected: PASS.

- [ ] **Step 5: Wrap the session body so one peer can't kill the listener**

In `bridge/bridge.py`, the accept loop's per-session block (around lines 836-840) currently is:

```python
            try:
                run_session(term, args, pm)
            finally:
                channel.close()
                log(f"{peer} disconnected after {time.monotonic() - t0:.0f}s")
```

Change to:

```python
            try:
                run_session(term, args, pm)
            except Exception as exc:  # one peer must never take down the listener
                log(f"session error for {peer}: {exc}")
            finally:
                channel.close()
                log(f"{peer} disconnected after {time.monotonic() - t0:.0f}s")
```

- [ ] **Step 6: Commit**

```bash
git add bridge/terminal.py bridge/bridge.py bridge/test_terminal_iac.py
git commit -m "Harden telnet IAC parsing against partial sequences (review W-fix)"
```

### Task 0.2: Stop model text from smuggling control bytes

**Files:**
- Modify: `bridge/render.py` (`StreamFormatter._transform`, top of body)
- Test: `bridge/test_render_markdown.py` (append)

**Interfaces:**
- Consumes: `StreamFormatter` from `render.py`.
- Produces: model text with bytes `0x01-0x03` stripped before bridge markers are injected.

- [ ] **Step 1: Write the failing test**

Append to `bridge/test_render_markdown.py`:

```python
from render import StreamFormatter


def test_model_control_bytes_are_stripped():
    fmt = StreamFormatter(80)
    out = fmt.feed("hello\x03world\x01\x02 there\n")
    line = out[0]
    # No raw quit/color/bullet bytes may survive into a display line.
    assert "\x03" not in line
    assert "\x02" not in line
    # Bridge-injected color markers are added later by _inline, not here,
    # so a plain line carries none.
    assert "\x01" not in line
    assert "helloworld there" in line
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bridge && python3 -m pytest test_render_markdown.py::test_model_control_bytes_are_stripped -v`
Expected: FAIL (raw `\x03` present).

- [ ] **Step 3: Strip controls at the top of `_transform`**

In `bridge/render.py`, `_transform` currently starts:

```python
    def _transform(self, line: str) -> str | None:
        """One source line of Markdown -> one plain line (or None to drop it)."""
        line = line.rstrip("\r")
```

Insert the strip immediately after the `rstrip`:

```python
    def _transform(self, line: str) -> str | None:
        """One source line of Markdown -> one plain line (or None to drop it)."""
        line = line.rstrip("\r")
        # Model text must not carry the in-band control bytes the client acts
        # on; to_ascii passes 0x01-0x03 through, so strip them here BEFORE we
        # inject our own color markers. 0x04/0x0E are already dropped downstream.
        line = line.translate({1: None, 2: None, 3: None})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd bridge && python3 -m pytest test_render_markdown.py -v`
Expected: PASS (all tests, including the existing ones).

- [ ] **Step 5: Commit**

```bash
git add bridge/render.py bridge/test_render_markdown.py
git commit -m "Strip in-band control bytes from model text before markers (review W-fix)"
```

### Task 0.3: Send generic errors to the peer; log detail to the host

**Files:**
- Modify: `bridge/backends.py:217-220` (ChatBackend error), `bridge/backends.py:454-456` (CodeBackend exit)
- Modify: `bridge/bridge.py:277-278` (`_pump` error)
- Test: `bridge/test_error_hygiene.py` (create)

**Interfaces:**
- Consumes: `CodeBackend` from `backends.py`.
- Produces: peer-facing strings that never include host paths / stderr.

- [ ] **Step 1: Write the failing test**

Create `bridge/test_error_hygiene.py`:

```python
import backends


def test_code_backend_bad_exit_hides_stderr(monkeypatch, capsys):
    be = backends.CodeBackend(cols=80, claude_bin="/definitely/not/here/claude")
    # FileNotFoundError path yields a generic, path-free message.
    out = "".join(be.stream("hi"))
    assert "not found" in out.lower()
    # The exact bogus path must not be reflected to the peer.
    assert "/definitely/not/here" not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bridge && python3 -m pytest test_error_hygiene.py -v`
Expected: FAIL — current message embeds `self._bin` (`'/definitely/not/here/claude' not found`).

- [ ] **Step 3: Make the peer-facing messages generic, log detail**

In `bridge/backends.py`, the `FileNotFoundError` branch of `CodeBackend.stream` (around line 416-418):

```python
        except FileNotFoundError:
            yield f"\n[bridge error: '{self._bin}' not found on the host]"
            return
```

becomes:

```python
        except FileNotFoundError:
            print(f"[bridge] claude binary not found: {self._bin!r}",
                  file=sys.stderr, flush=True)
            yield "\n[bridge error: claude CLI not found on the host]"
            return
```

Add `import sys` at the top of `backends.py` if absent.

The bad-exit branch (lines 454-456):

```python
        if proc.returncode not in (0, None):
            err = "".join(err_parts).strip()
            yield f"\n[claude exited {proc.returncode}{': ' + err if err else ''}]"
```

becomes:

```python
        if proc.returncode not in (0, None):
            err = "".join(err_parts).strip()
            if err:
                print(f"[bridge] claude stderr: {err}", file=sys.stderr, flush=True)
            yield f"\n[claude exited {proc.returncode}]"
```

In `ChatBackend.stream` (line 220), `yield f"\n[bridge error: {exc}]"` becomes:

```python
            print(f"[bridge] chat backend error: {exc}", file=sys.stderr, flush=True)
            yield "\n[bridge error: chat request failed]"
```

In `bridge/bridge.py` `_pump` (lines 277-278):

```python
            except Exception as exc:
                chunks.put(f"\n[bridge error: {exc}]")
```

becomes:

```python
            except Exception as exc:
                log(f"stream error: {exc}")
                chunks.put("\n[bridge error: reply failed]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd bridge && python3 -m pytest test_error_hygiene.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bridge/backends.py bridge/bridge.py bridge/test_error_hygiene.py
git commit -m "Send peers generic errors; log host detail to console (review W-fix)"
```

### Task 0.4: Bound the availability holes (poll_ctrl_c drain + pre-session line ceiling)

**Files:**
- Modify: `bridge/terminal.py:124-140` (`poll_ctrl_c`)
- Modify: `bridge/terminal.py` `read_line` (add optional deadline)
- Modify: `bridge/bridge.py` `require_pairing` (pass the deadline)
- Test: `bridge/test_terminal_iac.py` (append)

**Interfaces:**
- Consumes: `Terminal.read_line`, `Terminal.poll_ctrl_c`.
- Produces: `read_line(prompt="", deadline=None)` — returns `None` if `deadline` (a `time.monotonic()` value) passes before a full line arrives.

- [ ] **Step 1: Write the failing test**

Append to `bridge/test_terminal_iac.py`:

```python
import time
from terminal import Terminal, TermConfig


class _TrickleChannel(Channel):
    """Always 'timeout' (-1): a live peer that sends no completable line."""
    is_network = True

    def read_byte(self):
        return -1

    def write(self, data: bytes) -> None:
        pass


def test_read_line_honors_deadline():
    term = Terminal(_TrickleChannel(), TermConfig())
    t0 = time.monotonic()
    result = term.read_line(deadline=t0 + 0.3)
    assert result is None
    assert time.monotonic() - t0 < 2.0  # returned promptly, didn't hang


def test_poll_ctrl_c_is_bounded_under_flood():
    class _Flood(Channel):
        is_network = True
        def read_byte(self): return 0x41  # 'A' forever, never a timeout
        def write(self, d): pass
    term = Terminal(_Flood(), TermConfig())
    # Must return (False) rather than loop forever on an endless byte stream.
    assert term.poll_ctrl_c() is False
```

- [ ] **Step 2: Run test to verify it fails/hangs**

Run: `cd bridge && timeout 10 python3 -m pytest test_terminal_iac.py -v`
Expected: FAIL/timeout — `read_line` has no `deadline` kwarg; `poll_ctrl_c` loops forever.

- [ ] **Step 3: Add the deadline to `read_line` and bound `poll_ctrl_c`**

In `bridge/terminal.py`, change the `read_line` signature and loop head:

```python
    def read_line(self, prompt: str = "", deadline: float | None = None) -> str | None:
```

Inside the `while True:` loop, before `b = self._read_cooked_byte()`, add:

```python
            if deadline is not None and time.monotonic() >= deadline:
                return None
```

`_read_cooked_byte` blocks across timeouts, so also make the read respect the
deadline by converting `_raw_byte_blocking` to surface timeouts when a deadline
is active. Simplest: give `read_line` its own timeout-aware read. Replace the
loop's first line `b = self._read_cooked_byte()` with:

```python
            b = self._read_cooked_byte(deadline=deadline)
            if b == -1:      # a timeout tick with a deadline active
                continue
```

And update `_read_cooked_byte` / `_raw_byte_blocking` to accept and honor a
`deadline`:

```python
    def _raw_byte_blocking(self, deadline: float | None = None) -> int | None:
        while True:
            b = self.ch.read_byte()
            if b is None:
                self._closed = True
                return None
            if b == -1:
                if deadline is not None and time.monotonic() >= deadline:
                    return -1
                continue
            return b

    def _read_cooked_byte(self, deadline: float | None = None) -> int | None:
        while True:
            b = self._raw_byte_blocking(deadline=deadline)
            if b is None or b == -1:
                return b
            if b == IAC and self.ch.is_network and self.cfg.telnet:
                self._handle_iac()
                continue
            return b
```

Bound `poll_ctrl_c` (replace the `while True:` with a capped loop):

```python
    def poll_ctrl_c(self) -> bool:
        seen = False
        for _ in range(4096):  # drain what's buffered, don't chase a flood
            b = self.ch.read_byte()
            if b is None:
                self._closed = True
                return seen
            if b == -1:
                return seen
            if (b & 0x7F) == CTRL_C:
                seen = True
        return seen
```

- [ ] **Step 4: Enforce a pre-session ceiling in `require_pairing`**

In `bridge/bridge.py` `require_pairing`, compute a ceiling once and pass it to
`read_line`. After `prompted = False` (line 461), add:

```python
    ceiling = time.monotonic() + max(30.0, getattr(args, "idle_timeout", 60) or 60)
```

Change the read (line 463) from `line = term.read_line()` to:

```python
        line = term.read_line(deadline=ceiling)
```

And after `if line is None: return False`, an expired ceiling now also returns
False, freeing the single slot from a trickle that never completes a code.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd bridge && python3 -m pytest test_terminal_iac.py -v`
Expected: PASS. Then run the full suite: `python3 -m pytest -q` — no regressions.

- [ ] **Step 6: Commit**

```bash
git add bridge/terminal.py bridge/bridge.py bridge/test_terminal_iac.py
git commit -m "Bound poll_ctrl_c drain and add a pre-session line deadline (review W-fix)"
```

---

## Phase 1 — Bridge token store

### Task 1.1: Token generation + hashing helpers

**Files:**
- Modify: `bridge/bridge.py` (near `gen_pair_code`, lines 325-334)
- Test: `bridge/test_pairing.py` (append)

**Interfaces:**
- Produces:
  - `gen_token() -> str` — 32 chars from `_PAIR_ALPHABET`, `secrets`-sourced.
  - `token_hash(token: str) -> str` — `hashlib.sha256(token.encode()).hexdigest()`.

- [ ] **Step 1: Write the failing test**

Append to `bridge/test_pairing.py`:

```python
import re
from bridge import gen_token, token_hash


def test_gen_token_shape():
    t = gen_token()
    assert len(t) == 32
    assert re.fullmatch(r"[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{32}", t)
    assert gen_token() != gen_token()  # not constant


def test_token_hash_is_sha256_hex():
    h = token_hash("ABCDEF")
    assert re.fullmatch(r"[0-9a-f]{64}", h)
    assert token_hash("ABCDEF") == token_hash("ABCDEF")
    assert token_hash("ABCDEF") != token_hash("ABCDEG")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bridge && python3 -m pytest test_pairing.py -k "gen_token or token_hash" -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement the helpers**

In `bridge/bridge.py`, add `import hashlib` at the top, then after `gen_pair_code` (line 334):

```python
_TOKEN_LEN = 32  # 32 * ~4.95 bits ~= 158 bits of entropy


def gen_token(n: int = _TOKEN_LEN) -> str:
    import secrets
    return "".join(secrets.choice(_PAIR_ALPHABET) for _ in range(n))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd bridge && python3 -m pytest test_pairing.py -k "gen_token or token_hash" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bridge/bridge.py bridge/test_pairing.py
git commit -m "Add token generation and SHA-256 hashing helpers"
```

### Task 1.2: v2 device store — load/save/migrate

**Files:**
- Modify: `bridge/bridge.py` (`PairingManager._load`, `_save`, `__init__`, `clear_paired`, lines 358-388)
- Test: `bridge/test_pairing.py` (append)

**Interfaces:**
- Produces on `PairingManager`:
  - `self.devices: list[dict]` — each `{"token_sha256", "first_ip", "paired_at"}`.
  - `_load() -> list[dict]` — reads v2; ignores v1/legacy shapes → `[]`.
  - `_save()` — atomic write, dir `0700`, file `0600`, schema `{"v":2,"devices":[...]}`.
  - `clear_paired() -> int` — drops all devices, returns count.

- [ ] **Step 1: Write the failing test**

Append to `bridge/test_pairing.py`:

```python
import json, os, stat
from bridge import PairingManager


def test_v2_store_roundtrip_and_perms(tmp_path):
    store = tmp_path / "paired.json"
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(store))
    pm.devices.append({"token_sha256": "a" * 64,
                       "first_ip": "10.0.0.5", "paired_at": 1000})
    pm._save()
    data = json.loads(store.read_text())
    assert data["v"] == 2
    assert data["devices"][0]["token_sha256"] == "a" * 64
    assert stat.S_IMODE(os.stat(store).st_mode) == 0o600


def test_legacy_v1_ip_list_is_ignored(tmp_path):
    store = tmp_path / "paired.json"
    store.write_text(json.dumps(["10.0.1.117", "127.0.0.1"]))  # old shape
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(store))
    assert pm.devices == []  # legacy IPs never trusted


def test_clear_paired_counts_and_empties(tmp_path):
    store = tmp_path / "paired.json"
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(store))
    pm.devices = [{"token_sha256": "b" * 64, "first_ip": "x", "paired_at": 1}]
    pm._save()
    assert pm.clear_paired() == 1
    assert pm.devices == []
    assert json.loads(store.read_text())["devices"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bridge && python3 -m pytest test_pairing.py -k "v2_store or legacy_v1 or clear_paired_counts" -v`
Expected: FAIL (`PairingManager` still uses `self.paired` set).

- [ ] **Step 3: Rewrite persistence for v2**

In `bridge/bridge.py`, change `PairingManager.__init__` (line 364) from
`self.paired = self._load()` to `self.devices = self._load()`. Replace `_load`,
`_save`, and `clear_paired` (lines 368-388) with:

```python
    def _load(self) -> list:
        try:
            with open(self.store_path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        if isinstance(data, dict) and data.get("v") == 2:
            devs = data.get("devices")
            return devs if isinstance(devs, list) else []
        return []  # legacy v1 (an IP list) or anything unknown: never trusted

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.store_path), mode=0o700, exist_ok=True)
            tmp = self.store_path + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"v": 2, "devices": self.devices}, f)
            os.replace(tmp, self.store_path)
        except OSError as exc:
            log(f"pairing: could not persist ({exc})")

    def clear_paired(self) -> int:
        n = len(self.devices)
        self.devices = []
        self._save()
        return n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd bridge && python3 -m pytest test_pairing.py -k "v2_store or legacy_v1 or clear_paired_counts" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bridge/bridge.py bridge/test_pairing.py
git commit -m "PairingManager: v2 token-hash device store, atomic 0600 write, v1 migration"
```

### Task 1.3: Token check + issue on the manager

**Files:**
- Modify: `bridge/bridge.py` (`PairingManager` — replace `is_paired`, add `check_token`/`issue_token`; `check` no longer stores IPs; lines 394-427)
- Test: `bridge/test_pairing.py` (append)

**Interfaces:**
- Produces on `PairingManager`:
  - `check_token(line: str) -> bool` — constant-time match of `token_hash(line)` against any stored `token_sha256`.
  - `issue_token(peer) -> str` — generate a token, append `{token_sha256, first_ip, paired_at}`, persist, return the plaintext once.
  - `check(peer, guess)` keeps validating the human code but no longer records IPs (returns bool only).
- Removes: `is_paired` (callers updated in Task 2.1).

- [ ] **Step 1: Write the failing test**

Append to `bridge/test_pairing.py`:

```python
from bridge import token_hash


def test_issue_then_check_token(tmp_path):
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(tmp_path / "p.json"))
    tok = pm.issue_token("10.0.0.9")
    assert len(tok) == 32
    assert pm.check_token(tok) is True
    assert pm.check_token("WRONGTOKENWRONGTOKENWRONGTOKEN99") is False
    # persisted as a hash, never plaintext
    assert token_hash(tok) == pm.devices[0]["token_sha256"]
    assert tok not in (tmp_path / "p.json").read_text()


def test_check_code_does_not_store_ip(tmp_path):
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(tmp_path / "p.json"))
    assert pm.check("10.0.0.9", "ABC123") is True
    assert pm.devices == []  # code success alone stores nothing; issue does
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bridge && python3 -m pytest test_pairing.py -k "issue_then_check or check_code_does_not" -v`
Expected: FAIL.

- [ ] **Step 3: Implement check/issue; strip IP storage from `check`**

In `bridge/bridge.py`, replace `is_paired` (lines 394-395) and `check`
(lines 418-427) with:

```python
    def check_token(self, line: str) -> bool:
        """Constant-time match of a presented token against stored hashes."""
        import secrets
        h = token_hash(line)
        return any(secrets.compare_digest(h, d.get("token_sha256", ""))
                   for d in self.devices)

    def issue_token(self, peer) -> str:
        """Mint a token, remember only its hash + metadata, return it once."""
        tok = gen_token()
        self.devices.append({
            "token_sha256": token_hash(tok),
            "first_ip": peer or "",
            "paired_at": int(time.time()),
        })
        self._save()
        return tok

    def check(self, peer, guess: str) -> bool:
        """Constant-time compare of the human code; storage happens on issue."""
        import secrets
        ok = (self.window_open()
              and secrets.compare_digest(guess, self.code))
        if ok:
            self._fails.pop(peer, None)
        return ok
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd bridge && python3 -m pytest test_pairing.py -k "issue_then_check or check_code_does_not" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bridge/bridge.py bridge/test_pairing.py
git commit -m "PairingManager: check_token/issue_token; code success no longer stores IPs"
```

---

## Phase 2 — Bridge protocol wiring

### Task 2.1: Token-first routing + issuance in `require_pairing`

**Files:**
- Modify: `bridge/bridge.py` (`require_pairing` lines 438-503; `main` known-device note lines 830-832; `_run_session` — remove the `is_paired` short-circuit at 581 stays as call to gate)
- Modify: `bridge/bridge.py` — add `CMD_TOKEN` constant near `EOT` (line 181)
- Test: `bridge/test_pairing_flow.py` (create)

**Interfaces:**
- Consumes: `PairingManager.check_token`, `issue_token`, `check`, `exhausted`, `record_failure`, `window_open`.
- Produces: a paired session that, on a first-run code success in `--app` mode, writes `b"\x05" + token + b"\r"` to the terminal before the paired ack.
- `CMD_TOKEN = b"\x05"`.

- [ ] **Step 1: Write the failing test**

Create `bridge/test_pairing_flow.py`:

```python
import types
from bridge import PairingManager, require_pairing, CMD_TOKEN


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


def _args(**kw):
    d = dict(app=True, idle_timeout=60)
    d.update(kw)
    return types.SimpleNamespace(**d)


def test_valid_token_first_line_pairs_without_code(tmp_path):
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(tmp_path / "p.json"))
    tok = pm.issue_token("10.0.0.5")
    term = _FakeTerm([tok])
    assert require_pairing(term, _args(), pm) is True


def test_first_run_code_issues_token_frame(tmp_path):
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(tmp_path / "p.json"))
    term = _FakeTerm(["", "ABC123"])  # blank line (prompt), then the code
    assert require_pairing(term, _args(), pm) is True
    # A CMD_TOKEN frame (0x05 + 32 chars + CR) was written to the client.
    assert bytes(CMD_TOKEN) in term.written
    idx = term.written.index(CMD_TOKEN[0])
    frame = term.written[idx + 1: idx + 1 + 32]
    assert len(frame) == 32
    assert pm.check_token(frame.decode("ascii")) is True


def test_wrong_token_falls_through_to_code(tmp_path):
    pm = PairingManager("ABC123", ttl_secs=0, store_path=str(tmp_path / "p.json"))
    term = _FakeTerm(["ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ", "ABC123"])
    assert require_pairing(term, _args(), pm) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bridge && python3 -m pytest test_pairing_flow.py -v`
Expected: FAIL (ImportError `CMD_TOKEN`; no token routing).

- [ ] **Step 3: Add `CMD_TOKEN` and rewrite `require_pairing`**

In `bridge/bridge.py`, after `EOT = b"\x04"` (line 181) add:

```python
CMD_TOKEN = b"\x05"  # app mode: bridge issues a device token; client stores it
```

Replace the guess-handling middle of `require_pairing` (the block from
`if pm.exhausted(peer):` through the failure `time.sleep`, lines 479-502) so a
line is first tried as a token, then as a code, and a code success issues the
token frame in `--app` mode:

```python
        if pm.check_token(line):  # a client auto-presenting its stored token
            log(f"pairing: {peer} paired via token")
            if args.app:
                term.write(EOT)
            else:
                term.write_line("Paired - go ahead.")
            return True
        if pm.exhausted(peer):
            log(f"pairing: {peer} hit the guess cap - locked out")
            term.write_line("Too many wrong codes. Restart the bridge to retry.")
            if args.app:
                term.write(EOT)
            return False
        if pm.check(peer, line.upper()):  # code alphabet is uppercase-only
            if args.app:
                tok = pm.issue_token(peer)
                term.write(CMD_TOKEN + tok.encode("ascii") + b"\r")
                log(f"pairing: {peer} paired; issued token")
                term.write(EOT)
            else:
                log(f"pairing: {peer} paired via code")
                term.write_line("Paired - go ahead.")
            return True
        wait = pm.record_failure(peer)
        strikes = pm._fails[peer][0]
        left = pm.MAX_TRIES - strikes
        msg = ("Wrong code." if prompted else "This bridge is locked.")
        tail = f" {left} left." if left <= pm.FREE_TRIES else ""
        term.write_line(f"{msg} Type the code from the bridge console.{tail}")
        if args.app:
            term.write(EOT)
        prompted = True
        log(f"pairing: wrong code from {peer} "
            f"(strike {strikes}/{pm.MAX_TRIES}, backoff {wait:.0f}s)")
        time.sleep(min(wait, pm.SLEEP_CAP))
```

Also update the top-of-function paired short-circuit: delete the
`if pm.is_paired(peer): return True` block (lines 442-443) — trust is now proven
by presenting a token, not by IP.

- [ ] **Step 4: Fix the remaining `is_paired` callers**

In `bridge/bridge.py` `main` (lines 830-832), replace the known/new-device note
that calls `pm.is_paired(peer)` with an IP-neutral message:

```python
            if pm:
                note += " · will pair by token or code"
```

Grep to confirm no other `is_paired` references remain:
Run: `cd bridge && grep -n is_paired bridge.py` → expect no output.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd bridge && python3 -m pytest test_pairing_flow.py test_pairing.py -v`
Expected: PASS. Then `python3 -m pytest -q` for the whole suite.

- [ ] **Step 6: Commit**

```bash
git add bridge/bridge.py bridge/test_pairing_flow.py
git commit -m "require_pairing: token-first routing, issue CMD_TOKEN on code success"
```

### Task 2.2: Documentation of the protocol byte

**Files:**
- Modify: `AGENTS.md` (in-band control scheme section)
- Modify: `SECURITY.md` (what persists / how pairing works)

**Interfaces:** none (docs).

- [ ] **Step 1: Update the control-scheme list in `AGENTS.md`**

In the "In-band control scheme" section, add under the existing bytes:

```markdown
- `0x05 <token> CR` — (bridge -> client, app mode) a freshly issued device
  token; the native client writes it to a reserved disk sector and auto-sends
  it as its first line on every future connect, so pairing survives reboots.
  `to_ascii` drops 0x05 from model text, so a reply can't forge it.
```

Update the pairing sentence in the same file to say trust is a client-stored
token (hashes at rest), not a peer IP.

- [ ] **Step 2: Update `SECURITY.md`**

Replace the "Paired peer IPs touch disk" description with: the bridge persists
only SHA-256 hashes of issued device tokens (`paired.json` v2, mode 0600); peer
IPs are logged but never used for trust; tokens are stored plaintext on the
Apple II disk (physical-access threat, accepted).

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md SECURITY.md
git commit -m "Document the CMD_TOKEN frame and token-based pairing"
```

---

## Phase 3 — Disk build: reserve the token sector

### Task 3.1: Reserve and initialize the token sector in `build.sh`

**Files:**
- Create: `apple2gs/reserve_token_sector.py`
- Modify: `apple2gs/build.sh` (after the disk is assembled, before CATALOG)
- Test: manual disk inspection (documented command)

**Interfaces:**
- Produces: `CLAUDE.dsk` with track `$12`/sector `$0F` marked allocated in the
  VTOC and zero-filled (no magic → "no token").
- `reserve_token_sector.py <disk.dsk>` — DOS 3.3 image editor: sets the VTOC
  free-sector bit for T=0x12,S=0x0F to used, zero-fills that sector.

- [ ] **Step 1: Write the reservation helper**

Create `apple2gs/reserve_token_sector.py`:

```python
#!/usr/bin/env python3
"""Reserve the device-token sector (T=0x12 S=0x0F) on a DOS 3.3 disk image so
neither DOS nor dos33fsprogs ever allocates it, and zero it (no token yet).

DOS 3.3: 35 tracks x 16 sectors x 256 bytes. VTOC is track 0x11 sector 0.
The free-sector bitmap starts at VTOC offset 0x38, 4 bytes per track:
bytes [0],[1] = sectors 15..8 / 7..0 as bits (1 = free)."""
import sys

TRACK, SECTOR = 0x12, 0x0F
SECTOR_SIZE = 256
SECTORS_PER_TRACK = 16


def offset(track: int, sector: int) -> int:
    return (track * SECTORS_PER_TRACK + sector) * SECTOR_SIZE


def main(path: str) -> int:
    with open(path, "r+b") as f:
        img = bytearray(f.read())
        vtoc = offset(0x11, 0)
        # bitmap entry for TRACK: 4 bytes at vtoc+0x38+track*4
        bm = vtoc + 0x38 + TRACK * 4
        # sector 15..8 in byte 0 (bit 7..0), 7..0 in byte 1. S=0x0F -> byte0 bit7.
        if SECTOR >= 8:
            img[bm] &= ~(1 << (SECTOR - 8)) & 0xFF
        else:
            img[bm + 1] &= ~(1 << SECTOR) & 0xFF
        # zero the sector itself
        so = offset(TRACK, SECTOR)
        img[so:so + SECTOR_SIZE] = b"\x00" * SECTOR_SIZE
        f.seek(0)
        f.write(img)
    print(f"reserved token sector T={TRACK:#x} S={SECTOR:#x} in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
```

- [ ] **Step 2: Wire it into `build.sh`**

In `apple2gs/build.sh`, after the `BSAVE COBJ8` line and before `CATALOG`
(around line 47-48), add:

```bash
python3 "$(dirname "$0")/reserve_token_sector.py" CLAUDE.dsk
```

- [ ] **Step 3: Build and verify the sector is reserved + zeroed**

Run: `cd apple2gs && ./build.sh`
Then verify the sector is zero-filled:

```bash
python3 - <<'PY'
with open("apple2gs/CLAUDE.dsk","rb") as f: img=f.read()
off=(0x12*16+0x0F)*256
print("sector bytes all zero:", img[off:off+256]==b"\x00"*256)
PY
```

Expected: `sector bytes all zero: True`. Confirm `./build.sh` still prints the
COBJ/COBJ8 catalog and the CI disk-catalog gate still passes
(`grep -q COBJ` on `dos33 ... CATALOG`).

- [ ] **Step 4: Commit**

```bash
git add apple2gs/reserve_token_sector.py apple2gs/build.sh
git commit -m "Reserve and zero the device-token sector at disk build time"
```

---

## Phase 4 — 8-bit client (`apple2/claude2.s`)

Assemble with the project's build; test with MAME Lua. There is no unit harness
for asm — each task ends by asserting behavior via a scripted MAME run whose Lua
reads memory/disk taps, the project's established method.

### Task 4.1: RWTS read/write helper for the token sector

**Files:**
- Modify: `apple2/claude2.s` (new `token_read` / `token_write` routines + IOB + buffer equates)

**Interfaces:**
- Produces:
  - `TOKBUF = $9000` — 256-byte sector buffer.
  - `token_read` — RWTS-reads T=$12,S=$0F into `TOKBUF`; carry clear = ok.
  - `token_write` — RWTS-writes `TOKBUF` to T=$12,S=$0F; carry clear = ok.
  - `tok_valid` — after `token_read`, returns Z=1 (valid) if magic+checksum ok.

- [ ] **Step 1: Add equates and the IOB**

Near the other equates at the top of `apple2/claude2.s` (by `RING = $1F00`,
line 50), add:

```asm
TOKBUF   = $9000        ; token sector buffer (in the free $9000-$95FF gap)
RWTS     = $BD00        ; DOS 3.3 RWTS entry (A/Y -> IOB)
TOKTRK   = $12          ; reserved token track
TOKSEC   = $0F          ; reserved token sector
```

At the end of the file's data area (near `rb_head`/`rb_tail`, line 1570), add a
DOS 3.3 IOB and a small device-characteristics table. Use the standard DOS 3.3
IOB layout; slot/drive/volume are filled from the boot device at runtime by
reusing DOS's current values:

```asm
; --- RWTS IOB (DOS 3.3 standard 17-byte block) ---------------------------
iob:
    .byte $01            ; +0  table type
iob_slot:  .byte $60     ; +1  slot*16 (patched from DOS at boot)
iob_drive: .byte $01     ; +2  drive
iob_vol:   .byte $00     ; +3  volume (0 = match any)
iob_trk:   .byte TOKTRK  ; +4  track
iob_sec:   .byte TOKSEC  ; +5  sector
    .word dct            ; +6  pointer to device characteristics table
    .word TOKBUF         ; +8  buffer
    .word $0000          ; +10 (unused, byte count)
iob_cmd:   .byte $01     ; +12 command: 1=read, 2=write
iob_err:   .byte $00     ; +13 error code
    .byte $00            ; +14 last volume
    .byte $60            ; +15 last slot
    .byte $01            ; +16 last drive
dct:
    .byte $00,$01,$EF,$D8 ; device characteristics table (standard DOS 3.3)
```

- [ ] **Step 2: Patch slot/drive from DOS at boot**

DOS keeps the boot slot/drive; reuse them so the token I/O targets the same
device the client booted from. In the client's early init (near `session_start`
setup, before first use), copy DOS's current IOB slot/drive. Add a routine:

```asm
; Copy boot slot/drive out of DOS's own last-used RWTS IOB so our token I/O
; hits the same physical device. DOS's IOB slot/drive live at $B7E9/$B7EA.
tok_init_dev:
    lda $B7E9            ; DOS last slot (slot*16)
    sta iob_slot
    lda $B7EA            ; DOS last drive
    sta iob_drive
    rts
```

Call `jsr tok_init_dev` once during client startup (near where other one-time
init runs in `session_start`, `claude2.s:1002`+).

- [ ] **Step 3: Write `token_read` / `token_write` / `tok_valid`**

Add near the other serial helpers:

```asm
; RWTS read the token sector into TOKBUF. Carry clear = success.
token_read:
    lda #TOKTRK
    sta iob_trk
    lda #TOKSEC
    sta iob_sec
    lda #$01            ; read
    sta iob_cmd
    jmp rwts_call

; RWTS write TOKBUF to the token sector. Carry clear = success.
token_write:
    lda #TOKTRK
    sta iob_trk
    lda #TOKSEC
    sta iob_sec
    lda #$02            ; write
    sta iob_cmd
    ; fall through

rwts_call:
    lda #<iob
    ldy #>iob
    jsr RWTS            ; A=low, Y=high pointer to IOB
    lda iob_err         ; 0 = ok
    beq @ok
    sec
    rts
@ok:
    clc
    rts

; MAGIC "CLDTK1" at TOKBUF+0..5, len at +6, token at +7, checksum at +7+len.
; Returns Z=1 if valid, Z=0 otherwise. Clobbers A,X,Y.
tok_magic: .byte "CLDTK1"
tok_valid:
    ldx #$00
@m: lda TOKBUF,x
    cmp tok_magic,x
    bne @bad
    inx
    cpx #$06
    bne @m
    ; checksum: sum bytes [0 .. 7+len-1] must equal byte [7+len]
    lda TOKBUF+6        ; len
    clc
    adc #$07            ; index of checksum byte = 7+len
    tay                 ; Y = checksum index
    ldx #$00
    lda #$00
@s: clc
    adc TOKBUF,x
    inx
    cpx TOKBUF+6        ; note: sum over magic+len+token = 0..(6+len)= (7+len) bytes
    ; (loop bound handled below)
    bne @s_continue
@s_continue:
    ; Simpler exact loop below replaces the above approximation.
    ; (see Step 4 note; implement the precise checksum in Step 4)
@bad:
    lda #$01            ; force Z=0
    rts
```

- [ ] **Step 4: Replace the checksum stub with the exact loop**

The Step 3 checksum sketch is intentionally replaced here with the precise
version — sum bytes `[0 .. 6+len]` (that's magic 6 + len 1 + token `len`) and
compare to byte `[7+len]`:

```asm
tok_valid:
    ldx #$00
@m: lda TOKBUF,x
    cmp tok_magic,x
    bne @bad
    inx
    cpx #$06
    bne @m
    ldx #$00
    lda #$00
    ldy TOKBUF+6        ; Y = len
    ; count of summed bytes = 7 + len (indices 0..6+len)
    sty $06             ; scratch (known-safe ZP)
    ldx #$00
@s: clc
    adc TOKBUF,x
    inx
    cpx #$07            ; summed magic+len (7 bytes) yet?
    bcc @s
    ; now sum the token bytes: indices 7 .. 6+len
    ldy #$00
@t: cpy $06             ; y == len?
    beq @done
    clc
    adc TOKBUF+7,y
    iny
    bne @t
@done:
    ; A = checksum of [0..6+len]; compare to stored checksum at [7+len]
    ldy $06
    cmp TOKBUF+7,y      ; TOKBUF+7+len
    bne @bad
    lda #$00            ; Z=1 valid
    rts
@bad:
    lda #$01            ; Z=0 invalid
    rts
```

- [ ] **Step 5: Assemble to catch syntax/branch errors**

Run: `cd apple2gs && ./build.sh`
Expected: assembles COBJ8 with no `ca65`/`ld65` errors. (Behavior is exercised
in Task 4.2's MAME run.)

- [ ] **Step 6: Commit**

```bash
git add apple2/claude2.s
git commit -m "8-bit: RWTS token-sector read/write + validity check"
```

### Task 4.2: Auto-send stored token; capture issued token

**Files:**
- Modify: `apple2/claude2.s` (`session_start` after the CR probe, line 1016; recv path `recv_reply` line 1364; add `CMD_TOKEN=$05` handling)
- Test: `apple2gs/tests/` MAME Lua script (create `token_pair.lua`)

**Interfaces:**
- Consumes: `token_read`, `tok_valid`, `token_write`, `TOKBUF`, `send` path
  (`aciaput`), `getbyte`.
- Produces: on connect, if `tok_valid`, transmit the token + CR before entering
  the main loop; on receiving `CMD_TOKEN`, buffer the token into `TOKBUF` in the
  sector layout and `token_write`.

- [ ] **Step 1: Auto-send at session start**

In `apple2/claude2.s` `session_start`, right after the CR probe
(`lda #$0D / jsr aciaput`, line 1016-1017), add:

```asm
    jsr tok_init_dev
    jsr token_read
    bcs @notok          ; read failed (write-protected/no disk): skip
    jsr tok_valid
    bne @notok          ; no valid token: fall through to code prompt
    ; send TOKBUF+7 .. +7+len-1 followed by CR
    ldx #$00
    ldy TOKBUF+6        ; len
@snd:
    cpx TOKBUF+6
    beq @sndcr
    lda TOKBUF+7,x
    jsr aciaput
    inx
    bne @snd
@sndcr:
    lda #$0D
    jsr aciaput
@notok:
```

- [ ] **Step 2: Handle `CMD_TOKEN` in the receive path**

Add the equate near the other CMD_* equates: `CMD_TOKEN = $05`. In `recv_reply`
(`claude2.s:1364`+), where control codes are dispatched (alongside the
`CMD_HEADER=$0E` case at line 1401-1402), add a branch:

```asm
    cmp #CMD_TOKEN
    beq do_token
```

Add `do_token` (mirrors `do_header`'s CR-terminated read, but writes the sector):

```asm
; Read a CR-terminated token, frame it into TOKBUF in the on-disk layout,
; and RWTS-write it. rb_poll is called by getbyte, so the ring can't overflow.
do_token:
    ; magic
    ldx #$00
@wm: lda tok_magic,x
    sta TOKBUF,x
    inx
    cpx #$06
    bne @wm
    ; read token bytes into TOKBUF+7 until CR, counting length in X
    ldx #$00
@rt: jsr getbyte
    cmp #$0D
    beq @fin
    and #$7F
    sta TOKBUF+7,x
    inx
    cpx #$28            ; hard cap 40 to never overrun (token is 32)
    bcc @rt
@fin:
    stx TOKBUF+6        ; length
    ; checksum over [0 .. 6+len]
    lda #$00
    ldy #$00
@ck1: clc
    adc TOKBUF,y
    iny
    cpy #$07
    bcc @ck1
    ldy #$00
@ck2: cpy TOKBUF+6
    beq @ckdone
    clc
    adc TOKBUF+7,y
    iny
    bne @ck2
@ckdone:
    ldy TOKBUF+6
    sta TOKBUF+7,y     ; store checksum after the token
    jsr token_write    ; ignore carry: write-protect just means no persistence
    rts
```

- [ ] **Step 3: Write the MAME Lua pairing test**

Create `apple2gs/tests/token_pair.lua` following the existing MAME-script
pattern in the repo (same structure as the current autoboot scripts):

```lua
-- Boots claude2 under MAME with an SSC wired to the bridge socket, drives the
-- pairing code, then asserts the token sector was written and, on a second
-- session, auto-sent. Uses memory taps on TOKBUF ($9000) and a disk read-back.
-- (Fill the boot/type/snapshot calls from the repo's existing autoboot script;
-- this asserts the token-specific state.)

local TOKBUF = 0x9000
local mem = manager.machine.devices[":maincpu"].spaces["program"]

local function magic_present()
  local s = ""
  for i = 0, 5 do s = s .. string.char(mem:read_u8(TOKBUF + i)) end
  return s == "CLDTK1"
end

-- after typing the pairing code and waiting for the CMD_TOKEN frame:
emu.wait(3.0)
assert(magic_present(), "token magic not written to TOKBUF after pairing")
print("PASS: token written after code entry")
```

- [ ] **Step 4: Run the scripted MAME pairing session**

Start the bridge, then run MAME with the SSC wired to it and the Lua script:

```bash
cd bridge && python3 bridge.py --telnet --port 6502 --app --backend chat --cols 80 &
cd apple2gs && mame apple2ee -sl2 ssc -sl2:ssc:rs232 null_modem \
  -bitbanger socket.127.0.0.1:6502 -flop1 CLAUDE.dsk \
  -autoboot_script tests/token_pair.lua
```

Expected: the Lua prints `PASS: token written after code entry`. Then re-run
without `--clear-paired` and confirm the second boot does NOT show the LOCKED
prompt (token auto-sent). Kill the bridge when done.

- [ ] **Step 5: Commit**

```bash
git add apple2/claude2.s apple2gs/tests/token_pair.lua
git commit -m "8-bit: auto-send stored token, capture and persist issued token"
```

---

## Phase 5 — GS client (`apple2gs/claude.s`)

Same logic as Phase 4, 65816 dialect. RWTS on the IIgs under DOS 3.3 works the
same; keep register widths explicit.

### Task 5.1: RWTS helper (65816)

**Files:**
- Modify: `apple2gs/claude.s` (equates near `RBUF = $1E00` line ~2755; helpers near `sccput`)

**Interfaces:** mirror Task 4.1: `TOKBUF=$9000`, `token_read`, `token_write`, `tok_valid`, IOB, `tok_init_dev`.

- [ ] **Step 1: Add equates, IOB, and helpers in 65816**

Add the same equates (`TOKBUF`, `RWTS=$BD00`, `TOKTRK`, `TOKSEC`) and the IOB/DCT
data block (identical bytes to Task 4.1 Step 1). RWTS is an 8-bit DOS routine:
call it in emulation-safe 8-bit mode. Wrap the calls so M/X are 8-bit around
RWTS and restored after:

```asm
token_read:
    sep #$30            ; A,X,Y 8-bit for DOS RWTS
    .a8
    .i8
    lda #TOKTRK
    sta iob_trk
    lda #TOKSEC
    sta iob_sec
    lda #$01
    sta iob_cmd
    bra rwts_call

token_write:
    sep #$30
    .a8
    .i8
    lda #TOKTRK
    sta iob_trk
    lda #TOKSEC
    sta iob_sec
    lda #$02
    sta iob_cmd
rwts_call:
    lda #<iob
    ldy #>iob
    jsr RWTS
    lda iob_err
    php                 ; save Z
    rep #$30            ; back to 16-bit
    .a16
    .i16
    plp
    beq @ok
    sec
    rts
@ok:
    clc
    rts
```

`tok_valid`, `tok_init_dev`, and `tok_magic` are byte-identical to Task 4.1
(they run in 8-bit mode; put `sep #$30`/`.a8`/`.i8` at entry and
`rep #$30`/`.a16`/`.i16` before `rts`). Reuse `$06` scratch (known-safe ZP).

- [ ] **Step 2: Assemble**

Run: `cd apple2gs && ./build.sh`
Expected: COBJ assembles with no width/`BRK` mis-assembly (verify no stray
8/16-bit mismatch warnings; the `.a8/.a16` annotations after `jsr RWTS` are
mandatory per the project's 65816 rule).

- [ ] **Step 3: Commit**

```bash
git add apple2gs/claude.s
git commit -m "GS: RWTS token-sector read/write + validity (65816, width-safe)"
```

### Task 5.2: Auto-send + capture on the GS

**Files:**
- Modify: `apple2gs/claude.s` (`session_start` after CR probe line 633; `recv_reply` control dispatch line ~1627; add `CMD_TOKEN=$05` + `do_token`)
- Test: reuse the MAME approach where possible; primary check via KEGS end-to-end (Phase 6). GS auto-run under MAME is not scripted in-repo, so this task's gate is KEGS.

**Interfaces:** mirror Task 4.2 using `sccput`/`getbyte`.

- [ ] **Step 1: Auto-send at session start**

After the CR probe (`lda #$0D / jsr sccput`, `claude.s:633-636`), add the same
read-validate-send sequence as Task 4.2 Step 1, but transmit with `sccput` and
keep register widths 8-bit for the byte loop:

```asm
    jsr tok_init_dev
    jsr token_read
    bcs @notok
    jsr tok_valid
    bne @notok
    sep #$20
    .a8
    ldx #$00
@snd:
    cpx TOKBUF+6
    beq @sndcr
    lda TOKBUF+7,x
    jsr sccput
    inx
    bra @snd
@sndcr:
    lda #$0D
    jsr sccput
    rep #$20
    .a16
@notok:
```

(If X is 16-bit here, guard the index compare accordingly; token len < 256 so an
8-bit X via `sep #$10`/`.i8` around the loop is simplest — mirror the widths used
by the neighboring send code in `send_line` at `claude.s:897`.)

- [ ] **Step 2: Add `CMD_TOKEN` dispatch + `do_token`**

Add `CMD_TOKEN = $05` near the other CMD equates. In `recv_reply`'s control
dispatch (by the `CMD_HEADER` branch at `claude.s:1627-1628`), add
`cmp #CMD_TOKEN / beq do_token`. Implement `do_token` identically to Task 4.2
Step 2 using `getbyte` and `token_write`, in 8-bit mode for the byte work.

- [ ] **Step 3: Assemble + preview**

Run: `cd apple2gs && ./build.sh` (assembles), then a KEGS boot (Ctrl-⌘-Reset)
to confirm the client still reaches the menu and Connect works. Full pairing is
verified in Phase 6.

- [ ] **Step 4: Commit**

```bash
git add apple2gs/claude.s
git commit -m "GS: auto-send stored token, capture and persist issued token"
```

---

## Phase 6 — End-to-end verification

### Task 6.1: Full pair-then-reconnect against KEGS and MAME

**Files:** none (verification only); may add notes to `docs/`.

- [ ] **Step 1: Fresh-disk first-run (8-bit, MAME)**

Rebuild the disk (`cd apple2gs && ./build.sh`), start the bridge
(`--telnet --port 6502 --app`), boot claude2 under MAME. Expected: LOCKED prompt
appears; type the pairing code from the bridge console; session proceeds; bridge
logs `paired; issued token`; `paired.json` contains one device with a
`token_sha256` and no plaintext token.

- [ ] **Step 2: Reconnect skips the prompt**

Disconnect and reboot the same MAME disk. Expected: no LOCKED prompt — the client
auto-sends the token; bridge logs `paired via token`. Confirm the reserved sector
holds valid magic:

```bash
python3 - <<'PY'
with open("apple2gs/CLAUDE.dsk","rb") as f: img=f.read()
off=(0x12*16+0x0F)*256
print("magic:", img[off:off+6])
PY
```

Expected: `magic: b'CLDTK1'`.

- [ ] **Step 3: Revoke forces re-pair**

Restart the bridge with `--clear-paired`. Reboot the client. Expected: LOCKED
prompt returns (token no longer matches); enter the code; a new token is issued
and overwrites the sector.

- [ ] **Step 4: GS end-to-end (KEGS)**

Repeat Steps 1-3 on the GS client under KEGS (Ctrl-⌘-Reset to boot
`~/Downloads/CLAUDE.dsk`). Expected: identical behavior.

- [ ] **Step 5: Write-protect fallback**

Boot with the disk image write-protected (or a read-only medium). Expected: the
client still pairs by code each session (RWTS-write fails silently), no crash,
no hang.

- [ ] **Step 6: Full bridge test suite green**

Run: `cd bridge && python3 -m pytest -q`
Expected: all pass, including `test_pairing.py`, `test_pairing_flow.py`,
`test_terminal_iac.py`, `test_error_hygiene.py`, `test_render_markdown.py`,
`test_cancel.py`.

- [ ] **Step 7: Commit any notes**

```bash
git add -A
git commit -m "Verify token pairing end-to-end (KEGS + MAME); write-protect fallback"
```

---

## Self-review notes (author)

- Spec coverage: auth model (T1.3, T2.1), token/hash (T1.1), on-disk format
  (T4.1/T5.1 layout + T3.1 reservation), wire protocol/`CMD_TOKEN` (T2.1, T4.2,
  T5.2), bridge persistence v2 + migration (T1.2), `--clear-paired` revoke (T1.2,
  T6.1), client changes both CPUs (Phase 4/5), build (T3.1), error/fallback
  (T4.2 write ignore, T6.1 Step 5), companion hardening (Phase 0), testing
  (per-task + T6.1), docs (T2.2). No uncovered spec section.
- Type/name consistency: `check_token`, `issue_token`, `token_hash`, `gen_token`,
  `CMD_TOKEN`, `TOKBUF`, `token_read/write`, `tok_valid`, `tok_init_dev`,
  `do_token` used identically across tasks and both clients.
- Known soft spots to watch during execution: exact DOS 3.3 IOB slot/drive
  source addresses ($B7E9/$B7EA) and the RWTS DCT bytes should be confirmed on
  first assemble+run; the checksum loop bounds (magic+len+token) are the most
  error-prone asm — the MAME tap in T4.2 is the guard.
```
