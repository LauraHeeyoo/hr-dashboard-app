variable "subscription_id" {
  description = "Same subscription as the main configuration — kept as its own copy of the variable (not shared) because this is an intentionally standalone, rarely-touched configuration."
  type        = string
  default     = "b8c60067-2059-448d-8028-fbfbe2dceab6"
}

variable "existing_resource_group_name" {
  type    = string
  default = "Demo_dashboards"
}

variable "location" {
  description = "Region for the state-storage account ONLY. Scoped to this bootstrap config on purpose — the main config's `location` variable has no default and is chosen deliberately later; this one staying westeurope is not a precedent for that decision."
  type        = string
  default     = "westeurope"
}

variable "state_storage_account_name" {
  description = "Must be globally unique across all of Azure, lowercase letters/numbers only, 3-24 characters. Checked available via `az storage account check-name` this session."
  type        = string
  default     = "sthrdashtfstate"
}

variable "state_container_name" {
  type    = string
  default = "tfstate"
}
