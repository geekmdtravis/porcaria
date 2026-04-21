"""`porcaria dictate` — toggle recording, transcribe, optionally LLM-process, route to sinks."""
from __future__ import annotations

from typing import Annotated

import typer

from porcaria.cli._common import legacy_dictate, try_rpc


def main(
    clean: Annotated[
        bool,
        typer.Option(
            "--clean",
            help=(
                "Pass the transcript through the active LLM for punctuation, "
                "capitalization, and lightweight rewording before it hits the sinks. "
                "Off by default (raw ASR output is usually what you want)."
            ),
        ),
    ] = False,
    route: Annotated[
        str,
        typer.Option(
            "--route",
            help=(
                "Processing pipeline for the transcript. "
                "'default' (the default) means no extra processing — the transcript "
                "is handed straight off to the sinks. "
                "'task' means the LLM interprets the utterance as a fazerei command "
                "and executes it (use this for voice-driven task management). "
                "Routes and sinks are orthogonal: you can combine --route task with "
                "any --sinks value to also get a clipboard/note/speaker copy."
            ),
        ),
    ] = "default",
    sinks: Annotated[
        str,
        typer.Option(
            "--sinks",
            help=(
                "Comma-separated list of write destinations for the transcript. "
                "Values: 'clipboard' (copy to system clipboard), 'note' (append to "
                "a timestamped file under the quick-notes directory), 'speaker' "
                "(synthesize and play back via the active TTS provider). "
                "Combine with commas — e.g. 'clipboard,note' or 'clipboard,speaker'. "
                "Default is 'clipboard'."
            ),
        ),
    ] = "clipboard",
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            help=(
                "Use a named profile (e.g. 'home', 'travel') for this invocation only. "
                "Profiles bundle an ASR/LLM/TTS choice — useful for swapping local ↔ cloud."
            ),
        ),
    ] = None,
) -> None:
    """Toggle recording. Flags on the stop press decide what happens.

    First press: begins recording. Any flags you pass are ignored — the start
    press just starts capture.

    Second press: stops recording, transcribes, and applies the flags from
    *this* press to the result. So you can start with a bare keybind, speak
    for as long as you want, and pick the destination/processing at the end
    based on how the dictation actually went (clipboard, cleaned, saved to a
    note, read back aloud, routed through the task CLI)."""
    params = {"clean": clean, "route": route, "sinks": sinks, "profile": profile}
    resp = try_rpc("dictate.toggle", params)
    if resp is not None:
        from porcaria.cli._common import print_rpc

        if resp.ok or (resp.error and resp.error.get("code") != "not_implemented"):
            print_rpc(resp)
            return

    # Daemon not running or method not implemented — fall back to legacy bash.
    args: list[str] = []
    if clean:
        args.append("--ai-clean")
    if "note" in sinks.split(","):
        args.append("--quick-note")
    if route == "task":
        args.append("--fazerei")
    rc = legacy_dictate(args)
    raise typer.Exit(rc)
