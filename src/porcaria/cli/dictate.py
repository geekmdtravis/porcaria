"""`porcaria dictate` — toggle recording, transcribe, optionally LLM-process, route to a sink."""
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
                "Pass the raw transcript through the active LLM for punctuation, "
                "capitalization, and lightweight rewording before it hits the sink. "
                "Off by default (raw ASR output is usually what you want)."
            ),
        ),
    ] = False,
    note: Annotated[
        bool,
        typer.Option(
            "--note",
            help=(
                "In addition to the clipboard, append the transcript to a timestamped "
                "file under the configured quick-notes directory. Useful for keeping a "
                "session log without interrupting the paste-into-editor flow."
            ),
        ),
    ] = False,
    route: Annotated[
        str,
        typer.Option(
            "--route",
            help=(
                "Which sink(s) receive the transcript. "
                "'auto' copies to the clipboard (and adds a quick-note if --note is set). "
                "'clipboard' forces clipboard-only (ignores --note). "
                "'note' writes a quick-note only (no clipboard). "
                "'task' routes the utterance through the voice-command LLM into the "
                "fazerei task CLI instead of copying it — use this to say things like "
                "'add pay the rent to personal' or 'show me today's tasks'."
            ),
        ),
    ] = "auto",
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            help=(
                "Use a named profile (e.g. 'home', 'travel') for this invocation only "
                "instead of the active profile in config. Profiles bundle an ASR/LLM/TTS "
                "choice — use this to temporarily switch between local and cloud backends."
            ),
        ),
    ] = None,
) -> None:
    """Toggle recording and route the transcript to a sink.

    First invocation starts recording from the configured PulseAudio source.
    Second invocation stops recording, transcribes via the active ASR provider,
    optionally runs the text through the LLM (--clean), and sends the result to
    the selected sink (--route)."""
    params = {"clean": clean, "note": note, "route": route, "profile": profile}
    resp = try_rpc("dictate.toggle", params)
    if resp is not None:
        from porcaria.cli._common import print_rpc

        if resp.ok or (resp.error and resp.error.get("code") != "not_implemented"):
            print_rpc(resp)
            return

    # Daemon not running or not implementing this method yet — fall back.
    args: list[str] = []
    if clean:
        args.append("--ai-clean")
    if note:
        args.append("--quick-note")
    if route == "task":
        args.append("--fazerei")
    rc = legacy_dictate(args)
    raise typer.Exit(rc)
