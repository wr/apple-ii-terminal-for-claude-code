# Phase 2 — Bridge protocol wiring: report

## Task 2.1 — token-first routing + CMD_TOKEN issuance

Status: done.

- Created `bridge/test_pairing_flow.py` verbatim from the plan; confirmed it
  failed first (`ImportError: cannot import name 'CMD_TOKEN'`).
- Added `CMD_TOKEN = b"\x05"` next to `EOT` in `bridge.py`.
- Rewrote the guess-handling block of `require_pairing`: a presented line is
  now tried as `pm.check_token(line)` first, then the exhausted-guess check,
  then `pm.check(peer, line.upper())` — a code success in `--app` mode now
  calls `pm.issue_token(peer)` and writes `CMD_TOKEN + tok.encode('ascii') +
  b"\r"` before the EOT.
- Deleted the top-of-function `if pm.is_paired(peer): return True`
  short-circuit — trust is proven by presenting a token, not by IP.
- Fixed `main`'s connection-note logging, which called `pm.is_paired(peer)`;
  replaced with the IP-neutral `" · will pair by token or code"`.
- `grep -n is_paired bridge.py` → no output.
- All 3 new tests pass; `test_pairing.py` + `test_pairing_flow.py` green
  together.

Commit: `ce13555` — "require_pairing: token-first routing, issue CMD_TOKEN on code success"

## Test reconciliation (its own commit)

Commit: `5d903bf` — "Reconcile pairing tests with token-based model"

Of the ~10 pre-existing failures the prior phase left, the actual failing
set in `test_pairing.py` was 6 tests (the rest of the ~10 figure apparently
included tests fixed incidentally by Task 1.1-1.3 already committed before
this phase started). Per test:

- `test_right_and_wrong_code` — **rewritten**: dropped the trailing
  `is_paired` assertions. `check()` no longer marks a peer paired by itself
  (that's `issue_token`'s job now); the code-validation behavior it also
  tested (right/wrong compare) is still fully covered.
- `test_window_expiry` — **rewritten**: dropped the trailing
  `assertFalse(pm.is_paired("q"))` line. The window-closed-rejects-even-a-
  correct-code behavior it primarily tests is untouched and still asserted.
- `test_revocation_and_persistence` — **rewritten**: this exercised
  persist → reload → revoke → reload via the removed `pm.paired`/`is_paired`
  API. Same lifecycle, same coverage, re-expressed through
  `issue_token`/`check_token`: issue a token, confirm a fresh `PairingManager`
  loaded from the same store still recognizes it, `clear_paired()` revokes
  it, and a third fresh manager confirms it's gone.
- `test_paired_peer_passes_without_asking` — **removed**. It asserted that
  seeding `pm.paired` (an in-process IP set) with a peer's address let that
  peer skip the prompt entirely — i.e., IP alone was proof of trust. That
  contract is exactly what this phase eliminated; no rewrite preserves it
  because presenting a valid token is now mandatory every connection.
  Replacement coverage already exists in `test_pairing_flow.py`
  (`test_valid_token_first_line_pairs_without_code`), which is the correct
  token-based analog.
- `test_locked_header_on_empty_probe`, `test_wrong_then_right` — **rewritten**:
  both asserted the literal `b"Paired"` text in the transcript after a code
  success. In `--app` mode that text is no longer sent (only a `CMD_TOKEN`
  frame is, per the plan); rewritten to assert `bridge.CMD_TOKEN` appears in
  the output instead. `test_wrong_then_right` also gained an explicit
  `len(pm.devices) == 1` check so the "a token really got issued" assertion
  isn't lost along with the text check.

Backoff, lockout, window/TTL, and constant-time-compare coverage
(`test_backoff_grows_after_free_tries`, `test_backoff_capped`,
`test_guess_cap_exhaustion`, `test_ttl_zero_never_closes`,
`test_constant_time_compare_used`, `test_exhausted_peer_locked_out`,
`test_window_closed_refuses`, `test_dial_string_and_chatter_not_a_guess`,
`test_lowercase_code_accepted`) were untouched — none referenced the removed
API and none were weakened.

`test_pairing.py`: 27/27 pass after reconciliation (was 22 passed / 6 failed
before).

## Task 2.2 — documentation

Status: done. Commit: `eb412ed` — "Document the CMD_TOKEN frame and token-based pairing"

