from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from porcaria.config.schema import KokoroCfg
from porcaria.tts import kokoro_download as kd
from porcaria.tts.kokoro_download import (
    KokoroAssetError,
    ensure_kokoro_assets,
    ensure_kokoro_model,
    ensure_kokoro_voices,
)


class _FakeResp:
    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None, raise_after: int | None = None):
        self._chunks = chunks
        self.headers = headers or {}
        self._raise_after = raise_after

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self, chunk_size: int = 1):  # noqa: ARG002
        for i, chunk in enumerate(self._chunks):
            if self._raise_after is not None and i == self._raise_after:
                raise httpx.ReadError("simulated mid-stream failure")
            yield chunk


def _make_cfg(tmp_path: Path, *, payload_model: bytes, payload_voices: bytes) -> KokoroCfg:
    """Build a KokoroCfg pointing at tmp_path with min_bytes/hashes matching the fake payload."""
    return KokoroCfg(
        model_path=str(tmp_path / "kokoro.onnx"),
        voices_path=str(tmp_path / "voices.bin"),
        model_url="https://example.invalid/model",
        voices_url="https://example.invalid/voices",
        model_sha256=hashlib.sha256(payload_model).hexdigest(),
        voices_sha256=hashlib.sha256(payload_voices).hexdigest(),
    )


def _patch_stream(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, _FakeResp],
) -> list[str]:
    """Replace httpx.stream with a fake returning a per-URL fake response.

    Returns a list that gets populated with each requested URL, so tests can
    assert on call ordering / call counts.
    """
    calls: list[str] = []

    @contextmanager
    def fake_stream(method: str, url: str, **_kwargs):  # noqa: ARG001
        calls.append(url)
        if url not in responses:
            raise AssertionError(f"unexpected download URL: {url}")
        yield responses[url]

    monkeypatch.setattr(kd.httpx, "stream", fake_stream)
    return calls


def _shrink_min_bytes(monkeypatch: pytest.MonkeyPatch, *, model: int = 1, voices: int = 1) -> None:
    """Lower the sanity floors so tiny test payloads pass."""
    monkeypatch.setattr(kd, "_MIN_MODEL_BYTES", model)
    monkeypatch.setattr(kd, "_MIN_VOICES_BYTES", voices)


