# These three values are exactly what get passed to the MAIN config's
# `terraform init -backend-config=...` afterwards (see README.md).
output "storage_account_name" {
  value = azurerm_storage_account.tfstate.name
}

output "container_name" {
  value = azurerm_storage_container.tfstate.name
}

output "resource_group_name" {
  value = data.azurerm_resource_group.existing.name
}
