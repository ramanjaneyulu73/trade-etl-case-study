{% macro mark_expired_trades() %}
{#
  Demonstrates the literal "mark as expired" mutation (rule 4) as a
  standalone maintenance operation, the pattern this project would rely on
  once fct_valid_trades becomes a true incremental model that isn't
  rebuilt from scratch every run (see docs/architecture.md, 10,000x scale
  section). Safe to run repeatedly: only flips rows that need flipping.
  Runs automatically after every `dbt run` via on-run-end, and can also be
  invoked directly: dbt run-operation mark_expired_trades
#}
  {% if execute %}
    {% set relation = ref('fct_valid_trades') %}
    {% set sql %}
      update {{ relation }}
      set trade_status = 'EXPIRED'
      where maturity_date < current_date()
        and trade_status != 'EXPIRED'
    {% endset %}
    {% do run_query(sql) %}
  {% endif %}
{% endmacro %}
