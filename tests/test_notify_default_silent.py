from __future__ import annotations

import pytest

from porcaria import notify

# Capture the real implementations before the autouse silencing fixture overrides them.
_REAL = {
    name: getattr(notify, name)
    for name in ("send", "debug", "info", "success", "warn", "error", "critical")
}


def _restore_real(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the conftest autouse stub so we exercise the real send() gate."""
    for name, fn in _REAL.items():
        monkeypatch.setattr(notify, name, fn)


def _count_popens(monkeypatch: pytest.MonkeyPatch) -> dict:
    calls = {"n": 0}
    monkeypatch.setattr("porcaria.notify.which", lambda _: "/usr/bin/notify-send")

    class FakePopen:
        def __init__(self, *a, **kw):
            calls["n"] += 1

    monkeypatch.setattr("porcaria.notify.subprocess.Popen", FakePopen)
    return calls


def test_default_threshold_passes_warning_and_above(monkeypatch):
    """Default is 'warning' — completions + warnings + errors visible; info hidden."""
    _restore_real(monkeypatch)
    monkeypatch.delenv("PORCARIA_NOTIFY_LEVEL", raising=False)
    calls = _count_popens(monkeypatch)

    assert notify.debug("t") is False
    assert notify.info("t") is False
    assert notify.success("t") is True
    assert notify.warn("t") is True
    assert notify.error("t") is True
    assert notify.critical("t") is True
    assert calls["n"] == 4


def test_level_info_passes_everything_except_debug(monkeypatch):
    _restore_real(monkeypatch)
    monkeypatch.setenv("PORCARIA_NOTIFY_LEVEL", "info")
    calls = _count_popens(monkeypatch)

    assert notify.debug("t") is False
    assert notify.info("t") is True
    assert notify.success("t") is True
    assert notify.warn("t") is True
    assert notify.error("t") is True
    assert notify.critical("t") is True
    assert calls["n"] == 5


def test_level_debug_passes_everything(monkeypatch):
    _restore_real(monkeypatch)
    monkeypatch.setenv("PORCARIA_NOTIFY_LEVEL", "debug")
    calls = _count_popens(monkeypatch)

    assert notify.debug("t") is True
    assert notify.info("t") is True
    assert notify.success("t") is True
    assert notify.warn("t") is True
    assert notify.error("t") is True
    assert notify.critical("t") is True
    assert calls["n"] == 6


def test_level_error_suppresses_warning_and_success(monkeypatch):
    """Dropping to 'error' silences completions again — failures-only mode."""
    _restore_real(monkeypatch)
    monkeypatch.setenv("PORCARIA_NOTIFY_LEVEL", "error")
    calls = _count_popens(monkeypatch)

    assert notify.info("t") is False
    assert notify.success("t") is False
    assert notify.warn("t") is False
    assert notify.error("t") is True
    assert notify.critical("t") is True
    assert calls["n"] == 2


def test_level_none_suppresses_everything(monkeypatch):
    _restore_real(monkeypatch)
    monkeypatch.setenv("PORCARIA_NOTIFY_LEVEL", "none")

    def boom(*a, **kw):  # pragma: no cover - should never fire
        raise AssertionError("notify-send should not spawn at level=none")

    monkeypatch.setattr("porcaria.notify.subprocess.Popen", boom)

    assert notify.info("t") is False
    assert notify.success("t") is False
    assert notify.warn("t") is False
    assert notify.error("t") is False
    assert notify.critical("t") is False


def test_level_critical_only_passes_critical(monkeypatch):
    _restore_real(monkeypatch)
    monkeypatch.setenv("PORCARIA_NOTIFY_LEVEL", "critical")
    calls = _count_popens(monkeypatch)

    assert notify.info("t") is False
    assert notify.success("t") is False
    assert notify.warn("t") is False
    assert notify.error("t") is False
    assert notify.critical("t") is True
    assert calls["n"] == 1


def test_unknown_level_falls_back_to_default(monkeypatch):
    _restore_real(monkeypatch)
    monkeypatch.setenv("PORCARIA_NOTIFY_LEVEL", "bogus")
    calls = _count_popens(monkeypatch)

    # Default is "warning" → info suppressed, success/warn/error all pass.
    assert notify.info("t") is False
    assert notify.success("t") is True
    assert notify.error("t") is True
    assert calls["n"] == 2


def test_send_default_level_is_info(monkeypatch):
    """Direct notify.send() without level=… uses level='info'."""
    _restore_real(monkeypatch)
    monkeypatch.delenv("PORCARIA_NOTIFY_LEVEL", raising=False)
    calls = _count_popens(monkeypatch)

    assert notify.send("t", "b") is False  # info under default (warning) threshold

    monkeypatch.setenv("PORCARIA_NOTIFY_LEVEL", "info")
    assert notify.send("t", "b") is True
    assert calls["n"] == 1


def test_success_sits_at_warning_level(monkeypatch):
    """notify.success is gated identically to notify.warn (both at 'warning')."""
    _restore_real(monkeypatch)
    monkeypatch.setenv("PORCARIA_NOTIFY_LEVEL", "warning")
    calls = _count_popens(monkeypatch)

    assert notify.success("Done", "Thing worked") is True
    assert calls["n"] == 1

    # Bump to error → success drops out, warn drops out too.
    monkeypatch.setenv("PORCARIA_NOTIFY_LEVEL", "error")
    assert notify.success("Done", "Thing worked") is False
    assert notify.warn("huh", "x") is False
    assert calls["n"] == 1
