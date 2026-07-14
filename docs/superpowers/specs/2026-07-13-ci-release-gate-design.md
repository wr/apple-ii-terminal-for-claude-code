# CI Release Gate Design

## Goal

Make GitHub Actions start successfully and ensure it rejects any release disk
that lacks either native client.

## Repository policy

Keep the repository's full-SHA requirement for actions. Allow GitHub-owned
actions, then pin `actions/checkout`, `actions/setup-python`, and
`actions/cache` to immutable commit SHAs. Do not allow arbitrary third-party
actions.

## Build behavior

`apple2gs/build.sh` must work both from the repository root and from inside
`apple2gs`. It will resolve files relative to the directory it changes into,
so the token-sector reservation script cannot acquire a duplicated
`apple2gs/apple2gs` prefix.

## Test coverage

CI will install pytest and run the complete Python suite rather than invoking
only the older standalone test entrypoints. The full command is:

```sh
python3 -m pytest -q bridge tests/test_interrupt.py
```

The existing shell checks and both-client assembly checks remain.

## Disk validation

A reusable shell validator will inspect `dos33 CLAUDE.dsk CATALOG` and require
real binary catalog entries named `COBJ` and `COBJ8`. Searching raw disk strings
is not acceptable because HELLO contains both names even when a binary file is
missing.

A regression test will:

1. Accept a correctly built disk.
2. Delete `COBJ8` from a temporary copy.
3. Confirm the validator rejects that copy.

CI will run the validator after the full build and print the disk SHA-256 for
release bookkeeping.

## Verification

Local verification must cover the full pytest suite, shellcheck, a root-level
build, the disk-gate regression test, the final catalog, and a clean worktree.
After the commit is pushed, the GitHub Actions run must complete successfully;
local success alone does not resolve this blocker.
