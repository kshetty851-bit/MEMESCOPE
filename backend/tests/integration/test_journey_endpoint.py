"""The homepage journey read: live counts, and nothing else from the real wallet."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from solders.keypair import Keypair

from app.api.v1.endpoints import journey as api
from app.core.config import settings
from app.models.real_wallet_execution import RealWalletPosition

pytestmark = pytest.mark.integration

OWNER = str(Keypair().pubkey())


async def test_today_counts_only_the_owners_trades_since_dubai_midnight(
        db_session, monkeypatch):
    monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY", OWNER)
    monkeypatch.setattr(api, "_CACHE", None)

    async def github(now):
        return {"commits": 760, "merged_prs": 154}

    monkeypatch.setattr(api, "github_counts", github)
    now = datetime.now(UTC)

    def closed(pnl: str, at: datetime, wallet: str = OWNER,
               mint: str = "m") -> RealWalletPosition:
        return RealWalletPosition(mint_address=mint, status="CLOSED", quantity=Decimal(1),
                                  entry_price_usd=Decimal(25), opened_at=at, closed_at=at,
                                  realised_net_pnl_usd=Decimal(pnl), wallet_public_key=wallet)

    db_session.add_all([
        closed("1.10", now - timedelta(minutes=5), mint="a"),
        closed("-0.40", now - timedelta(minutes=4), mint="b"),
        closed("9", now - timedelta(minutes=3), wallet=str(Keypair().pubkey()), mint="c"),
        closed("2", now - timedelta(days=2), mint="d"),          # before today
    ])
    await db_session.flush()

    out = await api.journey(db_session)
    assert out["real_today"]["trades"] == 2 and out["real_today"]["wins"] == 1
    assert out["trades_tested"] == 4                             # every real trade counts here
    assert (out["commits"], out["merged_prs"]) == (760, 154)
    # Counts and the lab's headline only: no amounts, coins or address.
    assert set(out["real_today"]) == {"trades", "wins", "since"}
    assert OWNER not in str(out)
    assert set(out["lab"]) == {"started_at", "judge_at", "trades", "wins", "rugs",
                               "finished_days", "last_day_pnl_usd"}
    monkeypatch.setattr(api, "_CACHE", None)


def test_only_the_journey_path_opens_to_the_public():
    from app.middleware.alpha_access import AlphaAccessMiddleware

    exempt = AlphaAccessMiddleware._is_exempt
    assert exempt("/api/v1/journey")
    assert not exempt("/api/v1/journey/x")
    assert not exempt("/api/v1/real-wallet/status")
