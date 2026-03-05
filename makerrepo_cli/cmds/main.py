from .artifacts import main as artifacts_main  # no qa
from .cache import main as cache_main  # no qa
from .cli import cli
from .generators import main as generators_main  # no qa

__ALL__ = [cli]

if __name__ == "__main__":
    cli()
