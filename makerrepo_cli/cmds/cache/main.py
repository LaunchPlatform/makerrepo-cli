import logging
import os
import pathlib
from collections import defaultdict

import click
import questionary
import rich
from ocp_vscode import Camera
from rich import box
from rich.padding import Padding
from rich.table import Table

from ...core.cache import default_cache_dir
from ..environment import Environment
from ..environment import pass_env
from ..shared.utils import escape
from .cli import cli

logger = logging.getLogger(__name__)

# Cache files we can view in the CAD viewer (BREP only for now)
VIEWABLE_SUFFIX = ".brep"


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
    for root, _dirs, names in os.walk(cache_dir):
        root_path = pathlib.Path(root)
        for name in names:
            p = root_path / name
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            out.append((p.relative_to(cache_dir), size))
    return sorted(out)


def _group_cache_files_by_module_name(
    files: list[tuple[pathlib.Path, int]],
    cache_suffix: str = ".brep",
) -> defaultdict[tuple[str, str], list[tuple[pathlib.Path, int]]]:
    """Group cache files by (module, name). Path layout: <module>/<name>/<cache_key>.brep."""
    grouped: defaultdict[tuple[str, str], list[tuple[pathlib.Path, int]]] = defaultdict(
        list
    )
    for rel_path, size in files:
        parts = rel_path.parts
        if len(parts) < 3 or rel_path.suffix.lower() != cache_suffix:
            continue
        module, name = parts[0], parts[1]
        if not module or not name:
            continue
        key = (module, name)
        grouped[key].append((rel_path, size))
    return grouped


def _find_dangling_cache_files(
    caches: dict[str, dict[str, object]],
    module_name_files: defaultdict[tuple[str, str], list[tuple[pathlib.Path, int]]],
) -> list[tuple[pathlib.Path, int]]:
    """Return (rel_path, size) for cache files that have no matching @cached function."""
    known_keys = {
        (module, name) for module, items_dict in caches.items() for name in items_dict
    }
    return [
        (rel_path, size)
        for (module, name), file_list in module_name_files.items()
        if (module, name) not in known_keys
        for rel_path, size in file_list
    ]


def _print_cache_files_only(
    root: pathlib.Path,
    files: list[tuple[pathlib.Path, int]],
) -> None:
    """Print a simple table of cache files when no @cached functions are found."""
    if not files:
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


def _prompt_cache_prune_selection(
    files: list[tuple[pathlib.Path, int]],
) -> list[pathlib.Path] | None:
    """Show an interactive checkbox prompt to select cache file(s) to prune. Returns selected paths or None if cancelled."""
    if not files:
        return None
    choices = [
        questionary.Choice(
            title=f"{rel_path.as_posix()}  {_format_size(size)}",
            value=rel_path,
        )
        for rel_path, size in files
    ]
    selected = questionary.checkbox(
        "Select cache files to remove (Space to toggle, Enter to confirm)",
        choices=choices,
        validate=lambda x: (
            True if len(x) > 0 else "Select at least one cache file to remove"
        ),
    ).ask()
    return list(selected) if selected else None


