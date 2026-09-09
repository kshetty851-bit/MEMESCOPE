"""Rafiq's five strategy files, ported verbatim.

**Nothing in these files was tuned.** The only edits are the module paths on
their import lines, plus the removal of imports that were dead in the
originals — `ruff` fails the build on an unused import, and an unused import is
not logic. Every constant, every threshold, every docstring is Rafiq's.
"""

from app.labs.rafiq.strategies.strategy_a_hard_stop import HARD_STOP_GUARD
from app.labs.rafiq.strategies.strategy_b_time_boxed import TIME_BOXED_EXIT
from app.labs.rafiq.strategies.strategy_e_ensemble import ENSEMBLE_GUARDED

__all__ = ["ENSEMBLE_GUARDED", "HARD_STOP_GUARD", "TIME_BOXED_EXIT"]
