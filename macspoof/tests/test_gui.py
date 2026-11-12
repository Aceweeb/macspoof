"""GUI tests for macspoof.

These exercise the GTK widgets directly (no compositor needed) by activating
rows and emitting signals programmatically.

Run with:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from macspoof.gui import app as gui_app  # noqa: E402
from macspoof.gui import privileged  # noqa: E402
from macspoof.gui.window import InterfaceRow, MacSpoofWindow  # noqa: E402


def _make_window():
    """Create a window on the current display.

    The application is registered and started first, otherwise GTK complains
    that a window was created before the startup signal was emitted.
    """
    from gi.repository import Gdk

    if Gdk.Display.get_default() is None:
        raise unittest.SkipTest("no display available")

    application = gui_app.MacSpoofApp()
    application.register(None)
    application.emit("startup")
    return MacSpoofWindow(application)


class TestInterfaceRow(unittest.TestCase):
    def test_row_shows_spoofed_badge(self):
        class FakeIface:
            name = "eth0"
            mac = "aa:bb:cc:dd:ee:ff"
            permanent_mac = "11:22:33:44:55:66"
            up = True
            kind = "ethernet"
            driver = None

        selected = []
        row = InterfaceRow(FakeIface(), lambda i: selected.append(i))
        self.assertEqual(row.get_title(), "eth0")
        self.assertEqual(row.get_subtitle(), "aa:bb:cc:dd:ee:ff")
        self.assertEqual(row._badge.get_text(), "spoofed")
        row.emit("activated")
        self.assertEqual(len(selected), 1)

    def test_row_shows_no_badge_when_not_spoofed(self):
        class FakeIface:
            name = "eth0"
            mac = "11:22:33:44:55:66"
            permanent_mac = "11:22:33:44:55:66"
            up = False
            kind = "ethernet"
            driver = None

        row = InterfaceRow(FakeIface(), lambda i: None)
        self.assertEqual(row.get_subtitle(), "11:22:33:44:55:66")
        self.assertEqual(row._badge.get_text(), "")

    def test_row_refresh_updates_spoofed_state(self):
        class FakeIface:
            name = "eth0"
            mac = "11:22:33:44:55:66"
            permanent_mac = "11:22:33:44:55:66"
            up = True
            kind = "ethernet"
            driver = None

        row = InterfaceRow(FakeIface(), lambda i: None)
        self.assertEqual(row._badge.get_text(), "")

        row.iface.mac = "aa:bb:cc:dd:ee:ff"
        row.refresh()
        self.assertEqual(row._badge.get_text(), "spoofed")


class TestWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.window = _make_window()

    def test_controls_disabled_without_selection(self):
        self.window.selected = None
        self.window._update_controls_state()
        self.assertFalse(self.window.controls_group.get_sensitive())

    def test_selecting_interface_enables_controls(self):
        rows = list(self.window.rows.values())
        if not rows:
            self.skipTest("no interfaces available in this environment")

        self.window._select_interface(rows[0].iface)
        self.assertTrue(self.window.controls_group.get_sensitive())
        self.assertIsNotNone(self.window.selected)

    def test_invalid_entry_shows_error(self):
        rows = list(self.window.rows.values())
        if not rows:
            self.skipTest("no interfaces available in this environment")
        self.window._select_interface(rows[0].iface)

        self.window.entry.set_text("ZZ:BB:CC:DD:EE:FF")
        self.assertTrue(self.window._error_row.get_visible())
        self.assertIn("not a valid MAC", self.window.entry_error.get_text())

        self.window.entry.set_text("01:00:5E:00:00:01")
        self.assertTrue(self.window._error_row.get_visible())
        self.assertIn("Multicast", self.window.entry_error.get_text())

        self.window.entry.set_text("AA:BB:CC:DD:EE:FF")
        self.assertFalse(self.window._error_row.get_visible())

    def test_random_local_generates_locally_administered_mac(self):
        rows = list(self.window.rows.values())
        if not rows:
            self.skipTest("no interfaces available in this environment")
        self.window._select_interface(rows[0].iface)
        self.window._apply_random(keep_vendor=False)
        text = self.window.entry.get_text()
        self.assertRegex(text, r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
        first = int(text.split(":")[0], 16)
        self.assertEqual(first & 0x02, 0x02, "locally administered bit must be set")
        self.assertEqual(first & 0x01, 0x00, "multicast bit must be clear")

    def test_random_vendor_preserves_prefix(self):
        rows = list(self.window.rows.values())
        if not rows:
            self.skipTest("no interfaces available in this environment")
        iface = rows[0].iface
        self.window._select_interface(iface)
        self.window._apply_random(keep_vendor=True)
        text = self.window.entry.get_text()
        self.assertRegex(text, r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
        if iface.permanent_mac:
            self.assertTrue(
                text.startswith(iface.permanent_mac[:8]),
                f"{text} should keep the {iface.permanent_mac} vendor prefix",
            )

    def test_apply_custom_rejects_invalid_without_privileges(self):
        """An invalid MAC must never reach the privileged helper."""
        calls = []
        original = privileged.run_helper
        privileged.run_helper = lambda *a, **k: calls.append(a)

        rows = list(self.window.rows.values())
        if not rows:
            self.skipTest("no interfaces available in this environment")
        self.window._select_interface(rows[0].iface)
        try:
            self.window.entry.set_text("not-a-mac")
            self.window._apply_custom()
            self.assertEqual(calls, [])
        finally:
            privileged.run_helper = original

    def test_apply_custom_passes_normalised_mac(self):
        calls = []
        original = privileged.run_helper
        privileged.run_helper = lambda *a, **k: calls.append(a)

        rows = list(self.window.rows.values())
        if not rows:
            self.skipTest("no interfaces available in this environment")
        iface = rows[0].iface
        self.window._select_interface(iface)
        self.window.entry.set_text("aa-bb-cc-dd-ee-ff")
        try:
            self.window._apply_custom()
            # The call happens on a worker thread, so give it a moment.
            import time

            for _ in range(50):
                if calls:
                    break
                time.sleep(0.05)
            self.assertTrue(calls, "helper was never invoked")
            self.assertEqual(calls[0][:3], ("set", iface.name, "aa:bb:cc:dd:ee:ff"))
        finally:
            privileged.run_helper = original


class TestPrivilegedErrors(unittest.TestCase):
    def test_interpret_exit_codes(self):
        interpret = privileged._interpret
        self.assertIsNone(interpret(0, ""))
        self.assertIn("cancelled", interpret(126, "Error executing command as another user: Not authorized"))
        self.assertIn("Authentication is required", interpret(1, "Authentication is required"))
        self.assertIn("boom", interpret(3, "boom"))


if __name__ == "__main__":
    unittest.main()
