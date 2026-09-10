"""The three regimes, their boundaries, and BTC's veto."""

from __future__ import annotations

from app.labs.crypto_trend import config
from app.labs.crypto_trend.regime import CHOP, RISK_OFF, RISK_ON, compute_regime
from app.labs.crypto_trend.tests.fakes import NOW


def directions(up: int, down: int, flat: int, *, btc: str | None = "FLAT",
               eth: str | None = "FLAT") -> dict[str, str]:
    """`up`/`down`/`flat` anonymous coins PLUS BTC and ETH, so the universe
    has up + down + flat + 2 coins and BTC/ETH count toward breadth."""
    d = {f"U{i}USDT": "UP" for i in range(up)}
    d |= {f"D{i}USDT": "DOWN" for i in range(down)}
    d |= {f"F{i}USDT": "FLAT" for i in range(flat)}
    if btc is not None:
        d["BTCUSDT"] = btc
    if eth is not None:
        d["ETHUSDT"] = eth
    return d


def regime(d):
    return compute_regime(d, bar_close_time=NOW, computed_at=NOW)


def test_risk_on_at_exactly_sixty_percent_with_btc_up() -> None:
    # 10 UP + BTC UP + ETH UP = 12 of 20
    r = regime(directions(10, 4, 4, btc="UP", eth="UP"))
    assert (r.coins, r.breadth_up, r.breadth_down) == (20, 0.6, 0.2)
    assert r.regime == RISK_ON
    assert (r.btc_direction, r.eth_direction) == ("UP", "UP")


def test_risk_on_with_three_of_five_and_btc_flat() -> None:
    r = regime(directions(3, 0, 0, btc="FLAT", eth="FLAT"))  # 3 of 5 = 0.6
    assert r.breadth_up == 0.6 and r.regime == RISK_ON


def test_just_under_the_threshold_is_chop() -> None:
    r = regime(directions(9, 4, 5, btc="UP", eth="UP"))  # 9 + BTC + ETH = 11 of 20 = 0.55
    assert r.breadth_up == 0.55 and r.regime == CHOP


def test_btc_down_vetoes_risk_on() -> None:
    r = regime(directions(13, 0, 5, btc="DOWN", eth="UP"))  # 13 + ETH = 14 of 20 = 0.7 UP
    assert r.breadth_up == 0.7 and r.regime == CHOP


def test_risk_off_and_btc_up_vetoes_it() -> None:
    # 12 DOWN + ETH DOWN = 13 of 20 (0.65); 14 of 20 when BTC is DOWN as well
    assert regime(directions(2, 12, 4, btc="DOWN", eth="DOWN")).regime == RISK_OFF
    assert regime(directions(2, 12, 4, btc="UP", eth="DOWN")).regime == CHOP
    assert regime(directions(2, 12, 4, btc="FLAT", eth="DOWN")).regime == RISK_OFF


def test_a_missing_btc_vetoes_nothing() -> None:
    r = regime(directions(12, 0, 8, btc=None, eth=None))
    assert r.btc_direction is None and r.eth_direction is None
    assert r.regime == RISK_ON


def test_no_states_is_chop_with_zero_breadth() -> None:
    r = regime({})
    assert (r.coins, r.breadth_up, r.breadth_down, r.regime) == (0, 0.0, 0.0, CHOP)
    assert r.btc_direction is None


def test_thresholds_are_configurable(monkeypatch) -> None:
    monkeypatch.setattr(config, "BREADTH_RISK_ON", 0.9)
    assert regime(directions(14, 0, 4, btc="UP", eth="UP")).regime == CHOP  # 16/20 = 0.8
    monkeypatch.setattr(config, "BREADTH_RISK_ON", 0.5)
    assert regime(directions(9, 5, 4, btc="UP", eth="UP")).regime == RISK_ON  # 11/20
