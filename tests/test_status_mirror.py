from __future__ import annotations

import asyncio
import json

import pytest

from porcaria import live_state


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    live_state._reset_for_tests()
    yield
    live_state._reset_for_tests()


def _read_file() -> dict:
    return json.loads(live_state.status_path().read_text())


def test_mirror_file_contains_builder_fields_and_live_fields():
    def build() -> dict:
        return {
            "active_profile": "home",
            "servers": {"llamacpp": {"ok": True}},
            "pid": 42,
        }

    live_state.init(build_status=build)
    snap = _read_file()
    # builder fields
    assert snap["active_profile"] == "home"
    assert snap["servers"]["llamacpp"]["ok"] is True
    assert snap["pid"] == 42
    # live fields merged on top
    assert snap["active"] == "idle"
    assert snap["recording"] is False
    assert "phase_stack" in snap
    assert "busy" in snap
    assert "updated_ns" in snap


def test_refresher_reinvokes_build_status(monkeypatch):
    monkeypatch.setattr(live_state, "_REFRESH_INTERVAL_S", 0.02)

    counter = {"n": 0}

    def build() -> dict:
        counter["n"] += 1
        return {"servers": {"llamacpp": {"ok": counter["n"] > 1}}, "pid": 1}

    async def drive() -> None:
        live_state.init(build_status=build)
        # Allow several refresher ticks.
        await asyncio.sleep(0.12)
        # Cancel gracefully.
        live_state.teardown()

    asyncio.run(drive())

    # init() counts as first call; refresher should have added several more.
    assert counter["n"] >= 3


def test_phase_writes_do_not_block_on_health_probes():
    """Phase transitions reuse the cached base dict — they must not re-invoke build_status."""
    counter = {"n": 0}

    def build() -> dict:
        counter["n"] += 1
        return {"servers": {}, "pid": 1}

    live_state.init(build_status=build)
    baseline = counter["n"]  # 1 after init
    for _ in range(10):
        with live_state.phase("transcribing"):
            pass
    assert counter["n"] == baseline  # no additional rebuilds
