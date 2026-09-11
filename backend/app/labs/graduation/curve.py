"""How full a bonding curve is, from the account. Pure: no clock, no socket.

## Where the layout comes from

This module does NOT re-implement the account decoder. `app/services/curve/`
already has one that was verified against mainnet, and a second definition of
the same byte layout is a second thing to keep right. So:

* `app.services.curve.pda.bonding_curve_address` derives the PDA;
* `app.services.curve.state.parse` decodes the bytes;
* this module adds the discriminator check that `parse` does not do, and the
  progress arithmetic with the lab's own overridable constants.

`tests/test_curve.py` asserts that this module's progress agrees with
`CurveState.progress` on every level, so the two definitions cannot drift apart
without a test failing.

Verified live on 2026-09-11 against an untouched curve:

    owner        6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P
    length       151 bytes          (ACCOUNT_SIZE 49 is a MINIMUM; `parse`
                                     reads the prefix and ignores the rest)
    discriminator 17b7f83760d8ac60  (== the community decoder's signature)
    v_token      1,073,000,000,000,000
    real_token     793,100,000,000,000
    v_sol             30,000,000,006
    total        1,000,000,000,000,000

The 102 bytes past offset 49 are NOT decoded here. The account has grown since
`state.py` was written and whatever is there is not needed; reading a field
this lab has not verified would be inventing data.

## The arithmetic, and the number the brief got wrong

pump.fun mints 1,000,000,000 tokens and puts 793,100,000 of them on the curve.
The curve account is seeded with a virtual token reserve of 1,073,000,000 — the
793,100,000 for sale plus a 279,900,000 offset that makes the constant product
quote a sane opening price before anyone has bought. In raw base units (6
decimals) those are the three constants in `config`.

    tokens_sold = 1,073,000,000 - virtual_token_reserves
    progress    = tokens_sold / 793,100,000

and the curve completes when the virtual reserve reaches **279,900,000**, not
206,900,000. 206,900,000 is `1,000,000,000 - 793,100,000`: the supply held back
to seed the AMM pool at migration. Those tokens are never in the curve account,
so they can never be "remaining in the curve" — using them as the floor reads a
FULL curve as 91.57% and understates every reading near the top by about eight
points, which is exactly the range this lab exists to measure.

## Why only the token side

A USDC-denominated curve holds USDC in the reserve the SOL field normally
carries. Progress is a pure function of how many TOKENS have left the curve, so
the same expression is correct in both denominations and there is no special
case here. The denomination is recorded beside the reading, not inside it.
"""

from __future__ import annotations

from decimal import Decimal

from app.labs.graduation import config
from app.services.curve.state import CurveState, parse

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)
#: `Numeric(6, 3)` in `models.py`: 0.000 to 100.000.
_PCT_DP = Decimal("0.001")
#: Lamports per SOL, and the same scale the USDC-denominated field uses.
_QUOTE_DECIMALS = 9


def decode(data: bytes | None) -> CurveState | None:
    """A curve account, or None when these bytes are not one.

    The discriminator check is this module's addition: `parse` validates the
    field invariants but never looks at the first eight bytes, so a PDA that
    exists and holds some OTHER Anchor account would decode to five plausible
    integers. Deriving the address does not prove what is stored there.
    """
    if data is None or len(data) < len(config.CURVE_DISCRIMINATOR):
        return None
    if data[:8] != config.CURVE_DISCRIMINATOR:
        return None
    return parse(data)


def curve_floor_tokens() -> Decimal:
    """`virtual_token_reserves` when the curve is exactly full: 279,900,000
    whole tokens, 279,900,000,000,000 raw.

    Derived rather than stored, so it cannot disagree with the two constants it
    comes from.
    """
    return (
        config.INITIAL_VIRTUAL_TOKEN_RESERVES - config.INITIAL_REAL_TOKEN_RESERVES
    )


