# Deliberately NO `backend` block here — this configuration's state stays
# local (a terraform.tfstate file in this folder). See README.md for why.

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.0"
    }
  }
}

provider "azurerm" {
  subscription_id = var.subscription_id
  features {}
}
