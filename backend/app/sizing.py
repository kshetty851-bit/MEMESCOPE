"""Position size that grows with the account.

One rule, one place, because it governs both the Strategy Lab's twenty virtual
portfolios and the real wallet, and two copies of a sizing rule is two rules
the moment somebody edits one of them.

THE RULE, as specified: a wallet that has doubled trades double the size. A
$100 portfolio stakes its base size until it reaches $200, twice that from
$200, four times from $400, eight times from $800, and so on.

    equity        multiplier
    <   2x base        1x
    >=  2x base        2x
    >=  4x base        4x
    >=  8x base        8x

WHY IT SCALES BOTH WAYS. The rule was given as a way UP and says nothing about
the way down, so the choice is made here and stated rather than buried: the
multiplier is read from equity as it stands right now, not from the highest
equity ever reached.

A ratchet — size that only ever climbs — is the version that ruins accounts. A
portfolio that runs $100 -> $200 -> $100 would come back down still staking the
doubled size, so it would be betting twice as much of a pot that is no longer
twice as large, and each further round trip would compound that error. Reading
current equity means the stake rises with the account and falls with it, which
is what "if the amount of the wallet is $200" says on its face.

If the ratchet is genuinely wanted, pass the peak instead of the balance — the
function does not care which number it is handed, and that is the only edit.
"""

from __future__ import annotations

from decimal import Decimal

#: The most the stake may multiply, whatever equity says.
#:
#: A ceiling rather than an open-ended doubling because this multiplies a real
#: order size, and equity is a computed figure: one bad mark on an illiquid
#: position can inflate it. This is the only bound left on that failure since
#: the per-trade cap began scaling with the account, so it is load-bearing.
#:
#: RAISED 6 -> 8 on 2026-08-27, on instruction, and the measurement that argues
#: against going further is recorded here rather than lost. Round-trip cost on
#: live V6-07 candidates, quoted both ways through Jupiter:
#:
#:     $5      1.7 - 2.5%
#:     $100    1.9 - 4.4%
#:     $500    3.0 - 11.8%
#:     $2000   6.9 - 31.6%
#:
#: From a $5 base, 64x is $320 and 256x is $1,280. The first sits where fills
#: are still good; the second is into the range where a single round trip can
#: cost more than a strategy's whole edge. So 8 is headroom, not a target, and
#: the thing that will stop this account is pool depth rather than this number.
#: Raising it further buys permission the market will not honour.
MAX_DOUBLINGS = 8


def growth_multiplier(
    equity: Decimal | None, *, base: Decimal, max_doublings: int = MAX_DOUBLINGS
) -> Decimal:
    """How many times the base stake this account has earned the right to.

    Always at least 1: a drawdown reduces the stake back to base and stops
    there. Shrinking below the starting size is a different rule that nobody
    asked for, and inventing it here would be inventing a strategy.
    """
    if equity is None or base <= 0 or equity < base * 2:
        return Decimal(1)

    # Integer doubling rather than a logarithm: exact in Decimal, with no
    # float rounding to put an account on the wrong rung at the boundary.
    multiplier = Decimal(1)
    threshold = base * 2
    for _ in range(max_doublings):
        if equity < threshold:
            break
        multiplier *= 2
        threshold *= 2
    return multiplier


def scaled(amount: Decimal, multiplier: Decimal, *, cap: Decimal | None = None) -> Decimal:
    """Apply the multiplier, and let a hard cap win.

    `cap` is a safety bound — a maximum trade size, an exposure ceiling — and
    those exist to bound the blast radius of a mistake. A growth rule that
    could raise its own ceiling would not be a bound at all, so the cap is
    applied last and always wins.
    """
    grown = amount * multiplier
    return min(grown, cap) if cap is not None else grown


def linear_multiplier(
    equity: Decimal | None, *, base: Decimal, cap_multiple: Decimal
) -> Decimal:
    """Stake a fixed FRACTION of the wallet, capped.

    The rule as given: a $100 wallet stakes $10 a position, a $200 wallet $20,
    a $300 wallet $30, and the stake stops growing at $100 once the wallet
    reaches $1,000. That is simply "one tenth of the balance, capped" — so the
    multiplier is the ratio of equity to the starting balance, bounded above.

    DIFFERENT FROM `growth_multiplier`, and deliberately so. The doubling
    ladder jumps 1x -> 2x -> 4x at powers of two, so a $300 wallet still
    stakes $20 under it; here it stakes $30. Straight proportion is what was
    asked for and it is also the gentler rule — the ladder doubles the stake
    the instant equity crosses a threshold, which is the largest step change
    an account takes, and it takes it at exactly the moment a single good mark
    could have caused the crossing.

    IT SCALES DOWN AS WELL AS UP, for the reason the module docstring gives:
    a stake that only ratchets up keeps betting a doubled size out of a pot
    that is no longer doubled. Proportion of the CURRENT balance is the whole
    idea, and it is symmetric by construction.
    """
    if equity is None or base <= 0:
        return Decimal(1)
    if equity <= 0:
        return Decimal(0)
    return min(equity / base, cap_multiple)
