"""Parse LLM-generated fazerei command lines and execute each one safely.

Hard rules (replace the bash `fmt_process_fazerei_cmds` + eval):
  - Each line must start with the configured fazerei binary name.
  - Mutation subcommands are whitelisted: add, done, undone, edit.
  - Query subcommands are whitelisted: list, show.
  - Lines are parsed with shlex.split (quote-aware) and executed via
    subprocess.run. NO eval, NO shell=True.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

from porcaria.config.schema import FazereiCfg
from porcaria.shellout import run

MUTATION_VERBS = {"add", "done", "undone", "edit"}
QUERY_VERBS = {"list", "show"}

# Prefix/suffix strippers. Applied repeatedly until the line stops changing so
# nested wrappers like "- `fazerei ...`" fully unwrap in one call.
_PREFIX_STRIPPERS = [
    re.compile(r"^`+"),
    re.compile(r"^\$\s+"),
    re.compile(r"^>\s+"),
    re.compile(r"^[-*]\s+"),
]
_SUFFIX_STRIPPERS = [re.compile(r"`+$")]
_FENCE_LINE = re.compile(r"^```")
_LANG_TAG = re.compile(r"^(bash|shell|sh|zsh)$", re.IGNORECASE)


@dataclass
class CmdOutcome:
    line: str
    verb: str              # "" when rejected
    ok: bool
    stdout: str = ""
    stderr: str = ""
    error: str = ""        # populated when the line was rejected before exec


@dataclass
class RunReport:
    outcomes: list[CmdOutcome] = field(default_factory=list)
    query_output: str = ""
    skipped: bool = False  # True when LLM emitted FAZEREI_SKIP

    @property
    def ok_count(self) -> int:
        return sum(1 for o in self.outcomes if o.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for o in self.outcomes if not o.ok)

    def action_summary(self) -> str:
        verbs = {o.verb for o in self.outcomes if o.ok and o.verb}
        bits: list[str] = []
        if "done" in verbs:
            bits.append("marked done")
        if "add" in verbs:
            bits.append("added")
        if "undone" in verbs:
            bits.append("reverted")
        if "edit" in verbs:
            bits.append("edited")
        if "list" in verbs or "show" in verbs:
            bits.append("queried")
        return " ".join(bits)


def sanitize_line(raw: str) -> str | None:
    """Apply the same LLM-formatting-artifact cleanup the bash does.
    Returns None if the line should be skipped entirely (empty/fence/lang-tag)."""
    line = raw.strip()
    if _FENCE_LINE.match(line):
        return None
    # Run prefix/suffix strippers repeatedly until stable so nested wrappers unwrap.
    while True:
        prev = line
        for pat in _PREFIX_STRIPPERS:
            line = pat.sub("", line)
        for pat in _SUFFIX_STRIPPERS:
            line = pat.sub("", line)
        line = line.strip()
        if line == prev:
            break
    if not line:
        return None
    if _LANG_TAG.match(line):
        return None
    return line


def classify(argv: list[str], binary: str) -> str | None:
    """Return the verb if argv looks like a valid whitelisted fazerei command, else None."""
    if len(argv) < 2:
        return None
    if argv[0] != binary:
        return None
    verb = argv[1]
    if verb in MUTATION_VERBS or verb in QUERY_VERBS:
        return verb
    return None


def run_commands(cfg: FazereiCfg, llm_output: str) -> RunReport:
    """Parse and execute the LLM's fazerei command lines.

    Signals:
      - RunReport.skipped == True when the LLM said FAZEREI_SKIP (no commands).
      - query_output is the concatenated stdout of all query (list/show) calls.
      - outcomes lists every line we attempted, including rejections.
    """
    report = RunReport()
    stripped = llm_output.strip()
    if not stripped or stripped == "FAZEREI_SKIP":
        report.skipped = True
        return report

    for raw_line in stripped.splitlines():
        line = sanitize_line(raw_line)
        if line is None:
            continue
        try:
            argv = shlex.split(line, posix=True)
        except ValueError as e:
            report.outcomes.append(
                CmdOutcome(line=line, verb="", ok=False, error=f"unparseable: {e}")
            )
            continue

        verb = classify(argv, cfg.command)
        if verb is None:
            report.outcomes.append(
                CmdOutcome(line=line, verb="", ok=False, error="rejected: not a whitelisted fazerei command")
            )
            continue

        res = run(argv, timeout=30.0)
        outcome = CmdOutcome(
            line=line,
            verb=verb,
            ok=res.ok,
            stdout=res.stdout,
            stderr=res.stderr,
            error="" if res.ok else f"exited {res.returncode}",
        )
        report.outcomes.append(outcome)
        if verb in QUERY_VERBS and res.ok and res.stdout.strip():
            report.query_output += res.stdout
            if not report.query_output.endswith("\n"):
                report.query_output += "\n"

    return report
