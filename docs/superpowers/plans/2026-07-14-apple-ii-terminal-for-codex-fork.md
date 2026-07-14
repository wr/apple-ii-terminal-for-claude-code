# Apple II Terminal for Codex Fork Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an independent public sibling repository whose authenticated Codex CLI bridge and Apple II clients ship as a tested `CODEX.dsk` for FloppyEmu and two-sided physical media.

**Architecture:** Duplicate the Claude repository with its history, then convert it in place into a Codex-only product. Keep the serial protocol, transport, pairing, renderer, and proven hardware loops; replace the backend with one `CodexBackend`, isolate persisted state, rebrand both native clients, generate original Patch art, and publish one two-client DOS 3.3 image.

**Tech Stack:** Python 3.10+, Codex CLI 0.144.1+, pytest, ca65/ld65, 6502/65816 assembly, DOS 3.3, Pillow-free generated pixel assets, ShellCheck, MAME, KEGS, GitHub Actions

## Global Constraints

- The target is an independent sibling at `github.com/wr/apple-ii-terminal-for-codex`; preserve upstream commit history and MIT notice.
- The product is Codex-only; remove the Anthropic API backend, Anthropic dependency, Clawd art, and Claude demo media.
- Assume `codex` is already installed and authenticated; never read, copy, or accept credentials.
- Require Codex CLI 0.144.1 or newer and an explicit existing Git `--workdir`.
- Default to `sandbox_mode="workspace-write"` and `approval_policy="never"`; support only `--sandbox workspace-write` and `--sandbox read-only`.
- Feed prompts through stdin, never argv. Do not use `--ephemeral` or `--skip-git-repo-check`.
- Keep the current printable-ASCII plus control-byte protocol unchanged.
- Keep process-group cancellation, pairing limits, atomic token storage, serial polling, and all real-hardware workarounds unchanged.
- Isolate host state under `codex-ii-terminal` and `appleii-codex`; use disk token magic `CDXTK1` at track `$12`, sector `$0F`.
- Use phonebook entry 1, TCP port 6401, IIgs DTMF `2-6-3-3-9`, and 8-bit pulse digits `2-6-3`.
- Ship exactly `CODEX.dsk`, 143,360 bytes, with binary catalog entries `CODEX` and `CODEX8`.
- Keep Python 3.10 and 3.14 CI, immutable GitHub Action revisions, the master-based disk build, and a pinned dos33fsprogs commit.
- No Responses API backend, interactive TUI emulation, approval UI, danger-full-access mode, or combined Claude/Codex disk image.

---

## File map

The implementation takes place in a local sibling clone, expected at `/Users/wells/Projects/appleii-codex`.

- `bridge/backends.py`: Codex CLI version check, argv construction, JSONL mapping, resumption, stderr hygiene, and process-group cancellation.
- `bridge/bridge.py`: Codex-only CLI flags, workdir validation, command routing, banner, header framing, state path, and port 6401.
- `bridge/test_codex_backend.py` and `bridge/fixtures/codex/*.jsonl`: offline backend contract tests.
- `bridge/test_codex_smoke.py`: opt-in authenticated first-turn/resume/cancel test.
- `bridge/test_cancel.py`, `bridge/test_error_hygiene.py`, `tests/test_interrupt.py`: retained lifecycle regressions, renamed for `CodexBackend`.
- `apple2gs/codex.s`, `apple2/codex2.s`: provider identity, dial entry, disk token magic, instructions, and catalog names.
- `apple2gs/codex.cfg`, `apple2/codex2.cfg`: renamed linker configurations with unchanged memory maps.
- `apple2gs/patch_art.py`: hand-authored original Patch frames and storyboard.
- `apple2gs/gen_assets.py`: Patch packing, session mascot, CODEX dial sound, and unchanged palette/font/DOC emitters.
- `apple2gs/preview.py`: Codex labels and Patch preview rendering.
- `apple2gs/build.sh`: build `CODEX` and `CODEX8`, inject them into `CODEX.dsk`, and reserve the token sector.
- `tools/check-release-disk.sh`, `tests/test_release_gate.sh`, `tools/install-sd.sh`: exact artifact/catalog/install checks.
- `README.md`, `SECURITY.md`, `THIRD-PARTY-NOTICES.md`, `NOTICE.md`, `CHANGELOG.md`, `docs/*.md`: user, security, attribution, modem, and physical-disk instructions.
- `.github/workflows/ci.yml`, `.github/workflows/release.yml`: offline CI and tagged artifact publication.

---

### Task 1: Create the independent sibling working repository

**Files:**
- Create repository: `/Users/wells/Projects/appleii-codex`
- Modify: `/Users/wells/Projects/appleii-codex/AGENTS.md`
- Modify: `/Users/wells/Projects/appleii-codex/CLAUDE.md`

**Interfaces:**
- Consumes: approved design commit `646a01c` from `/Users/wells/Projects/appleii-claude`
- Produces: a clean local sibling on branch `main`, with `claude-upstream` pointing at the source and no pushable `origin` yet

- [ ] **Step 1: Verify the source checkpoint**

Run:

```bash
git -C /Users/wells/Projects/appleii-claude status --short
git -C /Users/wells/Projects/appleii-claude rev-parse HEAD
```

Expected: no status output and HEAD `646a01c...` or a later commit containing the approved design.

- [ ] **Step 2: Duplicate the history locally**

Run:

```bash
git clone /Users/wells/Projects/appleii-claude /Users/wells/Projects/appleii-codex
git -C /Users/wells/Projects/appleii-codex remote rename origin claude-upstream
git -C /Users/wells/Projects/appleii-codex remote set-url claude-upstream https://github.com/wr/apple-ii-terminal-for-claude-code.git
git -C /Users/wells/Projects/appleii-codex remote -v
```

Expected: only `claude-upstream` fetch/push URLs are listed. Do not create the public GitHub repository yet.

- [ ] **Step 3: Replace repository-specific agent guidance**

In both `AGENTS.md` and `CLAUDE.md`, retain all hardware landmines, then replace the source-of-truth and product summary with:

```markdown
## Source of truth
- GitHub: github.com/wr/apple-ii-terminal-for-codex
- Branch prefix: wells/
- PR mode: none (commit to main, push directly)

## What this is

A bridge that turns a real Apple II into a terminal for an already-installed
and authenticated Codex CLI. The host bridge runs `codex exec --json`, while
the IIgs and 8-bit clients share one bootable `CODEX.dsk`.
```

Also replace every operational `CLAUDE.dsk`, `COBJ`, `COBJ8`, port 6400, entry 0, and `CLDTK1` reference with the exact Codex values in Global Constraints. Historical warnings may still mention the Claude upstream when explaining provenance.

- [ ] **Step 4: Audit the guidance and commit**

Run:

```bash
rg -n 'github.com/wr/apple-ii-terminal-for-claude-code|CLAUDE\.dsk|COBJ8?|CLDTK1|port 6400|entry 0' AGENTS.md CLAUDE.md
git add AGENTS.md CLAUDE.md
git commit -m "chore: initialize Codex sibling repository"
```

Expected: `rg` finds only explicitly labeled upstream/history references; commit succeeds.

---

### Task 2: Implement the offline Codex CLI contract with TDD

**Files:**
- Create: `bridge/fixtures/codex/first-turn.jsonl`
- Create: `bridge/fixtures/codex/tool-turn.jsonl`
- Create: `bridge/fixtures/codex/failed-turn.jsonl`
- Create: `bridge/test_codex_backend.py`
- Modify: `bridge/backends.py`

