# Modem setup

The modem link is the one step where hardware, cables, and firmware all have
to agree, and it's where most setups stall. This page gets you from "modem in
hand" to a working **Connect**, and ends with a checklist for when the modem
plays dead.

The short version: the client talks **9600 8N1** on the modem port, the boot
menu's Connect dials **`ATDS=0`** (phone book entry 0), and the bridge listens
on TCP **6400**. Any Hayes-compatible WiFi modem that can store `host:port` in
a phone book slot and dial it will work; the syntax for that varies by device
(covered below).

## WiModem 232 / 232 Pro — what we run

Everything here is from the official CBMSTUFF manual (firmware 6.2). The Pro
adds an OLED that shows baud/IP/status, which alone is worth it for debugging.

**It ships at 300 baud.** The native clients only speak 9600, so a
factory-fresh WiModem answers the boot menu's AT console with garbage. Fix it
once, from any terminal that can do 300 baud (ProTERM, or the IIc's built-in
firmware terminal — see [TERMINAL-SETUP.md](../apple2/TERMINAL-SETUP.md)):

```
AT*B9600        modem now talks 9600
AT&W            save
```

After that the boot menu's **Modem** console works, and the rest is:

```
AT*SSIDYourNetwork,YourPassword     join WiFi (no space after SSID;
                                     both are case-sensitive)
AT&Z0=192.168.1.50:6400             your bridge host as phone book entry 0
AT&W                                save
```

Then **Connect** on the menu dials it. Alternatives for the WiFi join:
`AT*WPS` (press the router's WPS button first), `AT*WIFI` (opens a config
portal you join from a phone, SSID "WiModem232"), or `AT*N` to scan then
`AT*NS<number>,<passphrase>` to pick from the list. The status LED tells the
story: pulsing red = hunting for the router, yellow = WiFi up, green =
connected.

Useful extras: `ATI` prints the full status page (firmware, baud, IP, SSID).
`AT*D` sets DCD polarity — this matters on a Super Serial Card, see the
checklist. `AT*MODE1` + `AT&W` powers the radio down at boot until needed,
which quiets RF noise when the modem hangs directly off the machine.

## Cabling, per machine

The WiModem (like most WiFi modems) is a DB25-male device that acts like a
real Hayes modem (DCE). You need the cable that puts your machine's serial
port on a DB25 pointed at a modem:

| Machine | Port | Cable |
|---|---|---|
| IIgs | mini-DIN-8 **modem port** | "Apple/Mac 8-pin mini-DIN to DB25 male **modem** cable" — the classic Mac Plus/SE external-modem cable, still sold by retro parts shops |
| IIc | DIN-5 | "Apple IIc modem cable" (DIN-5 to DB25 male) |
| IIc Plus | mini-DIN-8 | Same cable as the IIgs |
| IIe / II+ | Super Serial Card in slot 2, DB25 | Straight-through DB25 (or the modem plugs on directly with a gender changer) |

Two traps in that table:

- A Mac **printer** cable looks identical to a modem cable and silently swaps
  the wrong pairs. If the modem never answers on a IIgs, suspect the cable's
  ancestry first.
- On the SSC, the **jumper block arrow must point to MODEM**. Pointed at
  TERMINAL, the card crosses TxD/RxD for talking to terminals, and a modem on
  the other end hears nothing. This is the single most common "dead modem" on
  slotted machines. While you're in there: SW1-5, SW1-6, SW1-7 ON for modem
  use (the baud DIPs don't matter — the client programs the chip directly).
- Never put a **null-modem adapter** between an SSC and a WiFi modem. The SSC
  in MODEM mode already presents the right way around; a null modem re-crosses
  it and breaks it. Gender changers are fine, null modems are not.

## Other WiFi modems

The catch: **`ATDS=0` — with the equals sign — is WiModem232 syntax.** Other
firmware stores phone book entries fine but dials them differently, so
Connect's auto-dial may error on them. The universal workaround is built into
the client: dial by hand from the boot menu's **Modem** console, Esc back, and
pick **Connect** — with the modem already online, the stray dial string passes
through to the bridge (which swallows it) and the session starts after the
3-second window. On a IIgs whose modem drives DCD, Connect skips the redial
entirely.

| Device | Store entry 0 | Dial it | Ships at | Notes |
|---|---|---|---|---|
| WiModem 232 (Pro) | `AT&Z0=host:6400` | `ATDS=0` — Connect just works | 300 | `AT*B9600` first |
| WiFi232 (Rickards) | `AT&Z0=host:6400` | `ATDS0` (no `=`) | 1200 | WiFi join: `AT$SSID=name`, `AT$PASS=pw`, `ATC1`; baud `AT$SB=9600`; save `AT&W`. Store the port explicitly — it defaults to 23 |
| Zimodem / RetroWiFi (ESP8266/ESP32 builds) | `ATP"0000000=host:6400"` | `ATD0000000` | varies (often 1200) | WiFi join: `ATW"ssid,password"`. No slot dialing — `ATDS` means SSH here. Use the manual-dial workaround |
| FujiNet and friends | — | `ATDT host:6400` | — | No slot storage confirmed; manual-dial workaround |

(If you test `ATDS0` without the equals on a WiModem232 and it works, tell us —
we'd switch the client's dial string and WiFi232 would work out of the box.)

## The modem plays dead — checklist

In the order they actually happen:

1. **SSC jumper block backwards.** Arrow to MODEM. Most common cause on a
   IIe/II+.
2. **DCD not asserted.** The SSC won't pass received data unless carrier
   detect is high, so a modem that doesn't drive DCD looks completely dead
   even with perfect cabling. On the WiModem, flip polarity with `AT*D1`
   (save with `AT&W`); the WiFi232 loops DCD to DTR on the board; worst case,
   strap DB25 pin 8 high in the cable.
3. **Printer cable, not modem cable** (IIgs/IIc Plus mini-DIN-8).
4. **Baud mismatch.** The modem answers, but as garbage. Factory WiModem =
   300, factory WiFi232 = 1200; the client is 9600. Fix on the modem side,
   once, and save.
5. **A null-modem adapter that shouldn't be there.**

Related symptoms:

- **Every letter shows twice (or three times).** Stacked echo: the client
  echoes locally and the modem's `ATE1` echoes too. Send `ATE0` and `AT&W`
  from the AT console.
- **Junk on screen before the dial.** WiFi modems announce things
  ("RECONNECTED", RING) on the wire. The client flushes before dialing and the
  bridge swallows known modem chatter, so this is cosmetic — but if you see it
  constantly, check baud.
- **Dial fails instantly with ERROR.** The modem didn't like the dial string —
  usually a non-WiModem device (see the table above), or entry 0 was never
  saved with `AT&W`.
