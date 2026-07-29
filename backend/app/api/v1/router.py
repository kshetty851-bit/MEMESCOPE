"""v1 API router.

New feature areas (scanner, tokens, alerts, watchlists) get their own module in
`endpoints/` and a single `include_router` line here.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, health, market, scores, tokens, users
from app.exit_signals import api as intelligence
from app.radar import api as radar

api_router = APIRouter()
api_router.include_router(health.router)
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
