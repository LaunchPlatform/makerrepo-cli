import logging
import pathlib
import sys

from mr.artifacts.registry import collect
from mr.artifacts.registry import Registry
from mr.artifacts.utils import find_python_modules
from mr.artifacts.utils import find_python_packages
from mr.artifacts.utils import load_module
from ocp_tessellate import OcpGroup
from ocp_tessellate.convert import tessellate_group
from ocp_tessellate.convert import to_ocpgroup
from ocp_tessellate.utils import numpy_to_buffer_json

from .ocp_data_types import OcpData
from .ocp_data_types import OcpPayload

logger = logging.getLogger(__name__)


def _scan_onerror(name: str):
    if issubclass(sys.exc_info()[0], ImportError):
        logger.warning(
            "Encountered ImportError while importing %s: %s", name, sys.exc_info()[1]
        )
        return
    raise  # reraise the last exception


def collect_from_repo(cwd: pathlib.Path | None = None) -> Registry:
    """Scan cwd for Python packages and modules, collect artifacts into a registry."""
    cwd = cwd or pathlib.Path.cwd()
    cwd_str = str(cwd.resolve())
    if cwd_str not in sys.path:
        sys.path.insert(0, cwd_str)
    pkgs = find_python_packages(cwd)
    modules = find_python_modules(cwd)
    return collect([load_module(str(s)) for s in pkgs + modules], onerror=_scan_onerror)


def convert(*cad_objs, names=None) -> OcpPayload:
    part_group, instances = to_ocpgroup(
        *cad_objs,
        names=names,
    )
    if len(part_group.objects) == 1 and isinstance(part_group.objects[0], OcpGroup):
        loc = part_group.loc
        part_group = part_group.objects[0]
        part_group.loc = loc * part_group.loc
    instances, shapes, mapping = tessellate_group(
        group=part_group,
        instances=instances,
    )

    data = numpy_to_buffer_json(
        dict(instances=instances, shapes=shapes),
    )
    return OcpPayload(
        data=OcpData.model_validate(data),
        type="data",
        count=part_group.count_shapes(),
    )
