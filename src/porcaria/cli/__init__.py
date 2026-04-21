"""porcaria CLI entry point."""
from __future__ import annotations

import typer

from porcaria.cli import clean, config as config_cmd, daemon, dictate, serve, speak, status, task, transcribe

app = typer.Typer(
    name="porcaria",
    help="Portable voice-AI pipeline (capture → ASR → LLM → sink).",
    no_args_is_help=True,
    add_completion=False,
)

app.command("dictate")(dictate.main)
app.command("transcribe")(transcribe.main)
app.command("speak")(speak.main)
app.command("clean")(clean.main)
app.command("task")(task.main)
app.command("status")(status.main)

app.add_typer(serve.app, name="serve", help="Start/stop local model servers.")
app.add_typer(daemon.app, name="daemon", help="Manage the porcaria daemon.")
app.add_typer(config_cmd.app, name="config", help="Inspect and edit config.")


if __name__ == "__main__":
    app()
