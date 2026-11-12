"""Install the root-owned privileged helper and its polkit policy.

Run this once with sudo:

    sudo macspoof-install-helper

It installs:

* ``/usr/local/libexec/macspoof-helper`` - a root-owned wrapper script
* ``/usr/share/polkit-1/actions/org.macspoof.policy`` - the polkit action

With those in place the GUI can authenticate through the desktop's polkit
agent and the authorisation can be remembered for the session, instead of
prompting for every single change.
"""

from __future__ import annotations

import sys

from .gui import helperpath


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0

    ok, message = helperpath.install_system_helper()
    if ok:
        print(message)
        print()
        print("Restart the macspoof GUI to pick up the new helper.")
        return 0

    print(f"error: {message}", file=sys.stderr)
    if "must run as root" in message:
        print("hint: try: sudo macspoof-install-helper", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
