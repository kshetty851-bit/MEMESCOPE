"""Mood Lab: the live rules are the backtested thresholds, and P/L charges costs and funding."""

from app.labs.mood import mood


def test_signals_match_backtest_thresholds():
    assert mood.signal("shadow", {"top": .9, "retail": .4, "fund": .5}) == 1
    assert mood.signal("shadow", {"top": .1, "retail": .6, "fund": .5}) == -1
    assert mood.signal("shadow", {"top": .6, "retail": .4, "fund": .5}) == 0
    assert mood.signal("shadow", {"top": None, "retail": .4, "fund": .5}) == 0
    assert mood.signal("contra", {"top": .5, "retail": .8, "fund": .9}) == -1
    assert mood.signal("contra", {"top": .5, "retail": .79, "fund": .95}) == 0


def test_percentile_needs_60_days_and_uses_only_the_past():
    assert mood.pct(list(range(59)), 10) is None
    assert mood.pct(list(range(100)), 50) == .5
    days = [{"fund": float(i), "ret_ls": float(i), "top": float(i)} for i in range(100)]
    days.append({"fund": 1000.0, "ret_ls": -1.0, "top": 50.0})
    r = mood.reading(days, 100)
    assert r["fund"] == 1.0 and r["retail"] == 0.0 and r["top"] == 40 / 90   # days 10-99 only


def test_net_charges_costs_and_funding_by_side():
    assert abs(mood.net(1, 100, 110, 0.001) - (0.10 - 0.002 - 0.001)) < 1e-12
    assert abs(mood.net(-1, 100, 90, 0.001) - (0.10 - 0.002 + 0.001)) < 1e-12
    assert mood.mood_score({"fund": 1.0, "retail": 1.0, "top": None}) == 100
