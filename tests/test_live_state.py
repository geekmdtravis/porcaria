from __future__ import annotations

import json
import threading

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


def _fake_builder_factory(counter: dict | None = None):
    counter = counter if counter is not None else {"n": 0}

    def build() -> dict:
        counter["n"] += 1
        return {"servers": {"llamacpp": {"ok": True}}, "pid": 999}

    return build, counter


def test_init_writes_initial_status_file(tmp_path):
    build, _ = _fake_builder_factory()
    live_state.init(build_status=build)
    snap = _read_file()
    assert snap["active"] == "idle"
    assert snap["recording"] is False
    assert snap["phase_stack"] == []
    assert snap["busy"] is False
    assert snap["servers"] == {"llamacpp": {"ok": True}}
    assert snap["pid"] == 999


def test_phase_push_pop():
    build, _ = _fake_builder_factory()
    live_state.init(build_status=build)
    with live_state.phase("transcribing"):
        snap = _read_file()
        assert snap["active"] == "transcribing"
        assert snap["phase_stack"] == ["transcribing"]
        assert snap["busy"] is True
    snap = _read_file()
    assert snap["active"] == "idle"
    assert snap["phase_stack"] == []
    assert snap["busy"] is False


def test_phase_cleanup_on_exception():
    build, _ = _fake_builder_factory()
    live_state.init(build_status=build)
    with pytest.raises(RuntimeError):
        with live_state.phase("cleaning"):
            raise RuntimeError("boom")
    snap = _read_file()
    assert snap["active"] == "idle"
    assert snap["phase_stack"] == []


def test_nested_phases_stack_top_wins():
    build, _ = _fake_builder_factory()
    live_state.init(build_status=build)
    with live_state.phase("task"):
        with live_state.phase("speaking"):
            snap = _read_file()
            assert snap["active"] == "speaking"
            assert snap["phase_stack"] == ["task", "speaking"]
        snap = _read_file()
        assert snap["active"] == "task"
        assert snap["phase_stack"] == ["task"]
    snap = _read_file()
    assert snap["active"] == "idle"


def test_recording_dominates_active():
    build, _ = _fake_builder_factory()
    live_state.init(build_status=build)
    live_state.set_recording(True)
    snap = _read_file()
    assert snap["active"] == "recording"
    assert snap["recording"] is True
    assert snap["busy"] is True
    with live_state.phase("transcribing"):
        # recording flag still wins even with stack non-empty
        snap = _read_file()
        assert snap["active"] == "recording"
    live_state.set_recording(False)
    snap = _read_file()
    assert snap["active"] == "idle"


def test_atomic_write_no_partial_clobber(monkeypatch):
    build, _ = _fake_builder_factory()
    live_state.init(build_status=build)
    good = live_state.status_path().read_text()
    # Force the next write to fail after the tmp file would have been staged.
    real_dumps = json.dumps

    def failing_dumps(*a, **kw):
        if kw.get("separators") == (",", ":"):
            raise RuntimeError("simulated serialization failure")
        return real_dumps(*a, **kw)

    monkeypatch.setattr("porcaria.live_state.json.dumps", failing_dumps)
    # Trigger a write; it should swallow / log and leave the file untouched.
    with pytest.raises(RuntimeError):
        with live_state.phase("transcribing"):
            pass
    assert live_state.status_path().read_text() == good


def test_teardown_unlinks_file():
    build, _ = _fake_builder_factory()
    live_state.init(build_status=build)
    assert live_state.status_path().exists()
    live_state.teardown()
    assert not live_state.status_path().exists()


def test_concurrent_phase_threads_end_idle():
    build, _ = _fake_builder_factory()
    live_state.init(build_status=build)
    barrier = threading.Barrier(8)

    def worker(name: str) -> None:
        barrier.wait()
        for _ in range(25):
            with live_state.phase(name):
                pass

    threads = [threading.Thread(target=worker, args=(f"p{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snap = _read_file()
    assert snap["active"] == "idle"
    assert snap["phase_stack"] == []
    assert snap["busy"] is False


def test_snapshot_live_shape():
    build, _ = _fake_builder_factory()
    live_state.init(build_status=build)
    live = live_state.snapshot_live()
    assert set(live.keys()) == {"active", "recording", "phase_stack", "busy", "updated_ns"}
    assert isinstance(live["updated_ns"], int)