**Interfaces:**
- Produces: `codex_version(codex_bin: str = "codex") -> tuple[int, int, int] | None`
- Produces: `CodexBackend(cols: int, model: str | None, codex_bin: str, cwd: str, sandbox: str, show_tools: bool)`
- Produces: `CodexBackend._build_cmd() -> list[str]`, `_render_event(event: dict) -> Iterator[str]`, `header()`, `footer()`, `reset()`
- Preserves: `Backend`, `_kill_process_group`, `abbrev_cwd`

- [ ] **Step 1: Add representative golden JSONL fixtures**

Create `bridge/fixtures/codex/first-turn.jsonl`:

```jsonl
{"type":"thread.started","thread_id":"019-test-thread"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_1","type":"reasoning","text":"private"}}
{"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"Done. I changed one file."}}
{"type":"turn.completed","usage":{"input_tokens":41,"cached_input_tokens":0,"output_tokens":9}}
```

Create `bridge/fixtures/codex/tool-turn.jsonl`:

```jsonl
{"type":"item.started","item":{"id":"cmd_1","type":"command_execution","command":"pytest -q"}}
{"type":"item.completed","item":{"id":"cmd_1","type":"command_execution","command":"pytest -q","exit_code":0,"aggregated_output":"2 passed"}}
{"type":"item.completed","item":{"id":"file_1","type":"file_change","changes":[{"path":"bridge.py","kind":"update"}],"status":"completed"}}
{"type":"item.completed","item":{"id":"web_1","type":"web_search","query":"Codex docs"}}
{"type":"item.completed","item":{"id":"mcp_1","type":"mcp_tool_call","server":"github","tool":"get_file","status":"completed"}}
{"type":"item.completed","item":{"id":"plan_1","type":"todo_list","items":[{"text":"Run tests","completed":true}]}}
{"type":"item.completed","item":{"id":"answer_1","type":"agent_message","text":"All tests pass."}}
{"type":"turn.completed","usage":{"output_tokens":4}}
```

Create `bridge/fixtures/codex/failed-turn.jsonl`:

```jsonl
{"type":"turn.started"}
not-json
{"type":"future.event","payload":{"secret":"ignored"}}
{"type":"turn.failed","error":{"message":"request failed with bearer sk-secret-value"}}
```

- [ ] **Step 2: Write failing command, version, event, and metadata tests**

Create `bridge/test_codex_backend.py` with:

```python
import json
from pathlib import Path

import pytest

import backends

FIXTURES = Path(__file__).parent / "fixtures" / "codex"


def backend(**overrides):
    values = dict(cols=80, model=None, codex_bin="codex", cwd="/tmp/repo",
                  sandbox="workspace-write", show_tools=False)
    values.update(overrides)
    return backends.CodexBackend(**values)


def test_first_turn_argv_uses_stdin_and_fail_closed_config():
    assert backend()._build_cmd() == [
        "codex", "exec", "--json", "--color", "never",
        "-c", 'sandbox_mode="workspace-write"',
        "-c", 'approval_policy="never"', "-",
    ]


def test_resume_argv_repeats_model_and_permissions():
    be = backend(model="gpt-5.4", sandbox="read-only")
    be._thread_id = "019-test-thread"
    assert be._build_cmd() == [
        "codex", "exec", "resume", "--json", "--color", "never",
        "-c", 'sandbox_mode="read-only"',
        "-c", 'approval_policy="never"', "--model", "gpt-5.4",
        "019-test-thread", "-",
    ]


@pytest.mark.parametrize("raw, expected", [
    ("codex-cli 0.144.1", (0, 144, 1)),
    ("codex-cli 1.2.3\n", (1, 2, 3)),
    ("garbage", None),
])
def test_parse_codex_version(raw, expected):
    assert backends._parse_codex_version(raw) == expected


def test_first_turn_fixture_emits_only_agent_message_and_saves_metadata(capsys):
    be = backend()
    output = []
    for raw in (FIXTURES / "first-turn.jsonl").read_text().splitlines():
        output.extend(be._render_event(json.loads(raw)))
    assert "".join(output) == "Done. I changed one file."
    assert be._thread_id == "019-test-thread"
    assert be._last_output_tokens == 9
    assert "private" not in "".join(output)


def test_tool_fixture_is_quiet_in_app_and_summarized_in_raw_mode():
    events = [json.loads(line) for line in
              (FIXTURES / "tool-turn.jsonl").read_text().splitlines()]
    quiet = backend(show_tools=False)
    loud = backend(show_tools=True)
    assert "".join(x for e in events for x in quiet._render_event(e)) == "All tests pass."
    rendered = "".join(x for e in events for x in loud._render_event(e))
    assert "pytest -q" in rendered
    assert "bridge.py" in rendered
    assert "All tests pass." in rendered


def test_header_and_footer_are_codex_specific(monkeypatch):
    monkeypatch.setattr(backends, "codex_version", lambda _bin: (0, 144, 1))
    be = backend(model="gpt-5.4", cwd="/tmp/repo")
    be._last_duration_ms = 2300
    be._last_output_tokens = 1200
    assert be.header() == ("Codex CLI v0.144.1", "gpt-5.4", "/tmp/repo")
    assert be.footer() == "Worked for 2s - 1.2k tokens"
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
python3 -m pytest -q bridge/test_codex_backend.py
```

Expected: collection or test failures because `CodexBackend` and `_parse_codex_version` do not exist.

- [ ] **Step 4: Replace provider-specific backend code**

Remove `ChatBackend`, `CodeBackend`, Claude model/account probes, and `TERMINAL_SYSTEM` from `bridge/backends.py`. Retain `Backend`, `abbrev_cwd`, `_process_group_exists`, and `_kill_process_group`. Add:

```python
MIN_CODEX_VERSION = (0, 144, 1)


def _parse_codex_version(raw: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", raw)
    return tuple(map(int, match.groups())) if match else None


def codex_version(codex_bin: str = "codex") -> tuple[int, int, int] | None:
    try:
        result = subprocess.run([codex_bin, "--version"], capture_output=True,
                                text=True, timeout=10, check=False)
    except OSError:
        return None
    return _parse_codex_version(result.stdout)


class CodexBackend(Backend):
    name = "codex"

    def __init__(self, cols: int, model: str | None, codex_bin: str,
                 cwd: str, sandbox: str, show_tools: bool) -> None:
        self._cols = cols
        self._model = model
        self._bin = codex_bin
        self._cwd = cwd
        self._sandbox = sandbox
        self._show_tools = show_tools
        self._thread_id: str | None = None
        self._proc: subprocess.Popen | None = None
        self._state_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._cancelled = False
        self._last_duration_ms: int | None = None
        self._last_output_tokens: int | None = None
        self._turn_started: float | None = None

    def _build_cmd(self) -> list[str]:
        cmd = [self._bin, "exec"]
        if self._thread_id:
            cmd.append("resume")
        cmd += ["--json", "--color", "never",
                "-c", f'sandbox_mode="{self._sandbox}"',
                "-c", 'approval_policy="never"']
        if self._model:
            cmd += ["--model", self._model]
        if self._thread_id:
            cmd.append(self._thread_id)
        cmd.append("-")
        return cmd

    def reset(self) -> None:
        self._thread_id = None

    def header(self) -> tuple[str, ...]:
        version = codex_version(self._bin)
        label = ".".join(map(str, version)) if version else "?"
        return (f"Codex CLI v{label}", self._model or "default model",
                abbrev_cwd(self._cwd))

    def footer(self) -> str | None:
        if self._last_duration_ms is None:
            return None
        seconds = round(self._last_duration_ms / 1000)
        elapsed = (f"{seconds // 60}m {seconds % 60}s"
                   if seconds >= 60 else f"{seconds}s")
        footer = f"Worked for {elapsed}"
        if self._last_output_tokens:
            tokens = (f"{self._last_output_tokens / 1000:.1f}".rstrip("0").rstrip(".") + "k"
                      if self._last_output_tokens >= 1000
                      else str(self._last_output_tokens))
            footer += f" - {tokens} tokens"
        return footer

    def _render_event(self, event: dict) -> Iterator[str]:
        etype = event.get("type")
        if etype == "thread.started":
            self._thread_id = event.get("thread_id") or self._thread_id
        elif etype == "turn.started":
            self._turn_started = time.monotonic()
        elif etype == "turn.completed":
            usage = event.get("usage") or {}
            self._last_output_tokens = usage.get("output_tokens")
        elif etype in ("turn.failed", "error"):
            yield "\n[Codex request failed; see the bridge console]"
        elif etype in ("item.started", "item.completed"):
            item = event.get("item") or {}
            kind = item.get("type")
            if etype == "item.completed" and kind == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    yield text
            elif self._show_tools:
                summary = self._tool_summary(item)
                if summary:
                    yield f"[{summary}]\n"

    def _tool_summary(self, item: dict) -> str | None:
        kind = item.get("type")
        if kind == "command_execution":
            value = item.get("command") or "command"
        elif kind == "file_change":
            changes = item.get("changes") or []
            value = f"changed {changes[0].get('path', 'file')}" if changes else "changed file"
        elif kind == "web_search":
            value = f"searched {item.get('query', 'web')}"
        elif kind == "mcp_tool_call":
            value = f"{item.get('server', 'MCP')}/{item.get('tool', 'tool')}"
        elif kind == "todo_list":
            entries = item.get("items") or []
            complete = sum(bool(entry.get("completed")) for entry in entries)
            value = f"plan {complete}/{len(entries)}"
        else:
            return None
        limit = max(8, self._cols - 4)
        return value if len(value) <= limit else value[:limit - 3] + "..."
```

