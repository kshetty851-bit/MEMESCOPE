"""v1 API router.

New feature areas (scanner, tokens, alerts, watchlists) get their own module in
`endpoints/` and a single `include_router` line here.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, health, market, tokens, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(tokens.router)
# Registered after tokens.router so the literal `/tokens/latest` route still
# wins over `/tokens/{mint}` path matching.
api_router.include_router(market.token_market_router)
api_router.include_router(market.market_router)
