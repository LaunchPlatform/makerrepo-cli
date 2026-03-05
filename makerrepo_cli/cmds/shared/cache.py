import hashlib
import json
import pathlib

from build123d import import_brep


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

    def lookup(self, module: str, name: str, args: tuple, kwargs: dict):
        module_folder = self.cache_folder / module
        if not module_folder.is_dir():
            return None

        cache_key = make_cache_key(args, kwargs)
        file_name = f"{name}_{cache_key}{self.suffix}"
        file_path = module_folder / file_name
        if not file_path.is_file():
            return None
        return import_brep(file_path)