- [ ] **Step 5: Run the focused tests and commit**

Run:

```bash
python3 -m pytest -q bridge/test_codex_backend.py
git add bridge/backends.py bridge/test_codex_backend.py bridge/fixtures/codex
git commit -m "feat: add Codex JSONL backend contract"
```

Expected: all focused tests pass and the commit succeeds.

---

### Task 3: Add subprocess streaming, stderr hygiene, cancellation, and resume fallback

**Files:**
- Modify: `bridge/backends.py`
- Modify: `bridge/test_codex_backend.py`
- Modify: `bridge/test_cancel.py`
- Modify: `bridge/test_error_hygiene.py`
- Create: `bridge/fixtures/fake_codex.py`

**Interfaces:**
- Produces: `CodexBackend.begin_turn()`, `stream(user_text: str)`, and `cancel()`
- Consumes: `_kill_process_group(proc, grace=2.0)`, `_build_cmd()`, `_render_event()`
- Guarantees: prompt is written only to stdin; stderr is drained concurrently; cancellation kills the whole process group

- [ ] **Step 1: Create a controllable fake Codex executable**

Create `bridge/fixtures/fake_codex.py`:

```python
#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time

if sys.argv[1:] == ["--version"]:
    print("codex-cli 0.144.1")
    raise SystemExit(0)

prompt = sys.stdin.read()
record = os.environ.get("FAKE_CODEX_RECORD")
if record:
    with open(record, "w", encoding="utf-8") as handle:
        json.dump({"argv": sys.argv[1:], "stdin": prompt}, handle)
mode = os.environ.get("FAKE_CODEX_MODE", "ok")
print(json.dumps({"type": "thread.started", "thread_id": "fake-thread"}), flush=True)
print(json.dumps({"type": "turn.started"}), flush=True)
if mode == "child":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(999)"])
    print(child.pid, file=sys.stderr, flush=True)
    time.sleep(999)
elif mode == "auth":
    print("Not authenticated. Run codex login. token=secret", file=sys.stderr)
    raise SystemExit(1)
elif mode == "resume-fail" and "resume" in sys.argv:
    print("thread cannot be resumed", file=sys.stderr)
    raise SystemExit(1)
else:
    print(json.dumps({"type": "item.completed", "item": {
        "type": "agent_message", "text": f"received:{prompt}"}}), flush=True)
    print(json.dumps({"type": "turn.completed", "usage": {"output_tokens": 3}}), flush=True)
```

- [ ] **Step 2: Add failing integration and lifecycle tests**

Add tests that invoke the fake executable via `sys.executable` plus script path, asserting:

```python
def test_stream_sends_prompt_only_on_stdin(tmp_path, monkeypatch):
    record = tmp_path / "record.json"
    monkeypatch.setenv("FAKE_CODEX_RECORD", str(record))
    be = backend(codex_bin=str(FIXTURES / "fake_codex.py"), cwd=str(tmp_path))
    be.begin_turn()
    assert "".join(be.stream("secret prompt")) == "received:secret prompt"
    saved = json.loads(record.read_text())
    assert saved["stdin"] == "secret prompt"
    assert "secret prompt" not in saved["argv"]


def test_auth_error_is_short_and_secret_free(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_CODEX_MODE", "auth")
    be = backend(codex_bin=str(FIXTURES / "fake_codex.py"), cwd=str(tmp_path))
    output = "".join(be.stream("hello"))
    assert output == "\n[Codex is not logged in; run codex login on the host]"
    assert "secret" not in output
    assert "Not authenticated" in capsys.readouterr().err


def test_failed_resume_clears_thread_and_explains_next_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_MODE", "resume-fail")
    be = backend(codex_bin=str(FIXTURES / "fake_codex.py"), cwd=str(tmp_path))
    be._thread_id = "fake-thread"
    output = "".join(be.stream("continue"))
    assert "next prompt starts a fresh thread" in output
    assert be._thread_id is None
```

Adapt the existing process-group tests to instantiate `CodexBackend`; add a test that starts fake mode `child`, calls `cancel()`, and proves both leader and child PIDs disappear.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
chmod +x bridge/fixtures/fake_codex.py
python3 -m pytest -q bridge/test_codex_backend.py bridge/test_cancel.py bridge/test_error_hygiene.py
```

Expected: new tests fail because `stream()`, `cancel()`, and error classification are incomplete.

- [ ] **Step 4: Implement the subprocess lifecycle**

Implement `begin_turn()` and `cancel()` using the retained lock/event pattern:

```python
def begin_turn(self) -> None:
    with self._state_lock:
        self._cancelled = False
        self._cancel_event.clear()

def cancel(self) -> None:
    with self._state_lock:
        self._cancelled = True
        self._cancel_event.set()
        proc = self._proc
    if proc is not None:
        _kill_process_group(proc)
```

In `stream()`, launch with `stdin=PIPE`, `stdout=PIPE`, `stderr=PIPE`, `cwd=self._cwd`, `text=True`, `bufsize=1`, and `start_new_session=True`. Publish `_proc` under the lock, immediately kill it if `_cancel_event` already won the race, write `user_text` to `proc.stdin`, close stdin, drain stderr on its own thread, parse stdout line by line, and set `_last_duration_ms` from `time.monotonic()` in `finally`.

Sanitize host-side stderr with:

```python
def _redact_stderr(value: str) -> str:
    value = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[redacted]", value)
    value = re.sub(r"(?i)(token\s*[=:]\s*)[^\s]+", r"\1[redacted]", value)
    return value
```

Classify nonzero exits in this order:

```python
if self._cancelled:
    return
if resumed:
    self._thread_id = None
    yield "\n[Codex could not resume this thread; next prompt starts a fresh thread]"
elif re.search(r"not authenticated|codex login|authentication", stderr, re.I):
    yield "\n[Codex is not logged in; run codex login on the host]"
else:
    yield f"\n[Codex exited {proc.returncode}; see the bridge console]"
