"""Desktop notifications via notify-send. Fire-and-forget; never blocks the caller."""
from __future__ import annotations

import subprocess
from typing import Literal

from porcaria.shellout import which

Urgency = Literal["low", "normal", "critical"]


def send(
    title: str,
    body: str = "",
    *,
    urgency: Urgency = "normal",
    icon: str | None = None,
) -> bool:
    """Send a desktop notification without blocking.

    Returns True if the spawn succeeded, False if notify-send is missing or the
    spawn itself failed. We do NOT wait for the subprocess — notify-send can
    take 20–40 ms synchronously via D-Bus, and three of those per dictation
    toggle noticeably delays the hot path.
    """
    if not which("notify-send"):
        return False
    argv = ["notify-send", "-u", urgency]
    if icon:
        argv.extend(["-i", icon])
    argv.append(title)
    if body:
        argv.append(body)
    try:
        subprocess.Popen(  # noqa: S603
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def info(title: str, body: str = "") -> bool:
    return send(title, body, urgency="low", icon="dialog-information")


def warn(title: str, body: str = "") -> bool:
    return send(title, body, urgency="normal", icon="dialog-warning")


def error(title: str, body: str = "") -> bool:
    return send(title, body, urgency="critical", icon="dialog-error")
