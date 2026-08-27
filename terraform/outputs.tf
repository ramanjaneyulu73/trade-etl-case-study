output "database_name" {
  value = snowflake_database.trade_etl_db.name
}

output "warehouse_name" {
  value = snowflake_warehouse.trade_etl_wh.name
}

output "role_name" {
  value = snowflake_account_role.trade_etl_role.name
}

output "raw_stage_fully_qualified" {
  value = "${snowflake_database.trade_etl_db.name}.${snowflake_schema.raw.name}.${snowflake_stage.raw_trades_stage.name}"
}
