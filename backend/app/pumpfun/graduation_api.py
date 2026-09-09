"""The graduation cohort: what happens in the hour after a coin graduates.

Computed server-side so one implementation owns the accounting, and so the page
cannot quietly disagree with a query run by hand.

Two exclusions, both of which change the answer:

* **The cold-start batch.** The collector's very first pass stamped every coin
  that was ALREADY complete. Their stamp is when we started watching, not when
  they graduated — the precise error that made the snapshot version
  unanswerable — so the earliest stamp instant is dropped. Genuine graduations
  trickle in at roughly one every two minutes; the cold start arrived seventy in
  the same second, which is how it is identified.
* **Coins with no graduation market cap.** Nothing can be measured against an
  unknown reference, and substituting a curve-derived estimate would be an
  assumption dressed as an observation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.models.graduation import PumpfunGraduation, PumpfunGraduationMark
from app.models.market import TokenMarketSnapshot
from app.models.token import DiscoveredToken
from app.lab import leaderboard
from app.pumpfun.graduation import TARGET_MINUTES

router = APIRouter(prefix="/pumpfun", tags=["pumpfun"])

DISCLOSURE = (
    "Observation, not a strategy. Every pump.fun coin seen graduating is "
    "stamped at the moment we first observe its bonding curve complete, and "
    "re-read at 5, 15, 30 and 60 minutes. The return shown is what buying at "
    "that stamped market cap and selling at each age would have produced, "
    "before fees and before any price impact — so treat it as an upper bound. "
    "pump.fun publishes no graduation timestamp; this is ours. "
    "Every figure here is a RATIO over the market cap the API reported at the "
    "stamp, and about 9% of those come back far too low — a baseline wrong by "
    "500x invents a 500x winner out of a coin that did nothing. So each "
    "baseline is now checked against our own market snapshot taken within "
    "three minutes, and a coin we cannot corroborate is excluded and counted "
    "rather than repaired. `excluded_bad_baseline` is that count."
)


@router.get("/graduations")
async def graduations(session: DbSession) -> dict[str, Any]:
    cold_start = await session.scalar(
        select(func.min(PumpfunGraduation.first_seen_complete_at))
    )
    base = select(PumpfunGraduation).where(
        PumpfunGraduation.mcap_usd_at_graduation.is_not(None),
        PumpfunGraduation.mcap_usd_at_graduation > 0,
    )
    if cold_start is not None:
        base = base.where(PumpfunGraduation.first_seen_complete_at != cold_start)

    # The cohort is filtered to coins whose baseline our own market series can
    # corroborate. Every figure below is a RATIO over that baseline, so an
    # uncorroborated one does not add noise — it manufactures a winner. See
    # MAX_BASELINE_DISAGREEMENT.
    ours = await _our_mcaps(session)
    everyone = list((await session.execute(base)).scalars())
    cohort = {g.id: g for g in everyone if _baseline_ok(g, ours)}
    dropped_baseline = len(everyone) - len(cohort)
    total_stamped = await session.scalar(
        select(func.count()).select_from(PumpfunGraduation)
    )

    rows = []
    for minutes in TARGET_MINUTES:
        marks = (await session.execute(
            select(PumpfunGraduationMark)
            .where(PumpfunGraduationMark.minutes_since == minutes,
                   PumpfunGraduationMark.mcap_usd.is_not(None))
        )).scalars()
        rets = sorted(
            float(m.mcap_usd / cohort[m.graduation_id].mcap_usd_at_graduation) - 1.0
            for m in marks if m.graduation_id in cohort
        )
        if not rets:
            rows.append({"minutes": minutes, "n": 0})
            continue
        mid = len(rets) // 2
        median = rets[mid] if len(rets) % 2 else (rets[mid - 1] + rets[mid]) / 2
        rows.append({
            "minutes": minutes,
            "n": len(rets),
            # Median first: one glitch cannot move it, and a mean on this
            # population is carried by a handful of survivors.
            "median_pct": round(median * 100, 2),
            "mean_pct": round(sum(rets) / len(rets) * 100, 2),
            "pct_up": round(100.0 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "worst_pct": round(rets[0] * 100, 2),
            "best_pct": round(rets[-1] * 100, 2),
        })

    return {
        "disclosure": DISCLOSURE,
        "cohort": len(cohort),
        "total_stamped": total_stamped or 0,
        "excluded_cold_start": (total_stamped or 0) - len(cohort) - dropped_baseline,
        # Coins whose API baseline our own market series contradicted. Reported
        # rather than folded into the cold-start number, because they are a
        # DATA fault and the reader should be able to see it move.
        "excluded_bad_baseline": dropped_baseline,
        "since": cold_start.isoformat() if cold_start else None,
        "ages": rows,
    }


# --------------------------------------------------------------------------
async def _our_mcaps(session) -> dict[str, Decimal]:
    """OUR market cap for each graduation, from the snapshot nearest its stamp.

    One query rather than one per coin: DISTINCT ON keeps the snapshot closest
    in time. Used only to corroborate the API baseline — see
    `MAX_BASELINE_DISAGREEMENT`.
    """
    gap = func.abs(func.extract(
        "epoch", TokenMarketSnapshot.captured_at
        - PumpfunGraduation.first_seen_complete_at))
    return dict((await session.execute(
        select(PumpfunGraduation.mint_address, TokenMarketSnapshot.market_cap)
        .distinct(PumpfunGraduation.mint_address)
        .join(DiscoveredToken,
              DiscoveredToken.mint_address == PumpfunGraduation.mint_address)
        .join(TokenMarketSnapshot,
              TokenMarketSnapshot.token_id == DiscoveredToken.id)
        .where(TokenMarketSnapshot.suspect.is_not(True),
               TokenMarketSnapshot.market_cap.is_not(None),
               TokenMarketSnapshot.market_cap > 0,
               TokenMarketSnapshot.captured_at
               >= PumpfunGraduation.first_seen_complete_at - timedelta(minutes=3),
               TokenMarketSnapshot.captured_at
               <= PumpfunGraduation.first_seen_complete_at + timedelta(minutes=3))
        .order_by(PumpfunGraduation.mint_address, gap)
    )).all())


def _baseline_ok(g, ours: dict[str, Decimal]) -> bool:
    """True when our own market cap agrees with the API's, or is absent.

    Absent is treated as agreeing rather than as failing: a coin we never
    priced is a gap in OUR series, not evidence against the API, and excluding
    on it would quietly drop the thinnest coins — the population these figures
    most need to keep.
    """
    if not g.mcap_usd_at_graduation:
        return True
    # Nonsense both sources agree on is still nonsense, so the floor is checked
    # first and independently of any second opinion.
    if g.mcap_usd_at_graduation < MIN_BASELINE_MCAP:
        return False
    mine = ours.get(g.mint_address)
    if mine is None:
        return True
    hi = max(mine, g.mcap_usd_at_graduation)
    lo = min(mine, g.mcap_usd_at_graduation)
    return lo > 0 and hi / lo <= MAX_BASELINE_DISAGREEMENT


# A simulated $100 book over the same cohort
# --------------------------------------------------------------------------

#: The book, and how it is divided. $10 x 10 means the whole $100 can be at
#: work at once and every position is the same size — no discretion about which
#: coin deserves more, because there is no basis for such a judgement here.
PAPER_BOOK_USD = Decimal("100")
PAPER_POSITION_USD = Decimal("10")
PAPER_MAX_CONCURRENT = 10

#: A multiple above this inside an hour is a corrupt market cap, not a trade.
#: The raw feed produced 11,670x on one coin; left in, it alone would have
#: reported the book turning $100 into six figures. Excluded and COUNTED, never
#: clamped — a clamped glitch is still a number somebody trusts.
PAPER_GLITCH_MULTIPLE = Decimal("100")

#: THE BASELINE MUST AGREE WITH OUR OWN EYES.
#:
#: `mcap_usd_at_graduation` is whatever pump.fun's API returned at the moment we
#: stamped the coin, and it is the DENOMINATOR of every multiple on this page.
#: It is usually right — against our own snapshot taken within three minutes the
#: median ratio is 1.01 — but roughly 9% of rows come back far too low, and a
#: baseline that is too low by 500x manufactures a 500x winner out of a coin
#: that did nothing.
#:
#: Measured on 2026-09-08: of 523 graduations in twelve hours, 48 disagreed with
#: our own market cap by more than 5x. Among the 78 coins the Graduation Hold
#: Lab actually traded, EVERY replayed multiple above 2x was also above 100x —
#: six unrelated coins all "graduating" at about $2,884 while our snapshots put
#: them near $47,000 — and the lab, pricing the same coins from the same series,
#: recorded them flat. There was not one real winner among them.
#:
#: So the baseline is cross-checked against the market series before it is used,
#: exactly as the universe wallet cross-checks a quoted price against a second
#: source. A row we cannot corroborate is EXCLUDED AND COUNTED, never repaired:
#: guessing the denominator would put an invented number into the headline.
MAX_BASELINE_DISAGREEMENT = Decimal("5")

#: AND IT MUST BE A MARKET CAP A POSITION COULD ACTUALLY HAVE ENTERED.
#:
#: Cross-checking two sources catches a baseline that is wrong. It does not
#: catch one that both sources agree is nonsense: on 2026-09-08 a coin was
#: stamped at $0.70 by the API and by our own snapshot alike, and its $12,443
#: mark five minutes later duly reported 17,756x — the single largest "winner"
#: on the page. Among 539 corroborated baselines, 91 sat under $1,000 and 105
#: under $10,000, against a median of $55,660 and a p25 of $29,590.
#:
#: The floor is not a data-quality guess, it is a tradeability fact: $10 cannot
#: be deployed into a coin whose entire market cap is $0.70, so a ratio taken
#: over such a baseline is not a return anybody could have earned. $10,000 is
#: a thousand times the position and still far below the cluster where real
#: graduations sit, so it removes the impossible without touching the real.
MIN_BASELINE_MCAP = PAPER_POSITION_USD * 1000

#: Round-trip execution assumed for the NET figure. Measured from real Jupiter
#: quotes at >= $100k liquidity. A coin at graduation sits in a much thinner
#: pool, so this is a FLOOR on the true cost and the net number is optimistic.
PAPER_EXECUTION_PCT = Decimal("0.0078")


@router.get("/graduations/paper")
async def graduation_paper(session: DbSession) -> dict[str, Any]:
    """What a $100 book would have made buying every graduation and selling at
    a fixed age — simulated over the cohort we actually stamped.

    NOT a lab. Nothing is traded; this replays the collected marks under one
    rule, so it cannot drift from the data it describes.

    Every exclusion is reported rather than silently dropped, because a
    backtest that quietly discards what it cannot price reports the survivors
    as if they were the population — which is the single error that has made
    every previous result on this platform look better than it was.
    """
    cold_start = await session.scalar(
        select(func.min(PumpfunGraduation.first_seen_complete_at))
    )
    rows = list((await session.execute(
        select(PumpfunGraduation)
        .where(PumpfunGraduation.mcap_usd_at_graduation.is_not(None),
               PumpfunGraduation.mcap_usd_at_graduation > 0,
               PumpfunGraduation.first_seen_complete_at != cold_start)
        .order_by(PumpfunGraduation.first_seen_complete_at)
    )).scalars())

    marks: dict[tuple, Decimal] = {}
    for m in (await session.execute(
        select(PumpfunGraduationMark)
        .where(PumpfunGraduationMark.mcap_usd.is_not(None))
    )).scalars():
        marks[(m.graduation_id, m.minutes_since)] = m.mcap_usd

    ours = await _our_mcaps(session)

    horizons = []
    for minutes in TARGET_MINUTES:
        cash = PAPER_BOOK_USD
        equity_realised = Decimal(0)
        open_until: list[datetime] = []
        taken = skipped_capacity = no_mark = glitched = bad_baseline = 0

        multiples: list[Decimal] = []
        for g in rows:
            t0 = g.first_seen_complete_at
            open_until = [t for t in open_until if t > t0]
            if len(open_until) >= PAPER_MAX_CONCURRENT:
                skipped_capacity += 1
                continue
            if not _baseline_ok(g, ours):
                # The denominator disagrees with our own eyes. Counted, never
                # repaired — see MAX_BASELINE_DISAGREEMENT.
                bad_baseline += 1
                continue
            exit_mcap = marks.get((g.id, minutes))
            if exit_mcap is None:
                # Not yet old enough, or unreadable. NOT a zero and not a win.
                no_mark += 1
                continue
            mult = exit_mcap / g.mcap_usd_at_graduation
            if mult > PAPER_GLITCH_MULTIPLE:
                glitched += 1
                continue
            if cash < PAPER_POSITION_USD:
                skipped_capacity += 1
                continue
            cash -= PAPER_POSITION_USD
            proceeds = PAPER_POSITION_USD * mult
            cash += proceeds
            equity_realised += proceeds - PAPER_POSITION_USD
            multiples.append(mult)
            open_until.append(t0 + timedelta(minutes=minutes))
            taken += 1

        # THE SAME BOOK WITH ITS SINGLE BEST TRADE REMOVED.
        #
        # Reported beside the headline, never instead of it, because on this
        # population they disagree completely: at 15 minutes the book reads
        # +$82 and one coin doing 14.4x IS that entire result — remove it and
        # the same book reads -$51. A strategy whose whole outcome is one trade
        # has not been shown to work; it has been shown to have had a trade.
        # Every false edge on this platform has had exactly this shape.
        without_best = PAPER_BOOK_USD
        if multiples:
            trimmed = list(multiples)
            trimmed.remove(max(trimmed))
            for mult in trimmed:
                without_best += PAPER_POSITION_USD * (mult - 1)
            cost_trimmed = (PAPER_POSITION_USD * PAPER_EXECUTION_PCT
                            * Decimal(len(trimmed)))
            without_best -= cost_trimmed

        gross = cash
        # Execution charged on BOTH legs of every trade actually taken.
        cost = PAPER_POSITION_USD * PAPER_EXECUTION_PCT * Decimal(taken)
        horizons.append({
            "minutes": minutes,
            "trades": taken,
            "final_equity_gross": round(gross, 2),
            "final_equity_net": round(gross - cost, 2),
            "pnl_gross": round(gross - PAPER_BOOK_USD, 2),
            "pnl_net": round(gross - PAPER_BOOK_USD - cost, 2),
            "final_equity_without_best": round(without_best, 2),
            "pnl_without_best": round(without_best - PAPER_BOOK_USD, 2),
            "best_trade_multiple": (round(max(multiples), 2) if multiples else None),
            "execution_charged": round(cost, 2),
            "skipped_no_mark_yet": no_mark,
            "skipped_capacity": skipped_capacity,
            "excluded_glitch": glitched,
            # Rows whose API baseline our own market series could not
            # corroborate. Reported beside the result, because a book that
            # quietly drops what it cannot price reports the survivors as if
            # they were the population.
            "excluded_bad_baseline": bad_baseline,
        })

    return leaderboard._jsonable({
        "disclosure": (
            f"Simulated. A ${PAPER_BOOK_USD:.0f} book, ${PAPER_POSITION_USD:.0f} "
            f"per position and at most {PAPER_MAX_CONCURRENT} at once, buying "
            "every graduation we stamped and selling at a fixed age. Nothing "
            "was traded. Entry is our first sighting of the completed curve — "
            "up to a minute after the real graduation — so a fill at that price "
            "is assumed, not demonstrated. Execution is charged at "
            f"{PAPER_EXECUTION_PCT*100:.2f}% round trip, measured on pools at "
            "$100k+ liquidity; a coin at graduation sits in a far thinner pool, "
            "so the net figure is a BEST CASE and the true cost is higher."
        ),
        "book_usd": PAPER_BOOK_USD,
        "position_usd": PAPER_POSITION_USD,
        "max_concurrent": PAPER_MAX_CONCURRENT,
        "cohort": len(rows),
        "horizons": horizons,
    })


# --------------------------------------------------------------------------
# Hourly cycles: buy the hour's graduations, close everything at +60m, compound
# --------------------------------------------------------------------------

#: The exit every position in a round uses. One hour, because the round IS an
#: hour — a position bought at :50 and closed at the boundary would be held ten
#: minutes and reported as an hour, which is a different strategy.
CYCLE_HORIZON_MINUTES = 60


@router.get("/graduations/cycles")
async def graduation_cycles(session: DbSession) -> dict[str, Any]:
    """$100, split equally across everything that graduates in an hour, all of
    it closed at +60m, and whatever comes back is the next hour's stake.

    Compounding is what makes this different from the fixed-size book, and it
    is also what makes it fragile: one hour that multiplies the balance lifts
    every hour after it, so the final figure can be a single round wearing a
    sequence's clothes. `balance_without_best_round` is reported for exactly
    that reason and the page shows both.

    A coin with no +60m mark yet is dropped from its round and counted, never
    treated as flat — an unpriced position is not a break-even one.
    """
    cold_start = await session.scalar(
        select(func.min(PumpfunGraduation.first_seen_complete_at))
    )
    rows = list((await session.execute(
        select(PumpfunGraduation)
        .where(PumpfunGraduation.mcap_usd_at_graduation.is_not(None),
               PumpfunGraduation.mcap_usd_at_graduation > 0,
               PumpfunGraduation.first_seen_complete_at != cold_start)
        .order_by(PumpfunGraduation.first_seen_complete_at)
    )).scalars())

    exits: dict[Any, Decimal] = {
        m.graduation_id: m.mcap_usd
        for m in (await session.execute(
            select(PumpfunGraduationMark).where(
                PumpfunGraduationMark.minutes_since == CYCLE_HORIZON_MINUTES,
                PumpfunGraduationMark.mcap_usd.is_not(None))
        )).scalars()
    }
    ours = await _our_mcaps(session)

    # Bucket by the hour the coin graduated in.
    buckets: dict[datetime, list[PumpfunGraduation]] = {}
    for g in rows:
        hour = g.first_seen_complete_at.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(hour, []).append(g)

    balance = PAPER_BOOK_USD
    rounds: list[dict[str, Any]] = []
    for hour in sorted(buckets):
        coins = buckets[hour]
        usable, no_mark, glitched, bad_baseline = [], 0, 0, 0
        for g in coins:
            ex = exits.get(g.id)
            if ex is None:
                no_mark += 1
                continue
            if not _baseline_ok(g, ours):
                bad_baseline += 1
                continue
            mult = ex / g.mcap_usd_at_graduation
            if mult > PAPER_GLITCH_MULTIPLE:
                glitched += 1
                continue
            usable.append(mult)

        if not usable:
            # Nothing tradeable this hour. The balance sits out; it does not
            # silently grow, and the round is still reported so a reader can
            # see the strategy was idle rather than absent.
            rounds.append({
                "hour": hour.isoformat(), "coins": len(coins), "traded": 0,
                "no_mark": no_mark, "glitched": glitched,
                "bad_baseline": bad_baseline,
                "opened_with": round(balance, 2), "closed_with": round(balance, 2),
                "round_multiple": 1.0,
            })
            continue

        stake = balance / Decimal(len(usable))
        proceeds = sum((stake * m for m in usable), Decimal(0))
        proceeds -= stake * PAPER_EXECUTION_PCT * Decimal(len(usable))
        opened = balance
        balance = proceeds
        rounds.append({
            "hour": hour.isoformat(), "coins": len(coins), "traded": len(usable),
            "no_mark": no_mark, "glitched": glitched,
                "bad_baseline": bad_baseline,
            "stake_each": round(stake, 2),
            "opened_with": round(opened, 2), "closed_with": round(balance, 2),
            "round_multiple": round(balance / opened, 4) if opened > 0 else None,
        })

    # THE SAME SEQUENCE WITHOUT ITS BEST ROUND. Compounding means one hour can
    # carry every hour after it, so a final balance that collapses when the
    # best round is removed is a single hour wearing a sequence's clothes.
    traded_rounds = [r for r in rounds if r["traded"] > 0]
    best_mult = max((Decimal(str(r["round_multiple"])) for r in traded_rounds),
                    default=None)
    without_best = PAPER_BOOK_USD
    dropped = False
    for r in rounds:
        mult = Decimal(str(r["round_multiple"] or 1))
        if not dropped and best_mult is not None and mult == best_mult:
            dropped = True
            continue
        without_best *= mult

    return leaderboard._jsonable({
        "disclosure": (
            f"Simulated. ${PAPER_BOOK_USD:.0f} split equally across every coin "
            "that graduated in an hour, all closed at +60 minutes, and whatever "
            "came back staked on the next hour. Nothing was traded. Entry is our "
            "first sighting of the completed curve, so a fill at that price is "
            "assumed rather than demonstrated, and execution is charged at "
            f"{PAPER_EXECUTION_PCT*100:.2f}% round trip — measured on pools at "
            "$100k+ liquidity, which a coin at graduation is not, so the result "
            "is a BEST CASE."
        ),
        "start_usd": PAPER_BOOK_USD,
        "horizon_minutes": CYCLE_HORIZON_MINUTES,
        "rounds_total": len(rounds),
        "rounds_traded": len(traded_rounds),
        "final_balance": round(balance, 2),
        "final_balance_without_best_round": round(without_best, 2),
        "best_round_multiple": (round(best_mult, 3) if best_mult else None),
        "rounds": rounds,
    })
