import asyncio
import json
import pathlib

import pytest
import pytest_asyncio
import websockets
from click.testing import CliRunner
from ocp_vscode import Camera
from pytest import MonkeyPatch

from .helper import switch_cwd
from makerrepo_cli.cmds.main import cli


DEFAULT_MOCK_CONFIG = {
    "ambient_intensity": 1.0,
    "angular_tolerance": 0.2,
    "axes": False,
    "axes0": False,
    "black_edges": False,
    "center_grid": False,
    "collapse": "R",
    "control": "trackball",
    "debug": False,
    "default_color": "#e8b024",
    "default_edgecolor": "#808080",
    "default_facecolor": "Violet",
    "default_opacity": 0.5,
    "default_thickedgecolor": "MediumOrchid",
    "default_vertexcolor": "MediumOrchid",
    "deviation": 0.1,
    "direct_intensity": 1.1,
    "explode": False,
    "grid": [False, False, False],
    "grid_font_size": 12,
    "metalness": 0.3,
    "modifier_keys": {
        "shift": "shiftKey",
        "ctrl": "ctrlKey",
        "meta": "metaKey",
        "alt": "altKey",
    },
    "new_tree_behavior": True,
    "glass": True,
    "tools": True,
    "pan_speed": 0.5,
    "ortho": True,
    "reset_camera": "RESET",
    "rotate_speed": 1.0,
    "roughness": 0.65,
    "theme": "browser",
    "ticks": 5,
    "transparent": False,
    "tree_width": 240,
    "up": "Z",
    "zoom_speed": 0.5,
    "_splash": True,
}
DEFAULT_MOCK_STATUS = {
    "ambient_intensity": 1,
    "states": {"/Group/Solid": [1, 1]},
    "direct_intensity": 1.1,
    "clip_slider_0": 40,
    "clip_slider_1": 40,
    "clip_slider_2": 40,
    "tab": "tree",
    "target": [10.4019, 0.4274, -24.7534],
    "target0": [10.4019, 0.4274, -24.7534],
    "position": [101.36996653681135, -93.26906574513457, -1.8075756537109555],
    "quaternion": [0.5963, 0.2408, 0.2863, 0.7099],
    "zoom": 0.9999999999999998,
}


class MockMsgHandler:
    def __init__(self, config: dict | None = None, status: dict | None = None):
        self.config = config or DEFAULT_MOCK_CONFIG
        self.status = status or DEFAULT_MOCK_STATUS
        self.data_msgs = []
        self.backend_msgs = []

    async def __call__(self, websocket: websockets.WebSocketServerProtocol, path: str):
        async for data in websocket:
            msg_type = data[:1]
            payload = data[2:]
            match msg_type:
                # command
                case b"C":
                    cmd = json.loads(payload)
                    match cmd:
                        case "status":
                            await websocket.send(json.dumps(self.status))
                        case "config":
                            await websocket.send(json.dumps(self.config))
                case b"D":
                    self.data_msgs.append(payload)
                case b"B":
                    self.backend_msgs.append(payload)


@pytest.fixture
def msg_handler() -> MockMsgHandler:
    return MockMsgHandler()


@pytest_asyncio.fixture
async def ws_server(msg_handler: MockMsgHandler, unused_tcp_port: int):
    server = await websockets.serve(msg_handler, "localhost", unused_tcp_port)
    try:
        yield server
    finally:
        server.close()
        await server.wait_closed()


