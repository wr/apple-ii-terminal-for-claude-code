# Security

This project bridges a real `claude` CLI to an Apple II over a serial line or your LAN. In code mode that CLI reads and writes files and runs commands on the host, so a few things are worth being plain about.

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | Yes |
| < 1.0 | No |

Fixes land on the latest 1.0.x release.

## Reporting a vulnerability

Open a [GitHub issue](https://github.com/wr/apple-ii-terminal-for-claude-code/issues). For anything you'd rather not post in the open, use GitHub's private ["Report a vulnerability"](https://github.com/wr/apple-ii-terminal-for-claude-code/security/advisories/new) advisory flow, or email the maintainer at media [at] wells [dot] ee. I'll respond as soon as I can — this is a hobby project, so no formal SLA.

## Security model

The bridge is one Python script you run on your own machine. It has no accounts, no server, and no telemetry. What matters is who can reach it and what it does with what it hears.

### Network exposure

`--telnet` makes the bridge listen for a WiFi modem or TCP client (port 6400). In code mode that hands whoever connects a `claude` session — effectively a shell — on the host. **Run it only on a home LAN you trust. Never port-forward it or bind it to a public interface.** Use `--host 127.0.0.1` to keep it local, or a serial cable (`--serial`) to avoid the network entirely.

### The pairing gate

A listening bridge is gated by a pairing code before any session proceeds (`--telnet` only; disable with `--no-pair` on an isolated network). It's already hardened:

- A **6-character code** (uppercase + digits, look-alikes dropped; ~8.9e8 combinations) printed at startup. Set your own with `--pair-code`.
- **Per-peer exponential backoff and a hard guess cap** — 3 free tries, then doubling delays, 10 attempts max per peer per run. Strike counts are keyed by IP and survive reconnects, so a caller can't reset them by redialing.
- **A per-device code**: by default each source IP gets its own pairing code, minted on first sight and printed to the bridge console when that device connects — so a code seen for one device can't enroll a different one, and the code only ever appears on the operator's console, never on the wire. Set `--pair-code` to fix one shared code instead. Already-paired devices are unaffected; they present their token, not the code.
- **Revocation**: `--clear-paired` (or the startup flag) forgets every remembered device.

Ongoing pairing/hardening work is tracked separately; this file describes what ships today.

### What's logged and stored

- **Prompts print to the console.** Every line you type from the Apple II is echoed to the bridge's own stdout so you can watch the session. Replies are logged as metadata only (timing and line count), not their text.
- **Only a token hash touches disk.** Once a device pairs, the bridge mints a 160-bit device token, sends it to the client once (`CMD_TOKEN`, `0x05`), and persists only its SHA-256 — never the plaintext — in `~/.config/claude-ii-terminal/paired.json` (schema v2, directory `0700`, file `0600`, written atomically). A reconnect proves itself by presenting that token, matched with a constant-time compare. Peer IPs are logged for visibility but are never trusted as proof of identity. Delete the file, or run `--clear-paired`, to forget every device.
- **The token itself lives in plaintext on the Apple II disk** (written to a reserved sector so the client can auto-present it on reconnect). Anyone with physical or disk-image access to that floppy/SD card can extract it — this is an accepted risk of a client with no secure storage of its own; treat the disk like a house key.

Nothing else is persisted, and nothing is sent anywhere but to Claude for the actual conversation.
