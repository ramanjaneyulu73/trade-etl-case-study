{{ config(materialized='view') }}

/*
  Applies the business rules from the case study to every raw trade message
  ever received (cheap full recompute at this data volume; see
  docs/architecture.md for how this becomes an incremental Streams/Tasks
  design at 10,000x scale):

    1. Reject trades with a lower version than the existing (max) version for that trade_id.
    2. Replace trades with the same version (the most recently arrived message wins).
    3. Reject trades with a maturity date earlier than today, as of when the message
       arrived (loaded_at::date) - a one-time, permanent judgment on that message, NOT
       re-evaluated against today's date on every future run.
    5. Optional data-quality rules: non-positive notional, unknown currency,
       maturity before trade date.

  Rule 4 (mark expired) is intentionally NOT applied here - it is a lifecycle
  state on already-valid trades, computed in fct_valid_trades and enforced by
  the mark_expired_trades() macro, not a rejection reason.

  Why rule 3 anchors on loaded_at, not current_date(): this view is fully
  recomputed from complete history on every run (see module docstring above).
  If rule 3 compared against current_date() instead, a trade accepted weeks
  ago would retroactively flip to REJECTED_PAST_MATURITY the moment its
  maturity passed - deleting it from fct_valid_trades instead of letting rule
  4 mark it EXPIRED there, which is what the business rules actually call
  for. Anchoring on the date the message was first received makes rule 3 a
  stable, one-time ingestion check, leaving today-relative expiry entirely to
  rule 4.
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
            when r.maturity_date < r.loaded_at::date
                then 'REJECTED_PAST_MATURITY'
            else 'VALID_CURRENT'
        end as disposition
    from ranked r

)

select * from classified
