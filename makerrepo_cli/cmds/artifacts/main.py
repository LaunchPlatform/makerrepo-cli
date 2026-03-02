import logging
import pathlib
import sys

import click
import questionary
import rich
from mr.artifacts.registry import Registry
from rich import box
from rich.markup import escape
from rich.padding import Padding
from rich.progress import BarColumn
from rich.progress import Progress
from rich.progress import SpinnerColumn
from rich.progress import TaskProgressColumn
from rich.progress import TextColumn
from rich.table import Table

from ..environment import Environment
from ..environment import pass_env
from .cli import cli
from .utils import collect_from_repo
from .utils import convert

logger = logging.getLogger(__name__)

# Supported export formats: 3D (build123d export_* / Mesher) and 2D (project then ExportSVG/ExportDXF)
EXPORT_FORMATS_3D = ("step", "stl", "brep", "gltf", "3mf")
EXPORT_FORMATS_2D = ("svg", "dxf")
EXPORT_FORMATS = (*EXPORT_FORMATS_3D, *EXPORT_FORMATS_2D)
DEFAULT_FORMAT = "step"
TABLE_HEADER_STYLE = "yellow"
TABLE_COLUMN_STYLE = "cyan"


def _artifact_display_name(artifact) -> str:
    """Return display name for an artifact (e.g. 'module/name' or 'artifact')."""
    s = f"{getattr(artifact, 'module', '')}/{getattr(artifact, 'name', '')}".strip("/")
    return s or getattr(artifact, "name", "artifact")


def _all_artifacts_flat(registry: Registry) -> list[tuple[str, str, object]]:
    """Yield (module_name, artifact_name, artifact) for every artifact."""
    for module_name, artifacts in registry.artifacts.items():
        for artifact_name, artifact in artifacts.items():
            yield (module_name, artifact_name, artifact)


def _prompt_artifact_selection(registry: Registry) -> list | None:
    """Show an interactive checkbox prompt to select artifact(s). Returns selected artifacts or None if cancelled."""
    flat = list(_all_artifacts_flat(registry))
    if not flat:
        return None
    if len(flat) == 1:
        return [flat[0][2]]
    choices = [
        questionary.Choice(title=f"{mod}/{name}", value=art) for mod, name, art in flat
    ]
    selected = questionary.checkbox(
        "Select artifact(s) (Space to toggle, Enter to confirm)",
        choices=choices,
        validate=lambda x: (True if len(x) > 0 else "Select at least one artifact"),
    ).ask()
    return list(selected) if selected else None


def _resolve_artifacts(registry: Registry, names: tuple[str, ...]) -> list:
    """Resolve artifact names to artifact objects. Names can be 'name' or 'module/artifact_name'."""
    flat = list(_all_artifacts_flat(registry))
    if not flat:
        raise ValueError("No artifacts found in repository")
    by_module_name: dict[str, dict] = registry.artifacts
    name_to_artifacts: dict[str, list[tuple[str, object]]] = {}
    for mod, art_name, art in flat:
        name_to_artifacts.setdefault(art_name, []).append((mod, art))
    result = []
    for name in names:
        if "/" in name:
            mod, art_name = name.split("/", 1)
            if mod not in by_module_name or art_name not in by_module_name[mod]:
                raise ValueError(f"Artifact not found: {name}")
            result.append(by_module_name[mod][art_name])
        else:
            candidates = name_to_artifacts.get(name, [])
            if len(candidates) == 0:
                raise ValueError(f"Artifact not found: {name}")
            if len(candidates) > 1:
                raise ValueError(
                    f"Ambiguous artifact name '{name}'; use module/artifact_name: "
                    + ", ".join(f"{m}/{a.name}" for m, a in candidates)
                )
            result.append(candidates[0][1])
    return result


_REALIZE_CACHE: dict[tuple[str, str], object] = {}


def _realize_artifacts(
    target_artifacts: list,
    *,
    show_progress: bool = True,
) -> list:
    """Run artifact.func() for each artifact, with progress bar and in-process cache."""
    if not target_artifacts:
        return []
    realized: list = []
    total = len(target_artifacts)

    def do_one(artifact) -> object:
        key = (getattr(artifact, "module", ""), getattr(artifact, "name", ""))
        if key in _REALIZE_CACHE:
            return _REALIZE_CACHE[key]
        value = artifact.func()
        _REALIZE_CACHE[key] = value
        return value

    if show_progress and total > 0:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
        ) as progress:
            task = progress.add_task("Realizing artifacts...", total=total)
            for artifact in target_artifacts:
                label = _artifact_display_name(artifact)
                progress.update(task, description=f"Realizing {label}...")
                realized.append(do_one(artifact))
                progress.advance(task)
    else:
        realized = [do_one(a) for a in target_artifacts]
    return realized


def _get_shape(obj: object):
    """Return a build123d Shape from a realized artifact (e.g. BasePartObject.part or Shape)."""
    return getattr(obj, "part", obj)


