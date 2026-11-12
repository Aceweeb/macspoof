"""GTK4 / libadwaita GUI for macspoof.

The GTK imports are deferred so that importing this package (for example by
the CLI or the helper installer) does not require PyGObject to be present.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `macspoof-gui` console script."""
    from .app import main as _main

    return _main(argv)
