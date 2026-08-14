[CmdletBinding()]
param(
    [Parameter()]
    [ValidateSet("check", "migrate", "seed-companies")]
    [string] $Operation = "check",

    [Parameter(Mandatory)]
    [string] $ResourceGroupName,

    [Parameter()]
    [string] $JobName = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Get-Command "az" -ErrorAction SilentlyContinue)) {
    throw "Azure CLI is not installed or is not available on PATH."
}

az account show --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Azure CLI is not authenticated. Run 'az login' first."
}

if (-not $JobName) {
    $JobName = az containerapp job list `
        --resource-group $ResourceGroupName `
        --query "[?tags.component=='database-maintenance'].name | [0]" `
        --output tsv `
        --only-show-errors
    if ($LASTEXITCODE -ne 0 -or -not $JobName) {
        throw "No database-maintenance Container Apps Job was found in '$ResourceGroupName'."
    }
}

$image = az containerapp job show `
    --name $JobName `
    --resource-group $ResourceGroupName `
    --query "properties.template.containers[?name=='database-maintenance'] | [0].image" `
    --output tsv `
    --only-show-errors
if ($LASTEXITCODE -ne 0 -or -not $image) {
    throw "Could not resolve the deployed database-maintenance image."
}

$execution = az containerapp job start `
    --name $JobName `
    --resource-group $ResourceGroupName `
    --container-name "database-maintenance" `
    --image $image `
    --cpu 0.25 `
    --memory "0.5Gi" `
    --env-vars "DATABASE_URL=secretref:database-url" `
    --args $Operation `
    --only-show-errors | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "Failed to start database-maintenance operation '$Operation'."
}

Write-Host "Database maintenance operation submitted."
Write-Host "Operation: $Operation"
Write-Host "Job:       $JobName"
Write-Host "Execution: $($execution.name)"
Write-Host "Inspect with: az containerapp job execution show --name $JobName --resource-group $ResourceGroupName --job-execution-name $($execution.name)"
