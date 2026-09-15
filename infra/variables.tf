variable "subscription_id" {
  description = "Azure subscription this configuration deploys into. Explicit on purpose: don't rely on whichever subscription happens to be `az account show`'s default at apply time."
  type        = string
  default     = "b8c60067-2059-448d-8028-fbfbe2dceab6" # "Beheer_Productie" — confirmed via `az account show`
}

variable "existing_resource_group_name" {
  description = "The pre-existing demo-dashboards Resource Group. Referenced as a data source only — never created, modified, or deleted by this configuration (see README.md)."
  type        = string
  default     = "Demo_dashboards"
}

variable "location" {
  description = <<-EOT
    Azure region for NEW application resources (Log Analytics, Container App
    Environment, Container App, later Azure OpenAI, etc.).

    DECIDED (D21 in ARCHITECTURE.md) as "northeurope" — not inherited from
    the Resource Group's own "westeurope" metadata, and not the naive
    "just match the SQL server's region" guess either; chosen after actually
    comparing westeurope vs. northeurope on all four criteria that mattered:
      - Azure Container Apps: northeurope is ~25-30% cheaper on the Standard
        consumption meters (vCPU, memory, requests) — real Retail Prices API
        data, not an estimate, and the most cost-impactful factor since this
        runs continuously;
      - Log Analytics: northeurope ~7.7% cheaper on ingestion/retention;
      - Azure OpenAI: identical token pricing in both regions — a non-factor;
      - model availability: northeurope has gpt-4o, gpt-4o-mini, gpt-4.1,
        gpt-4.1-mini, gpt-4.1-nano — entirely sufficient for this project's
        chat feature; it lacks only the newest gpt-5.x/6 generations, not
        currently needed (westeurope's advantage here didn't outweigh the
        cost difference above);
      - proximity to Azure SQL (srv-demo-dashboards is in northeurope):
        a bonus, not the deciding factor, but it lines up.
    Revisit only if a genuinely new requirement (e.g. needing a model that's
    northeurope-exclusive-absent) makes this worth reopening.

    Does NOT cover Azure OpenAI — see `openai_location` below (D23).
  EOT
  type        = string
  default     = "northeurope"
}

variable "openai_location" {
  description = <<-EOT
    Azure region for the Azure OpenAI resource specifically — deliberately
    decoupled from `var.location` (D23 in ARCHITECTURE.md).

    Why a separate variable: Azure OpenAI is an independent resource with its
    own regional characteristics, not tied to where compute happens to run.
    Verified: token pricing is IDENTICAL between northeurope and westeurope
    (0 differences across 300+ compared meters) — so there is no cost reason
    to keep it in northeurope alongside compute. westeurope has the fuller
    model catalog, including gpt-5.6-luna (not available in northeurope) —
    kept available as a future option even though gpt-4o-mini (available in
    both regions, chosen for its reliability over the cheaper gpt-4.1-nano at
    a fractions-of-a-cent-per-question cost difference) is the initial model.
    A few ms of extra cross-region latency to the Container App in
    northeurope is immaterial for a chat feature.
  EOT
  type        = string
  default     = "westeurope"
}

variable "project" {
  description = "Short, stable project identifier used as a resource-name prefix and tag, so this project's resources are visually distinguishable inside the shared Resource Group."
  type        = string
  default     = "hrdash"
}

variable "environment" {
  description = "Deployment environment label. Single environment for now (D5: no premature dev/test/prod split) — this variable exists so that split is a config change later, not a rewrite."
  type        = string
  default     = "dev"
}

locals {
  # Every new resource gets these tags, so `az resource list -g Demo_dashboards`
  # unambiguously shows which resources belong to this project vs. the older,
  # unrelated resources already sitting in the same Resource Group.
  common_tags = {
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
    repo        = "HR Dashboard app/infra"
  }
}
