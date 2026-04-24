"""Thread-safe live pipeline state tracker.

Mirrors the full `porcaria status` dict to $XDG_RUNTIME_DIR/porcaria/status.json
so waybar (and other high-frequency pollers) can read it cheaply each tick
instead of invoking the CLI. Phase transitions and the recording flag update
live fields immediately; server-health fields in the mirror are refreshed on a
background timer so transitions stay fast.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from porcaria import paths

log = logging.getLogger(__name__)

_REFRESH_INTERVAL_S = 3.0
_STATUS_FILENAME = "status.json"

_lock = threading.Lock()
_phase_stack: list[str] = []
_recording: bool = False
_build_status: Callable[[], dict] | None = None
_cached_full: dict = {}
_refresher_task: asyncio.Task | None = None


def status_path() -> Path:
    return paths.runtime_dir() / _STATUS_FILENAME


def _snapshot_live_locked() -> dict:
    stack = list(_phase_stack)
    recording = _recording
    if recording:
        active = "recording"
    elif stack:
        active = stack[-1]
    else:
        active = "idle"
    return {
        "active": active,
        "recording": recording,
        "phase_stack": stack,
        "busy": recording or bool(stack),
        "updated_ns": time.time_ns(),
    }


def snapshot_live() -> dict:
    """Snapshot of the live-state fields that merge into the status dict."""
    with _lock:
        return _snapshot_live_locked()


def _atomic_write(payload: dict) -> None:
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, separators=(",", ":"))
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        f.write(data)
    os.replace(tmp, path)


def _write_fast() -> None:
    """Merge current live fields onto the cached base dict and write."""
    with _lock:
        if _build_status is None:
            return
        merged = copy.deepcopy(_cached_full)
        merged.update(_snapshot_live_locked())
    try:
        _atomic_write(merged)
    except OSError as e:
        log.warning("status.json write failed: %s", e)


def _rebuild_and_write() -> None:
    """Invoke build_status (incl. server health probes) and refresh the cache + file."""
    global _cached_full
    if _build_status is None:
        return
    try:
        base = _build_status()
    except Exception:
        log.exception("live_state build_status callback failed")
        return
    with _lock:
        if _build_status is None:
            return
        _cached_full = base
        merged = copy.deepcopy(_cached_full)
        merged.update(_snapshot_live_locked())
    try:
        _atomic_write(merged)
    except OSError as e:
        log.warning("status.json write failed: %s", e)


async def _refresher_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_REFRESH_INTERVAL_S)
            await asyncio.to_thread(_rebuild_and_write)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("live_state refresher iteration failed")


def init(build_status: Callable[[], dict]) -> None:
    """Register the full-status builder, write an initial file, start the refresher."""
    global _build_status, _refresher_task
    with _lock:
        _build_status = build_status
        _phase_stack.clear()
        # _recording intentionally left alone — a fresh daemon start sets False
        # at ffmpeg-pid cleanup time; tests may seed it directly.
    _rebuild_and_write()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _refresher_task = None
        return
    _refresher_task = loop.create_task(_refresher_loop())


def teardown() -> None:
    """Stop the refresher, drop the builder, unlink the file."""
    global _build_status, _refresher_task, _cached_full
    task = _refresher_task
    _refresher_task = None
    if task is not None:
        task.cancel()
    with _lock:
        _build_status = None
        _cached_full = {}
        _phase_stack.clear()
    with contextlib.suppress(FileNotFoundError):
        status_path().unlink()


def set_recording(value: bool) -> None:
    global _recording
    with _lock:
        _recording = bool(value)
    _write_fast()


@contextlib.contextmanager
def phase(name: str) -> Iterator[None]:
    with _lock:
        _phase_stack.append(name)
    _write_fast()
    try:
        yield
    finally:
        with _lock:
            for i in range(len(_phase_stack) - 1, -1, -1):
                if _phase_stack[i] == name:
                    del _phase_stack[i]
                    break
        _write_fast()


def _reset_for_tests() -> None:
    """Reset module-level state. Only intended for pytest teardown."""
    global _build_status, _refresher_task, _cached_full, _recording
    task = _refresher_task
    _refresher_task = None
    if task is not None:
        task.cancel()
    with _lock:
        _build_status = None
        _cached_full = {}
        _phase_stack.clear()
        _recording = False
