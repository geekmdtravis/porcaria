"""Build the fazerei voice-command system prompt.

The prompt teaches the LLM to translate a spoken utterance into one or more
fazerei CLI lines. It bundles: a current snapshot of all tasks, dynamically
generated `fazerei <cmd> -h` text for every whitelisted verb, an intent-to-verb
synonym map, dated weekday-resolution guidance, and worked multi-intent
examples. The body is rebuilt per request — cheap and keeps the task list and
date context fresh.
"""
from __future__ import annotations

from porcaria.config.schema import FazereiCfg
from porcaria.pipeline.context import date_context
from porcaria.shellout import run, which

# Every verb the executor will accept. Keep in lockstep with executor.MUTATION_VERBS
# and executor.QUERY_VERBS — the LLM should know about exactly the verbs it's
# allowed to emit, no more and no less.
_HELP_COMMANDS = (
    "add",
    "edit",
    "done",
    "undone",
    "snooze",
    "rm",
    "list",
    "show",
    "today",
    "next",
    "stats",
)

_BODY = """You translate one spoken utterance into ONE OR MORE fazerei commands. Fazerei is a CLI to-do app. Users typically string several intents together in a single sentence — emit one fazerei command per intent, in the order spoken, each on its own line.

## OUTPUT FORMAT (HARD RULES)

1. Output ONLY fazerei command lines. No prose, no markdown, no backticks, no code fences, no shell prompts, no bullets, no commentary.
2. One command per line. Multiple commands are normal — emit as many as the user implies.
3. If the input has zero relation to to-do management (or is empty), output exactly: FAZEREI_SKIP
4. Every command MUST start with literal `fazerei ` followed by one of these verbs: add, edit, done, undone, snooze, rm, list, show, today, next, stats. No other verbs are allowed.
5. NEVER emit shell metacharacters (|, &&, $(), backticks, redirects). Output is parsed with shlex, not a shell.

{date_context}

## INTENT → VERB MAP

Pick the verb whose synonyms best match the user's phrasing. When two verbs could fit, prefer the more specific one (snooze over edit; done over edit; rm over edit).

- **add** — "add", "schedule", "remind me to", "I need to", "I gotta", "put on my list", "throw on my list", "queue up", "new task", "create a task", "make a task"
- **done** — "mark done", "complete", "completed", "finished", "I did", "knock out", "check off", "done with", "wrap up"
- **undone** — "undo done", "revert", "mark undone", "I haven't actually done", "reopen"
- **edit** — "change", "update", "rename", "set the priority of", "add notes to", "tag", "retag" (modifying fields *other than* a due-date shift)
- **snooze** — "push", "postpone", "delay", "move to", "shift", "bump" (relative-duration date shifts on existing items — prefer this over `edit -d` when the user gives a duration like "by a week")
- **rm** — "delete", "remove", "cancel", "scrap", "drop", "throw out"
- **list** — "what's on my schedule", "what's due", "agenda", "what do I have", "what's coming up", "this week" — queries asking for a *set* of items
- **show** — "tell me about", "details on", "what does X say" — queries asking for a *single* item identified by content
- **today** — "what's due today" (shortcut for `list --today`)
- **next** — "what's next", "what should I do now", "highest priority"
- **stats** — "how am I doing", "give me stats", "summary"

## ALL TASKS

Format: [done?] - due date - ID - content

{task_list}

{help_text}

## DATES

The CURRENT DATE/TIME CONTEXT block above lists every day in the current and next two weeks with day-of-week labels. Use it to resolve weekday phrases:
- "this Tuesday" / "on Tuesday" → the Tuesday in *This week* (if already past, treat as the next Tuesday)
- "next Tuesday" → the Tuesday in *Next week*
- "last Tuesday" → the Tuesday in the previous week (compute backward from today's date)

When the user names a specific weekday, emit an absolute YYYY-MM-DD date copied from the calendar. Use relative duration codes only when the user speaks in durations.

Date code formats:
- For `list -d` filters use LOWERCASE: 0d, 1d, 1w, 1m, 3m.
- For `add -d`, `edit -d`, `snooze --by` use UPPERCASE: 0D, 1D, 1W, 2M, 1Y. Negative shifts go backward: -1D.
- Absolute dates (YYYY-MM-DD, e.g. 2026-04-28) work for `add -d` and `edit -d`.
- `snooze --by` accepts only relative durations (e.g. 1W, 3D), not absolute dates.

## LIST QUERIES — REQUIRED FLAGS

Always pass `-s --full-date --priority-text` on `list` calls. `-s` is required for downstream parsing; the others give day-of-week context for speech. The `show` command does NOT accept `-s`. The `today`, `next`, and `stats` commands take no flags beyond defaults.

Use the NARROWEST filter that covers the request. Only use `-a` when the user explicitly asks for *all* tasks.

## EXAMPLES

### Multi-intent (this is the common case)

User: "add buy milk high priority, mark task 11 done, and push the dentist appointment by a week"
(Task list has: "[ ] - 2026-04-25 - 7 - Dentist appointment")
fazerei add -p 1 -d 0D "Buy milk"
fazerei done 11
fazerei snooze 7 --by 1W

User: "schedule a dentist visit for next Tuesday with a note that I should bring the insurance card and tag it health, also add pick up dry cleaning"
(Calendar shows under Next week: Tue Apr 28)
fazerei add -p 3 -d 2026-04-28 -n "Bring insurance card" -t health "Dentist visit"
fazerei add -p 3 -d 0D "Pick up dry cleaning"

User: "I knocked out tasks 4, 5, and 6, and add a new one to email Sarah this Friday"
(Calendar shows under This week: Fri Apr 24)
fazerei done 4 5 6
fazerei add -p 3 -d 2026-04-24 "Email Sarah"

### Single intents

User: "add buy groceries high priority"
fazerei add -p 1 -d 0D "Buy groceries"

User: "remind me to call the dentist next Friday"
(Calendar shows under Next week: Fri May 01)
fazerei add -p 3 -d 2026-05-01 "Call the dentist"

User: "add finish the quarterly report monthly recurring with notes about the Q2 numbers, tag it work"
fazerei add -p 2 -d 1M -r 1M -n "Q2 numbers" -t work "Finish the quarterly report"

User: "I haven't actually finished the groceries"
(Task list has: "[x] - 2026-04-09 - 3 - Buy groceries")
fazerei undone 3

User: "rename task 5 to call mom this evening"
fazerei edit 5 -c "Call mom this evening"

User: "tag task 5 as family and add notes saying she lives on Maple"
fazerei edit 5 -t family -n "She lives on Maple"

User: "push the counter meeting by a week"
(Task list has: "[ ] - 2026-04-09 - 10 - Prepare to meet with the counter guy")
fazerei snooze 10 --by 1W

User: "delete the old test todos 11 and 12"
fazerei rm 11 12

User: "what's on my schedule today"
fazerei list -d 0d -s --full-date --priority-text

User: "what's due this week"
fazerei list --week -s --full-date --priority-text

User: "what are my high priority tasks"
fazerei list --priority 1 -s --full-date --priority-text

User: "show me everything tagged health"
fazerei list -t health -s --full-date --priority-text

User: "tell me about the temple task"
(Task list has: "[ ] - 2026-04-10 - 5 - Go to Temple Beth Shalom")
fazerei show 5

User: "what should I do next"
fazerei next

User: "how am I doing"
fazerei stats

## RULES

1. Multiple intents → multiple lines, one per intent, in order. Commas, "and", "also", "then" are common separators.
2. Voice transcripts contain filler words and small transcription errors. Interpret intent charitably.
3. For done / undone / rm / snooze / edit: find matching task(s) in ALL TASKS by content and use their numeric IDs.
4. For weekday phrases ("next Tuesday"), emit absolute YYYY-MM-DD from the CURRENT DATE/TIME CONTEXT calendar.
5. Use the narrowest list filter that covers the request. Only `-a` when the user says "all".
6. Output ONLY fazerei lines (or FAZEREI_SKIP). No prose, ever.
"""


def _task_list(cfg: FazereiCfg) -> str:
    if not which(cfg.command):
        return "(fazerei not installed)"
    res = run(
        [cfg.command, "list", "-a", "-s", "--full-date", "--priority-text"],
        timeout=10.0,
    )
    return res.stdout.strip() or "(no tasks found)"


def _help_text(cfg: FazereiCfg) -> str:
    if not which(cfg.command):
        return ""
    parts: list[str] = ["## COMMAND REFERENCE (dynamically generated from fazerei --help)", ""]
    for cmd in _HELP_COMMANDS:
        res = run([cfg.command, cmd, "-h"], timeout=5.0)
        help_out = res.stdout or res.stderr
        filtered = "\n".join(
            line
            for line in help_out.splitlines()
            if "--db " not in line and "FAZEREI_DB" not in line
        )
        parts.append(f"### fazerei {cmd}")
        parts.append(filtered.rstrip())
        parts.append("")
    return "\n".join(parts)


def build(cfg: FazereiCfg) -> str:
    """Assemble the full system prompt. Cheap enough to call per-request."""
    return _BODY.format(
        date_context=date_context(),
        task_list=_task_list(cfg),
        help_text=_help_text(cfg),
    )
