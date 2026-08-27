"""STRATEGY LAB — research infrastructure. **No capital execution, ever.**

Strategy Lab replays many strategy definitions against one canonical stream of
token opportunities so they can be compared on identical evidence. It is not a
wallet. It opens no paper position, holds no lineage, signs nothing.

The isolation is structural, not a convention:

  * Its own tables (``strategy_lab_*``), models, repository, service and API.
  * It imports ``app.paper.costs`` — a pure execution-cost function — and
    nothing else from the wallets. It imports nothing from ``app.real_wallet``
    at all, and ``tests/unit/test_strategy_lab_isolation.py`` fails the build
    if that changes.
  * Its state machine has three values and none of them is live. See
    ``LabState``.
"""

from app.strategy_lab.state import LabState

__all__ = ["LabState"]
