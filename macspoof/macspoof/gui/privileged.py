"""Running privileged operations from the unprivileged GUI.

The GUI never runs as root.  Privileged work is delegated to the macspoof
helper through ``pkexec``, which asks the desktop's polkit agent for
authentication.  If the GUI itself is already running as root the helper is
invoked directly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from . import helperpath

HELPER_MODULE = "macspoof.helper"


class PrivilegedError(Exception):
    """Raised when a privileged operation could not be completed."""


def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _run(command: list[str], timeout: int = 90) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise PrivilegedError(f"{command[0]} not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PrivilegedError("the authentication dialog was not answered in time") from exc
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _interpret(code: int, stderr: str) -> str | None:
    """Turn an exit code into a human readable reason, or None if it worked."""
    if code == 0:
        return None
    lowered = stderr.lower()
    if "not authorized" in lowered or "authorization could not be obtained" in lowered:
        return "Authentication was cancelled or denied."
    if "authentication is required" in lowered:
        return "Authentication is required to change a MAC address."
    if "127" in lowered and "command not found" in lowered:
        return "The privileged helper could not be started."
    return stderr.strip() or f"the privileged helper failed (exit code {code})"


def _direct_command() -> list[str]:
    """Command used when we are already root."""
    return [sys.executable, "-m", HELPER_MODULE]


def run_helper(*args: str, timeout: int = 90) -> str:
    """Run the privileged helper with `args` and return its stdout.

    Raises PrivilegedError with a message suitable for showing to the user.
    """
    if is_root():
        command = _direct_command() + list(args)
    else:
        pkexec = shutil.which("pkexec")
        if not pkexec:
            raise PrivilegedError(
                "pkexec is not installed, so the GUI cannot authenticate. "
                "Run the GUI as root instead."
            )
        command = [pkexec] + helperpath.helper_command() + list(args)

    code, stdout, stderr = _run(command, timeout=timeout)
    reason = _interpret(code, stderr)
    if reason:
        raise PrivilegedError(reason)
    return stdout
