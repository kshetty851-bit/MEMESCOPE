"""Exit signals rendered into English, on the backend.

Sentinel narrates what arrives here; it never composes these sentences. Same
rule as `radar/explain.py`.

The wording is deliberately constrained. Every message describes **what has
already happened to measurable data** — "liquidity has been withdrawn", never
"liquidity will keep falling", and never anything resembling an instruction.
Exit Watch says the evidence is deteriorating; what anyone does about that is
not the platform's to suggest.
"""

from __future__ import annotations

from app.exit_signals.models import ExitSeverity, ExitSignal

SIGNAL_AGENT: dict[ExitSignal, str] = {
    ExitSignal.VOLUME_COLLAPSING: "pulse",
    ExitSignal.LIQUIDITY_LEAVING: "sentinel",
    ExitSignal.TECHNICAL_BREAKDOWN: "oracle",
    ExitSignal.MOMENTUM_ROLLING_OVER: "pulse",
    ExitSignal.CONFIDENCE_DROPPING: "oracle",
    ExitSignal.SELL_PRESSURE_BUILDING: "pulse",
    ExitSignal.PRICE_BELOW_DETECTION: "oracle",
    ExitSignal.SMART_MONEY_DISTRIBUTING: "titan",
    ExitSignal.HOLDER_GROWTH_STALLING: "titan",
}

SIGNAL_LABEL: dict[ExitSignal, str] = {
    ExitSignal.VOLUME_COLLAPSING: "Volume collapsing",
    ExitSignal.LIQUIDITY_LEAVING: "Liquidity leaving",
    ExitSignal.TECHNICAL_BREAKDOWN: "Technical breakdown",
    ExitSignal.MOMENTUM_ROLLING_OVER: "Momentum rolling over",
    ExitSignal.CONFIDENCE_DROPPING: "Confidence dropping",
    ExitSignal.SELL_PRESSURE_BUILDING: "Sell pressure building",
    ExitSignal.PRICE_BELOW_DETECTION: "Below detection price",
    ExitSignal.SMART_MONEY_DISTRIBUTING: "Smart money distributing",
    ExitSignal.HOLDER_GROWTH_STALLING: "Holder growth stalling",
}

SIGNAL_MESSAGE: dict[ExitSignal, str] = {
    ExitSignal.VOLUME_COLLAPSING: (
        "Trading volume has more than halved against its own recent baseline."
    ),
    ExitSignal.LIQUIDITY_LEAVING: (
        "Liquidity has been withdrawn from the pool over the observation window."
    ),
    ExitSignal.TECHNICAL_BREAKDOWN: (
        "Price is well below the high observed during the window."
    ),
    ExitSignal.MOMENTUM_ROLLING_OVER: (
        "The opportunity score has fallen materially from its own peak."
    ),
    ExitSignal.CONFIDENCE_DROPPING: (
        "Confidence has fallen — less of the model applies than it did."
    ),
    ExitSignal.SELL_PRESSURE_BUILDING: "Sells now outnumber buys over the last day.",
    ExitSignal.PRICE_BELOW_DETECTION: (
        "Trading below the price at which the Radar first detected it."
    ),
    ExitSignal.SMART_MONEY_DISTRIBUTING: (
        "Wallet-level distribution is declared but not yet collected."
    ),
    ExitSignal.HOLDER_GROWTH_STALLING: ("Holder growth is declared but not yet collected."),
}

SEVERITY_MESSAGE: dict[ExitSeverity, str] = {
    ExitSeverity.CLEAR: "Nothing measurable is deteriorating.",
    ExitSeverity.WATCH: (
        "Something has started to weaken. One signal is not a conclusion — this "
        "is worth knowing, not worth acting on alone."
    ),
    ExitSeverity.ELEVATED: (
        "Several independent signals are deteriorating together. Much of the "
        "evidence that put this on the Radar no longer holds."
    ),
}

#: Shown wherever Exit Watch appears. The platform has no view on anyone's
#: position, cost basis or intent, and must not imply otherwise.
DISCLAIMER = "Exit Watch reports weakening evidence. It is not a sell signal and not advice."


def render(signal: ExitSignal) -> dict[str, str]:
    return {
        "code": signal.value,
        "label": SIGNAL_LABEL[signal],
        "agent": SIGNAL_AGENT[signal],
        "message": SIGNAL_MESSAGE[signal],
    }
