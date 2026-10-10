"""One sentence per stable code, rendered when a result is READ.

Prose is never stored and never composed on the client (CLAUDE.md): a stored
sentence would freeze today's wording into history, and a client-side one would
let two surfaces drift apart. Stored results hold `{"code": ...}` and nothing
else; `render` adds the `text`. Rewording here is a deploy, not a migration.

Every sentence describes what was OBSERVED or ASSUMED. None says what to do -
the page is research and paper only and must read the same to someone who is
not allowed to trade. `test_forex_prose` holds every sentence to that.

An unknown code renders as itself: a code added to the engine before its prose
should show up as a visible raw code on the page, not as a 500 on the result.
"""

from __future__ import annotations

from typing import Any

TEXT: dict[str, str] = {
    # --- engine assumptions -------------------------------------------------
    "entry_next_bar_open": (
        "A signal is decided at the close of a bar and the trade is entered at the "
        "open of the next bar, never at the close that produced it."
    ),
    "candles_treated_as_mid_spread_symmetric": (
        "Candles are treated as mid prices; half of the configured spread is added "
        "on each side of every fill."
    ),
    "stop_first_when_ambiguous": (
        "When one bar touches both the stop and the target and no 1-minute data can "
        "order them, the stop is taken as hit first and the trade is flagged as ambiguous."
    ),
    "tp_limit_fill_no_slippage": (
        "A take-profit fills at its price with no slippage, as a resting limit order would."
    ),
    "stop_gap_fills_at_open": (
        "A stop that the market gaps through fills at the gapped price, not at the stop price."
    ),
    "rollover_2200_utc_wednesday_triple": (
        "Overnight financing is charged at 22:00 UTC and Wednesday's rollover counts as "
        "three nights. The one-hour shift with US daylight saving is not modelled."
    ),
    "margin_closeout_at_bar_extreme": (
        "Margin close-out is tested at each bar's most adverse price; if equity falls "
        "to the close-out level every position is closed."
    ),
    "leverage_caps_size_not_returns": (
        "Leverage only caps position size. Size comes from the risk per trade and the "
        "stop distance; returns are never the price move multiplied by leverage."
    ),
    # --- skipped signals ----------------------------------------------------
    "direction_disabled": "The signal was on a side the configuration has turned off.",
    "outside_session": "The signal fell outside the configured entry window.",
    "max_open_positions": "The maximum number of open positions was already reached.",
    "max_trades_per_day": "The maximum number of trades for that UTC day was already reached.",
    "daily_loss_limit": "The day's loss limit had been reached, so no new entries were taken.",
    "size_below_minimum": (
        "The position size, from the risk per trade and the stop distance, rounded to "
        "less than the minimum tradable size."
    ),
    "margin_insufficient": "The leverage cap cut the position size below the minimum tradable size.",
    "no_next_bar": "The signal came on the final candle, so there was no next bar to enter on.",
    "gap_before_entry": (
        "The next bar did not follow the signal bar directly (a data gap or the weekend), "
        "so no entry was made."
    ),
    # --- exits and entries --------------------------------------------------
    "stop_loss": "The stop price was reached.",
    "take_profit": "The take-profit price was reached.",
    "session_end": "Closed at the end of the strategy's trading window.",
    "margin_closeout": "Equity fell to the margin close-out level and every position was closed.",
    "end_of_data": "Still open when the candles ran out; closed at the last close and counted.",
    "asian_high_breakout": "A bar closed above the Asian-session high during the London window.",
    "asian_low_breakout": "A bar closed below the Asian-session low during the London window.",
    "rsi_pullback_long": "RSI rose back through the long level while price was above the trend average.",
    "rsi_pullback_short": (
        "RSI fell back through the short level while price was below the trend average."
    ),
    "bb_reentry_long": (
        "Price closed back above the lower Bollinger band after closing below it with RSI oversold."
    ),
    "bb_reentry_short": (
        "Price closed back below the upper Bollinger band after closing above it with RSI overbought."
    ),
    # --- scorecard flags ----------------------------------------------------
    "negative_expectancy": "The average result per trade, in R, was zero or negative over the full period.",
    "insufficient_trades": (
        "Too few trades for the figures to be reliable: under 30 over the full period "
        "or under 15 out of sample."
    ),
    "excessive_drawdown": "The maximum drawdown was more than 30% of equity.",
    "cost_sensitive": (
        "The result fell sharply, or turned negative, when spread, slippage and "
        "commission were doubled."
    ),
    "poor_out_of_sample": (
        "Out-of-sample expectancy was zero or negative, or less than half of the "
        "development figure."
    ),
    "possible_overfitting": (
        "The best parameters sat on an isolated peak, or development results were strong "
        "while out-of-sample results fell away."
    ),
    "not_significant": (
        "The t-statistic of the per-trade results was below 2 or was not computed, so a "
        "true average of zero cannot be ruled out."
    ),
    "no_out_of_sample": "No out-of-sample run was available for this evaluation.",
    # --- verdicts -----------------------------------------------------------
    "candidate_edge": (
        "No warning flags were raised. This describes the historical sample only; it is "
        "not a forecast."
    ),
    "no_edge_detected": (
        "Expectancy was negative or the out-of-sample results did not hold up; no edge "
        "was detected in this sample."
    ),
    "inconclusive": "The evidence is incomplete or flagged; the sample shows no clear result either way.",
    # --- data quality notes -------------------------------------------------
    "weekend_closure_model_fri21_sun22_utc": (
        "Bars between Friday 21:00 and Sunday 22:00 UTC are treated as market closure "
        "and are not counted as missing."
    ),
    "holiday_gaps_not_counted_as_missing": (
        "Gaps touching 25 December or 1 January are treated as holidays and are not "
        "counted as missing."
    ),
    "gaps_truncated_to_largest_50": "Only the 50 most significant gaps are listed.",
    "naive_datetimes_assumed_utc": "Timestamps without a time zone were taken as UTC.",
    "input_not_sorted": "The candles were not in time order.",
    # --- csv import notes ---------------------------------------------------
    "histdata_est_fixed_utc_minus_5": (
        "HistData timestamps are Eastern Standard Time without daylight saving (UTC-5 all "
        "year) and were converted to UTC on that basis."
    ),
    "metatrader_server_time_assumed_utc": (
        "MetaTrader exports use the broker's server time; with no offset given it was taken as UTC."
    ),
    "naive_timestamps_assumed_utc": "The timestamps carried no offset and were taken as UTC.",
    # --- metric notes -------------------------------------------------------
    "no_losses": "There were no losing trades, so the profit factor is not defined.",
    "no_trades": "There were no trades.",
    "insufficient_days": "Fewer than 60 days of data, so the ratio is not reported.",
    "zero_variance": "The values did not vary, so the ratio is not defined.",
    "zero_downside": "There were no down days, so the ratio is not defined.",
    "insufficient_observations": "Fewer than 20 observations, so no confidence interval is given.",
    # --- simulations and targets --------------------------------------------
    "iid_trade_order_shuffle": (
        "Trades are re-ordered at random. The final return is the same on every path, so "
        "only the spread of drawdowns varies."
    ),
    "iid_trade_resampling": "Trades are resampled independently, as if each were unrelated to the last.",
    "fixed_fractional_compounding": (
        "Each trade changes equity by its R-multiple times the risk percent, compounded."
    ),
    "r_multiples_from_history": "Outcomes are drawn from the R-multiples of the historical trades.",
    "historical_average_monthly_trade_count": (
        "Each simulated month contains the historical average number of trades."
    ),
    "historical_observation_not_forecast": (
        "Historical observation, not a forecast. Position size is never increased to reach a target."
    ),
    "no_position_size_increase_to_force_target": (
        "Position size is never increased to reach a target; every simulation uses the "
        "risk per trade the run was made with."
    ),
    "risk_of_ruin_assumes_iid_trades": (
        "The risk-of-ruin figure assumes trades are independent draws from the historical "
        "record; real sequences can cluster."
    ),
    "baseline_stand_aside": "Compared with taking no trades: zero return and zero drawdown.",
    # --- research notes -----------------------------------------------------
    "selection_on_development_only": (
        "Parameters were chosen on the development window only. Validation and test were "
        "then run once with the chosen values and were not used for selection."
    ),
    "no_eligible_parameters_base_config_used": (
        "No parameter set reached the minimum trade count on the development window, so "
        "the submitted configuration was used unchanged."
    ),
    "no_eligible_parameters": (
        "No parameter set reached the minimum trade count in the training window."
    ),
    "no_neighbouring_cells": (
        "The best cell has no neighbouring cells in the grid, so stability could not be assessed."
    ),
    "efficiency_not_meaningful": (
        "Efficiency is not reported: there was no positive in-sample average to compare against."
    ),
    "no_fold_fits_range": (
        "The window is too short for a single walk-forward fold with these train and test lengths."
    ),
    # --- run errors ---------------------------------------------------------
    "no_data_for_range": "No stored candles cover the requested range.",
    "no_candles_in_window": "No candles fall inside one of the windows this run needed.",
    "window_too_short_for_split": (
        "The window is too short to split into development, validation and test periods."
    ),
    "invalid_split_fractions": "The development and validation percentages leave no room for a test period.",
    "end_not_after_start": "The end of the window must be after its start.",
    "interrupted": "The server stopped before this run finished.",
    "market_lacks_trend_timeframe": "The trend timeframe could not be built from the stored candles.",
}

#: The sentence a gap-kind or grade label carries when the page wants one.
LABELS: dict[str, str] = {
    "weekend": "Weekend closure",
    "holiday": "Holiday",
    "missing": "Missing bars",
    "good": "Good",
    "fair": "Fair",
    "poor": "Poor",
    "empty": "No data",
}


def text(code: str) -> str:
    return TEXT.get(code, code)


def error_text(message: str | None) -> str | None:
    """A run's stored error with a known code rendered; anything else verbatim."""
    if message is None:
        return None
    return TEXT.get(message, message)


def render(value: Any) -> Any:
    """A copy of `value` with `text` added to every `{"code": ...}` object.

    Only dicts whose `code` is a string and that carry no `text` yet are
    touched; their other keys (such as `count`) are kept. Everything else is
    copied through unchanged.
    """
    if isinstance(value, dict):
        out = {k: render(v) for k, v in value.items()}
        if isinstance(value.get("code"), str) and "text" not in value:
            out["text"] = text(value["code"])
        return out
    if isinstance(value, list):
        return [render(v) for v in value]
    return value
