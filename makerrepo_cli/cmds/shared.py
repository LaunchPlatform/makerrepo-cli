"""Shared helpers for artifact and generator subcommands."""
import enum
import logging
import pathlib
import time
from contextlib import contextmanager
from enum import StrEnum
from typing import Any
from typing import Callable

import click
import questionary
import rich
from rich import box
from rich.markup import escape
from rich.padding import Padding
from rich.progress import BarColumn
from rich.progress import Progress
from rich.progress import SpinnerColumn
from rich.progress import TaskProgressColumn
from rich.progress import TextColumn
from rich.table import Table

logger = logging.getLogger(__name__)

# Export formats: 3D (build123d export_* / Mesher) and 2D (project then ExportSVG/ExportDXF)
EXPORT_FORMATS_3D = ("step", "stl", "brep", "gltf", "3mf")
EXPORT_FORMATS_2D = ("svg", "dxf")
EXPORT_FORMATS = (*EXPORT_FORMATS_3D, *EXPORT_FORMATS_2D)
DEFAULT_EXPORT_FORMAT = "step"


@enum.unique
class ListOutputFormat(StrEnum):
    """Output format for list commands (kubectl-style -o). More formats may be added later."""

    JSON = "json"


TABLE_HEADER_STYLE = "yellow"
TABLE_COLUMN_STYLE = "cyan"


@enum.unique
class Colormap(StrEnum):
    NONE = "none"
    TAB10 = "tab10"
    TAB20 = "tab20"
    TAB20B = "tab20b"
    TAB20C = "tab20c"
    SET1 = "set1"
    SET2 = "set2"
    SET3 = "set3"
    PAIRED = "paired"
    DARK2 = "dark2"
    PASTEL1 = "pastel1"
    PASTEL2 = "pastel2"
    ACCENT = "accent"
    GOLDEN_RATIO = "golden_ratio"
    SEEDED = "seeded"
    SEGMENTED = "segmented"
    LISTED = "listed"


DEFAULT_COLORMAP = Colormap.NONE


