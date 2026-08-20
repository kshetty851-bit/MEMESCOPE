"""The published strategies.

A strategy is a set of rules a reader can check a trade against. That is the
whole point of the wallet: not "our simulation made 40%", but "this rule, stated
in advance, applied to every token the Radar ranked, produced this". A rule that
lives only in code nobody reads is indistinguishable from a claim.

So every strategy publishes itself — `describe()` returns the rules in the same
words the API serves and the page prints, and a test asserts the published
numbers match the ones the code actually applies. Rewording is a deploy; changing
a threshold is a new **version**, because a strategy whose rules changed
underneath its own track record has no track record.

Pure. No I/O, no clock, no randomness; `now` is a parameter. Strategies are
registered here rather than in a table for the same reason providers are: the
rules *are* the code, and a row that could disagree with the code is a bug
waiting to be believed.

Nothing here recommends anything. A strategy describes what it did, never what a
reader should do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from app.paper.exits import ExitRules
from app.paper.models import Candidate, Entry

#: How many Radar places the retired Equal Weight strategy watched. Published
#: because it was half its entry rule: a token that never reached the top ten
#: was never bought.
DEFAULT_TOP_N = 10


@dataclass(frozen=True, slots=True)
class Rule:
    """One published rule, as a reader sees it."""

    label: str
    value: str


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """A strategy, described for publication.

    `version` is part of the identity. Editing a threshold without bumping it
    would silently re-describe trades that were taken under the old one.
    """

    id: str
    name: str
    version: str
    summary: str
    rules: tuple[Rule, ...]
    #: False when a strategy is declared but not runnable. Published rather than
    #: hidden, so "we have one strategy" and "we have four and run one" are
    #: distinguishable — see `provider_registry`, which does the same.
    operational: bool = True
    unavailable_reason: str | None = None


class Strategy(Protocol):
    """What every strategy must be able to do.

    Deliberately small. A strategy decides **how much to buy** and **where the
    exits sit**; it does not decide *what* to buy, because that is the Radar's
    job and a strategy that re-ranked candidates would be a second, unpublished
    scoring model competing with the one this platform stands behind.
    """

    spec: StrategySpec
    #: The exit rule set, as data. One `exits.resolve` runs every strategy, so
    #: there is exactly one implementation of "which rule closed this and when".
    exit_rules: ExitRules
    #: How many Radar places to watch, or `None` for the whole ranked Radar.
    top_n: int | None

    def describe(self) -> StrategySpec: ...

    def entry_for(
        self, candidate: Candidate, *, cash_available: Decimal, now: datetime
    ) -> Entry | None:
        """The position to open, or `None` when this candidate is not eligible."""
        ...


@dataclass(frozen=True, slots=True)
class FixedSizeStrategy:
    """Equal weight: the same dollar amount into every eligible token.

    The default, and the one the numbers on the page describe. Equal weight is
    chosen because it is the only allocation that cannot flatter the Radar — any
    size that varies with score, confidence or base rate would mix a second
    opinion into a result presented as a test of the first.

    Exits are symmetric multiples of the entry price and an elapsed holding
    period, all fixed at entry. Whichever comes first wins; nothing here waits
    for a better price.
    """

    id: str
    name: str
    version: str
    trade_size_usd: Decimal
    take_profit_multiple: Decimal
    stop_loss_multiple: Decimal
    hold_for: timedelta
    top_n: int = DEFAULT_TOP_N
    operational: bool = True
    unavailable_reason: str | None = None

    @property
    def spec(self) -> StrategySpec:
        return self.describe()

    @property
    def exit_rules(self) -> ExitRules:
        """The bracket, as data for the one shared exit resolver.

        Built from the same three fields `describe()` publishes, so the rule
        that runs and the rule that is printed cannot come apart.
        """
        return ExitRules(
            take_profit_multiple=self.take_profit_multiple,
            stop_loss_multiple=self.stop_loss_multiple,
            hold_for=self.hold_for,
        )

    def describe(self) -> StrategySpec:
        """The rules, in the words the API serves and the page prints.

        Derived from the same fields `entry_for` applies, so the published rule
        and the executed rule cannot drift. A test asserts exactly this.
        """
        gain = (self.take_profit_multiple - 1) * 100
        loss = (1 - self.stop_loss_multiple) * 100
        hours = int(self.hold_for.total_seconds() // 3600)
        return StrategySpec(
            id=self.id,
            name=self.name,
            version=self.version,
            summary=(
                f"Buys ${self.trade_size_usd:,.0f} of a token the first time it "
                f"reaches the Radar's top {self.top_n}, and closes it at "
                f"+{gain:.0f}%, -{loss:.0f}%, or after {hours} hours - whichever "
                "happens first."
            ),
            rules=(
                Rule("Allocation", "Equal weight"),
                Rule("Trade size", f"${self.trade_size_usd:,.0f}"),
                Rule("Entry", f"First time a token enters the Radar top {self.top_n}"),
                Rule("Re-entry", "Never. One position per token, ever."),
                Rule("Take profit", f"+{gain:.0f}%"),
                Rule("Stop loss", f"-{loss:.0f}%"),
                Rule("Maximum hold", f"{hours} hours"),
                Rule("Exit priority", "Whichever rule is breached first"),
                Rule("Discretion", "None. No rule is applied by hand."),
            ),
            operational=self.operational,
            unavailable_reason=self.unavailable_reason,
        )

    def entry_for(
        self, candidate: Candidate, *, cash_available: Decimal, now: datetime
    ) -> Entry | None:
        """Size and bound one entry, or decline it.

        Declines rather than part-fills when cash is short. A wallet that
        quietly halved its size would report a return the published rule did not
        produce, and "we ran out of money" is a real, interesting outcome that
        the equity curve should show rather than absorb.
        """
        if not self.operational:
            return None
        if candidate.rank > self.top_n:
            return None
        if candidate.price_usd <= 0:
            # A token with no positive observed price cannot be sized. It is not
            # free; it is unpriced, and the two must never be confused.
            return None
        if cash_available < self.trade_size_usd:
            return None

        quantity = self.trade_size_usd / candidate.price_usd
        return Entry(
            mint_address=candidate.mint_address,
            price_usd=candidate.price_usd,
            size_usd=self.trade_size_usd,
            quantity=quantity,
            target_price=candidate.price_usd * self.take_profit_multiple,
            stop_price=candidate.price_usd * self.stop_loss_multiple,
            expires_at=now + self.hold_for,
            opened_at=now,
            market_cap=candidate.market_cap,
            liquidity_usd=candidate.liquidity_usd,
        )


@dataclass(frozen=True, slots=True)
class TrailingStopStrategy:
    """Equal weight in, and one trailing stop out. **The published strategy.**

    Sprint 30 relaunched the wallet under a single rule, chosen before the
    relaunch and never revisited after seeing a result. Everything about it is
    mechanical:

    * **Entry** is the highest-ranked eligible token on the Radar, whatever its
      place. Not a top-ten cut — the wallet is meant to stay invested whenever a
      qualified opportunity exists, and a rule that only ever looked at ten rows
      would sit on idle cash the moment those ten had all been traded once.
    * **Size** is the same dollar amount every time. Equal weight is the only
      allocation that cannot flatter the Radar: any size varying with score,
      confidence or base rate mixes a second opinion into a result presented as
      a test of the first.
    * **Exit** is a trailing stop and *nothing else*. No target, no fixed stop,
      no holding period. A position closes when the price has given back a
      published fraction of the highest level observed while it was open.

    The trailing distance is fixed at entry and stored on the position for the
    same reason a target used to be: a distance re-read from configuration after
    the fact could be re-read favourably.

    Two consequences are stated rather than hidden, because both are real:

    * **A position can run indefinitely.** With no expiry, a token that never
      gives back a quarter of its high is never sold, and that capital is not
      available for the next entry. The equity curve shows this; nothing about
      it is smoothed over.
    * **The fill is assumed at the trigger level.** A reading far below the
      trigger closes the position at the trigger, not at the reading. That is
      the frozen convention of the shared resolver, it is optimistic on a gap
      down, and it is published on the strategy card as a rule of its own.
    """

    id: str
    name: str
    version: str
    trade_size_usd: Decimal
    #: Fraction back from the running high that closes a position. 0.25 is 25%.
    trailing_drawdown: Decimal
    #: `None` means the whole ranked Radar, which is what this strategy uses.
    top_n: int | None = None
    #: Longest a position may stay open, or `None` for no time limit.
    #:
    #: Written into the position row at entry as an absolute `expires_at`, so a
    #: later change to this number cannot reach back into a trade already
    #: taken. It is checked **first** by the shared resolver, ahead of every
    #: price rule: at the cutoff the position sells whatever the price is.
    hold_for: timedelta | None = None
    operational: bool = True
    unavailable_reason: str | None = None

    @property
    def spec(self) -> StrategySpec:
        return self.describe()

    @property
    def exit_rules(self) -> ExitRules:
        """The trailing stop, and a holding period when one is published.

        Every other field on `ExitRules` stays `None` — not zero. `resolve`
        skips a rule that is absent, so "no take profit" is expressed as the
        absence of a take profit rather than as a target nothing can reach.
        """
        return ExitRules(
            trailing_drawdown=self.trailing_drawdown, hold_for=self.hold_for
        )

    def describe(self) -> StrategySpec:
        """The rules, in the words the API serves and the page prints."""
        back = self.trailing_drawdown * 100
        hours = (
            None if self.hold_for is None else int(self.hold_for.total_seconds() // 3600)
        )
        return StrategySpec(
            id=self.id,
            name=self.name,
            version=self.version,
            summary=(
                f"Buys ${self.trade_size_usd:,.0f} of the highest-ranked eligible "
                "token on the Radar, and sells it once the price has given back "
                f"{back:.0f}% of the highest level seen since the position opened. "
                "There is no profit target, no fixed stop and no time limit."
                if hours is None
                else (
                    f"Buys ${self.trade_size_usd:,.0f} of the highest-ranked eligible "
                    "token on the Radar, and sells it once the price has given back "
                    f"{back:.0f}% of the highest level seen since the position opened "
                    f"or {hours} hours have elapsed - whichever happens first. There "
                    "is no profit target and no fixed stop."
                )
            ),
            rules=(
                Rule("Allocation", "Equal weight"),
                Rule("Trade size", f"${self.trade_size_usd:,.0f}"),
                Rule(
                    "Entry",
                    "Highest-ranked eligible token on the Radar, whenever cash allows"
                    if self.top_n is None
                    else f"Highest-ranked eligible token in the Radar top {self.top_n}",
                ),
                Rule("Re-entry", "Never. One position per token, ever."),
                Rule("Take profit", "None"),
                Rule("Fixed stop", "None"),
                Rule(
                    "Maximum hold",
                    "None. A position runs until the trailing stop."
                    if hours is None
                    else f"{hours} hours. The position is sold at the next quote "
                    "past the cutoff, at whatever price is executable.",
                ),
                Rule("Trailing stop", f"-{back:.0f}% from the highest price observed"),
                Rule(
                    "Trailing reference",
                    "The high before the current reading. One snapshot cannot both "
                    "set a new high and fall away from it.",
                ),
                Rule(
                    "Fill assumption",
                    "At an executable quote taken when the rule fires, never at "
                    "the trigger level. A gap through the trigger fills below it.",
                ),
                Rule("Discretion", "None. No rule is applied by hand."),
            ),
            operational=self.operational,
            unavailable_reason=self.unavailable_reason,
        )

    def entry_for(
        self, candidate: Candidate, *, cash_available: Decimal, now: datetime
    ) -> Entry | None:
        """Size one entry, or decline it.

        Declines rather than part-fills when cash is short, exactly as the
        retired strategy did: a wallet that quietly halved its size would report
        a return the published rule did not produce, and "there was not enough
        cash for the next one" is a real outcome the equity curve should show.
        """
        if not self.operational:
            return None
        if self.top_n is not None and candidate.rank > self.top_n:
            return None
        if candidate.price_usd <= 0:
            # Unpriced, not free. A position cannot be sized against a price
            # nobody observed, and inventing one would be the estimate this
            # platform refuses to make.
            return None
        if cash_available < self.trade_size_usd:
            return None

        return Entry(
            mint_address=candidate.mint_address,
            price_usd=candidate.price_usd,
            size_usd=self.trade_size_usd,
            quantity=self.trade_size_usd / candidate.price_usd,
            opened_at=now,
            # No target and no stop — two rules this strategy does not have.
            # Left `None` rather than set out of reach, so the position row
            # says "there is no such rule" instead of "the rule is 1,000,000x".
            # `expires_at` follows the same convention: absolute when a holding
            # period is published, absent when there is none. It is written
            # here, at entry, because `_rules_for` reconstructs the rule from
            # the row — a position with no cutoff on it has no cutoff, whatever
            # the registry says later.
            expires_at=None if self.hold_for is None else now + self.hold_for,
            trailing_drawdown=self.trailing_drawdown,
            market_cap=candidate.market_cap,
            liquidity_usd=candidate.liquidity_usd,
        )


@dataclass(frozen=True, slots=True)
class ActivatedTrailingStrategy:
    """$10 paper entries with a 2x activation gate and a 25% trailing exit.

    This deliberately has no price stop or time exit.  Before an observed 2x
    print, a position remains open regardless of drawdown.  At that first 2x
    print the trail becomes active; subsequent observations can only raise its
    high-water mark.  A gap below the theoretical trail closes at the observed
    price, never at an unobserved stop level.
    """

    id: str
    name: str
    version: str
    trade_size_usd: Decimal
    activation_multiple: Decimal
    trailing_drawdown: Decimal
    top_n: int | None = None
    operational: bool = True
    unavailable_reason: str | None = None

    @property
    def spec(self) -> StrategySpec:
        return self.describe()

    @property
    def exit_rules(self) -> ExitRules:
        # Activation is stateful and is evaluated by the paper service from
        # position fields; no ordinary bracket/expiry rule exists here.
        return ExitRules()

    def describe(self) -> StrategySpec:
        return StrategySpec(
            id=self.id,
            name=self.name,
            version=self.version,
            summary=(
                f"Buys ${self.trade_size_usd:,.0f} of every existing paper-qualified "
                "Radar token while cash permits. It has no price stop before an "
                f"observed {self.activation_multiple:g}x gain; after activation it sells "
                f"only after a {self.trailing_drawdown * 100:g}% giveback from the "
                "running observed high."
            ),
            rules=(
                Rule("Allocation", f"${self.trade_size_usd:,.0f} per qualified token"),
                Rule(
                    "Entry",
                    "Existing paper-qualified Radar tokens; scanner qualification unchanged",
                ),
                Rule("Cash rule", "Skip and record INSUFFICIENT_PAPER_CASH below $10"),
                Rule("Re-entry", "Never. One position per token, ever."),
                Rule("Price stop before 2x", "None"),
                Rule(
                    "Trail activation",
                    f"First observed price at or above {self.activation_multiple:g}x entry",
                ),
                Rule(
                    "Trailing stop",
                    f"{self.trailing_drawdown * 100:g}% below the running high "
                    "after activation",
                ),
                Rule(
                    "Gap execution",
                    "Observed trigger price; never an unobserved theoretical stop",
                ),
                Rule(
                    "Maximum hold", "None; terminal/non-trade exits require provider evidence"
                ),
                Rule("Discretion", "None. No rule is applied by hand."),
            ),
            operational=self.operational,
            unavailable_reason=self.unavailable_reason,
        )

    def entry_for(
        self, candidate: Candidate, *, cash_available: Decimal, now: datetime
    ) -> Entry | None:
        if (
            not self.operational
            or (self.top_n is not None and candidate.rank > self.top_n)
            or candidate.price_usd <= 0
            or cash_available < self.trade_size_usd
        ):
            return None
        return Entry(
            mint_address=candidate.mint_address,
            price_usd=candidate.price_usd,
            size_usd=self.trade_size_usd,
            quantity=self.trade_size_usd / candidate.price_usd,
            opened_at=now,
            trailing_drawdown=self.trailing_drawdown,
            trailing_activation_multiple=self.activation_multiple,
            market_cap=candidate.market_cap,
            liquidity_usd=candidate.liquidity_usd,
        )


@dataclass(frozen=True, slots=True)
class TrackRecordBracketStrategy:
    """Forward-only $10 experiment over immutable Track Record admissions.

    The service supplies canonical ``radar_tokens`` rows admitted after the
    wallet watermark.  It does not reproduce or reinterpret Radar's admission
    gates; it only fixes the position size and exit bracket.
    """

    id: str
    name: str
    version: str
    trade_size_usd: Decimal
    take_profit_multiple: Decimal
    stop_loss_multiple: Decimal
    top_n: int | None = None
    operational: bool = True
    unavailable_reason: str | None = None

    @property
    def spec(self) -> StrategySpec:
        return self.describe()

    @property
    def exit_rules(self) -> ExitRules:
        return ExitRules(
            take_profit_multiple=self.take_profit_multiple,
            stop_loss_multiple=self.stop_loss_multiple,
        )

    def describe(self) -> StrategySpec:
        return StrategySpec(
            id=self.id,
            name=self.name,
            version=self.version,
            summary=(
                "Buys $10 of every token admitted to MEMESCOPE Track Record after "
                "this experiment started, subject only to a usable post-admission "
                "observed price and cash. "
                "It takes profit at 1.25x or stops at 0.50x; it has no trailing "
                "or time-based exit."
            ),
            rules=(
                Rule(
                    "Universe", "Every new Track Record admission after the entry watermark"
                ),
                Rule("Allocation", "$10 per token"),
                Rule(
                    "Admission source",
                    "Canonical immutable MEMESCOPE Track Record admission",
                ),
                Rule("Re-entry", "Never. One position or terminal cash decision per token."),
                Rule("Take profit", "1.25x (+25%) from actual entry reference price"),
                Rule("Stop loss", "0.50x (-50%) from actual entry reference price"),
                Rule("Trailing stop", "None"),
                Rule(
                    "Maximum hold",
                    "None; provider terminal handling requires an observed price",
                ),
                Rule(
                    "Gap execution",
                    "Observed triggering price through the paper execution model",
                ),
                Rule("Discretion", "None. No rule is applied by hand."),
            ),
            operational=self.operational,
            unavailable_reason=self.unavailable_reason,
        )

    def entry_for(
        self, candidate: Candidate, *, cash_available: Decimal, now: datetime
    ) -> Entry | None:
        if (
            not self.operational
            or candidate.price_usd <= 0
            or cash_available < self.trade_size_usd
        ):
            return None
        return Entry(
            mint_address=candidate.mint_address,
            price_usd=candidate.price_usd,
            size_usd=self.trade_size_usd,
            quantity=self.trade_size_usd / candidate.price_usd,
            opened_at=candidate.observed_at,
            target_price=candidate.price_usd * self.take_profit_multiple,
            stop_price=candidate.price_usd * self.stop_loss_multiple,
            market_cap=candidate.market_cap,
            liquidity_usd=candidate.liquidity_usd,
        )


#: Restored from its persisted Generation 2 state on 2026-08-16.  The rules and
#: $100 entry size are the original V1 rules; no position is reconstructed.
#:
#: **Retired at the SEC-2 cutover**, and only then: until the cutover runs this
#: is still the operational strategy, and Generation 2 keeps trading under it.
#: See `SECURITY_GATED_STRATEGY_IDS` below for what changes and what does not.
TRAILING_STOP_25_V1 = TrailingStopStrategy(
    id="trailing_stop_25_v1",
    name="Trailing Stop 25%",
    version="1.0.0",
    trade_size_usd=Decimal(100),
    trailing_drawdown=Decimal("0.25"),
    operational=False,
    unavailable_reason=(
        "Retired at the SEC-2 cutover on 2026-08-20. Generation 2's open positions "
        "continue under these exact rules until they close — the rules travel on the "
        "position row, not on the registry — and its record is kept unchanged."
    ),
)

#: SEC-2. **The same strategy, with one added entry precondition.**
#:
#: Deliberately identical in every alpha-bearing respect to
#: `TRAILING_STOP_25_V1`: same $100 equal weight, same 25% trailing stop, same
#: highest-ranked-eligible entry, same absence of a target or a holding period.
#: Nothing about how the wallet chooses, sizes or exits a position changed
#: (§13, §14) — if any of those had moved, a comparison between the two
#: generations would be measuring two things at once and would be worthless.
#:
#: What changed is that a new entry additionally requires every mandatory
#: security check to positively pass on current evidence. The version is
#: `2.0.0-security` rather than a patch bump because the entry precondition is
#: part of the strategy's identity: trades taken under it were drawn from a
#: strictly smaller candidate set, and describing them with the old version
#: would silently re-describe what produced them.
#:
#: **Retired at the HOLD-6H cutover**, for the same reason V1 was retired at
#: this one: its open positions keep its exact rules — no time limit — because
#: the rules travel on the position row, and its record is kept unchanged.
TRAILING_STOP_25_SECURED_V2 = TrailingStopStrategy(
    id="trailing_stop_25_secured_v2",
    name="Trailing Stop 25% (security-gated)",
    version="2.0.0-security",
    trade_size_usd=Decimal(100),
    trailing_drawdown=Decimal("0.25"),
    operational=False,
    unavailable_reason=(
        "Retired at the HOLD-6H cutover on 2026-08-20. Its open positions continue "
        "under these exact rules — including no maximum hold — until they close, "
        "and its record is kept unchanged."
    ),
)

#: HOLD-6H. **The same security-gated strategy, with a maximum holding time.**
#:
#: One rule is added and nothing else moves: same $100 equal weight, same 25%
#: trailing stop, same highest-ranked-eligible entry, same mandatory security
#: precondition. A position now also closes once it has been open six hours,
#: whichever of the two comes first, and it closes at whatever price is
#: executable then — profit or loss, no discretion.
#:
#: Why a maximum hold at all is an empirical question the wallet is being run
#: to answer, not a claim made here. What *is* claimed is the mechanism: an
#: unbounded trailing stop leaves capital inside a position that has stopped
#: moving, and the equity curve showed that as idle money rather than as a
#: decision. The six hours is published as a rule so it can be checked against
#: every trade taken under it.
#:
#: `3.0.0-hold6h` rather than a patch bump for the same reason V2 was not a
#: patch of V1: the exit contract is part of the strategy's identity, and
#: describing these trades with V2's version would silently re-describe what
#: produced them. Capital is inherited along the lineage below, not minted.
TRAILING_STOP_25_SECURED_HOLD6H_V3 = TrailingStopStrategy(
    id="trailing_stop_25_secured_hold6h_v3",
    name="Trailing Stop 25% (security-gated, 6h max hold)",
    version="3.0.0-hold6h",
    trade_size_usd=Decimal(100),
    trailing_drawdown=Decimal("0.25"),
    hold_for=timedelta(hours=6),
    operational=True,
)

#: Strategies that share one pool of capital.
#:
#: ── WHY THIS IS A LINEAGE AND NOT "ALL WALLETS" ──────────────────────────
#:
#: A generation is a policy version; a *lineage* is the chain of policy
#: versions that inherited the same money. Pooling every wallet the platform
#: has ever run would be wrong, and measurably so: generations 1, 3, 4, 5 and
#: 6 were independent experiments that each began with their own $1,000, and
#: Generation 2 has since compounded its own $1,000 through $17,530 of
#: cumulative entries. Summing them against a single $1,000 base yields
#: **-$1,934**, which is not a balance but an artefact of adding six
#: separate experiments together.
#:
#: Each of those wallets also says so itself: every `archive_reason` on record
#: states the wallet is "retained unchanged" and "never mixed into the live
#: wallet's figures". Retroactively pooling them would contradict the recorded
#: intent of the archive.
#:
#: So capital is inherited forward along a lineage. The SEC-2 generation is a
#: policy revision of the trailing-stop strategy — same sizing, same exit,
#: with a security precondition added — so it inherits Generation 2's money
#: rather than minting more. An unrelated future strategy would form its own
#: lineage and would be a deliberate decision to fund something new.
#:
#: Declared in code rather than derived from `archive_reason` text: lineage is
#: a fact about the product, and parsing prose to decide where money lives is
#: the kind of thing that is wrong once and then wrong forever.
CAPITAL_LINEAGES: tuple[frozenset[str], ...] = (
    frozenset(
        {
            "trailing_stop_25_v1",
            "trailing_stop_25_secured_v2",
            "trailing_stop_25_secured_hold6h_v3",
        }
    ),
)


def lineage_for(strategy_id: str) -> frozenset[str]:
    """Every strategy sharing capital with this one, including itself.

    A strategy in no declared lineage funds itself alone, which is the safe
    default: capital is only ever shared where somebody wrote it down.
    """
    for lineage in CAPITAL_LINEAGES:
        if strategy_id in lineage:
            return lineage
    return frozenset({strategy_id})


#: Which strategies enforce the security entry gate.
#:
#: A set rather than a flag on the dataclass, because the gate is a property of
#: the *generation policy* rather than of the trading rules, and because the
#: repository invariant needs to answer "is this wallet gated" without
#: importing the strategy registry into the data layer's hot path.
#:
#: Membership here is what makes `PaperRepository.open_position` refuse to
#: create a position without fresh VERIFIED security evidence, so adding a
#: strategy to this set is the whole of turning enforcement on for it.
#:
#: V2 stays in this set after its retirement. Membership is what makes the
#: repository refuse an unauthorised insert, and a retired wallet must not
#: become *easier* to open a position on than a live one.
SECURITY_GATED_STRATEGY_IDS: frozenset[str] = frozenset(
    {TRAILING_STOP_25_SECURED_V2.id, TRAILING_STOP_25_SECURED_HOLD6H_V3.id}
)

#: **Retired at the Sprint 30 relaunch, and kept because its wallet still
#: exists.** Its trades are a permanent record; an archived wallet has to be
#: able to name the rules that produced them, and a strategy that vanished from
#: the registry would leave a wallet describing itself by an id alone.
#:
#: It does not trade, and there is no way to make it trade: the registry has one
#: operational strategy and there is no selector anywhere in the product.
EQUAL_WEIGHT_V1 = FixedSizeStrategy(
    id="equal_weight_v1",
    name="Equal Weight v1",
    version="1.0.0",
    trade_size_usd=Decimal(100),
    take_profit_multiple=Decimal(2),
    stop_loss_multiple=Decimal("0.5"),
    hold_for=timedelta(hours=48),
    operational=False,
    unavailable_reason=(
        "Retired at the Sprint 30 relaunch. Its wallet is archived and frozen — "
        "the trades it took are kept unchanged for internal comparison and are "
        "never mixed into the live wallet's figures."
    ),
)

PAPER_2X_TRAIL25_V1 = ActivatedTrailingStrategy(
    id="paper_2x_trail25_v1",
    name="Paper 2x Trail 25%",
    version="1.0.0-forward",
    trade_size_usd=Decimal(10),
    activation_multiple=Decimal(2),
    trailing_drawdown=Decimal("0.25"),
    operational=False,
    unavailable_reason="Retired for the all-scanned forward experiment.",
)

PAPER_ALL_SCANNED_TP125_SL50_V1 = TrackRecordBracketStrategy(
    id="paper_all_scanned_tp125_sl50_v1",
    name="All Scanned Tokens TP 1.25x / SL 0.50x",
    version="1.0.0-forward",
    trade_size_usd=Decimal(10),
    take_profit_multiple=Decimal("1.25"),
    stop_loss_multiple=Decimal("0.50"),
    operational=False,
    unavailable_reason="Archived with Generation 5; retained for its immutable record.",
)

PAPER_TRACK_RECORD_TP125_SL50_V1 = TrackRecordBracketStrategy(
    id="paper_track_record_tp125_sl50_v1",
    name="Track Record TP 1.25x / SL 0.50x",
    version="1.0.0-forward",
    trade_size_usd=Decimal(10),
    take_profit_multiple=Decimal("1.25"),
    stop_loss_multiple=Decimal("0.50"),
    operational=False,
    unavailable_reason=(
        "Archived with Generation 6; Generation 2 is the active resumed record."
    ),
)

#: What a wallet may follow. Kept as a Protocol union rather than one class so
#: the archived bracket and the live trailing stop can both be described without
#: one pretending to be the other.
AnyStrategy = (
    FixedSizeStrategy
    | TrailingStopStrategy
    | ActivatedTrailingStrategy
    | TrackRecordBracketStrategy
)


class StrategyRegistry:
    """Every declared strategy, and the one that actually trades.

    Mirrors `opportunities.providers.registry`: declaration is separate from
    operation, so a retired strategy is visible rather than absent.

    **Exactly one strategy is operational, asserted at construction.** Sprint 30
    published a single strategy and removed the selector; a second operational
    entry would be a mode nobody chose, and the failure should happen at import
    rather than as a surprise in a wallet's figures.
    """

    def __init__(self, strategies: tuple[AnyStrategy, ...], *, default: str) -> None:
        self._by_id: dict[str, AnyStrategy] = {
            strategy.id: strategy for strategy in strategies
        }
        if default not in self._by_id:
            raise ValueError(f"default strategy {default!r} is not registered")
        operational = [strategy.id for strategy in strategies if strategy.operational]
        if operational != [default]:
            raise ValueError(
                f"exactly one strategy must be operational and it must be the "
                f"default; found {operational!r} against default {default!r}"
            )
        self._default = default

    def all(self) -> tuple[AnyStrategy, ...]:
        return tuple(self._by_id.values())

    def get(self, strategy_id: str) -> AnyStrategy | None:
        return self._by_id.get(strategy_id)

    @property
    def default(self) -> AnyStrategy:
        return self._by_id[self._default]


registry = StrategyRegistry(
    (
        TRAILING_STOP_25_SECURED_HOLD6H_V3,
        TRAILING_STOP_25_SECURED_V2,
        PAPER_TRACK_RECORD_TP125_SL50_V1,
        PAPER_ALL_SCANNED_TP125_SL50_V1,
        PAPER_2X_TRAIL25_V1,
        TRAILING_STOP_25_V1,
        EQUAL_WEIGHT_V1,
    ),
    default=TRAILING_STOP_25_SECURED_HOLD6H_V3.id,
)
