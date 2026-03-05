import pathlib

import pytest

from makerrepo_cli.core.cache import CacheService


@pytest.fixture
def cache_folder(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "cache"
    path.mkdir()
    return path


@pytest.fixture
def cache_service(cache_folder: pathlib.Path) -> CacheService:
    return CacheService(cache_folder)
