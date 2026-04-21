from __future__ import annotations

import os
from pathlib import Path

import pytest

from porcaria.config import load_config
from porcaria.config.loader import _deep_merge


def test_defaults_load_cleanly():
    cfg = load_config(user_file=Path("/nonexistent/never/exists.toml"))
    assert cfg.active_profile == "home"
    assert "home" in cfg.profiles
    assert "travel" in cfg.profiles


def test_user_overlay(tmp_path: Path):
    user = tmp_path / "config.toml"
    user.write_text(
        """
active_profile = "travel"

[llm.llamacpp]
url = "http://override.example.com:9999"
"""
    )
    cfg = load_config(user_file=user)
    assert cfg.active_profile == "travel"
    assert cfg.llm.llamacpp.url == "http://override.example.com:9999"
    # untouched default preserved
    assert cfg.llm.openrouter.model == "anthropic/claude-sonnet-4-6"


def test_env_overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    user = tmp_path / "config.toml"
    user.write_text("active_profile = \"home\"\n")
    monkeypatch.setenv("PORCARIA_PROFILE", "travel")
    monkeypatch.setenv("PORCARIA_LLM_URL", "http://env.example.com:1234")
    cfg = load_config(user_file=user)
    assert cfg.active_profile == "travel"
    assert cfg.llm.llamacpp.url == "http://env.example.com:1234"


def test_profile_selector_accessor():
    cfg = load_config(user_file=Path("/nonexistent"))
    prof = cfg.profile()
    assert prof.asr == "parakeet"
    assert prof.llm == "llamacpp"
    travel = cfg.profile("travel")
    assert travel.llm == "openrouter"
    with pytest.raises(KeyError):
        cfg.profile("does-not-exist")


def test_deep_merge_nested():
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    overlay = {"a": {"c": 20, "e": 5}}
    assert _deep_merge(base, overlay) == {"a": {"b": 1, "c": 20, "e": 5}, "d": 3}
