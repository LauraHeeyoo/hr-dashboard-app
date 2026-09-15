# Sanity-check outputs — useful right after `terraform apply` to confirm this
# config is pointed at the right, existing Resource Group. Nothing sensitive.
output "resource_group_name" {
  value = data.azurerm_resource_group.existing.name
}

output "resource_group_location" {
  value = data.azurerm_resource_group.existing.location
}

# The Container App's system-assigned Managed Identity — not a secret (it's
# an object ID, not a credential), but the thing you need on hand for the
# one-time `CREATE USER ... FROM EXTERNAL PROVIDER` step in db_hr_demo
# (§10.3), and later for any RBAC role assignment granting this identity
# access to something (Key Vault, Azure OpenAI, etc.).
output "container_app_identity_principal_id" {
  value = azurerm_container_app.main.identity[0].principal_id
}
