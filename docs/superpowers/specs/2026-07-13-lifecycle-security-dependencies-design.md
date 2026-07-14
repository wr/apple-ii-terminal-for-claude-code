# Bridge Lifecycle, Security, and Dependency Cleanup Design

**Date:** 2026-07-13
**Status:** Approved for implementation planning

## Goal

Fix four concrete release-quality problems without redesigning the bridge:

1. Ctrl-C can be missed while Claude is producing output continuously.
2. Closing or interrupting the bridge can leave Claude child processes or reply threads running.
3. The security and pairing documentation overstates or misdescribes a few protections.
4. Serial, chat, build, and test dependencies are mixed together or omitted from setup instructions.

The normal Apple II experience stays the same: Ctrl-C during a think cancels the turn, Ctrl-C while printing only mutes local output, and Ctrl-C at an idle native-client prompt returns to the menu.

## Chosen approach

Use focused repairs around the existing bridge and backend boundaries. Do not introduce a new turn-controller framework or rewrite the transport stack.

The alternatives were a broad backend lifecycle refactor and a documentation-only cleanup. The refactor would create unnecessary release risk; documentation alone would leave confirmed cancellation and process leaks unfixed.

## Ctrl-C and reply-thread behavior

`run_app_session` currently checks the serial/TCP channel only when the reply queue is empty for 200 milliseconds. A backend that produces chunks continuously prevents that timeout, so the bridge never sees Ctrl-C.

The session loop will instead poll the channel on a fixed cadence independent of reply traffic. It will continue buffering the reply as it does today, but a busy queue will no longer starve input polling.

Each reply worker will be retained in a local variable instead of being started and forgotten. The turn will use `try/finally` cleanup:

- normal completion consumes the sentinel and joins the worker;
- client Ctrl-C cancels the backend, drains the partial reply, and joins the worker;
- disconnect, host-side Ctrl-C, or an exception cancels unfinished backend work before returning;
- a bounded join prevents cleanup itself from hanging forever, and a surviving worker is logged as an error.

Non-app sessions will receive the same cancel-on-unwind guarantee. The Apple II client code does not change.

## Backend cancellation and process cleanup

Both backends have a publication race: cancellation can arrive after a request/process starts but before it is stored where `cancel()` can find it.

Each backend will keep a thread-safe cancellation event and a small state lock:

- the event is cleared at the start of a turn;
- `cancel()` sets the event before looking up the active resource;
- after a subprocess or HTTP stream is created, it is published under the lock;
- if cancellation arrived during startup, the newly published resource is closed or killed immediately;
- cleanup clears only the resource owned by that turn.

The code backend already starts each normal Claude CLI turn in its own process group. Group cleanup will stop relying on the group leader's exit as proof that the group is gone. It will:

1. send SIGTERM to the process group;
2. poll for surviving group members through the grace period;
3. send SIGKILL if the group still exists;
4. reap the leader before returning.

The model-probe subprocess will also start in its own process group and use the same cleanup helper, including a final wait after forced termination. This project remains POSIX-only for code-mode process cancellation; Windows support is not added here.

## Pairing behavior and security documentation

The implementation will not add encryption or change the token format. Documentation will describe the behavior that exists:

- default pairing codes are created on demand and keyed by source IP, not by physical device;
- a valid token reconnect does not create or print a code;
- telnet traffic is plaintext, so a person able to capture trusted-LAN traffic can replay a code or token;
- native clients store and resend tokens, while raw telnet clients must pair again on each session;
- the host stores a token hash plus first-seen IP and pairing time;
- the store uses `$XDG_CONFIG_HOME/claude-ii-terminal/paired.json`, falling back to `~/.config/claude-ii-terminal/paired.json`;
- newly created storage uses restrictive permissions, but the bridge does not repair permissions on pre-existing paths;
- the effective pairing delay is capped at eight seconds, while the ten-attempt lockout remains;
- `--no-pair`, `--clear-paired`, listener exposure, and the trusted-LAN warning remain unchanged.

User-supplied `--pair-code` values will be normalized to uppercase during argument parsing because guesses from the Apple II are already uppercased. A regression test will prove that a lowercase command-line value works. No new length or alphabet restriction will be imposed on pinned codes.

Files requiring accuracy updates are `README.md`, `SECURITY.md`, `CHANGELOG.md`, `AGENTS.md`, `apple2/TERMINAL-SETUP.md`, the `--pair-code` help text, and the shipped token-pairing design's status/amendment. `docs/MODEM-SETUP.md` and `docs/COMPATIBILITY.md` do not need security changes.

## Dependency layout

Python 3.10 remains the minimum supported version. CI will test the Python-only suite on Python 3.10 and 3.14; the disk build remains on one Python version to avoid duplicating the toolchain job.

Runtime dependencies will be split by feature:

- `bridge/requirements-serial.txt`: `pyserial==3.5` for `--serial`;
- `bridge/requirements-chat.txt`: `anthropic>=0.77.0,<1` for `--backend chat`;
- `bridge/requirements.txt`: includes both files as the all-features convenience install;
- TCP plus `--backend code`: no Python package dependency, but it still requires the external `claude` executable.

Repository-only dependencies will be explicit and reproducible:

- `requirements-build.txt`: `Pillow==12.3.0`;
- `requirements-test.txt`: `pytest==9.1.1`.

These versions support Python 3.10. Runtime libraries use compatibility ranges where security and API updates should remain installable; deterministic build/test tools use exact versions.

README installation choices will match those boundaries. The serial setup guide will install the serial requirement and use `--backend code` in its basic example. Chat setup will state that it needs the chat requirement and `ANTHROPIC_API_KEY`. `tests/README.md` will use the same full pytest command as CI.

CI will install test and all-features runtime requirements for the Python-version matrix, making dependency resolution an intentional smoke test. The disk-build job will install only the pinned build requirement plus what that job actually uses.

## Tests

New tests will fail against the current implementation before production code changes. Coverage will include:

- continuous backend chunks cannot starve Ctrl-C polling;
- cancellation during delayed `Popen` publication kills the process;
- cancellation during delayed chat-stream entry closes the stream;
- a child that ignores SIGTERM cannot survive after the group leader exits;
- child-held stdout/stderr pipes do not leave `CodeBackend.stream()` stuck;
- host-side Ctrl-C and disconnect cancel and join active work;
- lowercase `--pair-code` input is normalized and accepted;
- dependency files install cleanly on the supported Python endpoints;
- the complete pytest suite, ShellCheck, both client assemblies, disk build, and release-disk gate still pass.

The process tests will use short-lived local Python child processes and bounded waits. They will not depend on a real Claude account, serial device, or network service.

## Scope boundaries

This work does not:

- change Apple II UI or serial protocol bytes;
- add TLS, authentication servers, or public-network support;
- replace the trusted-LAN security model;
- redesign the backend interface or transport classes;
- add Windows process-control support;
- change dos33fsprogs or GitHub Action pinning;
- revisit release version `1.1.0` beyond correcting inaccurate text.

## Completion criteria

The work is complete when focused regressions demonstrate each former failure, the full suite passes on Python 3.10 and 3.14 in CI, a fresh serial/code setup has an explicit install path, the security documents match the code, no Claude child process survives cancellation tests, and the release disk still builds with the same catalog gate.
