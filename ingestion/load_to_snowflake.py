"""Pushes locally generated trade files into Snowflake via an internal stage.

Uses Snowflake-native ingestion (PUT + COPY INTO) rather than a general
purpose loader, per the "Snowflake Native" ingestion requirement. Files that
load successfully are moved to data/processed/ so re-running the script never
double-loads a batch. Files Snowflake rejects outright (bad JSON, wrong
shape) go to data/quarantine/ instead of retrying forever in place.
"""
import argparse
import logging
import os
import re
import shutil
from pathlib import Path

import snowflake.connector
from dotenv import load_dotenv
from snowflake.connector.errors import ProgrammingError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("load_to_snowflake")

ROOT = Path(__file__).resolve().parent.parent
INCOMING_DIR = ROOT / "data" / "incoming"
PROCESSED_DIR = ROOT / "data" / "processed"
QUARANTINE_DIR = ROOT / "data" / "quarantine"

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

RAW_TABLE_DDL = """
create table if not exists {database}.{schema}.raw_trades (
    raw_payload variant,
    source_file_name string,
    loaded_at timestamp_ntz default current_timestamp()
)
"""

STAGE_DDL = """
create stage if not exists {database}.{schema}.{stage}
    file_format = (type = json, strip_outer_array = false)
"""


def validate_identifier(name: str, label: str) -> str:
    """database/schema/stage names get interpolated directly into DDL/PUT/COPY
    SQL below rather than bound as params (identifiers generally can't be
    parameterized) - this is the check standing in for that."""
    if not IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid {label} {name!r}: must match {IDENTIFIER_RE.pattern}")
    return name


def get_connection():
    load_dotenv(ROOT / ".env")
    required = [
        "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
        "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA",
    ]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {missing}. Copy .env.example to .env and fill it in.")

    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=os.environ["SNOWFLAKE_SCHEMA"],
    )


def ensure_objects(cur, database, schema, stage):
    cur.execute(STAGE_DDL.format(database=database, schema=schema, stage=stage))
    cur.execute(RAW_TABLE_DDL.format(database=database, schema=schema))


def load_file(cur, database, schema, stage, file_path: Path):
    put_sql = f"PUT file://{file_path.as_posix()} @{database}.{schema}.{stage} AUTO_COMPRESS=TRUE OVERWRITE=TRUE"
    cur.execute(put_sql)

    staged_name = f"{file_path.name}.gz"
    copy_sql = f"""
        copy into {database}.{schema}.raw_trades (raw_payload, source_file_name)
        from (
            select $1, metadata$filename
            from @{database}.{schema}.{stage}/{staged_name}
        )
        file_format = (type = json)
        on_error = 'abort_statement'
    """
    cur.execute(copy_sql)
    result = cur.fetchall()
    logger.info("Loaded %s -> %s rows_parsed/rows_loaded rows: %s", file_path.name, len(result), result)


def main():
    parser = argparse.ArgumentParser(description="Load simulated trade files into Snowflake raw_trades")
    parser.add_argument("--file", type=str, default=None, help="load a single specific file instead of the whole incoming/ dir")
    args = parser.parse_args()

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

    if args.file:
        files = [Path(args.file)]
    else:
        files = sorted(INCOMING_DIR.glob("*.jsonl"))

    if not files:
        logger.info("No files to load in %s", INCOMING_DIR)
        return

    conn = get_connection()
    database = validate_identifier(os.environ["SNOWFLAKE_DATABASE"], "database")
    schema = validate_identifier(os.environ["SNOWFLAKE_SCHEMA"], "schema")
    stage = validate_identifier(os.environ.get("SNOWFLAKE_STAGE", "RAW_TRADES_STAGE"), "stage")

    quarantined = []
    try:
        cur = conn.cursor()
        ensure_objects(cur, database, schema, stage)
        for file_path in files:
            try:
                load_file(cur, database, schema, stage, file_path)
                shutil.move(str(file_path), str(PROCESSED_DIR / file_path.name))
            except ProgrammingError:
                # Snowflake rejected the file's content outright (bad JSON,
                # wrong shape) - retrying won't fix that, so move it aside
                # instead of letting it block every future run's good files
                # or fail the DAG on the same file forever.
                logger.exception("Rejected by Snowflake, quarantining %s", file_path.name)
                shutil.move(str(file_path), str(QUARANTINE_DIR / file_path.name))
                quarantined.append(file_path.name)
            except Exception:
                # Anything else (connection drop, warehouse still resuming)
                # is plausibly transient - leave the file in incoming/ and
                # stop the batch so Airflow's task retry can pick it back up.
                logger.exception("Failed to load %s, leaving in incoming/ for retry", file_path.name)
                raise
    finally:
        conn.close()

    if quarantined:
        raise RuntimeError(
            f"{len(quarantined)} file(s) rejected by Snowflake, moved to {QUARANTINE_DIR}: {quarantined}"
        )


if __name__ == "__main__":
    main()
