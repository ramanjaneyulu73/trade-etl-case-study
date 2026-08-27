{% macro mark_expired_trades() %}
{#
  Demonstrates the literal "mark as expired" mutation (rule 4) as a
  standalone maintenance operation, the pattern this project would rely on
  once fct_valid_trades becomes a true incremental model that isn't
  rebuilt from scratch every run (see docs/architecture.md, 10,000x scale
  section). Safe to run repeatedly: only flips rows that need flipping.
  Run explicitly after `dbt run`: dbt run-operation mark_expired_trades
  (both the setup guide and the Airflow DAG do this as a separate step;
  it's not wired to on-run-end because its ref() sits inside an
  `execute`-guarded block, which dbt's on-run-end dependency inference
  can't resolve).
#}
  {% set relation = ref('fct_valid_trades') %}
  {% if execute %}
    {% set sql %}
      update {{ relation }}
      set trade_status = 'EXPIRED'
      where maturity_date < current_date()
        and trade_status != 'EXPIRED'
    {% endset %}
    {% do run_query(sql) %}
  {% endif %}
{% endmacro %}