```

Log `_redact_stderr(stderr)` only to the host. Malformed JSON and unknown events go to the host log and never stop a successful turn.

- [ ] **Step 5: Verify lifecycle regressions and commit**

Run:

```bash
python3 -m pytest -q bridge/test_codex_backend.py bridge/test_cancel.py bridge/test_error_hygiene.py tests/test_interrupt.py
git add bridge/backends.py bridge/test_codex_backend.py bridge/test_cancel.py bridge/test_error_hygiene.py bridge/fixtures
git commit -m "feat: make Codex turns resumable and cancellable"
```

Expected: all selected tests pass; no fake process survives the suite.

---

### Task 4: Convert the bridge to a Codex-only host application

**Files:**
- Modify: `bridge/bridge.py`
- Create: `bridge/test_codex_bridge.py`
- Modify: `bridge/test_pairing.py`
- Modify: `bridge/test_pairing_flow.py`
- Modify: `tests/test_interrupt.py`
- Delete: `bridge/requirements-chat.txt`
- Modify: `bridge/requirements.txt`

**Interfaces:**
- Produces: `validate_workdir(path: str) -> str`
- Produces: `make_backend(cols: int, args) -> CodexBackend`
- Produces CLI: `--workdir` required, `--sandbox {workspace-write,read-only}`, `--codex-bin`, port 6401
- Preserves: transports, pairing, app framing, Ctrl-C polling, `/new`, `/clear`, `/model`, `/help`, `/quit`, `/exit`

- [ ] **Step 1: Write failing argument, workdir, command, and state tests**

Create `bridge/test_codex_bridge.py`:

```python
import subprocess

import pytest

import bridge


def git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return str(tmp_path)


def test_defaults_are_codex_workspace_write(tmp_path):
    args = bridge.parse_args(["--telnet", "--workdir", git_repo(tmp_path)])
    assert args.port == 6401
    assert args.sandbox == "workspace-write"
    assert args.codex_bin == "codex"
    assert not hasattr(args, "backend")
    assert not hasattr(args, "effort")


@pytest.mark.parametrize("sandbox", ["workspace-write", "read-only"])
def test_supported_sandboxes(tmp_path, sandbox):
    args = bridge.parse_args(["--telnet", "--workdir", git_repo(tmp_path),
                              "--sandbox", sandbox])
    assert args.sandbox == sandbox


def test_workdir_must_exist_and_be_git(tmp_path):
    with pytest.raises(SystemExit):
        bridge.parse_args(["--telnet", "--workdir", str(tmp_path / "missing")])
    with pytest.raises(SystemExit):
        bridge.parse_args(["--telnet", "--workdir", str(tmp_path)])


def test_unknown_slash_command_is_never_forwarded():
    term = type("T", (), {"lines": [], "write_line": lambda self, x: self.lines.append(x)})()
    result = bridge.handle_command("/compact", term, None, None)
    assert result is None
    assert term.lines == ["[unknown command: /compact - try /help]"]


def test_pairing_store_is_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert bridge._pairing_store() == str(tmp_path / "codex-ii-terminal" / "paired.json")
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python3 -m pytest -q bridge/test_codex_bridge.py
```

Expected: failures for old backend flags, port, workdir handling, command forwarding, and state path.

- [ ] **Step 3: Replace the host CLI and routing**

Change `make_backend` to:

```python
def make_backend(cols: int, args) -> CodexBackend:
    return CodexBackend(cols=cols, model=args.model or None,
                        codex_bin=args.codex_bin, cwd=args.workdir,
                        sandbox=args.sandbox, show_tools=not args.app)
```

Add `validate_workdir()` using `Path.resolve(strict=True)` and:

```python
result = subprocess.run(
    ["git", "-C", resolved, "rev-parse", "--is-inside-work-tree"],
    capture_output=True, text=True, check=False,
)
if result.returncode or result.stdout.strip() != "true":
    raise ValueError("--workdir must be an existing Git repository")
```

In `parse_args`, require `--workdir`; add `--sandbox` with exactly the two choices and default `workspace-write`; rename `--claude-bin` to `--codex-bin`; default port to 6401; remove `--backend`, `--effort`, and `--permission-mode`. Convert validation errors to `p.error(str(exc))`.

Replace `/mode` and provider passthrough branches. Unknown slash commands always return the explicit error. `/model` changes `backend._model`; `/new` and `/clear` call `reset()`.

At startup, call `codex_version(args.codex_bin)` once. Exit 2 with a plain diagnostic if it is missing or lower than `(0, 144, 1)`. Do not run a model probe or an authentication request.

- [ ] **Step 4: Rebrand protocol-adjacent host text and state**

Replace banner/header/help strings with `Terminal for Codex`; change `_pairing_store()` to `codex-ii-terminal/paired.json`; keep protocol constants unchanged. Rename fake backend names and expected headers in pairing/interrupt tests from Claude to Codex without weakening assertions.

Set `bridge/requirements.txt` to:

```text
# Core bridge has no third-party dependency. Serial transport is optional.
-r requirements-serial.txt
```

Delete `bridge/requirements-chat.txt` and every Anthropic import/reference.

- [ ] **Step 5: Run the full Python suite and commit**

Run:

```bash
python3 -m pytest -q bridge tests/test_interrupt.py
rg -n 'anthropic|Anthropic|ChatBackend|CodeBackend|--backend|--effort|--permission-mode|claude-ii-terminal|appleii-claude' bridge tests/test_interrupt.py
git add bridge tests/test_interrupt.py
git commit -m "feat: make the host bridge Codex-only"
```

Expected: tests pass; `rg` has no matches except comments explicitly naming removed compatibility.

---

### Task 5: Rebrand both Apple II clients and isolate dial/token behavior

**Files:**
- Rename: `apple2gs/claude.s` to `apple2gs/codex.s`
- Rename: `apple2gs/claude.cfg` to `apple2gs/codex.cfg`
- Rename: `apple2/claude2.s` to `apple2/codex2.s`
- Rename: `apple2/claude2.cfg` to `apple2/codex2.cfg`
- Modify: `apple2gs/codex.s`
- Modify: `apple2/codex2.s`
- Modify: `tests/fake_modem.py`
- Modify: `apple2gs/tests/token_pair.lua`

**Interfaces:**
- Produces: native dial string `ATDS=1`, token magic `CDXTK1`, titles/URLs/commands for Codex
- Preserves: addresses, memory maps, serial ring polling, DCD logic, local `/quit`, control bytes, token sector/checksum

- [ ] **Step 1: Rename source files without changing behavior**

Run:

```bash
git mv apple2gs/claude.s apple2gs/codex.s
git mv apple2gs/claude.cfg apple2gs/codex.cfg
git mv apple2/claude2.s apple2/codex2.s
git mv apple2/claude2.cfg apple2/codex2.cfg
```

- [ ] **Step 2: Add static identity assertions before editing assembly**

Create `tests/test_codex_identity.py`:

```python
from pathlib import Path


def test_native_clients_have_codex_identity_and_isolated_dial_token():
    files = [Path("apple2gs/codex.s"), Path("apple2/codex2.s")]
    for path in files:
        text = path.read_text()
        assert '"ATDS=1"' in text
        assert '"CDXTK1"' in text
        assert "Terminal for Codex" in text or "TERMINAL FOR CODEX" in text
        assert "github.com/wr/apple-ii-terminal-for-codex" in text
        assert "ATDS=0" not in text
        assert "CLDTK1" not in text
        assert "Claude Code" not in text


def test_native_help_lists_only_local_commands():
    for path in (Path("apple2gs/codex.s"), Path("apple2/codex2.s")):
        text = path.read_text()
        assert "/new /model /help /quit" in text
        assert "/mode" not in text
```

- [ ] **Step 3: Run identity tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_codex_identity.py
```

Expected: failures show every remaining Claude/dial/token string.

- [ ] **Step 4: Replace native identity and commands**

Make exact replacements in both assembly files:

