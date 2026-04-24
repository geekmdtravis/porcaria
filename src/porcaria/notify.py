"""Desktop notifications via notify-send. Fire-and-forget; never blocks the caller.

Level taxonomy (pick the one that matches intent at the call site):

- ``debug``   — internal diagnostic, off in all normal configurations.
- ``info``    — in-progress chatter (e.g. "Recording…", "Transcribing…"). The
                waybar status module already surfaces these; treat them as noise
                for desktop popups.
- ``warning`` — notable completion OR soft degradation. Use ``notify.success``
                for happy-path completions (e.g. "Done • 47 chars",
                "parakeet ready") and ``notify.warn`` for soft issues
                (e.g. "AI cleanup failed, using raw transcription",
                "No speech detected").
- ``error``   — a failure that aborted the request (e.g. ASR unreachable, sink
                delivery failed, server failed to start).
- ``critical``— catastrophic; reserved for daemon-level can't-start-at-all cases.

The active threshold is read from ``PORCARIA_NOTIFY_LEVEL`` (default:
``warning``), set by ``porcaria daemon start --notify-level LEVEL``. Only
levels at or above the threshold surface; ``none`` suppresses everything.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Literal

from porcaria.shellout import which

Urgency = Literal["low", "normal", "critical"]
Level = Literal["debug", "info", "warning", "error", "critical"]

_LEVEL_ORDER: tuple[Level, ...] = ("debug", "info", "warning", "error", "critical")
_SILENT_TOKENS = frozenset({"none", "off", "silent", ""})
DEFAULT_LEVEL: Level = "warning"
APP_NAME = "porcaria"

log = logging.getLogger(__name__)


def _active_threshold() -> Level | None:
    """Return the active level threshold, or None to suppress everything."""
    raw = os.environ.get("PORCARIA_NOTIFY_LEVEL", DEFAULT_LEVEL).strip().lower()
    if raw in _SILENT_TOKENS:
        return None
    if raw in _LEVEL_ORDER:
        return raw  # type: ignore[return-value]
    log.warning(
        "unknown PORCARIA_NOTIFY_LEVEL=%r; falling back to %r", raw, DEFAULT_LEVEL
    )
    return DEFAULT_LEVEL


def _passes(level: Level) -> bool:
    threshold = _active_threshold()
    if threshold is None:
        return False
    return _LEVEL_ORDER.index(level) >= _LEVEL_ORDER.index(threshold)


def send(
    title: str,
    body: str = "",
    *,
    urgency: Urgency = "normal",
    icon: str | None = None,
    level: Level = "info",
) -> bool:
    """Send a desktop notification without blocking.

    Returns True if the spawn succeeded, False if the message was filtered by
    the level threshold, notify-send is missing, or the spawn itself failed.

    We do NOT wait for the subprocess — notify-send can take 20–40 ms
    synchronously via D-Bus, and three of those per dictation toggle noticeably
    delays the hot path.
    """
    if not _passes(level):
        return False
    if not which("notify-send"):
        return False
    argv = ["notify-send", "-a", APP_NAME, "-u", urgency]
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


def debug(title: str, body: str = "") -> bool:
    return send(title, body, urgency="low", icon="dialog-information", level="debug")


def info(title: str, body: str = "") -> bool:
    return send(title, body, urgency="low", icon="dialog-information", level="info")


def success(title: str, body: str = "") -> bool:
    """Terminal happy-path completion (e.g. 'Done • 47 chars', 'server ready').

    Sits at ``warning`` level so it's visible under the default threshold
    without re-introducing the chatty in-progress popups.
    """
    return send(title, body, urgency="normal", icon="dialog-information", level="warning")


def warn(title: str, body: str = "") -> bool:
    return send(title, body, urgency="normal", icon="dialog-warning", level="warning")


def error(title: str, body: str = "") -> bool:
    return send(title, body, urgency="critical", icon="dialog-error", level="error")


def critical(title: str, body: str = "") -> bool:
    return send(title, body, urgency="critical", icon="dialog-error", level="critical")
