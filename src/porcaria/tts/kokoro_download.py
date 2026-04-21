"""Fetch + verify the Kokoro ONNX model and voices files.

Called by the supervisor before spawning the Kokoro server, and exposed via
`porcaria download tts`. Downloads stream to `<dest>.partial`, verify SHA-256
(when a hash is configured), then atomically rename into place.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from porcaria import notify, paths
from porcaria.config.schema import KokoroCfg

log = logging.getLogger(__name__)

_CHUNK = 1024 * 1024  # 1 MiB
_MIN_MODEL_BYTES = 50 * 1024 * 1024   # sanity floor; real file is ~310 MB
_MIN_VOICES_BYTES = 1 * 1024 * 1024   # sanity floor; real file is ~25 MB


class KokoroAssetError(RuntimeError):
    """Raised when required Kokoro files are missing or invalid and can't be fetched."""


@dataclass(frozen=True)
class _Asset:
    label: str                # "model" | "voices"
    dest: Path
    url: str
    sha256: str               # empty string → skip hash check
    min_bytes: int


def _model_asset(cfg: KokoroCfg) -> _Asset:
    return _Asset(
        label="model",
        dest=paths.expand(cfg.model_path),
        url=cfg.model_url,
        sha256=cfg.model_sha256,
        min_bytes=_MIN_MODEL_BYTES,
    )


def _voices_asset(cfg: KokoroCfg) -> _Asset:
    return _Asset(
        label="voices",
        dest=paths.expand(cfg.voices_path),
        url=cfg.voices_url,
        sha256=cfg.voices_sha256,
        min_bytes=_MIN_VOICES_BYTES,
    )


def ensure_kokoro_assets(cfg: KokoroCfg, *, force: bool = False) -> tuple[Path, Path]:
    """Ensure model + voices files exist at the configured paths.

    Returns the resolved (model_path, voices_path). Raises KokoroAssetError if
    files are missing (or hash-mismatched) and auto_download is disabled, or
    if a download attempt fails.
    """
    model = _model_asset(cfg)
    voices = _voices_asset(cfg)
    for asset in (model, voices):
        _ensure_one(asset, auto_download=cfg.auto_download, force=force)
    return model.dest, voices.dest


def ensure_kokoro_model(cfg: KokoroCfg, *, force: bool = False) -> Path:
    """Ensure only the ONNX model file exists. Always forces auto_download=True
    so this can be called from the explicit CLI download command regardless of
    the config's auto_download setting."""
    asset = _model_asset(cfg)
    _ensure_one(asset, auto_download=True, force=force)
    return asset.dest


def ensure_kokoro_voices(cfg: KokoroCfg, *, force: bool = False) -> Path:
    """Ensure only the voices file exists. Always forces auto_download=True."""
    asset = _voices_asset(cfg)
    _ensure_one(asset, auto_download=True, force=force)
    return asset.dest


def _ensure_one(asset: _Asset, *, auto_download: bool, force: bool) -> None:
    if not force and asset.dest.is_file():
        if _hash_ok(asset.dest, asset.sha256):
            return
        log.warning("kokoro %s at %s failed hash check; re-fetching", asset.label, asset.dest)
        notify.info("porcaria", f"kokoro {asset.label}: hash pin drifted, re-fetching…")
    if not auto_download:
        raise KokoroAssetError(
            f"kokoro {asset.label} missing or invalid at {asset.dest} and auto_download is disabled"
        )
    _download(asset)


def _hash_ok(path: Path, expected: str) -> bool:
    if not expected:
        return True  # verification disabled for this asset
    actual = _sha256_file(path)
    if actual.lower() != expected.lower():
        log.warning("hash mismatch for %s: expected %s, got %s", path, expected, actual)
        return False
    return True


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(asset: _Asset) -> None:
    asset.dest.parent.mkdir(parents=True, exist_ok=True)
    partial = asset.dest.with_suffix(asset.dest.suffix + ".partial")
    partial.unlink(missing_ok=True)

    mb = asset.min_bytes / (1024 * 1024)
    log.info("kokoro: downloading %s from %s", asset.label, asset.url)
    notify.info("porcaria", f"downloading kokoro {asset.label} (~{mb:.0f} MB+)…")

    h = hashlib.sha256()
    written = 0
    try:
        with httpx.stream("GET", asset.url, follow_redirects=True, timeout=60.0) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0)
            next_log = 0.05
            with partial.open("wb") as out:
                for chunk in resp.iter_bytes(chunk_size=_CHUNK):
                    if not chunk:
                        continue
                    out.write(chunk)
                    h.update(chunk)
                    written += len(chunk)
                    if total and written / total >= next_log:
                        log.info(
                            "kokoro %s: %d / %d MB (%.0f%%)",
                            asset.label,
                            written // (1024 * 1024),
                            total // (1024 * 1024),
                            100 * written / total,
                        )
                        next_log += 0.2
    except (httpx.HTTPError, OSError) as e:
        partial.unlink(missing_ok=True)
        notify.warn("porcaria", f"kokoro {asset.label} download failed")
        raise KokoroAssetError(f"download of {asset.label} failed: {e}") from e

    if written < asset.min_bytes:
        partial.unlink(missing_ok=True)
        notify.warn("porcaria", f"kokoro {asset.label} download truncated")
        raise KokoroAssetError(
            f"{asset.label} download truncated: got {written} bytes, need >= {asset.min_bytes}"
        )

    if asset.sha256:
        actual = h.hexdigest()
        if actual.lower() != asset.sha256.lower():
            partial.unlink(missing_ok=True)
            notify.warn("porcaria", f"kokoro {asset.label} hash mismatch")
            raise KokoroAssetError(
                f"{asset.label} sha256 mismatch: expected {asset.sha256}, got {actual}"
            )

    os.replace(partial, asset.dest)
    log.info("kokoro %s ready at %s (%d bytes)", asset.label, asset.dest, written)
    notify.info("porcaria", f"kokoro {asset.label} ready")
