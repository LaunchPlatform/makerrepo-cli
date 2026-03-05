"""Tests for shell completion (mr completion <shell>)."""
from click.testing import CliRunner

from makerrepo_cli.cmds.main import cli


def test_completion_bash(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(cli, ["completion", "bash"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "_mr_completion" in result.output
    assert "complete" in result.output


def test_completion_zsh(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(cli, ["completion", "zsh"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "mr" in result.output
    assert "#compdef" in result.output or "compdef" in result.output


def test_completion_fish(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(cli, ["completion", "fish"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "mr" in result.output
    assert "complete" in result.output
