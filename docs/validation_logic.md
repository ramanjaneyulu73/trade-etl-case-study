# Validation Logic & Tech Stack Choices

## Data model

Every raw trade message lands as a `VARIANT` row in `RAW.RAW_TRADES` and carries:
`trade_id`, `version`, `trade_date`, `maturity_date`, `counterparty`, `instrument_type`,
`notional`, `currency`, `price`, `status`, `source_system`, `event_timestamp`.

`stg_trades` (view) flattens the VARIANT into typed columns. Everything downstream reads
from `stg_trades`, never from the raw table directly, so schema drift in the source only
needs to be handled in one place.

## `int_trade_classification`: where the rules live

One view classifies every message that has ever been received into exactly one
`disposition`. It ranks messages per `trade_id` by `version desc, event_timestamp desc`
and applies the rules in this order:

| # | Rule | Disposition | How |
|---|------|--------------|-----|
| 1 | Reject trades with a lower version than existing | `REJECTED_LOWER_VERSION` | `version < max(version) over (partition by trade_id)` |
| 2 | Replace trades with the same version | *(not a rejection)* | among rows sharing the trade's max version, the most recently arrived one wins (`row_number() over (partition by trade_id, version order by event_timestamp desc)`). The ones it supersedes get tagged `SUPERSEDED_SAME_VERSION`, not `REJECTED_*`, since the spec treats replace and reject as different outcomes. |
| 3 | Reject trades with a maturity date earlier than today | `REJECTED_PAST_MATURITY` | `maturity_date < loaded_at::date`. "Today" means the day the message arrived, not the day the pipeline happens to be re-run later (more on this below). |
| 5a | Non-positive notional (own rule, optional) | `REJECTED_INVALID_NOTIONAL` | data-quality guard: a booking system should never send a zero or negative notional |
| 5b | Unsupported currency (own rule, optional) | `REJECTED_INVALID_CURRENCY` | checked against `var('valid_currencies')` in `dbt_project.yml`, so the allow-list is a one-line config change rather than a code change |
| 5c | Maturity before trade date (own rule, optional) | `REJECTED_INVALID_DATES` | catches a message that's internally inconsistent even if it isn't yet in the past relative to today |
| — | none of the above | `VALID_CURRENT` | becomes the current row for that `trade_id` |

Rules 1 and 2 fall out of the same ranking logic instead of being two separate `CASE
WHEN` branches bolted together. That's deliberate: "keep the highest version, and on a
tie keep the latest arrival" is a single ordering rule. Reject and replace are just
names for what happens to the rows the ranking doesn't keep.

**Why rule 3 anchors on `loaded_at::date`, not `current_date()`.** `int_trade_classification`
gets fully recomputed from complete history on every run. Anchoring rule 3 on
`current_date()` instead would re-evaluate every past trade against today's date each
time it runs, so a trade accepted weeks ago would flip from `VALID_CURRENT` to
`REJECTED_PAST_MATURITY` the moment its maturity passed, and disappear from
`fct_valid_trades` entirely rather than staying there with `trade_status = 'EXPIRED'`,
which is what rule 4 is supposed to handle. Anchoring on the date the message first
arrived makes rule 3 a one-time, permanent judgment made at ingestion, cleanly
separated from rule 4's ongoing, today-relative expiry check. This distinction wasn't
obvious from reading the rules in isolation; it only became clear once this was tested
against a live warehouse (see the verification section below).

## `fct_valid_trades`: current state, rule 4 (mark expired)

One row per `trade_id`: the row from `int_trade_classification` with `disposition =
'VALID_CURRENT'`. `trade_status` is derived as `EXPIRED` once `maturity_date <
current_date()`, `ACTIVE` otherwise, computed on every build so it never drifts out of
sync with the calendar.

The `mark_expired_trades()` macro (`dbt_trades/macros/mark_expired_trades.sql`) also
does this as a literal `UPDATE ... SET trade_status = 'EXPIRED'`, run as an explicit
step after `dbt run`. Both the setup guide and the Airflow DAG run `dbt run-operation
mark_expired_trades` right after `dbt run`/`dbt test`. It isn't wired to dbt's
`on-run-end` hook because the macro's `ref('fct_valid_trades')` sits inside an
`execute`-guarded block (needed so `dbt run-operation` and normal parsing both work),
and dbt's dependency inference for `on-run-end` can't resolve a `ref()` in that
position. That turned up by actually running it, not by reading dbt's docs. The macro
is redundant with the derived column today, since `fct_valid_trades` is fully rebuilt
every run, but it's the part of the design that becomes load-bearing once the model
moves to incremental materialization at higher volume (see `architecture.md`), so it's
in place now instead of retrofitted later.

## `fct_rejected_trades`: rule 6 (audit log)

Append-only. Every message with a `REJECTED_*` disposition gets inserted once and never
updated, keyed on `(trade_id, version, source_file_name)`. Re-running
`int_trade_classification` (a view over full history) doesn't create duplicate audit
rows, because the incremental insert-only strategy anti-joins against what's already in
the table.

## Verified against a live warehouse

Every rule above was actually exercised against a real Snowflake trial account:

- Ran 200 simulated trades through `dbt run` and `dbt test` (13/13 tests passing): 148
  landed in `fct_valid_trades`, 32 in `REJECTED_LOWER_VERSION`, 6 in
  `REJECTED_INVALID_DATES`, and 9 correctly `SUPERSEDED_SAME_VERSION` (not counted as
  rejections, per rule 2).
- `REJECTED_PAST_MATURITY` (rule 3) didn't fire on that batch. The synthetic
  "already-matured" trades from `generate_trades.py` always also have `maturity_date <
  trade_date`, so `REJECTED_INVALID_DATES` catches them first. To isolate rule 3
  specifically, one hand-crafted trade was loaded with a trade date 10 days back and a
  maturity date 3 days back (after the trade date, but before today), and it landed in
  `REJECTED_PAST_MATURITY` as expected.
- That same test is what surfaced the `current_date()` vs `loaded_at::date` bug above.
  The original `current_date()` version passed a same-day test but would have quietly
  misbehaved for any trade whose maturity passed after it was accepted.
- `REJECTED_INVALID_NOTIONAL` and `REJECTED_INVALID_CURRENCY` had never fired either,
  and not because they were hard to trigger: `generate_trades.py` always produced a
  positive notional and always drew currency from the valid list, so neither rule could
  ever be exercised by any data the generator produced. This turned up while looking at
  why the dashboard's rejection-reasons chart only ever showed two bars. Fixed the
  generator to produce a small share of non-positive-notional and unsupported-currency
  trades, and confirmed live that both reasons now show up in `fct_rejected_trades`,
  with `dbt test` still at 13/13.

## Why this tech stack

**Snowflake COPY INTO from an internal stage** for ingestion, rather than pulling in an
external ETL tool, per the "Snowflake Native" preference, and because it needs no extra
infrastructure to demonstrate.

**dbt Core**, not Snowpark or Python UDFs, for the business rules. The rules are
set-based comparisons (max version per trade, date comparisons) that read naturally as
SQL window functions, and dbt gives version control, tests, docs, and hooks for free.

**A view plus two tables, not five separate incremental models.** Keeping the rule
logic in one place (`int_trade_classification`) means rules 1 through 3 and rule 5
can't drift out of sync between the valid-trades path and the rejected-trades path.

**Airflow over cron.** Rule 6 and the case study's monitoring and alerting
requirements need per-task retries, failure isolation, and email-on-failure, none of
which cron gives you.
