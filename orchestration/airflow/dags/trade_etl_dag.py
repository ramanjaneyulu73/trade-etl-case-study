"""Daily batch trade ETL: generate -> load to Snowflake -> dbt run -> dbt test -> mark expired.

Each stage is its own task so a failure (e.g. a dbt test failure) shows up
against the specific stage in the Airflow UI, retries independently, and
still triggers the on-failure email alert.
"""
from datetime import datetime, timedelta, timezone

from airflow import DAG
from airflow.operators.bash import BashOperator

DBT_DIR = "/opt/airflow/dbt_trades"
INGESTION_DIR = "/opt/airflow/ingestion"

default_args = {
    "owner": "data-eng",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": True,
    "email_on_retry": False,
    "email": "{{ var.value.get('alert_email', '') }}",
}

with DAG(
    dag_id="trade_etl_pipeline",
    description="Ingest, validate and store daily trade data in Snowflake via dbt",
    default_args=default_args,
    schedule_interval="@daily",
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    tags=["trades", "snowflake", "dbt"],
) as dag:

    generate_trades = BashOperator(
        task_id="generate_trades",
        bash_command=f"cd {INGESTION_DIR} && python generate_trades.py --count 200",
    )

    load_to_snowflake = BashOperator(
        task_id="load_to_snowflake",
        bash_command=f"cd {INGESTION_DIR} && python load_to_snowflake.py",
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=f"cd {DBT_DIR} && dbt run --profiles-dir {DBT_DIR} --target dev",
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=f"cd {DBT_DIR} && dbt test --profiles-dir {DBT_DIR} --target dev",
    )

    mark_expired_trades = BashOperator(
        task_id="mark_expired_trades",
        bash_command=(
            f"cd {DBT_DIR} && dbt run-operation mark_expired_trades "
            f"--profiles-dir {DBT_DIR} --target dev"
        ),
    )

    generate_trades >> load_to_snowflake >> dbt_run >> dbt_test >> mark_expired_trades
