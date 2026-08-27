# Architecture

See the [README](../README.md#architecture) for the rendered component diagram (GitHub
renders it inline via Mermaid). The same diagram is also kept as PlantUML source at
[diagrams/architecture.puml](diagrams/architecture.puml) for tools that prefer it
(render with the PlantUML VS Code extension, or https://www.plantuml.com/plantuml).

## Data flow

1. `ingestion/generate_trades.py` simulates a batch of trade messages (new trades,
   amendments, same-version corrections, stale/out-of-order versions, already-matured
   trades) and writes them as a `.jsonl` file to `data/incoming/`.
2. `ingestion/load_to_snowflake.py` stages the file (`PUT`) to an internal Snowflake
   stage and loads it (`COPY INTO`) into `RAW.RAW_TRADES` as `VARIANT` rows, then moves
   the file to `data/processed/` so re-running never double-loads it.
3. `dbt run` builds `stg_trades` → `int_trade_classification` → `fct_valid_trades` /
   `fct_rejected_trades` (see `docs/validation_logic.md` for the rule-by-rule logic).
4. `dbt test` runs schema tests (not-null, uniqueness, accepted-values) plus a singular
   test asserting no valid trade has `maturity_date < trade_date`.
5. Apache Airflow (`orchestration/airflow/`) runs steps 1–4 daily as a DAG, with retries
   and email-on-failure.
6. `dashboard/streamlit_app.py` queries `fct_valid_trades` / `fct_rejected_trades`
   directly for a live status view.
7. Terraform (`terraform/`) provisions the warehouse, database, `RAW` schema, stage,
   landing table, and a `TRADE_ETL_ROLE` with the grants the pipeline needs; dbt owns
   the `STAGING`/`MARTS` schemas and everything inside them.

## Handling file arrival delays, data quality problems, and task failures

- **File arrival delays**: `load_to_snowflake.py` only loads what's currently in
  `data/incoming/` and is idempotent (processed files are moved out, so a re-run is a
  no-op). If a file is late, the next Airflow DAG run just picks it up — there's no
  fixed set of "expected" files to wait on. For a stricter SLA, an Airflow
  `FileSensor`/`ExternalTaskSensor` with a timeout and its own failure alert would sit in
  front of `load_to_snowflake`, rather than the DAG silently proceeding with partial data.
- **Data quality problems**: handled structurally, not as an afterthought — every message
  that fails a rule lands in `fct_rejected_trades` with a specific `rejection_reason`
  rather than being dropped or silently excluded, and `dbt test` fails the run (and the
  Airflow task) if a structural invariant is violated (e.g. a duplicate `trade_id` in
  `fct_valid_trades`, a null `trade_id`). That distinction matters: a bad *row* should
  never stop the *batch* (it gets rejected and logged), but a broken *invariant* should
  stop the pipeline before bad data reaches `MARTS`.
- **Task failures**: every Airflow task retries (2 retries, 5 minute delay) before
  failing the DAG, `email_on_failure=True` sends an alert on final failure, and each
  stage (generate / load / dbt run / dbt test / mark expired) is a separate task so the
  UI shows exactly which one broke instead of one opaque "pipeline failed" state. dbt
  itself fails fast on a broken model (compilation error, failed test with
  `--fail-fast`) rather than silently producing partial output.

## Monitoring pipeline health with Snowflake's administrative views

Snowflake's `ACCOUNT_USAGE` and `INFORMATION_SCHEMA` views (via `snowflake.account_usage`)
give visibility the pipeline itself doesn't need to instrument:

- `QUERY_HISTORY` — filter on `WAREHOUSE_NAME = 'TRADE_ETL_WH'` to catch slow or failed
  `dbt run`/`COPY INTO` statements; `EXECUTION_STATUS = 'FAIL'` surfaces broken queries
  before Airflow's retry even kicks in.
- `COPY_HISTORY` (table function, `information_schema.copy_history`) — shows exactly
  which staged files loaded, how many rows, and any `COPY INTO` errors, independent of
  what the Python loader logged locally.
- `WAREHOUSE_METERING_HISTORY` — credit consumption per hour for `TRADE_ETL_WH`; a spike
  here with no corresponding increase in trade volume usually means a regressed model
  (e.g. an accidental full table scan) rather than a bug in the business logic.
- `TASK_HISTORY` — relevant if `mark_expired_trades` (or the whole classification step)
  is later moved into a Snowflake Task instead of being triggered by Airflow.

**Alerting**: Snowflake Alerts (`CREATE ALERT ... CONDITION ... ON SCHEDULE ...`) can
watch these views directly — e.g. an alert that fires if
`QUERY_HISTORY` shows `TRADE_ETL_WH` failures in the last hour, or if
`fct_rejected_trades` grows by more than N% of `fct_valid_trades` in a run (a spike in
rejections usually means an upstream schema change, not N independent bad trades) —
and notify via a Snowflake Notification Integration (email or a webhook into
Slack/PagerDuty). This is complementary to, not a replacement for, Airflow's
`email_on_failure`: Airflow tells you the *job* failed; Snowflake alerts tell you the
*data* looks wrong even when every job succeeded.

## Scalability: what changes at 10,000x volume

The current design intentionally does a full recompute of `int_trade_classification`
and a full-refresh rebuild of `fct_valid_trades` every run — correct and simple at
demo/case-study volume, but it re-scans the entire trade history every run, which
doesn't scale linearly forever. At 10,000x:

- **Ingestion**: swap the manual `PUT`/`COPY INTO` script for **Snowpipe** (auto-ingest
  on file arrival in cloud storage) or **Snowpipe Streaming** if trades need to land in
  near-real-time rather than in daily batches — no code change to the schema, just to
  how files reach the stage.
- **Classification becomes incremental**: `int_trade_classification` would filter to only
  rows landed since the last run (`loaded_at > watermark`), and the "existing version"
  lookup would compare against `fct_valid_trades` itself (a self-referential incremental
  merge) instead of recomputing from full history. This is exactly where
  `mark_expired_trades()` stops being redundant with the derived column and becomes the
  only way expiry gets applied to rows that aren't touched by the current run's merge.
- **Snowflake Streams & Tasks** in place of Airflow-triggered dbt runs for the
  Snowflake-native part of the pipeline: a Stream on `RAW_TRADES` feeds a Task that
  applies the classification incrementally, so the warehouse only processes genuinely
  new rows, and Airflow becomes purely the orchestrator for ingestion + monitoring
  rather than triggering full dbt builds constantly.
- **Warehouse sizing & concurrency**: move from a single `XSMALL` warehouse to
  size-appropriate warehouses per workload (a small warehouse for ingestion/COPY, a
  larger one for dbt transforms) with multi-cluster warehouses for the transform
  warehouse so concurrent runs don't queue behind each other, and auto-suspend tuned so
  10,000x the query volume doesn't mean 10,000x the idle credit burn.
- **Partitioning/clustering**: cluster `RAW_TRADES` and `fct_valid_trades` on `trade_id`
  (or a date-based key if trades are naturally time-partitioned) so the version-lookback
  window scan stays cheap as the table grows.
- **Rejected-trades audit log**: already append-only and incremental, so it scales as-is;
  at very high volume it's a natural candidate for a retention/archival policy (e.g. move
  rows older than N years to a cheaper storage tier) since compliance requires retention,
  not that every row stay in the hot table forever.
