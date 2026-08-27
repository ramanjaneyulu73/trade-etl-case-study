# Trade ETL Pipeline — Data Engineering Case Study

A batch ETL pipeline that simulates trade messages, loads them into Snowflake, applies
versioning/expiry/maturity business rules in dbt, stores valid and rejected trades
separately, and orchestrates the whole thing with Airflow.

```
ingestion/          trade message generator + Snowflake loader (Python)
dbt_trades/         dbt project: staging -> classification -> valid/rejected marts
terraform/          Snowflake infra as code (warehouse, database, schema, stage, role)
orchestration/      Airflow DAG + Docker Compose
dashboard/          Streamlit trade-status dashboard
docs/               architecture, setup guide, validation logic writeup, PlantUML diagram
.github/workflows/  CI for dbt, Terraform, and the Python scripts
```

- **Setup & run**: [docs/setup_guide.md](docs/setup_guide.md)
- **Architecture, failure handling, Snowflake monitoring/alerts, 10,000x scaling**: [docs/architecture.md](docs/architecture.md)
- **Business rules & tech stack rationale**: [docs/validation_logic.md](docs/validation_logic.md)
- **Diagram source**: [docs/diagrams/architecture.puml](docs/diagrams/architecture.puml)

## Business rules implemented (dbt)

1. Reject trades with a lower version than existing
2. Replace trades with the same version
3. Reject trades with a maturity date earlier than today
4. Mark trades as expired once the maturity date has passed
5. Optional extra rules: non-positive notional, unsupported currency, maturity before trade date
6. All rejections logged to an append-only `fct_rejected_trades` audit table

## Tech stack

Snowflake (ingestion + storage) · dbt Core (`dbt-snowflake`) · Apache Airflow (Docker) ·
Terraform (`Snowflake-Labs/snowflake` provider) · Streamlit · GitHub Actions
