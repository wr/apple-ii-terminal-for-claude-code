"""What Claude does on the far end of the wire.

Two backends, one interface:

  * ChatBackend - direct Messages API. You ask, Claude answers. No tools, no
    filesystem, nothing runs on the host. Predictable and bounded.
  * CodeBackend - wraps the `claude` CLI headless. The real coding agent: it
    reads files, edits them, runs commands ON THE BRIDGE HOST, and reports back.

Both stream text a chunk at a time so the terminal shows progress as it arrives.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
from typing import Iterator

_version_cache: dict[str, str] = {}


def claude_version(claude_bin: str = "claude") -> str:
    """`claude --version` -> just the version number (cached), or '?' on failure."""
    if claude_bin not in _version_cache:
        v = "?"
        try:
            out = subprocess.run(
                [claude_bin, "--version"], capture_output=True, text=True, timeout=10
            ).stdout
            m = re.search(r"\d+\.\d+\.\d+", out)
            if m:
                v = m.group(0)
        except Exception:
            pass
        _version_cache[claude_bin] = v
    return _version_cache[claude_bin]


_MODEL_CACHE = os.path.expanduser("~/.cache/appleii-claude/last-model")


def read_effort() -> str | None:
    """Claude Code's default reasoning effort (what `claude -p` uses)."""
    try:
        d = json.load(open(os.path.expanduser("~/.claude/settings.json")))
        return d.get("effortLevel")
    except Exception:
        return None


def read_plan() -> str | None:
    """Subscription tier from the oauth account, e.g. 'Claude Max'."""
    try:
        d = json.load(open(os.path.expanduser("~/.claude.json")))
        tier = (d.get("oauthAccount") or {}).get("organizationRateLimitTier") or ""
    except Exception:
        return None
    t = tier.lower()
    for key, label in (("max", "Claude Max"), ("pro", "Claude Pro"),
                       ("team", "Claude Team"), ("enterprise", "Claude Enterprise")):
        if key in t:
            return label
    return None


def abbrev_cwd(path: str | None) -> str:
    home = os.path.expanduser("~")
    if path and path.startswith(home):
        return "~" + path[len(home):]
    return path or ""


def read_cached_model() -> str | None:
    try:
        return open(_MODEL_CACHE).read().strip() or None
    except OSError:
        return None


def write_cached_model(model: str) -> None:
    try:
        os.makedirs(os.path.dirname(_MODEL_CACHE), exist_ok=True)
        with open(_MODEL_CACHE, "w") as f:
            f.write(model)
    except OSError:
        pass


def pretty_model(mid: str | None) -> str:
    """A friendly display name for a model id, e.g. claude-opus-4-8 -> Opus 4.8.
    Falls back to the raw id so it's always the real model."""
    if not mid:
        return "Claude"
    base = re.sub(r"\[.*?\]", "", mid.lower())  # drop a "[1m]" style suffix
    parts = base.replace("claude-", "").split("-")
    fam = next((p for p in parts if p in ("opus", "sonnet", "haiku")), None)
    if not fam:
        return mid
    nums = [p for p in parts if p.isdigit() and len(p) <= 2]
    ver = ".".join(nums[:2])
    label = f"{fam.capitalize()} {ver}".strip()
    if "1m" in mid.lower():
        label += " (1M context)"
    return label

# Keep Claude's prose friendly to a 1980s glass terminal.
TERMINAL_SYSTEM = (
    "You are talking to a user on a real Apple IIgs or IIc over a serial "
    "terminal, {cols} columns wide. Hard constraints on every reply:\n"
    "- Plain 7-bit ASCII only. No em-dashes, smart quotes, bullets, arrows, "
    "emoji, or box-drawing characters.\n"
    "- No Markdown tables. Avoid heavy formatting; short paragraphs read best.\n"
    "- Be concise. This screen is small and the line is slow.\n"
    "- Prefer short lines and plain lists (use '* ' or '1. ') over wide layouts."
)


