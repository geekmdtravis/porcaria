from __future__ import annotations

import pytest
from typer.testing import CliRunner

from porcaria.cli import daemon as daemon_cli


class _FakePopen:
    last_env: dict | None = None

    def __init__(self, *args, env=None, **kwargs) -> None:
        _FakePopen.last_env = env
        self.pid = 12345


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    _FakePopen.last_env = None
    monkeypatch.setattr("porcaria.cli.daemon.subprocess.Popen", _FakePopen)
    # Avoid polling for socket (never appears in the test).
    monkeypatch.setattr("porcaria.cli.daemon.time.sleep", lambda *_a, **_kw: None)
    # Pretend no existing daemon.
    monkeypatch.setattr("porcaria.cli.daemon._read_pid", lambda: None)
    yield


def test_start_default_does_not_set_notify_env():
    runner = CliRunner()
    result = runner.invoke(daemon_cli.app, ["start"])
    assert result.exit_code == 0, result.output
    assert _FakePopen.last_env is not None
    assert "PORCARIA_NOTIFY" not in _FakePopen.last_env


def test_start_with_notify_sets_env():
    runner = CliRunner()
    result = runner.invoke(daemon_cli.app, ["start", "--notify"])
    assert result.exit_code == 0, result.output
    assert _FakePopen.last_env is not None
    assert _FakePopen.last_env.get("PORCARIA_NOTIFY") == "1"


def test_start_default_strips_inherited_notify(monkeypatch):
    """Even if the invoking shell has PORCARIA_NOTIFY=1 exported, default is silent."""
    monkeypatch.setenv("PORCARIA_NOTIFY", "1")
    runner = CliRunner()
    result = runner.invoke(daemon_cli.app, ["start"])
    assert result.exit_code == 0, result.output
    assert _FakePopen.last_env is not None
    assert "PORCARIA_NOTIFY" not in _FakePopen.last_env
