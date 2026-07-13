# Design: disk-stored device token replaces IP-based pairing

Date: 2026-07-13
Status: approved (design), pending implementation plan
Scope: `bridge/`, `apple2gs/claude.s`, `apple2/claude2.s`, `apple2gs/build.sh`

## Problem

A `--telnet` bridge in code mode hands any accepted peer a `claude` CLI running
on the host. Today the only persistent trust is a set of **peer IP addresses**
saved to `~/.config/claude-ii-terminal/paired.json`. That has two exploitable
failure modes (from the security review):

- **DHCP lease reuse** — when the paired Apple II's lease expires and the router
  reassigns its IP to a different device, that device inherits trust and reaches
  the backend with no code typed.
- **Persisted loopback** — `127.0.0.1` was saved as paired, so any local
  process/user that can open the listening socket is ungated.

Root cause: trust is pinned to an L3 address, not to a device. This design binds
trust to a **secret the client device holds**, so a reused or spoofed address
proves nothing.

## Goals

- Trust follows the *device*, surviving DHCP churn and bridge/client reboots.
- The bridge never stores or logs a usable credential (hashes at rest only).
- The 6-char human pairing code becomes first-run / fallback only, not the
  steady-state path.
- Graceful degradation: a write-protected disk or any disk error falls back to
  typing the code for that session, never a crash.

## Non-goals

- Confidentiality of the token *at rest on the Apple II disk*. It is stored
  plaintext; physical access to the disk/SD is explicitly an accepted risk
  (trusted-LAN, physical Apple IIs). The token's secrecy protects the network
  path, not the medium.
- Per-device selective revoke in v1 (all-or-nothing `--clear-paired` ships;
  metadata is stored to enable per-device revoke later — see Future work).
- Token storage for non-native clients. A raw `telnet` user has no disk to write
  to and just types the code each session.

## Threat model

Attacker can reach the listening TCP port on the LAN (or the operator wrongly
exposed it). Attacker does **not** have physical access to the Apple II's boot
medium. Serial and `--connect` links are point-to-point and physically owned, so
they remain ungated as today; this design only changes the `--telnet` listener.

## Auth model

The credential is a high-entropy **token** the client stores on its boot disk and
auto-sends as its first line on every connect. The bridge trusts a peer iff the
presented token's hash is in its stored set. The 6-char code only appears on
first run (no token yet) or when the disk can't be written.

IP is still logged for operator visibility (`peer connected` etc.) but is never
consulted for trust.

## Token

- 160 bits of `secrets` entropy, rendered as 32 characters in the existing
  pairing alphabet (`ABCDEFGHJKMNPQRSTUVWXYZ23456789`, uppercase, look-alikes
  dropped). Pure 7-bit ASCII: survives the wire, `to_ascii`, and the client's
  high-bit masking unchanged.
- Machine-to-machine, so length is unconstrained by human typing.
- Bridge stores only `sha256(token)` (hex). Compared with
  `secrets.compare_digest` on the hex digests (constant time).

## On-disk format (client)

One sector, reserved at build time in the VTOC so neither DOS 3.3 nor
`dos33fsprogs` allocates it. Concrete choice (adjustable in the plan):
**track `$12`, sector `$0F`** (track 17/`$11` is the catalog/VTOC; tracks 12–33
have free sectors per the disk audit).

Sector layout (256 bytes):

| Offset | Bytes | Meaning                                   |
|--------|-------|-------------------------------------------|
| 0      | 6     | magic `"CLDTK1"`                          |
| 6      | 1     | token length N (32)                       |
| 7      | N     | token, ASCII                              |
| 7+N    | 1     | checksum = 8-bit sum of bytes [0 .. 7+N-1]|
| rest   | —     | zero fill                                 |

Client reads the sector at boot via RWTS (`$BD00`); a valid token requires
matching magic **and** checksum. Anything else (blank, corrupt, stale) → treat as
unpaired. Written on issuance via RWTS-write. Sector buffer lives in the free
`$9000–$95FF` gap; the RWTS IOB and zero-page scratch respect the known-safe ZP
rules (`$06–$09`, `$FA–$FE`; dodge CHRGET `$B1–$C8`, `$D6`, `$D8`).

## Wire protocol

One new **downstream** control byte: `CMD_TOKEN = 0x05` (below the header
`0x0E`, above `EOT = 0x04`; unused today). `to_ascii` already drops `0x05` from
model text, so a reply cannot forge a token frame.

Flow:

1. Client connects → sends the existing bare-CR session-open probe.
2. **Has a valid token** → sends `<token>\r` as its first real line. The bridge's
   `require_pairing` hashes it and checks the stored set first (constant time).
   Match → paired, straight into the session, no prompt. No match → fall through
   to the code path (below), as if unpaired.
3. **No token** → client sends no first line; user is prompted (existing LOCKED
   header) and types the 6-char code. On success the bridge:
   a. generates a token, stores `sha256(token)` + device metadata,
   b. sends `0x05 <token> 0x0D` to the client, then the normal paired ack + `EOT`.
   The client captures the token frame in its receive path and RWTS-writes the
   sector. Next boot uses path 2.

Token vs code need no disambiguation prefix: they live in different comparison
sets (32-char hash lookup vs the 6-char code) and cannot collide. A 32-char
line that is neither a known token nor the code counts as one failed guess under
the existing lockout.

## Bridge changes (`bridge/`)

- `PairingManager`: replace the paired-IP `set` with a device store keyed by
  token hash. New surface: `check_token(line) -> bool` (constant-time hash
  match), `issue_token(peer) -> str` (generate, record, return plaintext once).
  Keep the code path (`check`, `record_failure`, backoff, `MAX_TRIES`) for
  first-run/fallback.
