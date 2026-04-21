"""`porcaria dictate` — toggle recording, transcribe, optionally LLM-process, route to a sink."""
from __future__ import annotations

from typing import Annotated

import typer

from porcaria.cli._common import legacy_dictate, try_rpc


def main(
    clean: Annotated[bool, typer.Option("--clean", help="Run transcript through LLM cleanup.")] = False,
    note: Annotated[bool, typer.Option("--note", help="Save transcript to quick-notes dir.")] = False,
    route: Annotated[
        str,
        typer.Option(
            "--route",
            help="Sink: 'auto' (default), 'clipboard', 'note', or 'task' (voice-command a task CLI).",
        ),
    ] = "auto",
    profile: Annotated[str | None, typer.Option("--profile", help="Override active profile.")] = None,
) -> None:
    """Toggle dictation. A second invocation stops recording and processes the audio."""
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
