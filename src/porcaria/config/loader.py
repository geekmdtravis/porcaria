"""Load porcaria config: defaults → user TOML → env overlay."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from porcaria import paths
from porcaria.config.schema import Config

DEFAULTS_FILE = Path(__file__).with_name("defaults.toml")


def _read_toml(p: Path) -> dict[str, Any]:
    with p.open("rb") as f:
        return tomllib.load(f)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


_ENV_MAP: dict[str, tuple[str, ...]] = {
    "PORCARIA_PROFILE": ("active_profile",),
    "PORCARIA_ASR": ("profiles", "_active", "asr"),
    "PORCARIA_TTS": ("profiles", "_active", "tts"),
    "PORCARIA_LLM": ("profiles", "_active", "llm"),
    "PORCARIA_LLM_URL": ("llm", "llamacpp", "url"),
    "PORCARIA_PARAKEET_URL": ("asr", "parakeet", "url"),
    "PORCARIA_KOKORO_URL": ("tts", "kokoro", "url"),
    "PORCARIA_IPC_SOCKET": ("daemon", "ipc_socket"),
    "PORCARIA_HTTP_ENABLED": ("daemon", "http_enabled"),
    "PORCARIA_HTTP_BIND": ("daemon", "http_bind"),
}


def _set_nested(d: dict[str, Any], path: tuple[str, ...], val: Any) -> None:
    cur = d
    for key in path[:-1]:
        cur = cur.setdefault(key, {})
    cur[path[-1]] = val


def _coerce(val: str) -> Any:
    if val.lower() in ("true", "false"):
        return val.lower() == "true"
    return val


def _apply_env(data: dict[str, Any]) -> dict[str, Any]:
    active = os.environ.get("PORCARIA_PROFILE", data.get("active_profile", "home"))
    for env_key, path in _ENV_MAP.items():
        if env_key not in os.environ:
            continue
        concrete = tuple(active if seg == "_active" else seg for seg in path)
        _set_nested(data, concrete, _coerce(os.environ[env_key]))
    return data


def load_config(user_file: Path | None = None) -> Config:
    data = _read_toml(DEFAULTS_FILE)
    uf = user_file if user_file is not None else paths.config_file()
    if uf.exists():
        data = _deep_merge(data, _read_toml(uf))
    data = _apply_env(data)
    return Config.model_validate(data)


def defaults_text() -> str:
    return DEFAULTS_FILE.read_text()
