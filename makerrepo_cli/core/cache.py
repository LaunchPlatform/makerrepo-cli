import functools
import hashlib
import json
import logging
import os
import pathlib
import tempfile
from contextlib import contextmanager

from build123d import export_brep
from build123d import import_brep
from build123d import Part
from mr.registry import Registry

logger = logging.getLogger(__name__)

# Default cache directory: XDG_CACHE_HOME/makerrepo on Linux, ~/.cache/makerrepo otherwise
CACHE_DIR_NAME = "makerrepo"


def default_cache_dir() -> pathlib.Path:
    """Return the default cache directory for the CLI (e.g. ~/.cache/makerrepo)."""
    base = os.environ.get("XDG_CACHE_HOME")
    if not base:
        base = pathlib.Path.home() / ".cache"
    else:
        base = pathlib.Path(base)
    return base / CACHE_DIR_NAME


def make_cache_key(args: tuple, kwargs: dict) -> str:
    payload = json.dumps(
        dict(args=args, kwargs=kwargs),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def make_default_cache_service(
    cache_dir: pathlib.Path | None = None,
    *,
    suffix: str = ".brep",
    temp_folder: pathlib.Path | None = None,
) -> "CacheService":
    root = cache_dir if cache_dir is not None else default_cache_dir()
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return CacheService(root, suffix=suffix, temp_folder=temp_folder)


class CacheService:
    def __init__(
        self,
        cache_folder: pathlib.Path,
        suffix: str = ".brep",
        temp_folder: pathlib.Path | None = None,
    ):
        self.cache_folder = cache_folder
        self.suffix = suffix
        self.temp_folder = (
            (cache_folder / ".tmp") if temp_folder is None else temp_folder
        ).resolve()
        self.temp_folder.mkdir(parents=True, exist_ok=True)
        self.mem_cache = {}

    def lookup(self, module: str, name: str, args: tuple, kwargs: dict) -> Part | None:
        cache_key = make_cache_key(args, kwargs)
        file_name = f"{cache_key}{self.suffix}"

        mem_cache_key = (module, name, file_name)
        if mem_cache_key in self.mem_cache:
            logger.info(
                "Cache %s found in memory, returning cache for %s/%s",
                file_name,
                module,
                name,
            )
            return self.mem_cache[mem_cache_key]

        func_folder = self.cache_folder / module / name
        if not func_folder.is_dir():
            logger.debug(
                "Cache folder %s not found, skip cache lookup for %s/%s",
                func_folder,
                module,
                name,
            )
            return None

        file_path = func_folder / file_name
        if not file_path.is_file():
            logger.debug(
                "Cache file %s not found, skip cache lookup for %s/%s",
                file_path,
                func_folder,
                module,
                name,
            )
            return None
        logger.info(
            "Cache file found at %s, returning cache for %s/%s",
            file_path,
            module,
            name,
        )
        result = import_brep(file_path)
        self.mem_cache[mem_cache_key] = result
        return result

    def store(self, module: str, name: str, args: tuple, kwargs: dict, obj: Part):
        func_folder = self.cache_folder / module / name
        func_folder.mkdir(parents=True, exist_ok=True)

        cache_key = make_cache_key(args, kwargs)
        file_name = f"{cache_key}{self.suffix}"
        file_path = func_folder / file_name

        with tempfile.NamedTemporaryFile(
            delete=False, dir=self.temp_folder
        ) as temp_file:
            logger.debug(
                "Writing model %s/%s cache to a temp file to %s",
                module,
                name,
                temp_file.name,
            )
            export_brep(obj, temp_file.name)
        pathlib.Path(temp_file.name).rename(file_path)
        logger.info("Output model %s/%s cache to %s", module, name, file_path)
        mem_cache_key = (module, name, file_name)
        self.mem_cache[mem_cache_key] = obj


def connect_cache_service(registry: Registry, cache_service: CacheService):
    for module_name, cached_objs in registry.caches.items():
        for _, cached_obj in cached_objs.items():
            cached_obj.lookup_funcs.clear()
            cached_obj.lookup_funcs.append(
                functools.partial(
                    cache_service.lookup, cached_obj.module, cached_obj.name
                )
            )
            cached_obj.store_funcs.clear()
            cached_obj.store_funcs.append(
                functools.partial(
                    cache_service.store, cached_obj.module, cached_obj.name
                )
            )


def disconnect_cache_service(registry: Registry):
    for module_name, cached_objs in registry.caches.items():
        for _, cached_obj in cached_objs.items():
            cached_obj.lookup_funcs.clear()
            cached_obj.store_funcs.clear()


@contextmanager
def use_registry_cache(
    registry: Registry,
    *,
    use_cache: bool = True,
    cache_service: CacheService | None = None,
):
    """If use_cache is True and the registry has caches, connect a CacheService for the duration of the block."""
    if not use_cache:
        yield
        return
    caches = registry.caches
    if not caches:
        yield
        return
    effective_cache_service = (
        cache_service if cache_service is not None else make_default_cache_service()
    )
    connect_cache_service(registry, effective_cache_service)
    try:
        yield
    finally:
        disconnect_cache_service(registry)