@cli.command(name="list", help="List cached decorated functions and their cache files.")
@pass_env
def list_caches(env: Environment):
    """Scan repo for @cached functions, then list each with short desc, file:lineno, and matching cache files."""
    from ...core.repo.repo import collect_from_repo

    root = (
        env.cache_dir if env.cache_dir is not None else default_cache_dir()
    ).resolve()
    registry = collect_from_repo()
    caches = registry.caches
    files = _collect_cache_files(root)
    module_name_files = _group_cache_files_by_module_name(files)

    if not caches:
        if not files:
            click.echo(
                f"No cached functions found and no cache files in {root}"
                if root.is_dir()
                else f"No cached functions found; cache directory does not exist: {root}"
            )
        else:
            click.echo("No cached functions found in the current directory.")
            _print_cache_files_only(root, files)
        return

    env.logger.info(
        "Listing cached functions from current directory",
        extra={"markup": True, "highlighter": None},
    )
    table = Table(
        box=box.SIMPLE,
        header_style="yellow",
        expand=True,
    )
    table.add_column("Function", style="cyan")
    table.add_column("Description")
    table.add_column("Total size", justify="right", style="green")
    table.add_column("Size", justify="right", style="green")
    table.add_column("Cache files", no_wrap=False, overflow="fold", min_width=45)
    total_size = 0
    for module, items_dict in sorted(caches.items()):
        for name, cached_obj in sorted(items_dict.items()):
            short_desc = cached_obj.short_desc or ""
            key = (cached_obj.module, cached_obj.name)
            matched = module_name_files.get(key, [])
            func_total = sum(s for _, s in matched)
            total_size += func_total
            func_cell = f"{escape(module)}/{escape(name)}"
            total_str = _format_size(func_total)
            if matched:
                sorted_matched = sorted(matched)
                files_cell = "\n".join(
                    rel_path.as_posix() for rel_path, _ in sorted_matched
                )
                size_cell = "\n".join(_format_size(s) for _, s in sorted_matched)
            else:
                files_cell = "(no cache files)"
                size_cell = "—"
            table.add_row(
                func_cell,
                short_desc or "—",
                total_str,
                size_cell,
                files_cell,
            )
    rich.print(Padding(table, (0, 0, 0, 2)))

    # List dangling cache files (match cache path pattern but no corresponding @cached function)
    dangling = _find_dangling_cache_files(caches, module_name_files)
    if dangling:
        dangling_size = sum(s for _, s in dangling)
        rich.print(
            Padding(
                f"[dim]Dangling cache files (no matching @cached function): {len(dangling)} file(s), {_format_size(dangling_size)}[/dim]",
                (1, 0, 0, 2),
            )
        )
        for rel_path, size in sorted(dangling):
            rich.print(
                Padding(
                    f"  [dim]{rel_path.as_posix()}  {_format_size(size)}[/dim]",
                    (0, 0, 0, 2),
                )
            )

    if files:
        total_size_all = sum(s for _, s in files)
        rich.print(
            Padding(
                f"[dim]{len(files)} file(s), total {_format_size(total_size_all)}[/dim]",
                (1, 0, 0, 2),
            )
        )


def _viewable_cache_files(
    cache_dir: pathlib.Path,
) -> list[tuple[pathlib.Path, int]]:
    """Return list of (path, size) for viewable (.brep) files under cache_dir."""
    all_files = _collect_cache_files(cache_dir)
    return [(p, s) for p, s in all_files if p.suffix.lower() == VIEWABLE_SUFFIX]


def _prompt_cache_view_selection(
    files: list[tuple[pathlib.Path, int]],
) -> pathlib.Path | None:
    """Show an interactive choice to pick one cache file to view. Returns path or None if cancelled."""
    if not files:
        return None
    choices = [
        questionary.Choice(
            title=f"{rel_path.as_posix()}  {_format_size(size)}",
            value=rel_path,
        )
        for rel_path, size in files
    ]
    selected = questionary.select(
        "Select a cache file to view",
        choices=choices,
    ).ask()
    return selected


