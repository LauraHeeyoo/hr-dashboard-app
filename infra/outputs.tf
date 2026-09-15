# Sanity-check outputs — useful right after `terraform apply` to confirm this
# config is pointed at the right, existing Resource Group. Nothing sensitive.
output "resource_group_name" {
  value = data.azurerm_resource_group.existing.name
}

output "resource_group_location" {
  value = data.azurerm_resource_group.existing.location
}
