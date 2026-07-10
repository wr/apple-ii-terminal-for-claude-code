# Apple II terminal setup

How to get your IIgs or IIc talking to the bridge. Two paths: a **serial cable**
(works on both machines) or a **WiFi modem / network** (IIgs).

Start with serial — it's the fewest moving parts.

---

## Serial: the cable

The Apple II serial ports are RS-422 (the same family as classic Mac serial),
not RS-232. To reach a modern host you need a USB-serial adapter and the right
cable for your machine's connector:

| Machine            | Connector        | Cable                                                            |
|--------------------|------------------|-----------------------------------------------------------------|
| **IIgs**           | mini-DIN-8       | A "Mac serial to USB" FTDI cable works directly (IIgs serial is Mac-compatible RS-422). |
| **IIc Plus**       | mini-DIN-8       | Same as the IIgs.                                                |
| **Original IIc**   | 5-pin DIN (DIN-5)| Needs a DIN-5 cable/adapter — not the same as the IIgs. Retro-computing sellers (e.g. the A2 community) make these; or wire your own from the pinout below. |

RS-422 is differential and RS-232 is single-ended, but at these baud rates the
common trick works fine: connect the II's TXD- to the adapter's RX, RXD- to the
adapter's TX, ground to ground, and tie the unused differential legs to ground.
A proper RS-422↔RS-232 adapter is cleaner if you have one.

If you're buying rather than wiring: search for an "Apple IIgs serial USB cable"
(mini-DIN-8) or an "Apple IIc modem cable" (DIN-5) — these are sold ready-made.

### IIgs / IIc Plus mini-DIN-8 pinout (the port, looking at the machine)

```
   pin 3  TXD-   -> adapter RXD
   pin 5  RXD-   -> adapter TXD
   pin 4  GND    -> adapter GND
   pin 8  RXD+   -> tie to GND
   pin 6  TXD+   -> leave / tie to GND
   pin 1  HSKo (RTS)  -> adapter CTS   (only if using --rtscts)
   pin 2  HSKi (CTS)  -> adapter RTS   (only if using --rtscts)
```

Use **port 2 (modem)** on the IIgs by convention. Port 1 is the printer port;
it also works.

---

## Serial: settings on both sides

Set the Apple II terminal program and the bridge to match. A good starting point:

- **9600 baud, 8 data bits, no parity, 1 stop bit (8N1)**
- Local echo **OFF** (the bridge echoes what you type)
- Flow control: none to start

Bridge side:

```sh
python3 bridge.py --serial /dev/tty.usbserial-XXXX --baud 9600 --cols 80
```

Bump to `--baud 19200` once it's stable (the IIc's 6551 tops out around there;
the IIgs can go faster). At higher baud, add flow control on both sides:
`--rtscts` if your cable has the handshake lines wired, otherwise `--xonxoff`.
If Claude's replies drop characters and you have no flow control, throttle the
bridge with `--pace-cps 600`.

---

## Terminal software

### IIgs

Use a real comms program — load it from the BlueSCSI:

- **ProTERM**, **Spectrum**, or **Talk Is Cheap** are the classics.
- Set the connection to the serial port you wired (modem port), 9600 8N1,
  local echo off.
- Terminal emulation: plain **TTY/glass-tty** is safest. The bridge sends only
  ASCII and CR/LF, so you don't need ANSI or VT100. If your program defaults to
  VT100, that's fine too.

Put a disk image with your comms program onto the BlueSCSI and boot it.

### IIc

The IIc has no slots, so it's serial or nothing — which is perfect here.

- **ProTERM** runs on the IIc and is the reliable choice. 9600 8N1, echo off.
- **No-disk option:** the serial firmware has a built-in terminal mode. From the
  `]` prompt, type `IN#2` and press Return, then press **Control-A** followed by
  **T**. Keyboard now goes out the port and received bytes print to the screen,
  with BASIC out of the loop. Exit with **Control-A** then **Q**.

  Set the port to 9600 8N1 first via the command character if needed:
  `Control-A` `1` `4` `B` `Return` (9600 baud); 8N1 is already the default.
  Don't use `IN#2` alone — that hands each received line to BASIC and you get
  `?SYNTAX ERROR`. (Serial command character is Control-A on the modem port.)

---

## WiFi modem / telnet (IIgs)

If you have an ESP-based WiFi modem (Zimodem/RetroWiFi style) or an Uthernet II:

1. Run the bridge as a TCP server on your host:

   ```sh
   python3 bridge.py --telnet --port 6400 --cols 80
   ```

2. From the II's terminal program, dial the bridge. With a WiFi-modem in command
   mode, telnet to the host's IP:

   ```
   ATDT192.168.1.50:6400
   ```

   (Replace with your host's LAN IP.) A plain telnet client works too.

3. If you use a raw `telnet` client (not a modem passing bytes through), add
   `--telnet-negotiate` to the bridge so it answers the telnet option handshake
   and its negotiation bytes don't show up as garbage.

The bridge listens for one connection at a time. Reconnect and it picks up the
next caller.

---

## KEGS emulator (no hardware)

KEGS routes each emulated serial port to a TCP socket, so you can test without a
cable. Press **F4** → Serial Port Configuration and set **Slot 2** to one of:

- **Incoming** — KEGS listens on TCP **6502**. Dial in from the host:

  ```sh
  python3 bridge.py --connect 127.0.0.1:6502 --cols 80
  ```

  This is the simplest option. Inside KEGS, use a terminal program on Slot 2, or
  from the Applesoft `]` prompt enter the serial firmware's terminal mode:
  type `IN#2` and press Return, then press **Control-A** followed by **T**. That
  turns the port into a glass terminal (keyboard out, serial in) and stops BASIC
  from parsing the incoming text. Exit with **Control-A** then **Q**.

  Do NOT use `IN#2` alone or `IN#2` + `PR#2` — that feeds each received line to
  the BASIC interpreter and you get `?SYNTAX ERROR` on every line.

- **Virtual modem** — KEGS dials out like a Hayes modem. Run the bridge as a
  server (`python3 bridge.py --telnet --port 8888`) and inside KEGS type
  `ATDT 127.0.0.1:8888`. Set `g_serial_modem_init_telnet = 0` in `config.kegs`
  (or leave the bridge without `--telnet-negotiate`) for a clean raw stream.

Slot 1 uses port 6501; Slot 2 uses 6502. Baud doesn't matter under emulation —
KEGS moves bytes as fast as the socket allows.

## First contact

1. Start the bridge on the host. It prints `waiting...` (telnet) or the serial
   port it opened.
2. Connect from the Apple II.
3. You should see the `CLAUDE ][` banner. Type `/help`.
4. Type a question, press Return. Claude's reply streams in, wrapped to your
   screen width.

If the banner never shows: wrong baud, wrong port, or TX/RX swapped. If you see
the banner but typing does nothing: check that the II's terminal is actually
sending on the same port. If you see doubled letters: local echo is on — turn it
off (or run the bridge with `--no-echo`).
