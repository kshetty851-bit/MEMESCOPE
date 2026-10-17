"""'Crypto in 60 seconds': written from the data on the page, never beyond it.

Plain sentences built from measured numbers. Moves are described, not explained:
the news that ran alongside a move is offered as context, labelled as such.
"""

from __future__ import annotations

from typing import Any


def _pct(v: float | None) -> str:
    return (
        "flat" if v is None or abs(v) < 0.05 else f"{'up' if v > 0 else 'down'} {abs(v):.1f}%"
    )


def _usd(v: float | None) -> str:
    if v is None:
        return "—"
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= div:
            return f"${v / div:.2f}{unit}"
    return f"${v:,.0f}"


def write(bundle: dict[str, Any]) -> dict[str, Any]:
    m, stories = bundle.get("market"), bundle.get("stories") or []
    what, why, watch = [], [], []
    if m:
        # Bitcoin and Ether lead the ticker and Market Pulse; the briefing starts wider.
        what.append(
            f"The whole market is worth {_usd(m['total_mcap'])}, {_pct(m['mcap_change_24h'])}, "
            f"with {_usd(m['top100_volume'])} traded across the top 100 coins in a day."
        )
        ranked = [
            c for c in m["coins"] if c.get("ch24h") is not None and (c.get("mcap") or 0) > 1e9
        ]
        if ranked:
            up = max(ranked, key=lambda c: c["ch24h"])
            down = min(ranked, key=lambda c: c["ch24h"])
            what.append(
                f"Biggest large-cap move: {up['name']} {_pct(up['ch24h'])}; weakest: {down['name']} {_pct(down['ch24h'])}."
            )
    fg = bundle.get("fear_greed")
    if fg:
        why.append(
            f"Sentiment reads “{fg['label']}” ({fg['value']}/100) on the Fear & Greed index"
            + (
                f", from {fg['yesterday']} yesterday."
                if fg.get("yesterday") is not None
                else "."
            )
        )
    top = bundle.get("lead")
    if top:
        pubs = f"{top['sources']} publishers" if top["sources"] > 1 else top["source"]
        why.append(f"The most-covered story: “{top['title']}” ({pubs}).")
    sec = [s for s in stories[:40] if "security" in s["topics"]]
    if sec:
        why.append(
            f"{len(sec)} security-related stor{'y' if len(sec) == 1 else 'ies'} in today's coverage."
        )
    btcnet = bundle.get("bitcoin_network")
    if btcnet:
        watch.append(
            f"Bitcoin's next difficulty change ({btcnet['difficulty_change_pct']:+.1f}% estimated) "
            f"in {btcnet['difficulty_blocks_left']} blocks."
        )
    ours = bundle.get("ours")
    if ours and ours.get("rug_rate_24h") is not None:
        watch.append(
            f"On pump.fun, {ours['graduations_24h']} coins graduated in 24 hours; "
            f"{ours['rug_rate_24h']}% of those measured lost 80%+ in their first hour (MEMESCOPE data)."
        )
    developing = [s for s in stories[:30] if s["kind"] == "developing"]
    if developing:
        watch.append(f"Still developing: “{developing[0]['title']}”.")
    return {
        "what": what,
        "why": why,
        "watch": watch,
        "note": "Written automatically from the figures and headlines on this page. "
        "Moves are described, not explained: news that ran at the same time is context, not proof of cause.",
    }
