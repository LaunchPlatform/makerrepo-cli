import json
import logging
import pathlib

import click

from ..environment import Environment
from ..environment import pass_env
from ..shared import DEFAULT_EXPORT_FORMAT
from ..shared import EXPORT_FORMATS
from ..shared import export_shape_to_path
from ..shared import get_shape
from ..shared import item_display_name
from ..shared import item_safe_filename
from ..shared import print_items_table
from ..shared import prompt_item_selection
from ..shared import resolve_items
from ..shared import run_with_progress
from .cli import cli
from .utils import collect_from_repo

logger = logging.getLogger(__name__)


def _parse_payload(payload_str: str) -> dict:
    """Parse JSON payload from string or from file if value starts with @."""
    s = payload_str.strip()
    if s.startswith("@"):
        path = pathlib.Path(s[1:].strip())
        if not path.exists():
            raise FileNotFoundError(f"Payload file not found: {path}")
        return json.loads(path.read_text())
    return json.loads(s) if s else {}


def _realize_generators(
    target_generators: list,
    payload: dict,
    *,
    show_progress: bool = True,
) -> list:
    """Run generator.func(payload) for each generator, with progress bar."""

    def do_one(gen: object) -> object:
        f = getattr(gen, "func", None)
        if f is None:
            raise AttributeError(
                f"Generator {item_display_name(gen, 'generator')} has no .func"
            )
        return f(payload)

    return run_with_progress(
        target_generators,
        do_one,
        "Running generators",
        lambda g: item_display_name(g, "generator"),
        show_progress=show_progress,
    )


@cli.command(name="list", help="List generators")
@pass_env
def list_generators(env: Environment):
    registry = collect_from_repo()
    customizables = getattr(registry, "customizables", None)
    if not customizables:
        logger.error("No generators found")
        return

    env.logger.info(
        "Listing generators from current directory",
        extra={"markup": True, "highlighter": None},
    )
    print_items_table("Generators", customizables)


@cli.command(help="View generator output (accepts JSON payload)")
@click.argument("GENERATORS", nargs=-1)
@click.option(
    "-p",
    "--payload",
    default="{}",
    help="JSON payload for the generator (or @path/to/file.json)",
)
@click.option(
    "--port",
    help="OCP Viewer port to send the model data to",
    default=3939,
)
@pass_env
def view(
    env: Environment,
    generators: tuple[str, ...],
    payload: str,
    port: int,
):
    registry = collect_from_repo()
    customizables = getattr(registry, "customizables", None)
    if not customizables:
        logger.error("No generators found")
        return
    try:
        payload_dict = _parse_payload(payload)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error("Invalid payload: %s", e)
        return

    if not generators:
        target = prompt_item_selection(registry, "customizables", "generator")
        if target is None:
            logger.error("No generators selected")
            return
        gen_args = " ".join(item_display_name(g, "generator") for g in target)
        env.logger.info(
            "Tip: To skip the prompt next time, run: %s generators view -p '%s' %s",
            "mr",
            payload,
            gen_args,
        )
    else:
        try:
            target = resolve_items(registry, generators, "customizables", "generator")
        except ValueError as e:
            logger.error("%s", e)
            return

    realized = _realize_generators(target, payload_dict)
    from ocp_vscode import show

    show(realized, port=port)


