-- TEMPLATE ONLY. Resolve config/memescope_mapping.yaml before use.
-- Run only with a database role that is technically read-only.
BEGIN TRANSACTION READ ONLY;
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;

-- Replace TODO identifiers after verifying the current live schema and the
-- distinction between event time and ingestion/availability time.
SELECT
  TODO_opportunity_id,
  TODO_full_mint_address,
  TODO_full_pool_address,
  TODO_decision_availability_ts,
  TODO_strategy_version,
  TODO_baseline_eligible
FROM TODO_complete_eligible_opportunity_view
WHERE TODO_decision_availability_ts >= :start_ts
  AND TODO_decision_availability_ts < :end_ts
ORDER BY TODO_decision_availability_ts, TODO_full_mint_address;

ROLLBACK;
