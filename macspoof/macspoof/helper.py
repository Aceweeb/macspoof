"""Privileged helper executed via pkexec.

This module is intentionally small and only exposes the operations that
genuinely require root.  It is invoked by the GUI through pkexec, so the
polkit agent can ask the user for authentication while the GUI keeps running
as an unprivileged user.

It can also be called directly by an administrator:

    sudo python3 -m macspoof.helper set eth0 aa:bb:cc:dd:ee:ff
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from .backends import get_backend
from .macutils import is_multicast, is_valid, normalize

# Linux interface names are at most 15 chars and may not contain whitespace,
# slashes or other characters that could be abused to escape a path.
IFACE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")


def _die(message: str, code: int = 1) -> int:
    print(f"macspoof-helper: {message}", file=sys.stderr)
    return code


def _validate_interface(name: str) -> str | None:
    if not IFACE_RE.match(name):
        return f"invalid interface name: {name!r}"
    backend = get_backend()
    if backend.get_interface(name) is None:
        return f"no such interface: {name}"
    return None


def cmd_set(args) -> int:
    backend = get_backend()
    error = _validate_interface(args.interface)
    if error:
        return _die(error)

    mac = normalize(args.mac)
    if not is_valid(mac):
        return _die(f"invalid MAC address: {args.mac}")
    if is_multicast(mac):
        return _die("multicast addresses cannot be assigned")

    ok, msg = backend.set_mac(args.interface, mac)
    if not ok:
        return _die(msg)
    print(msg)

    if args.persist:
        ok, msg = backend.nm_set_persistent(args.interface, mac)
        if ok:
            print(msg)
        else:
            print(f"warning: {msg}", file=sys.stderr)
    return 0


def cmd_restore(args) -> int:
    backend = get_backend()
    error = _validate_interface(args.interface)
    if error:
        return _die(error)

    ok, msg = backend.restore_mac(args.interface)
    if not ok:
        return _die(msg)
    print(msg)

    if args.persist:
        ok, msg = backend.nm_clear_persistent(args.interface)
        if ok:
            print(msg)
        else:
            print(f"warning: {msg}", file=sys.stderr)
    return 0


def cmd_persist(args) -> int:
    backend = get_backend()
    error = _validate_interface(args.interface)
    if error:
        return _die(error)

    iface = backend.get_interface(args.interface)
    if not iface.mac:
        return _die(f"no MAC address on {args.interface}")

    if args.off:
        ok, msg = backend.nm_clear_persistent(args.interface)
    else:
        ok, msg = backend.nm_set_persistent(args.interface, iface.mac)
    if not ok:
        return _die(msg)
    print(msg)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="macspoof-helper",
        description="Privileged helper for macspoof (used via pkexec).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="set the MAC address of an interface")
    p_set.add_argument("interface")
    p_set.add_argument("mac")
    p_set.add_argument("--persist", action="store_true")
    p_set.set_defaults(func=cmd_set)

    p_restore = sub.add_parser("restore", help="restore the factory MAC address")
    p_restore.add_argument("interface")
    p_restore.add_argument("--persist", action="store_true")
    p_restore.set_defaults(func=cmd_restore)

    p_persist = sub.add_parser("persist", help="toggle NetworkManager persistence")
    p_persist.add_argument("interface")
    p_persist.add_argument("--off", action="store_true")
    p_persist.set_defaults(func=cmd_persist)

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        return _die("this helper must run as root (use pkexec)", 2)

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - top level guard
        return _die(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
