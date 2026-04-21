"""Play WAV audio via whichever player is available on the host."""
from __future__ import annotations

import subprocess
from pathlib import Path

from porcaria.shellout import which

# Ordered by preference. pw-play and ffplay can take stdin, others need a file.
_PLAYERS_STDIN = ["pw-play", "ffplay"]
_PLAYERS_FILE = ["paplay", "aplay", "afplay"]


def play_bytes(wav: bytes) -> bool:
    """Play WAV bytes. Uses stdin when possible, tmp-file otherwise."""
    for binary in _PLAYERS_STDIN:
        if which(binary):
            argv = [binary, "-"] if binary == "pw-play" else [binary, "-nodisp", "-autoexit", "-loglevel", "error", "-"]
            try:
                proc = subprocess.run(argv, input=wav, timeout=300, capture_output=True)
                if proc.returncode == 0:
                    return True
            except (subprocess.SubprocessError, FileNotFoundError):
                continue

    # Stdin path failed or unavailable — fall back to temp file.
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tf:
        tf.write(wav)
        tf.flush()
        return play_file(Path(tf.name))


def play_file(path: Path) -> bool:
    """Play a WAV file. Returns True if any player succeeded."""
    for binary in _PLAYERS_FILE + _PLAYERS_STDIN:
        if not which(binary):
            continue
        if binary == "ffplay":
            argv = [binary, "-nodisp", "-autoexit", "-loglevel", "error", str(path)]
        else:
            argv = [binary, str(path)]
        try:
            proc = subprocess.run(argv, timeout=300, capture_output=True)
            if proc.returncode == 0:
                return True
        except (subprocess.SubprocessError, FileNotFoundError):
            continue
    return False


def any_player_available() -> bool:
    return any(which(b) for b in _PLAYERS_STDIN + _PLAYERS_FILE)
