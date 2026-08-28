resource "snowflake_warehouse" "trade_etl_wh" {
  name                = var.warehouse_name
  warehouse_size      = var.warehouse_size
  auto_suspend        = 60
  auto_resume         = true
  initially_suspended = true
}

resource "snowflake_database" "trade_etl_db" {
  name = var.database_name
}

resource "snowflake_schema" "raw" {
  database = snowflake_database.trade_etl_db.name
  name     = "RAW"
}

resource "snowflake_table" "raw_trades" {
  database = snowflake_database.trade_etl_db.name
  schema   = snowflake_schema.raw.name
  name     = "RAW_TRADES"

  column {
    name = "RAW_PAYLOAD"
    type = "VARIANT"
  }
  column {
    name = "SOURCE_FILE_NAME"
    type = "STRING"
  }
  column {
    name = "LOADED_AT"
    type = "TIMESTAMP_NTZ"
    default {
      expression = "CURRENT_TIMESTAMP()"
    }
  }
}

resource "snowflake_stage" "raw_trades_stage" {
  database = snowflake_database.trade_etl_db.name
  schema   = snowflake_schema.raw.name
  name     = var.raw_stage_name
  # Snowflake's JSON file format always reports NULL_IF = [] on read-back
  # (it's the type-specific default, not something we're setting); matching
  # it here avoids Terraform showing permanent no-op drift on every plan.
  file_format = "TYPE = JSON NULL_IF = []"
}

resource "snowflake_account_role" "trade_etl_role" {
  provider = snowflake.securityadmin
  name     = var.role_name
}

resource "snowflake_grant_account_role" "trade_etl_role_to_user" {
  provider  = snowflake.securityadmin
  role_name = snowflake_account_role.trade_etl_role.name
  # Snowflake stores unquoted identifiers uppercase; normalizing here means
  # this resource's plan is stable no matter how service_user_name happens to
  # be cased in whatever credential source feeds it (tfvars locally vs. a
  # GitHub secret in CI) - a lowercase secret once caused Terraform to see a
  # diff against the (correctly uppercase) existing grant and try to replace
  # it, briefly revoking the role from the live service user.
  user_name = upper(var.service_user_name)
}

resource "snowflake_grant_privileges_to_account_role" "wh_usage" {
  account_role_name = snowflake_account_role.trade_etl_role.name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.trade_etl_wh.name
  }
}

# dbt (running as the service user/role) needs USAGE on the database plus the
# right to create its own STAGING/MARTS schemas and objects within it.
resource "snowflake_grant_privileges_to_account_role" "db_usage_and_create_schema" {
  account_role_name = snowflake_account_role.trade_etl_role.name
  privileges        = ["USAGE", "CREATE SCHEMA"]
  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.trade_etl_db.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "raw_schema_all" {
  account_role_name = snowflake_account_role.trade_etl_role.name
  all_privileges    = true
  on_schema {
    schema_name = "\"${snowflake_database.trade_etl_db.name}\".\"${snowflake_schema.raw.name}\""
  }
}
