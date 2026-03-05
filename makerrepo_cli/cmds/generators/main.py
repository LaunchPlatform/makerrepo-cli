import json
import logging
import pathlib
import sys

import click
import rich
from mr import Customizable
from mr import GeneratorValidationError
from ocp_vscode import Camera
from pydantic import BaseModel
from pydantic import ValidationError

from ..environment import Environment
from ..environment import pass_env
from ..shared.repo import collect_from_repo
from ..shared.utils import apply_colormap_to_payload
from ..shared.utils import Colormap
from ..shared.utils import colormap_option_help
from ..shared.utils import DEFAULT_COLORMAP
from ..shared.utils import DEFAULT_EXPORT_FORMAT
from ..shared.utils import EXPORT_FORMATS
from ..shared.utils import export_shape_to_path
from ..shared.utils import get_colormap
from ..shared.utils import get_shape
from ..shared.utils import item_display_name
from ..shared.utils import item_safe_filename
from ..shared.utils import item_to_list_payload
from ..shared.utils import ListOutputFormat
from ..shared.utils import print_items_table
from ..shared.utils import prompt_single_item_selection
from ..shared.utils import resolve_items
from ..shared.utils import SNAPSHOT_CAMERA_CHOICES
from ..shared.utils import timed_block
from .cli import cli

logger = logging.getLogger(__name__)


def _parse_payload(payload_str: str) -> dict:
    """Parse JSON payload from string, from file if value starts with @, or from stdin if -."""
    s = payload_str.strip()
    if s == "-":
        if sys.stdin.isatty():
            eof_hint = "Ctrl+Z then Enter" if sys.platform == "win32" else "Ctrl+D"
            rich.print(f"[dim]Enter JSON payload (end with {eof_hint}):[/dim]")
        return json.loads(sys.stdin.read())
    if s.startswith("@"):
        path = pathlib.Path(s[1:].strip())
        if not path.exists():
            raise FileNotFoundError(f"Payload file not found: {path}")
        return json.loads(path.read_text())
    return json.loads(s) if s else {}


def _format_validation_error(e: ValidationError) -> str:
    """Format Pydantic ValidationError as a user-friendly message."""
    lines = []
    for err in e.errors():
        loc = err.get("loc", ())
        path = ".".join(str(x) for x in loc if x != "__root__")
        msg = err.get("msg", "validation error")
        if path:
            lines.append(f"  {path}: {msg}")
        else:
            lines.append(f"  {msg}")
    return "\n".join(lines) if lines else str(e)


def _validate_params(
    customizable: Customizable,
    payload: dict,
) -> BaseModel | dict | None:
    """Validate payload against the generator's parameters_schema; return validated model or payload when no schema.
    Returns None on validation failure (error is logged)."""
    schema = getattr(customizable, "parameters_schema", None)
    if schema is None:
        return payload
    try:
        return schema.model_validate(payload)
    except ValidationError as e:
        gen_name = item_display_name(customizable, "generator")
        logger.error(
            "Payload validation failed for %s:\n%s",
            gen_name,
            _format_validation_error(e),
        )
        return None


def _realize_generator(
    customizable: Customizable,
    params: BaseModel,
) -> object:
    """Run generator.func(params) and return the result. Handles GeneratorValidationError."""
    try:
        return customizable.func(params)
    except GeneratorValidationError as e:
        gen_name = item_display_name(customizable, "generator")
        lines = [
            f"Validation failed for {gen_name}: {e.args[0] if e.args else 'Invalid parameters'}"
        ]
        for field_err in getattr(e, "fields", []) or []:
            path = ".".join(str(p) for p in getattr(field_err, "path", ()))
            msg = getattr(field_err, "message", str(field_err))
            lines.append(f"  {path}: {msg}" if path else f"  {msg}")
        logger.error("\n".join(lines))
        raise click.ClickException("Parameter validation failed")


