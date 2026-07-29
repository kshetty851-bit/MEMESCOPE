"""Exit signals — detecting when conviction is weakening.

The Radar answers "what is strengthening?". This answers the harder and more
useful question: **"what is quietly rolling over?"**

An entry signal that is never withdrawn is half a product. A platform that only
ever says "this looks good" accumulates a list of past opinions it has no
mechanism to revise, and users learn that the absence of a warning means
nothing.

Deliberately named **Exit Watch**, never "sell". It reports that the evidence
which put a token on the Radar is deteriorating — nothing more. The platform
has no view on anyone's position, cost basis or intent, and a "sell signal"
would claim all three.

Same discipline as `radar` and `services/scoring`: a pure engine with I/O seams,
enforced by `test_exit_signals_purity.py`.
"""
