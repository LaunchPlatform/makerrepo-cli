import pathlib

import pytest

from makerrepo_cli.cmds.shared.repo import collect_from_repo
from makerrepo_cli.core.cache import CacheService
from makerrepo_cli.core.cache import connect_cache_service
from makerrepo_cli.core.cache import make_cache_key


@pytest.mark.parametrize(
    "args, kwargs, expected",
    [
        (
            (),
            dict(foo="bar"),
            "16a4154f221f9a3733d9873f86166c18813865dfb432b9abeb841073fbd48cac",
        ),
        (
            ("hello", "baby"),
            dict(foo="bar"),
            "54169f0acbb76bd39c6003a8a3a881b2c0053d526f3da24e863691809164c926",
        ),
        (
            ("0", "0"),
            dict(),
            "d54c8c0586d78ae76e14b7247cb612a52e4375ef900bcfa1e3ed54d19fe79c63",
        ),
        (
            ("0", "1"),
            dict(),
            "e8339736d72712619602bc12ab193210075bf05535926f3bda7f58d39ba0a0ee",
        ),
        (
            (),
            dict(a="v0", b="v1"),
            "6d3c96b851c11544517c82df62bb33751f0fd80e0417ceb6259f5eb8f5cb8519",
        ),
        (
            (),
            dict(b="v1", a="v0"),
            "6d3c96b851c11544517c82df62bb33751f0fd80e0417ceb6259f5eb8f5cb8519",
        ),
    ],
)
def test_make_cache_key(args: tuple, kwargs: dict, expected: str):
    assert make_cache_key(args, kwargs) == expected


def test_cache_lookup(cache_folder: pathlib.Path, cache_service: CacheService):
    module_name = "mock_mod"
    func_name = "mock_artifact"
    args = ("foo",)
    kwargs = dict(key0="val0")
    assert cache_service.lookup(module_name, func_name, args, kwargs) is None

    module_folder = cache_folder / module_name
    module_folder.mkdir()
    assert cache_service.lookup(module_name, func_name, args, kwargs) is None

    from build123d import Box
    from build123d import export_brep

    cache_key = make_cache_key(args, kwargs)
    file_path = module_folder / f"{func_name}_{cache_key}{cache_service.suffix}"
    export_brep(Box(1, 1, 1), file_path)

    result = cache_service.lookup(module_name, func_name, args, kwargs)
    assert result is not None


def test_cache_store(cache_folder: pathlib.Path, cache_service: CacheService):
    module_name = "mock_mod"
    func_name = "mock_artifact"
    args = ("foo",)
    kwargs = dict(key0="val0")
    assert cache_service.lookup(module_name, func_name, args, kwargs) is None

    from build123d import Box

    cache_service.store(module_name, func_name, args, kwargs, Box(1, 1, 1))

    result = cache_service.lookup(module_name, func_name, args, kwargs)
    assert result is not None


def test_connect_cache_service(
    fixtures_folder: pathlib.Path,
    cache_folder: pathlib.Path,
    cache_service: CacheService,
):
    registry = collect_from_repo(fixtures_folder / "cached_examples")
    connect_cache_service(registry=registry, cache_service=cache_service)

    expensive_func = __import__(
        registry.caches["main"]["expensive_func"].func.__module__
    ).expensive_func

    cached_value = expensive_func(1, 2, 3)
    assert expensive_func(1, 2, 3) is cached_value

    expensive_func(1, 2, 4)
    assert expensive_func(1, 2, 4) is not cached_value
