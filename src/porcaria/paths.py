"""XDG path helpers."""
from __future__ import annotations

import os
from pathlib import Path

APP = "porcaria"


def _xdg(var: str, default_under_home: str) -> Path:
    val = os.environ.get(var)
    return Path(val) if val else Path.home() / default_under_home


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def config_file() -> Path:
    return config_dir() / "config.toml"


def runtime_dir() -> Path:
    val = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(val) if val else Path("/tmp")
    return base / APP


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / APP


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / APP


def ipc_socket() -> Path:
    return runtime_dir() / "ipc.sock"


def documents_dir() -> Path:
    val = os.environ.get("XDG_DOCUMENTS_DIR")
    return Path(val) if val else Path.home() / "Documents"


def ensure_dirs() -> None:
    for d in (config_dir(), runtime_dir(), state_dir(), cache_dir()):
        d.mkdir(parents=True, exist_ok=True)


def expand(p: str | Path) -> Path:
    """Expand ~ and $VAR in a string path."""
    return Path(os.path.expandvars(os.path.expanduser(str(p))))
