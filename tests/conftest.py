"""Shared pytest fixtures.

`_silence_notify` is autouse — every test run gets `porcaria.notify`'s send
functions stubbed to no-ops, so test cases that exercise download paths (or
any other code that calls `notify.send/info/warn/error`) don't spawn real
`notify-send` subprocesses against the developer's desktop. Without this,
running `pytest tests/test_kokoro_download.py` fires ~20 real desktop
notifications including bodies like "kokoro model hash mismatch" that look
exactly like a production failure.

Tests that want to assert on notification payloads can still do so by
monkeypatching the specific function in the module under test (e.g.
`monkeypatch.setattr(kd.notify, "info", spy)`).
"""
from __future__ import annotations

import pytest

from porcaria import notify


@pytest.fixture(autouse=True)
def _silence_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("send", "debug", "info", "success", "warn", "error", "critical"):
        monkeypatch.setattr(notify, name, lambda *args, **kwargs: True)
