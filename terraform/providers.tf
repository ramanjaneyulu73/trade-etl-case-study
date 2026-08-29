terraform {
  required_version = ">= 1.5.0"

  # Remote state (Terraform Cloud) is optional - see backend.tf.example.

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

# Creating a notification integration is account-level admin territory in
# Snowflake, not grantable to a custom role without extra ceremony - use
# ACCOUNTADMIN directly for that one resource, same as any cloud provider's
# IaC needs an elevated role for account-wide objects.
provider "snowflake" {
  alias             = "accountadmin"
  organization_name = var.snowflake_organization_name
  account_name      = var.snowflake_account_name
  user              = var.snowflake_admin_user
  password          = var.snowflake_admin_password
  role              = "ACCOUNTADMIN"
}

# The alert's condition/action read from the MARTS schema, which TRADE_ETL_ROLE
# owns (dbt runs as this role) - creating the alert as this role, not SYSADMIN,
# means it can actually see the tables it's monitoring without extra grants.
provider "snowflake" {
  alias             = "trade_etl_role"
  organization_name = var.snowflake_organization_name
  account_name      = var.snowflake_account_name
  user              = var.snowflake_admin_user
  password          = var.snowflake_admin_password
  role              = "TRADE_ETL_ROLE"
}
