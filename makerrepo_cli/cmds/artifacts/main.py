import logging
import pathlib

import click

from ..environment import Environment
from ..environment import pass_env
from ..shared import all_items_flat
from ..shared import apply_colormap_to_payload
from ..shared import Colormap
from ..shared import colormap_option_help
from ..shared import DEFAULT_COLORMAP
from ..shared import DEFAULT_EXPORT_FORMAT
from ..shared import EXPORT_FORMATS
from ..shared import export_shape_to_path
from ..shared import get_colormap
from ..shared import get_shape
from ..shared import item_display_name
from ..shared import item_safe_filename
from ..shared import print_items_table
from ..shared import prompt_item_selection
from ..shared import resolve_items
from ..shared import run_with_progress
from .cli import cli
from .utils import collect_from_repo
from .utils import convert

logger = logging.getLogger(__name__)

# Wrappers for tests that mock or use these directly
_all_artifacts_flat = lambda registry: all_items_flat(registry, "artifacts")
_prompt_artifact_selection = lambda registry: prompt_item_selection(
    registry, "artifacts", "artifact"
)

_REALIZE_CACHE: dict[tuple[str, str], object] = {}


def _realize_artifacts(
    target_artifacts: list,
    *,
    show_progress: bool = True,
) -> list:
    """Run artifact.func() for each artifact, with progress bar and in-process cache."""

    def do_one(artifact: object) -> object:
        key = (getattr(artifact, "module", ""), getattr(artifact, "name", ""))
        if key in _REALIZE_CACHE:
            return _REALIZE_CACHE[key]
        value = getattr(artifact, "func")()
        _REALIZE_CACHE[key] = value
        return value

    return run_with_progress(
        target_artifacts,
        do_one,
        "Realizing artifacts",
        lambda a: item_display_name(a, "artifact"),
        show_progress=show_progress,
    )


@cli.command(name="list", help="List artifacts")
@pass_env
def list_artifacts(env: Environment):
    registry = collect_from_repo()
    if not registry.artifacts:
        logger.error("No artifacts found")
        return

    env.logger.info(
        "Listing artifacts from current directory",
        extra={"markup": True, "highlighter": None},
    )
    print_items_table("Artifacts", registry.artifacts)


@cli.command(help="View artifact")
@click.argument("ARTIFACTS", nargs=-1)
@click.option(
    "-p", "--port", help="OCP Viewer port to send the model data to", default=3939
)
@click.option(
    "--colormap",
    type=click.Choice([c.value for c in Colormap], case_sensitive=False),
    default=DEFAULT_COLORMAP.value,
    show_default=True,
    help=colormap_option_help("artifacts"),
)
@pass_env
def view(
    env: Environment,
    artifacts: tuple[str, ...],
    port: int,
    colormap: str,
):
    registry = collect_from_repo()
    if not registry.artifacts:
        logger.error("No artifacts found")
        return
    if not artifacts:
        target_artifacts = _prompt_artifact_selection(registry)
        if target_artifacts is None:
            logger.error("No artifacts selected")
            return
        artifact_args = " ".join(
            item_display_name(a, "artifact") for a in target_artifacts
        )
        env.logger.info(
            "Tip: To skip the prompt next time, run: %s artifacts view %s",
            "mr",
            artifact_args,
        )
    else:
        target_artifacts = resolve_items(registry, artifacts, "artifacts", "artifact")

    realized_artifacts = _realize_artifacts(target_artifacts)
    from ocp_vscode import show

    show_kwargs: dict = {
        "port": port,
        "names": [item_safe_filename(a, "artifact") for a in target_artifacts],
    }
    effective_colormap = Colormap(colormap)
    cmap = get_colormap(effective_colormap)
    if cmap is not None:
        show_kwargs["colors"] = cmap

    show(*realized_artifacts, **show_kwargs)


