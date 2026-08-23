-- Export 4 missing positions
\copy (SELECT * FROM paper_positions WHERE id IN ('d6c684f8-40b5-4fa6-ac05-e369bbdad592', '6485bd17-0f91-453f-961a-362fd690291e', 'ba01dcf2-6b40-4b23-b5b6-5c86e2fc8677', '5d4922be-d4c0-4dfa-bd35-e781231a4a99')) TO 'delta_inserts_positions.csv' CSV HEADER

-- Export 2 missing audit rows
\copy (SELECT * FROM paper_trade_audit WHERE position_id IN ('8864a96f-0d0c-402f-bdfc-50fde7706ea8', '3e27e859-d1dd-4520-bf19-9e50af043ed6')) TO 'delta_inserts_audit.csv' CSV HEADER

-- Export 10 updated positions
\copy (SELECT * FROM paper_positions WHERE id IN ('50c1165e-ecc0-4ad1-a77e-628bc766431a', '8864a96f-0d0c-402f-bdfc-50fde7706ea8', 'eda89dde-c642-4d8f-9274-b1d6d31895df', '3e27e859-d1dd-4520-bf19-9e50af043ed6', 'de2a52c9-329e-41ae-9e5d-1c6ca0ff4c1d', '40b24ba0-c767-43e4-89a1-d4e2a7b6c0c1', '0ea78a00-b066-4ab8-86b8-2a8b86a9b117', 'ed2986dd-fac4-438d-9b2a-dca10c73c6c1', '5debd314-c5d1-428f-a445-90a2df1449cd', '0d339cb2-b8ac-499d-a604-0a8bd3698a86')) TO 'delta_updates_positions.csv' CSV HEADER
