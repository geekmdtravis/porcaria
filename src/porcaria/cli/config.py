"""`porcaria config {show,edit,validate}` — inspect and edit config."""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import typer

from porcaria import paths
from porcaria.config import load_config
from porcaria.config.loader import DEFAULTS_FILE

app = typer.Typer(
    help=(
        "Inspect, edit, and validate the porcaria config. "
        "User config lives at $XDG_CONFIG_HOME/porcaria/config.toml (typically "
        "~/.config/porcaria/config.toml); edits are merged on top of the shipped "
        "defaults. Run `porcaria daemon reload` after editing to apply changes."
    ),
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command("show")
def show() -> None:
    """Print the effective merged config as JSON.

    Shows the fully resolved config after the user's overrides have been layered
    on top of defaults — use this to confirm what the daemon is actually running."""
    cfg = load_config()
    typer.echo(json.dumps(cfg.model_dump(), indent=2))


@app.command("path")
def path() -> None:
    """Print the path where the user config lives (or would be created on first edit)."""
    typer.echo(str(paths.config_file()))


@app.command("edit")
def edit() -> None:
    """Open the user config in $EDITOR, seeding it from defaults if absent.

    Falls back to `nvim` then `vi` if $EDITOR is unset. After saving, run
    `porcaria daemon reload` for the daemon to pick up the changes."""
    paths.ensure_dirs()
    cf = paths.config_file()
    if not cf.exists():
        shutil.copy(DEFAULTS_FILE, cf)
        typer.echo(f"seeded {cf} from defaults")
    editor = os.environ.get("EDITOR", "nvim" if shutil.which("nvim") else "vi")
    subprocess.call([editor, str(cf)])


@app.command("validate")
def validate() -> None:
    """Validate the current config against the pydantic schema.

    Prints 'ok' and exits 0 on success; prints the error and exits 1 on failure.
    Handy for pre-commit hooks or smoke-testing a hand-edited config."""
    try:
        load_config()
    except Exception as e:
        typer.secho(f"config invalid: {type(e).__name__}: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    typer.echo("ok")


@app.command("defaults")
def defaults() -> None:
    """Print the defaults.toml shipped with porcaria.

    Useful as a reference when writing your own user config — every field shown
    here can be overridden in ~/.config/porcaria/config.toml."""
    typer.echo(DEFAULTS_FILE.read_text())
