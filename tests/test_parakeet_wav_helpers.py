"""Tests for the pure WAV-format helpers in parakeet_server (no torch needed)."""
from __future__ import annotations

import struct

from porcaria.asr.parakeet_server import _find_wav_data_offset, _is_wav_16k_mono_pcm16


def _build_wav(sample_rate: int = 16000, channels: int = 1, bits: int = 16, samples: int = 16) -> bytes:
    """Synthesize a minimal canonical WAV header followed by `samples` zero PCM frames."""
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    pcm = b"\x00\x00" * samples
    data_size = len(pcm)
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, channels, sample_rate, byte_rate, block_align, bits)
    data = struct.pack("<4sI", b"data", data_size) + pcm
    riff_size = 4 + len(fmt) + len(data)
    riff = struct.pack("<4sI4s", b"RIFF", riff_size, b"WAVE")
    return riff + fmt + data


def test_detects_canonical_16k_mono_pcm16():
    wav = _build_wav(sample_rate=16000, channels=1, bits=16)
    assert _is_wav_16k_mono_pcm16(wav)


def test_rejects_wrong_sample_rate():
    assert not _is_wav_16k_mono_pcm16(_build_wav(sample_rate=44100))


def test_rejects_stereo():
    assert not _is_wav_16k_mono_pcm16(_build_wav(channels=2))


def test_rejects_non_pcm16():
    # 24-bit is a perfectly valid uncompressed WAV but not the fast path.
    assert not _is_wav_16k_mono_pcm16(_build_wav(bits=24))


def test_rejects_too_short():
    assert not _is_wav_16k_mono_pcm16(b"RIFF" + b"\x00" * 10)


def test_find_data_offset_matches_header_size():
    wav = _build_wav()
    offset = _find_wav_data_offset(wav)
    assert offset is not None
    assert offset == 44  # canonical 44-byte header