def _export_shape_to_path(shape, path: pathlib.Path, fmt: str) -> None:
    """Export a single build123d Shape to path using format fmt. Uses lazy build123d imports."""
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
        # 2D: project 3D to viewport then export
        from build123d import Compound
        from build123d import ExportDXF
        from build123d import ExportSVG
        from build123d import LineType
        from build123d import Unit

        view_port_origin = (-100, -50, 30)  # default camera position for projection
        visible, hidden = shape.project_to_viewport(view_port_origin)
        max_dimension = max(*Compound(children=visible + hidden).bounding_box().size)
        scale = 100 / max_dimension if max_dimension > 0 else 1.0

        if fmt_lower == "svg":
            exporter = ExportSVG(scale=scale)
        else:  # dxf
            exporter = ExportDXF(unit=Unit.MM)

        exporter.add_layer("Visible")
        exporter.add_layer("Hidden", line_type=LineType.ISO_DOT)
        exporter.add_shape(visible, layer="Visible")
        exporter.add_shape(hidden, layer="Hidden")
        exporter.write(path)
    else:
        logger.error("Unsupported export format: %s", fmt)


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

    table = Table(
        title="Artifacts",
        box=box.SIMPLE,
        header_style=TABLE_HEADER_STYLE,
        expand=True,
    )
    table.add_column("Module", style=TABLE_COLUMN_STYLE)
    table.add_column("Name", style=TABLE_COLUMN_STYLE)
    table.add_column("Sample", style=TABLE_COLUMN_STYLE)
    for module, artifacts in registry.artifacts.items():
        for i, (name, artifact) in enumerate(artifacts.items()):
            table.add_row(
                escape(module) if i == 0 else "", escape(name), str(artifact.sample)
            )
    rich.print(Padding(table, (1, 0, 0, 4)))


@cli.command(help="View artifact")
@click.argument("ARTIFACTS", nargs=-1)
@click.option(
    "-p", "--port", help="OCP Viewer port to send the model data to", default=3939
)
@pass_env
def view(env: Environment, artifacts: tuple[str, ...], port: int):
    registry = collect_from_repo()
    if not registry.artifacts:
        logger.error("No artifacts found")
        return
    if not artifacts:
        target_artifacts = _prompt_artifact_selection(registry)
        if target_artifacts is None:
            logger.error("No artifacts selected")
            return
        artifact_args = " ".join(_artifact_display_name(a) for a in target_artifacts)
        env.logger.info(
            "Tip: To skip the prompt next time, run: %s artifacts view %s",
            "mr",
            artifact_args,
        )
    else:
        target_artifacts = _resolve_artifacts(registry, artifacts)

    # Realize artifacts (with progress bar and in-process cache)
    realized_artifacts = _realize_artifacts(target_artifacts)
    # defer the import to make testing mocking much easier
    from ocp_vscode import show

    # TODO: pass in some args
    show(realized_artifacts, port=port)


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
        artifact_args = " ".join(_artifact_display_name(a) for a in target_artifacts)
        env.logger.info(
            "Tip: To skip the prompt next time, run: %s artifacts export -o <path> %s",
            "mr",
            artifact_args,
        )
    else:
        target_artifacts = _resolve_artifacts(registry, artifacts)

    realized = _realize_artifacts(target_artifacts)
    shapes = [_get_shape(obj) for obj in realized]

    # Infer format from output path if not given
    if fmt is None:
        if output.suffix and output.suffix.lower().lstrip(".") in EXPORT_FORMATS:
            fmt = output.suffix.lower().lstrip(".")
        else:
            fmt = DEFAULT_FORMAT

    ext = f".{fmt}" if fmt != "step" else ".step"
    output_resolved = output.resolve()

    if len(shapes) == 0:
        logger.error("No shapes to export")
        return

    # Single shape and output path has a file extension -> write to that file
    if len(shapes) == 1 and output_resolved.suffix:
        _export_shape_to_path(shapes[0], output_resolved, fmt)
        env.logger.info("Exported to %s", output_resolved)
        return

    # Multiple shapes and output path has a file extension -> one compound to that file
    if len(shapes) > 1 and output_resolved.suffix:
        from build123d import Compound

        compound = Compound(children=shapes)
        _export_shape_to_path(compound, output_resolved, fmt)
        env.logger.info("Exported %d artifact(s) to %s", len(shapes), output_resolved)
        return

    # Output is a directory: one file per artifact
    out_dir = output_resolved if output_resolved.is_dir() else output_resolved
    if not out_dir.is_dir():
        out_dir.mkdir(parents=True, exist_ok=True)

    for artifact, shape in zip(target_artifacts, shapes):
        mod = getattr(artifact, "module", "")
        name = getattr(artifact, "name", "artifact")
        safe_name = f"{mod}_{name}".strip("_") if mod else name
        safe_name = safe_name.replace("/", "_")
        out_path = out_dir / f"{safe_name}{ext}"
        _export_shape_to_path(shape, out_path, fmt)
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
@pass_env
def snapshot(env: Environment, artifacts: tuple[str, ...], output: pathlib.Path):
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
        artifact_args = " ".join(_artifact_display_name(a) for a in target_artifacts)
        env.logger.info(
            "Tip: To skip the prompt next time, run: %s artifacts snapshot -o %s %s",
            "mr",
            output,
            artifact_args,
        )
    else:
        target_artifacts = _resolve_artifacts(registry, artifacts)

    realized_artifacts = _realize_artifacts(target_artifacts)

    # Convert to model data format using convert from utils
    model_data = convert(realized_artifacts)

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
