with open("app/paper/strategy.py", "r") as f:
    content = f.read()

# I will find the end of ActivatedTrailingStrategy or TrackRecordBracketStrategy to insert TrailingStopStrategyV2
import re

v2_class = """
@dataclass(frozen=True, slots=True)
class TrailingStopStrategyV2:
    \"\"\"Equal weight in, trailing stop out, and a strict time stop. **The V2 strategy.**\"\"\"

    id: str
    name: str
    version: str
    trade_size_usd: Decimal
    trailing_drawdown: Decimal
    hold_for: timedelta
    min_liquidity_usd: Decimal
    top_n: int | None = None
    operational: bool = True
    unavailable_reason: str | None = None

    @property
    def spec(self) -> StrategySpec:
        return self.describe()

    @property
    def exit_rules(self) -> ExitRules:
        return ExitRules(
            trailing_drawdown=self.trailing_drawdown,
            hold_for=self.hold_for,
        )

    def describe(self) -> StrategySpec:
        back = self.trailing_drawdown * 100
        hours = int(self.hold_for.total_seconds() // 3600)
        return StrategySpec(
            id=self.id,
            name=self.name,
            version=self.version,
            summary=(
                f"Buys ${self.trade_size_usd:,.0f} of the highest-ranked eligible "
                f"token on the Radar (min liquidity ${self.min_liquidity_usd:,.0f}), "
                "and sells it once the price has given back "
                f"{back:.0f}% of the highest level seen, or after {hours} hours - whichever happens first."
            ),
            rules=(
                Rule("Allocation", "Equal weight"),
                Rule("Trade size", f"${self.trade_size_usd:,.0f}"),
                Rule("Liquidity Gate", f"Minimum ${self.min_liquidity_usd:,.0f} verifiable liquidity"),
                Rule(
                    "Entry",
                    "Highest-ranked eligible token on the Radar, whenever cash allows"
                    if self.top_n is None
                    else f"Highest-ranked eligible token in the Radar top {self.top_n}",
                ),
                Rule("Re-entry", "Never. One position per token, ever."),
                Rule("Take profit", "None"),
                Rule("Fixed stop", "None"),
                Rule("Maximum hold", f"{hours} hours. Time stop is strictly enforced."),
                Rule("Trailing stop", f"-{back:.0f}% from the highest price observed"),
                Rule(
                    "Trailing reference",
                    "The high before the current reading. One snapshot cannot both "
                    "set a new high and fall away from it.",
                ),
                Rule(
                    "Fill assumption",
                    "At the trigger level. A gap below it is not modelled, which "
                    "makes this figure optimistic on a fast fall.",
                ),
                Rule("Discretion", "None. No rule is applied by hand."),
            ),
            operational=self.operational,
            unavailable_reason=self.unavailable_reason,
        )

    def entry_for(
        self, candidate: Candidate, *, cash_available: Decimal, now: datetime
    ) -> Entry | None:
        if not self.operational:
            return None
        if self.top_n is not None and candidate.rank > self.top_n:
            return None
        if candidate.price_usd <= 0:
            return None
        if candidate.liquidity_usd is None or candidate.liquidity_usd < self.min_liquidity_usd:
            return None
        if cash_available < self.trade_size_usd:
            return None

        return Entry(
            mint_address=candidate.mint_address,
            price_usd=candidate.price_usd,
            size_usd=self.trade_size_usd,
            quantity=self.trade_size_usd / candidate.price_usd,
            opened_at=now,
            expires_at=now + self.hold_for,
            trailing_drawdown=self.trailing_drawdown,
            market_cap=candidate.market_cap,
            liquidity_usd=candidate.liquidity_usd,
        )
"""

content = content.replace("class ActivatedTrailingStrategy:", v2_class + "\n\n@dataclass(frozen=True, slots=True)\nclass ActivatedTrailingStrategy:")

# Now replace TRAILING_STOP_25_V1 operational=False
content = content.replace(
    "trailing_drawdown=Decimal(\"0.25\"),\n    operational=True,",
    "trailing_drawdown=Decimal(\"0.25\"),\n    operational=False,\n    unavailable_reason=\"Retired in favor of V2\",",
)

v2_instance = """
TRAILING_STOP_25_TIME_V2 = TrailingStopStrategyV2(
    id="paper_trailing_stop_25_time_v2",
    name="Trailing Stop 25% + 24h",
    version="2.0.0",
    trade_size_usd=Decimal(100),
    trailing_drawdown=Decimal("0.25"),
    hold_for=timedelta(hours=24),
    min_liquidity_usd=Decimal(10000),
    operational=True,
)
"""

content = content.replace("EQUAL_WEIGHT_V1 = FixedSizeStrategy(", v2_instance + "\nEQUAL_WEIGHT_V1 = FixedSizeStrategy(")

content = content.replace("default=TRAILING_STOP_25_V1.id,", "default=TRAILING_STOP_25_TIME_V2.id,")
content = content.replace("TRAILING_STOP_25_V1,\n        EQUAL_WEIGHT_V1,", "TRAILING_STOP_25_V1,\n        TRAILING_STOP_25_TIME_V2,\n        EQUAL_WEIGHT_V1,")
content = content.replace("TrailingStopStrategy\n    | ActivatedTrailingStrategy", "TrailingStopStrategy\n    | TrailingStopStrategyV2\n    | ActivatedTrailingStrategy")

with open("app/paper/strategy.py", "w") as f:
    f.write(content)
