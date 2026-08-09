"""v1 API router.

New feature areas (scanner, tokens, alerts, watchlists) get their own module in
`endpoints/` and a single `include_router` line here.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    alpha,
    analysts,
    auth,
    events,
    health,
    identity,
    market,
    scores,
    tokens,
    users,
    watchlists,
)
from app.exit_signals import api as intelligence
from app.health import api as pipeline_health
from app.opportunities import api as opportunities
from app.paper import api as paper
from app.radar import api as radar
from app.real_wallet import api as real_wallet
from app.real_wallet_safety import api as real_wallet_safety

api_router = APIRouter()
api_router.include_router(health.router)
# Pipeline health, on its own `/health` prefix so it cannot be confused with the
# liveness and readiness probes above. Those report this process; this reports
# whether the platform is still producing anything.
api_router.include_router(pipeline_health.router)
api_router.include_router(alpha.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(tokens.router)
# Registered after tokens.router so the literal `/tokens/latest` route still
# wins over `/tokens/{mint}` path matching.
api_router.include_router(market.token_market_router)
api_router.include_router(market.market_router)
# `/scores/top` and `/scores/model` are declared before `/scores/{mint}` inside
# the module, for the same reason.
api_router.include_router(scores.router)
# The Opportunity Radar. Additive: no existing route changes shape. Its own
# module declares literal paths before `/{mint}`, as the scores router does.
api_router.include_router(radar.router)
# Exit Watch, the permanent record and the leaderboards. Additive; the Radar's
# own routes and every pre-existing endpoint are unchanged.
api_router.include_router(intelligence.router)
# Clone risk. Additive, and the only API added in Phase 12: deciding whether a
# name is contested needs a scan across every discovered token, so it cannot be
# computed client-side.
api_router.include_router(identity.router)
# The Phase 15 analyst ensemble. Additive and read-only: it runs the six pure
# analysts over stored observations and publishes its own weights.
api_router.include_router(analysts.router)
# Phase 17: watchlists and the event log. Watchlist routes are scoped to the
# authenticated user in SQL; event routes are read-only. Additive throughout —
# no existing route changed shape.
api_router.include_router(watchlists.router)
api_router.include_router(events.router)
# Sprint 4/5: the Opportunity board. Its own namespace rather than reshaping
# `/radar` — opportunities live in their own tables and `/radar` has an
# established shape driven by a different model. Additive: no existing route
# changes, and the board is empty while the engine's feature flag is off.
api_router.include_router(opportunities.router)
# Sprint 25: the paper wallet. Its own namespace. Sprint 35 adds a paper-only
# manual close endpoint, but still no manual entry and no real execution path.
# Additive: no existing route changes, and the wallet reports itself as not
# running while its feature flag is off rather than serving an empty book.
api_router.include_router(paper.router)
# Safety decisions are an audit/read surface only. They cannot request a
# wallet, build a transaction, or invoke an execution engine.
api_router.include_router(real_wallet_safety.router)
# Dedicated execution-wallet visibility is admin-only and read-only. It is
# intentionally a separate boundary from the safety audit endpoints above.
api_router.include_router(real_wallet.router)
