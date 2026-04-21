"""Summarize raw task-list output for spoken feedback."""
from __future__ import annotations

from porcaria.llm.base import LLMProvider
from porcaria.pipeline.context import date_context


def summarize_for_speech(llm: LLMProvider, raw_output: str, original_question: str = "") -> str:
    """Turn raw task-list output into a brief, natural spoken summary."""
    ctx = date_context()
    system = (
        "You turn raw task-list output into a brief, natural spoken summary.\n\n"
        f"{ctx}\n\n"
        f'CRITICAL: The user\'s original voice command was: "{original_question}"\n'
        "You MUST answer ONLY what they asked about. Filter the task data to match their request:\n"
        "- If they ask about a SPECIFIC DAY (e.g. Sunday, Monday), only mention tasks due on that day. Ignore all other days.\n"
        "- If they ask about a SPECIFIC TOPIC (e.g. medical records, groceries), only mention tasks matching that topic. Ignore unrelated tasks.\n"
        "- If they ask for a summary or overview, give a brief overview but still stay focused.\n"
        "- NEVER pad your response with extra information the user did not ask for.\n\n"
        "CRITICAL RULES:\n"
        "1. Use relative dates: \"today\", \"tomorrow\", \"this Friday\", \"next week\", etc.\n"
        "2. Be concise — a few sentences, not a wall of text.\n"
        "3. Group tasks naturally (e.g. \"The tasks due on December 11th are ...\").\n"
        '4. If none of the tasks match what the user asked about, say so with appropriate uncertainty (e.g. "I was unable to find any tasks on June 13th.").\n'
        "5. Output ONLY the spoken text — no markdown, no bullet points, no labels.\n"
        "6. Speak as a helpful assistant giving a quick verbal briefing.\n"
        "7. Double check all dates to ensure tasks align with their true dates.\n"
        "8. DO NOT include a count of the tasks in your reply. Instead of \"You have 3 tasks due tomorrow…\", say \"The following are due tomorrow…\".\n"
    )
    try:
        summary = llm.chat(system, raw_output, temperature=0.0).strip()
    except Exception:
        summary = ""
    return summary or raw_output
