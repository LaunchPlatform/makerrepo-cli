import json
import logging
import pathlib

import click
from ocp_vscode import Camera

from ...core.cache import make_default_cache_service
from ...core.cache import use_registry_cache
from ...core.repo.repo import collect_from_repo
from ..environment import Environment
from ..environment import pass_env
from ..shared.utils import all_items_flat
from ..shared.utils import apply_colormap_to_payload
from ..shared.utils import Colormap
from ..shared.utils import colormap_option_help
from ..shared.utils import convert
from ..shared.utils import DEFAULT_COLORMAP
from ..shared.utils import DEFAULT_EXPORT_FORMAT
from ..shared.utils import EXPORT_FORMATS
from ..shared.utils import export_shape_to_path
from ..shared.utils import get_build_version
from ..shared.utils import get_colormap
from ..shared.utils import get_shape
from ..shared.utils import item_display_name
from ..shared.utils import item_safe_filename
from ..shared.utils import item_to_list_payload
from ..shared.utils import ListOutputFormat
from ..shared.utils import print_items_table
from ..shared.utils import prompt_item_selection
from ..shared.utils import resolve_items
from ..shared.utils import run_with_progress
from ..shared.utils import select_model_from_result
from ..shared.utils import SNAPSHOT_CAMERA_CHOICES
from ..shared.utils import timed_block
from .cli import cli

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
    use_versioned: bool = False,
) -> list:
    """Run artifact.func() for each artifact, with progress bar and in-process cache."""

    def do_one(artifact: object) -> object:
        key = (
            getattr(artifact, "module", ""),
            getattr(artifact, "name", ""),
            use_versioned,
        )
        if key in _REALIZE_CACHE:
            return _REALIZE_CACHE[key]
        value = getattr(artifact, "func")()
        selected = select_model_from_result(
            value,
            use_versioned=use_versioned,
            context=item_display_name(artifact, "artifact"),
        )
        _REALIZE_CACHE[key] = selected
        return selected

    return run_with_progress(
        target_artifacts,
        do_one,
        "Realizing artifacts",
        lambda a: item_display_name(a, "artifact"),
        show_progress=show_progress,
    )


@cli.command(name="list", help="List artifacts")
@click.option(
    "-o",
    "--output",
    "output_format",
    type=click.Choice([f.value for f in ListOutputFormat], case_sensitive=False),
    default=None,
    help="Output format (default: table). Use -o json for JSON to stdout.",
)
@pass_env
def list_artifacts(env: Environment, output_format: str | None):
    registry = collect_from_repo()
    if not registry.artifacts:
        if output_format == ListOutputFormat.JSON.value:
            click.echo("[]")
        else:
            logger.error("No artifacts found")
        return

    if output_format == ListOutputFormat.JSON.value:
        items = [
            item_to_list_payload(item, module, name)
            for module, items_dict in registry.artifacts.items()
            for name, item in items_dict.items()
        ]
        click.echo(json.dumps(items, indent=2))
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
    "--camera",
    type=click.Choice([c.name.lower() for c in Camera], case_sensitive=False),
    default="reset",
    show_default=True,
    help="Camera preset when loading the model (from CAD viewer Camera enum)",
)
@click.option(
    "--colormap",
    type=click.Choice([c.value for c in Colormap], case_sensitive=False),
    default=DEFAULT_COLORMAP.value,
    show_default=True,
    help=colormap_option_help("artifacts"),
)
@click.option(
    "--versioned",
    is_flag=True,
    help="Use the versioned model for artifacts (if available)",
)
@click.option(
    "--render-joints",
    is_flag=True,
    help="Draw build123d joint helpers in the CAD viewer (ocp_vscode show render_joints)",
)
@pass_env
def view(
    env: Environment,
    artifacts: tuple[str, ...],
    port: int,
    camera: str,
    colormap: str,
    versioned: bool,
    render_joints: bool,
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

    with (
        use_registry_cache(
            registry,
            use_cache=env.use_cache,
            cache_service=(
                make_default_cache_service(env.cache_dir) if env.use_cache else None
            ),
        ),
        timed_block(env.logger),
    ):
        realized_artifacts = _realize_artifacts(
            target_artifacts,
            use_versioned=versioned,
        )
    from ocp_vscode import show

    camera_enum = Camera[camera.upper()]
    show_kwargs: dict = {
        "port": port,
        "names": [item_safe_filename(a, "artifact") for a in target_artifacts],
        "reset_camera": camera_enum,
    }
    if render_joints:
        show_kwargs["render_joints"] = True
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
@click.option(
    "--versioned",
    is_flag=True,
    help="Use the versioned model for artifacts (if available)",
)
@pass_env
def export(
    env: Environment,
    artifacts: tuple[str, ...],
    output: pathlib.Path,
    fmt: str | None,
    versioned: bool,
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

    with (
        use_registry_cache(
            registry,
            use_cache=env.use_cache,
            cache_service=make_default_cache_service(env.cache_dir)
            if env.use_cache
            else None,
        ),
        timed_block(env.logger),
    ):
        realized = _realize_artifacts(
            target_artifacts,
            use_versioned=versioned,
        )
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

    build_version = get_build_version()
    for artifact, shape in zip(target_artifacts, shapes):
        stem = item_safe_filename(artifact, "artifact")
        name = f"{stem}.{build_version}{ext}" if build_version else f"{stem}{ext}"
        out_path = out_dir / name
        export_shape_to_path(shape, out_path, fmt)
        env.logger.info("Exported to %s", out_path)


@cli.command(name="snapshot", help="Capture a snapshot from artifacts")
@click.argument("ARTIFACTS", nargs=-1)
@click.option(
    "-o",
    "--output",
    help="Output image file path (may use {build_version} placeholder)",
    default="snapshot.{build_version}.png",
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
    help=colormap_option_help("artifacts"),
)
@click.option(
    "--versioned",
    is_flag=True,
    help="Use the versioned model for artifacts (if available)",
)
@pass_env
def snapshot(
    env: Environment,
    artifacts: tuple[str, ...],
    output: pathlib.Path,
    camera: str,
    colormap: str,
    versioned: bool,
):
    """Capture a screenshot from artifacts."""
    import asyncio

    from ...core.capture_image import CADViewerService
    from ...core.capture_image import DEFAULT_CONFIG

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

    build_version = get_build_version()
    output = pathlib.Path(str(output).format(build_version=build_version))

    with (
        use_registry_cache(
            registry,
            use_cache=env.use_cache,
            cache_service=make_default_cache_service(env.cache_dir)
            if env.use_cache
            else None,
        ),
        timed_block(env.logger),
    ):
        realized_artifacts = _realize_artifacts(
            target_artifacts,
            use_versioned=versioned,
        )

    # Convert to model data format using convert from utils
    model_data = convert(realized_artifacts)

    effective_colormap = Colormap(colormap)
    apply_colormap_to_payload(model_data, effective_colormap)

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

            # Save screenshot to file
            output.write_bytes(screenshot_bytes)
            env.logger.info("Screenshot saved to %s", output.absolute())

    asyncio.run(capture_snapshot())