class Backend:
    name = "backend"

    def stream(self, user_text: str) -> Iterator[str]:
        raise NotImplementedError

    def reset(self) -> None:
        pass

    def footer(self) -> str | None:
        """Optional one-line status shown after a reply (e.g. 'Worked for 4m 41s').
        Returns None when there's nothing to show."""
        return None

    def header(self) -> tuple[str, ...] | None:
        """Optional header lines for the client. None to leave it."""
        return None

    def prime(self) -> None:
        """Optional: fetch header/model info before the first user message."""
        pass

    def cancel(self) -> None:
        """Stop an in-flight stream() early (the client sent Ctrl-C). Safe to
        call from another thread; a backend that can't cancel just ignores it."""
        pass


# --------------------------------------------------------------------------- #
# Chat: Messages API
# --------------------------------------------------------------------------- #
class ChatBackend(Backend):
    name = "chat"

    def __init__(self, cols: int, model: str = "claude-opus-4-8",
                 effort: str = "low", max_tokens: int = 2048) -> None:
        import anthropic  # lazy so `code` mode doesn't need the SDK installed

        self._client = anthropic.Anthropic()
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens
        self._system = TERMINAL_SYSTEM.format(cols=cols)
        self._messages: list[dict] = []
        self._cancel = False
        self._stream = None  # the in-flight anthropic stream, if any

    def reset(self) -> None:
        self._messages = []

    def cancel(self) -> None:
        """Abort an in-flight turn (the client sent Ctrl-C). Setting the flag
        stops us at the next chunk; closing the stream also unblocks a turn
        that's STALLED between chunks, so a wedged model doesn't hang the
        session waiting for a byte that never comes."""
        self._cancel = True
        s = self._stream
        if s is not None:
            try:
                s.close()  # tears down the HTTP response from under the reader
            except Exception:
                pass

    def stream(self, user_text: str) -> Iterator[str]:
        self._cancel = False
        self._messages.append({"role": "user", "content": user_text})
        reply_parts: list[str] = []
        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system,
                output_config={"effort": self._effort},
                messages=self._messages,
            ) as stream:
                self._stream = stream
                try:
                    for text in stream.text_stream:
                        if self._cancel:
                            break
                        reply_parts.append(text)
                        yield text
                except Exception:
                    # cancel() closes the stream from another thread, which
                    # surfaces here as a read error - treat it as a clean stop,
                    # but let a genuine streaming fault propagate.
                    if not self._cancel:
                        raise
            if self._cancel:
                # keep the partial turn so the transcript stays coherent
                self._messages.append({"role": "assistant",
                                       "content": "".join(reply_parts) or "(interrupted)"})
                return
            final = stream.get_final_message()
            self._messages.append({"role": "assistant", "content": final.content})
        except Exception as exc:  # surface the error to the terminal, keep going
            # Roll back the user turn so the next message starts clean.
            self._messages.pop()
            print(f"[bridge] chat backend error: {exc}", file=sys.stderr, flush=True)
            yield "\n[bridge error: chat request failed]"
        finally:
            self._stream = None


def _kill_process_group(proc: subprocess.Popen, grace: float = 2.0) -> None:
    """Take down a Popen's whole process group: SIGTERM it, wait `grace`
    seconds, then SIGKILL anything still standing. Assumes the process was
    started with start_new_session=True so its pgid == pid, which is how one
    signal reaches `claude -p` AND the children it spawned (MCP servers, tools)
    instead of orphaning them. No-ops if the process is already gone."""
    if proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError, OSError):
        return  # already reaped, or not a group we can signal

    def _sig(sig) -> None:
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    _sig(signal.SIGTERM)
    try:
        proc.wait(timeout=grace)
        return  # went quietly
    except subprocess.TimeoutExpired:
        pass
    _sig(signal.SIGKILL)  # ignored SIGTERM; SIGKILL can't be caught
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass


