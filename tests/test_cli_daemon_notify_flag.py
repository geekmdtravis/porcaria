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


def test_start_default_sets_level_warning():
    runner = CliRunner()
    result = runner.invoke(daemon_cli.app, ["start"])
    assert result.exit_code == 0, result.output
    assert _FakePopen.last_env is not None
    assert _FakePopen.last_env.get("PORCARIA_NOTIFY_LEVEL") == "warning"
    # Legacy boolean env var should always be stripped.
    assert "PORCARIA_NOTIFY" not in _FakePopen.last_env


def test_start_with_explicit_level_info():
    runner = CliRunner()
    result = runner.invoke(daemon_cli.app, ["start", "--notify-level", "info"])
    assert result.exit_code == 0, result.output
    assert _FakePopen.last_env is not None
    assert _FakePopen.last_env.get("PORCARIA_NOTIFY_LEVEL") == "info"


def test_start_with_level_none_silences():
    runner = CliRunner()
    result = runner.invoke(daemon_cli.app, ["start", "--notify-level", "none"])
    assert result.exit_code == 0, result.output
    assert _FakePopen.last_env.get("PORCARIA_NOTIFY_LEVEL") == "none"


def test_start_rejects_invalid_level():
    runner = CliRunner()
    result = runner.invoke(daemon_cli.app, ["start", "--notify-level", "loud"])
    assert result.exit_code == 2, result.output
    assert "invalid --notify-level" in result.output or "invalid --notify-level" in (result.stderr or "")


def test_start_level_is_case_insensitive():
    runner = CliRunner()
    result = runner.invoke(daemon_cli.app, ["start", "--notify-level", "WARNING"])
    assert result.exit_code == 0, result.output
    assert _FakePopen.last_env.get("PORCARIA_NOTIFY_LEVEL") == "warning"


def test_start_strips_inherited_notify_boolean(monkeypatch):
    """Even if the invoking shell has the legacy PORCARIA_NOTIFY=1, it gets stripped."""
    monkeypatch.setenv("PORCARIA_NOTIFY", "1")
    runner = CliRunner()
    result = runner.invoke(daemon_cli.app, ["start"])
    assert result.exit_code == 0, result.output
    assert "PORCARIA_NOTIFY" not in _FakePopen.last_env
    assert _FakePopen.last_env.get("PORCARIA_NOTIFY_LEVEL") == "warning"
