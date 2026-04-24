"""Dictation orchestrator. Wraps capture + ASR + LLM + sink routing."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any

import httpx

from porcaria import live_state, notify
from porcaria.audio import player
from porcaria.capture import recorder
from porcaria.capture.recorder import RecorderUnavailable
from porcaria.config.schema import Config
from porcaria.pipeline.clean import clean as clean_transcription
from porcaria.pipeline.summarize import summarize_for_speech
from porcaria.providers import get_asr, get_llm, get_tts
from porcaria.sinks.base import DictationContext, SinkResult
from porcaria.sinks.clipboard import ClipboardSink
from porcaria.sinks.fazerei import FazereiSink
from porcaria.sinks.quick_note import QuickNoteSink
from porcaria.sinks.speaker import SpeakerSink

log = logging.getLogger(__name__)
_TIMING = os.environ.get("PORCARIA_TIMING") == "1"


def _stage(label: str, t0: float) -> float:
    now = time.monotonic()
    if _TIMING:
        log.info("[timing] %s: %.3fs", label, now - t0)
    return now

_START_TIME_KEY = "start_ns"

_VALID_ROUTES = {"default", "task"}
_VALID_SINKS = {"clipboard", "note", "speaker"}


def _record_start_file() -> Any:
    from porcaria import paths

    return paths.runtime_dir() / "dictation.start_ns"


def _parse_sinks(raw: str | list[str] | None) -> list[str]:
    """Parse a comma-separated sinks string or list into a deduped, validated list.
    Returns [] for None / empty input — callers decide what to do with an empty
    resolution (substitute a profile default, warn the user, etc.)."""
    if raw is None:
        return []
    parts = raw if isinstance(raw, list) else [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p in seen:
            continue
        if p not in _VALID_SINKS:
            raise ValueError(f"unknown sink {p!r}; valid: {sorted(_VALID_SINKS)}")
        seen.add(p)
        out.append(p)
    return out


def start_recording(cfg: Config) -> dict:
    """Start ffmpeg recording. Returns daemon-facing summary.

    Intentionally takes no routing/cleanup flags — those are decided at stop
    time. The start press just begins capture; you pick what to *do* with the
    transcript when you stop."""
    if recorder.is_recording():
        return {"status": "already_recording"}
    try:
        pid = recorder.start(
            sample_rate=cfg.capture.sample_rate,
            mono=cfg.capture.mono,
            pulse_source=cfg.capture.pulse_source,
            max_duration_s=cfg.capture.timeout_seconds,
        )
    except RecorderUnavailable as e:
        notify.error("Dictation unavailable", str(e))
        return {"status": "recorder_unavailable", "error": str(e)}
    except Exception as e:
        notify.error("Dictation failed to start", str(e))
        raise
    _record_start_file().write_text(str(time.time_ns()))
    live_state.set_recording(True)
    notify.send(
        "Dictation recording",
        "Toggle the key again to stop.",
        urgency="normal",
        icon="dialog-information",
    )
    return {"status": "recording", "pid": pid}


def stop_and_process(
    cfg: Config,
    *,
    clean: bool = False,
    route: str = "default",
    sinks: str | list[str] | None = None,
    profile_name: str | None = None,
) -> dict:
    """Stop recording, transcribe, and dispatch.

    `route` is the processing pipeline:
      - "default" → no extra processing; hand off to sinks.
      - "task"    → LLM-interprets the transcript as a fazerei command and runs it.

    `sinks` is the comma-separated list of write destinations:
      - "clipboard", "note" (quick-note file), "speaker" (TTS read-back).
      - Combine with commas, e.g. "clipboard,note" or "clipboard,speaker".
      - None → fall back to the active profile's `sinks` list. An empty
        resolution triggers a console + desktop warning.

    `route` and `sinks` are orthogonal: any route can coexist with any sinks. The
    task route still does its own LLM interpretation on the raw transcript, but
    sinks fire alongside.
    """
    if not recorder.is_recording():
        return {"status": "not_recording"}

    prof = cfg.profile(profile_name)
    if sinks is None:
        sinks = list(prof.sinks)
    sinks_resolved = _parse_sinks(sinks)
    if not sinks_resolved:
        msg = (
            f"No sinks configured for profile {cfg.active_profile!r}; "
            "transcript will not be delivered anywhere."
        )
        log.warning(msg)
        notify.warn("Dictation has no sinks", msg)
    if route not in _VALID_ROUTES:
        raise ValueError(f"unknown route {route!r}; valid: {sorted(_VALID_ROUTES)}")

    t_stop_start = time.monotonic()
    start_ns = _read_start_ns()
    try:
        wav = recorder.stop()
    finally:
        live_state.set_recording(False)
    t_after_stop = _stage("recorder.stop", t_stop_start)
    notify.info("Dictation transcribing", f"{len(wav)//1024} KB queued…")
    asr = get_asr(cfg, prof.asr)
    t_before_asr = time.monotonic()
    try:
        with live_state.phase("transcribing"):
            transcript = asr.transcribe(wav)
    except httpx.ConnectError as e:
        # Most common cause of "I recorded but nothing pasted": the ASR server isn't up.
        msg = (
            f"ASR server '{prof.asr}' unreachable — start it with "
            "`porcaria serve all` (or `porcaria daemon` → toggle servers)."
        )
        notify.error("ASR server unreachable", msg)
        log.warning("asr.transcribe connect failed: %s", e)
        return {"status": "asr_unreachable", "error": str(e), "provider": prof.asr}
    except Exception as e:
        notify.error("Transcription failed", f"{prof.asr}: {e}")
        raise
    t_after_asr = _stage("asr.transcribe", t_before_asr)
    if not transcript.strip():
        notify.warn("No speech detected", "Your transcript was empty.")
        return {"status": "empty_transcript"}

    llm_output: str | None = None
    if clean and route != "task":
        # --clean: LLM cleanup for text that reaches sinks. Skipped for the task
        # route because the task pipeline has its own interpretation LLM call.
        try:
            with live_state.phase("cleaning"):
                llm_output = clean_transcription(get_llm(cfg, prof.llm), transcript)
        except Exception as e:
            log.warning("cleanup failed; using raw transcript: %s", e)
            notify.warn("AI cleanup skipped", "Using raw transcription.")

    ctx = DictationContext(now=datetime.now(), profile=prof.asr + "/" + prof.llm, extras={})
    sink_results: list[dict] = []

    # Route processing. Task runs on the raw transcript (its LLM handles phrasing).
    if route == "task":
        res = _handle_fazerei(cfg, transcript, prof_llm=prof.llm, tts_name=prof.tts, ctx=ctx)
        sink_results.append({"route": "task", **res.__dict__})

    # Sink fanout, orthogonal to route. Sinks receive the cleaned text when --clean is set.
    text_for_sinks = llm_output if llm_output is not None else transcript
    cleaned_arg = text_for_sinks if clean else None
    t_sinks_start = time.monotonic()
    for name in sinks_resolved:
        if name == "clipboard":
            r = ClipboardSink(cfg.sinks.clipboard).handle(transcript, cleaned_arg)
        elif name == "note":
            r = QuickNoteSink(cfg.sinks.quick_note).handle(transcript, cleaned_arg)
        elif name == "speaker":
            with live_state.phase("speaking"):
                r = SpeakerSink(cfg, prof.tts).handle(transcript, cleaned_arg)
        else:  # should be unreachable — _parse_sinks already validated
            raise ValueError(f"unhandled sink {name!r}")
        if not r.ok:
            notify.error(f"Sink {name} failed", r.message)
        sink_results.append({"sink": name, **r.__dict__})
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
    with live_state.phase("task"):
        sink = FazereiSink(cfg.sinks.fazerei)
        system = sink.system_prompt(ctx) or ""
        llm = get_llm(cfg, prof_llm)
        try:
            llm_output = llm.chat(system, transcript, temperature=0.0)
        except Exception as e:
            notify.error("Task LLM failed", str(e))
            return SinkResult(ok=False, message=f"LLM call failed: {e}")

        result = sink.handle(transcript, llm_output)

        # Speak query results if any.
        if result.artifact and any(v in result.message for v in ("queried",)):
            try:
                speak_text = summarize_for_speech(llm, result.artifact, original_question=transcript)
                _speak(cfg, tts_name, speak_text)
                notify.info("Task query result", speak_text[:400])
            except Exception as e:
                log.warning("summarize/speak failed: %s", e)

        if result.ok:
            notify.success("Task complete", result.message)
        else:
            notify.error("Task failed", result.message)
        return result


def _speak(cfg: Config, tts_name: str, text: str) -> None:
    if not text.strip():
        return
    try:
        tts = get_tts(cfg, tts_name)
    except Exception:
        return
    with live_state.phase("speaking"):
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


def _successful_destinations(sink_results: list[dict]) -> list[str]:
    """Names of destinations (sinks + task route) that successfully delivered.

    Each sink appends ``{"sink": name, "ok": bool, ...}``; the task route
    appends ``{"route": "task", "ok": bool, ...}``. We list only those with
    ``ok == True`` — failed destinations get their own error notifications."""
    dests: list[str] = []
    for r in sink_results:
        if not r.get("ok"):
            continue
        if r.get("route") == "task":
            dests.append("task")
        elif "sink" in r:
            dests.append(r["sink"])
    return dests


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
    destinations = _successful_destinations(sink_results)
    if destinations:
        # Describe what actually happened to the transcript:
        # "Dictation → clipboard", "Cleaned dictation → clipboard + note",
        # "Dictation → task + clipboard", etc.
        prefix = "Cleaned dictation" if llm_output is not None else "Dictation"
        summary = f"{prefix} → {' + '.join(destinations)}"
        notify.success(
            summary,
            f"{char_count} chars • "
            + (f"rec {recording_ms / 1000:.1f}s, " if recording_ms is not None else "")
            + f"asr {t_asr:.2f}s",
        )
    # Nothing delivered (no sinks / all failed / task failed with no sinks):
    # the "no sinks configured" warning or per-sink error notifications have
    # already told the user; don't stack a misleading success on top.
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
    route: str = "default",
    sinks: str | list[str] | None = None,
    profile_name: str | None = None,
) -> dict:
    """Start recording if stopped; stop + process if recording.

    Flags on the start press are ignored for behavior — start just begins
    capture. Flags on the stop press determine clean / route / sinks, so the
    user decides at stop time how to handle the transcript.

    Validation is eager, however: a bogus --sinks or --route raises even on a
    start press, so the user sees their typo before recording for 10 minutes."""
    if route not in _VALID_ROUTES:
        raise ValueError(f"unknown route {route!r}; valid: {sorted(_VALID_ROUTES)}")
    _parse_sinks(sinks)  # raises on invalid sink names

    if recorder.is_recording():
        return stop_and_process(
            cfg, clean=clean, route=route, sinks=sinks, profile_name=profile_name
        )
    return start_recording(cfg)
