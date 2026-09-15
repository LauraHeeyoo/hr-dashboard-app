# This is the MAIN configuration — everything the application actually runs on.
# It is separate from bootstrap/, which only exists to create the storage this
# config's own state lives in (see bootstrap/README.md for why that has to be
# a separate, earlier step).

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.0" # pinned to the 5.x line; bump deliberately, not automatically
    }
  }

  # Empty on purpose. Values that vary (storage account, container, key) are
  # supplied at `terraform init` time via backend-config flags/file, kept out
  # of version-controlled .tf files so the same config can target a
  # different backend later without editing this file.
  #
  # REVISED (see D20 in ARCHITECTURE.md, and bootstrap/main.tf's comment on
  # `shared_access_key_enabled`): the original design authenticated here via
  # Entra ID (`use_azuread_auth = true`), authorized by an RBAC role
  # assignment. Creating that assignment needs
  # `Microsoft.Authorization/roleAssignments/write`, which the currently
  # available Contributor role doesn't include, and no one with broader
  # rights is reachable for about a month — so this backend falls back to the
  # storage account's own access key instead, for now. No key is typed into
  # any file: with `use_azuread_auth` unset (defaults false), Terraform's
  # azurerm backend fetches the key itself via a `listKeys` call using the
  # signed-in `az` session — a control-plane action Contributor already
  # allows. Revisit once the RBAC path is actually usable again.
  backend "azurerm" {}
}

provider "azurerm" {
  subscription_id = var.subscription_id

  # azurerm v5 provider requires an explicit features block even when empty.
  features {}
}
