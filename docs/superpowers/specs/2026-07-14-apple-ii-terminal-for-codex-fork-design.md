# Apple II Terminal for Codex fork design

Date: 2026-07-14
Status: approved
Target repository: `github.com/wr/apple-ii-terminal-for-codex`

## Goal

Create a polished public sibling of Apple II Terminal for Claude Code. It will
turn the same supported Apple II models into a terminal for an already-installed
and authenticated Codex CLI, ship a bootable `CODEX.dsk`, run from FloppyEmu,
and work as side B of a two-sided 5.25-inch Claude/Codex disk.

This is a focused fork. It preserves the working Apple II protocol and hardware
code, then replaces the provider backend, identity, art, sound cues, persisted
state, documentation, and release artifact. It will not refactor the Claude
project into a general multi-provider framework.

## Product decisions

- The fork is Codex-only. The Anthropic Messages API backend and its Python
  dependency are removed.
- The host already has `codex` installed and authenticated. The bridge does not
  offer login, read credentials, copy credentials, or accept API keys.
- Codex gets workspace-write access inside an explicit `--workdir` by default.
  Approval requests fail closed because the Apple II cannot service an
  interactive host approval prompt.
- The public identity is original. It does not use Clawd, Anthropic artwork,
  the OpenAI knot, or other company artwork.
- The mascot is Patch, a small original terminal mechanic. Patch wakes, unfolds
  a keyboard, types, and settles into a static session pose.
- Claude remains modem phonebook entry 0. Codex defaults to entry 1 and TCP port
  6401, allowing both bridges to run at the same time.

## Architecture

The fork keeps three layers:

1. `bridge/`: Python host bridge and Codex CLI adapter.
2. `apple2gs/`: 65816 Super Hi-Res client for the IIgs.
3. `apple2/`: plain-6502 text client for the II+, IIe, IIc, and IIc Plus.

The serial protocol remains provider-neutral and unchanged: printable 7-bit
ASCII plus the existing color, bullet, session-end, header, token, and EOT
control frames. Transports, pairing, wrapping, scrollback, serial polling, and
process-group cancellation retain their current boundaries.

`CodexBackend` implements the existing backend lifecycle:

- `begin_turn()` establishes the cancellation boundary synchronously.
- `stream()` launches Codex and converts JSONL events into terminal text.
- `cancel()` terminates the complete Codex process group.
- `reset()` forgets the saved Codex thread ID.
- `header()` reports Codex CLI version, selected model when known, and workdir.
- `footer()` reports locally measured duration and output tokens when provided.

The existing subprocess lifecycle stays inside `CodexBackend`; the Codex-only
fork has no second CLI backend that would justify a generalized base class.
Rendering and Apple II protocol code will not be generalized.

## Codex CLI contract

The minimum supported CLI for the first release is Codex CLI 0.144.1. The bridge
runs `codex --version` at startup and gives a plain host/client error if the
binary is missing or too old. Authentication failures are reported as host-side
diagnostics plus a short Apple II message telling the user to run `codex login`
on the host.

The first turn uses non-interactive JSONL execution. The bridge supplies the
prompt through stdin so it is not exposed in the process argument list:

```text
codex exec --json --color never [config overrides] -
```

The bridge saves `thread.started.thread_id`. Later turns resume that thread:

```text
codex exec resume --json [config overrides] <thread-id> -
```

Both processes run with `cwd=--workdir`. The bridge passes the same model and
permission overrides on initial and resumed turns. It never uses `--ephemeral`,
because resumption depends on Codex's saved local session state.

The required one-off configuration is equivalent to:

```toml
sandbox_mode = "workspace-write"
approval_policy = "never"
```

This means Codex can read, edit, and run commands in the workspace. Anything
that requires broader access fails rather than waiting for approval. A
`--sandbox read-only` bridge option is supported. Danger-full-access is not a
documented or supported v1 mode.

`--workdir` is required, must already exist, and must be a Git repository.
There is no automatic `--skip-git-repo-check` in v1.

## JSONL event mapping

The adapter accepts documented Codex event families and ignores unknown fields:

- `thread.started`: save the thread ID.
- `turn.started`: start local timing; no client text.
- completed `agent_message`: emit its text as the reply.
- command, file-change, MCP, web-search, and plan items: optionally emit short
  40/80-column status summaries when tool display is enabled.
- reasoning items: suppress.
- `turn.completed`: save usage and finish timing.
- `turn.failed` and top-level `error`: produce a short sanitized client error;
  retain detailed diagnostics on the host.
- malformed JSON or unknown items: host-log and continue where safe.

Codex's documented JSONL is item-oriented rather than token-delta prose. Native
client mode already buffers the complete reply. Raw terminal mode may therefore
show status items during work and the prose answer when its agent-message item
completes. The bridge must not fake token streaming.

## Session commands and cancellation

The bridge owns these commands:

- `/new` and `/clear`: forget the Codex thread and start fresh.
- `/model <id>`: save a model override and pass it on every later invocation.
- `/help`: show only commands supported by this transport.
- `/quit` and `/exit`: return the native client to its menu or close raw mode.

Unknown slash commands are rejected clearly. Interactive TUI commands such as
`/compact` are not forwarded as if `codex exec` supported them.

Ctrl-C keeps the current Apple behavior. During a turn it sends a bare control
byte, the bridge kills the full Codex process group, and the client receives any
usable partial output followed by `Interrupted by user` and EOT. The first
release must prove with an authenticated smoke test that a cancelled Codex
thread can be resumed. If Codex marks that thread non-resumable, the bridge
clears it and tells the user that the next prompt starts a fresh thread.

