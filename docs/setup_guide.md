# Setup & Execution Guide (Windows)

## 1. Create a free Snowflake trial account

Snowflake is cloud-only — there's no local emulator, so this step has to happen in a
browser and can't be scripted:

1. Go to https://signup.snowflake.com/
2. Fill in your details, pick any cloud provider/region (AWS is fine), and choose the
   **Standard** edition (plenty for this project).
3. Verify your email and set a password.
4. After first login, note your **account identifier** — shown in the URL, e.g.
   `https://xy12345.us-east-1.snowflakecomputing.com` → account identifier is
   `xy12345.us-east-1`. You'll need this for every config file below.
5. Your trial user is created with `ACCOUNTADMIN`. Terraform in this repo runs as
   `SYSADMIN` (better practice than provisioning with `ACCOUNTADMIN`) — your trial user
   already has `SYSADMIN` available; just make sure the role is active
   (`use role sysadmin;` in a worksheet, or Terraform sets it per-session).

## 2. Install tooling

| Tool | Status | Notes |
|---|---|---|
| Python 3.11 | ✅ already present | |
| Git | ✅ already present | |
| `gh` CLI | ✅ installed via `winget install GitHub.cli` | run `gh auth login` once |
| Terraform | ✅ installed via `winget install Hashicorp.Terraform` | |
| `dbt-core` + `dbt-snowflake` | ✅ installed via `pip install --user` | |
| Docker Desktop + WSL2 | ✅ installed (`wsl --install`, `winget install -e --id Docker.DockerDesktop`) | required for Airflow; on RAM-constrained machines close other apps first, see note below |

### Docker Desktop / WSL2

Requires WSL2 (`wsl --install`, needs an elevated terminal + a reboot) and Docker
Desktop (`winget install -e --id Docker.DockerDesktop`, also needs admin). Launch Docker
Desktop once, skip the optional Docker Hub sign-in, and confirm it's running with
`docker ps` in a normal (non-admin) terminal.

On a RAM-constrained machine, Docker Desktop's WSL2 VM plus the Airflow stack (Postgres +
webserver + scheduler) can use 2+ GB once running — close other memory-heavy apps (browsers,
IDEs) first if `docker compose up` or the containers themselves seem to hang.

You don't need Docker for anything except the Airflow orchestration piece — ingestion,
dbt, Terraform, and the Streamlit dashboard all run directly on Windows with no
container involved.

## 3. Provision Snowflake infrastructure with Terraform

State is stored remotely in Terraform Cloud (`terraform/providers.tf`'s `cloud` block), not
a local file — this is what lets both your machine and the `terraform-apply` CI job (see
step 8) see the same state instead of each trying to recreate resources the other already
made. One-time setup: sign up free at [app.terraform.io](https://app.terraform.io), create
an organization and a workspace (CLI-driven workflow, Execution Mode: Local), then generate
a User API token (User Settings → Tokens) and either run `terraform login` or write it to
`%APPDATA%\terraform.d\credentials.tfrc.json`:

```json
{
  "credentials": {
    "app.terraform.io": { "token": "YOUR_TOKEN" }
  }
}
```

```powershell
cd terraform
copy terraform.tfvars.example terraform.tfvars
notepad terraform.tfvars   # fill in your account id, trial username/password
terraform init
terraform plan
terraform apply
```

This creates the `TRADE_ETL_WH` warehouse, `TRADE_ETL_DB` database, `RAW` schema,
`RAW_TRADES` landing table, `RAW_TRADES_STAGE` internal stage, and a `TRADE_ETL_ROLE`
granted to your trial user.

## 4. Configure local credentials

```powershell
copy .env.example .env
notepad .env   # SNOWFLAKE_ACCOUNT / USER / PASSWORD / ROLE / WAREHOUSE / DATABASE

copy dbt_trades\profiles.yml.example dbt_trades\profiles.yml
```

`profiles.yml` reads from the same `SNOWFLAKE_*` environment variables — either load
`.env` into your shell (`python -c "from dotenv import load_dotenv; load_dotenv()"` or
use a tool like `direnv`) before running `dbt`, or just set them directly:

```powershell
$env:SNOWFLAKE_ACCOUNT="xy12345.us-east-1"
$env:SNOWFLAKE_USER="..."
$env:SNOWFLAKE_PASSWORD="..."
$env:SNOWFLAKE_ROLE="TRADE_ETL_ROLE"
$env:SNOWFLAKE_WAREHOUSE="TRADE_ETL_WH"
$env:SNOWFLAKE_DATABASE="TRADE_ETL_DB"
$env:SNOWFLAKE_SCHEMA="RAW"
```

## 5. Run the pipeline manually (no Docker needed)

```powershell
python ingestion\generate_trades.py --count 200
python ingestion\load_to_snowflake.py

cd dbt_trades
dbt run
dbt test
dbt run-operation mark_expired_trades
cd ..
```

Run `generate_trades.py` + `load_to_snowflake.py` + `dbt run`/`dbt test` a few times in
a row (with different `--seed` values, or none, for variety) to see amendments,
same-version replaces, and rejections accumulate.

## 6. Run it on a schedule with Airflow (Docker)

Once Docker Desktop is running:

```powershell
cd orchestration\airflow
copy ..\..\.env .env   # docker-compose reads SNOWFLAKE_* / SMTP_* from here
docker compose up airflow-init
docker compose up -d
```

Open http://localhost:8080 (`admin` / `admin`), unpause `trade_etl_pipeline`, and
trigger a run. Set the Airflow Variable `alert_email` (Admin → Variables) to your email
address, and fill in `SMTP_*` in `.env` (e.g. a Gmail app password) to receive
failure alerts.

## 7. Run the dashboard

```powershell
pip install -r dashboard\requirements.txt
streamlit run dashboard\streamlit_app.py
```

## 8. Push to GitHub + CI/CD

```powershell
gh auth login
gh repo create trade-etl-case-study --public --source=. --remote=origin
git add -A
git commit -m "Initial trade ETL pipeline"
git push -u origin main
```

Then in the repo's **Settings → Secrets and variables → Actions**, add:
`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_ROLE`,
`SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`. The `dbt_ci` and `terraform_ci` workflows
run schema-safe checks (`dbt parse`, `terraform validate`) unconditionally, and only run
the credentialed `dbt build --target ci` / `terraform plan` steps once those secrets are
present.
