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
| 3 | Reject trades with a maturity date earlier than today | `REJECTED_PAST_MATURITY` | `maturity_date < loaded_at::date` — "today" meaning the day the message arrived, not the day the pipeline happens to be re-run (see note below) |
| 5a | Non-positive notional (own rule, optional) | `REJECTED_INVALID_NOTIONAL` | data-quality guard — a booking system should never send a zero/negative notional |
| 5b | Unsupported currency (own rule, optional) | `REJECTED_INVALID_CURRENCY` | checked against `var('valid_currencies')` in `dbt_project.yml`, so the allow-list is a one-line config change, not a code change |
| 5c | Maturity before trade date (own rule, optional) | `REJECTED_INVALID_DATES` | catches an internally inconsistent message even if it isn't yet in the past relative to today |
| — | none of the above | `VALID_CURRENT` | becomes the current row for that `trade_id` |

Rules 1 and 2 fall out of the same ranking logic rather than being two separate
`CASE WHEN` branches bolted together, which is deliberate: "keep the highest version,
and on a tie keep the latest arrival" is a single ordering rule, and reject/replace are
just names for what happens to the rows that ranking doesn't keep.

**Why rule 3 anchors on `loaded_at::date` and not `current_date()`**: `int_trade_classification`
is fully recomputed from complete history on every run. Anchoring rule 3 on
`current_date()` instead would make it re-evaluate *every past trade* against today's
date on every run — so a trade accepted weeks ago, once its maturity date passed, would
retroactively flip from `VALID_CURRENT` to `REJECTED_PAST_MATURITY` and disappear from
`fct_valid_trades` entirely, rather than staying there with `trade_status = 'EXPIRED'`
the way rule 4 intends. Anchoring on the date the message was *first received* makes
rule 3 a one-time, permanent ingestion-time judgment ("was this dead on arrival?"),
cleanly separating it from rule 4's ongoing, today-relative expiry check. This was
caught by testing against a live warehouse, not by inspection — see the verification
note below.

## `fct_valid_trades` — current state, rule 4 (mark expired)

One row per `trade_id`: the row from `int_trade_classification` with `disposition =
'VALID_CURRENT'`. `trade_status` is derived as `EXPIRED` once `maturity_date <
current_date()`, `ACTIVE` otherwise — computed every build, so it can never drift out of
sync with the calendar.

The `mark_expired_trades()` macro (`dbt_trades/macros/mark_expired_trades.sql`) also
does this as a literal `UPDATE ... SET trade_status = 'EXPIRED'`, run as an explicit step
after `dbt run` — both the setup guide and the Airflow DAG run
`dbt run-operation mark_expired_trades` right after `dbt run`/`dbt test`. It isn't wired
to dbt's `on-run-end` hook: the macro's `ref('fct_valid_trades')` sits inside an
`execute`-guarded block (needed so `dbt run-operation` and normal parsing both work), and
dbt's dependency inference for `on-run-end` can't resolve a `ref()` in that position —
confirmed by actually running it, not just by reading dbt's docs. The macro is redundant
with the derived column *today* because `fct_valid_trades` is fully rebuilt every run —
but it's the piece of the design that becomes load-bearing the moment the model moves to
incremental materialization at higher volume (see `architecture.md`), so it's included
now rather than retrofitted later.

## `fct_rejected_trades` — rule 6 (audit log)

Append-only: every message with a `REJECTED_*` disposition is inserted once and never
updated, keyed on `(trade_id, version, source_file_name)`. Re-running `int_trade_classification`
(a view over full history) doesn't create duplicate audit rows because the incremental
`insert`-only strategy anti-joins against what's already in the table.

## Verified against a live warehouse

Every rule listed above was exercised against a real Snowflake trial account, not just
written and assumed correct:

- Ran 200 simulated trades through `dbt run` + `dbt test` (13/13 tests passing): 148
  landed in `fct_valid_trades`, 32 in `REJECTED_LOWER_VERSION`, 6 in
  `REJECTED_INVALID_DATES`, 9 correctly `SUPERSEDED_SAME_VERSION` (not counted as
  rejections, per rule 2).
- `REJECTED_PAST_MATURITY` (rule 3) didn't fire on that batch — the synthetic
  "already-matured" trades generated by `generate_trades.py` always also have
  `maturity_date < trade_date`, so they're caught by `REJECTED_INVALID_DATES` first.
  Loaded one hand-crafted trade (`trade_date` 10 days ago, `maturity_date` 3 days ago —
  after `trade_date` but before today) to isolate rule 3, and confirmed it landed in
  `REJECTED_PAST_MATURITY` specifically.
- That same live test is what surfaced the `current_date()` vs `loaded_at::date` bug
  described above — the original `current_date()` version worked for a same-day test but
  would have silently misbehaved for any trade whose maturity passed after acceptance.
- **`REJECTED_INVALID_NOTIONAL` and `REJECTED_INVALID_CURRENCY` had never fired either** —
  not because they were hard to trigger, but because `generate_trades.py` always produced
  a positive notional and always drew currency from the valid list, so neither rule could
  structurally ever be exercised by any data the generator produced. Found while reviewing
  why the dashboard's rejection-reasons chart only ever showed two bars. Fixed the
  generator to produce a small share of non-positive-notional and unsupported-currency
  trades; confirmed live that both reasons now appear in `fct_rejected_trades` and `dbt
  test` is still 13/13.

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
