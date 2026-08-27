"""What Strategy Lab is allowed to be doing. **There is no live value.**

Declared in its own module so the enum can be imported by the isolation test
without dragging in the service, and so a reader looking for "can this thing
trade" finds the whole answer in twenty lines.
"""

from __future__ import annotations

import enum


class LabState(enum.StrEnum):
    """The complete set. A fourth member would be a design change, not a config."""

    #: Nothing runs. The API answers, and reports itself as disabled.
    DISABLED = "DISABLED"
    #: Historical replay over stored observations, on demand. Reads only.
    BACKTEST = "BACKTEST"
    #: Continuous evaluation of new canonical opportunities as they arrive.
    #: Built and tested; not switched on until it is separately approved.
    FORWARD_RESEARCH = "FORWARD_RESEARCH"
