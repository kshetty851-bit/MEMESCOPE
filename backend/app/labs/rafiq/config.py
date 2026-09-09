"""The lab's own configuration. Deliberately NOT `app.core.config`.

Reading its flag from the platform's settings object would mean editing that
object, and the whole premise of this module is that the existing
implementation is untouched. Two environment variables, read directly, with a
default that keeps the lab dark.
"""

from __future__ import annotations

import os
from decimal import Decimal


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


#: The single gate. Off, the runner returns immediately, the routes report the
#: lab as not running, and the nav entry is hidden.
def enabled() -> bool:
    """Read at call time, not at import: a test may flip it, and a worker that
    cached it at import would keep running a lab the operator had turned off."""
    return _flag("RAFIQ_LAB_ENABLED")


#: Each strategy's own book. $1,000, the same figure the Karthik paper wallet
#: started from, so the two columns on the page are comparable without a
#: rebasing step that could be got wrong.
STARTING_EQUITY = Decimal("1000.00")

#: A candidate older than this at the moment the runner sees it is not entered.
#: The strategies are written about fresh admissions; entering a token the beat
#: happened to catch up on hours later would be a different experiment.
MAX_CANDIDATE_AGE_SECONDS = 900

#: Prints this far off the 10-minute rolling median do not fill in either
#: direction, and a level exit never fills better than trigger x this cap.
#: Both guards are mandatory here: this project has twice published a result
#: that a glitch print produced.
GLITCH_BAND = Decimal(3)
FILL_DRIFT_CAP = Decimal("1.15")
#: Nothing is acted on across an observation gap longer than this.
STALE_GUARD_SECONDS = 900
