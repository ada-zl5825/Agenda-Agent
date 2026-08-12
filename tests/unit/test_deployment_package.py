"""Regression tests for the Azure Functions remote-build package."""

from pathlib import Path


def test_function_package_keeps_project_readme() -> None:
    """The build backend needs the pyproject readme during ``pip install .``."""
    ignored_patterns = {
        line.strip()
        for line in Path(".funcignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "README.md" not in ignored_patterns
    assert "*.md" not in ignored_patterns
    assert Path("README.md").is_file()
