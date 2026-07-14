# CI Release Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository's GitHub Actions workflow start reliably, run the full Python suite, build from the repository root, and reject release disks that lack either native client.

**Architecture:** Keep the existing single CI workflow, but pin every GitHub-owned action to an immutable commit and align repository policy so only GitHub-owned actions are allowed. Move disk validation into a reusable shell script that reads the DOS 3.3 catalog, then test the validator against both a real build and a copy with `COBJ8` deleted.

**Tech Stack:** Bash, GitHub Actions YAML, pytest, dos33fsprogs, gh CLI

## Global constraints

- [ ] Keep GitHub Actions SHA pinning enabled.
- [ ] Permit GitHub-owned actions only; do not enable arbitrary third-party actions.
- [ ] Limit changes to blocker 1. Do not address release mismatch, hardware testing, rights, or unrelated bridge/runtime/security findings.
- [ ] Preserve the existing vendored DOS 3.3 master disk workflow.
- [ ] Verify locally before changing GitHub settings or pushing.

---

## Task 1: Make the disk build location-independent

**Files:**
- Modify: `apple2gs/build.sh:48`

- [ ] **Step 1: Reproduce the root-level failure**

Run from the repository root:

```bash
DOS33FSPROGS=/tmp/dos33fsprogs ./apple2gs/build.sh
```

Expected: failure opening `apple2gs/apple2gs/reserve_token_sector.py`.

- [ ] **Step 2: Fix the post-`cd` helper path**

Change:

```bash
python3 "$(dirname "$0")/reserve_token_sector.py" CLAUDE.dsk
```

to:

```bash
python3 reserve_token_sector.py CLAUDE.dsk
```

The script already changes into its own directory, so all later relative paths should be resolved there.

- [ ] **Step 3: Verify both supported invocation paths**

From the repository root:

```bash
DOS33FSPROGS=/tmp/dos33fsprogs ./apple2gs/build.sh
```

From `apple2gs/`:

```bash
DOS33FSPROGS=/tmp/dos33fsprogs ./build.sh
```

Expected: both commands build `apple2gs/CLAUDE.dsk` successfully.

- [ ] **Step 4: Commit the build fix**

```bash
git add apple2gs/build.sh
git commit -m "Fix root-level disk build"
```

---

## Task 2: Replace the string scan with a real DOS catalog gate

**Files:**
- Create: `tools/check-release-disk.sh`
- Create: `tests/test_release_gate.sh`

- [ ] **Step 1: Write the failing regression test**

Create `tests/test_release_gate.sh`:

```bash
#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOS33="${DOS33:-${DOS33FSPROGS:-/tmp/dos33fsprogs}/utils/dos33fs-utils/dos33}"
CHECK="$ROOT/tools/check-release-disk.sh"
DISK="${1:-$ROOT/apple2gs/CLAUDE.dsk}"

"$CHECK" "$DISK" >/dev/null

tmp="$(mktemp "${TMPDIR:-/tmp}/claude-gate.XXXXXX.dsk")"
trap 'rm -f "$tmp"' EXIT
cp "$DISK" "$tmp"
"$DOS33" -y "$tmp" DELETE COBJ8 >/dev/null

if "$CHECK" "$tmp" >/dev/null 2>&1; then
  echo "release gate test: accepted disk after COBJ8 deletion" >&2
  exit 1
fi

echo "release gate test: valid disk accepted; missing COBJ8 rejected"
```

Make it executable and run it:

```bash
chmod +x tests/test_release_gate.sh
DOS33FSPROGS=/tmp/dos33fsprogs ./tests/test_release_gate.sh
```

Expected: failure because `tools/check-release-disk.sh` does not exist yet.

- [ ] **Step 2: Implement the catalog validator**

Create `tools/check-release-disk.sh`:

```bash
#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DISK="${1:-$ROOT/apple2gs/CLAUDE.dsk}"
DOS33="${DOS33:-${DOS33FSPROGS:-/tmp/dos33fsprogs}/utils/dos33fs-utils/dos33}"

if [ ! -x "$DOS33" ]; then
  echo "release gate: dos33 executable not found: $DOS33" >&2
  exit 1
fi

if [ ! -f "$DISK" ]; then
  echo "release gate: disk image not found: $DISK" >&2
  exit 1
fi

catalog="$("$DOS33" "$DISK" CATALOG)"
printf '%s\n' "$catalog"

for name in COBJ COBJ8; do
  if ! printf '%s\n' "$catalog" | awk -v name="$name" \
    '$1 == "B" && $3 == name { found=1 } END { exit !found }'; then
    echo "release gate: $DISK is missing binary catalog entry $name" >&2
    exit 1
  fi
done

echo "release gate: disk contains COBJ and COBJ8"
```

Make it executable:

```bash
chmod +x tools/check-release-disk.sh
```

- [ ] **Step 3: Run the regression test**

```bash
DOS33FSPROGS=/tmp/dos33fsprogs ./tests/test_release_gate.sh
```

Expected: `release gate test: valid disk accepted; missing COBJ8 rejected`.

