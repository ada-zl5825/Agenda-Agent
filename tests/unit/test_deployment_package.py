"""Regression tests for the Azure Functions remote-build package."""

import json
from pathlib import Path


def test_function_package_installs_project_non_editably() -> None:
    """Remote builds must install the project into the runtime site-packages directory."""
    requirement_lines = [
        line.strip()
        for line in Path("requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert requirement_lines[0] == "."
    assert not any(
        line == "-e" or line.startswith(("-e ", "--editable "))
        for line in requirement_lines
    )


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


def test_action_link_key_is_separate_and_resolved_through_managed_identity() -> None:
    infrastructure = Path("infra/main.bicep").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/deploy-azure.yml").read_text(encoding="utf-8")

    assert "param linkEncryptionKey string" in infrastructure
    assert "var linkEncryptionSecretName = 'recruitment-link-encryption-key'" in infrastructure
    assert "AZURE_KEY_VAULT_URL: keyVault.properties.vaultUri" in infrastructure
    assert "AZURE_CLIENT_ID: runtimeIdentity.properties.clientId" in infrastructure
    assert "LINK_ENCRYPTION_KEY_SECRET_NAME: linkEncryptionSecretName" in infrastructure
    assert "runtimeKeyVaultSecretsUser" in infrastructure
    assert "linkEncryptionKey=${{ secrets.LINK_ENCRYPTION_KEY }}" in workflow


def test_http_routes_have_no_default_api_prefix() -> None:
    """Public FastAPI and OAuth routes are mounted at the site root."""
    host_config = json.loads(Path("host.json").read_text(encoding="utf-8"))

    assert host_config["extensions"]["http"]["routePrefix"] == ""


def test_phase_four_uses_managed_identity_azure_openai_configuration() -> None:
    infrastructure = Path("infra/main.bicep").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/deploy-azure.yml").read_text(encoding="utf-8")

    assert "LLM_ENABLED: string(llmEnabled)" in infrastructure
    assert "AZURE_OPENAI_ENDPOINT: azureOpenAIEndpoint" in infrastructure
    assert "AZURE_OPENAI_DEPLOYMENT: azureOpenAIDeployment" in infrastructure
    assert "AZURE_OPENAI_API_VERSION: azureOpenAIApiVersion" in infrastructure
    assert "AZURE_CLIENT_ID: runtimeIdentity.properties.clientId" in infrastructure
    assert "AZURE_OPENAI_API_KEY" not in infrastructure
    assert "azureOpenAIEndpoint=${{ vars.AZURE_OPENAI_ENDPOINT }}" in workflow
    assert "azureOpenAIDeployment=${{ vars.AZURE_OPENAI_DEPLOYMENT }}" in workflow
