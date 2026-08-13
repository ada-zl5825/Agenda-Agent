targetScope = 'resourceGroup'

@description('Azure region used by all production resources.')
param location string = resourceGroup().location

@description('Globally unique Azure Function App name.')
@minLength(2)
@maxLength(60)
param functionAppName string

@description('PostgreSQL administrator login name.')
@minLength(1)
param postgresAdministratorLogin string = 'agendaadmin'

@secure()
@description('URL-safe PostgreSQL administrator password. Never commit this value.')
param postgresAdministratorPassword string

@description('Microsoft Entra application (client) ID used for delegated Graph access.')
param microsoftClientId string

@secure()
@description('Microsoft Entra application client secret. Stored in Key Vault.')
param microsoftClientSecret string

@description('Stable connection ID for the single Outlook account.')
param microsoftConnectionId string

@secure()
@description('Base64-encoded 32-byte key used to encrypt the MSAL token cache.')
param tokenCacheEncryptionKey string

@secure()
@minLength(44)
@maxLength(44)
@description('Base64-encoded 32-byte key used exclusively to encrypt recruitment action links.')
param linkEncryptionKey string

@description('IANA timezone used for user-facing schedules.')
param userTimezone string = 'Europe/London'

@description('Timer schedule in NCRONTAB format: every ten minutes by default.')
param mailSyncSchedule string = '0 */10 * * * *'

@description('Enable mail synchronization only after Alembic migrations and OAuth consent complete.')
param mailSyncEnabled bool = false

@description('Enable Phase 4 structured recruitment extraction.')
param llmEnabled bool = false

@description('HTTPS model endpoint. Foundry direct models use the stable /openai/v1 route.')
param azureOpenAIEndpoint string = ''

@description('Structured-output-capable model deployment in the Azure OpenAI resource.')
param azureOpenAIDeployment string = ''

@description('Classic Azure OpenAI API version. Ignored when the endpoint uses /openai/v1.')
param azureOpenAIApiVersion string = '2024-10-21'

@description('Maximum Flex Consumption instance count.')
@minValue(40)
@maxValue(1000)
param maximumInstanceCount int = 40

@description('Memory per Flex Consumption instance in MB.')
@allowed([2048, 4096])
param instanceMemoryMB int = 2048

var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id))
var storageAccountName = 'st${take(resourceToken, 20)}'
var deploymentStorageContainerName = 'app-package-${take(resourceToken, 20)}'
var managedIdentityName = 'id-agenda-runtime-${resourceToken}'
var appServicePlanName = 'plan-agenda-${resourceToken}'
var logAnalyticsName = 'log-agenda-${resourceToken}'
var applicationInsightsName = 'appi-agenda-${resourceToken}'
var keyVaultName = 'kv-agenda-${take(resourceToken, 13)}'
var linkEncryptionSecretName = 'recruitment-link-encryption-key'
var virtualNetworkName = 'vnet-agenda-${resourceToken}'
var postgresServerName = 'psql-agenda-${resourceToken}'
var postgresDatabaseName = 'recruitment'
var postgresPrivateDnsZoneName = 'privatelink.postgres.database.azure.com'

var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
var storageTableDataContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
var monitoringMetricsPublisherRoleId = '3913510d-42f4-4e42-8a64-420c390055eb'
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    retentionInDays: 30
    features: {
      searchVersion: 1
    }
    sku: {
      name: 'PerGB2018'
    }
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: applicationInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    DisableLocalAuth: true
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
    publicNetworkAccess: 'Enabled'
  }

  resource blobService 'blobServices' = {
    name: 'default'
    properties: {
      deleteRetentionPolicy: {
        enabled: true
        days: 7
      }
    }

    resource deploymentContainer 'containers' = {
      name: deploymentStorageContainerName
      properties: {
        publicAccess: 'None'
      }
    }
  }
}

resource runtimeIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
}

resource runtimeBlobOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, runtimeIdentity.id, storageBlobDataOwnerRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwnerRoleId)
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource runtimeBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, runtimeIdentity.id, storageBlobDataContributorRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource runtimeQueueContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, runtimeIdentity.id, storageQueueDataContributorRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource runtimeTableContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, runtimeIdentity.id, storageTableDataContributorRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageTableDataContributorRoleId)
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource runtimeMetricsPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(applicationInsights.id, runtimeIdentity.id, monitoringMetricsPublisherRoleId)
  scope: applicationInsights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringMetricsPublisherRoleId)
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: tenant().tenantId
    enableRbacAuthorization: true
    enablePurgeProtection: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    publicNetworkAccess: 'Enabled'
    sku: {
      family: 'A'
      name: 'standard'
    }
  }
}

resource runtimeKeyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, runtimeIdentity.id, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: virtualNetworkName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.20.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'functions-outbound'
        properties: {
          addressPrefix: '10.20.0.0/26'
          delegations: [
            {
              name: 'flex-consumption-delegation'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'postgresql'
        properties: {
          addressPrefix: '10.20.1.0/24'
          delegations: [
            {
              name: 'postgresql-flexible-server-delegation'
              properties: {
                serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers'
              }
            }
          ]
        }
      }
    ]
  }
}

resource functionSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: virtualNetwork
  name: 'functions-outbound'
}

resource postgresSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: virtualNetwork
  name: 'postgresql'
}

resource postgresPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: postgresPrivateDnsZoneName
  location: 'global'
}

