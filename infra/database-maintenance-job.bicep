targetScope = 'resourceGroup'

@description('Azure region used by the Container Apps environment.')
param location string = resourceGroup().location

@description('Name of the existing Container Apps managed environment.')
param containerAppsEnvironmentName string

@description('Full resource ID of the database-maintenance user-assigned identity.')
param databaseMaintenanceIdentityId string

@description('Login server of the Azure Container Registry containing the maintenance image.')
param containerRegistryLoginServer string

@description('Immutable maintenance image reference, including its tag.')
param databaseMaintenanceImage string

@description('Unversioned Key Vault URI for the database-url secret.')
param databaseUrlSecretUri string

var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id))
var maintenanceJobName = 'job-agenda-db-${resourceToken}'

resource maintenanceEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: containerAppsEnvironmentName
}

resource maintenanceJob 'Microsoft.App/jobs@2024-03-01' = {
  name: maintenanceJobName
  location: location
  tags: {
    component: 'database-maintenance'
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${databaseMaintenanceIdentityId}': {}
    }
  }
  properties: {
    environmentId: maintenanceEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: containerRegistryLoginServer
          identity: databaseMaintenanceIdentityId
        }
      ]
      secrets: [
        {
          name: 'database-url'
          keyVaultUrl: databaseUrlSecretUri
          identity: databaseMaintenanceIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'database-maintenance'
          image: databaseMaintenanceImage
          args: [
            'check'
          ]
          env: [
            {
              name: 'DATABASE_URL'
              secretRef: 'database-url'
            }
          ]
          resources: {
            cpu: any('0.25')
            memory: '0.5Gi'
          }
        }
      ]
    }
  }
}

output databaseMaintenanceJobName string = maintenanceJob.name