def test_happy_path_downloads_both(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_bytes = b"fake model payload" * 64
    voices_bytes = b"fake voices payload" * 16
    cfg = _make_cfg(tmp_path, payload_model=model_bytes, payload_voices=voices_bytes)
    _shrink_min_bytes(monkeypatch)
    _patch_stream(
        monkeypatch,
        {
            cfg.model_url: _FakeResp([model_bytes], headers={"content-length": str(len(model_bytes))}),
            cfg.voices_url: _FakeResp([voices_bytes], headers={"content-length": str(len(voices_bytes))}),
        },
    )

    model_path, voices_path = ensure_kokoro_assets(cfg)

    assert model_path.read_bytes() == model_bytes
    assert voices_path.read_bytes() == voices_bytes
    assert not model_path.with_suffix(".onnx.partial").exists()


def test_files_already_present_no_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_bytes = b"existing model"
    voices_bytes = b"existing voices"
    cfg = _make_cfg(tmp_path, payload_model=model_bytes, payload_voices=voices_bytes)
    _shrink_min_bytes(monkeypatch)
    Path(cfg.model_path).write_bytes(model_bytes)
    Path(cfg.voices_path).write_bytes(voices_bytes)

    calls = _patch_stream(monkeypatch, {})  # no URLs allowed

    ensure_kokoro_assets(cfg)

    assert calls == []


def test_hash_mismatch_triggers_redownload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # File on disk has wrong content; hash of the *expected* payload is pinned.
    good_model = b"canonical model"
    good_voices = b"canonical voices"
    cfg = _make_cfg(tmp_path, payload_model=good_model, payload_voices=good_voices)
    _shrink_min_bytes(monkeypatch)
    # Pre-seed the destination with bad data.
    Path(cfg.model_path).write_bytes(b"corrupt")
    Path(cfg.voices_path).write_bytes(good_voices)  # voices are fine

    _patch_stream(
        monkeypatch,
        {cfg.model_url: _FakeResp([good_model], headers={"content-length": str(len(good_model))})},
    )

    ensure_kokoro_assets(cfg)
    assert Path(cfg.model_path).read_bytes() == good_model


def test_truncated_response_raises_and_leaves_no_final_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_bytes = b"ok"  # only 2 bytes
    voices_bytes = b"voices"
    cfg = _make_cfg(tmp_path, payload_model=model_bytes, payload_voices=voices_bytes)
    # Set the min floor above the payload so the download fails the size check.
    monkeypatch.setattr(kd, "_MIN_MODEL_BYTES", 1024)
    monkeypatch.setattr(kd, "_MIN_VOICES_BYTES", 1)
    _patch_stream(
        monkeypatch,
        {cfg.model_url: _FakeResp([model_bytes], headers={"content-length": str(len(model_bytes))})},
    )

    with pytest.raises(KokoroAssetError, match="truncated"):
        ensure_kokoro_assets(cfg)

    assert not Path(cfg.model_path).exists()
    assert not Path(str(cfg.model_path) + ".partial").exists()


def test_mid_stream_error_leaves_no_final_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_bytes = b"chunk-a"
    voices_bytes = b"voices"
    cfg = _make_cfg(tmp_path, payload_model=model_bytes, payload_voices=voices_bytes)
    _shrink_min_bytes(monkeypatch)
    _patch_stream(
        monkeypatch,
        {
            cfg.model_url: _FakeResp([b"chunk-a", b"chunk-b"], raise_after=1),
        },
    )

    with pytest.raises(KokoroAssetError, match="download of model failed"):
        ensure_kokoro_assets(cfg)

    assert not Path(cfg.model_path).exists()
    assert not Path(str(cfg.model_path) + ".partial").exists()


def test_auto_download_disabled_raises_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _make_cfg(tmp_path, payload_model=b"x", payload_voices=b"y")
    cfg = cfg.model_copy(update={"auto_download": False})
    _shrink_min_bytes(monkeypatch)
    _patch_stream(monkeypatch, {})  # nothing should be fetched

    with pytest.raises(KokoroAssetError, match="auto_download is disabled"):
        ensure_kokoro_assets(cfg)


def test_force_redownloads_even_when_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    good_model = b"freshly downloaded model"
    good_voices = b"freshly downloaded voices"
    cfg = _make_cfg(tmp_path, payload_model=good_model, payload_voices=good_voices)
    _shrink_min_bytes(monkeypatch)
    # Pre-seed with the correct content — hash matches, would normally skip.
    Path(cfg.model_path).write_bytes(good_model)
    Path(cfg.voices_path).write_bytes(good_voices)

    calls = _patch_stream(
        monkeypatch,
        {
            cfg.model_url: _FakeResp([good_model], headers={"content-length": str(len(good_model))}),
            cfg.voices_url: _FakeResp([good_voices], headers={"content-length": str(len(good_voices))}),
        },
    )

    ensure_kokoro_assets(cfg, force=True)
    assert sorted(calls) == sorted([cfg.model_url, cfg.voices_url])


def test_empty_sha_skips_hash_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_bytes = b"custom quantization"
    voices_bytes = b"custom voices"
    cfg = _make_cfg(tmp_path, payload_model=model_bytes, payload_voices=voices_bytes)
    # User points at a custom model; disables hash pin by setting it to "".
    cfg = cfg.model_copy(update={"model_sha256": "", "voices_sha256": ""})
    _shrink_min_bytes(monkeypatch)
    _patch_stream(
        monkeypatch,
        {
            cfg.model_url: _FakeResp([model_bytes], headers={"content-length": str(len(model_bytes))}),
            cfg.voices_url: _FakeResp([voices_bytes], headers={"content-length": str(len(voices_bytes))}),
        },
    )

    ensure_kokoro_assets(cfg)
    assert Path(cfg.model_path).read_bytes() == model_bytes


def test_ensure_kokoro_model_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_bytes = b"model-only fetch"
    voices_bytes = b"unused-in-this-test"
    cfg = _make_cfg(tmp_path, payload_model=model_bytes, payload_voices=voices_bytes)
    _shrink_min_bytes(monkeypatch)
    calls = _patch_stream(
        monkeypatch,
        {cfg.model_url: _FakeResp([model_bytes], headers={"content-length": str(len(model_bytes))})},
    )

    path = ensure_kokoro_model(cfg)
    assert path == Path(cfg.model_path)
    assert path.read_bytes() == model_bytes
    assert calls == [cfg.model_url]
    assert not Path(cfg.voices_path).exists()


def test_ensure_kokoro_voices_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_bytes = b"unused-in-this-test"
    voices_bytes = b"voices-only fetch"
    cfg = _make_cfg(tmp_path, payload_model=model_bytes, payload_voices=voices_bytes)
    _shrink_min_bytes(monkeypatch)
    calls = _patch_stream(
        monkeypatch,
        {cfg.voices_url: _FakeResp([voices_bytes], headers={"content-length": str(len(voices_bytes))})},
    )

    path = ensure_kokoro_voices(cfg)
    assert path == Path(cfg.voices_path)
    assert path.read_bytes() == voices_bytes
    assert calls == [cfg.voices_url]
    assert not Path(cfg.model_path).exists()


def test_hash_mismatch_on_download_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Server returns bytes whose hash doesn't match the pinned value.
    cfg = _make_cfg(tmp_path, payload_model=b"expected model", payload_voices=b"expected voices")
    _shrink_min_bytes(monkeypatch)
    _patch_stream(
        monkeypatch,
        {cfg.model_url: _FakeResp([b"TAMPERED PAYLOAD"], headers={"content-length": "16"})},
    )

    with pytest.raises(KokoroAssetError, match="sha256 mismatch"):
        ensure_kokoro_assets(cfg)

    assert not Path(cfg.model_path).exists()
    assert not Path(str(cfg.model_path) + ".partial").exists()
