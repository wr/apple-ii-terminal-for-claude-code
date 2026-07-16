# Security

This project bridges a real `claude` CLI to an Apple II over a serial line or your LAN. In code mode that CLI reads and writes files and runs commands on the host, so a few things are worth being plain about.

## Supported versions

| Version | Supported |
|---|---|
| 1.1.x | Yes |
| 1.0.x | No |
| < 1.0 | No |

Fixes land on the latest 1.1.x release.

## Reporting a vulnerability

Open a [GitHub issue](https://github.com/wr/apple-ii-terminal-for-claude-code/issues). For anything you'd rather not post in the open, use GitHub's private ["Report a vulnerability"](https://github.com/wr/apple-ii-terminal-for-claude-code/security/advisories/new) advisory flow, or email the maintainer at media [at] wells [dot] ee. I'll respond as soon as I can — this is a hobby project, so no formal SLA.

## Security model

The bridge is one Python script you run on your own machine. It has no accounts, no server, and no telemetry. What matters is who can reach it and what it does with what it hears.

### Network exposure

`--telnet` makes the bridge listen for a WiFi modem or TCP client (port 6400). In code mode that hands an accepted caller a `claude` session — effectively a shell — on the host. Telnet does not encrypt pairing codes, tokens, prompts, or replies. A caller who captures an unused code or a valid token may be able to replay it. **Run the listener only on a home LAN you trust. Never port-forward it or bind it to a public interface.** Use `--host 127.0.0.1` to keep it local, or a serial cable (`--serial`) to avoid the network entirely.

### The pairing gate

A listening bridge is gated by a pairing code before any session proceeds (`--telnet` only; disable with `--no-pair` on an isolated network):

- **On-demand codes.** By default the bridge creates a 6-character code (uppercase letters and digits, with look-alikes dropped; about 8.9e8 combinations) when an unpaired source IP first needs one. It prints the code on the bridge console, then the caller sends it over the plaintext connection. The generated code remains valid and replayable from that source IP until a successful pairing consumes it. Source IP is a throttle and code-assignment key, not device identity.
- **Shared pinned codes.** `--pair-code` fixes one code for every caller instead. Letters are case-insensitive. A pinned code is not consumed after use.
- **Retry limits.** The first unrecognized token-shaped credential from each source IP in a bridge run is treated as a stale token and does not spend a strike, in either native (`--app`) or raw telnet mode. After that, the first 3 wrong pairing-code guesses have no delay. Later misses sleep for 2 seconds, 4 seconds, then at most 8 seconds per attempt. The hard limit is 10 code guesses per source IP per bridge run. Strike counts survive reconnects during that run.
- **Native token persistence.** With `--app`, a successful code exchange mints a token and consumes a generated code. The 8-bit client stores the plaintext token on its boot disk and presents it after reboot. The IIgs client retains the token only in RAM for reconnects during the current boot because DOS RWTS is unsafe in its native session path. Possession of either token grants access from any source IP. A valid-token reconnect neither needs nor prints a code.
- **Raw telnet has no token persistence.** Without `--app`, the bridge does not issue a token. A raw terminal must enter the current console code for each new session.
- **Revocation**: `--clear-paired` revokes every stored token credential.

Ongoing pairing/hardening work is tracked separately; this file describes what ships today.

### What's logged and stored

- **Prompts print to the console.** Every line you type from the Apple II is echoed to the bridge's own stdout so you can watch the session. Replies are logged as metadata only (timing and line count), not their text.
- **Pairing records contain a hash and metadata.** For each issued token, the bridge stores its SHA-256, first-seen IP, and pairing time in schema v2. The path is `$XDG_CONFIG_HOME/claude-ii-terminal/paired.json`, falling back to `~/.config/claude-ii-terminal/paired.json` when XDG is unset. Writes use a temporary file and atomic replace. The newly created leaf pairing directory and file request modes `0700` and `0600`; existing path modes are not repaired. Delete the file, or run `--clear-paired`, to revoke every stored token.
- **The 8-bit client's token lives in plaintext on the Apple II disk** (written to a reserved sector so the client can auto-present it after reboot). Anyone with physical or disk-image access to that floppy/SD card can extract it — this is an accepted risk of a client with no secure storage of its own; treat the disk like a house key. The IIgs client keeps its token only in RAM, so it must pair again after reboot.
