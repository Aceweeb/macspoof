"""Unit tests for macspoof.

Run with:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from macspoof import macutils
from macspoof.backends.linux import LinuxBackend


class TestMacUtils(unittest.TestCase):
    def test_valid_addresses(self):
        for mac in ("AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff", "aa-bb-cc-dd-ee-ff"):
            self.assertTrue(macutils.is_valid(mac), mac)

    def test_invalid_addresses(self):
        for mac in ("", "ZZ:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE", "AA:BB:CC:DD:EE:FF:11", "not-a-mac"):
            self.assertFalse(macutils.is_valid(mac), mac)

    def test_broadcast_and_zero_rejected(self):
        self.assertFalse(macutils.is_valid("FF:FF:FF:FF:FF:FF"))
        self.assertFalse(macutils.is_valid("00:00:00:00:00:00"))

    def test_normalize(self):
        self.assertEqual(macutils.normalize("AA-BB-CC-DD-EE-FF"), "aa:bb:cc:dd:ee:ff")
        self.assertEqual(macutils.normalize("AA.BB.CC.DD.EE.FF"), "aa:bb:cc:dd:ee:ff")

    def test_random_is_locally_administered_unicast(self):
        for _ in range(200):
            mac = macutils.random_mac()
            self.assertTrue(macutils.is_valid(mac))
            self.assertTrue(macutils.is_locally_administered(mac))
            self.assertFalse(macutils.is_multicast(mac))
            first = int(mac.split(":")[0], 16)
            self.assertEqual(first & 0x02, 0x02)
            self.assertEqual(first & 0x01, 0x00)

    def test_random_keep_vendor(self):
        mac = macutils.random_mac("34:5a:60:ed:34:5c")
        self.assertTrue(mac.startswith("34:5a:60:"))
        self.assertTrue(macutils.is_valid(mac))

    def test_random_keep_vendor_preserves_prefix_bits(self):
        """The vendor prefix must not be mangled by the local-admin bit."""
        for _ in range(50):
            mac = macutils.random_mac("00:0c:29:aa:bb:cc")
            self.assertTrue(mac.startswith("00:0c:29:"), mac)

    def test_random_without_vendor_differs(self):
        macs = {macutils.random_mac() for _ in range(50)}
        self.assertGreater(len(macs), 40)


class TestLinuxBackend(unittest.TestCase):
    def setUp(self):
        self.backend = LinuxBackend()

    def test_permanent_mac_is_valid_or_none(self):
        for iface in self.backend.list_interfaces():
            if iface.permanent_mac:
                self.assertTrue(macutils.is_valid(iface.permanent_mac), iface.name)

    def test_current_mac_is_valid_or_none(self):
        for iface in self.backend.list_interfaces():
            if iface.mac:
                self.assertTrue(macutils.is_valid(iface.mac), iface.name)

    def test_systemd_unit_is_valid(self):
        unit = self.backend.render_systemd_unit("eth0")
        self.assertIn("[Unit]", unit)
        self.assertIn("[Service]", unit)
        self.assertIn("[Install]", unit)
        self.assertIn("ExecStart=", unit)
        self.assertIn("ExecStop=", unit)
        self.assertIn("WantedBy=multi-user.target", unit)

    def test_systemd_unit_with_fixed_mac(self):
        unit = self.backend.render_systemd_unit("eth0", "AA:BB:CC:DD:EE:FF")
        self.assertIn("AA:BB:CC:DD:EE:FF", unit)


class TestCLI(unittest.TestCase):
    """Smoke tests for the command line interface."""

    def run_cli(self, *args):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return subprocess.run(
            [sys.executable, "-m", "macspoof", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    def test_list(self):
        result = self.run_cli("list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("INTERFACE", result.stdout)

    def test_version(self):
        result = self.run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("macspoof", result.stdout)

    def test_invalid_mac_rejected(self):
        result = self.run_cli("set", "ZZ:BB:CC:DD:EE:FF", "-i", "lo")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a valid MAC", result.stderr)

    def test_multicast_rejected(self):
        result = self.run_cli("set", "01:00:5E:00:00:01", "-i", "lo")
        self.assertEqual(result.returncode, 1)
        self.assertIn("multicast", result.stderr)

    def test_unknown_interface(self):
        result = self.run_cli("set", "AA:BB:CC:DD:EE:FF", "-i", "definitely-not-here")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
