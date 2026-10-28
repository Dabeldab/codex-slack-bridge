# Azure DevOps relay shim

ChatGPT Work is awakened through GitHub PR activity, so Azure DevOps is connected as an outer relay shim rather than a direct ChatGPT app. Developer Mode is not required.

## Authentication

Use a Microsoft Entra service principal plus GitHub OIDC. No Azure DevOps PAT and no client secret are stored in GitHub.

The bootstrap script creates/verifies:

- an Entra application/service principal;
- a federated credential restricted to `repo:dariusmakesstuff/codex-slack-bridge:environment:azure-relay`;
- an Azure DevOps service-principal entitlement using the service principal object ID;
- optional project membership.

Run a plan first:

```powershell
.\scripts\bootstrap-azure-devops-relay.ps1 -Organization YOUR_ORG -Project YOUR_PROJECT
```

Then apply from an Azure CLI session belonging to an Entra/Azure DevOps admin:

```powershell
az login --allow-no-subscriptions
.\scripts\bootstrap-azure-devops-relay.ps1 -Organization YOUR_ORG -Project YOUR_PROJECT -Apply
```

The script prints non-secret values to add to the protected GitHub environment `azure-relay`:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_DEVOPS_ORGANIZATION`
- `AZURE_DEVOPS_PROJECT`

Run the **Azure DevOps Relay Probe** workflow. It uses `azure/login` OIDC, obtains an Azure DevOps resource token for `499b84ac-1321-427f-aa17-267ca6975798`, and performs a bounded project read.

## Relay topology

```text
Azure DevOps event / pipeline
          |
          v
Microsoft Entra workload identity
          |
          v
GitHub relay shim
          |
          v
long-lived GitHub PR -> ChatGPT Work
          |
          v
GitHub normalized response
          |
          v
Command Center / Azure DevOps
```

For the first production cutover, GitHub remains the canonical reasoning mailbox. Azure is an additional ingress/egress surface. This prevents Azure-specific auth or service-hook behavior from weakening the local lane/capability contract.

The organization/project values are intentionally not hard-coded because they are account-specific and were not available to the implementation session.
