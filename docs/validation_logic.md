# Validation Logic & Tech Stack Choices

## Data model

Every raw trade message lands as a `VARIANT` row in `RAW.RAW_TRADES` and carries:
`trade_id`, `version`, `trade_date`, `maturity_date`, `counterparty`, `instrument_type`,
`notional`, `currency`, `price`, `status`, `source_system`, `event_timestamp`.

`stg_trades` (view) flattens the VARIANT into typed columns. Everything downstream reads
from `stg_trades`, never from the raw table directly, so schema drift in the source only
needs to be handled in one place.

## `int_trade_classification` — where the rules live

One view classifies every message that has ever been received into exactly one
`disposition`. It ranks messages per `trade_id` by `version desc, event_timestamp desc`
and applies the rules in this order:

| # | Rule | Disposition | How |
|---|------|--------------|-----|
| 1 | Reject trades with a lower version than existing | `REJECTED_LOWER_VERSION` | `version < max(version) over (partition by trade_id)` |
| 2 | Replace trades with the same version | *(not a rejection)* | among rows sharing the trade's max version, the most recently arrived one wins (`row_number() over (partition by trade_id, version order by event_timestamp desc)`); the ones it supersedes are tagged `SUPERSEDED_SAME_VERSION`, not `REJECTED_*`, since the spec treats replace and reject as distinct outcomes |
| 3 | Reject trades with a maturity date earlier than today | `REJECTED_PAST_MATURITY` | checked on the winning candidate row only |
| 5a | Non-positive notional (own rule, optional) | `REJECTED_INVALID_NOTIONAL` | data-quality guard — a booking system should never send a zero/negative notional |
| 5b | Unsupported currency (own rule, optional) | `REJECTED_INVALID_CURRENCY` | checked against `var('valid_currencies')` in `dbt_project.yml`, so the allow-list is a one-line config change, not a code change |
| 5c | Maturity before trade date (own rule, optional) | `REJECTED_INVALID_DATES` | catches an internally inconsistent message even if it isn't yet in the past relative to today |
| — | none of the above | `VALID_CURRENT` | becomes the current row for that `trade_id` |

Rules 1 and 2 fall out of the same ranking logic rather than being two separate
`CASE WHEN` branches bolted together, which is deliberate: "keep the highest version,
and on a tie keep the latest arrival" is a single ordering rule, and reject/replace are
just names for what happens to the rows that ranking doesn't keep.

## `fct_valid_trades` — current state, rule 4 (mark expired)

One row per `trade_id`: the row from `int_trade_classification` with `disposition =
'VALID_CURRENT'`. `trade_status` is derived as `EXPIRED` once `maturity_date <
current_date()`, `ACTIVE` otherwise — computed every build, so it can never drift out of
sync with the calendar.

The `mark_expired_trades()` macro (`dbt_trades/macros/mark_expired_trades.sql`) also
does this as a literal `UPDATE ... SET trade_status = 'EXPIRED'`, run automatically after
every `dbt run` via `on-run-end`, and callable directly with
`dbt run-operation mark_expired_trades`. It's redundant with the derived column *today*
because `fct_valid_trades` is fully rebuilt every run — but it's the piece of the design
that becomes load-bearing the moment the model moves to incremental materialization at
higher volume (see `architecture.md`), so it's included now rather than retrofitted later.

## `fct_rejected_trades` — rule 6 (audit log)

Append-only: every message with a `REJECTED_*` disposition is inserted once and never
updated, keyed on `(trade_id, version, source_file_name)`. Re-running `int_trade_classification`
(a view over full history) doesn't create duplicate audit rows because the incremental
`insert`-only strategy anti-joins against what's already in the table.

## Why this tech stack

- **Snowflake COPY INTO from an internal stage** for ingestion, rather than an
  external ETL tool, per the "Snowflake Native" preference and because it needs
  no extra infrastructure to demonstrate.
- **dbt Core** (not Snowpark/Python UDFs) for the business rules: the rules are set-based
  comparisons (max version per trade, date comparisons) that read naturally as SQL window
  functions, and dbt gives version control, tests, docs and `on-run-end` hooks for free.
- **A view + two tables, not five separate incremental models**: keeping the rule logic in
  one place (`int_trade_classification`) means rules 1–3 and 5 can't drift out of sync
  between the valid-trades path and the rejected-trades path.
- **Airflow over cron**: rule 6 and the case study's monitoring/alerting requirements need
  per-task retries, failure isolation, and email-on-failure, which cron doesn't give you.