@cli.command(
    name="view",
    help="Open a cache file in the CAD viewer. With no arguments, prompts to select a file interactively.",
)
@click.option(
    "-p", "--port", help="OCP Viewer port to send the model data to", default=3939
)
@click.option(
    "--camera",
    type=click.Choice([c.name.lower() for c in Camera], case_sensitive=False),
    default="reset",
    show_default=True,
    help="Camera preset when loading the model (from CAD viewer Camera enum).",
)
@click.argument(
    "path",
    required=False,
    type=click.Path(path_type=pathlib.Path),
)
@pass_env
def view_cache(
    env: Environment,
    port: int,
    camera: str,
    path: pathlib.Path | None,
):
    """Load a cache BREP file and show it in the CAD viewer."""
    from build123d import import_brep

    from ocp_vscode import show

    root = (
        env.cache_dir if env.cache_dir is not None else default_cache_dir()
    ).resolve()
    if not root.is_dir():
        click.echo(f"Cache directory does not exist: {root}")
        return

    if path is None:
        viewable = _viewable_cache_files(root)
        if not viewable:
            click.echo(f"No viewable cache files (.brep) in {root}")
            return
        rel = _prompt_cache_view_selection(viewable)
        if rel is None:
            click.echo("Cancelled.")
            return
        env.logger.info(
            "Tip: To skip the prompt next time, run: mr cache view %s",
            rel.as_posix(),
        )
        path = rel

    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        click.echo(f"Path is outside cache directory: {path}")
        raise SystemExit(2)
    if not target.is_file():
        click.echo(f"Not found or not a file: {path}")
        raise SystemExit(2)
    if target.suffix.lower() != VIEWABLE_SUFFIX:
        click.echo(f"Not a viewable cache file (expected {VIEWABLE_SUFFIX}): {path}")
        raise SystemExit(2)

    part = import_brep(target)
    camera_enum = Camera[camera.upper()]
    show(part, port=port, reset_camera=camera_enum)


@cli.command(
    name="prune",
    help="Remove cache files. With no arguments, prompts to select files interactively. Use --all to remove everything, --dangling to remove only orphaned files, or pass paths to remove specific files or folders.",
)
@click.option(
    "--all",
    "prune_all",
    is_flag=True,
    help="Remove all cache files.",
)
@click.option(
    "--dangling",
    "prune_dangling",
    is_flag=True,
    help="Remove only dangling cache files (no matching @cached function).",
)
@click.argument(
    "paths",
    nargs=-1,
    type=click.Path(path_type=pathlib.Path),
)
@pass_env
def prune_caches(
    env: Environment,
    prune_all: bool,
    prune_dangling: bool,
    paths: tuple[pathlib.Path, ...],
):
    """Delete cache files: either all (--all), only dangling (--dangling), or the given paths relative to the cache directory."""
    root = (
        env.cache_dir if env.cache_dir is not None else default_cache_dir()
    ).resolve()
    if not root.is_dir():
        click.echo(f"Cache directory does not exist: {root}")
        return
    if prune_all and prune_dangling:
        click.echo("Cannot use --all and --dangling together.")
        raise SystemExit(2)
    if prune_dangling and paths:
        click.echo("Cannot use --dangling and path arguments together.")
        raise SystemExit(2)
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
    if prune_dangling:
        from ...core.repo.repo import collect_from_repo

        registry = collect_from_repo()
        caches = registry.caches
        files = _collect_cache_files(root)
        module_name_files = _group_cache_files_by_module_name(files)
        dangling = _find_dangling_cache_files(caches, module_name_files)
        if not dangling:
            click.echo("No dangling cache files to remove.")
            return
        for rel_path, _ in dangling:
            (root / rel_path).unlink()
        # Remove empty dirs under root (only those that might be left after removing dangling)
        for d in sorted(root.rglob("*"), key=lambda x: -len(x.parts)):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        click.echo(f"Removed {len(dangling)} dangling cache file(s).")
        return
    files = _collect_cache_files(root)
    if not paths:
        if not files:
            click.echo("No cache files to remove.")
            return
        selected = _prompt_cache_prune_selection(files)
        if selected is None:
            click.echo("Cancelled.")
            return
        path_args = " ".join(p.as_posix() for p in selected)
        env.logger.info(
            "Tip: To skip the prompt next time, run: mr cache prune %s",
            path_args,
        )
        paths = selected
    else:
        # Paths provided: each must exist in the cache
        valid_paths: set[pathlib.Path] = set()
        for rel_path, _ in files:
            valid_paths.add(rel_path)
            valid_paths.update(rel_path.parents)
        for path in paths:
            target = (root / path).resolve()
            try:
                rel = target.relative_to(root)
            except ValueError:
                click.echo(f"Path is outside cache directory: {path}")
                raise SystemExit(2)
            if rel not in valid_paths:
                click.echo(f"Not in cache: {rel.as_posix()}")
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
