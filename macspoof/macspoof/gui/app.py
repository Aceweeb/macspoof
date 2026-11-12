"""The macspoof GTK4 application."""

from __future__ import annotations

import sys

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
except (ImportError, ValueError) as exc:  # pragma: no cover - environment specific
    print(
        f"error: the macspoof GUI needs PyGObject with GTK4 and libadwaita ({exc}).\n"
        "Install them with your package manager, for example:\n"
        "  Arch:    sudo pacman -S python-gobject gtk4 libadwaita\n"
        "  Debian:  sudo apt install python3-gi gir1.2-gtk-4.0 libadwaita-1-0\n"
        "  Fedora:  sudo dnf install python3-gobject gtk4 libadwaita\n"
        "\nThe command line interface works without them: macspoof --help",
        file=sys.stderr,
    )
    raise SystemExit(1)

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from .. import __version__  # noqa: E402
from .window import MacSpoofWindow  # noqa: E402

APP_ID = "com.github.macspoof.MacSpoof"

CSS = """
.spoofed-badge {
    background-image: none;
    background-color: alpha(@accent_bg_color, 0.18);
    color: @accent_color;
    border-radius: 6px;
    padding: 1px 7px;
    font-weight: bold;
}

.error-label {
    color: @error_color;
    font-size: 0.9em;
}
"""


class MacSpoofApp(Adw.Application):
    """GTK application hosting the main window."""

    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._window = None

    def do_startup(self):  # noqa: N802 - GTK callback name
        # PyGObject does not chain up vfunc overrides automatically.
        Adw.Application.do_startup(self)
        self._apply_css()

    def do_activate(self):  # noqa: N802 - GTK callback name
        if self._window is None:
            self._window = MacSpoofWindow(self)
        self._window.present()

    def do_command_line(self, command_line):  # noqa: N802 - GTK callback name
        if "--version" in command_line.get_arguments():
            print(f"macspoof {__version__}")
            return 0
        self.activate()
        return 0

    def _apply_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            return
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `macspoof-gui` console script."""
    Adw.init()
    return MacSpoofApp().run(argv if argv is not None else sys.argv)
