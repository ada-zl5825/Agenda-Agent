[CmdletBinding()]
param(
    [Parameter()]
    [string] $ResourceGroupName = "rg-agenda-agent-prod-uks",

    [Parameter()]
    [string] $GitHubRepository = "ada-zl5825/Agenda-Agent",

    [Parameter()]
    [string] $EnvironmentName = "production",

    [Parameter()]
    [string] $SubscriptionId = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-Command {
    param([Parameter(Mandatory)][string] $Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' is not installed."
    }
}

function New-RandomUrlSafeSecret {
    param([Parameter(Mandatory)][int] $ByteCount)

    $bytes = [byte[]]::new($ByteCount)
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $random.GetBytes($bytes)
    }
    finally {
        $random.Dispose()
    }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "A").Replace("/", "B")
}

function Set-GitHubVariable {
    param(
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][string] $Value
    )

    gh variable set $Name --repo $GitHubRepository --env $EnvironmentName --body $Value
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to set GitHub variable '$Name'."
    }
}

function Set-GitHubSecret {
    param(
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][string] $Value
    )

    $Value | gh secret set $Name --repo $GitHubRepository --env $EnvironmentName
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to set GitHub secret '$Name'."
    }
}

Assert-Command -Name "az"
Assert-Command -Name "gh"

gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "GitHub CLI is not authenticated. Run 'gh auth login' first."
}

az account show --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) {
    az login --use-device-code | Out-Null
}

if ($SubscriptionId) {
    az account set --subscription $SubscriptionId
}

$account = az account show --only-show-errors | ConvertFrom-Json
$SubscriptionId = [string] $account.id
$tenantId = [string] $account.tenantId
$resourceGroup = az group show --name $ResourceGroupName --only-show-errors | ConvertFrom-Json
$resourceGroupId = [string] $resourceGroup.id
$repository = gh api "repos/$GitHubRepository" | ConvertFrom-Json
$oidcSubject = "repo:$($repository.owner.login)@$($repository.owner.id)/$($repository.name)@$($repository.id):environment:$EnvironmentName"

$requiredProviders = @(
    "Microsoft.App",
    "Microsoft.Authorization",
    "Microsoft.ContainerRegistry",
    "Microsoft.DBforPostgreSQL",
    "Microsoft.Insights",
    "Microsoft.KeyVault",
    "Microsoft.ManagedIdentity",
    "Microsoft.Network",
    "Microsoft.OperationalInsights",
    "Microsoft.Storage",
    "Microsoft.Web"
)
foreach ($provider in $requiredProviders) {
    $registrationState = az provider show `
        --namespace $provider `
        --query registrationState `
        --output tsv `
        --only-show-errors
    if ($registrationState -ne "Registered") {
        az provider register --namespace $provider --only-show-errors | Out-Null
    }
}

$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    $subscriptionHashBytes = $sha256.ComputeHash(
        [System.Text.Encoding]::UTF8.GetBytes($SubscriptionId)
    )
}
finally {
    $sha256.Dispose()
}
$subscriptionHash = ([BitConverter]::ToString($subscriptionHashBytes) -replace "-", "").Substring(
    0,
    8
).ToLowerInvariant()
$functionAppName = "func-agenda-agent-$subscriptionHash"
$redirectUri = "https://$functionAppName.azurewebsites.net/auth/callback"

$deploymentIdentityName = "id-agenda-github-production"
$identityJson = az identity list `
    --resource-group $ResourceGroupName `
    --query "[?name=='$deploymentIdentityName'] | [0]" `
    --only-show-errors
if ([string]::IsNullOrWhiteSpace($identityJson) -or $identityJson -eq "null") {
    $identityJson = az identity create `
        --name $deploymentIdentityName `
        --resource-group $ResourceGroupName `
        --location $resourceGroup.location `
        --only-show-errors
}
$deploymentIdentity = $identityJson | ConvertFrom-Json

$roleAssignments = @(
    "Contributor",
    "Role Based Access Control Administrator"
)
foreach ($role in $roleAssignments) {
    $existingRoleAssignment = az role assignment list `
        --assignee-object-id $deploymentIdentity.principalId `
        --role $role `
        --scope $resourceGroupId `
        --query '[0].id' `
        --output tsv `
        --only-show-errors
    if (-not $existingRoleAssignment) {
        az role assignment create `
            --assignee-object-id $deploymentIdentity.principalId `
            --assignee-principal-type ServicePrincipal `
            --role $role `
            --scope $resourceGroupId `
            --only-show-errors | Out-Null
    }
}

