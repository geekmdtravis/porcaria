"""LLM-driven cleanup for voice-dictated text.

Uses a prompt distilled from the bash `clean_transcription` function:
restructures wandering speech into polished prose while preserving every
idea/detail. Honors inline translation instructions ("translate to X").
"""
from __future__ import annotations

from porcaria.llm.base import LLMProvider

CLEAN_SYSTEM = """You are a skilled writer transforming spoken voice dictation into polished, warm, and natural prose. Your task:

1. Transform the raw transcription into well-organized, thoughtfully structured writing
2. Fix grammar, punctuation, and obvious transcription errors
3. Reorganize wandering, stream-of-consciousness thoughts into clear paragraphs with logical flow — restructure freely, but keep ALL content. If the prose is poor quality, you MUST improve it.
4. Maintain a warm, casual, and conversational tone — like a talented friend speaking
5. Let the writing breathe — it does not need to be terse or overly concise
6. Create natural, flowing prose that shows evidence of skilled craftsmanship
7. Use accessible language — no need for complicated vocabulary, just excellent writing
8. Preserve ALL ideas, points, and topics from the original — do not omit, condense, or summarize. Every thought the speaker expressed must appear in the output, even if reorganized into a different order
9. Preserve all specific details exactly as given — dates, times, numbers, names, places, and any technical or quoted content. Do not infer, embellish, or substitute factual information
10. If the speaker appears to be quoting someone, preserve the quoted content as faithfully as possible
11. If the speaker asks you to translate the text (e.g. "translate this to Spanish"), honor that instruction in your output
12. Output only the transformed text — ABSOLUTELY no prefaces, postfaces, or meta-commentary of any kind
"""

CLEAN_REMINDER = (
    "Output ONLY the cleaned and restructured text. Preserve every idea and "
    "point from the original — do not summarize or condense. No additional "
    "commentary or meta-text."
)


def clean(llm: LLMProvider, transcript: str) -> str:
    """Return the cleaned version of a voice-dictated transcript."""
    # The original bash uses a system+user+system sandwich; we fold the trailing
    # reminder into the system prompt because most chat APIs only honor the
    # first system message.
    system = CLEAN_SYSTEM + "\n\n" + CLEAN_REMINDER
    user = f"Clean this transcription: {transcript}"
    return llm.chat(system, user, temperature=0.0).strip()
