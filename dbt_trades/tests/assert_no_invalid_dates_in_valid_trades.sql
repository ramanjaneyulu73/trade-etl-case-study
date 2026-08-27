-- Singular test: a trade that passed validation must never have a maturity
-- date before its trade date. Fails (returns rows) if it ever does.
select trade_id, version, trade_date, maturity_date
from {{ ref('fct_valid_trades') }}
where maturity_date < trade_date