@cli.command(name="list", help="List generators")
@click.option(
    "-o",
    "--output",
    "output_format",
    type=click.Choice([f.value for f in ListOutputFormat], case_sensitive=False),
    default=None,
    help="Output format (default: table). Use -o json for JSON to stdout.",
)
@pass_env
def list_generators(env: Environment, output_format: str | None):
    registry = collect_from_repo()
    customizables = getattr(registry, "customizables", None)
    if not customizables:
        if output_format == ListOutputFormat.JSON.value:
            click.echo("[]")
        else:
            logger.error("No generators found")
        return

    if output_format == ListOutputFormat.JSON.value:
        items = [
            item_to_list_payload(item, module, name)
            for module, items_dict in customizables.items()
            for name, item in items_dict.items()
        ]
        click.echo(json.dumps(items, indent=2))
        return

    env.logger.info(
        "Listing generators from current directory",
        extra={"markup": True, "highlighter": None},
    )
    print_items_table("Generators", customizables)


@cli.command(help="View generator output (accepts JSON payload)")
@click.argument("GENERATOR", required=False)
@click.option(
    "-p",
    "--payload",
    default="{}",
    help="JSON payload for the generator (@path/to/file.json, or - for stdin)",
)
@click.option(
    "--port",
    help="OCP Viewer port to send the model data to",
    default=3939,
)
@click.option(
    "--camera",
    type=click.Choice([c.name.lower() for c in Camera], case_sensitive=False),
    default=Camera.RESET.name.lower(),
    show_default=True,
    help="Camera preset when loading the model (from CAD viewer Camera enum)",
)
@click.option(
    "--colormap",
    type=click.Choice([c.value for c in Colormap], case_sensitive=False),
    default=DEFAULT_COLORMAP.value,
    show_default=True,
    help=colormap_option_help("generator output"),
)
@pass_env
def view(
    env: Environment,
    generator: str | None,
    payload: str,
    port: int,
    camera: str,
    colormap: str,
):
    registry = collect_from_repo()
    customizables = registry.customizables
    if not customizables:
        logger.error("No generators found")
        return
    try:
        payload_dict = _parse_payload(payload)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error("Invalid payload: %s", e)
        return

    if generator is None or generator == "":
        gen = prompt_single_item_selection(customizables, "generator")
        if gen is None:
            logger.error("No generator selected")
            return
        gen_arg = item_display_name(gen, "generator")
        env.logger.info(
            "Tip: To skip the prompt next time, run: %s generators view -p '%s' %s",
            "mr",
            payload,
            gen_arg,
        )
    else:
        try:
            gen = resolve_items(registry, (generator,), "customizables", "generator")[0]
        except ValueError as exc:
            env.logger.error("Failed to resolve generator %s: %s", generator, exc)
            exit(-1)

    params = _validate_params(gen, payload_dict)
    if params is None:
        sys.exit(1)
    with timed_block(env.logger):
        realized = _realize_generator(gen, params)
    from ocp_vscode import show

    camera_enum = Camera[camera.upper()]
    show_kwargs: dict = {"port": port, "reset_camera": camera_enum}
    cmap = get_colormap(Colormap(colormap))
    if cmap is not None:
        show_kwargs["colors"] = cmap
    show([realized], **show_kwargs)


