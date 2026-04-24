from __future__ import annotations

import pytest

from porcaria import notify

# Capture the real implementations before the autouse silencing fixture overrides them.
_REAL = {name: getattr(notify, name) for name in ("send", "info", "warn", "error")}


def _restore_real(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the conftest autouse stub so we exercise the real send() gate."""
    for name, fn in _REAL.items():
        monkeypatch.setattr(notify, name, fn)


def test_send_default_silent_never_spawns(monkeypatch: pytest.MonkeyPatch) -> None:
    _restore_real(monkeypatch)
    monkeypatch.delenv("PORCARIA_NOTIFY", raising=False)

    def boom(*a, **kw):  # pragma: no cover - asserts it isn't called
        raise AssertionError("notify-send should not spawn when PORCARIA_NOTIFY is unset")

    monkeypatch.setattr("porcaria.notify.subprocess.Popen", boom)

    assert notify.send("t", "b") is False


def test_send_with_env_spawns(monkeypatch: pytest.MonkeyPatch) -> None:
    _restore_real(monkeypatch)
    monkeypatch.setenv("PORCARIA_NOTIFY", "1")
    monkeypatch.setattr("porcaria.notify.which", lambda _: "/usr/bin/notify-send")

    called = {"n": 0}

    class FakePopen:
        def __init__(self, *a, **kw):
            called["n"] += 1

    monkeypatch.setattr("porcaria.notify.subprocess.Popen", FakePopen)

    assert notify.send("t", "b") is True
    assert called["n"] == 1


def test_info_warn_error_respect_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    _restore_real(monkeypatch)
    monkeypatch.delenv("PORCARIA_NOTIFY", raising=False)

    def boom(*a, **kw):  # pragma: no cover - asserts it isn't called
        raise AssertionError("notify-send should not spawn")

    monkeypatch.setattr("porcaria.notify.subprocess.Popen", boom)

    assert notify.info("t", "b") is False
    assert notify.warn("t", "b") is False
    assert notify.error("t", "b") is False
