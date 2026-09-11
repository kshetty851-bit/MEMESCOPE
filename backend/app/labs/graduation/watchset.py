"""Who is being polled, and when they stop being polled. Pure: no I/O.

Separated from the recorder because this is the part with rules in it, and
rules are worth testing without a socket, a node or a database in the way.
Everything here is a decision about one in-memory dict.

## The three ways out, and why tracked tokens are different

A candidate enters from `subscribeNewToken` — that is the only door, because
the launch feed is the only free source of new mints.

| rule            | applies to        | window                         |
|-----------------|-------------------|--------------------------------|
| `silent`        | **below** 70%     | no reserve movement, SILENT_MIN|
| `evicted`       | **below** 70%     | the set is full; lowest first  |
| `post_migration`| migrated          | POST_MIGRATION_SECONDS         |
| `stale`         | anything          | STALE_HOURS since first seen   |

A TRACKED token — one that has polled at or above the threshold — is never
evicted for silence and never evicted for room. It is the thing the lab
exists to watch, and a curve that parks at 94% for three hours is not a
mistake to be cleaned up; it is the observation. `stale` is the only backstop,
so the set cannot fill with tokens that will never resolve either way.

## Silence is measured on the RESERVES, not on the clock

A poll happens whether or not anybody traded. Measuring silence from the last
POLL would mean every dead token looked permanently alive, and the watch set
would fill with curves nobody has ever bought — which is two thirds of them.
So `last_progress_change_at` moves only when a reserve actually moves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.labs.graduation import config
from app.labs.graduation.models import (
    STATUS_MIGRATED,
    STATUS_TRACKING,
    STATUS_WATCHING,
)
from app.services.curve.state import CurveState

#: What is compared to decide a curve moved. Every reserve, plus the flag:
#: a curve completing is a change even if the reserves were already still.
Fingerprint = tuple[int, int, int, int, bool]


def fingerprint(state: CurveState) -> Fingerprint:
    return (
        state.virtual_token_reserves,
        state.virtual_sol_reserves,
        state.real_token_reserves,
        state.real_sol_reserves,
        state.complete,
    )


@dataclass(slots=True)
class TokenState:
    """What is known about one mint while it is being polled."""

    mint: str
    first_seen_at: datetime
    name: str | None = None
    symbol: str | None = None
    creator: str | None = None
    launch_pool: str | None = None
    bonding_curve_key: str | None = None
    curve_address: str | None = None
    quote_currency: str = config.QUOTE_SOL

    tracked_at: datetime | None = None
    migrated_at: datetime | None = None
    max_progress: Decimal | None = None
    last_progress: Decimal | None = None
    last_progress_change_at: datetime | None = None
    first_sample_at: datetime | None = None
    last_sample_at: datetime | None = None
    sample_count: int = 0
    peak_market_cap_quote: Decimal | None = None
    seen_complete_on_chain: bool = False
    #: The last reserves seen, for change detection. None until first read.
    last_fingerprint: Fingerprint | None = None
    #: Levels already checkpointed, so a retry cannot duplicate one.
    levels_done: set[Decimal] = field(default_factory=set)

    @property
    def tracked(self) -> bool:
        return self.tracked_at is not None

    @property
    def graduated(self) -> bool:
        return self.migrated_at is not None or self.seen_complete_on_chain

    @property
    def status(self) -> str:
        if self.migrated_at is not None:
            return STATUS_MIGRATED
        return STATUS_TRACKING if self.tracked else STATUS_WATCHING

    def observe(self, state: CurveState, progress: Decimal | None,
                now: datetime) -> bool:
        """Fold one poll in. Returns whether anything actually moved.

        The return value drives two things at once — whether a sample row is
        worth writing, and whether the silence timer resets — which is why it
        is one function and one comparison rather than two that could disagree.
        """
        moved = self.last_fingerprint != (current := fingerprint(state))
        self.last_fingerprint = current
        self.first_sample_at = self.first_sample_at or now
        self.last_sample_at = now
        self.sample_count += 1
        if state.complete:
            self.seen_complete_on_chain = True
        if progress is not None:
            self.last_progress = progress
            self.max_progress = (
                progress if self.max_progress is None
                else max(self.max_progress, progress)
            )
            if not self.tracked and progress >= config.TRACK_PROGRESS_PCT:
                self.tracked_at = now
        if moved:
            self.last_progress_change_at = now
        return moved

    def silent_since(self) -> datetime:
        """When this token last did anything. Falls back to first sight, so a
        token that has never been read successfully still ages out."""
        return self.last_progress_change_at or self.first_seen_at


class WatchSet:
    """The mints being polled, and the rules for leaving."""

    def __init__(self, *, max_size: int | None = None) -> None:
        self._max_size = max_size if max_size is not None else config.MAX_WATCH_SET
        self.states: dict[str, TokenState] = {}
        self.admitted = 0
        self.rejected_foreign = 0
        self.rejected_full = 0

    def __len__(self) -> int:
        return len(self.states)

    def __contains__(self, mint: str) -> bool:
        return mint in self.states

    def get(self, mint: str) -> TokenState | None:
        return self.states.get(mint)

    def mints(self) -> list[str]:
        return list(self.states)

    def admit(self, state: TokenState) -> TokenState | None:
        """Add a candidate, evicting for room if need be.

        Returns the state that was EVICTED to make room, or None. Returning the
        victim rather than swallowing it is what lets the caller persist its
        final row — an evicted token that vanished from memory without being
        written would be a token the tables never mention.
        """
        if state.mint in self.states:
            return None
        if state.launch_pool in config.FOREIGN_POOLS:
            # A `bonk` curve has no PDA under the pump.fun program at all, so
            # polling it would read an account that does not exist, for ever.
            self.rejected_foreign += 1
            return None
        evicted = None
        if len(self.states) >= self._max_size:
            evicted = self._evict_lowest()
            if evicted is None:
                # Every slot holds a tracked token. Refuse the newcomer rather
                # than drop something that has already proved interesting.
                self.rejected_full += 1
                return None
        self.states[state.mint] = state
        self.admitted += 1
        return evicted

    def _evict_lowest(self) -> TokenState | None:
        """The least-progressed untracked token, oldest first among equals."""
        candidates = [s for s in self.states.values()
                      if not s.tracked and not s.graduated]
        if not candidates:
            return None
        victim = min(candidates,
                     key=lambda s: (s.last_progress or Decimal(-1), s.first_seen_at))
        return self.states.pop(victim.mint, None)

    def expiry_reason(self, state: TokenState, now: datetime) -> str | None:
        """Why this token should stop being polled, or None."""
        if state.migrated_at is not None:
            elapsed = (now - state.migrated_at).total_seconds()
            return "post_migration" if elapsed >= config.POST_MIGRATION_SECONDS else None
        if now - state.first_seen_at >= timedelta(hours=config.STALE_HOURS):
            # The backstop, and the only rule a tracked token can trip. A curve
            # parked at 94% for a day is not going to resolve.
            return "stale"
        if state.tracked:
            return None
        if now - state.silent_since() >= timedelta(minutes=config.SILENT_MIN):
            return "silent"
        return None

    def sweep(self, now: datetime) -> list[tuple[TokenState, str]]:
        """Remove everything whose window has closed, and hand it back."""
        expired = [(s, r) for s in list(self.states.values())
                   if (r := self.expiry_reason(s, now)) is not None]
        for state, _ in expired:
            self.states.pop(state.mint, None)
        return expired
