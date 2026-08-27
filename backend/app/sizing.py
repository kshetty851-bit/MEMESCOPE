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
#: position can inflate it. Six doublings is 64x, far past the depth these
#: pools support, so the cap can only ever bind on a number that is wrong.
MAX_DOUBLINGS = 6


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
