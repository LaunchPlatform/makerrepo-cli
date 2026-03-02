import logging
import pathlib

import click
import rich
from mr.artifacts.registry import Registry
from rich import box
from rich.markup import escape
from rich.padding import Padding
from rich.table import Table

from ..environment import Environment
from ..environment import pass_env
from .cli import cli
from .utils import collect_from_repo
from .utils import convert

logger = logging.getLogger(__name__)
TABLE_HEADER_STYLE = "yellow"
TABLE_COLUMN_STYLE = "cyan"


def _all_artifacts_flat(registry: Registry) -> list[tuple[str, str, object]]:
    """Yield (module_name, artifact_name, artifact) for every artifact."""
    for module_name, artifacts in registry.artifacts.items():
        for artifact_name, artifact in artifacts.items():
            yield (module_name, artifact_name, artifact)


def _resolve_artifacts(registry: Registry, names: tuple[str, ...]) -> list:
    """Resolve artifact names to artifact objects. Names can be 'name' or 'module.name'."""
    flat = list(_all_artifacts_flat(registry))
    if not flat:
        raise ValueError("No artifacts found in repository")
    by_module_name: dict[str, dict] = registry.artifacts
    name_to_artifacts: dict[str, list[tuple[str, object]]] = {}
    for mod, art_name, art in flat:
        name_to_artifacts.setdefault(art_name, []).append((mod, art))
    result = []
    for name in names:
        if "." in name:
            mod, art_name = name.split(".", 1)
            if mod not in by_module_name or art_name not in by_module_name[mod]:
                raise ValueError(f"Artifact not found: {name}")
            result.append(by_module_name[mod][art_name])
        else:
            candidates = name_to_artifacts.get(name, [])
            if len(candidates) == 0:
                raise ValueError(f"Artifact not found: {name}")
            if len(candidates) > 1:
                raise ValueError(
                    f"Ambiguous artifact name '{name}'; use module.name: "
                    + ", ".join(f"{m}.{a.name}" for m, a in candidates)
                )
            result.append(candidates[0][1])
    return result


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
        _, _, first = next(_all_artifacts_flat(registry))
        logger.info(
            "No artifacts provided, using first: %s/%s",
            first.module,
            first.name,
        )
        target_artifacts = [first]
    else:
        target_artifacts = _resolve_artifacts(registry, artifacts)

    # TODO: this is going to be a bit slow, provide a progress bar & cache?
    realized_artifacts = [artifact.func() for artifact in target_artifacts]
    # defer the import to make testing mocking much easier
    from ocp_vscode import show

    # TODO: pass in some args
    show(realized_artifacts, port=port)


@cli.command(help="Export artifact")
@pass_env
def export(env: Environment):
    registry = collect_from_repo()
    if not registry.artifacts:
        logger.error("No artifacts found")
        return
    # TODO:


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
        _, _, first = next(_all_artifacts_flat(registry))
        env.logger.info(
            "No artifacts provided, using first: %s/%s",
            first.module,
            first.name,
        )
        target_artifacts = [first]
    else:
        target_artifacts = _resolve_artifacts(registry, artifacts)

    # Realize artifacts
    realized_artifacts = [artifact.func() for artifact in target_artifacts]

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
