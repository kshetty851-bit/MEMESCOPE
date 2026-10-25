"""Money, timing and reconciliation regressions for the independent paper book."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D  # noqa: N817

from app.labs.graduation.pool_sprint_book import START, WSOL_MINT, Observation, report, walk


def coin(mint="a", minute=0, ret="0.2", hold=5):
    at = START + timedelta(minutes=minute)
    return Observation(
        mint,
        f"pool-{mint}",
        at,
        D(1),
        D(15000),
        exited_at=at + timedelta(minutes=hold),
        exit_price=1 + D(ret),
        source="dexscreener",
        base_mint=mint,
        quote_mint=WSOL_MINT,
        pair_evidence="synthetic_test",
        graduated_at=at - timedelta(seconds=10),
        entry_buys=65,
        entry_sells=35,
    )


def test_sol_filter_refuses_other_quotes_wrong_base_and_unverified_identities():
    rows = [
        coin("sol"),
        replace(coin("spcx"), quote_mint="SPCX"),
        replace(coin("reverse"), base_mint="other"),
        replace(coin("unknown"), pair_evidence=None),
    ]
    r = report(rows, START + timedelta(minutes=10))
    assert r["trades"] == 1 and r["pnl_usd"] == "10.00"
    assert r["excluded_non_sol"] == 2 and r["unverified_pools"] == 1
    assert r["trades_list"][0]["quote_mint"] == WSOL_MINT


def test_fresh65_requires_original_counts_and_exact_freshness_boundaries():
    c = coin()
    assert replace(c, graduated_at=c.opened_at).fresh65
    assert replace(c, graduated_at=c.opened_at - timedelta(seconds=30)).fresh65
    assert replace(c, entry_buys=13, entry_sells=7).fresh65
    for refused in [
        replace(c, graduated_at=c.opened_at - timedelta(seconds=30, microseconds=1)),
        replace(c, graduated_at=c.opened_at + timedelta(microseconds=1)),
        replace(c, graduated_at=None),
        replace(c, entry_buys=None),
        replace(c, entry_sells=None),
        replace(c, entry_buys=0, entry_sells=0),
        replace(c, entry_buys=64, entry_sells=36),
        replace(c, entry_buys=-1),
        replace(c, entry_sells=-1),
    ]:
        assert not refused.fresh65
        assert walk([refused], as_of=c.opened_at + timedelta(minutes=10))["trades"] == 0


def test_every_comparison_uses_the_same_fresh65_entry_filter():
    good = coin("good")
    refused = replace(coin("refused", ret="100"), entry_buys=64, entry_sells=36)
    r = report([good, refused], START + timedelta(minutes=20))
    assert r["entry_rule"] == "FRESH_30S_BUYS_65PCT"
    assert r["excluded_entry_rule"] == 1 and r["pnl_usd"] == "10.00"
    assert r["trades_list"][0]["entry_buys"] == 65
    assert all(row["trades"] == 1 for row in r["costs"])
    assert r["start_dates"][-1]["trades"] == 1
    assert all(row["cells"][0]["trades"] == 1 for row in r["sizes"])


def test_a_sale_funds_only_entries_at_or_after_its_exit():
    rows = [coin("a"), coin("b", 4), coin("c", 5)]
    r = walk(rows, as_of=START + timedelta(minutes=20), capital=D(50), details=True)
    assert r["trades"] == 2
    assert r["skipped"] == 1
    assert r["skipped_list"][0]["mint"] == "b"
    assert r["balance_usd"] == "70.00"
    assert r["lowest_cash_usd"] == "0.00"


def test_overlapping_entries_reserve_separate_stakes():
    rows = [coin("a", ret="-0.5"), coin("b", 1, "0"), coin("c", 2)]
    r = walk(rows, as_of=START + timedelta(minutes=20), capital=D(100))
    assert (r["trades"], r["skipped"], r["max_concurrent"]) == (2, 1, 2)
    assert r["balance_usd"] == "75.00"
    assert r["rugs"] == 1


def test_missing_exit_reduces_conservative_balance_but_is_not_an_observed_rug():
    c = replace(coin(), exited_at=None, exit_price=None, source=None)
    r = walk([c], as_of=START + timedelta(minutes=8), capital=D(100), details=True)
    assert (r["unpriced"], r["closed"], r["rugs"]) == (1, 0, 0)
    assert r["pricing_reserve_usd"] == "50.00"
    assert r["priced_pnl_usd"] == "0.00"
    assert r["balance_usd"] == r["free_cash_usd"] == "50.00"
    assert r["trades_list"][0]["pct"] is None
    assert r["trades_list"][0]["rugged"] is False


def test_future_exit_does_not_credit_cash_or_profit_early():
    r = walk([coin()], as_of=START + timedelta(minutes=4), capital=D(100), details=True)
    assert r["open"] == 1 and r["closed"] == 0
    assert r["balance_usd"] == "100.00" and r["free_cash_usd"] == "50.00"
    assert r["open_stake_usd"] == "50.00"
    assert r["trades_list"][0]["status"] == "open"


def test_an_unknown_exit_is_not_reserved_until_seven_minutes():
    c = replace(coin(), exited_at=None, exit_price=None)
    before = walk([c], as_of=START + timedelta(minutes=6), capital=D(100))
    after = walk([c], as_of=START + timedelta(minutes=7), capital=D(100))
    assert before["unpriced"] == 0 and before["open"] == 1
    assert after["unpriced"] == 1 and after["open"] == 0


def test_each_cost_scenario_has_its_own_cash_limit():
    rows = [coin()]
    free = walk(rows, as_of=START + timedelta(minutes=10), capital=D(50))
    costly = walk(rows, as_of=START + timedelta(minutes=10), capital=D(50), cost=D(1))
    assert free["trades"] == 1 and costly["trades"] == 0
    assert costly["skipped"] == 1 and costly["balance_usd"] == "50.00"


def test_pool_boundaries_and_invalid_entry_quote():
    rows = [
        replace(coin("low"), liquidity=D(10000)),
        replace(coin("below"), liquidity=D(9999)),
        replace(coin("high"), liquidity=D(40000)),
        replace(coin("bad"), entry_price=D(0)),
    ]
    r = walk(rows, as_of=START + timedelta(minutes=10))
    assert r["signals"] == r["trades"] == 1


def test_daily_profit_uses_dubai_close_day_and_reconciles_costs():
    c = coin(minute=23 * 60 + 58)
    r = walk([c], as_of=START + timedelta(days=2), capital=D(100), cost=D(1))
    days = {d["date"]: d for d in r["days"]}
    assert days["2026-10-01"]["pnl_usd"] == "-1.00"
    assert days["2026-10-02"]["pnl_usd"] == "10.00"
    assert sum(D(d["pnl_usd"]) for d in r["days"]) == D(r["pnl_usd"])
    assert r["balance_usd"] == "109.00"


def test_a_fresh_start_excludes_prior_entries_and_their_proceeds():
    rows = [coin("a"), coin("b", 24 * 60)]
    r = walk(rows, as_of=START + timedelta(days=2), start=START + timedelta(days=1))
    assert r["trades"] == 1 and r["priced_pnl_usd"] == "10.00"


def test_priced_profit_and_reserve_reconcile_in_a_synthetic_account():
    at = START + timedelta(minutes=20)
    rows = [
        coin("quote", ret="1"),
        replace(coin("candle", 1, "1"), source="geckoterminal_candle_close"),
        replace(coin("gap", 2), exited_at=None, exit_price=None, source=None),
    ]
    r = walk(rows, as_of=at, capital=D(2000))
    assert (r["signals"], r["trades"], r["skipped"]) == (3, 3, 0)
    assert (r["closed"], r["unpriced"], r["rugs"]) == (2, 1, 0)
    assert (r["dex_exits"], r["candle_exits"]) == (1, 1)
    assert r["priced_pnl_usd"] == "100.00"
    assert r["pricing_reserve_usd"] == "50.00"
    assert r["balance_usd"] == "2050.00"
    assert r["lowest_cash_usd"] == "1850.00"


def test_same_account_matches_all_current_comparison_cells():
    at = START + timedelta(days=2, minutes=20)
    rows = [coin("a"), coin("b", 30, "-0.8"), coin("c", 24 * 60 + 1)]
    r = report(list(rows), at)
    size50 = next(row for row in r["sizes"] if D(row["ticket_usd"]) == 50)["cells"][0]
    cost0 = r["costs"][0]
    first_start = r["start_dates"][-1]
    for comp in [size50, cost0, first_start]:
        for key in ["balance_usd", "pnl_usd", "trades", "rugs", "skipped", "lowest_usd"]:
            assert comp[key] == r[key]
    assert abs(sum(D(b["pnl_usd"]) for b in r["bands"]) - D(r["pnl_usd"])) <= D("0.02")


def test_creator_block_starts_at_close_not_at_the_earlier_buy():
    rows = [
        replace(coin("rug", ret="-0.5"), creator="A"),
        replace(coin("already_open", minute=4), creator="A"),
        replace(coin("later", minute=5), creator="A"),
        coin("unknown", minute=6),
    ]
    b = walk(rows, as_of=START + timedelta(minutes=20), details=True)
    assert b["trades"] == 3 and b["creator_skipped"] == 1 and b["skipped"] == 0
    assert b["creator_blocked_list"][0]["mint"] == "later"
    assert (
        b["creator_blocked_list"][0]["blocked_since"]
        == (START + timedelta(minutes=5)).isoformat()
    )


def test_candle_rug_is_not_known_until_the_seven_minute_deadline():
    rows = [
        replace(coin("rug", ret="-0.5"), creator="A", source="geckoterminal_candle_close"),
        replace(coin("before_deadline", minute=6), creator="A"),
        replace(coin("at_deadline", minute=7), creator="A"),
    ]
    b = walk(rows, as_of=START + timedelta(minutes=20), details=True)
    assert b["trades"] == 2 and b["creator_skipped"] == 1
    assert b["creator_blocked_list"][0]["mint"] == "at_deadline"


def test_unpriced_exit_or_sub50_percent_loss_does_not_trigger_creator_block():
    rows = [
        replace(coin("gap"), creator="A", exit_price=None, exited_at=None),
        replace(coin("under_threshold", ret="-0.49"), creator="B"),
        replace(coin("nextA", minute=10), creator="A"),
        replace(coin("nextB", minute=10), creator="B"),
    ]
    b = walk(rows, as_of=START + timedelta(minutes=20), cost=D(1))
    assert b["trades"] == 4 and b["creator_skipped"] == 0 and b["blocked_creators"] == 0


def test_creator_history_belongs_to_each_funded_scenario():
    rows = [
        replace(coin("rug", ret="-0.5"), creator="A"),
        replace(coin("next", minute=24 * 60 + 1), creator="A"),
    ]
    full = walk(rows, as_of=START + timedelta(days=2))
    later = walk(rows, start=START + timedelta(days=1), as_of=START + timedelta(days=2))
    assert full["creator_skipped"] == 1
    assert later["creator_skipped"] == 0 and later["trades"] == 1
    excluded = [replace(rows[0], entry_buys=0), rows[1]]
    assert walk(excluded, as_of=START + timedelta(days=2))["creator_skipped"] == 0
