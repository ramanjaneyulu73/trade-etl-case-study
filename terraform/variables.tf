variable "snowflake_organization_name" {
  description = "Snowflake organization name (the part before the hyphen in an org-account identifier, e.g. LCVNXNE in LCVNXNE-QC12462)"
  type        = string
}

variable "snowflake_account_name" {
  description = "Snowflake account name (the part after the hyphen in an org-account identifier, e.g. QC12462 in LCVNXNE-QC12462)"
  type        = string
}

variable "snowflake_admin_user" {
  description = "Login used to run Terraform. Must have SYSADMIN + SECURITYADMIN in the trial account."
  type        = string
}

variable "snowflake_admin_password" {
  description = "Password for snowflake_admin_user."
  type        = string
  sensitive   = true
}

variable "service_user_name" {
  description = "Existing Snowflake login (e.g. the trial account's own user) to grant the trade_etl role to, for pipeline scripts and dbt."
  type        = string
}

variable "database_name" {
  type    = string
  default = "TRADE_ETL_DB"
}

variable "warehouse_name" {
  type    = string
  default = "TRADE_ETL_WH"
}

variable "warehouse_size" {
  type    = string
  default = "XSMALL"
}

variable "role_name" {
  type    = string
  default = "TRADE_ETL_ROLE"
}

variable "raw_stage_name" {
  type    = string
  default = "RAW_TRADES_STAGE"
}
