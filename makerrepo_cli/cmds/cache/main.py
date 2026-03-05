import pathlib

import click
import rich
from rich import box
from rich.padding import Padding
from rich.table import Table

from ..shared.cache import default_cache_dir
from .cli import cli


def _format_size(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


def _collect_cache_files(cache_dir: pathlib.Path) -> list[tuple[pathlib.Path, int]]:
    """Return list of (path, size) for all files under cache_dir. Paths are relative to cache_dir."""
    if not cache_dir.is_dir():
        return []
    out: list[tuple[pathlib.Path, int]] = []
    for p in cache_dir.rglob("*"):
        if p.is_file():
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            out.append((p.relative_to(cache_dir), size))
    return sorted(out)


@cli.command(name="list", help="List cache files and their sizes.")
@click.option(
    "-C",
    "--cache-dir",
    "cache_dir",
    type=click.Path(path_type=pathlib.Path, exists=False),
    default=None,
    help="Cache directory (default: ~/.cache/makerrepo or XDG_CACHE_HOME/makerrepo).",
)
def list_caches(cache_dir: pathlib.Path | None):
    """List all cache files under the cache directory with their sizes."""
    root = cache_dir if cache_dir is not None else default_cache_dir()
    root = root.resolve()
    files = _collect_cache_files(root)
    if not files:
        click.echo(f"No cache files in {root}")
        return
    total_size = sum(s for _, s in files)
    table = Table(
        title=f"Cache files — {root}",
        box=box.SIMPLE,
        header_style="yellow",
        expand=True,
    )
    table.add_column("Path", style="cyan")
    table.add_column("Size", justify="right", style="green")
    for rel_path, size in files:
        table.add_row(rel_path.as_posix(), _format_size(size))
    table.caption = (
        f"{len(files)} file(s), total [bold]{_format_size(total_size)}[/bold]"
    )
    rich.print(Padding(table, (0, 0, 0, 2)))


@cli.command(
    name="prune",
    help="Remove cache files. Use --all to remove everything, or pass paths to remove specific files or folders.",
)
@click.option(
    "-C",
    "--cache-dir",
    "cache_dir",
    type=click.Path(path_type=pathlib.Path, exists=False),
    default=None,
    help="Cache directory (default: ~/.cache/makerrepo or XDG_CACHE_HOME/makerrepo).",
)
@click.option(
    "--all",
    "prune_all",
    is_flag=True,
    help="Remove all cache files.",
)
@click.argument(
    "paths",
    nargs=-1,
    type=click.Path(path_type=pathlib.Path),
)
def prune_caches(
    cache_dir: pathlib.Path | None,
    prune_all: bool,
    paths: tuple[pathlib.Path, ...],
):
    """Delete cache files: either all (--all) or the given paths relative to the cache directory."""
    root = cache_dir if cache_dir is not None else default_cache_dir()
    root = root.resolve()
    if not root.is_dir():
        click.echo(f"Cache directory does not exist: {root}")
        return
    if prune_all:
        if paths:
            click.echo("Cannot use --all and path arguments together.")
            raise SystemExit(2)
        to_remove = list(root.rglob("*"))
        to_remove = [p for p in to_remove if p.is_file()]
        if not to_remove:
            click.echo("No cache files to remove.")
            return
        for p in to_remove:
            p.unlink()
        # Remove empty dirs
        for d in sorted(root.rglob("*"), key=lambda x: -len(x.parts)):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        click.echo(f"Removed {len(to_remove)} cache file(s).")
        return
    if not paths:
        click.echo(
            "Specify --all or one or more paths to remove (e.g. module/file.brep)."
        )
        raise SystemExit(2)
    removed = 0
    for rel in paths:
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            click.echo(f"Path is outside cache directory: {rel}")
            raise SystemExit(2)
        if target.is_file():
            target.unlink()
            removed += 1
        elif target.is_dir():
            count = 0
            for f in target.rglob("*"):
                if f.is_file():
                    f.unlink()
                    count += 1
            for d in sorted(target.rglob("*"), key=lambda x: -len(x.parts)):
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
            if target.is_dir() and not any(target.iterdir()):
                target.rmdir()
            removed += count
        else:
            click.echo(f"Not found: {rel}")
    click.echo(f"Removed {removed} item(s).")