- `require_pairing`: on the first real line, try `check_token` first; else treat
  the line as a code guess. On a successful code, call `issue_token` and send the
  `CMD_TOKEN` frame before the paired ack.
- Persistence: `paired.json` becomes
  `{"v": 2, "devices": [{"token_sha256": "...", "first_ip": "...", "paired_at": <epoch>}]}`.
  Written at mode `0600` in a dir created `0700`, via temp-file + `os.replace`
  (atomic). Loader ignores unknown/legacy shapes (old v1 IP list → dropped on
  next write; those strings never match a real hash, so they are inert until
  then).
- `--clear-paired` clears the device store (revokes every device). `--no-pair`
  unchanged. Token exchange is gated to `--app` sessions.
- Logging: keep logging the peer IP and the human code (operator console), per
  the operator's request. Never log the issued token; log `paired via token` /
  `issued token to <ip>` without the secret.

This same edit pass folds in the review's other `bridge.py`/`terminal.py`/
`render.py` fixes that touch the same code (see "Companion hardening").

## Client changes (both `.s`)

Shared shape across 65816 and 6502, same logic, per-CPU asm:

- **RWTS helper**: read and write the reserved sector (build/populate an IOB,
  `jsr $BD00`), returning success/failure. Failure (write-protected, I/O error)
  is non-fatal.
- **Boot / token auto-send**: right after the CR probe in `session_start`
  (GS `claude.s:633`, 8-bit `claude2.s:1016`), RWTS-read the sector; if a valid
  token is present, send it followed by CR using the existing
  `sccput`/`aciaput` path (as `send_line` does).
- **Token capture**: add a `CMD_TOKEN` case to the receive path
  (`recv_reply` / `check_incoming` / the pairing-time reader), collect the token
  bytes to the sector buffer, and RWTS-write.
- **Fallback**: read miss / bad checksum → behave as unpaired (let the user type
  the code). Write error → proceed anyway; next boot simply prompts again.

## Build changes

- `apple2gs/build.sh`: after assembling the disk, reserve the token sector in the
  VTOC bitmap so nothing allocates it, and initialize it to a known-empty state
  (no magic) so first boot reads cleanly as "no token." Prefer a small host-side
  step (dos33fsprogs or a tiny Python VTOC tweak) over hand-editing.
- CI (optional): assert the reserved sector is present and marked allocated,
  alongside the existing COBJ/COBJ8 catalog gate.

## Error handling & edge cases

- **Write-protected disk**: RWTS-write fails → client proceeds unpaired-per-boot;
  the user types the code each session. No crash, no hang.
- **Revoked token** (`--clear-paired`): bridge no longer matches it → prompts for
  the code → issues a fresh token → client overwrites the sector.
- **Corrupt sector**: checksum fail → unpaired path.
- **Stale token, bridge lost its store**: same as revoked — re-pair, overwrite.
- **Cloned disk image**: a byte-for-byte clone of an already-paired disk carries
  the token, so clones share one identity until re-paired. Acceptable and noted;
  a freshly `build.sh`-produced disk has no token and pairs fresh (the master is
  pristine, so this is the default state).
- **Old bridge / new client or vice-versa**: both move together in this repo, but
  the client no-ops gracefully if the bridge never sends a `CMD_TOKEN` frame
  (falls back to the code each session).

## Backward compatibility / migration

No user action required. On first connect after upgrade, a client with no stored
token types the code once and is issued a token; the old IP-based `paired.json`
is superseded on the next write. Serial and `--connect` flows are unchanged.

## Companion hardening (same branch, from the security review)

These are independent of the token work but touch the same files, so they ride
along in the same branch as a separate commit:

- **Telnet IAC crash** (`terminal.py:59-67`): guard `opt is None` in
  `_handle_iac`; wrap the per-session body in the accept loop in `except
  Exception` so one peer can't take down the listener.
- **Control-byte passthrough** (`render.py:99-100`): strip `0x01–0x03` from model
  text before the bridge injects its own markers, so model output can't desync
  colors / inject a bullet / send a spurious quit.
- **stderr / exception reflection** (`backends.py`, `bridge.py`): send the peer a
  generic error; log the detailed stderr/exception to the host console only.
- **Availability ceiling** (`terminal.py`): bound `poll_ctrl_c`'s drain and add a
  wall-clock cap on an uncompleted pre-session line so a byte-trickle can't hold
  the single slot.

## Testing

- **Bridge** (extend `test_pairing.py`): token issue/verify/persist/revoke;
  hashes-only at rest (assert no plaintext token in `paired.json`);
  first-line routing (valid token vs wrong token vs code vs junk); constant-time
  compare path; atomic write + `0600` perms; legacy v1 file ignored.
- **Client** (MAME Lua, the project's existing harness): boot with an empty
  sector → type the code → assert `CMD_TOKEN` received and the sector written
  (Lua disk/memory tap) → reboot → assert the token auto-sends and no code prompt
  appears. Repeat the write-protected case → assert graceful fallback.
- **End-to-end**: against KEGS + the live bridge, full pair-then-reconnect.

## Security properties

- Token is 160-bit unguessable; online guessing is infeasible and still bounded
  by the existing per-peer lockout.
- Bridge stores only `sha256(token)`; a leaked `paired.json` yields no usable
  credential and no IPs-as-trust.
- Constant-time comparison; token never logged.
- Trust is per-device and revocable; no address is ever trusted.
- Accepted residual: plaintext token on the Apple II disk (physical-access
  threat, explicitly out of scope).

## Future work (not in v1)

- Per-device revoke using the stored `first_ip` / `paired_at` metadata (e.g.
  `--revoke <ip-or-index>`).
- Optional token rotation on a schedule.
- IIgs BRAM as a secondary store so a GS keeps its token across disk swaps.
