"""Dictation orchestrator. Wraps capture + ASR + LLM + sink routing."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any

from porcaria import notify
from porcaria.audio import player
from porcaria.capture import recorder
from porcaria.config.schema import Config
from porcaria.pipeline.clean import clean as clean_transcription
from porcaria.pipeline.summarize import summarize_for_speech
from porcaria.providers import get_asr, get_llm, get_tts
from porcaria.sinks.base import DictationContext, SinkResult
from porcaria.sinks.clipboard import ClipboardSink
from porcaria.sinks.fazerei import FazereiSink
from porcaria.sinks.quick_note import QuickNoteSink

log = logging.getLogger(__name__)
_TIMING = os.environ.get("PORCARIA_TIMING") == "1"


def _stage(label: str, t0: float) -> float:
    now = time.monotonic()
    if _TIMING:
        log.info("[timing] %s: %.3fs", label, now - t0)
    return now

_START_TIME_KEY = "start_ns"


def _record_start_file() -> Any:
    from porcaria import paths

    return paths.runtime_dir() / "dictation.start_ns"


def start_recording(cfg: Config) -> dict:
    """Start ffmpeg recording. Returns daemon-facing summary."""
    if recorder.is_recording():
        return {"status": "already_recording"}
    pid = recorder.start(
        sample_rate=cfg.capture.sample_rate,
        mono=cfg.capture.mono,
        pulse_source=cfg.capture.pulse_source,
        max_duration_s=cfg.capture.timeout_seconds,
    )
    _record_start_file().write_text(str(time.time_ns()))
    notify.send(
        "Dictation",
        "Recording… toggle the key again to stop.",
        urgency="normal",
        icon="dialog-information",
    )
    return {"status": "recording", "pid": pid}


def stop_and_process(
    cfg: Config,
    *,
    clean: bool = False,
    note: bool = False,
    route: str = "auto",
    profile_name: str | None = None,
) -> dict:
    """Stop recording and route the transcript through the selected sink(s).

    route:
      - "auto"      → clipboard (with --note adding quick_note alongside)
      - "clipboard" → clipboard only
      - "note"      → quick_note only (skip clipboard)
      - "task"      → fazerei voice-command flow (bypasses clipboard & note)
    """
    if not recorder.is_recording():
        return {"status": "not_recording"}

    t_stop_start = time.monotonic()
    start_ns = _read_start_ns()
    wav = recorder.stop()
    t_after_stop = _stage("recorder.stop", t_stop_start)
    notify.info("Dictation", f"Transcribing ({len(wav)//1024} KB)…")

    prof = cfg.profile(profile_name)
    asr = get_asr(cfg, prof.asr)
    t_before_asr = time.monotonic()
    transcript = asr.transcribe(wav)
    t_after_asr = _stage("asr.transcribe", t_before_asr)
    if not transcript.strip():
        notify.warn("Dictation", "No speech detected")
        return {"status": "empty_transcript"}

    llm_output: str | None = None
    if clean and route != "task":
        # Standard --clean flag: LLM cleanup for prose sinks.
        try:
            llm_output = clean_transcription(get_llm(cfg, prof.llm), transcript)
        except Exception as e:
            log.warning("cleanup failed; using raw transcript: %s", e)
            notify.warn("Dictation", "AI cleanup failed, using raw transcription")

    ctx = DictationContext(now=datetime.now(), profile=prof.asr + "/" + prof.llm, extras={})
    sink_results: list[dict] = []

    if route == "task":
        res = _handle_fazerei(cfg, transcript, prof_llm=prof.llm, tts_name=prof.tts, ctx=ctx)
        sink_results.append({"sink": "fazerei", **res.__dict__})
        return _finish(
            start_ns,
            t_stop_start,
            transcript,
            sink_results,
            t_stop=t_after_stop - t_stop_start,
            t_asr=t_after_asr - t_before_asr,
            wav_bytes=len(wav),
        )

    text_for_sinks = llm_output if llm_output is not None else transcript

    t_sinks_start = time.monotonic()
    if route in ("auto", "clipboard") and route != "note":
        r = ClipboardSink(cfg.sinks.clipboard).handle(transcript, text_for_sinks if clean else None)
        sink_results.append({"sink": "clipboard", **r.__dict__})
    if note or route == "note":
        r = QuickNoteSink(cfg.sinks.quick_note).handle(transcript, text_for_sinks if clean else None)
        sink_results.append({"sink": "quick_note", **r.__dict__})
    _stage("sinks", t_sinks_start)

    return _finish(
        start_ns,
        t_stop_start,
        transcript,
        sink_results,
        llm_output=llm_output,
        t_stop=t_after_stop - t_stop_start,
        t_asr=t_after_asr - t_before_asr,
        t_sinks=time.monotonic() - t_sinks_start,
        wav_bytes=len(wav),
    )


# ---------- internals ----------


def _handle_fazerei(
    cfg: Config,
    transcript: str,
    *,
    prof_llm: str,
    tts_name: str,
    ctx: DictationContext,
) -> SinkResult:
    sink = FazereiSink(cfg.sinks.fazerei)
    system = sink.system_prompt(ctx) or ""
    llm = get_llm(cfg, prof_llm)
    try:
        llm_output = llm.chat(system, transcript, temperature=0.0)
    except Exception as e:
        notify.warn("Fazerei Buddy", f"LLM call failed: {e}")
        return SinkResult(ok=False, message=f"LLM call failed: {e}")

    result = sink.handle(transcript, llm_output)

    # Speak query results if any.
    if result.artifact and any(v in result.message for v in ("queried",)):
        try:
            speak_text = summarize_for_speech(llm, result.artifact, original_question=transcript)
            _speak(cfg, tts_name, speak_text)
            notify.info("Fazerei Buddy", speak_text[:400])
        except Exception as e:
            log.warning("summarize/speak failed: %s", e)

    if result.ok:
        notify.info("Fazerei Buddy", result.message)
    else:
        notify.warn("Fazerei Buddy", result.message)
    return result


def _speak(cfg: Config, tts_name: str, text: str) -> None:
    if not text.strip():
        return
    try:
        tts = get_tts(cfg, tts_name)
    except Exception:
        return
    try:
        wav = tts.synth(text)
    except Exception as e:
        log.warning("tts synth failed: %s", e)
        return
    if not player.any_player_available():
        return
    player.play_bytes(wav)


def _read_start_ns() -> int | None:
    p = _record_start_file()
    if not p.exists():
        return None
    try:
        val = int(p.read_text().strip())
        p.unlink(missing_ok=True)
        return val
    except (ValueError, OSError):
        return None


def _finish(
    start_ns: int | None,
    t_stop_start: float,
    transcript: str,
    sink_results: list[dict],
    *,
    llm_output: str | None = None,
    t_stop: float = 0.0,
    t_asr: float = 0.0,
    t_sinks: float = 0.0,
    wav_bytes: int = 0,
) -> dict:
    total_ms = (time.time_ns() - start_ns) // 1_000_000 if start_ns else None
    # "processing" = after the user hit stop, excluding the recording duration.
    processing_ms = int((time.monotonic() - t_stop_start) * 1000)
    recording_ms = (total_ms - processing_ms) if total_ms is not None else None
    char_count = len(transcript)
    notify.info(
        "Dictation",
        f"Done • {char_count} chars • "
        + (f"rec {recording_ms / 1000:.1f}s, " if recording_ms is not None else "")
        + f"asr {t_asr:.2f}s",
    )
    return {
        "status": "processed",
        "transcript": transcript,
        "llm_output": llm_output,
        "sinks": sink_results,
        "timings": {
            "recording_ms": recording_ms,
            "processing_ms": processing_ms,
            "stop_ms": int(t_stop * 1000),
            "asr_ms": int(t_asr * 1000),
            "sinks_ms": int(t_sinks * 1000),
            "wav_bytes": wav_bytes,
        },
        "elapsed_ms": total_ms,
    }


def toggle(
    cfg: Config,
    *,
    clean: bool = False,
    note: bool = False,
    route: str = "auto",
    profile_name: str | None = None,
) -> dict:
    """Start recording if stopped; stop+process if recording."""
    if recorder.is_recording():
        return stop_and_process(
            cfg, clean=clean, note=note, route=route, profile_name=profile_name
        )
    return start_recording(cfg)
