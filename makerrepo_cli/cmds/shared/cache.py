import functools
import hashlib
import json
import logging
import pathlib
import tempfile

from build123d import export_brep
from build123d import import_brep
from build123d import Part
from mr.registry import Registry

logger = logging.getLogger(__name__)


def make_cache_key(args: tuple, kwargs: dict) -> str:
    payload = json.dumps(
        dict(args=args, kwargs=kwargs),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


class CacheService:
    def __init__(self, cache_folder: pathlib.Path, suffix: str = ".brep"):
        self.cache_folder = cache_folder
        self.suffix = suffix

    def lookup(self, module: str, name: str, args: tuple, kwargs: dict) -> Part | None:
        module_folder = self.cache_folder / module
        if not module_folder.is_dir():
            logger.debug(
                "Module folder %s not found, skip cache lookup for %s/%s",
                module_folder,
                module,
                name,
            )
            return None

        cache_key = make_cache_key(args, kwargs)
        file_name = f"{name}_{cache_key}{self.suffix}"
        file_path = module_folder / file_name
        if not file_path.is_file():
            logger.debug(
                "Cache file %s not found, skip cache lookup for %s/%s",
                file_path,
                module_folder,
                module,
                name,
            )
            return None
        logger.info(
            "Cache file found at %s, returning cache for %s/%s",
            file_path,
            module_folder,
            module,
            name,
        )
        return import_brep(file_path)

    def store(self, module: str, name: str, args: tuple, kwargs: dict, obj: Part):
        module_folder = self.cache_folder / module
        module_folder.mkdir(parents=True, exist_ok=True)

        cache_key = make_cache_key(args, kwargs)
        file_name = f"{name}_{cache_key}{self.suffix}"
        file_path = module_folder / file_name

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            logger.debug(
                "Writing model %s/%s B-REP cache to a temp file to %s",
                module,
                name,
                temp_file.name,
            )
            export_brep(obj, temp_file.name)
        pathlib.Path(temp_file.name).rename(file_path)
        logger.info("Output model %s/%s B-REP cache to %s", module, name, file_path)


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
