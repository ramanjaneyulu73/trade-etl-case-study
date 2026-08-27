{% macro generate_schema_name(custom_schema_name, node) -%}
    {#- Use the custom schema (STAGING/MARTS) exactly as configured in
       dbt_project.yml, without prefixing the target/profile schema. Matches
       what every doc, diagram, and the dashboard's connection expect. #}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
