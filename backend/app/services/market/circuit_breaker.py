"""Circuit breaker.

Once a provider has failed repeatedly, continuing to call it wastes the worker's
time and adds load to something already struggling. The breaker trips after N
consecutive failures and fails fast for a cooldown, then admits a single probe
(half-open) and only fully closes after that probe succeeds a few times.

States:

    CLOSED ──failures >= threshold──▶ OPEN ──cooldown elapsed──▶ HALF_OPEN
       ▲                                                            │
       └────────────── successes >= threshold ──────────────────────┘
                                    │
                             any failure ──▶ OPEN
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)


class CircuitState(enum.StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a call is rejected because the breaker is open.

    `retry_after_seconds` is the cooldown still to run. Callers use it to defer
    work by the right amount instead of retrying immediately — without it, a
    rejection costs nothing to produce and the caller spins.
    """

    def __init__(self, message: str, *, retry_after_seconds: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


@dataclass
class CircuitBreaker:
    name: str = "provider"
    failure_threshold: int = 5
    reset_seconds: float = 60.0
    half_open_successes: int = 2

    _state: CircuitState = CircuitState.CLOSED
    _failures: int = 0
    _successes: int = 0
    _opened_at: float = 0.0

    # Injected in tests so cooldown behaviour is deterministic.
    _clock: object = None

    def _now(self) -> float:
        clock = self._clock
        return clock() if callable(clock) else time.monotonic()

    @property
    def state(self) -> CircuitState:
        # Reading the state also performs the OPEN -> HALF_OPEN transition;
        # there is no background timer to do it.
        if (
            self._state is CircuitState.OPEN
            and self._now() - self._opened_at >= self.reset_seconds
        ):
            self._state = CircuitState.HALF_OPEN
            self._successes = 0
            logger.info("circuit_half_open", circuit=self.name)
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._failures

    def allows_request(self) -> bool:
        return self.state is not CircuitState.OPEN

    def ensure_closed(self) -> None:
        """Raise `CircuitOpenError` if calls are currently being rejected."""
        if not self.allows_request():
            remaining = max(0.0, self.reset_seconds - (self._now() - self._opened_at))
            raise CircuitOpenError(
                f"{self.name} circuit is open; retry in {remaining:.1f}s",
                retry_after_seconds=remaining,
            )

    def record_success(self) -> None:
        if self.state is CircuitState.HALF_OPEN:
            self._successes += 1
            if self._successes >= self.half_open_successes:
                self._close()
            return

        self._failures = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        # A failure while probing means the dependency is still unhealthy;
        # go straight back to open rather than burning the rest of the probes.
        if self.state is CircuitState.HALF_OPEN:
            self._open()
            return

        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open()

    def reset(self) -> None:
        self._close()

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._now()
        self._successes = 0
        logger.warning(
            "circuit_opened",
            circuit=self.name,
            failures=self._failures,
            cooldown_seconds=self.reset_seconds,
        )

    def _close(self) -> None:
        was = self._state
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._successes = 0
        if was is not CircuitState.CLOSED:
            logger.info("circuit_closed", circuit=self.name)
