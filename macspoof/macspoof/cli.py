"""Command line interface for macspoof."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .backends import get_backend
from .macutils import is_locally_administered, is_multicast, is_valid, normalize, random_mac


def _needs_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() != 0


def _require_root(action: str) -> bool:
    if not _needs_root():
        return True
    print(f"error: {action} requires root privileges (try: sudo)", file=sys.stderr)
    return False


def _select_interface(backend, requested: str | None, require_link: bool = True):
    """Resolve an interface, prompting when several candidates exist."""
    all_interfaces = backend.list_interfaces()
    interfaces = [i for i in all_interfaces if i.kind not in ("loopback",)]
    if requested:
        # An explicitly requested interface is honoured even if it is normally
        # filtered out (loopback, bridge, ...).
        match = next((i for i in all_interfaces if i.name == requested), None)
        if match is None:
            print(f"error: interface '{requested}' not found", file=sys.stderr)
            return None
        return match

    if not interfaces:
        print("error: no usable network interfaces found", file=sys.stderr)
        return None

    # Bridges, veths and other virtual links are driven by their parent and
    # usually refuse MAC changes, so only offer real hardware by default.
    physical = [i for i in interfaces if not i.is_virtual]
    if len(physical) == 1:
        return physical[0]
    if len(interfaces) == 1:
        return interfaces[0]

    print("error: multiple interfaces available, specify one with --interface:", file=sys.stderr)
    for iface in interfaces:
        print(f"  {iface.name:<12} {iface.mac or '-':<18} {iface.kind}", file=sys.stderr)
    return None


def cmd_list(args) -> int:
    backend = get_backend()
    interfaces = backend.list_interfaces()
    if not interfaces:
        print("no network interfaces found")
        return 1

    header = f"{'INTERFACE':<12} {'CURRENT MAC':<18} {'PERMANENT MAC':<18} {'STATE':<6} {'KIND':<10} NOTES"
    print(header)
    print("-" * len(header))
    for iface in interfaces:
        state = "UP" if iface.up else "DOWN"
        notes = []
        if iface.driver:
            notes.append(f"driver={iface.driver}")
        if iface.nm_connection:
            notes.append(f"nm={iface.nm_connection}")
        if iface.mac and is_locally_administered(iface.mac):
            notes.append("locally-administered")
        if iface.mac and is_multicast(iface.mac):
            notes.append("MULTICAST")
        print(
            f"{iface.name:<12} {iface.mac or '-':<18} {iface.permanent_mac or '-':<18} "
            f"{state:<6} {iface.kind:<10} {' '.join(notes)}"
        )
    return 0


def cmd_current(args) -> int:
    backend = get_backend()
    iface = _select_interface(backend, args.interface)
    if iface is None:
        return 1
    print(iface.mac or "-")
    return 0


def _apply(backend, iface, mac: str, args) -> int:
    ok, msg = backend.set_mac(iface.name, mac)
    if not ok:
        print(f"error: {msg}", file=sys.stderr)
        return 1
    print(msg)

    if getattr(args, "persist", False):
        ok, msg = backend.nm_set_persistent(iface.name, mac)
        if ok:
            print(msg)
        else:
            print(f"warning: persistence not applied: {msg}", file=sys.stderr)
    return 0


def cmd_set(args) -> int:
    backend = get_backend()
    iface = _select_interface(backend, args.interface)
    if iface is None:
        return 1

    mac = normalize(args.mac)
    if mac.lower() == "random":
        vendor = iface.permanent_mac if args.keep_vendor else None
        mac = random_mac(vendor)
    elif not is_valid(mac):
        print(f"error: '{args.mac}' is not a valid MAC address", file=sys.stderr)
        return 1
    if is_multicast(mac):
        print("error: multicast addresses cannot be assigned", file=sys.stderr)
        return 1

    if not _require_root(f"changing the MAC of {iface.name}"):
        return 1
    return _apply(backend, iface, mac, args)


def cmd_random(args) -> int:
    backend = get_backend()
    iface = _select_interface(backend, args.interface)
    if iface is None:
        return 1

    vendor = None
    if args.keep_vendor and iface.permanent_mac:
        vendor = iface.permanent_mac
    mac = random_mac(vendor)

    if not _require_root(f"changing the MAC of {iface.name}"):
        return 1
    return _apply(backend, iface, mac, args)


def cmd_restore(args) -> int:
    backend = get_backend()
    iface = _select_interface(backend, args.interface)
    if iface is None:
        return 1

    if not _require_root(f"restoring the MAC of {iface.name}"):
        return 1

    ok, msg = backend.restore_mac(iface.name)
    if not ok:
        print(f"error: {msg}", file=sys.stderr)
        return 1
    print(msg)

    if getattr(args, "persist", False):
        ok, msg = backend.nm_clear_persistent(iface.name)
        if ok:
            print(msg)
        else:
            print(f"warning: persistence not cleared: {msg}", file=sys.stderr)
    return 0


def cmd_install(args) -> int:
    backend = get_backend()
    iface = _select_interface(backend, args.interface)
    if iface is None:
        return 1

    mac = None
    if args.mac:
        mac = normalize(args.mac)
        if not is_valid(mac):
            print(f"error: '{args.mac}' is not a valid MAC address", file=sys.stderr)
            return 1

    if not _require_root("installing a systemd unit"):
        return 1

    ok, msg = backend.install_systemd_unit(iface.name, mac)
    print(msg if ok else f"error: {msg}", file=sys.stderr if not ok else sys.stdout)
    return 0 if ok else 1


def cmd_uninstall(args) -> int:
    backend = get_backend()
    if not _require_root("removing the systemd unit"):
        return 1
    ok, msg = backend.uninstall_systemd_unit()
    print(msg if ok else f"error: {msg}", file=sys.stderr if not ok else sys.stdout)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="macspoof",
        description="Spoof (change) the MAC address of a network interface.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  macspoof list                          show every interface and its MACs
  macspoof random --interface enp34s0    assign a random locally administered MAC
  macspoof set AA:BB:CC:DD:EE:FF -i en0 set a specific MAC
  macspoof restore --interface enp34s0   go back to the factory MAC
  macspoof random -i enp34s0 --persist  also make it survive reconnects
""",
    )
    parser.add_argument("--version", action="version", version=f"macspoof {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list interfaces and MAC addresses")
    p_list.set_defaults(func=cmd_list)

    p_cur = sub.add_parser("current", help="print the current MAC of an interface")
    p_cur.add_argument("-i", "--interface")
    p_cur.set_defaults(func=cmd_current)

    p_set = sub.add_parser("set", help="set a specific MAC address")
    p_set.add_argument("mac", help="MAC address, e.g. AA:BB:CC:DD:EE:FF (or 'random')")
    p_set.add_argument("-i", "--interface")
    p_set.add_argument("--keep-vendor", action="store_true", help="with 'random', keep the vendor OUI")
    p_set.add_argument("--persist", action="store_true", help="survive reconnects (NetworkManager)")
    p_set.set_defaults(func=cmd_set)

    p_rand = sub.add_parser("random", help="assign a random MAC address")
    p_rand.add_argument("-i", "--interface")
    p_rand.add_argument("--keep-vendor", action="store_true", help="keep the original vendor OUI")
    p_rand.add_argument("--persist", action="store_true", help="survive reconnects (NetworkManager)")
    p_rand.set_defaults(func=cmd_random)

    p_restore = sub.add_parser("restore", help="restore the factory MAC address")
    p_restore.add_argument("-i", "--interface")
    p_restore.add_argument("--persist", action="store_true", help="also clear the persisted MAC")
    p_restore.set_defaults(func=cmd_restore)

    p_install = sub.add_parser("install", help="install a systemd unit that applies a MAC at boot")
    p_install.add_argument("-i", "--interface")
    p_install.add_argument("--mac", help="MAC to apply at boot (default: random each boot)")
    p_install.set_defaults(func=cmd_install)

    p_uninstall = sub.add_parser("uninstall", help="remove the systemd unit")
    p_uninstall.set_defaults(func=cmd_uninstall)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - top level guard
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
