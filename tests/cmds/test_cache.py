"""CLI tests for mr cache list / mr cache prune."""
import pathlib

from click.testing import CliRunner

from makerrepo_cli.cmds.main import cli


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