```text
Claude Code                         -> Codex
Terminal for Claude Code            -> Terminal for Codex
TERMINAL FOR CLAUDE CODE            -> TERMINAL FOR CODEX
apple-ii-terminal-for-claude-code   -> apple-ii-terminal-for-codex
ATDS=0                              -> ATDS=1
CLDTK1                              -> CDXTK1
TCP port 6400                       -> TCP port 6401
entry 0                             -> entry 1
COBJ / COBJ8 help names             -> CODEX / CODEX8
/new /mode /help /quit              -> /new /model /help /quit
```

Keep strings within their existing screen-width limits. Update `tests/fake_modem.py` to recognize `ATDS=1`; update token Lua magic and disk filename. Do not alter instruction bodies or polling loops except for literal string lengths and pointers.

- [ ] **Step 5: Assemble both clients and run identity tests**

Run:

```bash
cd apple2gs
python3 gen_assets.py
ca65 --cpu 65816 -o codex.o codex.s
ld65 -C codex.cfg -o codex.obj codex.o
ca65 --cpu 6502 -o ../apple2/codex2.o ../apple2/codex2.s
ld65 -C ../apple2/codex2.cfg -o CODEX8 ../apple2/codex2.o
cd ..
python3 -m pytest -q tests/test_codex_identity.py bridge/test_pairing.py
```

Expected: both link successfully and tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add apple2 apple2gs tests
git commit -m "feat: convert native clients to Codex identity"
```

---

### Task 6: Replace Clawd with original Patch art and CODEX sound cues

**Files:**
- Create: `apple2gs/patch_art.py`
- Modify: `apple2gs/gen_assets.py`
- Modify: `apple2gs/preview.py`
- Modify: `apple2gs/codex.s`
- Modify: `apple2/codex2.s`
- Create: `apple2gs/test_patch_assets.py`
- Delete: `apple2gs/clawd.gif`

**Interfaces:**
- Produces: `PATCH_FRAMES`, `PATCH_SEQUENCE`, `PATCH_HOLD`, `PATCH_SESSION` from `patch_art.py`
- Produces: generated `SPLASH_*`, `splash_data`, `splash_seq`, and `mascot_data` with the existing assembly interface
- Preserves: 4-color 640-mode palette, existing splash renderer, static GS session mascot, blinking 8-bit menu mascot

- [ ] **Step 1: Define the original hand-authored Patch frame contract**

Create `apple2gs/patch_art.py` with four-color cell art (`.` black, `S` shadow, `C` coral, `G` platinum, `K` cutout). Use a 28x16 canvas for these named poses:

```python
PATCH_FRAMES = {
    "sleep": (
        "............................",
        "............................",
        ".........GGGGGGGG...........",
        "........GGKKGGKKGG..........",
        "........GGGGGGGGGG..........",
        "...........GG...............",
        "......CCCCCCCCCCCCCCCC......",
        "......CSSSSSSSSSSSSSSC......",
        "......CCCCCCCCCCCCCCCC......",
        ".........CC......CC.........",
        ".........CC......CC.........",
        "............................",
        "............................",
        "............................",
        "............................",
        "............................",
    ),
    "awake": (
        ".........GGGGGGGG...........",
        "........GGKKGGKKGG..........",
        "........GGGGGGGGGG..........",
        "...........GG...............",
        "....CCCCCCCCCCCCCCCCCCCC....",
        "....CSSSSSSSSSSSSSSSSSSC....",
        "....CCCCCCCCCCCCCCCCCCCC....",
        ".......CC..........CC.......",
        ".......CC..........CC.......",
        "............................",
        "............................",
        "............................",
        "............................",
        "............................",
        "............................",
        "............................",
    ),
    "typing_a": (
        "...........GGGGGGGG.........",
        "..........GGKKGGKKGG........",
        "..........GGGGGGGGGG........",
        ".............GG.............",
        "......CCCCCCCCCCCCCCCC......",
        "......CSSSSSSSSSSSSSSC......",
        "......CCCCCCCCCCCCCCCC......",
        ".....CC............CC.......",
        "....CCGGGGGGGGGGGGGGCC......",
        "......GGGGGGGGGGGGGG........",
        ".........CC......CC.........",
        ".........CC......CC.........",
        "............................",
        "............................",
        "............................",
        "............................",
    ),
    "typing_b": (
        "...........GGGGGGGG.........",
        "..........GGKKGGKKGG........",
        "..........GGGGGGGGGG........",
        ".............GG.............",
        "......CCCCCCCCCCCCCCCC......",
        "......CSSSSSSSSSSSSSSC......",
        "......CCCCCCCCCCCCCCCC......",
        ".......CC..........CC.......",
        "......CCGGGGGGGGGGGGCC......",
        "........GGGGGGGGGGGG........",
        ".........CC......CC.........",
        ".........CC......CC.........",
        "............................",
        "............................",
        "............................",
        "............................",
    ),
}

PATCH_SEQUENCE = (
    ("sleep", 24), ("awake", 10), ("typing_a", 5), ("typing_b", 5),
    ("typing_a", 5), ("typing_b", 5), ("awake", 12), ("sleep", 30),
)
PATCH_HOLD = "awake"
PATCH_SESSION = "awake"
```

These exact cells are the first shippable Patch implementation and are original project artwork. Visual QA in Step 5 can refine individual cells and timing while keeping dimensions, names, colors, and story beats fixed.

- [ ] **Step 2: Write failing asset tests**

Create `apple2gs/test_patch_assets.py`:

```python
from patch_art import PATCH_FRAMES, PATCH_HOLD, PATCH_SEQUENCE, PATCH_SESSION


def test_patch_frames_have_one_640_packable_geometry():
    shapes = {(len(frame), len(frame[0])) for frame in PATCH_FRAMES.values()}
    assert shapes == {(16, 28)}
    assert all(len(row) == 28 for frame in PATCH_FRAMES.values() for row in frame)
    assert all(set(row) <= set(".SCGK") for frame in PATCH_FRAMES.values() for row in frame)


def test_storyboard_references_real_frames_and_has_typing_motion():
    assert PATCH_HOLD in PATCH_FRAMES
    assert PATCH_SESSION in PATCH_FRAMES
    assert {name for name, _duration in PATCH_SEQUENCE} <= PATCH_FRAMES.keys()
    assert {name for name, _duration in PATCH_SEQUENCE if name.startswith("typing_")} == {
        "typing_a", "typing_b"
    }
```

- [ ] **Step 3: Replace the GIF extractor with a deterministic Patch emitter**

Import the Patch constants. Remove Pillow import, `SPLASH_SRC`, sheet substitution, GIF classification, and all Clawd-specific code. Convert each row through:

```python
PATCH_COLORS = {".": 0, "K": 0, "S": 1, "C": 2, "G": 3}


def splash_extract():
    names = list(PATCH_FRAMES)
    frames = [tuple(tuple(PATCH_COLORS[cell] for cell in row)
                    for row in PATCH_FRAMES[name]) for name in names]
    index = {name: position for position, name in enumerate(names)}
    sequence = [(index[name], duration) for name, duration in PATCH_SEQUENCE]
    hold = index[PATCH_HOLD]
    return frames, sequence, 28, 16, hold
```

Update `emit_splash()` to consume the returned hold index instead of appending a GIF-derived frame. Set `MASCOT_FRAMES = [PATCH_FRAMES[PATCH_SESSION]]` and map `S`/`C`/`G` through the existing session palette. Replace `requirements-build.txt` with:

```text
# Asset generation uses only the Python standard library.
```

Run `rg -n 'PIL|Pillow'` to confirm the dependency is gone.

Change `_dial_pair()` to iterate `"26339"`; extend `_DTMF` with digit 6 `(770, 1477)` and 9 `(852, 1477)`. Change the 8-bit pulse sequence to 2, 6, 3 without removing the `rb_poll` call inside every half-cycle.

Replace the 8-bit `mascot_art` with this 16x5 Patch silhouette, preserving the existing eye positions at row 1, columns 4 and 11 so `eyes_close`/`eyes_open` remain correct:

```asm
mascot_art:
        .byte   "    XXXXXXXX    "
        .byte   "   X XXXXXX X   "
        .byte   "  XXXXXXXXXXXX  "
        .byte   "    XX XX XX    "
        .byte   "    XX    XX    "
