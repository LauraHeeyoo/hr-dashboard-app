# Bootstrap: creating the remote state backend

## Why this is a separate configuration

The main configuration (`infra/`) stores its Terraform state remotely, in an Azure Storage
account/container, using the `backend "azurerm" {}` block in `../providers.tf`. But that storage
account is itself an Azure resource — and Terraform can't store a config's state in a resource that
config hasn't created yet, and can't create a resource whose existence it needs before it can start
storing state anywhere. That's the chicken-and-egg problem.

The standard, deliberate way out: a **tiny, separate** Terraform configuration (this directory) that
creates *only* the storage account and blob container, using its own **local** state file (a
`terraform.tfstate` sitting on disk here, applied once, by a human, and not touched again afterwards).
Once that storage account exists, the *main* configuration's `terraform init` is pointed at it, and
everything from that point on uses proper remote state.

This is a deliberate, one-time exception to "always use remote state" — not a precedent for skipping
remote state anywhere else in this project.

## What this creates

- **Nothing new at the Resource Group level** — it reads the existing `Demo_dashboards` Resource Group
  via the same kind of `data` source as the main config (see D12: Terraform never manages that group
  itself).
- One **new** Storage Account inside it, dedicated to Terraform state — never reused for application
  data, and separate from the `stdemodashboards` account that already exists in the same Resource Group
  for whatever the existing demo setup uses it for.
- One **blob container** inside that storage account (`tfstate`), where the main configuration's state
  file will live.

## Access model: storage account key (revised from the original Entra ID plan)

**Original design:** Entra ID authentication only, no key at all, authorized by an RBAC role
assignment. **What actually happened:** creating that role assignment failed —
`Microsoft.Authorization/roleAssignments/write` isn't included in the Contributor role (confirmed via
`az role assignment list`, the only role actually held), and the person who could grant broader rights
(Owner / User Access Administrator) is unavailable for about a month. Rather than block on that, this
step now uses the storage account's own access key instead — a deliberate, documented fallback, not a
silent one:

- `shared_access_key_enabled = true` on the storage account (reverted from `false`).
- The main configuration's backend block (`../providers.tf`) no longer sets `use_azuread_auth` — with
  it unset, Terraform's azurerm backend fetches the storage account key itself via a `listKeys` call,
  using whatever `az` session is active. **No key is ever typed into a file, committed, or pasted
  anywhere by hand** — it's fetched at runtime, the same way the Entra ID path would have fetched a
  token, just authorized by a coarser (control-plane, not data-plane) permission that Contributor
  already includes.
- The `azurerm_role_assignment` this file originally created has been **removed** — no longer needed
  for this access model.

**This isn't fully resolved, just deliberately deferred**: the exact same `roleAssignments/write` gap
will block any *future* role assignment this project's Terraform needs to create — e.g. granting the
Container App's Managed Identity access to Key Vault or Azure OpenAI later in Phase 0.5/1. Revisit the
Entra-ID-only design once someone with sufficient rights is available again; until then, expect to hit
this same wall again and handle it the same way (case by case, documented, not silently worked around).

## Proposed values (review before applying)

| | Value | Notes |
|---|---|---|
| Storage account name | `sthrdashtfstate` | Globally unique across all of Azure — checked available via `az storage account check-name` this session. Lowercase letters/numbers only (storage account naming rules), 15 characters. |
| Container name | `tfstate` | |
| Resource group | `Demo_dashboards` (existing) | |
| Location | `westeurope` | Scoped to this state-storage account only — **not** a precedent for where application resources will live (see ARCHITECTURE.md: that region decision is deliberately still open, made just before the first real application resource). |
| Redundancy | `LRS` (locally redundant) | Deliberately the cheapest option — this is a small demo project's state file, not a production system requiring geo-redundancy. Revisit only if that changes. |
| Access | Storage account key, auto-fetched by Terraform via `listKeys` (Contributor-level) — see above | Blob versioning is enabled so an accidental bad `apply` doesn't destroy state history. |

## How to run this (not yet done)

```bash
cd infra/bootstrap
terraform init      # local state, no backend block here — that's the point
terraform plan       # review exactly these 2 resources before creating anything
terraform apply
```

After this succeeds, the storage account name/container above get passed to the *main* config's
`terraform init` as backend configuration (next step, not part of this file) — something like:

```bash
cd infra
terraform init \
  -backend-config="resource_group_name=Demo_dashboards" \
  -backend-config="storage_account_name=sthrdashtfstate" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=hr-dashboard-app.tfstate"
```

That's a manual, one-time command (or captured in a small `backend.hcl` file, gitignored only if it
ever contains anything sensitive — here it doesn't, it's just names) — not something either
configuration needs to repeat on every future `apply`.

## Secrets

The storage account's access key **is** a secret now (the revised access model above) — but it lives
only inside this storage account itself and inside `bootstrap`'s local `terraform.tfstate` (already
excluded by `.gitignore`'s `*.tfstate` rule). It is never written into any `.tf` file, never passed as
a CLI argument, and never needs to be manually copied anywhere — Terraform fetches it itself via
`listKeys` each time it's needed. Nothing from this step needs Key Vault (consistent with
ARCHITECTURE.md §10.4: Key Vault is introduced only once a real runtime secret needs storing/sharing,
not just fetching on demand by whoever already has Contributor).
