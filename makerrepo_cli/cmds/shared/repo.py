"""Shared repo scanning and collection for artifacts and generators."""
import logging
import pathlib
import sys

from mr.registry import collect
from mr.registry import Registry
from mr.utils import find_python_modules
from mr.utils import find_python_packages
from mr.utils import load_module

logger = logging.getLogger(__name__)


def _scan_onerror(name: str) -> None:
    if issubclass(sys.exc_info()[0], ImportError):
        logger.warning(
            "Encountered ImportError while importing %s: %s", name, sys.exc_info()[1]
        )
        return
    raise  # reraise the last exception


def collect_from_repo(cwd: pathlib.Path | None = None) -> Registry:
    """Scan cwd for Python packages and modules, collect artifacts and generators into a registry.

    The returned registry has .artifacts (from @artifact) and .customizables (from @customizable).
    """
    cwd = cwd or pathlib.Path.cwd()
    cwd_str = str(cwd.resolve())
    if cwd_str not in sys.path:
        sys.path.insert(0, cwd_str)
    pkgs = find_python_packages(cwd)
    modules = find_python_modules(cwd)
    registry = collect(
        [load_module(str(s)) for s in pkgs + modules], onerror=_scan_onerror
    )
    if not hasattr(registry, "customizables"):
        registry.customizables = {}  # type: ignore[attr-defined]
    return registry
