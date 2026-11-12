"""Backend selection: Linux (iproute2/NetworkManager) and macOS (ifconfig)."""

from __future__ import annotations

import platform
import sys

from . import darwin, linux


def get_backend():
    """Return the backend matching the running operating system."""
    system = platform.system()
    if system == "Linux":
        return linux.LinuxBackend()
    if system == "Darwin":
        return darwin.DarwinBackend()
    raise RuntimeError(f"unsupported platform: {system}")


def _selftest() -> int:
    """Import check used by `python -m macspoof.backends`."""
    print("backends ok:", sys.platform)
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