def progress_pct(
    v_tokens: Decimal | None,
    *,
    pool: str | None = None,
    complete: bool = False,
) -> Decimal | None:
    """How full the curve is, 0.000 to 100.000, or None when unmeasurable.

    `None` and `0` are different claims — one says the curve position is not
    knowable, the other says nobody has bought yet. Only the second is a
    measurement, and every caller here keeps them apart.
    """
    if complete or (pool is not None and pool == config.AMM_POOL):
        return _HUNDRED
    if pool is not None and pool in config.FOREIGN_POOLS:
        # A `bonk` curve is a different curve with different constants, and it
        # has no PDA under the pump.fun program at all.
        return None
    if v_tokens is None:
        return None
    sellable = config.INITIAL_REAL_TOKEN_RESERVES
    if sellable <= 0:  # misconfigured override; refuse rather than divide
        return None
    sold = config.INITIAL_VIRTUAL_TOKEN_RESERVES - v_tokens
    return _clamp(sold / sellable * _HUNDRED)


def progress_pct_from_real(real_tokens: Decimal | None) -> Decimal | None:
    """The same number from `real_token_reserves`.

    This is the definition `app/services/curve/state.py` uses, written once
    here so a join between this lab's rows and the platform's curve snapshots
    is comparing the same quantity.
    """
    if real_tokens is None:
        return None
    sellable = config.INITIAL_REAL_TOKEN_RESERVES
    if sellable <= 0:
        return None
    return _clamp((Decimal(1) - real_tokens / sellable) * _HUNDRED)


def progress_of(state: CurveState | None) -> Decimal | None:
    """Progress of a decoded account — what the poller calls.

    Reads `real_token_reserves`, the field the account actually carries, rather
    than inferring it from the virtual reserve. A completed curve zeroes every
    reserve, so `complete` is checked first or a graduated account would read
    as 100% by luck rather than by statement.
    """
    if state is None:
        return None
    if state.complete:
        return _HUNDRED
    return progress_pct_from_real(Decimal(state.real_token_reserves))


def whole_tokens(raw: Decimal | int | None) -> Decimal | None:
    """Raw base units -> whole tokens. The account counts in base units; the
    sample rows store whole tokens so a human can read them."""
    if raw is None:
        return None
    return Decimal(raw) / (Decimal(10) ** config.TOKEN_DECIMALS)


def quote_reserves(state: CurveState | None) -> tuple[Decimal | None, Decimal | None]:
    """Virtual and real quote reserves, in whole units.

    Named "quote" rather than "sol" because a USDC-denominated curve puts USDC
    in this field. Both denominations carry nine decimals in the account, so
    the division is the same; only the label differs, and the label lives on
    the row.
    """
    if state is None:
        return None, None
    scale = Decimal(10) ** _QUOTE_DECIMALS
    return (Decimal(state.virtual_sol_reserves) / scale,
            Decimal(state.real_sol_reserves) / scale)


def market_cap_quote(state: CurveState | None) -> Decimal | None:
    """Market cap in the quote currency, from the curve's own reserves.

    The constant product prices a token at `virtual_quote / virtual_token`, so
    the whole supply is worth that times `token_total_supply`. Both token
    figures are raw, so their decimals cancel and only the quote's nine remain.

    A completed curve zeroes its reserves, so this is `None` after graduation
    rather than a division by zero — the AMM price is a market question by
    then, and `grad_postgrad_samples` is where it is asked.
    """
    if state is None or state.virtual_token_reserves <= 0:
        return None
    cap = (Decimal(state.virtual_sol_reserves) * Decimal(state.token_total_supply)
           / Decimal(state.virtual_token_reserves) / (Decimal(10) ** _QUOTE_DECIMALS))
    return cap.quantize(Decimal("0.000000001"))


def crossed(previous: Decimal | None, current: Decimal | None,
            level: Decimal) -> bool:
    """True when `current` reaches `level` and `previous` had not.

    `previous is None` counts as not reached: a token first polled at 94% has
    crossed 70, 80 and 90 between two polls, and all three checkpoints are
    owed. Progress is not monotonic — a sell moves it back down — so a token
    that falls under a level and climbs through it again must NOT get a second
    row. The caller passes the highest progress ever seen, not the last one.
    """
    if current is None:
        return False
    return current >= level and (previous is None or previous < level)


def _clamp(pct: Decimal) -> Decimal:
    return min(_HUNDRED, max(_ZERO, pct)).quantize(_PCT_DP)
