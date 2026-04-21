"""Speaker sink: synthesize the transcript via the active TTS and play it aloud."""
from __future__ import annotations

import logging

from porcaria.audio import player
from porcaria.config.schema import Config
from porcaria.providers import get_tts
from porcaria.sinks.base import DictationContext, SinkResult

log = logging.getLogger(__name__)


class SpeakerSink:
    name = "speaker"

    def __init__(self, cfg: Config, tts_name: str) -> None:
        self._cfg = cfg
        self._tts_name = tts_name

    def system_prompt(self, ctx: DictationContext) -> str | None:
        return None

    def handle(self, transcript: str, llm_output: str | None) -> SinkResult:
        text = (llm_output if llm_output is not None else transcript).strip()
        if not text:
            return SinkResult(ok=False, message="no text to speak")
        try:
            tts = get_tts(self._cfg, self._tts_name)
        except Exception as e:  # noqa: BLE001
            return SinkResult(ok=False, message=f"TTS provider unavailable: {e}")
        try:
            wav = tts.synth(text)
        except Exception as e:  # noqa: BLE001
            log.warning("speaker sink synth failed: %s", e)
            return SinkResult(ok=False, message=f"synth failed: {e}")
        if not player.any_player_available():
            return SinkResult(ok=False, message="no audio player found")
        if not player.play_bytes(wav):
            return SinkResult(ok=False, message="audio player failed")
        return SinkResult(ok=True, message=f"spoke {len(text)} chars via {self._tts_name}")