- [ ] **Step 4: Check both scripts with ShellCheck**

```bash
shellcheck tools/check-release-disk.sh tests/test_release_gate.sh
```

Expected: no findings.

- [ ] **Step 5: Commit the disk gate**

```bash
git add tools/check-release-disk.sh tests/test_release_gate.sh
git commit -m "Add a real DOS catalog release gate"
```

---

## Task 3: Make CI enforce the complete release gate

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Pin GitHub-owned actions to immutable revisions**

Use these exact revisions:

```yaml
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
- uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
- uses: actions/cache@0400d5f644dc74513175e3cd8d07132dd4860809 # v4.2.4
```

- [ ] **Step 2: Install and run pytest explicitly**

Add pytest to the dependency step:

```bash
python3 -m pip install pytest
```

Replace the three partial test commands with:

```bash
python3 -m pytest -q bridge tests/test_interrupt.py
```

Expected: all 55 tests run.

- [ ] **Step 3: Include the new shell scripts in linting**

Extend the ShellCheck invocation to cover:

```text
tools/check-release-disk.sh
tests/test_release_gate.sh
```

- [ ] **Step 4: Replace the release string scan**

After `./apple2gs/build.sh`, run:

```bash
DOS33="$HOME/dos33fsprogs/utils/dos33fs-utils/dos33" \
  ./tools/check-release-disk.sh apple2gs/CLAUDE.dsk
DOS33="$HOME/dos33fsprogs/utils/dos33fs-utils/dos33" \
  ./tests/test_release_gate.sh apple2gs/CLAUDE.dsk
sha256sum apple2gs/CLAUDE.dsk
```

Delete the old `strings ... | grep` loop and its stale Downloads-copy comment.

- [ ] **Step 5: Run the local CI equivalent**

```bash
python3 -m pytest -q bridge tests/test_interrupt.py
shellcheck apple2gs/build.sh tools/check-release-disk.sh tests/test_release_gate.sh
DOS33FSPROGS=/tmp/dos33fsprogs ./apple2gs/build.sh
DOS33FSPROGS=/tmp/dos33fsprogs ./tools/check-release-disk.sh apple2gs/CLAUDE.dsk
DOS33FSPROGS=/tmp/dos33fsprogs ./tests/test_release_gate.sh apple2gs/CLAUDE.dsk
shasum -a 256 apple2gs/CLAUDE.dsk
```

Expected: 55 tests pass, ShellCheck is clean, both clients are present in the DOS catalog, the deletion regression is rejected, and a SHA-256 is printed.

- [ ] **Step 6: Commit the workflow hardening**

```bash
git add .github/workflows/ci.yml
git commit -m "Harden the CI release gate"
```

---

## Task 4: Align repository policy and verify the live workflow

**Remote state:**
- Repository: `wr/apple-ii-terminal-for-claude-code`
- Branch: `main`

- [ ] **Step 1: Confirm authentication and inspect the current policy**

```bash
gh auth status
gh api repos/wr/apple-ii-terminal-for-claude-code/actions/permissions
gh api repos/wr/apple-ii-terminal-for-claude-code/actions/permissions/selected-actions
```

Expected before the change: Actions enabled, `allowed_actions` set to `local_only`, and SHA pinning enabled. The selected-actions request may return a conflict while local-only mode is active.

- [ ] **Step 2: Permit only GitHub-owned actions**

```bash
printf '%s\n' '{"enabled":true,"allowed_actions":"selected"}' |
  gh api --method PUT \
    repos/wr/apple-ii-terminal-for-claude-code/actions/permissions \
    --input -

printf '%s\n' '{"github_owned_allowed":true,"verified_allowed":false,"patterns_allowed":[]}' |
  gh api --method PUT \
    repos/wr/apple-ii-terminal-for-claude-code/actions/permissions/selected-actions \
    --input -
```

Do not disable SHA pinning.

- [ ] **Step 3: Verify the effective policy**

```bash
gh api repos/wr/apple-ii-terminal-for-claude-code/actions/permissions
gh api repos/wr/apple-ii-terminal-for-claude-code/actions/permissions/selected-actions
```

Expected: `allowed_actions` is `selected`, GitHub-owned actions are allowed, verified actions and custom patterns are disallowed, and SHA pinning remains enabled.

- [ ] **Step 4: Push `main`**

```bash
git status --short
git log --oneline -5
git push origin main
```

Expected: the local commits reach `origin/main` and trigger CI.

- [ ] **Step 5: Watch the triggered run to completion**

```bash
gh run list --workflow ci.yml --branch main --limit 3
gh run watch <run-id> --exit-status
gh run view <run-id> --json conclusion,jobs,url
```

Expected: the workflow starts, all jobs execute, and the conclusion is `success`.

- [ ] **Step 6: Record final evidence**

Report:

- the local pytest count;
- successful root and in-directory disk builds;
- the valid/mutated disk gate result;
- the disk SHA-256;
- the effective Actions policy;
- the successful GitHub Actions run URL;
- that blockers 2, 3, and 4 were intentionally left untouched.
