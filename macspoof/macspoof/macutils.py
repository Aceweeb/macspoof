"""MAC address helpers: parsing, validation and generation."""

from __future__ import annotations

import re
import secrets

MAC_RE = re.compile(r"^[0-9a-fA-F]{2}([:-])(?:[0-9a-fA-F]{2}\1){4}[0-9a-fA-F]{2}$")

# Broadcast / all-zero addresses are never valid targets.
_INVALID = {"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"}


def is_valid(mac: str) -> bool:
    """True if `mac` is a well formed unicast MAC address."""
    if not mac or not MAC_RE.match(mac.strip()):
        return False
    return normalize(mac) not in _INVALID


def normalize(mac: str) -> str:
    """Return the lowercase colon-separated form of `mac`."""
    return mac.strip().lower().replace("-", ":").replace(".", ":")


def random_mac(keep_vendor: str | None = None) -> str:
    """Generate a random MAC address.

    Without `keep_vendor` the address is locally administered: the locally
    administered bit (0x02) is forced on and the multicast bit (0x01) forced
    off, so it is guaranteed unique to this host and can never collide with a
    real vendor OUI.

    With `keep_vendor` the original three-byte vendor prefix is preserved
    verbatim so the address impersonates that vendor. The prefix bits are
    left untouched because the vendor prefix is authoritative.
    """
    if keep_vendor:
        prefix = normalize(keep_vendor).split(":")[:3]
        if len(prefix) != 3:
            raise ValueError(f"invalid vendor prefix: {keep_vendor}")
        octets = [int(p, 16) for p in prefix] + [secrets.randbelow(256) for _ in range(3)]
    else:
        octets = [secrets.randbelow(256) for _ in range(6)]
        octets[0] = (octets[0] & 0xFE) | 0x02

    return ":".join(f"{o:02x}" for o in octets)


def is_locally_administered(mac: str) -> bool:
    """True if the 0x02 bit of the first octet is set."""
    return bool(int(normalize(mac).split(":")[0], 16) & 0x02)


def is_multicast(mac: str) -> bool:
    """True if the 0x01 bit of the first octet is set."""
    return bool(int(normalize(mac).split(":")[0], 16) & 0x01)