# --------------------------------------------------------------------------- #
# Code: the `claude` CLI, headless
# --------------------------------------------------------------------------- #
class CodeBackend(Backend):
    name = "code"

    def __init__(self, cols: int, model: str | None = None,
                 permission_mode: str = "default",
                 claude_bin: str = "claude", cwd: str | None = None,
                 show_tools: bool = True) -> None:
        self._cols = cols
        self._model = model
        self._permission_mode = permission_mode
        self._bin = claude_bin
        self._cwd = cwd
        # When False, don't stream tool-use markers - so the client sees no
        # output until the final answer, keeping a thinking spinner up the
        # whole time instead of stopping at the first tool call.
        self._show_tools = show_tools
        self._session_id: str | None = None
        self._proc: subprocess.Popen | None = None  # the in-flight turn, if any
        self._cancelled = False
        # Seed from the last run so the header shows a real model at boot, before
        # the first reply's init event arrives.
        self._last_model = read_cached_model()
        self._last_cwd = cwd
        self._last_version = None
        if cwd:  # a missing cwd makes Popen raise FileNotFoundError, misleadingly
            os.makedirs(cwd, exist_ok=True)

    def reset(self) -> None:
        self._session_id = None

    def header(self) -> tuple[str, ...] | None:
        ver = getattr(self, "_last_version", None) or claude_version(self._bin)
        model = getattr(self, "_last_model", None) or self._model
        line1 = f"Claude Code v{ver}"
        line2 = pretty_model(model)
        eff = read_effort()
        if eff:
            line2 += f" with {eff} effort"
        plan = read_plan()
        if plan:
            line2 += f" - {plan}"
        cwd = getattr(self, "_last_cwd", None) or self._cwd or os.getcwd()
        return (line1, line2, abbrev_cwd(cwd))

    def prime(self) -> None:
        """Learn the model/cwd/version before the first user message."""
        if not getattr(self, "_last_model", None):
            self.probe_model()

    def probe_model(self, timeout: float = 20.0) -> None:
        """Talk to claude ourselves: start a stream-json query and read the
        init event (model/cwd/version), then stop before it generates a reply."""
        cmd = [self._bin, "-p", "hi", "--output-format", "stream-json",
               "--verbose", "--permission-mode", self._permission_mode]
        if self._model:
            cmd += ["--model", self._model]
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1, cwd=self._cwd,
            )
        except Exception:
            return
        killer = threading.Timer(timeout, proc.kill)
        killer.start()
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "system" and ev.get("subtype") == "init":
                    self._absorb_init(ev)
                    break
        finally:
            killer.cancel()
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()

    @staticmethod
    def _real_model(mid) -> str | None:
        """Slash-command turns report their model as "<synthetic>" - never
        let that reach the header or the model cache."""
        return mid if mid and "<" not in mid else None

    def _absorb_init(self, ev: dict) -> None:
        self._last_model = self._real_model(ev.get("model")) or self._last_model
        self._last_cwd = ev.get("cwd") or getattr(self, "_last_cwd", None)
        self._last_version = ev.get("claude_code_version") or getattr(
            self, "_last_version", None)
        if self._last_model:
            write_cached_model(self._last_model)

    def footer(self) -> str | None:
        ms = getattr(self, "_last_duration_ms", None)
        if not ms:
            return None
        secs = round(ms / 1000)
        t = f"{secs // 60}m {secs % 60}s" if secs >= 60 else f"{secs}s"
        foot = f"Worked for {t}"
        tok = getattr(self, "_last_output_tokens", None)
        if tok:
            if tok >= 1000:
                num = f"{tok / 1000:.1f}".rstrip("0").rstrip(".") + "k"
            else:
                num = str(tok)
            foot += f" - {num} tokens"  # ASCII '-'; the client can't show a dot
        return foot

    def _build_cmd(self, user_text: str) -> list[str]:
        cmd = [
            self._bin, "-p", user_text,
            "--output-format", "stream-json",
            "--verbose",
            "--permission-mode", self._permission_mode,
        ]
        if self._model:
            cmd += ["--model", self._model]
        if self._session_id:
            cmd += ["--resume", self._session_id]
        return cmd

    def cancel(self) -> None:
        """Kill the in-flight `claude -p` turn AND every child it spawned (the
        client sent Ctrl-C). The turn leads its own process group (see the
        start_new_session below), so we signal the whole group - SIGTERM, a
        short grace, then SIGKILL for anything that ignored it - instead of
        terminating just the parent and orphaning its children. stderr is
        drained on its own thread, so a full pipe can't wedge the kill. The
        pipe EOFs, stream() winds down, and the exit-code complaint is
        suppressed because we're the ones who shot it."""
        self._cancelled = True
        proc = self._proc
        if proc is not None:
            _kill_process_group(proc)

    def stream(self, user_text: str) -> Iterator[str]:
        self._last_duration_ms = None
        self._last_output_tokens = None
        self._cancelled = False
        try:
            proc = subprocess.Popen(
                self._build_cmd(user_text),
                stdin=subprocess.DEVNULL,  # else `claude -p` blocks reading a piped stdin
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=self._cwd,
                start_new_session=True,  # own process group: cancel() can kill
                                         # claude and its children in one signal
            )
        except FileNotFoundError:
            print(f"[bridge] claude binary not found: {self._bin!r}",
                  file=sys.stderr, flush=True)
            yield "\n[bridge error: claude CLI not found on the host]"
            return

        self._proc = proc
        assert proc.stdout is not None
        # Drain stderr on a thread for the whole turn. `claude -p` can emit more
        # than a pipe buffer holds; if we only read stderr at the end, a full
        # stderr pipe would block the child (and us) mid-turn. Collect it here
        # and surface it only if the exit code turns out bad.
        err_parts: list[str] = []

        def _drain_err(p=proc) -> None:
            try:
                if p.stderr is not None:
                    for chunk in iter(lambda: p.stderr.read(4096), ""):
                        err_parts.append(chunk)
            except Exception:
                pass

        err_thread = threading.Thread(target=_drain_err, daemon=True)
        err_thread.start()

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            yield from self._render_event(event)

        proc.wait()
        err_thread.join(timeout=1.0)
        self._proc = None
        if self._cancelled:
            return  # we killed it; a nonzero exit code is expected, not news
        if proc.returncode not in (0, None):
            err = "".join(err_parts).strip()
            if err:
                print(f"[bridge] claude stderr: {err}", file=sys.stderr, flush=True)
            yield f"\n[claude exited {proc.returncode}]"

    def _render_event(self, event: dict) -> Iterator[str]:
        etype = event.get("type")

        if etype == "system" and event.get("subtype") == "init":
            self._session_id = event.get("session_id") or self._session_id
            self._absorb_init(event)
            return

        if etype == "assistant":
            self._last_model = self._real_model(
                event.get("message", {}).get("model")) or self._last_model
            for block in event.get("message", {}).get("content", []):
                btype = block.get("type")
                if btype == "text":
                    yield block.get("text", "")
                elif btype == "tool_use" and self._show_tools:
                    name = block.get("name", "tool")
                    yield f"\n[{name}] "
                    inp = block.get("input", {})
                    hint = inp.get("command") or inp.get("file_path") or inp.get("path")
                    if hint:
                        yield str(hint)[: self._cols]
                    yield "\n"
            return

        if etype == "result":
            self._session_id = event.get("session_id") or self._session_id
            self._last_duration_ms = event.get("duration_ms") or event.get(
                "duration_api_ms"
            )
            usage = event.get("usage") or {}
            self._last_output_tokens = usage.get("output_tokens")
            if self._last_model:  # persist for the next run's boot header
                write_cached_model(self._last_model)
            return
