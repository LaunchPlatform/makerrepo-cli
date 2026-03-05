from ..aliase import AliasedGroup
from ..cli import cli as root_cli


@root_cli.group(
    name="cache",
    help="Manage cache system.",
    cls=AliasedGroup,
)
def cli():
    pass