- `AGENTS.md`: added the `0x05 <token> CR` entry to the in-band control
  scheme list (verbatim per the plan), and reworded the `--telnet` pairing
  bullet to describe token-based trust (code mints a token once via
  `CMD_TOKEN`; only its SHA-256 persists; a reconnect proves itself by
  presenting the token) instead of the old "paired peers persist" phrasing.
- `SECURITY.md`: replaced the "Paired peer IPs touch disk" bullet with a
  description of the v2 `paired.json` store (SHA-256 hashes only, dir
  `0700`/file `0600`, atomic write, constant-time compare, IPs logged but
  never trusted), and added a new bullet calling out the accepted risk that
  the token itself lives in plaintext on the Apple II disk (physical-access
  threat, not mitigated).

## Full suite

`bridge/.venv/bin/python -m pytest -q` → **48 passed**, no failures, no
regressions outside `test_pairing*.py`.

## Commit hashes (this phase)

1. `ce13555` — require_pairing: token-first routing, issue CMD_TOKEN on code success
2. `5d903bf` — Reconcile pairing tests with token-based model
3. `eb412ed` — Document the CMD_TOKEN frame and token-based pairing

## Concerns / notes

- `require_pairing`'s `if not pm.window_open(): return False` check still
  runs *before* the token-first check in the per-line loop is even reached
  (it's a whole-function early return). That means once `--pair-ttl` closes
  the window, an already-paired device presenting a valid stored token would
  also be refused — the plan's Task 2.1 only specified deleting the
  `is_paired` short-circuit, not reordering the window check relative to
  token validation, so I followed the plan as written. Worth flagging since
  in practice `--pair-ttl` defaults to 15 minutes and tokens are meant to
  outlive restarts — a returning device could get locked out until the
  bridge restarts (which reopens the window). Not fixed here since it's out
  of this phase's explicit scope (Phase 3+ / a follow-up would need to
  decide whether token-holders should bypass the window entirely).
- Did not touch Phase 0/1/3-6 work; only Phase 2 (Tasks 2.1, 2.2) plus the
  requested test-suite reconciliation.

## Critical fix pass

Status: done. Fixed the exact issue flagged above under "Concerns / notes" —
the security review rated it Critical: the whole-function
`if not pm.window_open(): return False` gate ran before the per-line loop
ever reached `pm.check_token(line)`, so ~15 minutes after bridge start
(default `--pair-ttl 15`) an already-paired device presenting a **valid,
previously-issued token** was refused with "PAIRING CLOSED" and never got a
chance to authenticate. That defeated the whole point of persistent tokens
and contradicted the `--pair-ttl` help text ("Paired devices are
unaffected").

Fix, in `bridge/bridge.py`'s `require_pairing`:
- Deleted the top-of-function `window_open()` gate entirely.
- Re-added the identical refusal (same log line, same `PAIRING CLOSED`
  lock-header/EOT for `--app`, same plain-text line otherwise) *inside* the
  per-line loop, placed immediately after the `check_token` success branch
  and before the `exhausted(peer)` check. Net effect: a stored token is
  checked and can succeed regardless of window state; only a peer who is
  *not* presenting a valid token gets bounced once the window has closed
  (before it ever reaches the code-guess/lockout logic).

Tests:
- `test_pairing.py::TestRequirePairing::test_window_closed_refuses` — updated
  from feeding an empty channel (which relied on the old eager whole-function
  return) to feeding one non-token junk line (`b"NOTATOKEN\r"`) via the
  existing `run_pairing` background-thread helper, since the refusal is now
  reactive and only fires after a real line is evaluated and fails
  `check_token`. Assertion (`assertFalse` + `PAIRING CLOSED` in output) left
  unweakened.
- `test_pairing_flow.py::test_valid_token_pairs_after_window_closes` — new
  test, using the file's existing `_FakeTerm`/`_args` helpers: issues a
  token, forces `pm.born` back an hour to close the window, scripts the
  fake terminal to present that token as its first line, and asserts
  `require_pairing(...) is True`. Verified this test **fails** against the
  pre-fix code (`assert False is True`, log shows "window closed; refusing
  new device") and **passes** after the fix.

Verification run:
- `bridge/.venv/bin/python -m pytest test_pairing.py test_pairing_flow.py -v`
  → **31 passed**, 0 failed.
- `bridge/.venv/bin/python -m pytest -q` (full suite) → **49 passed**, 0
  failed, no regressions.