@cli.command(help="Export artifact(s) to STEP, STL, BREP, glTF, 3MF, SVG, or DXF")
@click.argument("ARTIFACTS", nargs=-1)
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
    env: Environment, artifacts: tuple[str, ...], output: pathlib.Path, fmt: str | None
):
    registry = collect_from_repo()
    if not registry.artifacts:
        logger.error("No artifacts found")
        return

    # Reject unknown output extensions so we never write with a wrong/misleading ext
    if output.suffix:
        ext_normalized = output.suffix.lower().lstrip(".")
        if ext_normalized not in EXPORT_FORMATS:
            logger.error(
                "Unknown output extension %s. Supported: %s",
                output.suffix,
                ", ".join(EXPORT_FORMATS),
            )
            return

    if not artifacts:
        target_artifacts = _prompt_artifact_selection(registry)
        if target_artifacts is None:
            logger.error("No artifacts selected")
            return
        artifact_args = " ".join(
            item_display_name(a, "artifact") for a in target_artifacts
        )
        env.logger.info(
            "Tip: To skip the prompt next time, run: %s artifacts export -o <path> %s",
            "mr",
            artifact_args,
        )
    else:
        target_artifacts = resolve_items(registry, artifacts, "artifacts", "artifact")

    realized = _realize_artifacts(target_artifacts)
    shapes = [get_shape(obj) for obj in realized]

    # Infer format from output path if not given
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

    # Single shape and output path has a file extension -> write to that file
    if len(shapes) == 1 and output_resolved.suffix:
        export_shape_to_path(shapes[0], output_resolved, fmt)
        env.logger.info("Exported to %s", output_resolved)
        return

    # Multiple shapes and output path has a file extension -> one compound to that file
    if len(shapes) > 1 and output_resolved.suffix:
        from build123d import Compound

        compound = Compound(children=shapes)
        export_shape_to_path(compound, output_resolved, fmt)
        env.logger.info("Exported %d artifact(s) to %s", len(shapes), output_resolved)
        return

    # Output is a directory: one file per artifact
    out_dir = output_resolved if output_resolved.is_dir() else output_resolved
    if not out_dir.is_dir():
        out_dir.mkdir(parents=True, exist_ok=True)

    for artifact, shape in zip(target_artifacts, shapes):
        out_path = out_dir / f"{item_safe_filename(artifact, 'artifact')}{ext}"
        export_shape_to_path(shape, out_path, fmt)
        env.logger.info("Exported to %s", out_path)


@cli.command(name="snapshot", help="Capture a snapshot from artifacts")
@click.argument("ARTIFACTS", nargs=-1)
@click.option(
    "-o",
    "--output",
    help="Output image file path",
    default="snapshot.png",
    type=click.Path(path_type=pathlib.Path),
)
@click.option(
    "--colormap",
    type=click.Choice([c.value for c in Colormap], case_sensitive=False),
    default=DEFAULT_COLORMAP.value,
    show_default=True,
    help=colormap_option_help("artifacts"),
)
@pass_env
def snapshot(
    env: Environment,
    artifacts: tuple[str, ...],
    output: pathlib.Path,
    colormap: str,
):
    """Capture a screenshot from artifacts."""
    import asyncio

    from .capture_image import CADViewerService

    registry = collect_from_repo()
    if not registry.artifacts:
        logger.error("No artifacts found")
        return
    if not artifacts:
        target_artifacts = _prompt_artifact_selection(registry)
        if target_artifacts is None:
            logger.error("No artifacts selected")
            return
        artifact_args = " ".join(
            item_display_name(a, "artifact") for a in target_artifacts
        )
        env.logger.info(
            "Tip: To skip the prompt next time, run: %s artifacts snapshot -o %s %s",
            "mr",
            output,
            artifact_args,
        )
    else:
        target_artifacts = resolve_items(registry, artifacts, "artifacts", "artifact")

    realized_artifacts = _realize_artifacts(target_artifacts)

    # Convert to model data format using convert from utils
    model_data = convert(realized_artifacts)

    effective_colormap = Colormap(colormap)
    apply_colormap_to_payload(model_data, effective_colormap)

    async def capture_snapshot():
        env.logger.info("Starting CAD viewer service...")
        async with CADViewerService(logger=env.logger) as viewer:
            env.logger.info("Loading CAD model data...")
            await viewer.load_cad_data(model_data.model_dump(mode="json"))

            env.logger.info("Taking screenshot...")
            screenshot_bytes = await viewer.take_screenshot()

            # Save screenshot to file
            output.write_bytes(screenshot_bytes)
            env.logger.info("Screenshot saved to %s", output.absolute())

    asyncio.run(capture_snapshot())
