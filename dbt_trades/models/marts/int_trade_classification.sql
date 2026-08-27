{{ config(materialized='view') }}

/*
  Applies the business rules from the case study to every raw trade message
  ever received (cheap full recompute at this data volume; see
  docs/architecture.md for how this becomes an incremental Streams/Tasks
  design at 10,000x scale):

    1. Reject trades with a lower version than the existing (max) version for that trade_id.
    2. Replace trades with the same version (the most recently arrived message wins).
    3. Reject trades with a maturity date earlier than today.
    5. Optional data-quality rules: non-positive notional, unknown currency,
       maturity before trade date.

  Rule 4 (mark expired) is intentionally NOT applied here - it is a lifecycle
  state on already-valid trades, computed in fct_valid_trades and enforced by
  the mark_expired_trades() macro, not a rejection reason.
*/

with all_trades as (

    select * from {{ ref('stg_trades') }}

),

ranked as (

    select
        *,
        max(version) over (partition by trade_id) as max_version_for_trade,
        -- among messages that share the trade's max version, the most recently
        -- arrived one is the current state (rule 2: same-version replace);
        -- the rest are superseded, not rejected
        row_number() over (
            partition by trade_id, version
            order by event_timestamp desc, loaded_at desc
        ) as rn_within_version
    from all_trades

),

classified as (

    select
        r.trade_id,
        r.version,
        r.trade_date,
        r.maturity_date,
        r.counterparty,
        r.instrument_type,
        r.notional,
        r.currency,
        r.price,
        r.status,
        r.source_system,
        r.event_timestamp,
        r.source_file_name,
        r.loaded_at,
        case
            when r.version < r.max_version_for_trade
                then 'REJECTED_LOWER_VERSION'
            when r.rn_within_version > 1
                then 'SUPERSEDED_SAME_VERSION'
            when r.notional <= 0
                then 'REJECTED_INVALID_NOTIONAL'
            when r.currency not in ({{ "'" ~ var('valid_currencies') | join("','") ~ "'" }})
                then 'REJECTED_INVALID_CURRENCY'
            when r.maturity_date < r.trade_date
                then 'REJECTED_INVALID_DATES'
            when r.maturity_date < current_date()
                then 'REJECTED_PAST_MATURITY'
            else 'VALID_CURRENT'
        end as disposition
    from ranked r

)

select * from classified
