# Read-only reference to the existing Resource Group — this configuration
# never creates, modifies, or deletes it (same rule as the main config).
data "azurerm_resource_group" "existing" {
  name = var.existing_resource_group_name
}

# The ONE new resource this bootstrap step creates: a storage account
# dedicated to holding Terraform state for this project. Not shared with
# `stdemodashboards` (whatever that existing account is already used for)
# and not shared with any future per-environment split — one state backend,
# one job.
resource "azurerm_storage_account" "tfstate" {
  name                = var.state_storage_account_name
  resource_group_name = data.azurerm_resource_group.existing.name
  location            = var.location

  account_tier             = "Standard"
  account_replication_type = "LRS" # cheapest tier — a small demo project's state, not a system needing geo-redundancy

  # Blob versioning: if a future `terraform apply` from this bootstrap config
  # (rare — this normally runs once and is left alone) ever overwrote
  # something unexpectedly, previous blob versions are recoverable.
  blob_properties {
    versioning_enabled = true
  }

  # REVISED (see D20 in ARCHITECTURE.md): Entra ID / RBAC auth was the original
  # design, but creating the required `Storage Blob Data Contributor` role
  # assignment needs `Microsoft.Authorization/roleAssignments/write` —
  # Contributor (what's actually available right now) deliberately excludes
  # that, and the person who could grant broader rights is unavailable for
  # about a month. Falling back to the storage account's own access key for
  # THIS state backend specifically — a documented, deliberate exception, not
  # a silent reversal. Terraform's azurerm backend fetches this key itself at
  # init/plan/apply time via the signed-in `az` session's `listKeys` call
  # (something Contributor CAN do — it's a control-plane action, unlike the
  # data-plane RBAC grant above) — no key is ever typed into a file by hand.
  shared_access_key_enabled = true

  public_network_access = "Enabled" # still reachable over the network (from a dev machine / CI runner)
  min_tls_version       = "TLS1_2"

  tags = {
    project    = "hrdash"
    managed_by = "terraform-bootstrap"
    purpose    = "terraform-remote-state"
  }
}

resource "azurerm_storage_container" "tfstate" {
  name                  = var.state_container_name
  storage_account_id    = azurerm_storage_account.tfstate.id
  container_access_type = "private"
}

# REMOVED (was here): an `azurerm_role_assignment` granting the signed-in user
# "Storage Blob Data Contributor" on this storage account, for the originally
# planned Entra-ID-only access model. Creating it failed with a 403 —
# `Microsoft.Authorization/roleAssignments/write` isn't included in the
# Contributor role, and no one with broader rights is available right now
# (see the comment on `shared_access_key_enabled` above). Revisit once that's
# no longer true, and note the SAME wall applies to any future role
# assignment this project's Terraform tries to create — e.g. later, granting
# the Container App's Managed Identity access to Key Vault or Azure OpenAI —
# so this isn't a one-off, it'll need addressing again.
