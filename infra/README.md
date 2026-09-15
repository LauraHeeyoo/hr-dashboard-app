# Infrastructure (Terraform)

This directory is the **only** thing Terraform manages for the HR Dashboard app. Nothing outside
`infra/` is touched by `terraform apply`.

## What Terraform manages vs. what it doesn't

| | Managed by Terraform? |
|---|---|
| Resource group `Demo_dashboards` | **No.** Pre-existing, referenced as a `data` source (`main.tf`). Terraform never creates, modifies, or deletes it. |
| `srv-demo-dashboards` (SQL logical server) + `db_hr_demo` | **No.** Existing dependency. Terraform only ever reads facts about the resource group it lives in — never touches the server or database themselves. |
| `fa-demo-hr-datagenerator` (Function App, the HR data simulator) | **No**, for now. A candidate for a *later, separate* Terraform-import exercise — deliberately not attempted yet. |
| `stdemodashboards` (existing storage account) | **No.** Whatever it's already used for is not this project's concern. A **new, separate** storage account is created for Terraform's own state (see `bootstrap/`) — state storage is never mixed with an existing, differently-purposed account. |
| The state-backend storage account + container (`bootstrap/`) | **Yes** — but applied once, by hand, from `bootstrap/`'s own *local* state, before the main configuration can use it. Chicken-and-egg: the storage that will hold remote state can't itself start out managed by that same remote state. |
| Everything the app actually runs on (Log Analytics, Container App Environment, Container App, Managed Identity, later Azure OpenAI, later a Container Apps Job, later Front Door) | **Yes.** Added one resource at a time, in this main configuration, once `bootstrap/` is done. |

## Layout

```
infra/
├── bootstrap/          # one-time, local-state-only: creates the remote state backend itself
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── README.md
├── providers.tf         # terraform{} block, provider "azurerm", backend "azurerm" (empty until bootstrap runs)
├── variables.tf
├── main.tf              # the existing Resource Group as a data source; new resources added here over time
└── outputs.tf
```

No modules yet, and deliberately so — this is a single environment today. A module is worth extracting
only once a second environment genuinely duplicates these resources, not before.

## Working agreement for this phase

From this point on, **all Terraform CLI commands (`init`, `fmt`, `validate`, `plan`, `apply`, `destroy`,
`import`, `state ...`) are run by Laura, not by Claude** — this is a deliberate Terraform-learning
choice, not a technical constraint. Claude writes/edits `.tf` files, explains what a command does and
what output to expect before it's run, and analyzes the output afterwards. Read-only Azure CLI checks
(existing-resource lookups, region/service/name availability, identity/permission status) remain fine
either way; Azure CLI commands that *mutate* anything Terraform is supposed to be creating are not a
backdoor around that — if it's this project's Terraform's job, it goes through Terraform, run by Laura.

## Status

- ✅ Confirmed: a Microsoft Entra admin is already configured on `srv-demo-dashboards` (the signed-in
  account itself, per `az sql server ad-admin list`) — the Managed-Identity design in `ARCHITECTURE.md`
  §10.3 can proceed without first arranging that prerequisite.
- ✅ `providers.tf` / `variables.tf` / `main.tf` written.
- ✅ `bootstrap/` written, now using **Entra ID (Azure RBAC) auth instead of a storage account key** —
  `shared_access_key_enabled = false` on the storage account, `use_azuread_auth = true` on the main
  config's backend block, and a `Storage Blob Data Contributor` role assignment scoped to just that
  storage account. **Not yet applied.**
- ✅ The main config's `location` variable no longer defaults to the Resource Group's own region
  (`westeurope`) — it's unset on purpose until a deliberate region decision is made (proximity to
  `srv-demo-dashboards` in `northeurope`, service/quota availability, cost) right before the first real
  application resource is created. The bootstrap's state-storage account staying in `westeurope` is
  unaffected by this and not a precedent for it.
- ✅ `.gitignore` added at the project root (Terraform state/plan/cache files excluded;
  `.terraform.lock.hcl` deliberately kept).
- ⏳ **Next (Laura runs this): `terraform init` inside `infra/bootstrap/`** — see the message accompanying
  this update for exactly what to run, what it does, and what to report back.
