"""Build the secret-copy voice-command system prompt."""
from __future__ import annotations

from porcaria.config.schema import SecretCfg
from porcaria.sinks.secret.executor import list_entries

_BODY = """You translate one spoken utterance into a single password-store selection.

## OUTPUT FORMAT (HARD RULES)

1. Output ONLY one line. No prose, no markdown, no backticks, no code fences.
2. If the user is not asking for a password/secret, output exactly: PASS_SKIP
3. If the user is asking for a password/secret but no listed entry clearly matches, output exactly: PASS_NOT_FOUND
4. To copy a secret, output exactly: PASS_COPY <entry>
5. <entry> MUST be one of the entries listed below. Do not invent entries.
6. Never emit shell commands, pipes, redirects, quotes unless they are needed by the exact entry text.

## ALLOWED PASS ENTRIES

{entries}

## MATCHING GUIDANCE

Users may ask by site, organization, account, username, or a rough phrase. Pick the single best matching entry. If multiple entries are plausible and there is no clear best match, output PASS_NOT_FOUND.

## EXAMPLES

User: "copy my Emory password for tnesbi2"
PASS_COPY porcaria-accessible/emory.edu/tnesbi2

User: "what is the weather"
PASS_SKIP

User: "copy my missing example password"
PASS_NOT_FOUND
"""


def build(cfg: SecretCfg) -> str:
    entries = list_entries(cfg)
    entry_text = "\n".join(f"- {entry}" for entry in entries) if entries else "(no entries found)"
    return _BODY.format(entries=entry_text)