@contextmanager
def timed_block(log: logging.Logger, message: str = "Model generated"):
    """Context manager that logs elapsed time when the block exits."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - t0
        log.info("%s in %.2f s", message, elapsed)


def rgba_to_hex(rgba: tuple[float, ...]) -> str:
    """Convert (r,g,b) or (r,g,b,a) in 0-1 range to #RRGGBB hex string."""
    r, g, b = int(rgba[0] * 255), int(rgba[1] * 255), int(rgba[2] * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def get_colormap(colormap: Colormap | str):
    """Return ocp_vscode ColorMap iterator for the given name, or None for 'none'."""
    from ocp_vscode import ColorMap

    name = colormap.lower() if isinstance(colormap, str) else colormap.value
    if name == Colormap.NONE.value:
        return None
    method = getattr(ColorMap, name)
    return method()


def apply_colormap_to_payload(payload: Any, colormap: Colormap | str) -> None:
    """Apply a colormap to each part in the payload (mutates in place)."""
    cmap = get_colormap(colormap)
    if cmap is None:
        return
    for part in payload.data.shapes.parts:
        color_tuple = next(cmap)
        part.color = rgba_to_hex(color_tuple)


def colormap_option_help(item_kind: str = "parts") -> str:
    """Default help text for --colormap option."""
    return f"Colormap to use for coloring {item_kind} (use 'none' to disable)"


def item_display_name(item: Any, default: str = "item") -> str:
    """Return display name for a registry item (e.g. 'module/name' or default)."""
    s = f"{getattr(item, 'module', '')}/{getattr(item, 'name', '')}".strip("/")
    return s or getattr(item, "name", default)


def all_items_flat(registry: Any, items_attr: str) -> list[tuple[str, str, Any]]:
    """Yield (module_name, item_name, item) for every item in registry.<items_attr>."""
    items_dict = getattr(registry, items_attr, {})
    result: list[tuple[str, str, Any]] = []
    for module_name, items in items_dict.items():
        for item_name, item in items.items():
            result.append((module_name, item_name, item))
    return result


def prompt_item_selection(
    registry: Any,
    items_attr: str,
    item_kind: str,
) -> list[Any] | None:
    """Show an interactive checkbox prompt to select item(s). Returns selected or None if cancelled."""
    flat = all_items_flat(registry, items_attr)
    if not flat:
        return None
    if len(flat) == 1:
        return [flat[0][2]]
    plural = f"{item_kind}s" if not item_kind.endswith("s") else item_kind
    choices = [
        questionary.Choice(title=f"{mod}/{name}", value=item)
        for mod, name, item in flat
    ]
    selected = questionary.checkbox(
        f"Select {plural} (Space to toggle, Enter to confirm)",
        choices=choices,
        validate=lambda x: (True if len(x) > 0 else f"Select at least one {item_kind}"),
    ).ask()
    return list(selected) if selected else None


def _flat_items_from_dict(
    items_dict: dict[str, dict[str, Any]],
) -> list[tuple[str, str, Any]]:
    """Yield (module_name, item_name, item) for every item in items_dict."""
    result: list[tuple[str, str, Any]] = []
    for module_name, items in items_dict.items():
        for item_name, item in items.items():
            result.append((module_name, item_name, item))
    return result


def prompt_single_item_selection(
    items_dict: dict[str, dict[str, Any]],
    item_kind: str,
) -> Any | None:
    """Show an interactive select prompt to pick one item. Returns [item] or None if cancelled."""
    flat = _flat_items_from_dict(items_dict)
    if not flat:
        return None
    if len(flat) == 1:
        return flat[0][2]
    choices = [
        questionary.Choice(title=f"{mod}/{name}", value=item)
        for mod, name, item in flat
    ]
    return questionary.select(
        f"Select one {item_kind}",
        choices=choices,
    ).ask()


def resolve_items(
    registry: Any,
    names: tuple[str, ...],
    items_attr: str,
    item_kind: str,
) -> list[Any]:
    """Resolve item names to objects. Names can be 'name' or 'module/item_name'."""
    flat = all_items_flat(registry, items_attr)
    if not flat:
        raise ValueError(f"No {item_kind}s found in repository")
    by_module = getattr(registry, items_attr, {})
    name_to_items: dict[str, list[tuple[str, Any]]] = {}
    for mod, item_name, item in flat:
        name_to_items.setdefault(item_name, []).append((mod, item))
    result: list[Any] = []
    for name in names:
        if "/" in name:
            mod, item_name = name.split("/", 1)
            if mod not in by_module or item_name not in by_module[mod]:
                raise ValueError(f"{item_kind.capitalize()} not found: {name}")
            result.append(by_module[mod][item_name])
        else:
            candidates = name_to_items.get(name, [])
            if len(candidates) == 0:
                raise ValueError(f"{item_kind.capitalize()} not found: {name}")
            if len(candidates) > 1:
                raise ValueError(
                    f"Ambiguous {item_kind} name '{name}'; use module/{item_kind}_name: "
                    + ", ".join(f"{m}/{getattr(a, 'name', '')}" for m, a in candidates)
                )
            result.append(candidates[0][1])
    return result


def run_with_progress(
    items: list[Any],
    do_one: Callable[[Any], Any],
    task_label: str,
    describe_fn: Callable[[Any], str],
    *,
    show_progress: bool = True,
) -> list[Any]:
    """Run do_one(item) for each item with a progress bar. Returns list of results."""
    if not items:
        return []
    total = len(items)
    if show_progress and total > 0:
        realized: list[Any] = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
        ) as progress:
            task = progress.add_task(f"{task_label}...", total=total)
            for item in items:
                progress.update(task, description=f"{describe_fn(item)}...")
                realized.append(do_one(item))
                progress.advance(task)
        return realized
    return [do_one(item) for item in items]


def get_shape(obj: Any) -> Any:
    """Return a build123d Shape from a realized item (e.g. BasePartObject.part or Shape)."""
    return getattr(obj, "part", obj)


