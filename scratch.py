from sqlalchemy import text, bindparam, String
from sqlalchemy.dialects.postgresql import ARRAY
from datetime import datetime

stmt = text("""
    SELECT m.mint, latest.price_usd
    FROM unnest(:mints) AS m(mint)
    CROSS JOIN LATERAL (
        SELECT price_usd
        FROM token_market_snapshots
        WHERE mint_address = m.mint
          AND captured_at <= :as_of
          AND price_usd IS NOT NULL
        ORDER BY captured_at DESC
        LIMIT 1
    ) latest
""").bindparams(
    bindparam("mints", value=["a", "b"], type_=ARRAY(String)),
    bindparam("as_of", value=datetime.now())
)
print("Syntax OK")
