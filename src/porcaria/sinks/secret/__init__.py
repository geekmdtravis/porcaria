"""Secret sink: voice → LLM-selected pass entry → clipboard."""
from __future__ import annotations

import re

from porcaria.config.schema import SecretCfg
from porcaria.sinks.base import DictationContext, SinkResult
from porcaria.sinks.secret.executor import SecretOutcome, SecretReport

_DIAG_CHARS = 300
_SECRET_REQUEST_RE = re.compile(
    r"\b(password|passphrase|secret|credential|credentials|login|token|api key|key)\b",
    re.IGNORECASE,
)


class SecretSink:
    name = "secret"

    def __init__(self, cfg: SecretCfg) -> None:
        self._cfg = cfg

    def system_prompt(self, ctx: DictationContext) -> str | None:
        from porcaria.sinks.secret.prompt import build

        return build(self._cfg)

    def handle(self, transcript: str, llm_output: str | None) -> SinkResult:
        from porcaria.sinks.secret.executor import run_selection

        if llm_output is None:
            return SinkResult(ok=False, message="secret sink requires LLM output")
        return _to_result(run_selection(self._cfg, llm_output))


def run_with_repair(
    cfg: SecretCfg,
    llm,
    system_prompt: str,
    transcript: str,
) -> tuple[SinkResult, str]:
    from porcaria.sinks.secret.executor import run_selection

    llm_output = llm.chat(system_prompt, transcript, temperature=0.0)
    report = run_selection(cfg, llm_output)
    report = _reinterpret_secret_skip(cfg, transcript, report)
    if _should_repair(report):
        llm_output = llm.chat(
            system_prompt,
            _build_repair_user_message(transcript, llm_output, report),
            temperature=0.0,
        )
        report = run_selection(cfg, llm_output)
        report = _reinterpret_secret_skip(cfg, transcript, report)
    return _to_result(report), llm_output


def _reinterpret_secret_skip(cfg: SecretCfg, transcript: str, report: SecretReport) -> SecretReport:
    if not report.skipped or not _SECRET_REQUEST_RE.search(transcript):
        return report
    return SecretReport(
        outcome=SecretOutcome(
            "",
            False,
            kind="not_found",
            error="password request did not match an allowed entry",
        ),
        skipped=False,
        prefix=cfg.prefix,
    )


def _should_repair(report: SecretReport) -> bool:
    if report.skipped or report.ok:
        return False
    if report.outcome is None:
        return True
    return report.outcome.kind == "invalid_format"


def _build_repair_user_message(transcript: str, prior_output: str, report: SecretReport) -> str:
    error = "unknown"
    if report.outcome is not None:
        error = report.outcome.error or "unknown"
    return "\n".join(
        [
            "Your previous output could not be executed. Re-emit exactly one line using the OUTPUT FORMAT rules above.",
            "Output ONLY PASS_COPY <entry> or PASS_SKIP.",
            "",
            f"Original request: {transcript}",
            "",
            "Your previous output:",
            prior_output.strip() or "(empty)",
            "",
            f"Error: {error}",
        ]
    )


def _to_result(report: SecretReport) -> SinkResult:
    if report.skipped:
        return SinkResult(
            ok=False,
            message="I didn't hear a password request.",
            artifact="skipped",
        )
    if report.outcome is None:
        return SinkResult(ok=False, message="LLM output did not match expected secret format")
    if report.outcome.ok:
        return SinkResult(ok=True, message="copied secret to clipboard")
    if report.outcome.kind == "not_found":
        return SinkResult(
            ok=False,
            message=f"I couldn't find a matching password under {report.prefix}.",
            artifact="not_found",
        )

    diag = f"{report.outcome.entry or '(none)'}: {report.outcome.error or 'unknown'}"
    if len(diag) > _DIAG_CHARS:
        diag = diag[: _DIAG_CHARS - 1] + "…"
    return SinkResult(ok=False, message=f"secret copy failed ({diag})")


__all__ = ["SecretSink", "run_with_repair"]
