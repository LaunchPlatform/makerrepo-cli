from ..aliase import AliasedGroup
from ..cli import cli as root_cli


@root_cli.group(
    name="generators",
    help="Operations for generators.",
    cls=AliasedGroup,
)
def cli():
    pass
