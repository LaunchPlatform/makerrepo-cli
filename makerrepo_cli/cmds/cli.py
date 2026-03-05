import logging
import os
import pathlib

import click
from click.shell_completion import get_completion_class
from rich.logging import RichHandler

from .environment import Environment
from .environment import LOG_LEVEL_MAP
from .environment import LogLevel
from .environment import pass_env

# Used by the completion command to generate shell scripts (env var for Click completion)
COMPLETE_VAR = "_MR_COMPLETE"
PROG_NAME = "mr"


@click.group(help="Command line tools for MakerRepo")
@click.option(
    "-l",
    "--log-level",
    type=click.Choice(
        list(map(lambda key: key.value, LOG_LEVEL_MAP.keys())), case_sensitive=False
    ),
    default=lambda: os.environ.get("LOG_LEVEL", "INFO"),
)
@click.option(
    "--build123d-log-level",
    type=click.Choice(
        list(map(lambda key: key.value, LOG_LEVEL_MAP.keys())), case_sensitive=False
    ),
    default=lambda: os.environ.get("BUILD123D_LOG_LEVEL", "WARNING"),
    help="Log level for the build123d library logger.",
)
@click.option(
    "--log-format",
    type=str,
    default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    help="logging format (only used when rich log is disabled)",
)
@click.option(
    "--disable-rich-log",
    is_flag=True,
    help="disable rich log handler",
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
    "--no-cache",
    "no_cache",
    is_flag=True,
    help="Disable cache for model evaluation.",
)
@click.version_option(prog_name="mr", package_name="mr")
@pass_env
def cli(
    env: Environment,
    log_level: str,
    build123d_log_level: str,
    log_format: str,
    disable_rich_log: bool,
    cache_dir: pathlib.Path | None,
    no_cache: bool,
):
    env.log_level = LogLevel(log_level)
    env.cache_dir = cache_dir
    env.use_cache = not no_cache

    # Set build123d logger level independently
    logging.getLogger("build123d").setLevel(
        LOG_LEVEL_MAP[LogLevel(build123d_log_level)]
    )

    if disable_rich_log:
        logging.basicConfig(
            level=LOG_LEVEL_MAP[env.log_level],
            format=log_format,
            force=True,
        )
    else:
        FORMAT = "%(message)s"
        logging.basicConfig(
            level=LOG_LEVEL_MAP[env.log_level],
            format=FORMAT,
            datefmt="[%X]",
            handlers=[RichHandler()],
            force=True,
        )


def _install_completion_script(shell: str) -> None:
    """Print the shell completion script for the given shell."""
    comp_cls = get_completion_class(shell)
    if comp_cls is None:
        raise click.UsageError(f"Unknown shell: {shell}")
    comp = comp_cls(cli, {}, PROG_NAME, COMPLETE_VAR)
    click.echo(comp.source())


@cli.command(
    "completion",
    help='Print shell completion script for bash, zsh, or fish. Use: eval "$(mr completion <shell>)"',
)
@click.argument(
    "shell",
    type=click.Choice(["bash", "zsh", "fish"], case_sensitive=False),
    required=True,
)
def completion(shell: str) -> None:
    """Output the completion script for the given shell. Add to your rc file or run:

    eval \"$(mr completion bash)\"   # bash
    eval \"$(mr completion zsh)\"    # zsh
    eval \"$(mr completion fish)\"   # fish
    """
    _install_completion_script(shell)