@cli.command(
    help="Export generator output to STEP, STL, BREP, glTF, 3MF, SVG, or DXF (accepts JSON payload)"
)
@click.argument("GENERATOR", required=False)
@click.option(
    "-p",
    "--payload",
    default="{}",
    help="JSON payload for the generator (@path/to/file.json, or - for stdin)",
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
    generator: str | None,
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

    if generator is None or generator == "":
        gen = prompt_single_item_selection(customizables, "generator")
        if gen is None:
            logger.error("No generator selected")
            return
        gen_arg = item_display_name(gen, "generator")
        env.logger.info(
            "Tip: To skip the prompt next time, run: %s generators export -p '%s' -o <path> %s",
            "mr",
            payload,
            gen_arg,
        )
    else:
        try:
            gen = resolve_items(registry, (generator,), "customizables", "generator")[0]
        except ValueError as e:
            logger.error("%s", e)
            return

    params = _validate_params(gen, payload_dict)
    if params is None:
        sys.exit(1)
    with timed_block(env.logger):
        realized = _realize_generator(gen, params)
    shape = get_shape(realized)

    if fmt is None:
        if output.suffix and output.suffix.lower().lstrip(".") in EXPORT_FORMATS:
            fmt = output.suffix.lower().lstrip(".")
        else:
            fmt = DEFAULT_EXPORT_FORMAT

    ext = f".{fmt}" if fmt != "step" else ".step"
    output_resolved = output.resolve()

    if shape is None:
        logger.error("No shape to export")
        return

    if output_resolved.suffix:
        export_shape_to_path(shape, output_resolved, fmt)
        env.logger.info("Exported to %s", output_resolved)
        return

    out_dir = output_resolved if output_resolved.is_dir() else output_resolved
    if not out_dir.is_dir():
        out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{item_safe_filename(gen, 'generator')}{ext}"
    export_shape_to_path(shape, out_path, fmt)
    env.logger.info("Exported to %s", out_path)


@cli.command(
    name="snapshot",
    help="Capture a snapshot from generator output (accepts JSON payload)",
)
@click.argument("GENERATOR", required=False)
@click.option(
    "-p",
    "--payload",
    default="{}",
    help="JSON payload for the generator (@path/to/file.json, or - for stdin)",
)
@click.option(
    "-o",
    "--output",
    help="Output image file path",
    default="snapshot.png",
    type=click.Path(path_type=pathlib.Path),
)
@click.option(
    "--camera",
    type=click.Choice(SNAPSHOT_CAMERA_CHOICES, case_sensitive=False),
    default="iso",
    show_default=True,
    help="Camera view preset for the snapshot (view presets only)",
)
@click.option(
    "--colormap",
    type=click.Choice([c.value for c in Colormap], case_sensitive=False),
    default=DEFAULT_COLORMAP.value,
    show_default=True,
    help=colormap_option_help("generator output"),
)
@pass_env
def snapshot(
    env: Environment,
    generator: str | None,
    payload: str,
    output: pathlib.Path,
    camera: str,
    colormap: str,
):
    import asyncio

    from ..shared.capture_image import CADViewerService
    from ..shared.capture_image import DEFAULT_CONFIG
    from ..shared.utils import convert

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

    if generator is None or generator == "":
        gen = prompt_single_item_selection(customizables, "generator")
        if gen is None:
            logger.error("No generator selected")
            return
        gen_arg = item_display_name(gen, "generator")
        env.logger.info(
            "Tip: To skip the prompt next time, run: %s generators snapshot -p '%s' -o %s %s",
            "mr",
            payload,
            output,
            gen_arg,
        )
    else:
        try:
            gen = resolve_items(registry, (generator,), "customizables", "generator")[0]
        except ValueError as e:
            logger.error("%s", e)
            return

    params = _validate_params(gen, payload_dict)
    if params is None:
        sys.exit(1)
    with timed_block(env.logger):
        realized = _realize_generator(gen, params)
    model_data = convert(realized)

    apply_colormap_to_payload(model_data, Colormap(colormap))

    viewer_config = {**DEFAULT_CONFIG, "reset_camera": camera}

    async def capture_snapshot():
        env.logger.info("Starting CAD viewer service...")
        async with CADViewerService(logger=env.logger) as viewer:
            env.logger.info("Loading CAD model data...")
            await viewer.load_cad_data(
                model_data.model_dump(mode="json"), config=viewer_config
            )

            env.logger.info("Taking screenshot...")
            screenshot_bytes = await viewer.take_screenshot()

            output.write_bytes(screenshot_bytes)
            env.logger.info("Screenshot saved to %s", output.absolute())

    asyncio.run(capture_snapshot())
