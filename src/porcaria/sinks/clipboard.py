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

        # wl-copy keeps a daemonized child alive to serve Wayland paste requests.
        # waiting on it would hang; we just pipe input and let it detach.
        if argv[0] == "wl-copy":
            return _pipe_and_detach(argv, text)

        # xclip, xsel, pbcopy exit promptly — short blocking wait is fine.
        try:
            proc = subprocess.run(
                argv,
                input=text.encode("utf-8"),
                timeout=5,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            return SinkResult(ok=False, message=f"clipboard write failed: {e}")
        if proc.returncode != 0:
            return SinkResult(
                ok=False,
                message=f"clipboard tool exited {proc.returncode}: {proc.stderr.decode(errors='replace')[:200]}",
            )
        return SinkResult(ok=True, message=f"copied {len(text)} chars via {argv[0]}")


def _pipe_and_detach(argv: list[str], text: str) -> SinkResult:
    """Spawn the clipboard tool, write stdin, close it, and return without
    waiting. Suitable for wl-copy which daemonizes to serve the Wayland
    clipboard selection."""
    try:
        proc = subprocess.Popen(  # noqa: S603
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return SinkResult(ok=False, message=f"clipboard spawn failed: {e}")
    try:
        assert proc.stdin is not None
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()
    except (BrokenPipeError, OSError) as e:
        return SinkResult(ok=False, message=f"clipboard write failed: {e}")
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