```

Add this assertion to `tests/test_codex_identity.py`:

```python
def test_8bit_patch_keeps_blink_eye_coordinates():
    text = Path("apple2/codex2.s").read_text()
    assert '.byte   "   X XXXXXX X   "' in text
    assert "adc     #4" in text
    assert "adc     #11" in text
```

- [ ] **Step 4: Run deterministic asset and assembly checks**

Run:

```bash
python3 -m pytest -q apple2gs/test_patch_assets.py
cd apple2gs
python3 gen_assets.py
shasum -a 256 assets.inc > /tmp/patch-assets-1.sha
python3 gen_assets.py
shasum -a 256 assets.inc > /tmp/patch-assets-2.sha
diff -u /tmp/patch-assets-1.sha /tmp/patch-assets-2.sha
ca65 --cpu 65816 -o codex.o codex.s
cd ..
```

Expected: tests pass, hashes match, and assembly succeeds without Pillow installed.

- [ ] **Step 5: Render and inspect the actual SHR geometry**

Run:

```bash
cd apple2gs
python3 preview.py assets.inc patch-preview.png
```

Inspect `patch-preview.png` and `patch-preview_mascot.png` at original size. Adjust only `PATCH_FRAMES` cells or `PATCH_SEQUENCE` durations until Patch reads as a small terminal mechanic, the keyboard motion is legible, no row exceeds the canvas, and the session pose does not animate.

- [ ] **Step 6: Delete Clawd and audit generated assets**

Run:

```bash
git rm apple2gs/clawd.gif
rg -n 'Clawd|clawd|Anthropic|PIL|Pillow|252833' apple2 apple2gs requirements-build.txt
git add apple2 apple2gs requirements-build.txt
git commit -m "feat: add original Patch mascot and Codex sound cues"
```

Expected: `rg` is empty and the commit succeeds.

---

### Task 7: Build and validate the exact `CODEX.dsk` release artifact

**Files:**
- Modify: `apple2gs/build.sh`
- Modify: `apple2gs/hello.bas`
- Modify: `tools/check-release-disk.sh`
- Modify: `tests/test_release_gate.sh`
- Modify: `tools/install-sd.sh`
- Create: `tests/test_disk_token_magic.py`

**Interfaces:**
- Produces: `apple2gs/CODEX.dsk`, exactly 143,360 bytes
- Produces DOS binary files: `CODEX` at `$4000`, `CODEX8` at `$2000`
- Preserves: master image, HELLO ROM detection, token-sector reservation, FloppyEmu in-place push behavior

- [ ] **Step 1: Make the release gate expect the new artifact**

Change defaults to `apple2gs/CODEX.dsk`, require file size 143360, and require catalog entries `CODEX` and `CODEX8`. In `tests/test_release_gate.sh`, delete `CODEX8` from a temporary copy and require rejection.

Add `tests/test_disk_token_magic.py`:

```python
from pathlib import Path

TRACK, SECTOR, SIZE = 0x12, 0x0F, 256


def test_release_disk_token_sector_is_blank_and_reserved():
    image = Path("apple2gs/CODEX.dsk").read_bytes()
    assert len(image) == 143360
    offset = (TRACK * 16 + SECTOR) * SIZE
    assert image[offset:offset + 6] == b"\x00" * 6
    vtoc = (0x11 * 16) * SIZE
    bitmap = vtoc + 0x38 + TRACK * 4
    assert image[bitmap] & 0x80 == 0
```

- [ ] **Step 2: Run release tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_disk_token_magic.py
DOS33FSPROGS=/tmp/dos33fsprogs ./tests/test_release_gate.sh
```

Expected: failures because `CODEX.dsk` does not exist.

- [ ] **Step 3: Change the master-based build**

In `apple2gs/build.sh`, assemble `codex.s`/`codex2.s`, link `codex.obj`/`CODEX8`, copy `codex.obj` to `CODEX`, and inject:

```bash
cp "$BASE" CODEX.dsk
$DOS33 CODEX.dsk UNLOCK HELLO
$DOS33 -y CODEX.dsk DELETE HELLO
$DOS33 -y CODEX.dsk SAVE A HH HELLO
$DOS33 -a 0x4000 CODEX.dsk BSAVE CODEX CODEX
$DOS33 -a 0x2000 CODEX.dsk BSAVE CODEX8 CODEX8
python3 reserve_token_sector.py CODEX.dsk
test "$(wc -c < CODEX.dsk | tr -d ' ')" = 143360
```

Change HELLO to `BRUN CODEX` for IIgs and `BRUN CODEX8` otherwise. Make `COPY_TO_DOWNLOADS=1` copy to `~/Downloads/CODEX.dsk`. Make `tools/install-sd.sh` default to `apple2gs/CODEX.dsk` while still accepting any explicit image path.

- [ ] **Step 4: Build, validate, damage-test, and commit**

Run:

```bash
DOS33FSPROGS=/tmp/dos33fsprogs ./apple2gs/build.sh
DOS33FSPROGS=/tmp/dos33fsprogs ./tools/check-release-disk.sh apple2gs/CODEX.dsk
DOS33FSPROGS=/tmp/dos33fsprogs ./tests/test_release_gate.sh apple2gs/CODEX.dsk
python3 -m pytest -q tests/test_disk_token_magic.py
shasum -a 256 apple2gs/CODEX.dsk
git add apple2gs tools tests
git commit -m "build: produce two-client CODEX disk image"
```

Expected: catalog contains `CODEX` and `CODEX8`; damaged copy fails; disk size and token reservation pass; checksum prints.

---

### Task 8: Rewrite public docs, attribution, and security guidance

**Files:**
- Modify: `README.md`
- Modify: `SECURITY.md`
- Modify: `THIRD-PARTY-NOTICES.md`
- Modify: `CHANGELOG.md`
- Create: `NOTICE.md`
- Modify: `docs/COMPATIBILITY.md`
- Modify: `docs/MODEM-SETUP.md`
- Modify: `apple2/TERMINAL-SETUP.md`
- Delete: `docs/demo.gif`
- Create: `docs/PHYSICAL-DISK.md`

**Interfaces:**
- Produces: install instructions assuming `codex login` is already complete
- Produces: trusted-LAN, bearer-token, plaintext-telnet, workspace-write, and fail-closed approval disclosures
- Produces: upstream modification notice and third-party boundaries

- [ ] **Step 1: Add a documentation identity test**

Create `tests/test_public_docs.py`:

```python
from pathlib import Path


PUBLIC = [Path("README.md"), Path("SECURITY.md"),
          Path("THIRD-PARTY-NOTICES.md"), Path("docs/MODEM-SETUP.md"),
          Path("apple2/TERMINAL-SETUP.md")]


def test_public_docs_name_the_shipped_product():
    joined = "\n".join(path.read_text() for path in PUBLIC)
    assert "CODEX.dsk" in joined
    assert "--workdir" in joined
    assert "workspace-write" in joined
    assert "approval_policy" in joined
    assert "TCP port 6401" in joined or ":6401" in joined
    assert "ATDS=1" in joined
    assert "apple-ii-terminal-for-codex" in joined


def test_removed_brand_assets_are_not_shipped():
    assert not Path("apple2gs/clawd.gif").exists()
    assert not Path("docs/demo.gif").exists()
```

