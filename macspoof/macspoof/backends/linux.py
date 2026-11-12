"""Linux backend built on iproute2, ethtool and NetworkManager."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field

from ..macutils import is_valid, normalize

SYSFS_NET = "/sys/class/net"


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


def _run(cmd: list[str]) -> tuple[int, str, str]:
    """Run a command, returning (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: command not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]}: timed out"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


class LinuxBackend:
    name = "linux"

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _sysfs_read(path: str) -> str | None:
        try:
            with open(path) as fh:
                return fh.read().strip()
        except OSError:
            return None

    @staticmethod
    def _interface_kind(name: str) -> str:
        if os.path.isdir(f"{SYSFS_NET}/{name}/wireless"):
            return "wireless"
        if os.path.isdir(f"{SYSFS_NET}/{name}/bridge"):
            return "bridge"
        link = LinuxBackend._sysfs_read(f"{SYSFS_NET}/{name}/type")
        if link == "772":  # ARPHRD_LOOPBACK
            return "loopback"
        if not os.path.exists(f"{SYSFS_NET}/{name}/device"):
            return "virtual"
        return "ethernet"

    @staticmethod
    def _permanent_mac(name: str) -> str | None:
        """Original factory MAC, recovered via ethtool when available."""
        if shutil.which("ethtool"):
            code, out, _ = _run(["ethtool", "-P", name])
            if code == 0 and "Permanent address" in out:
                for line in out.splitlines():
                    if "Permanent address" in line:
                        mac = line.split(":", 1)[1].strip()
                        if is_valid(mac):
                            return normalize(mac)
        # Some drivers expose the original address in sysfs.
        mac = LinuxBackend._sysfs_read(f"{SYSFS_NET}/{name}/perm_address")
        return normalize(mac) if mac and is_valid(mac) else None

    # ----------------------------------------------------------------- query
    def _ip_json_links(self) -> list[dict]:
        """Interfaces as reported by iproute2 (namespace aware)."""
        code, out, _ = _run(["ip", "-j", "link", "show"])
        if code != 0 or not out:
            return []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def list_interfaces(self) -> list[Interface]:
        interfaces: list[Interface] = []
        nm_map = self._nm_connections()

        links = self._ip_json_links()
        if links:
            for link in links:
                name = link.get("ifname")
                if not name:
                    continue
                mac = link.get("address")
                flags = link.get("flags") or []
                interfaces.append(
                    Interface(
                        name=name,
                        mac=normalize(mac) if mac and is_valid(mac) else None,
                        permanent_mac=self._permanent_mac(name),
                        up="UP" in flags,
                        kind=self._kind_from_link(name, link),
                        driver=self._driver(name),
                        nm_connection=nm_map.get(name, {}).get("name"),
                        nm_uuid=nm_map.get(name, {}).get("uuid"),
                        nm_managed=name in nm_map,
                    )
                )
            return interfaces

        # Fallback: sysfs only (older iproute2 without JSON support).
        if not os.path.isdir(SYSFS_NET):
            return []
        for name in sorted(os.listdir(SYSFS_NET)):
            mac = self._sysfs_read(f"{SYSFS_NET}/{name}/address")
            flags = self._sysfs_read(f"{SYSFS_NET}/{name}/flags") or "0"
            try:
                up = bool(int(flags, 0) & 0x1)
            except ValueError:
                up = False
            conn = nm_map.get(name)
            interfaces.append(
                Interface(
                    name=name,
                    mac=normalize(mac) if mac and is_valid(mac) else None,
                    permanent_mac=self._permanent_mac(name),
                    up=up,
                    kind=self._interface_kind(name),
                    driver=self._driver(name),
                    nm_connection=conn.get("name") if conn else None,
                    nm_uuid=conn.get("uuid") if conn else None,
                    nm_managed=conn is not None,
                )
            )
        return interfaces

    @staticmethod
    def _driver(name: str) -> str | None:
        driver_link = f"{SYSFS_NET}/{name}/device/driver"
        if not os.path.exists(driver_link):
            return None
        return os.path.basename(os.path.realpath(driver_link))

    @staticmethod
    def _kind_from_link(name: str, link: dict) -> str:
        link_type = (link.get("link_type") or "").lower()
        if link_type == "loopback":
            return "loopback"
        if link.get("linkinfo", {}).get("info_kind"):
            return link["linkinfo"]["info_kind"]
        if os.path.isdir(f"{SYSFS_NET}/{name}/wireless"):
            return "wireless"
        if os.path.isdir(f"{SYSFS_NET}/{name}/bridge"):
            return "bridge"
        if not os.path.exists(f"{SYSFS_NET}/{name}/device"):
            return "virtual"
        return "ethernet"

    def _nm_connections(self) -> dict[str, dict]:
        """Map device name -> active NetworkManager connection profile."""
        if not shutil.which("nmcli"):
            return {}
        code, out, _ = _run(["nmcli", "-t", "-f", "DEVICE,UUID,NAME", "connection", "show", "--active"])
        if code != 0:
            return {}
        result: dict[str, dict] = {}
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) < 3:
                continue
            device, uuid, name = parts[0], parts[1], ":".join(parts[2:])
            if device and device != "--":
                result[device] = {"uuid": uuid, "name": name}
        return result

    def get_interface(self, name: str) -> Interface | None:
        for iface in self.list_interfaces():
            if iface.name == name:
                return iface
        return None

    # ------------------------------------------------------------------ write
    def set_mac(self, name: str, mac: str) -> tuple[bool, str]:
        """Set the hardware address of `name` using iproute2."""
        mac = normalize(mac)
        if not is_valid(mac):
            return False, f"invalid MAC address: {mac}"

        code, _, err = _run(["ip", "link", "set", "dev", name, "down"])
        if code != 0:
            return False, f"failed to bring {name} down: {err}"

        code, _, err = _run(["ip", "link", "set", "dev", name, "address", mac])
        if code != 0:
            _run(["ip", "link", "set", "dev", name, "up"])
            return False, f"failed to set MAC on {name}: {err}"

        code, _, err = _run(["ip", "link", "set", "dev", name, "up"])
        if code != 0:
            return False, f"failed to bring {name} up: {err}"
        return True, f"{name} -> {mac}"

    def restore_mac(self, name: str) -> tuple[bool, str]:
        iface = self.get_interface(name)
        if iface is None:
            return False, f"interface not found: {name}"
        if not iface.permanent_mac:
            return False, f"no permanent MAC known for {name}"
        return self.set_mac(name, iface.permanent_mac)

    # ------------------------------------------------------------ persistence
    # NetworkManager exposes the ethernet setting group under two spellings
    # depending on version: the legacy `802-11-ethernet` and the current
    # `802-3-ethernet` (alias `ethernet`). Try each until one is accepted.
    _CLONE_PROPERTIES = (
        "802-3-ethernet.cloned-mac-address",
        "ethernet.cloned-mac-address",
        "802-11-ethernet.cloned-mac-address",
    )

    def _nm_set_clone(self, uuid: str, value: str) -> tuple[bool, str]:
        """Set cloned-mac-address on a profile, trying known property names."""
        last_err = ""
        for prop in self._CLONE_PROPERTIES:
            code, _, err = _run(["nmcli", "connection", "modify", uuid, prop, value])
            if code == 0:
                return True, prop
            last_err = err
        return False, last_err

    def nm_set_persistent(self, name: str, mac: str) -> tuple[bool, str]:
        """Make the spoofed MAC survive reconnects via NetworkManager."""
        iface = self.get_interface(name)
        if iface is None or not iface.nm_uuid:
            return False, f"no active NetworkManager profile for {name}"
        mac = normalize(mac)
        ok, detail = self._nm_set_clone(iface.nm_uuid, mac)
        if not ok:
            return False, f"nmcli failed: {detail}"
        return True, f"NetworkManager profile '{iface.nm_connection}' will use {mac}"

    def nm_clear_persistent(self, name: str) -> tuple[bool, str]:
        iface = self.get_interface(name)
        if iface is None or not iface.nm_uuid:
            return False, f"no active NetworkManager profile for {name}"
        # "permanent" tells NetworkManager to fall back to the real hardware
        # address again; an empty value unsets the clone.
        ok, detail = self._nm_set_clone(iface.nm_uuid, "permanent")
        if not ok:
            return False, f"nmcli failed: {detail}"
        return True, f"NetworkManager profile '{iface.nm_connection}' restored to default MAC"

    # -------------------------------------------------------------- systemd
    def systemd_unit_name(self) -> str:
        return "macspoof.service"

    def systemd_unit_path(self) -> str:
        return f"/etc/systemd/system/{self.systemd_unit_name()}"

    def render_systemd_unit(self, iface_name: str, mac: str | None = None) -> str:
        """Build the unit file text for `iface_name`."""
        payload = mac or "random"
        exec_start, env_lines = self._exec_cmd("set", "--interface", iface_name, payload)
        exec_stop, _ = self._exec_cmd("restore", "--interface", iface_name)
        env_block = "".join(f"Environment={line}\n" for line in env_lines)
        return f"""[Unit]
Description=macspoof - set a spoofed MAC address on {iface_name}
After=network-pre.target systemd-networkd.service NetworkManager.service
Before=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
{env_block}ExecStart={exec_start}
ExecStop={exec_stop}

[Install]
WantedBy=multi-user.target
"""

    @staticmethod
    def _exec_cmd(*args: str) -> tuple[str, list[str]]:
        """Command line that invokes macspoof, plus needed env vars.

        Prefers the installed `macspoof` console script; otherwise runs the
        module with the interpreter that imported it, exporting PYTHONPATH so
        the import works regardless of the service's working directory.
        """
        found = shutil.which("macspoof")
        if found:
            return " ".join([found, *args]), []

        import sys

        module_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        parent = os.path.dirname(module_root)
        env = [f"PYTHONPATH={parent}"] if parent else []
        return " ".join([sys.executable, "-m", "macspoof", *args]), env

    def install_systemd_unit(self, iface_name: str, mac: str | None = None) -> tuple[bool, str]:
        """Install a systemd unit that re-applies the MAC at boot."""
        if not shutil.which("systemctl"):
            return False, "systemctl not found"

        unit = self.render_systemd_unit(iface_name, mac)
        unit_path = self.systemd_unit_path()
        try:
            with open(unit_path, "w") as fh:
                fh.write(unit)
        except PermissionError:
            return False, f"permission denied writing {unit_path} (need root)"
        except OSError as exc:
            return False, f"cannot write {unit_path}: {exc}"

        _run(["systemctl", "daemon-reload"])
        code, _, err = _run(["systemctl", "enable", self.systemd_unit_name()])
        if code != 0:
            return False, f"systemctl enable failed: {err}"
        return True, f"installed and enabled {unit_path}"

    def uninstall_systemd_unit(self) -> tuple[bool, str]:
        if not shutil.which("systemctl"):
            return False, "systemctl not found"
        _run(["systemctl", "disable", "--now", self.systemd_unit_name()])
        unit_path = self.systemd_unit_path()
        try:
            os.remove(unit_path)
        except FileNotFoundError:
            pass
        except PermissionError:
            return False, f"permission denied removing {unit_path} (need root)"
        except OSError as exc:
            return False, f"cannot remove {unit_path}: {exc}"
        _run(["systemctl", "daemon-reload"])
        return True, "removed systemd unit"
