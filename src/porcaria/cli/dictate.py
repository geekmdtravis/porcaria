"""`porcaria dictate` — toggle recording, transcribe, optionally LLM-process, route to sinks."""
from __future__ import annotations

from typing import Annotated

import typer

from porcaria.cli._common import print_rpc, try_rpc


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
                "'secret' means the LLM selects an allowed pass entry and copies it "
                "to the clipboard. Routes and sinks are orthogonal for default/task; "
                "secret does not allow sink fanout."
            ),
        ),
    ] = "default",
    sinks: Annotated[
        str | None,
        typer.Option(
            "--sinks",
            help=(
                "Comma-separated list of write destinations for the transcript. "
                "Values: 'clipboard' (copy to system clipboard), 'note' (append to "
                "a timestamped file under the quick-notes directory), 'speaker' "
                "(synthesize and play back via the active TTS provider). "
                "Combine with commas — e.g. 'clipboard,note' or 'clipboard,speaker'. "
                "If omitted, the active profile's `sinks` list is used."
            ),
        ),
    ] = None,
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
    if resp is None:
        typer.secho(
            "daemon not running; run `porcaria daemon start` first",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(2)
    if resp.error and resp.error.get("code") == "not_implemented":
        typer.secho(
            "dictate.toggle is not implemented by the running daemon",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)
    print_rpc(resp)
