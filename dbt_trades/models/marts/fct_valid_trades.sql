{{ config(materialized='table') }}

/*
  Current state, one row per trade_id: the latest accepted version.
  Full-refresh table (see docs/architecture.md for the incremental/Streams &
  Tasks design this would move to at much higher volume). trade_status is
  derived at query/build time so expiry (rule 4) is always correct even
  without the mark_expired_trades() maintenance macro; the macro exists to
  demonstrate the mutate-in-place pattern this becomes once the model is
  incremental.
*/

select
    trade_id,
    version,
    trade_date,
    maturity_date,
    counterparty,
    instrument_type,
    notional,
    currency,
    price,
    status as booking_status,
    source_system,
    event_timestamp,
    source_file_name,
    loaded_at,
    case
        when maturity_date < current_date() then 'EXPIRED'
        else 'ACTIVE'
    end as trade_status,
    current_timestamp() as processed_at
from {{ ref('int_trade_classification') }}
where disposition = 'VALID_CURRENT'