## Pairing and state isolation

Network pairing remains enabled by default and retains the existing generated
codes, retry limits, stale-token handling, token hashing, atomic writes, and
trusted-LAN warnings.

The fork uses separate host state:

```text
$XDG_CONFIG_HOME/codex-ii-terminal/paired.json
~/.config/codex-ii-terminal/paired.json
~/.cache/appleii-codex/
```

The disk token sector stays at track `$12`, sector `$0F`, but uses the new magic
value `CDXTK1`. Claude and Codex therefore pair independently even when
they occupy opposite sides of one physical disk. The plaintext bearer-token and
telnet replay risks remain documented.

The listener stays on `0.0.0.0` because a WiFi modem must reach it. Pairing,
the console warning, port 6401, and an explicit `--workdir` are the safety
boundary. The README also documents `--host 127.0.0.1` for emulator-only use.

## Apple II identity and experience

Both clients retain the current menu, session layout, spinner, scrollback,
serial behavior, and model support.

Visible identity changes include:

- `Terminal for Codex` titles, instructions, headers, and repository URLs.
- An animated IIgs Patch splash and static Patch session mascot.
- A simplified inverse-block Patch mascot with blink behavior on 8-bit Apples.
- IIgs DTMF digits `2-6-3-3-9`, spelling CODEX.
- An 8-bit `2-6-3` pulse-dial cue with the current serial polling guarantees.
- Phonebook entry 1 in the Codex dial command.
- Original demo media showing the Codex client, not altered Claude screenshots.

Patch art is designed for the actual SHR cell and palette constraints. It is
not forced through the Clawd-specific GIF classifier. The implementation should
use a small hand-authored frame set or a new extractor built around Patch's own
sprites. Generated `assets.inc` remains build output.

## Disk, FloppyEmu, and physical media

`CODEX.dsk` is a standard 143,360-byte DOS 3.3 image. It is built from the same
known-good master workflow and contains both clients:

- `CODEX`: IIgs SHR client.
- `CODEX8`: 8-bit text client.

HELLO keeps the existing ROM detection and BRUNs the appropriate file. The
release gate requires both catalog entries and tests rejection after deleting
`CODEX8`.

FloppyEmu treats `CLAUDE.dsk` and `CODEX.dsk` as separate selectable SD-card
files. The install helper accepts either image and retains contiguity checks and
in-place updates.

For a physical two-sided disk:

- side A remains the existing Claude disk;
- side B receives `CODEX.dsk` as an independent 140K disk;
- the media must be certified for double-sided use and writable on the reverse;
- the operator backs up both sides before copying;
- a disk utility copies from FloppyEmu to the flipped real disk, with source and
  destination confirmed before writing.

No 280K combined image or software side-selection logic is introduced. A stock
Apple drive sees only the surface currently facing its head.

## Public fork and release policy

The fork preserves the upstream MIT notice and history and adds a modification
notice for the Codex fork. It replaces Clawd, Anthropic branding, and the current
demo media. It includes a clear statement that the project is not affiliated
with or endorsed by OpenAI and that Codex is an OpenAI product name.

Third-party notices continue to identify Apple DOS, the font, tools, and their
separate terms. The build verifies hashes for vendored third-party inputs. The
fork does not imply that MIT covers the complete disk image.

CI retains immutable GitHub Action revisions, Python 3.10 and 3.14 tests,
ShellCheck, both assemblers, the master-based disk build, and the two-client
catalog gate. dos33fsprogs is pinned to a commit rather than a moving default
branch. Tagged releases publish:

- `CODEX.dsk`
- `SHA256SUMS`
- concise installation and upgrade notes

## Testing

Normal CI uses no Codex account and no network service. It covers:

- golden JSONL fixtures for every mapped event family;
- malformed JSON, missing fields, unknown items, failed turns, and nonzero exit;
- exact first-turn and resume argv/config construction;
- prompt delivery over stdin;
- fake-Codex integration recording argv and emitting JSONL;
- model override, workdir validation, and read-only mode;
- complete process-group cancellation and all existing startup-race regressions;
- local slash-command routing and unsupported commands;
- renderer, terminal, pairing, and native interrupt suites;
- IIgs and 8-bit assembly;
- MAME protocol tests and token persistence;
- valid and deliberately damaged disk release gates.

An opt-in authenticated smoke test runs in a temporary Git repository and proves:

1. initial turn returns a thread ID;
2. a second turn resumes the same thread;
3. Ctrl-C kills Codex and its children;
4. the thread resumes after cancellation, or the documented fresh-thread
   fallback is shown;
5. workspace-write can edit only inside the selected workdir.

## Non-goals

- No OpenAI Responses API backend.
- No Anthropic backend or provider switcher.
- No interactive Codex TUI emulation.
- No approval UI on the Apple II.
- No danger-full-access mode in v1.
- No combined Claude/Codex disk image.
- No refactor of the original Claude repository into shared packages.

## Acceptance criteria

The fork is ready for public release when:

- a logged-in Codex CLI can complete, resume, cancel, and continue a session;
- workspace-write and read-only behavior match their documentation;
- no Codex or child process survives interruption or disconnect;
- both Apple II clients boot and pass emulator protocol tests;
- `CODEX.dsk` contains `CODEX` and `CODEX8` and passes the release gate;
- FloppyEmu boots the image;
- a certified two-sided physical test disk boots Claude on side A and Codex on
  side B without token or dial-entry collision;
- all Claude/Anthropic artwork and current branded demo media are absent;
- the security, attribution, and third-party notices match the shipped files;
- CI passes on Python 3.10 and 3.14 and a tagged release publishes the disk and
  checksum.
