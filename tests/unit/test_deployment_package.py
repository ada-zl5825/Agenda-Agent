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


def test_function_package_includes_phase_five_runtime_dependencies() -> None:
    requirements = Path("requirements.txt").read_text(encoding="utf-8")

    assert "langgraph==" in requirements
    assert "langgraph-checkpoint-postgres==" in requirements
    assert "psycopg-pool==" in requirements


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
    workflow = Path(".github/workflows/deploy-infra.yml").read_text(encoding="utf-8")

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
    workflow = Path(".github/workflows/deploy-infra.yml").read_text(encoding="utf-8")

    assert "LLM_ENABLED: string(llmEnabled)" in infrastructure
    assert "AZURE_OPENAI_ENDPOINT: azureOpenAIEndpoint" in infrastructure
    assert "AZURE_OPENAI_DEPLOYMENT: azureOpenAIDeployment" in infrastructure
    assert "AZURE_OPENAI_API_VERSION: azureOpenAIApiVersion" in infrastructure
    assert "AZURE_CLIENT_ID: runtimeIdentity.properties.clientId" in infrastructure
    assert "AZURE_OPENAI_API_KEY" not in infrastructure
    assert "azureOpenAIEndpoint=${{ vars.AZURE_OPENAI_ENDPOINT }}" in workflow
    assert "azureOpenAIDeployment=${{ vars.AZURE_OPENAI_DEPLOYMENT }}" in workflow


def test_phase_seven_calendar_is_permissioned_but_disabled_by_default() -> None:
    infrastructure = Path("infra/main.bicep").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/deploy-infra.yml").read_text(encoding="utf-8")
    bootstrap = Path("scripts/bootstrap-azure.ps1").read_text(encoding="utf-8")

    assert "param calendarSyncEnabled bool = false" in infrastructure
    assert "CALENDAR_SYNC_ENABLED: string(calendarSyncEnabled)" in infrastructure
    assert "calendarSyncEnabled=${{ vars.CALENDAR_SYNC_ENABLED || 'false' }}" in workflow
    assert "1ec239c2-d7c9-4623-a91a-a9775856bb36" in bootstrap
    assert 'Set-GitHubVariable -Name "CALENDAR_SYNC_ENABLED" -Value "false"' in bootstrap


def test_phase_eight_daily_brief_is_secure_and_disabled_by_default() -> None:
    infrastructure = Path("infra/main.bicep").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/deploy-infra.yml").read_text(encoding="utf-8")
    bootstrap = Path("scripts/bootstrap-azure.ps1").read_text(encoding="utf-8")

    assert "param dailyBriefEnabled bool = false" in infrastructure
    assert "DAILY_BRIEF_SCHEDULE: dailyBriefSchedule" in infrastructure
    assert "DAILY_BRIEF_LOCAL_HOUR: string(dailyBriefLocalHour)" in infrastructure
    assert "param dailyBriefSchedule string = '0 0 * * * *'" in infrastructure
    assert "PUBLIC_APP_BASE_URL: 'https://${functionApp.properties.defaultHostName}'" in (
        infrastructure
    )
    assert "var webSessionSigningSecretName = 'web-session-signing-key'" in infrastructure
    assert "WEB_SESSION_SIGNING_KEY: '@Microsoft.KeyVault(" in infrastructure
    assert "webSessionSigningKey=${{ secrets.WEB_SESSION_SIGNING_KEY }}" in workflow
    assert "dailyBriefEnabled=${{ vars.DAILY_BRIEF_ENABLED || 'false' }}" in workflow
    assert "e383f46e-2787-4529-855e-0e479a3ffac0" in bootstrap
    assert 'Set-GitHubVariable -Name "DAILY_BRIEF_ENABLED" -Value "false"' in bootstrap
    assert 'Set-GitHubSecret -Name "WEB_SESSION_SIGNING_KEY"' in bootstrap


def test_phase_nine_a_deploys_app_and_infrastructure_on_separate_paths() -> None:
    app_workflow = Path(".github/workflows/deploy-app.yml").read_text(encoding="utf-8")
    infra_workflow = Path(".github/workflows/deploy-infra.yml").read_text(encoding="utf-8")
    infrastructure = Path("infra/main.bicep").read_text(encoding="utf-8")
    requirements = Path("requirements.txt").read_text(encoding="utf-8")

    assert "azure/arm-deploy" not in app_workflow
    assert "infra/|scripts/bootstrap-azure" in infra_workflow
    assert "opsApiToken=${{ secrets.OPS_API_TOKEN }}" in infra_workflow
    assert "recruitment-operations" in infrastructure
    assert "OPS_API_TOKEN: '@Microsoft.KeyVault(" in infrastructure
    assert "azure-storage-queue==" in requirements
    assert "^(alembic/|infra/" in app_workflow
    assert "schema_change" in infra_workflow
    assert "Hold application deployment until the migration succeeds" in infra_workflow


def test_console_admin_identity_can_be_bootstrapped_without_a_new_secret() -> None:
    infrastructure = Path("infra/main.bicep").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/deploy-infra.yml").read_text(encoding="utf-8")

    assert "param adminMicrosoftHomeAccountId string = ''" in infrastructure
    assert "ADMIN_MICROSOFT_HOME_ACCOUNT_ID: adminMicrosoftHomeAccountId" in infrastructure
    assert "vars.ADMIN_MICROSOFT_HOME_ACCOUNT_ID" in workflow


def test_database_maintenance_is_a_private_allowlisted_container_apps_job() -> None:
    foundation = Path("infra/database-maintenance-foundation.bicep").read_text(encoding="utf-8")
    job = Path("infra/database-maintenance-job.bicep").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/deploy-infra.yml").read_text(encoding="utf-8")
    dockerfile = Path("infra/database-maintenance/Dockerfile").read_text(encoding="utf-8")
    trigger_script = Path("scripts/start-database-maintenance.ps1").read_text(encoding="utf-8")

    assert "10.20.2.0/27" in foundation
    assert "internal: true" in foundation
    assert "adminUserEnabled: false" in foundation
    assert "KeyVault/vaults" in foundation
    assert "triggerType: 'Manual'" in job
    assert "replicaRetryLimit: 0" in job
    assert "secretRef: 'database-url'" in job
    assert "keyVaultUrl: databaseUrlSecretUri" in job
    assert "databaseMaintenanceIdentityId" in job
    assert "az acr build" in workflow
    assert "database-maintenance-job.bicep" in workflow
    assert "USER agenda" in dockerfile
    assert "properties.template.containers[?name=='database-maintenance']" in trigger_script
    assert "--image $image" in trigger_script
    assert '--env-vars "DATABASE_URL=secretref:database-url"' in trigger_script
