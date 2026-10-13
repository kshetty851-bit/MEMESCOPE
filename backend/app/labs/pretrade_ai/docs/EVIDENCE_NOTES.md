# Evidence translated into package design

## Source scope A - earlier agreed research

The supplied markdown describes an inspected 901-trade paper ledger at historical $50 sizing and a separate 50-trade real-wallet sample. It reports:

- $50K-<$75K: 159 paper trades, 125 winners, +$446.33 recorded net P&L.
- $75K-<$100K: 15 trades, +$34.65.
- $100K-<$150K: 81 trades, +$36.09.
- $150K-<$200K: 89 trades, -$90.36.
- $200K+: 557 trades, +$102.77.
- All ten largest paper winners entered at $50,975-$57,478 and contributed $269.90.
- A seven-day same-name cooldown removed more winning P&L than losing P&L; it was not creator identity evidence.

These are retrospective fixed-ledger descriptions, not portfolio simulations or forward claims.

## Source scope B - Astra replay dated October 12, 2026

The supplied PDF describes a later 902-trade, $10, cash-limited replay over October 1-12, 2026. It reports:

- Original five-minute control: +$97.81 net, $28.68 maximum drawdown.
- Skip $150K-$200K: +$117.32 net, $30.18 maximum drawdown.
- Only $50K-$100K: +$98.60 net, $18.00 maximum drawdown.
- Only $50K-$75K: +$91.75 net, $18.00 maximum drawdown.
- The corrected -10% stop produced +$91.98 versus the +$97.81 control.
- The report found and corrected look-ahead caused by back-dated DEX Screener rows; decisions must use the time information became available.
- Creator trades and historical size-specific sell quotes were not available for the tested coins, so those rules were not testable.
- Real-wallet results were kept separate from paper results.

The PDF also labels the period short, already inspected, and limited to one market regime.

## Implementation consequences

1. Entry selection is the package's primary function; existing exit behavior remains the comparison control.
2. $50K-$75K receives an evidence-priority liquidity prior, while $150K-$200K is downweighted rather than silently removed.
3. Every feature carries `observed_at`, and validation rejects observations available after `decision_ts`.
4. Creator/funder risk uses full identities, dated linkage, confidence, and prior independently confirmed malicious evidence. Symbol/name repetition is not a feature.
5. Chronological train/validation/test splits use label embargo and group purging. October 1-12, 2026 must remain development evidence.
6. Thresholds are configurable and must be frozen before an untouched test.
7. Backtesting compares identical supplied matched-size entry/exit outcomes and refuses linear P&L resizing.
8. Missing data produces `INSUFFICIENT_DATA` or `untestable`, never an assumed safe zero.
9. The integration layer writes an offline advisory outbox only and cannot execute or modify production.