resource postgresPrivateDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: postgresPrivateDnsZone
  name: 'agenda-vnet-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetwork.id
    }
  }
}

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresServerName
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    administratorLogin: postgresAdministratorLogin
    administratorLoginPassword: postgresAdministratorPassword
    version: '16'
    availabilityZone: '1'
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      delegatedSubnetResourceId: postgresSubnet.id
      privateDnsZoneArmResourceId: postgresPrivateDnsZone.id
      publicNetworkAccess: 'Disabled'
    }
    storage: {
      storageSizeGB: 32
      autoGrow: 'Enabled'
    }
  }
  dependsOn: [
    postgresPrivateDnsLink
  ]
}

resource postgresDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgresServer
  name: postgresDatabaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource databaseUrlSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'database-url'
  properties: {
    value: 'postgresql+psycopg://${postgresAdministratorLogin}:${postgresAdministratorPassword}@${postgresServer.properties.fullyQualifiedDomainName}:5432/${postgresDatabase.name}?sslmode=require'
  }
}

resource microsoftClientSecretValue 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'microsoft-client-secret'
  properties: {
    value: microsoftClientSecret
  }
}

resource tokenCacheEncryptionKeyValue 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'token-cache-encryption-key'
  properties: {
    value: tokenCacheEncryptionKey
  }
}

resource linkEncryptionKeyValue 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: linkEncryptionSecretName
  properties: {
    value: linkEncryptionKey
  }
}

resource appServicePlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: appServicePlanName
  location: location
  kind: 'functionapp'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${runtimeIdentity.id}': {}
    }
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    keyVaultReferenceIdentity: runtimeIdentity.id
    virtualNetworkSubnetId: functionSubnet.id
    siteConfig: {
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      vnetRouteAllEnabled: true
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${deploymentStorageContainerName}'
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: runtimeIdentity.id
          }
        }
      }
      runtime: {
        name: 'python'
        version: '3.12'
      }
      scaleAndConcurrency: {
        maximumInstanceCount: maximumInstanceCount
        instanceMemoryMB: instanceMemoryMB
      }
    }
  }

  resource appSettings 'config' = {
    name: 'appsettings'
    properties: {
      APP_ENV: 'production'
      AZURE_CLIENT_ID: runtimeIdentity.properties.clientId
      DATABASE_URL: '@Microsoft.KeyVault(SecretUri=${databaseUrlSecret.properties.secretUriWithVersion})'
      USER_TIMEZONE: userTimezone
      LOG_LEVEL: 'INFO'
      MICROSOFT_CLIENT_ID: microsoftClientId
      MICROSOFT_CLIENT_SECRET: '@Microsoft.KeyVault(SecretUri=${microsoftClientSecretValue.properties.secretUriWithVersion})'
      MICROSOFT_TENANT: 'consumers'
      MICROSOFT_REDIRECT_URI: 'https://${functionApp.properties.defaultHostName}/auth/callback'
      MICROSOFT_CONNECTION_ID: microsoftConnectionId
      TOKEN_CACHE_ENCRYPTION_KEY: '@Microsoft.KeyVault(SecretUri=${tokenCacheEncryptionKeyValue.properties.secretUriWithVersion})'
      TOKEN_CACHE_ENCRYPTION_KEY_VERSION: 'v1'
      AZURE_KEY_VAULT_URL: keyVault.properties.vaultUri
      LINK_ENCRYPTION_KEY_SECRET_NAME: linkEncryptionSecretName
      KEY_VAULT_REQUEST_TIMEOUT_SECONDS: '10'
      LLM_ENABLED: string(llmEnabled)
      AZURE_OPENAI_ENDPOINT: azureOpenAIEndpoint
      AZURE_OPENAI_DEPLOYMENT: azureOpenAIDeployment
      AZURE_OPENAI_API_VERSION: azureOpenAIApiVersion
      AZURE_OPENAI_REQUEST_TIMEOUT_SECONDS: '30'
      AZURE_OPENAI_MAX_RETRY_ATTEMPTS: '3'
      GRAPH_BASE_URL: 'https://graph.microsoft.com/v1.0'
      GRAPH_REQUEST_TIMEOUT_SECONDS: '30'
      GRAPH_MAX_RETRY_ATTEMPTS: '4'
      GRAPH_MAX_RETRY_DELAY_SECONDS: '30'
      MAIL_FOLDER_ID: 'inbox'
      MAIL_SYNC_ENABLED: string(mailSyncEnabled)
      MAIL_SYNC_INTERVAL_MINUTES: '10'
      MAIL_SYNC_SCHEDULE: mailSyncSchedule
      AzureWebJobsStorage__accountName: storage.name
      AzureWebJobsStorage__credential: 'managedidentity'
      AzureWebJobsStorage__clientId: runtimeIdentity.properties.clientId
      APPLICATIONINSIGHTS_CONNECTION_STRING: applicationInsights.properties.ConnectionString
      APPLICATIONINSIGHTS_AUTHENTICATION_STRING: 'ClientId=${runtimeIdentity.properties.clientId};Authorization=AAD'
    }
  }
  dependsOn: [
    runtimeBlobOwner
    runtimeBlobContributor
    runtimeQueueContributor
    runtimeTableContributor
    runtimeMetricsPublisher
    runtimeKeyVaultSecretsUser
  ]
}

output functionAppName string = functionApp.name
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output microsoftRedirectUri string = 'https://${functionApp.properties.defaultHostName}/auth/callback'
output keyVaultName string = keyVault.name
output postgresServerName string = postgresServer.name
