"""Clipboard sink. Auto-detects wl-copy (Wayland), xclip/xsel (X11), pbcopy (macOS)."""
from __future__ import annotations

import subprocess

from porcaria.config.schema import ClipboardCfg
from porcaria.shellout import which
from porcaria.sinks.base import DictationContext, SinkResult


class ClipboardSink:
    name = "clipboard"

    def __init__(self, cfg: ClipboardCfg) -> None:
        self._cfg = cfg

    def system_prompt(self, ctx: DictationContext) -> str | None:
        return None  # clipboard is a pure terminal sink; no LLM pass

    def handle(self, transcript: str, llm_output: str | None) -> SinkResult:
        text = (llm_output if llm_output is not None else transcript).rstrip("\n")
        argv = _resolve_argv(self._cfg.tool)
        if argv is None:
            return SinkResult(ok=False, message="no clipboard tool found (wl-copy/xclip/xsel/pbcopy)")
        try:
            proc = subprocess.run(argv, input=text.encode("utf-8"), timeout=5, capture_output=True)
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            return SinkResult(ok=False, message=f"clipboard write failed: {e}")
        if proc.returncode != 0:
            return SinkResult(
                ok=False,
                message=f"clipboard tool exited {proc.returncode}: {proc.stderr.decode(errors='replace')[:200]}",
            )
        return SinkResult(ok=True, message=f"copied {len(text)} chars via {argv[0]}")


def _resolve_argv(tool: str) -> list[str] | None:
    if tool != "auto":
        return [tool] if which(tool) else None
    for candidate in ("wl-copy", "xclip", "xsel", "pbcopy"):
        if which(candidate):
            if candidate == "xclip":
                return ["xclip", "-selection", "clipboard"]
            if candidate == "xsel":
                return ["xsel", "--clipboard", "--input"]
            return [candidate]
    return None
