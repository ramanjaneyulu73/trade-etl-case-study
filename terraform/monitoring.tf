# Demonstrates a live Snowflake-native alert (not just documented) - fires
# when fct_rejected_trades grows unusually fast relative to normal volume,
# which usually means an upstream schema change or a bad batch, not N
# independent bad trades. Complementary to Airflow's email_on_failure: this
# catches "every job succeeded but the data looks wrong", which job-level
# alerting alone can't see. See docs/architecture.md's monitoring section for
# the fuller design (this implements one of the alert conditions described
# there; QUERY_HISTORY/WAREHOUSE_METERING_HISTORY-based alerts are the same
# pattern, just against ACCOUNT_USAGE views instead of our own MARTS tables).
#
# Ordering note: the alert's condition/action reference MARTS.FCT_REJECTED_TRADES,
# which dbt creates, not Terraform - this resource only applies cleanly once
# at least one `dbt run` has already created that table.

resource "snowflake_grant_privileges_to_account_role" "execute_alert" {
  provider          = snowflake.securityadmin
  account_role_name = snowflake_account_role.trade_etl_role.name
  privileges        = ["EXECUTE ALERT"]
  on_account        = true
}

resource "snowflake_email_notification_integration" "trade_etl_alerts" {
  provider           = snowflake.accountadmin
  name               = "TRADE_ETL_ALERT_EMAIL"
  enabled            = true
  allowed_recipients = [var.alert_email]
  comment            = "Notifies on trade ETL data-quality alerts (rejection-rate spikes)."
}

resource "snowflake_alert" "high_rejection_rate" {
  provider  = snowflake.trade_etl_role
  database  = snowflake_database.trade_etl_db.name
  schema    = snowflake_schema.raw.name
  name      = "HIGH_REJECTION_RATE"
  warehouse = snowflake_warehouse.trade_etl_wh.name
  enabled   = true
  comment   = "Fires when more than 10 trades are rejected in a 60-minute window - usually an upstream schema change, not N independent bad trades."

  condition = <<-SQL
    select count(*) from ${snowflake_database.trade_etl_db.name}.marts.fct_rejected_trades
    where rejected_at > dateadd('minute', -60, current_timestamp())
    having count(*) > 10
  SQL

  action = <<-SQL
    call system$send_email(
      '${snowflake_email_notification_integration.trade_etl_alerts.name}',
      '${var.alert_email}',
      'Trade ETL Alert: high rejection rate',
      'More than 10 trades were rejected in the last 60 minutes. Check fct_rejected_trades for a spike in a single rejection_reason, which usually means an upstream schema change rather than independently bad trades.'
    )
  SQL

  alert_schedule {
    interval = 60
  }

  depends_on = [snowflake_grant_privileges_to_account_role.execute_alert]
}