def export_shape_to_path(shape: Any, path: pathlib.Path, fmt: str) -> None:
    """Export a single build123d Shape to path using format fmt."""
    fmt_lower = fmt.lower()
    path = pathlib.Path(path)

    if fmt_lower in EXPORT_FORMATS_3D:
        from build123d import export_brep
        from build123d import export_gltf
        from build123d import export_step
        from build123d import export_stl
        from build123d import Mesher

        if fmt_lower == "step":
            export_step(shape, path)
        elif fmt_lower == "stl":
            export_stl(shape, path)
        elif fmt_lower == "brep":
            export_brep(shape, path)
        elif fmt_lower == "gltf":
            export_gltf(shape, path)
        elif fmt_lower == "3mf":
            mesher = Mesher()
            mesher.add_shape(shape)
            mesher.write(path)
    elif fmt_lower in EXPORT_FORMATS_2D:
        from build123d import Compound
        from build123d import ExportDXF
        from build123d import ExportSVG
        from build123d import LineType
        from build123d import Unit

        view_port_origin = (-100, -50, 30)
        visible, hidden = shape.project_to_viewport(view_port_origin)
        max_dimension = max(*Compound(children=visible + hidden).bounding_box().size)
        scale = 100 / max_dimension if max_dimension > 0 else 1.0

        if fmt_lower == "svg":
            exporter = ExportSVG(scale=scale)
        else:
            exporter = ExportDXF(unit=Unit.MM)

        exporter.add_layer("Visible")
        exporter.add_layer("Hidden", line_type=LineType.ISO_DOT)
        exporter.add_shape(visible, layer="Visible")
        exporter.add_shape(hidden, layer="Hidden")
        exporter.write(path)
    else:
        logger.error("Unsupported export format: %s", fmt)


def item_safe_filename(item: Any, default_name: str = "item") -> str:
    """Return a safe filename stem for an item (module_name or name)."""
    mod = getattr(item, "module", "")
    name = getattr(item, "name", default_name)
    safe = f"{mod}_{name}".strip("_") if mod else name
    return safe.replace("/", "_")


def item_to_list_payload(item: Any, module: str, name: str) -> dict[str, Any]:
    """Build a JSON-serializable dict for a registry item (artifact or customizable).

    Includes module, name, and any other attribute on the item that is serializable
    (e.g. sample, filename, lineno from the mr lib). Skips private names and callables.
    """
    payload: dict[str, Any] = {}
    for attr in dir(item):
        if attr.startswith("_"):
            continue
        try:
            val = getattr(item, attr)
        except AttributeError:
            continue
        if callable(val):
            continue
        if val is None or isinstance(val, (str, int, float, bool)):
            payload[attr] = val
        elif isinstance(val, pathlib.Path):
            payload[attr] = str(val)
    payload["module"] = module
    payload["name"] = name
    # Ensure sample is always present when the item has it (e.g. may be non-scalar)
    if "sample" not in payload and hasattr(item, "sample"):
        try:
            payload["sample"] = str(getattr(item, "sample", ""))
        except Exception:
            pass
    return payload


def print_items_table(
    title: str,
    items_dict: dict[str, dict[str, Any]],
    sample_attr: str = "sample",
) -> None:
    """Print a rich table of items (Module, Name, Sample)."""
    table = Table(
        title=title,
        box=box.SIMPLE,
        header_style=TABLE_HEADER_STYLE,
        expand=True,
    )
    table.add_column("Module", style=TABLE_COLUMN_STYLE)
    table.add_column("Name", style=TABLE_COLUMN_STYLE)
    table.add_column("Sample", style=TABLE_COLUMN_STYLE)
    for module, items in items_dict.items():
        for i, (name, item) in enumerate(items.items()):
            sample = getattr(item, sample_attr, "")
            table.add_row(
                escape(module) if i == 0 else "",
                escape(name),
                str(sample) if sample else "",
            )
    rich.print(Padding(table, (1, 0, 0, 4)))
