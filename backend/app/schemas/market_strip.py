"""The market figures a trader needs before acting on anything we surface.

Lifted out of `opportunities/schemas.py` in Sprint 23, unchanged in shape, so
the Radar and the Opportunity board answer "what is this trading at?" with one
object rather than two that drift. The board's `MarketOut` is now an alias for
this; the wire format did not change.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.schemas.common import BaseSchema


class MarketStripOut(BaseSchema):
    """Price, size and flow for one token, as last observed.

    Every field is optional and the whole object is nullable, because a token
    the market has not priced yet is a real state — and rendering a missing
    price as `$0` would be the estimate this platform does not make. A client
    that gets `market: null` must say "no market data", never zero.

    Money stays a string end to end (`NUMERIC` in Postgres, string in JSON) so
    no float rounding sits between the snapshot and the screen.
    """

    price_usd: Decimal | None = None
    market_cap: Decimal | None = None
    liquidity_usd: Decimal | None = None
    volume_24h: Decimal | None = None
    #: Percent change over 24h, when both ends of the window were observed.
    change_24h_pct: Decimal | None = None
    #: When this reading was taken. Surfaced so a stale price is visibly stale
    #: rather than silently presented as current.
    captured_at: datetime | None = None
    dex_name: str | None = None
