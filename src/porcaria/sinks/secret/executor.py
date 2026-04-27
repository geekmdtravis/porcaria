"""Parse LLM-selected pass entries and ask pass to copy them to the clipboard.

The LLM never emits a shell command. It may only emit one control line:

  PASS_COPY porcaria-accessible/path/to/entry

The executor validates that path against entries discovered via `pass ls`, then
runs `pass show -c <entry>` with shell=False. Porcaria never receives the secret
on stdout.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from porcaria.config.schema import SecretCfg
from porcaria.shellout import run, which

SKIP_SIGNAL = "PASS_SKIP"
NOT_FOUND_SIGNAL = "PASS_NOT_FOUND"
COPY_PREFIX = "PASS_COPY"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_FENCE_LINE = re.compile(r"^```")
_LANG_TAG = re.compile(r"^(bash|shell|sh|zsh)$", re.IGNORECASE)
_PREFIX_STRIPPERS = [
    re.compile(r"^`+"),
    re.compile(r"^\$\s+"),
    re.compile(r"^>\s+"),
    re.compile(r"^[-*]\s+"),
]
_SUFFIX_STRIPPERS = [re.compile(r"`+$")]


@dataclass
class SecretOutcome:
    entry: str
    ok: bool
    kind: str = "copy_failed"
    error: str = ""


@dataclass
class SecretReport:
    outcome: SecretOutcome | None = None
    skipped: bool = False
    prefix: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.outcome and self.outcome.ok)


def sanitize_line(raw: str) -> str | None:
    line = raw.strip()
    if _FENCE_LINE.match(line):
        return None
    while True:
        prev = line
        for pat in _PREFIX_STRIPPERS:
            line = pat.sub("", line)
        for pat in _SUFFIX_STRIPPERS:
            line = pat.sub("", line)
        line = line.strip()
        if line == prev:
            break
    if not line or _LANG_TAG.match(line):
        return None
    return line


def list_entries(cfg: SecretCfg) -> list[str]:
    """Return pass leaf entries below the configured prefix."""
    if not which(cfg.command):
        return []
    res = run([cfg.command, "ls", cfg.prefix], timeout=10.0)
    if not res.ok:
        return []
    return parse_pass_ls(res.stdout, cfg.prefix)


def parse_pass_ls(output: str, prefix: str) -> list[str]:
    """Parse `pass ls <prefix>` tree output into leaf entry paths."""
    stack: list[str] = []
    paths: list[str] = []
    for raw in output.splitlines():
        parsed = _parse_tree_line(raw)
        if parsed is None:
            continue
        depth, name = parsed
        if not name or name == "Password Store":
            continue
        stack = stack[:depth]
        stack.append(name)
        path = "/".join(stack)
        if path == prefix or path.startswith(prefix + "/"):
            paths.append(path)

    dirs = {p for p in paths for other in paths if other.startswith(p + "/")}
    return sorted(p for p in paths if p not in dirs)


def _parse_tree_line(raw: str) -> tuple[int, str] | None:
    line = _ANSI.sub("", raw).rstrip()
    if not line.strip():
        return None

    marker_pos = -1
    for marker in ("├── ", "└── "):
        marker_pos = line.find(marker)
        if marker_pos >= 0:
            name = line[marker_pos + len(marker):].strip()
            return marker_pos // 4 + 1, name

    return 0, line.strip()


def run_selection(cfg: SecretCfg, llm_output: str) -> SecretReport:
    report = SecretReport(prefix=cfg.prefix)
    lines = [line for raw in llm_output.splitlines() if (line := sanitize_line(raw))]
    if not lines or lines == [SKIP_SIGNAL]:
        report.skipped = True
        return report
    if lines == [NOT_FOUND_SIGNAL]:
        report.outcome = SecretOutcome("", False, kind="not_found", error="no matching secret found")
        return report
    if len(lines) != 1:
        report.outcome = SecretOutcome(
            "", False, kind="invalid_format", error="expected exactly one PASS_COPY line"
        )
        return report

    try:
        argv = shlex.split(lines[0], posix=True)
    except ValueError as e:
        report.outcome = SecretOutcome("", False, kind="invalid_format", error=f"unparseable: {e}")
        return report

    if len(argv) != 2 or argv[0] != COPY_PREFIX:
        report.outcome = SecretOutcome(
            "", False, kind="invalid_format", error="rejected: expected PASS_COPY <entry>"
        )
        return report

    entry = argv[1]
    if not entry.startswith(cfg.prefix + "/"):
        report.outcome = SecretOutcome(
            entry, False, kind="invalid_format", error="rejected: entry outside allowed prefix"
        )
        return report

    entries = set(list_entries(cfg))
    if entry not in entries:
        report.outcome = SecretOutcome(
            entry, False, kind="not_found", error="entry not found in pass list"
        )
        return report

    error = _copy_with_pass(cfg, entry)
    if error:
        report.outcome = SecretOutcome(entry, False, kind="copy_failed", error=error)
        return report

    report.outcome = SecretOutcome(entry, True, kind="copied")
    return report


def _copy_with_pass(cfg: SecretCfg, entry: str) -> str:
    """Run `pass show -c` and wait for pinentry/copy completion.

    pass starts its clipboard-clear helper in the background, prints a copied
    confirmation, then exits. Waiting for pass itself avoids reporting success
    while a GPG pinentry prompt is still waiting for user input.
    """
    copied = run([cfg.command, "show", "-c", entry], timeout=120.0)
    if copied.returncode == 124:
        return "pass timed out waiting for clipboard confirmation"
    if not copied.ok:
        return f"pass show -c exited {copied.returncode}"
    return ""