- [ ] **Step 2: Rewrite README and setup docs around the actual prerequisite**

Document this quick start exactly:

```bash
codex --version                 # must be 0.144.1 or newer
codex login                     # only if the host is not already authenticated
python3 -m pip install -r bridge/requirements.txt
python3 bridge/bridge.py --telnet --app --workdir /absolute/path/to/git/repo
```

Explain that the bridge never receives an API key; Codex owns auth. Document `--sandbox read-only`, `--host 127.0.0.1` for emulator-only use, pairing/revocation, port 6401, modem entry 1, `CODEX.dsk`, all supported Apple models, and current local slash commands.

- [ ] **Step 3: Rewrite security and legal boundaries**

`SECURITY.md` must state:

- the default listener is reachable on the LAN and telnet traffic is plaintext;
- the pairing token is a bearer credential stored plaintext on disk and hashed on the host;
- prompts print on the host console and Codex retains its own local session data;
- workspace-write can edit and run commands only inside Codex's sandbox boundary;
- approval policy is `never`, so broader operations fail rather than wait invisibly;
- `--no-pair` is for isolated networks and no mode should be port-forwarded;
- the bridge does not handle Codex credentials.

Keep `LICENSE` byte-for-byte unchanged. Create `NOTICE.md` containing:

```markdown
# Modification notice

Apple II Terminal for Codex is derived from Apple II Terminal for Claude Code
(https://github.com/wr/apple-ii-terminal-for-claude-code). The Codex fork
replaces the provider backend, product identity, artwork, sound cues, persisted
state, documentation, and release artifact. The upstream commit history and MIT
license are preserved.

This project is not affiliated with or endorsed by OpenAI. Codex is an OpenAI
product name.
```

In `THIRD-PARTY-NOTICES.md`, remove Clawd, retain Apple DOS and UNSCII provenance, state that MIT covers project code rather than the whole disk, and identify `CODEX.dsk` as the distributed derivative artifact.

- [ ] **Step 4: Document physical side B without destructive automation**

Create `docs/PHYSICAL-DISK.md` with this ordered checklist:

1. Use media certified for double-sided recording; do not assume a single-sided disk is safe on its reverse.
2. Back up both surfaces first.
3. Put `CLAUDE.dsk` and `CODEX.dsk` on FloppyEmu as separate files.
4. Keep Claude on side A; flip the disk and use a disk utility to copy `CODEX.dsk` to side B.
5. Confirm source is FloppyEmu and destination is the real disk before writing.
6. Provide a reverse-side write-enable notch only if the drive requires it.
7. Cold-boot each side and confirm its pairing token does not unlock the other bridge.

Do not add a script that writes a real disk automatically.

- [ ] **Step 5: Remove old demo media, run the audit, and commit**

Run:

```bash
git rm docs/demo.gif
python3 -m pytest -q tests/test_public_docs.py
rg -n 'Anthropic|Clawd|clawd|CLAUDE\.dsk|COBJ8?|ATDS=0|:6400|--backend|Messages API' \
  README.md SECURITY.md THIRD-PARTY-NOTICES.md docs apple2/TERMINAL-SETUP.md CHANGELOG.md
git add README.md SECURITY.md THIRD-PARTY-NOTICES.md NOTICE.md CHANGELOG.md docs apple2/TERMINAL-SETUP.md tests/test_public_docs.py
git commit -m "docs: publish Codex install and security guidance"
```

Expected: tests pass; `rg` finds only clearly labeled upstream history or the intentional side-A `CLAUDE.dsk` mention in `PHYSICAL-DISK.md`.

---

### Task 9: Add reproducible CI and tagged release publication

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`
- Create: `tools/bootstrap-dos33fsprogs.sh`
- Modify: `requirements-test.txt`
- Modify: `requirements-build.txt`

**Interfaces:**
- Produces: pinned dos33fsprogs bootstrap with verified commit
- Produces: CI on Python 3.10 and 3.14 with no Codex login/network dependency
- Produces: tagged release assets `CODEX.dsk` and `SHA256SUMS`

- [ ] **Step 1: Pin the disk tools in one script**

Create `tools/bootstrap-dos33fsprogs.sh`:

```bash
#!/bin/bash
set -eu

DOS33_COMMIT=78fc3bd4b24a6b792f49f311e85412e0cccc272c
DEST="${DEST:-$HOME/dos33fsprogs}"

if [ ! -d "$DEST/.git" ]; then
  git clone https://github.com/deater/dos33fsprogs.git "$DEST"
fi
git -C "$DEST" fetch origin "$DOS33_COMMIT"
git -C "$DEST" checkout --detach "$DOS33_COMMIT"
make -C "$DEST/utils/dos33fs-utils"
make -C "$DEST/utils/asoft_basic-utils"
git -C "$DEST" rev-parse HEAD
```

Never replace the SHA with `main`, `master`, or a moving shallow clone.

Test it with:

```bash
shellcheck tools/bootstrap-dos33fsprogs.sh
DEST=/tmp/dos33fsprogs-codex tools/bootstrap-dos33fsprogs.sh
test "$(git -C /tmp/dos33fsprogs-codex rev-parse HEAD)" = \
  78fc3bd4b24a6b792f49f311e85412e0cccc272c
```

Expected: ShellCheck passes, both tools exist, and HEAD equals the recorded 40-character SHA.

- [ ] **Step 2: Convert CI names and artifact checks**

Keep action SHAs unchanged. Install `requirements-test.txt` and `bridge/requirements.txt`, run:

```yaml
- name: Bridge and renderer tests
  run: python3 -m pytest -q bridge tests apple2gs/test_patch_assets.py

- name: Full CODEX disk build
  run: |
    export DOS33FSPROGS="$HOME/dos33fsprogs"
    ./apple2gs/build.sh

- name: Validate release disk
  run: |
    DOS33FSPROGS="$HOME/dos33fsprogs" ./tools/check-release-disk.sh apple2gs/CODEX.dsk
    DOS33FSPROGS="$HOME/dos33fsprogs" ./tests/test_release_gate.sh apple2gs/CODEX.dsk
    sha256sum apple2gs/CODEX.dsk
```

Use the pinned bootstrap script on cache misses and put the commit SHA in the cache key.

- [ ] **Step 3: Add the release workflow**

Trigger only on tags matching `v*`. Reuse the same pinned build inputs. Generate checksums with:

```bash
cd apple2gs
sha256sum CODEX.dsk > SHA256SUMS
```

Upload `apple2gs/CODEX.dsk` and `apple2gs/SHA256SUMS` using an immutable GitHub-owned action revision, then create the GitHub release with installation/upgrade notes. Give the workflow only `contents: write`; all other permissions remain absent.

- [ ] **Step 4: Run the local CI equivalent and commit**

Run:

```bash
python3 -m pytest -q bridge tests apple2gs/test_patch_assets.py
shellcheck apple2gs/build.sh tools/install-sd.sh tools/check-release-disk.sh \
  tools/bootstrap-dos33fsprogs.sh tests/test_release_gate.sh
