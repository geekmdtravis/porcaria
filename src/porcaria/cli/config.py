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

app = typer.Typer(help="Inspect and edit config.", no_args_is_help=True)


@app.command("show")
def show() -> None:
    """Print the effective merged config as JSON."""
    cfg = load_config()
    typer.echo(json.dumps(cfg.model_dump(), indent=2))


@app.command("path")
def path() -> None:
    """Print the user config path."""
    typer.echo(str(paths.config_file()))


@app.command("edit")
def edit() -> None:
    """Open the user config in $EDITOR, seeding it from defaults if absent."""
    paths.ensure_dirs()
    cf = paths.config_file()
    if not cf.exists():
        shutil.copy(DEFAULTS_FILE, cf)
        typer.echo(f"seeded {cf} from defaults")
    editor = os.environ.get("EDITOR", "nvim" if shutil.which("nvim") else "vi")
    subprocess.call([editor, str(cf)])


@app.command("validate")
def validate() -> None:
    """Validate the current config; exit 1 on error."""
    try:
        load_config()
    except Exception as e:
        typer.secho(f"config invalid: {type(e).__name__}: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    typer.echo("ok")


@app.command("defaults")
def defaults() -> None:
    """Print the shipped defaults.toml."""
    typer.echo(DEFAULTS_FILE.read_text())
