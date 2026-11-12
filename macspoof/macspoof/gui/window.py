"""GTK4 / libadwaita user interface for macspoof."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..backends import get_backend  # noqa: E402
from ..macutils import is_multicast, is_valid, normalize, random_mac  # noqa: E402
from . import helperpath, privileged  # noqa: E402

ICON_KIND = {
    "ethernet": "network-wired-symbolic",
    "wireless": "network-wireless-symbolic",
    "bridge": "network-server-symbolic",
    "loopback": "network-offline-symbolic",
    "virtual": "network-vpn-symbolic",
}


class InterfaceRow(Adw.ActionRow):
    """One row in the interface list."""

    def __init__(self, iface, on_select):
        super().__init__()
        self.iface = iface
        self._on_select = on_select

        icon = Gtk.Image.new_from_icon_name(ICON_KIND.get(iface.kind, "network-wired-symbolic"))
        icon.set_pixel_size(24)
        self.add_prefix(icon)

        self._badge = Gtk.Label()
        self._badge.set_valign(Gtk.Align.CENTER)
        self.add_suffix(self._badge)

        self._status = Gtk.Label()
        self._status.add_css_class("caption")
        self._status.set_valign(Gtk.Align.CENTER)
        self.add_suffix(self._status)

        self.set_activatable(True)
        self.connect("activated", lambda *_: on_select(iface))
        self.refresh()

    def refresh(self):
        """Update the labels from the stored interface state."""
        iface = self.iface
        self.set_title(iface.name)
        self.set_subtitle(iface.mac or "no address")
        self._status.set_text("up" if iface.up else "down")

        spoofed = bool(iface.permanent_mac and iface.mac and iface.mac != iface.permanent_mac)
        if spoofed:
            self._badge.set_text("spoofed")
            self._badge.remove_css_class("dim-label")
            self._badge.add_css_class("spoofed-badge")
        else:
            self._badge.set_text("")
            self._badge.remove_css_class("spoofed-badge")
            self._badge.add_css_class("dim-label")


class MacSpoofWindow(Adw.ApplicationWindow):
    """The main window: a list of interfaces plus the spoofing controls."""

    def __init__(self, application):
        super().__init__(application=application, title="MAC Spoof")
        self.set_default_size(640, 700)
        self.set_size_request(460, 520)

        self.backend = get_backend()
        self.rows: dict[str, InterfaceRow] = {}
        self.selected = None

        self._build_ui()
        self.refresh_interfaces()

    # ------------------------------------------------------------------ ui
    def _build_ui(self):
        header = Adw.HeaderBar()
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh interface list")
        refresh.connect("clicked", lambda *_: self.refresh_interfaces())
        header.pack_start(refresh)

        # --- interface list
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list_box.add_css_class("boxed-list")

        list_group = Adw.PreferencesGroup(
            title="Network interfaces",
            description="Select an interface to spoof its MAC address.",
        )
        list_group.add(self.list_box)

        # --- spoofing controls
        self.controls_group = Adw.PreferencesGroup(
            title="Spoofing",
            description="Select an interface above to enable these actions.",
        )
        self._build_controls()

        page = Adw.PreferencesPage()
        page.add(list_group)
        page.add(self.controls_group)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(page)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(header)

        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(scroller)
        outer.append(self.toasts)

        self.set_content(outer)
        self._install_actions()
        self._update_controls_state()

    def _install_actions(self):
        """Expose the random-address modes as window actions."""
        actions = Gio.SimpleAction.new("random-local", None)
        actions.connect("activate", self._on_random_local)
        self.add_action(actions)

        actions = Gio.SimpleAction.new("random-vendor", None)
        actions.connect("activate", self._on_random_vendor)
        self.add_action(actions)

    def _build_controls(self):
        self.entry = Adw.EntryRow(title="Custom MAC address")
        self.entry.set_show_apply_button(True)
        self.entry.set_tooltip_text("e.g. AA:BB:CC:DD:EE:FF")
        self.entry.connect("apply", lambda *_: self._apply_custom())
        self.entry.connect("changed", lambda *_: self._validate_entry())
        self.controls_group.add(self.entry)

        self.entry_error = Gtk.Label()
        self.entry_error.add_css_class("error-label")
        self.entry_error.set_xalign(0)
        self.entry_error.set_margin_top(4)
        self.entry_error.set_margin_bottom(4)
        self._error_row = Adw.PreferencesGroup()
        self._error_row.set_visible(False)
        self._error_row.add(self.entry_error)
        self.controls_group.add(self._error_row)

        random_row = Adw.ActionRow(
            title="Random MAC address",
            subtitle="Generate a new address for this interface",
        )
        random_button = Gtk.MenuButton(label="Randomize", valign=Gtk.Align.CENTER)
        random_button.add_css_class("suggested-action")
        random_button.set_tooltip_text("Choose how the random address is generated")
        random_menu = Gio.Menu()
        random_menu.append("Locally administered", "win.random-local")
        random_menu.append("Keep vendor prefix", "win.random-vendor")
        random_button.set_menu_model(random_menu)
        random_row.add_suffix(random_button)
        random_row.set_activatable_widget(random_button)
        self.controls_group.add(random_row)
        self._random_button = random_button

        restore_row = Adw.ActionRow(
            title="Restore factory MAC address",
            subtitle="Go back to the address burned into the hardware",
        )
        restore_button = Gtk.Button(label="Restore", valign=Gtk.Align.CENTER)
        restore_button.connect("clicked", lambda *_: self._apply_restore())
        restore_row.add_suffix(restore_button)
        restore_row.set_activatable_widget(restore_button)
        self.controls_group.add(restore_row)
        self._restore_button = restore_button

        self.persist_row = Adw.SwitchRow(
            title="Persist across reconnects",
            subtitle="Apply this MAC again when the connection is re-established",
        )
        self.persist_row.set_active(True)
        self.controls_group.add(self.persist_row)

    # ------------------------------------------------------------- refresh
    def refresh_interfaces(self):
        """Reload the interface list from the system."""
        try:
            interfaces = [i for i in self.backend.list_interfaces() if i.kind != "loopback"]
        except Exception as exc:  # noqa: BLE001
            self._toast(f"Could not read interfaces: {exc}")
            return

        present = {i.name for i in interfaces}

        for name, row in list(self.rows.items()):
            if name not in present:
                self.list_box.remove(row)
                del self.rows[name]

        for iface in interfaces:
            row = self.rows.get(iface.name)
            if row is not None:
                row.iface = iface
                row.refresh()
            else:
                row = InterfaceRow(iface, self._select_interface)
                self.rows[iface.name] = row
                self.list_box.append(row)

        # Keep the selection pointing at the live interface object.
        if self.selected is not None:
            match = next((i for i in interfaces if i.name == self.selected.name), None)
            if match is not None:
                self.selected = match
            else:
                self.selected = None

        self._update_controls_state()

    def _select_interface(self, iface):
        self.selected = iface
        self.entry.set_text("")
        self._validate_entry()
        self._update_controls_state()

    def _update_controls_state(self):
        """Enable or disable the controls depending on the selection."""
        has_selection = self.selected is not None
        self.controls_group.set_sensitive(has_selection)
        self.controls_group.set_title("Spoofing")
        if has_selection:
            self.controls_group.set_description(f"Interface: {self.selected.name}")
        else:
            self.controls_group.set_description("Select an interface above to enable these actions.")

    # -------------------------------------------------------------- helpers
    def _validate_entry(self):
        text = self.entry.get_text().strip()
        message = ""
        if text:
            if not is_valid(text):
                message = "That is not a valid MAC address."
            elif is_multicast(normalize(text)):
                message = "Multicast addresses cannot be assigned."
        self.entry_error.set_text(message)
        self._error_row.set_visible(bool(message))
        self.entry.set_tooltip_text(message or "e.g. AA:BB:CC:DD:EE:FF")

    def _toast(self, message, timeout=4):
        toast = Adw.Toast.new(message)
        toast.set_timeout(timeout)
        self.toasts.add_toast(toast)

    def _persist_flag(self):
        return self.persist_row.get_active()

    # -------------------------------------------------------------- actions
    def _apply_custom(self):
        if not self.selected:
            return
        mac = self.entry.get_text().strip()
        if not is_valid(mac):
            self._validate_entry()
            self._toast("Enter a valid MAC address first.")
            return
        if is_multicast(normalize(mac)):
            self._toast("Multicast addresses cannot be assigned.")
            return
        self._run_privileged(
            ["set", self.selected.name, normalize(mac)],
            f"{self.selected.name} now uses {normalize(mac)}",
        )

    def _apply_random(self, keep_vendor: bool = False):
        """Generate and apply a random MAC address.

        With `keep_vendor` the original vendor prefix is preserved, which
        impersonates that manufacturer.  Otherwise a locally administered
        address is used, which cannot collide with any real vendor OUI.
        """
        if not self.selected:
            return
        vendor = self.selected.permanent_mac if keep_vendor else None
        mac = random_mac(vendor)
        self.entry.set_text(mac)
        self._validate_entry()
        self._run_privileged(
            ["set", self.selected.name, mac],
            f"{self.selected.name} now uses {mac}",
        )

    def _on_random_local(self, *_args):
        self._apply_random(keep_vendor=False)

    def _on_random_vendor(self, *_args):
        self._apply_random(keep_vendor=True)

    def _apply_restore(self):
        if not self.selected:
            return
        self._run_privileged(
            ["restore", self.selected.name],
            f"{self.selected.name} restored to its factory MAC address",
        )

    # ------------------------------------------------------------ privileged
    def _run_privileged(self, args, success_message):
        """Run a privileged action in a thread and report the outcome."""
        self._set_busy(True)
        persist = self._persist_flag()

        def worker():
            try:
                if persist and args[0] in ("set", "restore"):
                    privileged.run_helper(*args, "--persist")
                else:
                    privileged.run_helper(*args)
                GLib.idle_add(self._on_success, success_message)
            except privileged.PrivilegedError as exc:
                GLib.idle_add(self._on_error, str(exc))
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._on_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_success(self, message):
        self._set_busy(False)
        self._toast(message)
        self.refresh_interfaces()
        return False

    def _on_error(self, message):
        self._set_busy(False)
        self._toast(f"Error: {message}", timeout=6)
        return False

    def _set_busy(self, busy: bool):
        for widget in (self._random_button, self._restore_button):
            widget.set_sensitive(not busy)
        self.entry.set_sensitive(not busy)
        if busy:
            self.toasts.add_toast(Adw.Toast.new("Waiting for authentication…"))

    def do_close_request(self):  # noqa: N802 - GTK callback name
        helperpath.cleanup_fallback()
        return False