@cli.command(
    help="Export generator output to STEP, STL, BREP, glTF, 3MF, SVG, or DXF (accepts JSON payload)"
)
@click.argument("GENERATORS", nargs=-1)
@click.option(
    "-p",
    "--payload",
    default="{}",
    help="JSON payload for the generator (or @path/to/file.json)",
)
@click.option(
    "-o",
    "--output",
    help="Output file or directory (default: current directory)",
    default=".",
    type=click.Path(path_type=pathlib.Path),
)
@click.option(
    "-f",
    "--format",
    "fmt",
    help="Export format (default: step, or inferred from -o extension)",
    type=click.Choice(EXPORT_FORMATS, case_sensitive=False),
    default=None,
)
@pass_env
def export(
    env: Environment,
    generators: tuple[str, ...],
    payload: str,
    output: pathlib.Path,
    fmt: str | None,
):
    registry = collect_from_repo()
    customizables = getattr(registry, "customizables", None)
    if not customizables:
        logger.error("No generators found")
        return
    try:
        payload_dict = _parse_payload(payload)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error("Invalid payload: %s", e)
        return

    if output.suffix:
        ext_normalized = output.suffix.lower().lstrip(".")
        if ext_normalized not in EXPORT_FORMATS:
            logger.error(
                "Unknown output extension %s. Supported: %s",
                output.suffix,
                ", ".join(EXPORT_FORMATS),
            )
            return

    if not generators:
        target = prompt_item_selection(registry, "customizables", "generator")
        if target is None:
            logger.error("No generators selected")
            return
        gen_args = " ".join(item_display_name(g, "generator") for g in target)
        env.logger.info(
            "Tip: To skip the prompt next time, run: %s generators export -p '%s' -o <path> %s",
            "mr",
            payload,
            gen_args,
        )
    else:
        try:
            target = resolve_items(registry, generators, "customizables", "generator")
        except ValueError as e:
            logger.error("%s", e)
            return

    realized = _realize_generators(target, payload_dict)
    shapes = [get_shape(obj) for obj in realized]

    if fmt is None:
        if output.suffix and output.suffix.lower().lstrip(".") in EXPORT_FORMATS:
            fmt = output.suffix.lower().lstrip(".")
        else:
            fmt = DEFAULT_EXPORT_FORMAT

    ext = f".{fmt}" if fmt != "step" else ".step"
    output_resolved = output.resolve()

    if len(shapes) == 0:
        logger.error("No shapes to export")
        return

    if len(shapes) == 1 and output_resolved.suffix:
        export_shape_to_path(shapes[0], output_resolved, fmt)
        env.logger.info("Exported to %s", output_resolved)
        return

    if len(shapes) > 1 and output_resolved.suffix:
        from build123d import Compound

        compound = Compound(children=shapes)
        export_shape_to_path(compound, output_resolved, fmt)
        env.logger.info("Exported %d generator(s) to %s", len(shapes), output_resolved)
        return

    out_dir = output_resolved if output_resolved.is_dir() else output_resolved
    if not out_dir.is_dir():
        out_dir.mkdir(parents=True, exist_ok=True)

    for gen, shape in zip(target, shapes):
        out_path = out_dir / f"{item_safe_filename(gen, 'generator')}{ext}"
        export_shape_to_path(shape, out_path, fmt)
        env.logger.info("Exported to %s", out_path)


@cli.command(
    name="snapshot",
    help="Capture a snapshot from generator output (accepts JSON payload)",
)
@click.argument("GENERATORS", nargs=-1)
@click.option(
    "-p",
    "--payload",
    default="{}",
    help="JSON payload for the generator (or @path/to/file.json)",
)
@click.option(
    "-o",
    "--output",
    help="Output image file path",
    default="snapshot.png",
    type=click.Path(path_type=pathlib.Path),
)
@pass_env
def snapshot(
    env: Environment,
    generators: tuple[str, ...],
    payload: str,
    output: pathlib.Path,
):
    import asyncio

    from ..artifacts.capture_image import CADViewerService
    from ..artifacts.utils import convert

    registry = collect_from_repo()
    customizables = getattr(registry, "customizables", None)
    if not customizables:
        logger.error("No generators found")
        return
    try:
        payload_dict = _parse_payload(payload)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error("Invalid payload: %s", e)
        return

    if not generators:
        target = prompt_item_selection(registry, "customizables", "generator")
        if target is None:
            logger.error("No generators selected")
            return
        gen_args = " ".join(item_display_name(g, "generator") for g in target)
        env.logger.info(
            "Tip: To skip the prompt next time, run: %s generators snapshot -p '%s' -o %s %s",
            "mr",
            payload,
            output,
            gen_args,
        )
    else:
        try:
            target = resolve_items(registry, generators, "customizables", "generator")
        except ValueError as e:
            logger.error("%s", e)
            return

    realized = _realize_generators(target, payload_dict)
    model_data = convert(*realized)

    async def capture_snapshot():
        env.logger.info("Starting CAD viewer service...")
        async with CADViewerService(logger=env.logger) as viewer:
            env.logger.info("Loading CAD model data...")
            await viewer.load_cad_data(model_data.model_dump(mode="json"))

            env.logger.info("Taking screenshot...")
            screenshot_bytes = await viewer.take_screenshot()

            output.write_bytes(screenshot_bytes)
            env.logger.info("Screenshot saved to %s", output.absolute())

    asyncio.run(capture_snapshot())
