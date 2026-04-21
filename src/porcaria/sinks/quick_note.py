"""Quick-note sink. Writes timestamped transcript files under a configured directory."""
from __future__ import annotations

from datetime import datetime

from porcaria import paths
from porcaria.config.schema import QuickNoteCfg
from porcaria.sinks.base import DictationContext, SinkResult


class QuickNoteSink:
    name = "quick_note"

    def __init__(self, cfg: QuickNoteCfg) -> None:
        self._cfg = cfg

    def system_prompt(self, ctx: DictationContext) -> str | None:
        return None

    def handle(self, transcript: str, llm_output: str | None) -> SinkResult:
        text = llm_output if llm_output is not None else transcript
        target_dir = paths.expand(self._cfg.dir)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return SinkResult(ok=False, message=f"could not create notes dir {target_dir}: {e}")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = target_dir / f"quick-note-{stamp}.txt"
        try:
            path.write_text(text)
        except OSError as e:
            return SinkResult(ok=False, message=f"could not write note {path}: {e}")
        return SinkResult(ok=True, message=f"saved {path.name}", artifact=str(path))
