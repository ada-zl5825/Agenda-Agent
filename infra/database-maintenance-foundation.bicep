targetScope = 'resourceGroup'

@description('Azure region used by the existing Agenda Agent production resources.')
param location string = resourceGroup().location

var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id))
var virtualNetworkName = 'vnet-agenda-${resourceToken}'
var logAnalyticsName = 'log-agenda-${resourceToken}'
var keyVaultName = 'kv-agenda-${take(resourceToken, 13)}'
var registryName = 'acragenda${take(resourceToken, 16)}'
var environmentName = 'cae-agenda-db-${resourceToken}'
var maintenanceIdentityName = 'id-agenda-db-maintenance-${resourceToken}'
var maintenanceJobName = 'job-agenda-db-${resourceToken}'
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: virtualNetworkName
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource maintenanceSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: virtualNetwork
  name: 'database-maintenance'
  properties: {
    addressPrefix: '10.20.2.0/27'
    delegations: [
      {
        name: 'container-apps-environment-delegation'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
  }
}

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  tags: {
    component: 'database-maintenance'
  }
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    dataEndpointEnabled: false
    networkRuleBypassOptions: 'AzureServices'
    publicNetworkAccess: 'Enabled'
  }
}

resource maintenanceIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: maintenanceIdentityName
  location: location
  tags: {
    component: 'database-maintenance'
  }
}

resource maintenanceRegistryPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, maintenanceIdentity.id, acrPullRoleId)
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: maintenanceIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource maintenanceKeyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, maintenanceIdentity.id, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: maintenanceIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource maintenanceEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  tags: {
    component: 'database-maintenance'
  }
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: maintenanceSubnet.id
      internal: true
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: false
  }
}

output containerRegistryName string = containerRegistry.name
output containerRegistryLoginServer string = containerRegistry.properties.loginServer
output containerAppsEnvironmentName string = maintenanceEnvironment.name
output databaseMaintenanceIdentityId string = maintenanceIdentity.id
output databaseMaintenanceJobName string = maintenanceJobName
output databaseUrlSecretUri string = '${keyVault.properties.vaultUri}secrets/database-url'
