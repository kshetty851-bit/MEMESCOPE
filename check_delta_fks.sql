CREATE TEMP TABLE ovh_ids (id uuid PRIMARY KEY);
\copy ovh_ids FROM 'ovh_position_ids.txt'

-- Missing positions
CREATE TEMP TABLE missing_positions AS
SELECT * FROM paper_positions p
LEFT JOIN ovh_ids o ON p.id = o.id
WHERE o.id IS NULL;

-- Audit rows
-- we need to get ovh audit ids first.
CREATE TEMP TABLE ovh_audit_ids (id uuid PRIMARY KEY);
\copy ovh_audit_ids FROM 'ovh_audit_ids.txt'

CREATE TEMP TABLE missing_audit AS
SELECT a.* FROM paper_trade_audit a
LEFT JOIN ovh_audit_ids o ON a.id = o.id
WHERE o.id IS NULL;

SELECT 'missing_pos_token_ids', token_id FROM missing_positions;
SELECT 'missing_audit_ids', id, position_id FROM missing_audit;
