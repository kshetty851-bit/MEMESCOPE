"""The filter chain, the one-pool-per-token collapse, and the refresh."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.labs.breakout import config
from app.labs.breakout.models import BoUniverseMember
from app.labs.breakout.tests.fakes import (
    NOW,
    USDC,
    WSOL,
    FakeSource,
    dex_pair,
    gecko_body,
    gecko_pool,
)
from app.labs.breakout.universe import (
    BreakoutUniverse,
    Candidate,
    dex_allowed,
    from_dex_pair,
    gecko_candidates,
    reject_reason,
    select_universe,
)


def candidate(**kw) -> Candidate:
    base = {
        "mint": "MintAAA", "symbol": "AAA", "name": "Token A", "pool_address": "PoolAAA",
        "dex": "raydium", "pair_created_at": NOW - timedelta(days=30),
        "liquidity_usd": Decimal("250000"), "volume_24h_usd": Decimal("900000"),
        "price_usd": Decimal("0.04"), "fdv": Decimal("12000000"),
        "source": "geckoterminal",
    }
    return Candidate(**(base | kw))


# --- the dex allow-list -------------------------------------------------------

@pytest.mark.parametrize("dex", ["raydium", "raydium-clmm", "meteora",
                                 "meteora-damm-v2", "orca", "pumpswap", "ORCA"])
def test_the_allow_list_matches_venue_variants_by_prefix(dex) -> None:
    """`raydium-clmm` IS Raydium. Measured on 80 live pools, 4 of the 22 that
    cleared every other filter were `raydium-clmm` — an exact-match list would
    have dropped all four."""
    assert dex_allowed(dex) is True


@pytest.mark.parametrize("dex", ["pumpfun", "humidifi", "zerofi", "manifest", "lifinity"])
def test_everything_else_including_the_bonding_curve_is_refused(dex) -> None:
    assert dex_allowed(dex) is False


def test_the_denylist_wins_over_a_matching_allow_prefix(monkeypatch) -> None:
    """Order matters: with `pump` allowed, only the denylist keeps the curve out."""
    monkeypatch.setattr(config, "DEX_ALLOWLIST", ("pump",))
    assert dex_allowed("pumpswap") is True
    assert dex_allowed("pumpfun") is False


# --- the filters --------------------------------------------------------------

def test_a_qualifying_pool_has_no_reason_to_be_rejected() -> None:
    assert reject_reason(candidate(), NOW) is None


def test_a_pool_younger_than_min_age_days_is_refused() -> None:
    young = candidate(pair_created_at=NOW - timedelta(days=config.MIN_AGE_DAYS,
                                                      seconds=-1))
    assert reject_reason(young, NOW) == "age"
    exactly = candidate(pair_created_at=NOW - timedelta(days=config.MIN_AGE_DAYS))
    assert reject_reason(exactly, NOW) is None, "the floor is inclusive"


def test_an_unknown_age_is_refused_rather_than_assumed_old() -> None:
    assert reject_reason(candidate(pair_created_at=None), NOW) == "age_unknown"


def test_the_liquidity_and_volume_floors_are_inclusive() -> None:
    assert reject_reason(
        candidate(liquidity_usd=Decimal(config.MIN_LIQUIDITY_USD)), NOW) is None
    assert reject_reason(
        candidate(liquidity_usd=Decimal(config.MIN_LIQUIDITY_USD) - 1), NOW) == "liquidity"
    assert reject_reason(
        candidate(volume_24h_usd=Decimal(config.MIN_VOLUME_24H_USD)), NOW) is None
    assert reject_reason(
        candidate(volume_24h_usd=Decimal(config.MIN_VOLUME_24H_USD) - 1), NOW) == "volume"


def test_a_missing_liquidity_is_refused_not_treated_as_zero_or_as_passing() -> None:
    """DexScreener omits `liquidity` entirely on bonding-curve pairs. An
    unknown reserve is not a $50,000 one."""
    assert reject_reason(candidate(liquidity_usd=None), NOW) == "liquidity"
    assert reject_reason(candidate(volume_24h_usd=None), NOW) == "volume"


@pytest.mark.parametrize("mint", [WSOL, USDC])
def test_wrapped_sol_and_stables_are_excluded_by_mint(mint) -> None:
    assert reject_reason(candidate(mint=mint), NOW) == "excluded_mint"


def test_the_exclusion_runs_before_the_dex_check() -> None:
    """So the funnel counts a stablecoin as a stablecoin, whatever venue it is on."""
    assert reject_reason(candidate(mint=WSOL, dex="pumpfun"), NOW) == "excluded_mint"


# --- one pool per token -------------------------------------------------------

def test_the_deepest_pool_wins_and_the_others_become_alt_pools() -> None:
    shallow = candidate(pool_address="Shallow", liquidity_usd=Decimal("60000"))
    deep = candidate(pool_address="Deep", liquidity_usd=Decimal("400000"))
    middle = candidate(pool_address="Middle", liquidity_usd=Decimal("90000"))
    selected, _ = select_universe([shallow, deep, middle], NOW)
    assert len(selected) == 1
    assert selected[0].candidate.pool_address == "Deep"
    assert [a["pool_address"] for a in selected[0].alt_pools] == ["Middle", "Shallow"]


def test_a_pool_that_failed_the_filters_is_not_kept_as_an_alternate() -> None:
    """A too-shallow pool of the same token is not a fallback — it is a pool
    that failed."""
    deep = candidate(pool_address="Deep", liquidity_usd=Decimal("400000"))
    failing = candidate(pool_address="Thin", liquidity_usd=Decimal("10"))
    selected, rejected = select_universe([deep, failing], NOW)
    assert selected[0].alt_pools == []
    assert rejected["liquidity"] == 1


def test_the_same_pool_twice_from_two_sources_is_not_its_own_alternate() -> None:
    both = [candidate(source="geckoterminal"), candidate(source="dexscreener")]
    selected, _ = select_universe(both, NOW)
    assert len(selected) == 1 and selected[0].alt_pools == []


def test_different_tokens_stay_separate() -> None:
    selected, _ = select_universe(
        [candidate(mint="A", pool_address="PA"), candidate(mint="B", pool_address="PB")],
        NOW)
    assert {s.candidate.mint for s in selected} == {"A", "B"}


def test_the_universe_is_capped_by_24h_volume() -> None:
    pool = [candidate(mint=f"M{i}", pool_address=f"P{i}", volume_24h_usd=Decimal(i))
            for i in range(200_000, 200_010)]
    selected, rejected = select_universe(pool, NOW, size=3)
    assert [s.candidate.mint for s in selected] == ["M200009", "M200008", "M200007"]
    assert rejected["over_cap"] == 7


def test_the_reject_counter_reads_as_a_funnel() -> None:
    _, rejected = select_universe([
        candidate(mint=WSOL), candidate(mint="B", dex="pumpfun"),
        candidate(mint="C", pair_created_at=NOW), candidate(mint="D", liquidity_usd=None),
        candidate(mint="E", volume_24h_usd=Decimal("1")),
    ], NOW)
    assert dict(rejected) == {"excluded_mint": 1, "dex": 1, "age": 1,
                              "liquidity": 1, "volume": 1}


# --- normalisation ------------------------------------------------------------

def test_a_gecko_page_becomes_candidates_with_symbol_and_name() -> None:
    body = gecko_body(gecko_pool(mint="M1", symbol="ONE", name="Token One"))
    (found,) = gecko_candidates(body)
    assert (found.mint, found.symbol, found.name) == ("M1", "ONE", "Token One")
    assert found.liquidity_usd == Decimal("250000.0")
    assert found.volume_24h_usd == Decimal("900000.0")
    assert found.pair_created_at is not None and found.pair_created_at.tzinfo is not None
    assert found.source == "geckoterminal"


def test_a_gecko_row_missing_its_base_token_or_dex_is_dropped_not_guessed() -> None:
    pool, token = gecko_pool()
    pool["relationships"].pop("dex")
    assert gecko_candidates({"data": [pool], "included": [token]}) == []


def test_a_gecko_row_whose_token_was_not_included_still_yields_the_mint() -> None:
    """The id is `<network>_<mint>`; the tail is the mint when `included`
    did not carry the token (GeckoTerminal returned 17 tokens for 20 pools
    on the day this was measured)."""
    pool, _ = gecko_pool(mint="MintZZZ")
    (found,) = gecko_candidates({"data": [pool], "included": []})
    assert found.mint == "MintZZZ"
    assert found.symbol is None


def test_a_dex_pair_becomes_a_candidate_with_a_timezone_aware_creation_time() -> None:
    found = from_dex_pair(dex_pair(mint="M4", symbol="FOUR"))
    assert found is not None
    assert found.mint == "M4" and found.source == "dexscreener"
    assert found.pair_created_at.tzinfo is not None
    assert found.liquidity_usd == Decimal("180000")


def test_a_dex_pair_with_no_liquidity_key_normalises_to_none() -> None:
    found = from_dex_pair(dex_pair(liquidity=None))
    assert found is not None and found.liquidity_usd is None


def test_a_pair_on_another_chain_is_not_a_candidate() -> None:
    assert from_dex_pair(dex_pair(chain="base")) is None


def test_junk_numbers_do_not_become_zero() -> None:
    """A NaN would compare False against every floor and a None is honest."""
    pair = dex_pair()
    pair["liquidity"]["usd"] = "NaN"
    pair["volume"]["h24"] = "not a number"
    found = from_dex_pair(pair)
    assert found is not None
    assert found.liquidity_usd is None and found.volume_24h_usd is None


# --- the refresh --------------------------------------------------------------

@pytest.mark.integration
async def test_a_refresh_stores_the_universe_and_a_run(lab_session) -> None:
    pools = [gecko_pool(mint=f"M{i}", symbol=f"S{i}", pool=f"P{i}",
                        volume=900_000 - i) for i in range(3)]
    source = FakeSource(pages={1: gecko_body(*pools)},
                        boosts=[{"chainId": "solana", "tokenAddress": "M9"}],
                        pairs=[dex_pair(mint="M9", pool="P9")])
    result = await BreakoutUniverse(lab_session, source).refresh(NOW)

    assert result["universe_size"] == 4 and result["added"] == 4
    rows = (await lab_session.execute(select(BoUniverseMember))).scalars().all()
    assert {r.mint for r in rows} == {"M0", "M1", "M2", "M9"}
    assert all(r.active for r in rows)
    assert {r.source for r in rows} == {"geckoterminal", "dexscreener"}
    assert all(r.holders is None for r in rows), "no free source serves holders"


@pytest.mark.integration
async def test_a_token_that_stops_qualifying_is_marked_inactive_not_deleted(
    lab_session,
) -> None:
    universe = BreakoutUniverse(lab_session, FakeSource(
        pages={1: gecko_body(gecko_pool(mint="M1", pool="P1"),
                             gecko_pool(mint="M2", pool="P2"))}))
    await universe.refresh(NOW)

    shrunk = BreakoutUniverse(lab_session, FakeSource(
        pages={1: gecko_body(gecko_pool(mint="M1", pool="P1"))}))
    result = await shrunk.refresh(NOW)
    assert result["dropped"] == 1

    rows = {r.mint: r for r in (await lab_session.execute(
        select(BoUniverseMember))).scalars()}
    assert rows["M2"].active is False and rows["M2"].inactive_reason == "filtered_out"
    assert rows["M1"].active is True


@pytest.mark.integration
async def test_a_readmitted_token_keeps_first_seen_and_loses_its_failure_count(
    lab_session,
) -> None:
    pool = gecko_body(gecko_pool(mint="M1", pool="P1"))
    await BreakoutUniverse(lab_session, FakeSource(pages={1: pool})).refresh(NOW)
    first_seen = (await lab_session.execute(select(BoUniverseMember.first_seen))).scalar_one()

    await lab_session.execute(
        BoUniverseMember.__table__.update().values(active=False, fetch_failures=5,
                                                   inactive_reason="fetch_failures"))
    later = NOW.replace(day=12)
    await BreakoutUniverse(lab_session, FakeSource(pages={1: pool})).refresh(later)

    row = (await lab_session.execute(select(BoUniverseMember))).scalar_one()
    assert row.active is True and row.inactive_reason is None
    assert row.fetch_failures == 0, "qualifying again is a fresh start"
    assert row.first_seen == first_seen and row.last_seen == later


@pytest.mark.integration
async def test_an_empty_result_leaves_the_previous_universe_standing(lab_session) -> None:
    """A bad refresh must not empty the universe."""
    await BreakoutUniverse(lab_session, FakeSource(
        pages={1: gecko_body(gecko_pool(mint="M1", pool="P1"))})).refresh(NOW)

    result = await BreakoutUniverse(lab_session, FakeSource()).refresh(NOW)
    assert result["universe_size"] == 0
    assert "unchanged" in result["errors"][0]
    row = (await lab_session.execute(select(BoUniverseMember))).scalar_one()
    assert row.active is True


@pytest.mark.integration
async def test_a_refresh_is_idempotent(lab_session) -> None:
    body = gecko_body(gecko_pool(mint="M1", pool="P1"))
    universe = BreakoutUniverse(lab_session, FakeSource(pages={1: body}))
    await universe.refresh(NOW)
    second = await BreakoutUniverse(lab_session, FakeSource(pages={1: body})).refresh(NOW)
    assert second["added"] == 0 and second["dropped"] == 0
    assert len((await lab_session.execute(select(BoUniverseMember))).scalars().all()) == 1


async def test_one_source_failing_does_not_cost_the_other(lab_session=None) -> None:
    """GeckoTerminal alone is a working universe and so is DexScreener alone."""
    class HalfBroken(FakeSource):
        async def gecko_pools(self, page):
            raise RuntimeError("gecko down")

        async def gecko_trending(self):
            raise RuntimeError("gecko down")

    source = HalfBroken(boosts=[{"chainId": "solana", "tokenAddress": "M9"}],
                        pairs=[dex_pair(mint="M9", pool="P9")])
    found = await BreakoutUniverse.gather(BreakoutUniverse(None, source))  # type: ignore[arg-type]
    assert [c.mint for c in found] == ["M9"]


async def test_the_gather_stops_paging_after_a_failed_page() -> None:
    class BreakOnTwo(FakeSource):
        async def gecko_pools(self, page):
            if page == 2:
                raise RuntimeError("429 storm")
            return await super().gecko_pools(page)

    source = BreakOnTwo(pages={1: gecko_body(gecko_pool(mint="M1", pool="P1"))})
    await BreakoutUniverse.gather(BreakoutUniverse(None, source))  # type: ignore[arg-type]
    assert [c for c in source.calls if c[0] == "pools"] == [("pools", 1)]
