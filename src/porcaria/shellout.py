"""Thin subprocess wrapper with timeout, stderr capture, and sensible defaults."""
from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Completed:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run(
    argv: list[str] | str,
    *,
    timeout: float | None = 60.0,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    check: bool = False,
) -> Completed:
    """Run a command; return Completed. Accepts list or string (string is shlex.split)."""
    if isinstance(argv, str):
        argv = shlex.split(argv)
    log.debug("run: %s", argv)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
            input=stdin,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        return Completed(returncode=127, stdout="", stderr=str(e))
    except subprocess.TimeoutExpired as e:
        return Completed(returncode=124, stdout=e.stdout or "", stderr=f"timeout after {timeout}s")
    out = Completed(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    if check and not out.ok:
        raise RuntimeError(f"command failed ({out.returncode}): {argv}\nstderr:\n{out.stderr}")
    return out


def which(cmd: str) -> bool:
    """Return True if `cmd` is on PATH."""
    from shutil import which as _which

    return _which(cmd) is not None
