from __future__ import annotations

import pathlib

from makerrepo_cli.core.repo.repo import collect_from_repo


def test_collect_from_repo_applies_pythonpaths(fixtures_folder: pathlib.Path):
    registry = collect_from_repo(fixtures_folder / "pythonpaths_examples")
    assert "main" in registry.artifacts
    assert "main" in registry.artifacts["main"]
