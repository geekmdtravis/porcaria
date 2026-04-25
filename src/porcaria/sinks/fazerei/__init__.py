"""Fazerei sink: voice → LLM-generated fazerei commands → safe execution."""
from __future__ import annotations

from porcaria.config.schema import FazereiCfg
from porcaria.sinks.base import DictationContext, SinkResult
from porcaria.sinks.fazerei.executor import RunReport

# Cap diagnostics so failure notifications stay readable.
_DIAG_CHARS = 300


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


def run_with_repair(
    cfg: FazereiCfg,
    llm,
    system_prompt: str,
    transcript: str,
) -> tuple[SinkResult, str]:
    """LLM call + parse + execute, with one repair retry on parse failure.

    Returns ``(SinkResult, llm_output)`` — the LLM output is the final attempt's
    raw text, useful for diagnostics on either path.

    The repair retry fires when the first attempt produced zero successful
    commands but did emit something (i.e. the LLM tried but malformed every
    line). It does NOT retry on FAZEREI_SKIP, on partial success, or on
    runtime failures (where the verb was valid but `fazerei` itself returned
    non-zero).
    """
    from porcaria.sinks.fazerei.executor import run_commands

    llm_output = llm.chat(system_prompt, transcript, temperature=0.0)
    report = run_commands(cfg, llm_output)
    if _should_repair(report):
        repair_msg = _build_repair_user_message(transcript, llm_output, report)
        llm_output = llm.chat(system_prompt, repair_msg, temperature=0.0)
        report = run_commands(cfg, llm_output)
    return _to_result(report), llm_output


def _should_repair(report: RunReport) -> bool:
    if report.skipped:
        return False
    if not report.outcomes:
        # Output was non-empty but produced no parsed lines (markdown, prose, etc).
        return True
    if report.ok_count > 0:
        # Partial success — don't burn an LLM call to chase the failed siblings.
        return False
    # All failed. Repair only when at least one failure was a parse/whitelist
    # rejection (verb == ""). Runtime exec failures (verb classified but fazerei
    # returned non-zero) can't be fixed by re-prompting.
    return any(o.verb == "" for o in report.outcomes)


def _build_repair_user_message(transcript: str, prior_output: str, report: RunReport) -> str:
    parts = [
        "Your previous output could not be executed. Re-emit the commands following the OUTPUT FORMAT rules above. Output ONLY fazerei command lines, one per line — no prose, no markdown, no backticks.",
        "",
        f"Original request: {transcript}",
        "",
        "Your previous output:",
        prior_output.strip() or "(empty)",
        "",
    ]
    if report.outcomes:
        parts.append("Per-line errors:")
        for o in report.outcomes:
            parts.append(f"  {o.line!r}: {o.error or 'unknown'}")
    else:
        parts.append(
            "(No lines could be parsed. Each line MUST start with `fazerei ` and a "
            "valid verb: add, edit, done, undone, snooze, rm, list, show, today, next, stats.)"
        )
    return "\n".join(parts)


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
        # Surface what actually went wrong so failure notifications are debuggable.
        failed = [o for o in report.outcomes if not o.ok]
        diag = "; ".join(f"{o.line!r}: {o.error or 'unknown'}" for o in failed)
        if len(diag) > _DIAG_CHARS:
            diag = diag[: _DIAG_CHARS - 1] + "…"
        message += f" ({diag})"
    result = SinkResult(ok=ok, message=message)
    if report.query_output:
        result.artifact = report.query_output
    return result


__all__ = ["FazereiSink", "RunReport", "run_with_repair"]
