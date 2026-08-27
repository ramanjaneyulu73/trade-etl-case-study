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
  database    = snowflake_database.trade_etl_db.name
  schema      = snowflake_schema.raw.name
  name        = var.raw_stage_name
  file_format = "TYPE = JSON STRIP_OUTER_ARRAY = FALSE"
}

resource "snowflake_account_role" "trade_etl_role" {
  name = var.role_name
}

resource "snowflake_grant_account_role" "trade_etl_role_to_user" {
  role_name = snowflake_account_role.trade_etl_role.name
  user_name = var.service_user_name
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
