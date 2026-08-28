terraform {
  required_version = ">= 1.5.0"

  # Remote state in Terraform Cloud - shared between local runs and CI, so
  # both see the same state instead of CI trying to recreate resources that
  # already exist (which is what happened before this was added).
  cloud {
    organization = "trade-etl-case-study"

    workspaces {
      name = "trade-etl-case-study"
    }
  }

  required_providers {
    snowflake = {
      source  = "Snowflake-Labs/snowflake"
      version = ">= 0.94.0, < 1.0.0"
    }
  }
}

provider "snowflake" {
  organization_name = var.snowflake_organization_name
  account_name      = var.snowflake_account_name
  user              = var.snowflake_admin_user
  password          = var.snowflake_admin_password
  role              = "SYSADMIN"
}

# Role creation and role-to-user grants are SECURITYADMIN's job in Snowflake's
# built-in RBAC model, not SYSADMIN's (which owns compute/data objects like
# warehouses, databases, and schemas).
provider "snowflake" {
  alias             = "securityadmin"
  organization_name = var.snowflake_organization_name
  account_name      = var.snowflake_account_name
  user              = var.snowflake_admin_user
  password          = var.snowflake_admin_password
  role              = "SECURITYADMIN"
}
