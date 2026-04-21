from __future__ import annotations

from pathlib import Path

import pytest

from porcaria import paths


def test_runtime_dir_prefers_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert paths.runtime_dir() == tmp_path / "porcaria"


def test_runtime_dir_falls_back_to_tmp(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert paths.runtime_dir() == Path("/tmp") / "porcaria"


def test_expand_env_and_home(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MY_DIR", "/opt/stuff")
    assert paths.expand("$MY_DIR/foo") == Path("/opt/stuff/foo")
    assert paths.expand("~/bar").is_absolute()


def test_ipc_socket_under_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert paths.ipc_socket() == tmp_path / "porcaria" / "ipc.sock"
