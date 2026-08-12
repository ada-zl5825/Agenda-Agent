"""Regression tests for the Azure Functions remote-build package."""

import json
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


def test_flex_function_app_uses_function_app_config_for_python_runtime() -> None:
    """Flex Consumption rejects the legacy worker-runtime app setting."""
    infrastructure = Path("infra/main.bicep").read_text(encoding="utf-8")

    assert "runtime: {" in infrastructure
    assert "name: 'python'" in infrastructure
    assert "version: '3.12'" in infrastructure
    assert "FUNCTIONS_WORKER_RUNTIME" not in infrastructure
    assert "FUNCTIONS_EXTENSION_VERSION" not in infrastructure


def test_http_routes_have_no_default_api_prefix() -> None:
    """Public FastAPI and OAuth routes are mounted at the site root."""
    host_config = json.loads(Path("host.json").read_text(encoding="utf-8"))

    assert host_config["extensions"]["http"]["routePrefix"] == ""
