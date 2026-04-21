"""Audio capture via ffmpeg. Toggle semantics with persistent state under runtime_dir.

State files (all under $XDG_RUNTIME_DIR/porcaria/):
    ffmpeg.pid   — active ffmpeg subprocess
    dictation.wav — the WAV being written
    watchdog.pid  — optional timeout watchdog (not used by the daemon; kept
                    for bash-era compatibility)
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from porcaria import paths
from porcaria.shellout import which


class RecorderUnavailable(RuntimeError):
    """A required external recording dependency (ffmpeg) is missing."""


@dataclass
class RecorderPaths:
    pid_file: Path
    wav_file: Path
    log_file: Path

    @classmethod
    def default(cls) -> RecorderPaths:
        rt = paths.runtime_dir()
        return cls(
            pid_file=rt / "ffmpeg.pid",
            wav_file=rt / "dictation.wav",
            log_file=rt / "ffmpeg.log",
        )


def _read_pid(p: Path) -> int | None:
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (ValueError, OSError):
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _try_reap(pid: int) -> bool:
    """Non-blocking reap. Returns True if the child has exited (and was either
    reaped here or already gone). False if it's still running.

    Important: a child that exited but hasn't been reaped is a zombie; os.kill(pid,0)
    reports it as alive. waitpid(WNOHANG) either reaps it (returns non-zero pid)
    or raises ChildProcessError if it's already been reaped / isn't our child.
    """
    try:
        reaped, _status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        # Not our child (daemon restarted, or already reaped) — fall back to /proc check.
        return not _alive(pid)
    if reaped == 0:
        return False  # still running
    return True


def is_recording(rp: RecorderPaths | None = None) -> bool:
    rp = rp or RecorderPaths.default()
    pid = _read_pid(rp.pid_file)
    return bool(pid and _alive(pid))


def start(
    *,
    sample_rate: int = 16000,
    mono: bool = True,
    pulse_source: str = "default",
    max_duration_s: int = 600,
    rp: RecorderPaths | None = None,
) -> int:
    """Start ffmpeg recording. Returns the subprocess PID.

    The daemon is responsible for stopping recording on toggle; if it wants a
    hard cap it should schedule a watchdog. `max_duration_s` is kept in the
    signature for future use.
    """
    rp = rp or RecorderPaths.default()
    paths.ensure_dirs()

    if not which("ffmpeg"):
        raise RecorderUnavailable(
            "ffmpeg not found on PATH — install it (e.g. `sudo pacman -S ffmpeg` "
            "or `brew install ffmpeg`) to enable voice capture."
        )

    if is_recording(rp):
        raise RuntimeError("recording already in progress")

    rp.wav_file.unlink(missing_ok=True)
    rp.log_file.unlink(missing_ok=True)

    # Match the bash reference invocation exactly. No -t (daemon owns the
    # timeout), no -y (we unlinked any stale file above — nothing to overwrite).
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-f", "pulse",
        "-i", pulse_source,
        "-ac", "1" if mono else "2",
        "-ar", str(sample_rate),
        "-c:a", "pcm_s16le",
        str(rp.wav_file),
    ]
    log_fh = rp.log_file.open("ab")
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    rp.pid_file.write_text(str(proc.pid))
    return proc.pid


def stop(rp: RecorderPaths | None = None, *, wait_s: float = 5.0) -> bytes:
    """Stop the active recording and return the WAV bytes.

    Sends SIGINT to ffmpeg (which flushes the WAV header cleanly), uses
    waitpid(WNOHANG) to notice the moment the process is reaped — crucial,
    because os.kill(pid, 0) reports zombie processes as alive and would force
    us to wait the full wait_s timeout every time.
    """
    rp = rp or RecorderPaths.default()
    pid = _read_pid(rp.pid_file)
    if pid is None:
        raise RuntimeError("no active recording")

    if _alive(pid):
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + wait_s
        while not _try_reap(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        if not _try_reap(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            # Give SIGTERM a short window, then try SIGKILL as a last resort.
            end = time.monotonic() + 0.5
            while not _try_reap(pid) and time.monotonic() < end:
                time.sleep(0.02)
            if not _try_reap(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                _try_reap(pid)

    rp.pid_file.unlink(missing_ok=True)

    if not rp.wav_file.exists() or rp.wav_file.stat().st_size == 0:
        raise RuntimeError("no audio captured")
    return rp.wav_file.read_bytes()


def cancel(rp: RecorderPaths | None = None) -> bool:
    """Cancel recording without producing a transcript. Returns True if there was
    something to cancel."""
    rp = rp or RecorderPaths.default()
    pid = _read_pid(rp.pid_file)
    if pid is None:
        return False
    if _alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    rp.pid_file.unlink(missing_ok=True)
    rp.wav_file.unlink(missing_ok=True)
    return True
