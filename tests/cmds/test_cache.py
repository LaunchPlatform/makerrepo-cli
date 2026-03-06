"""CLI tests for mr cache list / mr cache prune."""
import pathlib

from click.testing import CliRunner

from ..helper import switch_cwd
from makerrepo_cli.cmds.main import cli


def test_cache_list_empty(
    cli_runner: CliRunner,
    cache_folder: pathlib.Path,
    fixtures_folder: pathlib.Path,
) -> None:
    """With no @cached functions and empty cache dir, show no-functions-and-no-files message."""
    with switch_cwd(fixtures_folder / "examples"):
        result = cli_runner.invoke(
            cli, ["-C", str(cache_folder), "cache", "list"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert "No cached functions found" in result.output
    assert str(cache_folder) in result.output


def test_cache_list_with_files(
    cli_runner: CliRunner,
    cache_folder: pathlib.Path,
    fixtures_folder: pathlib.Path,
) -> None:
    """With no @cached functions but cache files present, show 'no functions' and list files."""
    (cache_folder / "mod").mkdir()
    (cache_folder / "mod" / "func_abc.brep").write_bytes(b"x" * 100)
    (cache_folder / "other.txt").write_bytes(b"y" * 50)
    with switch_cwd(fixtures_folder / "examples"):
        result = cli_runner.invoke(
            cli, ["-C", str(cache_folder), "cache", "list"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert "No cached functions found" in result.output
    assert "Cache files" in result.output
    assert "mod/func_abc.brep" in result.output
    assert "other.txt" in result.output
    assert "100" in result.output or "50" in result.output
    assert "2 file(s)" in result.output


def test_cache_list_nonexistent_dir(
    cli_runner: CliRunner,
    tmp_path: pathlib.Path,
    fixtures_folder: pathlib.Path,
) -> None:
    """When cache directory does not exist, report no functions and missing dir."""
    missing = tmp_path / "missing_cache"
    with switch_cwd(fixtures_folder / "examples"):
        result = cli_runner.invoke(
            cli, ["-C", str(missing), "cache", "list"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert "No cached functions found" in result.output
    assert "missing_cache" in result.output or "does not exist" in result.output


def test_cache_list_with_cached_functions(
    cli_runner: CliRunner,
    cache_folder: pathlib.Path,
    fixtures_folder: pathlib.Path,
) -> None:
    """From a repo with @cached functions, list each with file:lineno and matching cache files."""
    # Path layout: <module>/<name>/<cache_key>.brep
    (cache_folder / "main" / "expensive_func").mkdir(parents=True)
    (cache_folder / "main" / "expensive_func" / "abc123def.brep").write_bytes(
        b"x" * 200
    )
    with switch_cwd(fixtures_folder / "cached_examples"):
        result = cli_runner.invoke(
            cli, ["-C", str(cache_folder), "cache", "list"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert "main.expensive_func" in result.output
    assert "main/expensive_func" in result.output
    assert "200" in result.output


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


def test_cache_list_shows_dangling(
    cli_runner: CliRunner,
    cache_folder: pathlib.Path,
    fixtures_folder: pathlib.Path,
) -> None:
    """List shows matched cache files under each @cached function and a separate dangling section."""
    # Matched: main/expensive_func (exists in cached_examples)
    (cache_folder / "main" / "expensive_func").mkdir(parents=True)
    (cache_folder / "main" / "expensive_func" / "abc123.brep").write_bytes(b"x" * 200)
    # Dangling: module/name with no @cached function
    (cache_folder / "old_module" / "removed_func").mkdir(parents=True)
    (cache_folder / "old_module" / "removed_func" / "deadbeef.brep").write_bytes(
        b"y" * 100
    )
    with switch_cwd(fixtures_folder / "cached_examples"):
        result = cli_runner.invoke(
            cli, ["-C", str(cache_folder), "cache", "list"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert "main/expensive_func" in result.output
    assert "Dangling cache files" in result.output
    assert "old_module/removed_func/deadbeef.brep" in result.output
    assert "1 file(s)" in result.output or "2 file(s)" in result.output
    assert "100" in result.output
    assert "200" in result.output


def test_cache_prune_dangling_removes_only_dangling(
    cli_runner: CliRunner,
    cache_folder: pathlib.Path,
    fixtures_folder: pathlib.Path,
) -> None:
    """prune --dangling removes only cache files with no matching @cached function."""
    (cache_folder / "main" / "expensive_func").mkdir(parents=True)
    matched_file = cache_folder / "main" / "expensive_func" / "abc123.brep"
    matched_file.write_bytes(b"x" * 200)
    (cache_folder / "old_module" / "removed_func").mkdir(parents=True)
    dangling_file = cache_folder / "old_module" / "removed_func" / "dead.brep"
    dangling_file.write_bytes(b"y" * 50)
    with switch_cwd(fixtures_folder / "cached_examples"):
        result = cli_runner.invoke(
            cli,
            ["-C", str(cache_folder), "cache", "prune", "--dangling"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert "Removed 1 dangling cache file(s)" in result.output
    assert not dangling_file.exists()
    assert matched_file.exists()


def test_cache_prune_dangling_no_dangling(
    cli_runner: CliRunner,
    cache_folder: pathlib.Path,
    fixtures_folder: pathlib.Path,
) -> None:
    """prune --dangling when all cache files are matched reports no dangling and leaves files."""
    (cache_folder / "main" / "expensive_func").mkdir(parents=True)
    kept = cache_folder / "main" / "expensive_func" / "abc123.brep"
    kept.write_bytes(b"x" * 100)
    with switch_cwd(fixtures_folder / "cached_examples"):
        result = cli_runner.invoke(
            cli,
            ["-C", str(cache_folder), "cache", "prune", "--dangling"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert "No dangling cache files to remove" in result.output
    assert kept.exists()


def test_cache_prune_dangling_with_paths_fails(
    cli_runner: CliRunner, cache_folder: pathlib.Path
) -> None:
    """Cannot use --dangling and path arguments together."""
    (cache_folder / "a").mkdir()
    (cache_folder / "a" / "b.brep").write_bytes(b"x")
    result = cli_runner.invoke(
        cli,
        ["-C", str(cache_folder), "cache", "prune", "--dangling", "a/b.brep"],
        catch_exceptions=False,
    )
    assert result.exit_code == 2
    assert "Cannot use --dangling and path arguments together" in result.output