$federatedCredentialName = "github-production-environment"
$federatedCredentialId = az identity federated-credential list `
    --identity-name $deploymentIdentityName `
    --resource-group $ResourceGroupName `
    --query "[?name=='$federatedCredentialName'] | [0].id" `
    --output tsv `
    --only-show-errors
if (-not $federatedCredentialId) {
    az identity federated-credential create `
        --name $federatedCredentialName `
        --identity-name $deploymentIdentityName `
        --resource-group $ResourceGroupName `
        --issuer "https://token.actions.githubusercontent.com" `
        --subject $oidcSubject `
        --audiences "api://AzureADTokenExchange" `
        --only-show-errors | Out-Null
}
else {
    az identity federated-credential update `
        --name $federatedCredentialName `
        --identity-name $deploymentIdentityName `
        --resource-group $ResourceGroupName `
        --issuer "https://token.actions.githubusercontent.com" `
        --subject $oidcSubject `
        --audiences "api://AzureADTokenExchange" `
        --only-show-errors | Out-Null
}

gh api `
    --method PUT `
    "repos/$GitHubRepository/environments/$EnvironmentName" `
    -F "deployment_branch_policy[protected_branches]=false" `
    -F "deployment_branch_policy[custom_branch_policies]=true" | Out-Null

$branchPolicies = gh api `
    "repos/$GitHubRepository/environments/$EnvironmentName/deployment-branch-policies" |
    ConvertFrom-Json
$branchPolicyExists = $branchPolicies.branch_policies |
    Where-Object { $_.name -eq "main" } |
    Select-Object -First 1
if (-not $branchPolicyExists) {
    gh api `
        --method POST `
        "repos/$GitHubRepository/environments/$EnvironmentName/deployment-branch-policies" `
        -f name="main" `
        -f type="branch" | Out-Null
}

$appDisplayName = "Agenda Agent Production"
$applicationJson = az ad app list `
    --display-name $appDisplayName `
    --query '[0]' `
    --only-show-errors
if ([string]::IsNullOrWhiteSpace($applicationJson) -or $applicationJson -eq "null") {
    $applicationJson = az ad app create `
        --display-name $appDisplayName `
        --sign-in-audience AzureADandPersonalMicrosoftAccount `
        --web-redirect-uris $redirectUri `
        --only-show-errors
}
$application = $applicationJson | ConvertFrom-Json
$microsoftClientId = [string] $application.appId

az ad app update `
    --id $microsoftClientId `
    --web-redirect-uris $redirectUri `
    --only-show-errors | Out-Null

$graphResourceAppId = "00000003-0000-0000-c000-000000000000"
$userReadScopeId = "e1fe6dd8-ba31-4d61-89e7-88639da4683d"
$mailReadScopeId = "570282fd-fa5c-430d-a7fd-fc8dc98a9dca"
$calendarsReadWriteScopeId = "1ec239c2-d7c9-4623-a91a-a9775856bb36"
$mailSendScopeId = "e383f46e-2787-4529-855e-0e479a3ffac0"
$configuredGraphScopes = az ad app permission list `
    --id $microsoftClientId `
    --query "[?resourceAppId=='$graphResourceAppId'].resourceAccess[].id" `
    --output tsv `
    --only-show-errors
$requiredGraphScopeIds = @(
    $userReadScopeId,
    $mailReadScopeId,
    $calendarsReadWriteScopeId
    $mailSendScopeId
)
$missingGraphPermissions = @(
    $requiredGraphScopeIds |
        Where-Object { $configuredGraphScopes -notcontains $_ } |
        ForEach-Object { "$_=Scope" }
)
if ($missingGraphPermissions.Count -gt 0) {
    az ad app permission add `
        --id $microsoftClientId `
        --api $graphResourceAppId `
        --api-permissions $missingGraphPermissions `
        --only-show-errors | Out-Null
}

$clientCredential = az ad app credential reset `
    --id $microsoftClientId `
    --append `
    --display-name "github-production" `
    --years 1 `
    --only-show-errors | ConvertFrom-Json

$microsoftConnectionId = [guid]::NewGuid().ToString()
$postgresPassword = New-RandomUrlSafeSecret -ByteCount 32
$tokenCacheKeyBytes = [byte[]]::new(32)
$tokenKeyRandom = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $tokenKeyRandom.GetBytes($tokenCacheKeyBytes)
}
finally {
    $tokenKeyRandom.Dispose()
}
$tokenCacheKey = [Convert]::ToBase64String($tokenCacheKeyBytes)
$linkEncryptionKeyBytes = [byte[]]::new(32)
$linkKeyRandom = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $linkKeyRandom.GetBytes($linkEncryptionKeyBytes)
}
finally {
    $linkKeyRandom.Dispose()
}
$linkEncryptionKey = [Convert]::ToBase64String($linkEncryptionKeyBytes)
$webSessionKeyBytes = [byte[]]::new(32)
$webSessionRandom = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $webSessionRandom.GetBytes($webSessionKeyBytes)
}
finally {
    $webSessionRandom.Dispose()
}
$webSessionSigningKey = [Convert]::ToBase64String($webSessionKeyBytes)
$opsApiTokenBytes = [byte[]]::new(32)
$opsApiTokenRandom = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $opsApiTokenRandom.GetBytes($opsApiTokenBytes)
}
finally {
    $opsApiTokenRandom.Dispose()
}
$opsApiToken = [Convert]::ToBase64String($opsApiTokenBytes)

Set-GitHubVariable -Name "AZURE_CLIENT_ID" -Value ([string] $deploymentIdentity.clientId)
Set-GitHubVariable -Name "AZURE_TENANT_ID" -Value $tenantId
Set-GitHubVariable -Name "AZURE_SUBSCRIPTION_ID" -Value $SubscriptionId
Set-GitHubVariable -Name "CALENDAR_SYNC_ENABLED" -Value "false"
Set-GitHubVariable -Name "DAILY_BRIEF_ENABLED" -Value "false"
Set-GitHubVariable -Name "WORKFLOW_PROCESSING_ENABLED" -Value "false"
Set-GitHubVariable -Name "AZURE_RESOURCE_GROUP" -Value $ResourceGroupName
Set-GitHubVariable -Name "AZURE_FUNCTIONAPP_NAME" -Value $functionAppName
Set-GitHubVariable -Name "MICROSOFT_CLIENT_ID" -Value $microsoftClientId
Set-GitHubVariable -Name "MICROSOFT_CONNECTION_ID" -Value $microsoftConnectionId

Set-GitHubSecret -Name "POSTGRES_ADMIN_PASSWORD" -Value $postgresPassword
Set-GitHubSecret -Name "MICROSOFT_CLIENT_SECRET" -Value ([string] $clientCredential.password)
Set-GitHubSecret -Name "TOKEN_CACHE_ENCRYPTION_KEY" -Value $tokenCacheKey
Set-GitHubSecret -Name "LINK_ENCRYPTION_KEY" -Value $linkEncryptionKey
Set-GitHubSecret -Name "WEB_SESSION_SIGNING_KEY" -Value $webSessionSigningKey
Set-GitHubSecret -Name "OPS_API_TOKEN" -Value $opsApiToken

Write-Host "Bootstrap complete."
Write-Host "Repository:        $GitHubRepository"
Write-Host "Resource group:    $ResourceGroupName"
Write-Host "Function app:      $functionAppName"
Write-Host "OAuth redirect:    $redirectUri"
Write-Host "Next: push the deployment files to main or run deploy-production manually."
