"""Tests for the listening-bridge access control (bridge.py pairing).

Covers the protections added for the "weak pairing" hardening pass:
  * higher-entropy, Apple II-typeable pairing codes
  * per-peer wrong-code lockout with exponential backoff + a hard guess cap
  * per-device pairing codes (each source IP gets its own, or a pinned code)
  * revocation of remembered (paired) peers
  * bounded input length on the terminal read path

No emulator, no network: a FakeChannel stands in for the Apple II and the
real Terminal + require_pairing run against it.

Run:  python3 -m pytest test_pairing.py -v   (or: python3 test_pairing.py)
"""
import os
import queue
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bridge
from bridge import PairingManager, gen_pair_code, _PAIR_ALPHABET
from terminal import Terminal, TermConfig


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeChannel:
    is_network = True
    peer = "10.0.0.9"

    def __init__(self):
        self.rx = queue.Queue()
        self.tx = bytearray()
        self._lock = threading.Lock()

    def feed(self, data: bytes):
        for b in data:
            self.rx.put(b)

    def read_byte(self):
        try:
            return self.rx.get(timeout=0.05)
        except queue.Empty:
            return -1

    def write(self, data: bytes):
        with self._lock:
            self.tx.extend(data)

    def out(self) -> bytes:
        with self._lock:
            return bytes(self.tx)

    def close(self):
        pass


class Args:
    app = True
    cols = 80


