"""Fazerei sink: voice → LLM-generated fazerei commands → safe execution."""
from __future__ import annotations

from porcaria.config.schema import FazereiCfg
from porcaria.sinks.base import DictationContext, SinkResult
from porcaria.sinks.fazerei.executor import RunReport


class FazereiSink:
    """Sink that uses an LLM to convert transcripts to fazerei CLI commands.

    The sink doesn't own the LLM call; the dictation pipeline does. The sink
    provides (1) the system prompt and (2) a handler that parses and executes
    the LLM output via shlex.split + subprocess.run — never eval.

    Query (list/show) stdout is placed on SinkResult.artifact so the pipeline
    can decide whether to summarize-and-speak it.
    """

    name = "fazerei"

    def __init__(self, cfg: FazereiCfg) -> None:
        self._cfg = cfg

    def system_prompt(self, ctx: DictationContext) -> str | None:
        from porcaria.sinks.fazerei.prompt import build

        return build(self._cfg)

    def handle(self, transcript: str, llm_output: str | None) -> SinkResult:
        from porcaria.sinks.fazerei.executor import run_commands

        if llm_output is None:
            return SinkResult(ok=False, message="fazerei sink requires LLM output")
        report = run_commands(self._cfg, llm_output)
        return _to_result(report)


def _to_result(report: RunReport) -> SinkResult:
    if report.skipped:
        return SinkResult(ok=False, message="skipped (no task-related intent)")
    if not report.outcomes:
        return SinkResult(ok=False, message="LLM output did not match expected command format")

    ok = report.fail_count == 0
    action = report.action_summary() or "processed"
    message = f"{report.ok_count} {action}"
    if report.fail_count:
        message += f" — {report.fail_count} failed"
    result = SinkResult(ok=ok, message=message)
    if report.query_output:
        result.artifact = report.query_output
    return result


__all__ = ["FazereiSink", "RunReport"]
