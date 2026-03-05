import hashlib
import json
import pathlib


def cache_key(args: tuple, kwargs: dict) -> str:
    payload = json.dumps(
        dict(args=args, kwargs=kwargs),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


class CacheService:
    def __init__(self, cache_folder: pathlib.Path):
        self.cache_folder = cache_folder

    def lookup(self, module: str, name: str, args: tuple, kwargs: dict):
        module_folder = self.cache_folder / module
        if not module_folder.is_dir():
            return
