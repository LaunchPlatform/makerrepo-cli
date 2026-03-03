import pathlib

import pytest
from click.testing import CliRunner
from pytest import MonkeyPatch

from .helper import switch_cwd
from makerrepo_cli.cmds.main import cli


def test_generators_list(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
):
    """Test that generators list runs (no @customizable in fixtures -> No generators found)."""
    monkeypatch.syspath_prepend(fixtures_folder)

    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(cli, ["generators", "list"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "No generators found" in result.output or "Generators" in result.output


def test_generators_list_json_no_generators(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
):
    """Test that generators list -o json with no generators outputs []."""
    import json

    monkeypatch.syspath_prepend(fixtures_folder)

    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(
            cli, ["generators", "list", "-o", "json"], catch_exceptions=False
        )

    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_generators_list_json_output(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
):
    """Test that generators list -o json outputs valid JSON with module, name, and extra fields."""
    import json

    class MockGen:
        module = "examples"
        name = "box_gen"
        sample = "a 1x1 box"
        filename = "/some/path/main.py"
        lineno = 42

        def func(self, payload):
            pass

    mock_registry = type(
        "Registry", (), {"customizables": {"examples": {"box_gen": MockGen()}}}
    )()

    monkeypatch.syspath_prepend(fixtures_folder)
    monkeypatch.setattr(
        "makerrepo_cli.cmds.generators.main.collect_from_repo",
        lambda cwd=None: mock_registry,
    )

    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(
            cli, ["generators", "list", "-o", "json"], catch_exceptions=False
        )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 1
    item = data[0]
    assert item["module"] == "examples"
    assert item["name"] == "box_gen"
    assert item["sample"] == "a 1x1 box"
    assert item["filename"] == "/some/path/main.py"
    assert item["lineno"] == 42


def test_export_no_generators(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    """Export with no generators in repo must report No generators found."""
    monkeypatch.syspath_prepend(fixtures_folder)

    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(
            cli,
            ["generators", "export", "-o", str(tmp_path / "out.step")],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert "No generators found" in result.output
    assert not (tmp_path / "out.step").exists()


def test_export_invalid_payload(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    """Export with invalid JSON payload must report Invalid payload."""
    from build123d import Box

    # Mock generator: func(payload) -> object with .part (Shape)
    class MockGen:
        module = "examples"
        name = "box_gen"

        def func(self, payload):
            return type("Obj", (), {"part": Box(1, 1, 1)})()

    mock_registry = type(
        "Registry", (), {"customizables": {"examples": {"box_gen": MockGen()}}}
    )()

    def collect_mock(cwd=None):
        return mock_registry

    monkeypatch.syspath_prepend(fixtures_folder)
    monkeypatch.setattr(
        "makerrepo_cli.cmds.generators.main.collect_from_repo",
        collect_mock,
    )

    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(
            cli,
            [
                "generators",
                "export",
                "-p",
                "not valid json",
                "-o",
                str(tmp_path / "out.step"),
                "box_gen",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert "Invalid payload" in result.output
    assert not (tmp_path / "out.step").exists()


def test_export_unknown_extension(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    """Export with unknown output extension must error and not create any file."""
    from build123d import Box

    class MockGen:
        module = "examples"
        name = "box_gen"

        def func(self, payload):
            return type("Obj", (), {"part": Box(1, 1, 1)})()

    mock_registry = type(
        "Registry", (), {"customizables": {"examples": {"box_gen": MockGen()}}}
    )()

    monkeypatch.syspath_prepend(fixtures_folder)
    monkeypatch.setattr(
        "makerrepo_cli.cmds.generators.main.collect_from_repo",
        lambda cwd=None: mock_registry,
    )

    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(
            cli,
            [
                "generators",
                "export",
                "-o",
                str(tmp_path / "out.xyz"),
                "box_gen",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert "Unknown output extension" in result.output
    assert ".xyz" in result.output
    assert "Supported:" in result.output
    assert not (tmp_path / "out.xyz").exists()


def test_export_single_generator_step(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    """Export single generator to STEP file."""
    from build123d import Box

    class MockGen:
        module = "examples"
        name = "box_gen"

        def func(self, payload):
            return type("Obj", (), {"part": Box(5, 5, 5)})()

    mock_registry = type(
        "Registry", (), {"customizables": {"examples": {"box_gen": MockGen()}}}
    )()

    monkeypatch.syspath_prepend(fixtures_folder)
    monkeypatch.setattr(
        "makerrepo_cli.cmds.generators.main.collect_from_repo",
        lambda cwd=None: mock_registry,
    )

    with switch_cwd(fixtures_folder):
        output_file = tmp_path / "box.step"
        result = cli_runner.invoke(
            cli,
            [
                "generators",
                "export",
                "-o",
                str(output_file),
                "box_gen",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert output_file.exists()
    content = output_file.read_text()
    assert "ISO-10303-21" in content


def test_snapshot_no_generators(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    """Snapshot with no generators in repo must report No generators found."""
    monkeypatch.syspath_prepend(fixtures_folder)

    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(
            cli,
            ["generators", "snapshot", "-o", str(tmp_path / "snap.png")],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert "No generators found" in result.output
    assert not (tmp_path / "snap.png").exists()


def test_view_no_generators(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
):
    """View with no generators in repo must report No generators found."""
    monkeypatch.syspath_prepend(fixtures_folder)

    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(cli, ["generators", "view"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "No generators found" in result.output


def test_view_single_generator_without_argument_uses_default(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
):
    """View with a single generator in repo must not crash and should auto-select it."""
    import sys
    import types

    class MockGen:
        module = "examples"
        name = "box_gen"

        def func(self, payload):
            return object()

    mock_registry = type(
        "Registry", (), {"customizables": {"examples": {"box_gen": MockGen()}}}
    )()

    # Stub ocp_vscode so view can import show and ColorMap without requiring the real package.
    dummy_module = types.SimpleNamespace(
        ColorMap=type("DummyColorMap", (), {})(),
        show=lambda *args, **kwargs: None,
    )
    monkeypatch.setitem(sys.modules, "ocp_vscode", dummy_module)

    monkeypatch.syspath_prepend(fixtures_folder)
    monkeypatch.setattr(
        "makerrepo_cli.cmds.generators.main.collect_from_repo",
        lambda cwd=None: mock_registry,
    )

    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(
            cli,
            ["generators", "view", "-p", "{}"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0


def test_export_payload_from_stdin(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    """Export with -p - reads JSON payload from stdin."""
    from build123d import Box

    class MockGen:
        module = "examples"
        name = "box_gen"

        def func(self, payload):
            return type("Obj", (), {"part": Box(1, 1, 1)})()

    mock_registry = type(
        "Registry", (), {"customizables": {"examples": {"box_gen": MockGen()}}}
    )()

    monkeypatch.syspath_prepend(fixtures_folder)
    monkeypatch.setattr(
        "makerrepo_cli.cmds.generators.main.collect_from_repo",
        lambda cwd=None: mock_registry,
    )

    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(
            cli,
            [
                "generators",
                "export",
                "-p",
                "-",
                "-o",
                str(tmp_path / "out.step"),
                "box_gen",
            ],
            input="{}",
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert (tmp_path / "out.step").exists()


def test_export_payload_validation_fails(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    """Export with payload that fails generator's param validation must report error."""
    from build123d import Box
    from pydantic import BaseModel

    class BoxParams(BaseModel):
        size: float

    class MockCustomizable:
        module = "examples"
        name = "box_gen"
        parameters_schema = BoxParams

        def func(self, payload):
            return type("Obj", (), {"part": Box(1, 1, 1)})()

    mock_registry = type(
        "Registry", (), {"customizables": {"examples": {"box_gen": MockCustomizable()}}}
    )()

    monkeypatch.syspath_prepend(fixtures_folder)
    monkeypatch.setattr(
        "makerrepo_cli.cmds.generators.main.collect_from_repo",
        lambda cwd=None: mock_registry,
    )

    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(
            cli,
            [
                "generators",
                "export",
                "-p",
                '{"wrong": "key"}',
                "-o",
                str(tmp_path / "out.step"),
                "box_gen",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 1
    assert "Payload validation failed" in result.output
    assert not (tmp_path / "out.step").exists()


def test_export_payload_validation_passes(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    """Export with payload valid for generator's param succeeds and uses validated payload."""
    from build123d import Box
    from pydantic import BaseModel

    class BoxParams(BaseModel):
        size: float = 3.0

    class MockGen:
        module = "examples"
        name = "box_gen"
        parameters_schema = BoxParams

        def func(self, payload):
            # generator receives validated Pydantic model
            size = getattr(payload, "size", 1)
            return type("Obj", (), {"part": Box(size, 1, 1)})()

    mock_registry = type(
        "Registry", (), {"customizables": {"examples": {"box_gen": MockGen()}}}
    )()

    monkeypatch.syspath_prepend(fixtures_folder)
    monkeypatch.setattr(
        "makerrepo_cli.cmds.generators.main.collect_from_repo",
        lambda cwd=None: mock_registry,
    )

    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(
            cli,
            [
                "generators",
                "export",
                "-p",
                '{"size": 2}',
                "-o",
                str(tmp_path / "out.step"),
                "box_gen",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert (tmp_path / "out.step").exists()
