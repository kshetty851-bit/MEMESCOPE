"""The paper labs block a rugged name for 12h; wallet policy stays separate."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.labs.graduation import api as gapi
from app.labs.graduation import config, moneyblock
from app.real_wallet.driver import RealWalletDriver

START = datetime(2026, 10, 1, tzinfo=UTC)


def position(mint, opened, *, net=-0.8, symbol="Grok"):
    return SimpleNamespace(
        mint=mint, symbol=symbol, opened_at=opened,
        closed_at=opened + timedelta(minutes=5), net_return=net,
    )


def test_paper_defaults_are_12_hours_without_enabling_wallet_check():
    assert config.KARTHIK_LAB_RUGGED_NAME_BAN is True
    assert config.KARTHIK_RUGGED_NAME_HOURS == 12
    assert config.KARTHIK_WALLET_RUGGED_NAME_BAN is False
    assert config.KARTHIK_WALLET_RUGGED_NAME_HOURS == 48
    assert moneyblock.SAME_NAME_BLOCK_HOURS == 3


def test_block_replays_from_day_one_and_normalizes_the_name():
    rug = position("first", START)
    repeat = position("second", rug.closed_at + timedelta(hours=11),
                      symbol="G.R.O.K", net=0.2)
    kept, refused, _, _ = gapi._without_bad_names([repeat, rug])
    assert kept == [rug]
    assert refused == 1


def test_twelve_hours_runs_from_the_rug_close_and_expires_at_the_boundary():
    rug = position("first", START)
    before = position("before", rug.closed_at + timedelta(hours=12, microseconds=-1))
    boundary = position("boundary", rug.closed_at + timedelta(hours=12), net=0.1)
    kept, refused, _, _ = gapi._without_bad_names([rug, before, boundary])
    assert kept == [rug, boundary]
    assert refused == 1


def test_a_future_rug_does_not_block_an_already_opening_coin():
    rug = position("first", START)
    concurrent = position("concurrent", START + timedelta(minutes=3), net=0.1)
    assert gapi._without_bad_names([rug, concurrent])[0] == [rug, concurrent]


@pytest.mark.parametrize(("loss", "refused"), [(-0.50, True), (-0.499, False)])
def test_only_a_loss_of_at_least_fifty_percent_starts_the_block(loss, refused):
    first = position("first", START, net=loss)
    later = position("later", START + timedelta(hours=1), net=0.1)
    assert (later not in gapi._without_bad_names([first, later])[0]) is refused


def test_a_skipped_coin_cannot_extend_the_block_with_its_hypothetical_rug():
    rug = position("first", START)
    skipped = position("skipped", START + timedelta(hours=6))
    allowed = position("allowed", rug.closed_at + timedelta(hours=12), net=0.1)
    assert gapi._without_bad_names([rug, skipped, allowed])[0] == [rug, allowed]


def test_each_lab_uses_its_own_exit_outcomes():
    karthik = [position("first", START, net=-0.4),
               position("again", START + timedelta(hours=1), net=0.1)]
    pump = [position("first", START, net=-0.8),
            position("again", START + timedelta(hours=1), net=0.1)]
    assert gapi._without_bad_names(karthik)[0] == karthik
    assert gapi._without_bad_names(pump)[0] == pump[:1]


@pytest.mark.parametrize("lab_enabled", [False, True])
@pytest.mark.parametrize("lab_hours", [1, 12, 48])
async def test_lab_switch_and_window_never_enable_wallet_name_block(
    monkeypatch, lab_enabled, lab_hours,
):
    monkeypatch.setattr(config, "KARTHIK_LAB_RUGGED_NAME_BAN", lab_enabled)
    monkeypatch.setattr(config, "KARTHIK_RUGGED_NAME_HOURS", lab_hours)
    monkeypatch.setattr(config, "KARTHIK_WALLET_RUGGED_NAME_BAN", False)
    session = SimpleNamespace(scalar=AsyncMock(return_value="Grok"), scalars=AsyncMock())
    wallet = SimpleNamespace(_session=session)
    assert await RealWalletDriver._bad_name(wallet, "new-mint", "G-Q50", START) is False
    session.scalars.assert_not_awaited()


async def test_wallet_uses_its_own_window_if_its_own_switch_is_enabled(monkeypatch):
    monkeypatch.setattr(config, "KARTHIK_LAB_RUGGED_NAME_BAN", False)
    monkeypatch.setattr(config, "KARTHIK_RUGGED_NAME_HOURS", 12)
    monkeypatch.setattr(config, "KARTHIK_WALLET_RUGGED_NAME_BAN", True)
    monkeypatch.setattr(config, "KARTHIK_WALLET_RUGGED_NAME_HOURS", 48)
    session = SimpleNamespace(
        scalar=AsyncMock(return_value="Grok"),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: ["GROK"])),
    )
    wallet = SimpleNamespace(_session=session)
    assert await RealWalletDriver._bad_name(wallet, "new-mint", "G-Q50", START) is True
    statement = session.scalars.await_args.args[0]
    assert START - timedelta(hours=48) in statement.compile().params.values()


async def test_permanent_wallet_name_exclusion_still_applies_with_window_off(monkeypatch):
    monkeypatch.setattr(config, "KARTHIK_WALLET_RUGGED_NAME_BAN", False)
    session = SimpleNamespace(scalar=AsyncMock(return_value="MrBeast"), scalars=AsyncMock())
    assert await RealWalletDriver._bad_name(
        SimpleNamespace(_session=session), "new-mint", "G-Q50", START,
    ) is True
    session.scalars.assert_not_awaited()
