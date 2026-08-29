# Proof

Screenshots and raw command output for everything claimed in the [README](../README.md#validated-so-far).

**Airflow — `trade_etl_pipeline` DAG**

| | |
|---|---|
| ![DAG list](proof/airflow_dag_list.png) | ![All tasks green](proof/airflow_run_success.png) |
| ![Graph view](proof/airflow_graph_view.png) | ![DAG source](proof/airflow_dag_code.png) |

![Retry recovering from a real failure](proof/airflow_retry_recovery.png)

That last one is worth calling out specifically: it's the Audit Log for a scheduled
`dbt_run` task going `failed` → `running` → `success`, about 5 minutes apart, matching
this DAG's configured retry (`retries: 2, retry_delay: 5 minutes`) exactly. This is a
real automatic recovery, not a staged screenshot — see the "CI/CD hardening" section of
[architecture.md](architecture.md) for the specific bug it was recovering from.

[`proof/docker_ps.txt`](proof/docker_ps.txt) is a plain `docker ps` capture
showing the actual containers behind these screenshots: the Postgres metadata DB, the
scheduler, and the webserver serving port 8080 — this is the same Docker Compose stack
(`orchestration/airflow/docker-compose.yaml`) described in the setup guide, not something
different in a screenshot.

![Docker Desktop showing the built images](proof/docker_desktop_images.png)

The containers themselves get torn down between runs to free up RAM on a
resource-constrained machine (see [setup_guide.md](setup_guide.md)'s Docker Desktop / WSL2 note),
but the images they're built from persist locally — this is Docker Desktop's own Images
tab, not just the CLI.

**Streamlit — live dashboard** ([open it yourself](https://trade-etl-case-study.streamlit.app/))

| | |
|---|---|
| ![Dashboard overview](proof/dashboard_overview.png) | ![Rejection reasons and notional by currency](proof/dashboard_rejections_currency.png) |

![Valid trades table](proof/dashboard_valid_trades.png)

![Deployment config on Streamlit Community Cloud](proof/streamlit_cloud_deployment.png)

That last one shows the actual deployment record: this app, on this account, built from
`trade-etl-case-study · main · dashboard/streamlit_app.py` — not a different app that
happens to look similar.

**Snowflake — Snowsight**

| | |
|---|---|
| ![Schema tree and a live query](proof/snowsight_schema_and_query.png) | ![Rejection breakdown matching the dashboard exactly](proof/snowsight_rejection_breakdown.png) |

The database tree shows `RAW`/`STAGING`/`MARTS` under `TRADE_ETL_DB` with real
table/view counts, and the rejection-reason counts in the second query
(215/4/42/4) match the dashboard and `dbt_test` output exactly — same
underlying data, three different views of it.

**Snowflake Alert — running unattended, not a one-off demo**

![Real alert email received in Gmail](proof/gmail_alert_received.png)

[`proof/snowflake_alert_history.txt`](proof/snowflake_alert_history.txt) is a
fresh `ALERT_HISTORY` query, not the same run described in the "CI/CD hardening" section
of [architecture.md](architecture.md). It shows `HIGH_REJECTION_RATE` firing on
its own 60-minute schedule continuously since it was created, entirely without anyone
watching: two real `TRIGGERED` events roughly 10 hours apart (both landed in the inbox
above), one `ACTION_FAILED` from the missing-grant bug before it was fixed, and
`CONDITION_FALSE` on every other tick, which is what a healthy run looks like when
rejection volume is normal. This isn't a screenshot of one lucky firing, it's the alert
doing its job for over a day straight, landing in a real inbox.

**Terraform Cloud and dbt**

| | |
|---|---|
| ![Workspace overview](proof/terraform_cloud_overview.png) | ![Outputs](proof/terraform_cloud_outputs.png) |

![Run history: 21 successes, 1 real error](proof/terraform_cloud_runs.png)

The run history shows "Errored 1" out of 22 runs, not a suspiciously perfect all-green
history — that one error is the case-mismatch incident documented in the "CI/CD
hardening" section of [architecture.md](architecture.md), left visible rather
than only showing the clean runs.

- [`proof/terraform_plan_zero_drift.txt`](proof/terraform_plan_zero_drift.txt): `terraform plan` against the live warehouse, "No changes"
- [`proof/dbt_test_13_of_13.txt`](proof/dbt_test_13_of_13.txt): `dbt test` run against live data, 13/13 passing
- GitHub Actions history is public and needs no separate proof file: [github.com/ramanjaneyulu73/trade-etl-case-study/actions](https://github.com/ramanjaneyulu73/trade-etl-case-study/actions)
