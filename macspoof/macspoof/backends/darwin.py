"""macOS backend built on ifconfig and networksetup."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field

from ..macutils import is_valid, normalize

_IFCONFIG_RE = re.compile(r"^(\S+):", re.MULTILINE)
_ETHER_RE = re.compile(r"ether\s+([0-9a-fA-F:]{17})")


def _run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: command not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]}: timed out"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


@dataclass
class Interface:
    name: str
    mac: str | None = None
    permanent_mac: str | None = None
    up: bool = False
    kind: str = "ethernet"
    driver: str | None = None
    nm_connection: str | None = None
    nm_uuid: str | None = None
    nm_managed: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def is_virtual(self) -> bool:
        return self.kind in {"bridge", "vlan", "veth", "tun", "tap", "dummy", "macvlan"}


class DarwinBackend:
    name = "darwin"

    def list_interfaces(self) -> list[Interface]:
        if not shutil.which("ifconfig"):
            return []
        code, out, _ = _run(["ifconfig", "-a"])
        if code != 0:
            return []

        blocks = re.split(r"\n(?=\S)", out)
        interfaces: list[Interface] = []
        for block in blocks:
            header = block.splitlines()[0] if block.strip() else ""
            name = header.split(":")[0].strip()
            if not name:
                continue
            ether = _ETHER_RE.search(block)
            mac = normalize(ether.group(1)) if ether and is_valid(ether.group(1)) else None
            up = "status: active" in block or "UP" in header
            kind = "wireless" if "802.11" in block or name.startswith("en") and "wl" in name else "ethernet"
            interfaces.append(
                Interface(
                    name=name,
                    mac=mac,
                    permanent_mac=self._permanent_mac(name),
                    up=up,
                    kind=kind,
                )
            )
        return interfaces

    def _permanent_mac(self, name: str) -> str | None:
        """Hardware MAC as reported by networksetup."""
        if not shutil.which("networksetup"):
            return None
        code, out, _ = _run(["networksetup", "-listallhardwareports"])
        if code != 0:
            return None
        lines = out.splitlines()
        for index, line in enumerate(lines):
            if line.startswith(f"Device: {name}"):
                if index + 1 < len(lines) and "Hardware Address" in lines[index + 1]:
                    mac = lines[index + 1].split(":", 1)[1].strip()
                    if is_valid(mac):
                        return normalize(mac)
        return None

    def get_interface(self, name: str) -> Interface | None:
        for iface in self.list_interfaces():
            if iface.name == name:
                return iface
        return None

    def set_mac(self, name: str, mac: str) -> tuple[bool, str]:
        mac = normalize(mac)
        if not is_valid(mac):
            return False, f"invalid MAC address: {mac}"
        code, _, err = _run(["ifconfig", name, "ether", mac])
        if code != 0:
            return False, f"ifconfig failed: {err}"
        return True, f"{name} -> {mac}"

    def restore_mac(self, name: str) -> tuple[bool, str]:
        iface = self.get_interface(name)
        if iface is None:
            return False, f"interface not found: {name}"
        if not iface.permanent_mac:
            return False, f"no permanent MAC known for {name}"
        return self.set_mac(name, iface.permanent_mac)

    def nm_set_persistent(self, name: str, mac: str) -> tuple[bool, str]:
        return False, "NetworkManager persistence is Linux-only"

    def nm_clear_persistent(self, name: str) -> tuple[bool, str]:
        return False, "NetworkManager persistence is Linux-only"

    def install_systemd_unit(self, iface_name: str, mac: str | None = None) -> tuple[bool, str]:
        return False, "systemd units are Linux-only"

    def uninstall_systemd_unit(self) -> tuple[bool, str]:
        return False, "systemd units are Linux-only"