DOS33FSPROGS=/tmp/dos33fsprogs-codex ./apple2gs/build.sh
DOS33FSPROGS=/tmp/dos33fsprogs-codex ./tools/check-release-disk.sh apple2gs/CODEX.dsk
git add .github tools requirements-test.txt requirements-build.txt
git commit -m "ci: build and publish reproducible Codex disk releases"
```

Expected: every command succeeds and only `CODEX.dsk` plus `SHA256SUMS` are configured as release assets.

---

### Task 10: Prove authenticated Codex behavior and native-client compatibility

**Files:**
- Create: `bridge/test_codex_smoke.py`
- Modify: `tests/README.md`
- Modify: `apple2gs/tests/token_pair.lua`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: an installed/authenticated Codex CLI 0.144.1+, MAME ROMs, KEGS, FloppyEmu, IIgs, and IIc
- Produces: opt-in smoke evidence for initial/resume/cancel/fallback/sandbox behavior
- Produces: emulator and disk evidence required before public release

- [ ] **Step 1: Add an opt-in authenticated smoke script**

Mark the test `@pytest.mark.codex_live` and skip unless `RUN_CODEX_LIVE=1`. In a temporary Git repo, instantiate `CodexBackend` with `workspace-write`, ask it to create `inside.txt` containing `APPLEII_CODEX`, assert a thread ID is captured, ask it to report the previous filename, and assert the same thread ID remains. Start a turn that runs a long child process, call `cancel()`, verify the backend process group is gone, then send one more prompt.

The last assertion accepts only these two documented outcomes:

```python
assert (
    be._thread_id == original_thread
    or (be._thread_id is None and
        "next prompt starts a fresh thread" in resume_output)
)
```

Run read-only mode in a second temporary repo, ask it to create `forbidden.txt`, and assert the file does not exist. Never inspect `~/.codex` or credentials.

- [ ] **Step 2: Run offline tests, then the authenticated smoke**

Run:

```bash
python3 -m pytest -q -m 'not codex_live'
RUN_CODEX_LIVE=1 python3 -m pytest -q -m codex_live bridge/test_codex_smoke.py -s
```

Expected: offline suite passes; live test proves first turn, resume, cancellation cleanup, post-cancel behavior, workspace write, and read-only denial.

- [ ] **Step 3: Run MAME protocol tests**

Build `CODEX.dsk`, update the documented MAME commands to use the new source/disk names, and run the existing W-516, W-517, interrupt, and token-pair Lua scripts with `ATDS=1` and `CDXTK1` expectations.

Expected: IIe 80-column, IIe 40-column fallback, IIc modem port, dial verdict, Ctrl-C, and token persistence checks pass. Save no ROMs in the repository.

- [ ] **Step 4: Run KEGS and FloppyEmu checks**

Boot `CODEX.dsk` in KEGS, connect the bridge with:

```bash
python3 bridge/bridge.py --connect 127.0.0.1:6502 --app \
  --workdir /absolute/path/to/a/test/git/repo
```

Verify Patch splash/menu, real header, one completed reply, spinner, scrollback, `/new`, `/model`, and Ctrl-C. Push the same image with `tools/install-sd.sh`, boot it on FloppyEmu, and repeat one turn on physical IIgs and IIc.

- [ ] **Step 5: Test the two-sided physical disk**

Using certified double-sided media and the manual checklist, copy `CODEX.dsk` to side B while preserving Claude on side A. Cold-boot each side. Confirm side A dials entry 0/port 6400 and side B dials entry 1/port 6401; pair both and prove their stored tokens do not cross-authenticate.

If physical hardware is unavailable, record that exact unverified acceptance item in `CHANGELOG.md`; do not claim release readiness.

- [ ] **Step 6: Record verification and commit**

Add a `## Verification` subsection to the unreleased changelog entry with command names and outcomes, excluding credentials, tokens, local absolute paths, and ROM details.

Run:

```bash
git add bridge/test_codex_smoke.py tests/README.md apple2gs/tests/token_pair.lua CHANGELOG.md
git commit -m "test: verify Codex sessions and Apple II clients"
```

---

### Task 11: Final audit, create the public sibling, and publish the first release

**Files:**
- Modify if audit finds a real defect: only files already listed in Tasks 2-10
- Create remotely: `github.com/wr/apple-ii-terminal-for-codex`

**Interfaces:**
- Consumes: clean verified local `main`
- Produces: public independent GitHub repository and tagged release containing `CODEX.dsk` and `SHA256SUMS`

- [ ] **Step 1: Run the release-blocking audit**

Run:

```bash
git status --short
python3 -m pytest -q -m 'not codex_live'
shellcheck apple2gs/build.sh tools/*.sh tests/test_release_gate.sh
DOS33FSPROGS=/tmp/dos33fsprogs-codex ./apple2gs/build.sh
DOS33FSPROGS=/tmp/dos33fsprogs-codex ./tools/check-release-disk.sh apple2gs/CODEX.dsk
test "$(wc -c < apple2gs/CODEX.dsk | tr -d ' ')" = 143360
rg -n 'Anthropic|Clawd|clawd|sk-[A-Za-z0-9]|CLAUDE\.dsk|COBJ8?|ATDS=0|CLDTK1' \
  --glob '!docs/PHYSICAL-DISK.md' --glob '!docs/superpowers/**' .
```

Expected: clean status before generated artifacts, all checks pass, exact size matches, and brand/secret audit has no unexplained matches.

- [ ] **Step 2: Review the complete fork diff against its merge base**

Run:

```bash
git diff --stat claude-upstream/main...HEAD
git diff --check claude-upstream/main...HEAD
git log --oneline --decorate claude-upstream/main..HEAD
```

Expected: no whitespace errors; commits correspond to Tasks 1-10; no unrelated source changes.

- [ ] **Step 3: Create the independent public repository and push history**

This is the external publication checkpoint. After the user confirms publication, run:

```bash
gh repo create wr/apple-ii-terminal-for-codex --public \
  --description "Use a real Apple II as a terminal for Codex CLI"
git remote add origin git@github.com:wr/apple-ii-terminal-for-codex.git
git push -u origin main
```

Expected: the repository is public, `origin/main` matches local `main`, and `claude-upstream` remains available for provenance comparisons. This follows GitHub's independent repository duplication model rather than creating a linked fork-network repository.

- [ ] **Step 4: Confirm CI before tagging**

Run:

```bash
gh run list --workflow CI --branch main --limit 1
gh run watch --exit-status
```

Expected: Python 3.10/3.14 and build/release-gate jobs pass.

- [ ] **Step 5: Tag and publish**

Choose the version recorded in `CHANGELOG.md`, then run:

```bash
git tag -a v1.0.0 -m "Apple II Terminal for Codex v1.0.0"
git push origin v1.0.0
gh run watch --exit-status
gh release view v1.0.0 --json assets,url
```

Expected: annotated tag is pushed; release workflow succeeds; assets are exactly `CODEX.dsk` and `SHA256SUMS`; the published checksum matches a fresh local build.

- [ ] **Step 6: Perform the public install test**

Download the release assets into a clean temporary directory, verify `SHA256SUMS`, install the downloaded disk through `tools/install-sd.sh`, and boot it. Use the README alone to start the bridge against an existing authenticated Codex install.

Expected: a new user path works without source-tree assumptions, API keys, or undocumented flags.

---

## Final acceptance gate

Release only when every item below has current evidence:

- [ ] First turn, resume, Ctrl-C process cleanup, and post-cancel resume/fallback pass against a real authenticated Codex CLI.
- [ ] Workspace-write edits only the chosen repo; read-only creates no file; approvals fail closed.
- [ ] Offline CI passes on Python 3.10 and 3.14 without a Codex account.
- [ ] Both clients assemble, boot, dial entry 1, pair with `CDXTK1`, and pass emulator protocol tests.
- [ ] `CODEX.dsk` is 143,360 bytes and contains `CODEX` plus `CODEX8`; the damaged-image test fails.
- [ ] Patch is original, readable at actual SHR geometry, animated only on the menu, and no Clawd/Anthropic asset ships.
- [ ] FloppyEmu boots the release download.
- [ ] A certified two-sided disk boots Claude on side A and Codex on side B, or release remains blocked with that item named.
- [ ] Security, attribution, third-party notices, non-affiliation text, install docs, and checksums match the shipped artifact.
- [ ] Public GitHub CI passes and the tag release contains only `CODEX.dsk` and `SHA256SUMS`.
