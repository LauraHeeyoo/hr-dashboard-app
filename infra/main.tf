# The existing demo-dashboards Resource Group, referenced — not managed.
# `data` blocks only ever READ; there is no `terraform destroy` risk here,
# and no risk of Terraform ever proposing to change or delete this group.
data "azurerm_resource_group" "existing" {
  name = var.existing_resource_group_name
}

# First real application resource. A Container App Environment (the next
# step) requires a Log Analytics workspace to exist first — a hard Azure
# dependency, not a stylistic choice. A NEW, dedicated workspace, not a
# reuse of `workspace-fademohrdata` (the HR-generator's own, in a different
# resource group) — no cost benefit to sharing (Log Analytics bills per GB
# ingested/retained, not per workspace) and real downsides (mixes an
# unrelated system's logs with ours, couples our observability to a
# resource this project doesn't own or control).
resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${var.project}"
  resource_group_name = data.azurerm_resource_group.existing.name
  location            = var.location

  sku               = "PerGB2018" # the standard pay-as-you-go tier; no reason to pick anything else at this scale
  retention_in_days = 30          # matches the existing workspace-fademohrdata's own retention; enough history to debug, without paying to keep more

  # A cheap, concrete cost guardrail — consistent with this project's general
  # stance on budget caps (ARCHITECTURE.md §10.5): if a bug ever floods logs,
  # this caps the damage rather than relying on noticing a surprise bill.
  # 1 GB/day is generous for a small demo app's actual log volume; raise it
  # deliberately if real usage ever needs more, don't remove it by default.
  daily_quota_gb = 1

  tags = local.common_tags
}

# The "envelope" the Container App itself will run inside — logging wiring,
# the internal network, and scaling infrastructure for one or more Container
# Apps. This is the hard consumer of the Log Analytics workspace above.
#
# No VNet integration (`infrastructure_subnet_id` left unset) and no internal
# load balancer — this app is meant to be publicly reachable (D1: public
# demo), and network isolation isn't a requirement we've set (§10.7: access
# control here is app-level guardrails + RBAC, not network boundaries). No
# zone redundancy either — real availability-zone resilience costs more and
# isn't warranted for a small demo.
resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${var.project}"
  resource_group_name        = data.azurerm_resource_group.existing.name
  location                   = var.location
  logs_destination           = "log-analytics" # required explicitly alongside log_analytics_workspace_id below — the provider supports other log destinations too, this picks ours
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  tags = local.common_tags
}

# The Container App itself — placeholder image for now, real application
# image comes later via the application deployment pipeline, not Terraform
# (§12.2's ownership split, Model A):
#   - Terraform owns everything here EXCEPT the image and revision_suffix.
#   - `lifecycle.ignore_changes` on exactly those two hands them to
#     `az containerapp update` (or the app pipeline) going forward — a later
#     image deploy will NOT show up as drift on the next `terraform plan`.
#   - `revision_mode = "Single"` on purpose: one active revision at a time,
#     matching "the deploy pipeline replaces what's running," not a
#     blue/green multi-revision setup we don't need yet.
# System-assigned Managed Identity is just one more block on this same
# resource (§10.3) — not a separate resource, so it belongs in this same
# step rather than its own.
resource "azurerm_container_app" "main" {
  name                         = "ca-${var.project}"
  resource_group_name          = data.azurerm_resource_group.existing.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  identity {
    type = "SystemAssigned"
  }

  template {
    container {
      name   = "placeholder"
      image  = "mcr.microsoft.com/k8se/quickstart:latest" # bootstrap-only; the app pipeline replaces this (§12.2) — not something to verify working yet
      cpu    = 0.25
      memory = "0.5Gi"
    }

    # Explicit, not left to whatever the provider/API defaults to: scale to
    # zero when idle (nobody's hitting this placeholder), never more than one
    # instance (no reason for this bootstrap image to run multiple copies).
    # Revisit both once the real application has actual traffic patterns.
    min_replicas = 0
    max_replicas = 1
  }

  ingress {
    external_enabled = true
    target_port      = 80 # matches this placeholder image's port — worth confirming once it's up, not a Terraform-level concern
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  tags = local.common_tags

  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
      template[0].revision_suffix,
    ]
  }
}

# The Azure OpenAI resource. `location = var.openai_location`, NOT
# `var.location` — deliberately a different region than the Container App
# Environment above (D23): Azure OpenAI token pricing doesn't vary between
# northeurope/westeurope, and westeurope has the fuller model catalog
# (keeps gpt-5.6-luna available as a future option).
#
# `custom_subdomain_name` is required for an OpenAI-kind Cognitive Services
# account — without it, Entra-ID-based (as opposed to key-based) calls to
# this resource don't have a stable endpoint to authenticate against.
resource "azurerm_cognitive_account" "openai" {
  name                  = "oai-${var.project}"
  resource_group_name   = data.azurerm_resource_group.existing.name
  location              = var.openai_location
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "oai-${var.project}"

  tags = local.common_tags
}

# gpt-5.4-mini — originally written as gpt-4o-mini, chosen for reliability
# over the cheaper gpt-4.1-nano (the cost difference between "mini"-class
# candidate models is fractions of a cent per question, not worth trading
# reliability for). Swapped at apply time: gpt-4o-mini's pinned version
# turned out to already be in "Deprecating" status, closed to new
# deployments (real 400 error, not caught by `plan`/`validate` — this is an
# Azure-side model lifecycle fact, not an HCL correctness issue). Verified
# gpt-5.4-mini is GenerallyAvailable with a Sept-2027 retirement date (the
# longest runway of the current "mini"-tier options checked) before picking
# it, rather than guessing another version and risking the same error again.
resource "azurerm_cognitive_deployment" "gpt5_4_mini" {
  name                 = "gpt-5.4-mini"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  # Stay on the pinned version above as long as it's valid; only move
  # automatically once Microsoft actually retires it, rather than on every
  # new "default version" announcement (the provider's own default) — avoids
  # both an unpinned-in-practice deployment and a hard break at retirement.
  # Note: this does NOT notify us when that happens — no built-in alert is
  # tied to it (tracked as a small Phase 5 observability follow-up below).
  version_upgrade_option = "OnceCurrentVersionExpired"

  model {
    format  = "OpenAI"
    name    = "gpt-5.4-mini"
    version = "2026-03-17"
  }

  sku {
    name     = "GlobalStandard"
    capacity = 10 # 10K TPM — Azure's own default starting capacity; plenty for a low-traffic demo, raise deliberately if real usage needs more
  }
}

# NOT done here (deliberately): granting the Container App's Managed
# Identity access to this account (the `Cognitive Services OpenAI User` role
# assignment from §12.1 step 9). That would hit the exact same
# `Microsoft.Authorization/roleAssignments/write` wall as the bootstrap's
# storage-account role assignment (D20) — and there's no need to walk into
# it now, since nothing calls this resource yet. Deferred to Phase 3, when
# the application actually needs to authenticate to it — by which point the
# rights situation may have changed; if not, expect the same
# key-based-fallback pattern as D20.

# Nothing else yet. This is also the natural end of Phase 0.5's core
# resource list (§12.1) — remaining items (Key Vault, Container Apps Job,
# Front Door, the Function App Terraform import) are each explicitly
# triggered by a later, concrete need, not scheduled up front.
