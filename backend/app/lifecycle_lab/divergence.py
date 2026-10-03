"""Attention/price divergence cases A-E.

Research categories, not signals. No case is ranked above another and none
implies an action; the point of naming them is to measure later which, if any,
carries information.

With ``m`` = attention ``baseline_multiple`` and ``p`` = market ``price_change``
(fractional, over the market feature window):

=====  =========================================  =================================
Case   Attention                                  Price
=====  =========================================  =================================
A      up: ``m >= attention_strong_up``            flat: ``|p| <= price_flat_band``
B      up: ``m >= attention_strong_up``            up: ``price_up < p < price_surge``
C      up: ``m >= attention_strong_up``            surge: ``p >= price_surge``
D      down: ``m <= attention_down``               surge: ``p >= price_surge``
E      strongly down: ``m <= attention_strong_down``  down: ``p <= price_down``
=====  =========================================  =================================

E uses the *strong* attention threshold: a mild drift in both is ordinary
noise, a collapse in both is the case worth naming. Anything else — or any
input Unavailable, or no market at all — is ``NONE``. Evaluation order is the
table order; the thresholds make A-C mutually exclusive and D/E disjoint on
price, so order only matters under a misconfigured band.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from decimal import Decimal

from app.lifecycle_lab.config import EventConfig
from app.lifecycle_lab.domain import AttentionFeatures, DivergenceCase, MarketFeatures


def classify_divergence(
    attention: AttentionFeatures, market: MarketFeatures | None, cfg: EventConfig
) -> DivergenceCase:
    if market is None:
        return DivergenceCase.NONE
    m = attention.baseline_multiple
    p = market.price_change
    if not isinstance(m, Decimal) or not isinstance(p, Decimal):
        return DivergenceCase.NONE

    if m >= cfg.attention_strong_up:
        if abs(p) <= cfg.price_flat_band:
            return DivergenceCase.A_ATTENTION_UP_PRICE_FLAT
        if cfg.price_up < p < cfg.price_surge:
            return DivergenceCase.B_ATTENTION_UP_PRICE_UP
        if p >= cfg.price_surge:
            return DivergenceCase.C_ATTENTION_UP_PRICE_SURGE
        return DivergenceCase.NONE
    if m <= cfg.attention_down and p >= cfg.price_surge:
        return DivergenceCase.D_ATTENTION_DOWN_PRICE_SURGE
    if m <= cfg.attention_strong_down and p <= cfg.price_down:
        return DivergenceCase.E_ATTENTION_DOWN_PRICE_DOWN
    return DivergenceCase.NONE