def test_list(
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
):
    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(cli, ["artifacts", "list"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "main" in result.output
    assert "Artifacts" in result.output


def test_list_json_output(
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
):
    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(
            cli, ["artifacts", "list", "-o", "json"], catch_exceptions=False
        )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) >= 1
    for item in data:
        assert "module" in item
        assert "name" in item
        assert isinstance(item["module"], str)
        assert isinstance(item["name"], str)
    # At least one artifact has sample (from fixtures examples/main.py)
    names = [obj["name"] for obj in data]
    assert "main" in names


def test_list_json_empty_output(
    cli_runner: CliRunner,
    tmp_path: pathlib.Path,
):
    with switch_cwd(tmp_path):
        result = cli_runner.invoke(
            cli, ["artifacts", "list", "-o", "json"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert json.loads(result.output) == []


@pytest.mark.asyncio
async def test_view(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    unused_tcp_port: int,
    ws_server: websockets.WebSocketServer,
    msg_handler: MockMsgHandler,
):
    def operate():
        with switch_cwd(fixtures_folder):
            from makerrepo_cli.cmds.artifacts.main import _all_artifacts_flat
            from makerrepo_cli.cmds.shared.repo import collect_from_repo

            registry = collect_from_repo()
            flat = list(_all_artifacts_flat(registry))
            first_artifact = flat[0][2]
            monkeypatch.setattr(
                "makerrepo_cli.cmds.artifacts.main._prompt_artifact_selection",
                lambda reg: [first_artifact],
            )
            result = cli_runner.invoke(
                cli,
                ["artifacts", "view", "-p", unused_tcp_port],
                catch_exceptions=False,
            )
        assert result.exit_code == 0

    await asyncio.wait_for(asyncio.to_thread(operate), 10)
    assert len(msg_handler.data_msgs) == 1
    assert len(msg_handler.backend_msgs) == 1


CAMERA_OPTION_CASES = [
    (
        c.name.lower(),
        "rear" if c.name.lower() == "back" else c.name.lower(),
    )
    for c in Camera
    if c.name.lower() != "keep"
]


@pytest.mark.parametrize(
    ("camera_option", "expected_reset_camera"),
    CAMERA_OPTION_CASES,
)
@pytest.mark.asyncio
async def test_view_camera_config(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    unused_tcp_port: int,
    ws_server: websockets.WebSocketServer,
    msg_handler: MockMsgHandler,
    camera_option: str,
    expected_reset_camera: str,
):
    def operate():
        with switch_cwd(fixtures_folder):
            from makerrepo_cli.cmds.artifacts.main import _all_artifacts_flat
            from makerrepo_cli.cmds.shared.repo import collect_from_repo

            registry = collect_from_repo()
            flat = list(_all_artifacts_flat(registry))
            first_artifact = flat[0][2]
            monkeypatch.setattr(
                "makerrepo_cli.cmds.artifacts.main._prompt_artifact_selection",
                lambda reg: [first_artifact],
            )
            cli_args = [
                "artifacts",
                "view",
                "-p",
                unused_tcp_port,
                "--camera",
                camera_option,
            ]
            result = cli_runner.invoke(cli, cli_args, catch_exceptions=False)
        assert result.exit_code == 0

    await asyncio.wait_for(asyncio.to_thread(operate), 10)
    # One data message containing the model + viewer config
    assert len(msg_handler.data_msgs) == 1
    payload = json.loads(msg_handler.data_msgs[0])
    config = payload.get("config", {})

    assert config.get("reset_camera") == expected_reset_camera


def test_view_camera_invalid(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
):
    with switch_cwd(fixtures_folder):
        from makerrepo_cli.cmds.artifacts.main import _all_artifacts_flat
        from makerrepo_cli.cmds.shared.repo import collect_from_repo

        registry = collect_from_repo()
        flat = list(_all_artifacts_flat(registry))
        first_artifact = flat[0][2]
        monkeypatch.setattr(
            "makerrepo_cli.cmds.artifacts.main._prompt_artifact_selection",
            lambda reg: [first_artifact],
        )
        result = cli_runner.invoke(
            cli,
            ["artifacts", "view", "--camera", "invalidvalue"],
            catch_exceptions=False,
        )

    assert result.exit_code == 2
    assert "Invalid value" in result.output or "invalidvalue" in result.output


@pytest.mark.asyncio
async def test_snapshot_camera_option(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    captured_config: dict = {}

    class MockViewer:
        async def load_cad_data(self, data, config=None):
            captured_config.clear()
            if config:
                captured_config.update(config)

        async def take_screenshot(self):
            return b"\x89PNG\r\n\x1a\n" + b"\0" * 100

    class MockCADViewerService:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return MockViewer()

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(
        "makerrepo_cli.cmds.shared.capture_image.CADViewerService",
        MockCADViewerService,
    )

    def operate():
        with switch_cwd(fixtures_folder):
            from makerrepo_cli.cmds.artifacts.main import _all_artifacts_flat
            from makerrepo_cli.cmds.shared.repo import collect_from_repo

            registry = collect_from_repo()
            flat = list(_all_artifacts_flat(registry))
            first_artifact = flat[0][2]
            monkeypatch.setattr(
                "makerrepo_cli.cmds.artifacts.main._prompt_artifact_selection",
                lambda reg: [first_artifact],
            )
            output_file = tmp_path / "snap_camera.png"
            result = cli_runner.invoke(
                cli,
                ["artifacts", "snapshot", "-o", str(output_file), "--camera", "top"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert output_file.exists()

    await asyncio.wait_for(asyncio.to_thread(operate), 10)
    assert captured_config.get("reset_camera") == "top"


def test_snapshot_camera_invalid(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    with switch_cwd(fixtures_folder):
        from makerrepo_cli.cmds.artifacts.main import _all_artifacts_flat
        from makerrepo_cli.cmds.shared.repo import collect_from_repo

        registry = collect_from_repo()
        flat = list(_all_artifacts_flat(registry))
        first_artifact = flat[0][2]
        monkeypatch.setattr(
            "makerrepo_cli.cmds.artifacts.main._prompt_artifact_selection",
            lambda reg: [first_artifact],
        )
        result = cli_runner.invoke(
            cli,
            [
                "artifacts",
                "snapshot",
                "-o",
                str(tmp_path / "out.png"),
                "--camera",
                "reset",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 2
    assert "Invalid value" in result.output or "reset" in result.output


@pytest.mark.asyncio
async def test_snapshot(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    def operate():
        with switch_cwd(fixtures_folder):
            from makerrepo_cli.cmds.artifacts.main import _all_artifacts_flat
            from makerrepo_cli.cmds.shared.repo import collect_from_repo

            registry = collect_from_repo()
            flat = list(_all_artifacts_flat(registry))
            first_artifact = flat[0][2]
            monkeypatch.setattr(
                "makerrepo_cli.cmds.artifacts.main._prompt_artifact_selection",
                lambda reg: [first_artifact],
            )
            output_file = tmp_path / "test_snapshot.png"
            result = cli_runner.invoke(
                cli,
                ["artifacts", "snapshot", "-o", str(output_file)],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        # Verify output file was created
        assert output_file.exists()
        # Verify it's a valid PNG image (PNG magic bytes: 89 50 4E 47)
        screenshot_bytes = output_file.read_bytes()
        assert len(screenshot_bytes) > 0, "Screenshot should not be empty"
        assert screenshot_bytes.startswith(b"\x89PNG\r\n\x1a\n"), (
            "Screenshot should be a valid PNG image"
        )

    # Use real CADViewerService - increase timeout for browser launch
    await asyncio.wait_for(asyncio.to_thread(operate), 60)


def test_export_unknown_extension(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    with switch_cwd(fixtures_folder):
        result = cli_runner.invoke(
            cli,
            ["artifacts", "export", "-o", str(tmp_path / "out.xyz")],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert "Unknown output extension" in result.output
    assert ".xyz" in result.output
    assert "Supported:" in result.output
    assert not (tmp_path / "out.xyz").exists()


def test_export_single_artifact_step(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    with switch_cwd(fixtures_folder):
        from makerrepo_cli.cmds.artifacts.main import _all_artifacts_flat
        from makerrepo_cli.cmds.shared.repo import collect_from_repo

        registry = collect_from_repo()
        flat = list(_all_artifacts_flat(registry))
        first_artifact = flat[0][2]
        monkeypatch.setattr(
            "makerrepo_cli.cmds.artifacts.main._prompt_artifact_selection",
            lambda reg: [first_artifact],
        )
        output_file = tmp_path / "box.step"
        result = cli_runner.invoke(
            cli,
            ["artifacts", "export", "-o", str(output_file)],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert output_file.exists()
    content = output_file.read_text()
    assert "ISO-10303-21" in content


def test_export_with_artifact_name_to_stl(
    monkeypatch: MonkeyPatch,
    cli_runner: CliRunner,
    fixtures_folder: pathlib.Path,
    tmp_path: pathlib.Path,
):
    with switch_cwd(fixtures_folder):
        from makerrepo_cli.cmds.artifacts.main import _all_artifacts_flat
        from makerrepo_cli.cmds.shared.repo import collect_from_repo

        registry = collect_from_repo()
        flat = list(_all_artifacts_flat(registry))
        first_artifact = flat[0][2]
        monkeypatch.setattr(
            "makerrepo_cli.cmds.artifacts.main._prompt_artifact_selection",
            lambda reg: [first_artifact],
        )
        result = cli_runner.invoke(
            cli,
            [
                "artifacts",
                "export",
                "-o",
                str(tmp_path),
                "-f",
                "stl",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    stl_files = list(tmp_path.glob("*.stl"))
    assert len(stl_files) == 1
    data = stl_files[0].read_bytes()
    assert len(data) > 0
    # ASCII STL starts with "solid"; binary STL has 80-byte header + 4-byte count
    assert b"solid" in data[:100] or len(data) >= 84
