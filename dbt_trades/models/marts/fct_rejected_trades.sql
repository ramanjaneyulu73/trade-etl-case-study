{{ config(
    materialized='incremental',
    incremental_strategy='append'
) }}

/*
  Append-only compliance audit log (rule 6). Every distinct rejected message
  is recorded exactly once, keeping its original rejected_at even if the
  classification view is recomputed on later runs.

  No unique_key here deliberately - the 'append' strategy ignores it (dbt
  only honors unique_key for 'merge'/'delete+insert'), so dedup is done by
  hand below via the NOT EXISTS anti-join instead.
*/

select
    s.trade_id,
    s.version,
    s.trade_date,
    s.maturity_date,
    s.counterparty,
    s.instrument_type,
    s.notional,
    s.currency,
    s.price,
    s.status as booking_status,
    s.source_system,
    s.event_timestamp,
    s.source_file_name,
    s.loaded_at,
    s.disposition as rejection_reason,
    current_timestamp() as rejected_at
from {{ ref('int_trade_classification') }} s
where s.disposition like 'REJECTED_%'

{% if is_incremental() %}
and not exists (
    select 1
    from {{ this }} t
    where t.trade_id = s.trade_id
      and t.version = s.version
      and t.source_file_name = s.source_file_name
)
{% endif %}
