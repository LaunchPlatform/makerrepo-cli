import pathlib

import pytest
from click.testing import CliRunner

from makerrepo_cli.cmds.main import cli
from makerrepo_cli.cmds.shared.cache import CacheService
from makerrepo_cli.cmds.shared.cache import connect_cache_service
from makerrepo_cli.cmds.shared.cache import make_cache_key
from makerrepo_cli.cmds.shared.repo import collect_from_repo


@pytest.fixture
def cache_folder(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "cache"
    path.mkdir()
    return path


@pytest.fixture
def cache_service(cache_folder: pathlib.Path) -> CacheService:
    return CacheService(cache_folder)


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


# --- Cache CLI commands (mr cache list / mr cache prune) ---


def test_cache_list_empty(cli_runner: CliRunner, cache_folder: pathlib.Path) -> None:
    result = cli_runner.invoke(
        cli, ["-C", str(cache_folder), "cache", "list"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert f"No cache files in {cache_folder}" in result.output


def test_cache_list_with_files(
    cli_runner: CliRunner, cache_folder: pathlib.Path
) -> None:
    (cache_folder / "mod").mkdir()
    (cache_folder / "mod" / "func_abc.brep").write_bytes(b"x" * 100)
    (cache_folder / "other.txt").write_bytes(b"y" * 50)
    result = cli_runner.invoke(
        cli, ["-C", str(cache_folder), "cache", "list"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert "Cache files" in result.output
    assert "mod/func_abc.brep" in result.output
    assert "other.txt" in result.output
    assert "100" in result.output or "50" in result.output
    assert "2 file(s)" in result.output


def test_cache_list_nonexistent_dir(
    cli_runner: CliRunner, tmp_path: pathlib.Path
) -> None:
    missing = tmp_path / "missing_cache"
    result = cli_runner.invoke(
        cli, ["-C", str(missing), "cache", "list"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert f"No cache files in {missing}" in result.output


def test_cache_prune_all_with_paths_fails(
    cli_runner: CliRunner, cache_folder: pathlib.Path
) -> None:
    (cache_folder / "a.brep").write_bytes(b"x")
    result = cli_runner.invoke(
        cli,
        ["-C", str(cache_folder), "cache", "prune", "--all", "a.brep"],
        catch_exceptions=False,
    )
    assert result.exit_code == 2
    assert "Cannot use --all and path arguments together" in result.output


def test_cache_prune_all_empty(
    cli_runner: CliRunner, cache_folder: pathlib.Path
) -> None:
    result = cli_runner.invoke(
        cli,
        ["-C", str(cache_folder), "cache", "prune", "--all"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "No cache files to remove" in result.output


def test_cache_prune_all_removes_files(
    cli_runner: CliRunner, cache_folder: pathlib.Path
) -> None:
    (cache_folder / "mod").mkdir()
    (cache_folder / "mod" / "f.brep").write_bytes(b"x")
    (cache_folder / "top.txt").write_bytes(b"y")
    result = cli_runner.invoke(
        cli,
        ["-C", str(cache_folder), "cache", "prune", "--all"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Removed 2 cache file(s)" in result.output
    assert not (cache_folder / "mod" / "f.brep").exists()
    assert not (cache_folder / "top.txt").exists()


def test_cache_prune_by_path_file(
    cli_runner: CliRunner, cache_folder: pathlib.Path
) -> None:
    (cache_folder / "a").mkdir()
    (cache_folder / "a" / "f.brep").write_bytes(b"x")
    (cache_folder / "a" / "keep.brep").write_bytes(b"y")
    result = cli_runner.invoke(
        cli,
        ["-C", str(cache_folder), "cache", "prune", "a/f.brep"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Removed 1 item(s)" in result.output
    assert not (cache_folder / "a" / "f.brep").exists()
    assert (cache_folder / "a" / "keep.brep").exists()


def test_cache_prune_by_path_dir(
    cli_runner: CliRunner, cache_folder: pathlib.Path
) -> None:
    (cache_folder / "sub").mkdir()
    (cache_folder / "sub" / "one.brep").write_bytes(b"1")
    (cache_folder / "sub" / "two.brep").write_bytes(b"2")
    (cache_folder / "other.brep").write_bytes(b"3")
    result = cli_runner.invoke(
        cli,
        ["-C", str(cache_folder), "cache", "prune", "sub"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Removed 2 item(s)" in result.output
    assert not (cache_folder / "sub" / "one.brep").exists()
    assert not (cache_folder / "sub" / "two.brep").exists()
    assert (cache_folder / "other.brep").exists()


def test_cache_prune_path_not_in_cache(
    cli_runner: CliRunner, cache_folder: pathlib.Path
) -> None:
    (cache_folder / "only.brep").write_bytes(b"x")
    result = cli_runner.invoke(
        cli,
        ["-C", str(cache_folder), "cache", "prune", "nonexistent.brep"],
        catch_exceptions=False,
    )
    assert result.exit_code == 2
    assert "Not in cache" in result.output
    assert "nonexistent.brep" in result.output
    assert (cache_folder / "only.brep").exists()


def test_cache_prune_path_outside_cache(
    cli_runner: CliRunner, cache_folder: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    (cache_folder / "a.brep").write_bytes(b"x")
    outside = tmp_path / "outside"
    outside.write_bytes(b"y")
    # Pass path that resolves outside cache (e.g. absolute path to other dir)
    result = cli_runner.invoke(
        cli,
        ["-C", str(cache_folder), "cache", "prune", str(outside)],
        catch_exceptions=False,
    )
    assert result.exit_code == 2
    assert "Path is outside cache directory" in result.output
    assert (cache_folder / "a.brep").exists()