def make_pm(code="ABC234", pinned=True):
    """A manager with a throwaway store and no real throttling delay. `pinned`
    fixes one code for all peers; pinned=False gives per-IP codes."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # start with no file (a fresh, unpaired store)
    pm = PairingManager(code if pinned else "", store_path=path)
    pm.SLEEP_CAP = 0.0  # don't actually sleep the backoff in tests
    return pm, path


def run_pairing(pm, feed: bytes, preloaded=b""):
    """Drive require_pairing on a background thread; return (result, channel)."""
    ch = FakeChannel()
    if preloaded:
        ch.feed(preloaded)
    term = Terminal(ch, TermConfig(width=80, echo=False, telnet=False))
    box = {}

    def go():
        box["r"] = bridge.require_pairing(term, Args(), pm)

    t = threading.Thread(target=go, daemon=True)
    t.start()
    time.sleep(0.05)
    ch.feed(feed)
    t.join(timeout=4)
    assert not t.is_alive(), "require_pairing did not return"
    return box.get("r"), ch


# --------------------------------------------------------------------------- #
# Code generation
# --------------------------------------------------------------------------- #
class TestCodeGen(unittest.TestCase):
    def test_length_and_alphabet(self):
        for _ in range(200):
            c = gen_pair_code()
            self.assertEqual(len(c), 6)
            self.assertTrue(set(c) <= set(_PAIR_ALPHABET))

    def test_no_ambiguous_chars(self):
        # I/L/O and 0/1 are the look-alikes we must never emit.
        self.assertFalse(set("ILO01") & set(_PAIR_ALPHABET))

    def test_entropy_beats_four_digits(self):
        # 31**6 must dwarf the old 10**4 space.
        self.assertGreater(len(_PAIR_ALPHABET) ** 6, 10 ** 4 * 10000)

    def test_reasonably_unique(self):
        codes = {gen_pair_code() for _ in range(500)}
        self.assertGreater(len(codes), 490)  # essentially no collisions


# --------------------------------------------------------------------------- #
# Manager logic
# --------------------------------------------------------------------------- #
class TestManager(unittest.TestCase):
    def test_right_and_wrong_code(self):
        # Code success no longer marks the peer "paired" itself (that's now
        # `issue_token`'s job) - `check` just validates the human code.
        pm, path = make_pm("ABC234")
        try:
            self.assertFalse(pm.check("p", "WRONG"))
            self.assertTrue(pm.check("p", "ABC234"))
        finally:
            os.path.exists(path) and os.unlink(path)

    def test_backoff_grows_after_free_tries(self):
        pm, path = make_pm()
        try:
            waits = [pm.record_failure("p") for _ in range(6)]
            # first FREE_TRIES are free (no wait), then it climbs
            self.assertEqual(waits[:pm.FREE_TRIES], [0.0] * pm.FREE_TRIES)
            self.assertGreater(waits[pm.FREE_TRIES], 0.0)
            self.assertGreater(waits[-1], waits[pm.FREE_TRIES])
        finally:
            os.path.exists(path) and os.unlink(path)

    def test_backoff_capped(self):
        pm, path = make_pm()
        try:
            last = 0.0
            for _ in range(40):
                last = pm.record_failure("p")
            self.assertLessEqual(last, pm.BACKOFF_CAP)
        finally:
            os.path.exists(path) and os.unlink(path)

    def test_guess_cap_exhaustion(self):
        pm, path = make_pm()
        try:
            self.assertFalse(pm.exhausted("p"))
            for _ in range(pm.MAX_TRIES):
                pm.record_failure("p")
            self.assertTrue(pm.exhausted("p"))
        finally:
            os.path.exists(path) and os.unlink(path)

    def test_pinned_code_same_for_every_peer(self):
        pm, path = make_pm("ABC234")            # pinned
        try:
            self.assertEqual(pm.code_for("10.0.0.1"), "ABC234")
            self.assertEqual(pm.code_for("10.0.0.2"), "ABC234")
            self.assertTrue(pm.check("10.0.0.1", "ABC234"))
        finally:
            os.path.exists(path) and os.unlink(path)

    def test_per_ip_codes_differ_and_are_stable(self):
        pm, path = make_pm(pinned=False)        # per-IP
        try:
            c1 = pm.code_for("10.0.0.1")
            c2 = pm.code_for("10.0.0.2")
            self.assertNotEqual(c1, c2)          # each IP its own code
            self.assertEqual(pm.code_for("10.0.0.1"), c1)  # stable for the run
            self.assertTrue(pm.check("10.0.0.1", c1))       # its code pairs it
            self.assertFalse(pm.check("10.0.0.1", c2))      # not another's code
        finally:
            os.path.exists(path) and os.unlink(path)

    def test_per_ip_map_is_capped(self):
        pm, path = make_pm(pinned=False)
        pm.MAX_CODES = 4
        try:
            first = pm.code_for("ip0")
            for i in range(1, 6):               # push well past the cap
                pm.code_for(f"ip{i}")
            self.assertLessEqual(len(pm._codes), pm.MAX_CODES)
            self.assertNotIn("ip0", pm._codes)   # oldest was evicted
            # the evicted peer simply gets a fresh code next time
            self.assertNotEqual(pm.code_for("ip0"), first)
        finally:
            os.path.exists(path) and os.unlink(path)

    def test_revocation_and_persistence(self):
        # Trust now lives in an issued token's hash, not a peer IP - exercise
        # the same persist/reload/revoke lifecycle through issue_token/
        # check_token instead of the removed is_paired/paired-set API.
        pm, path = make_pm("ABC234")
        try:
            tok = pm.issue_token("p")
            self.assertTrue(pm.check_token(tok))
            # a fresh manager on the same store still recognizes the token...
            pm2 = PairingManager("ABC234", store_path=path)
            self.assertTrue(pm2.check_token(tok))
            # ...until revoked
            self.assertEqual(pm2.clear_paired(), 1)
            self.assertFalse(pm2.check_token(tok))
            pm3 = PairingManager("ABC234", store_path=path)
            self.assertFalse(pm3.check_token(tok))
        finally:
            os.path.exists(path) and os.unlink(path)

    def test_constant_time_compare_used(self):
        # A guess of a different length must simply fail, not raise.
        pm, path = make_pm("ABC234")
        try:
            self.assertFalse(pm.check("p", "AB"))
            self.assertFalse(pm.check("p", "ABC234XYZ"))
        finally:
            os.path.exists(path) and os.unlink(path)


# --------------------------------------------------------------------------- #
# require_pairing integration
# --------------------------------------------------------------------------- #
class TestRequirePairing(unittest.TestCase):
    # NOTE: the old test_paired_peer_passes_without_asking asserted that
    # membership in an in-process `pm.paired` IP set let a peer skip the
    # prompt. That set is gone - trust now requires presenting a token
    # (see test_pairing_flow.py's test_valid_token_first_line_pairs_without_code
    # for the replacement coverage), so the IP-bypass test was removed rather
    # than rewritten.

    def test_locked_header_on_empty_probe(self):
        pm, path = make_pm("ABC234")
        try:
            # empty probe (bare CR), then the correct code
            r, ch = run_pairing(pm, feed=b"\rABC234\r")
            self.assertTrue(r)
            out = ch.out()
            self.assertIn(b"\x0e", out)        # header frame marker
            self.assertIn(b"LOCKED", out)
            self.assertIn(bridge.CMD_TOKEN, out)  # code success issues a device token
        finally:
            os.path.exists(path) and os.unlink(path)

    def test_wrong_then_right(self):
        pm, path = make_pm("ABC234")
        try:
            r, ch = run_pairing(pm, feed=b"NOPE99\rABC234\r")
            self.assertTrue(r)
            self.assertIn(b"locked", ch.out())  # first miss: "bridge is locked"
            self.assertIn(bridge.CMD_TOKEN, ch.out())  # code success issues a token
            self.assertEqual(len(pm.devices), 1)
        finally:
            os.path.exists(path) and os.unlink(path)

    def test_lowercase_code_accepted(self):
        pm, path = make_pm("ABC234")
        try:
            r, _ = run_pairing(pm, feed=b"abc234\r")
            self.assertTrue(r)
        finally:
            os.path.exists(path) and os.unlink(path)

    def test_dial_string_and_chatter_not_a_guess(self):
        pm, path = make_pm("ABC234")
        try:
            r, _ = run_pairing(pm, feed=b"ATDS=0\rCONNECT 9600\rABC234\r")
            self.assertTrue(r)
            # the dial/chatter lines must not have burned guesses
            self.assertEqual(pm._fails.get(FakeChannel.peer, [0])[0], 0)
        finally:
            os.path.exists(path) and os.unlink(path)

    def test_exhausted_peer_locked_out(self):
        pm, path = make_pm("ABC234")
        try:
            for _ in range(pm.MAX_TRIES):
                pm.record_failure(FakeChannel.peer)
            r, ch = run_pairing(pm, feed=b"ABC234\r")  # even correct: too late
            self.assertFalse(r)
            self.assertIn(b"Too many wrong codes", ch.out())
        finally:
            os.path.exists(path) and os.unlink(path)


# --------------------------------------------------------------------------- #
# Input length bound (terminal.py)
# --------------------------------------------------------------------------- #
class TestInputBound(unittest.TestCase):
    def test_read_line_caps_buffer(self):
        ch = FakeChannel()
        cfg = TermConfig(width=80, echo=False, telnet=False, max_line=32)
        term = Terminal(ch, cfg)
        box = {}

        def go():
            box["line"] = term.read_line()

        t = threading.Thread(target=go, daemon=True)
        t.start()
        time.sleep(0.05)
        ch.feed(b"X" * 5000 + b"\r")   # unbounded flood, finally terminated
        t.join(timeout=4)
        self.assertFalse(t.is_alive())
        self.assertLessEqual(len(box["line"]), 32)

    def test_normal_line_unaffected(self):
        ch = FakeChannel()
        term = Terminal(ch, TermConfig(width=80, echo=False, telnet=False))
        box = {}

        def go():
            box["line"] = term.read_line()

        t = threading.Thread(target=go, daemon=True)
        t.start()
        time.sleep(0.05)
        ch.feed(b"hello claude\r")
        t.join(timeout=4)
        self.assertEqual(box["line"], "hello claude")


import re
from bridge import gen_token, token_hash


def test_gen_token_shape():
    t = gen_token()
    assert len(t) == 32
    assert re.fullmatch(r"[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{32}", t)
    assert gen_token() != gen_token()  # not constant


def test_token_hash_is_sha256_hex():
    h = token_hash("ABCDEF")
    assert re.fullmatch(r"[0-9a-f]{64}", h)
    assert token_hash("ABCDEF") == token_hash("ABCDEF")
    assert token_hash("ABCDEF") != token_hash("ABCDEG")


import json, os, stat
from bridge import PairingManager


def test_v2_store_roundtrip_and_perms(tmp_path):
    store = tmp_path / "paired.json"
    pm = PairingManager("ABC123", store_path=str(store))
    pm.devices.append({"token_sha256": "a" * 64,
                       "first_ip": "10.0.0.5", "paired_at": 1000})
    pm._save()
    data = json.loads(store.read_text())
    assert data["v"] == 2
    assert data["devices"][0]["token_sha256"] == "a" * 64
    assert stat.S_IMODE(os.stat(store).st_mode) == 0o600


def test_legacy_v1_ip_list_is_ignored(tmp_path):
    store = tmp_path / "paired.json"
    store.write_text(json.dumps(["10.0.1.117", "127.0.0.1"]))  # old shape
    pm = PairingManager("ABC123", store_path=str(store))
    assert pm.devices == []  # legacy IPs never trusted


def test_clear_paired_counts_and_empties(tmp_path):
    store = tmp_path / "paired.json"
    pm = PairingManager("ABC123", store_path=str(store))
    pm.devices = [{"token_sha256": "b" * 64, "first_ip": "x", "paired_at": 1}]
    pm._save()
    assert pm.clear_paired() == 1
    assert pm.devices == []
    assert json.loads(store.read_text())["devices"] == []


from bridge import token_hash


def test_issue_then_check_token(tmp_path):
    pm = PairingManager("ABC123", store_path=str(tmp_path / "p.json"))
    tok = pm.issue_token("10.0.0.9")
    assert len(tok) == 32
    assert pm.check_token(tok) is True
    assert pm.check_token("WRONGTOKENWRONGTOKENWRONGTOKEN99") is False
    # persisted as a hash, never plaintext
    assert token_hash(tok) == pm.devices[0]["token_sha256"]
    assert tok not in (tmp_path / "p.json").read_text()


def test_check_code_does_not_store_ip(tmp_path):
    pm = PairingManager("ABC123", store_path=str(tmp_path / "p.json"))
    assert pm.check("10.0.0.9", "ABC123") is True
    assert pm.devices == []  # code success alone stores nothing; issue does


if __name__ == "__main__":
    unittest.main(verbosity=2)
