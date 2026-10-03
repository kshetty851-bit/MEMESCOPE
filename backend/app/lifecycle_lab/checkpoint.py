"""Meme Lifecycle Lab — replay checkpoints and when they may be trusted.

A checkpoint is a ``ReplayState`` (``replay.py``) plus the evidence needed to
decide, later, whether continuing from it is still equivalent to replaying
from scratch. Resuming is valid only if *everything the fold could have seen
at or before* ``processed_until`` is unchanged:

* **the engine** — ``REPLAY_VERSION`` and a hash of the pure engine modules'
  source bytes (``engine_hash``; the service reads the files, this module
  cannot). Either changing means the old state was computed by different code.
* **the configuration and strategy** — the lab config hash and the
  experiment's strategy spec hash.
* **the window** — the replay's ``start`` (the forward epoch).
* **the inputs visible at ``processed_until``** — ``input_watermarks``: per
  meme and per kind of row, ``count`` and the sum of a 60-bit MD5 prefix of a
  canonical row key, over every row whose knowledge time is at or before
  ``processed_until``. A row added, removed or edited with knowledge time
  ``<= processed_until`` changes the count or the sum; a row that becomes
  known later does not, and is exactly what resuming is supposed to pick up.
  Links count when ``linked_at <= processed_until`` (all links under
  hindsight), with ``unlinked_at`` only if it too is ``<= processed_until`` —
  so a link made *now* does not invalidate a checkpoint from an hour ago, but
  a link backdated into the past, or an unlink moved, does.
* **the meme set** — a meme added, archived or removed.

The repository computes the same watermarks in SQL (``count(*)`` and
``sum(md5-prefix)`` per meme and kind), so validation does not load rows; the
row keys below are the contract the SQL must reproduce byte for byte, and an
integration test holds the two together.

Late-arriving rows: the collector stamps ``retrieved_at`` at fetch time and
inserts a little later, so the most recent minutes are not yet settled. The
service never checkpoints closer to ``now`` than ``MLL_CHECKPOINT_SAFETY_LAG``;
a row that still arrives behind a checkpoint changes its watermark, and the
next run replays in full rather than trusting it.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.lifecycle_lab.config import LabConfig
from app.lifecycle_lab.domain import (
    Arm,
    CollectionRun,
    DataClass,
    MarketPoint,
    Meme,
    MemeAlias,
    MemeTokenLink,
    Observation,
    ResearchMode,
    TokenInfo,
)
from app.lifecycle_lab.replay import (
    REPLAY_VERSION,
    ReplayInputs,
    ReplayState,
    config_hash,
    obs_visibility_floor,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_US = timedelta(microseconds=1)

#: The modules whose source decides what a replay computes: the replay, every
#: engine it reaches, and the paper cost model the exits reuse. Their bytes
#: are hashed into ``engine_hash``; ``test_mll_checkpoint`` asserts this list
#: covers replay.py's transitive imports, so a new engine cannot be missed.
ENGINE_MODULES: tuple[str, ...] = (
    "app.lifecycle_lab.attention",
    "app.lifecycle_lab.config",
    "app.lifecycle_lab.divergence",
    "app.lifecycle_lab.domain",
    "app.lifecycle_lab.events",
    "app.lifecycle_lab.exits",
    "app.lifecycle_lab.experiments",
    "app.lifecycle_lab.market",
    "app.lifecycle_lab.metrics",
    "app.lifecycle_lab.pit",
    "app.lifecycle_lab.portfolio",
    "app.lifecycle_lab.replay",
    "app.lifecycle_lab.states",
    "app.lifecycle_lab.strategy",
    "app.paper.costs",
)

#: Watermark key for collection runs that are about no meme and no mint: one
#: sweep speaks for every meme, so it is tracked once.
GLOBAL_KEY = "*"
#: Kinds of row in a meme's watermark.
MEME_KINDS: tuple[str, ...] = ("alias", "link", "market", "meme", "obs", "run", "token")
GLOBAL_KINDS: tuple[str, ...] = ("run",)

VALID = "valid"
#: Watermark kind → the reason code reported when it differs. Ordered by how
#: much it explains: a new link usually also changes market and token rows.
_CAUSES: tuple[tuple[str, str], ...] = (
    ("meme", "meme_changed"),
    ("link", "link_changed"),
    ("alias", "alias_changed"),
    ("token", "token_changed"),
    ("obs", "retroactive_data_changed"),
    ("market", "retroactive_data_changed"),
    ("run", "retroactive_data_changed"),
)

Watermarks = dict[str, dict[str, str]]


# --------------------------------------------------------------------------
# Versions and scope
# --------------------------------------------------------------------------


def engine_hash(sources: Mapping[str, bytes]) -> str:
    """SHA-256 over ``(module name, source bytes)`` in name order."""
    h = hashlib.sha256()
    for name in sorted(sources):
        h.update(name.encode())
        h.update(b"\0")
        h.update(hashlib.sha256(sources[name]).digest())
    return h.hexdigest()


@dataclass(frozen=True, slots=True)
class CheckpointVersions:
    """What produced a state. Any difference means a different computation."""

    replay_version: str
    #: ``engine_hash`` of ``ENGINE_MODULES``.
    engine_hash: str
    #: ``replay.config_hash(cfg, arm)``.
    config_hash: str
    #: The experiment's registered strategy spec hash.
    spec_hash: str


def current_versions(
    *, engine_sources: Mapping[str, bytes], cfg: LabConfig, arm: Arm, spec_hash: str
) -> CheckpointVersions:
    """The versions a checkpoint written now would carry."""
    return CheckpointVersions(
        replay_version=REPLAY_VERSION,
        engine_hash=engine_hash(engine_sources),
        config_hash=config_hash(cfg, arm),
        spec_hash=spec_hash,
    )


@dataclass(frozen=True, slots=True)
class CheckpointScope:
    """One current checkpoint per scope (``mll_replay_checkpoints.scope_key``)."""

    mode: ResearchMode
    arm: Arm
    experiment_id: str
    hindsight_links: bool = False

    def key(self) -> str:
        return (
            f"{self.mode.value}|{self.arm.value}|{self.experiment_id}|"
            f"hindsight={int(self.hindsight_links)}"
        )


@dataclass(frozen=True, slots=True)
class Checkpoint:
    scope: CheckpointScope
    versions: CheckpointVersions
    #: The replay's ``start``.
    window_start: datetime
    #: The last decision tick folded into ``state``.
    processed_until: datetime
    #: ``input_watermarks`` at ``processed_until``.
    input_watermark: Watermarks
    #: ``ReplayState.to_json()``.
    state: Mapping[str, Any] = field(default_factory=dict)


def make_checkpoint(
    *,
    scope: CheckpointScope,
    versions: CheckpointVersions,
    state: ReplayState,
    watermarks: Watermarks,
) -> Checkpoint:
    if state.processed_until is None:
        raise ValueError("a state that has folded no tick is not a checkpoint")
    if state.mode is not scope.mode or state.arm is not scope.arm:
        raise ValueError("state and scope disagree on mode or arm")
    if state.config_hash != versions.config_hash:
        raise ValueError("state was built under another configuration")
    return Checkpoint(
        scope=scope,
        versions=versions,
        window_start=state.start,
        processed_until=state.processed_until,
        input_watermark={m: dict(kinds) for m, kinds in watermarks.items()},
        state=state.to_json(),
    )


def is_valid(
    checkpoint: Checkpoint,
    *,
    current_versions: CheckpointVersions,
    current_watermarks: Watermarks,
    window_start: datetime | None = None,
) -> tuple[bool, str]:
    """``(True, "valid")``, or ``(False, reason)`` with a stable reason code.

    ``current_watermarks`` must be computed at ``checkpoint.processed_until``
    with the same mode, links mode and lower bound as the stored ones.
    """
    old, new = checkpoint.versions, current_versions
    if old.replay_version != new.replay_version:
        return False, "replay_version_changed"
    if old.engine_hash != new.engine_hash:
        return False, "engine_code_changed"
    if old.spec_hash != new.spec_hash:
        return False, "strategy_spec_changed"
    if old.config_hash != new.config_hash:
        return False, "config_changed"
    if window_start is not None and checkpoint.window_start != window_start:
        return False, "window_start_changed"
    stored = checkpoint.input_watermark
    if set(stored) != set(current_watermarks):
        return False, "meme_set_changed"
    for subject in sorted(stored):
        before, now = stored[subject], current_watermarks[subject]
        changed = {k for k in set(before) | set(now) if before.get(k) != now.get(k)}
        if not changed:
            continue
        cause = next((c for kind, c in _CAUSES if kind in changed), "retroactive_data_changed")
        return False, f"{cause}:{subject}:{','.join(sorted(changed))}"
    return True, VALID


# --------------------------------------------------------------------------
# Canonical row keys — the SQL in ``repository.input_watermarks`` must build
# exactly these strings.
# --------------------------------------------------------------------------


def canon_ts(value: datetime | None) -> str:
    """Microseconds since the epoch; ``''`` for None."""
    return "" if value is None else str((value - _EPOCH) // _US)


def canon_num(value: Decimal | int | None) -> str:
    """Plain notation, no trailing fractional zeros (``trim_scale`` in SQL);
    ``''`` for None."""
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def canon_str(value: str | None) -> str:
    return "" if value is None else value


def _join(parts: Iterable[str]) -> str:
    return "|".join(parts)


def meme_key(m: Meme) -> str:
    return _join(
        (
            m.id,
            m.slug,
            m.display_name,
            canon_ts(m.tracking_started_at),
            canon_str(m.wikipedia_title),
            canon_str(m.gdelt_query),
        )
    )


def alias_key(a: MemeAlias) -> str:
    return _join((a.alias, a.kind.value, canon_ts(a.added_at)))


def link_key(link: MemeTokenLink, at: datetime) -> str:
    unlinked = (
        link.unlinked_at if link.unlinked_at is not None and link.unlinked_at <= at else None
    )
    return _join(
        (
            link.mint_address,
            link.method.value,
            canon_num(link.confidence),
            canon_ts(link.linked_at),
            canon_ts(unlinked),
        )
    )


def token_key(t: TokenInfo) -> str:
    return _join(
        (
            t.mint_address,
            canon_str(t.name),
            canon_str(t.symbol),
            canon_ts(t.created_at),
            canon_ts(t.discovered_at),
            canon_str(t.creator_address),
        )
    )


def observation_key(o: Observation) -> str:
    """Every field an engine reads, plus identity. ``raw_payload`` and
    ``source_url`` are provenance, read by no engine, and not covered."""
    return _join(
        (
            o.source.value,
            o.metric.value,
            o.value_kind.value,
            o.data_class.value,
            canon_str(o.meme_id),
            canon_str(o.mint_address),
            canon_str(o.query),
            canon_ts(o.window_start),
            canon_ts(o.window_end),
            canon_ts(o.source_timestamp),
            canon_ts(o.observed_at),
            canon_ts(o.retrieved_at),
            canon_num(o.raw_value),
            canon_num(o.normalized_value),
            canon_num(o.confidence),
        )
    )


def market_key(p: MarketPoint) -> str:
    return _join(
        (
            p.mint_address,
            canon_ts(p.observed_at),
            canon_ts(p.available_at),
            p.data_class.value,
            p.source,
            canon_num(p.price_usd),
            canon_num(p.market_cap),
            canon_num(p.liquidity_usd),
            canon_num(p.volume_5m),
            canon_num(p.volume_1h),
            canon_num(p.volume_24h),
            canon_num(p.buy_count_24h),
            canon_num(p.sell_count_24h),
            canon_num(p.bar_volume),
            canon_num(p.bar_seconds),
        )
    )


def run_key(r: CollectionRun) -> str:
    return _join(
        (
            r.id,
            r.source.value,
            r.status.value,
            r.data_class.value,
            canon_ts(r.started_at),
            canon_ts(r.finished_at),
            canon_str(r.reason),
        )
    )


def row_hash(key: str) -> int:
    """First 60 bits of MD5 — ``('x' || substr(md5(k), 1, 15))::bit(60)::bigint``
    in SQL. Not a security boundary: an edit has to *collide* to slip by."""
    return int(hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()[:15], 16)


def digest_part(count: int, total: int) -> str:
    return f"{count}:{total}"


class _Acc:
    __slots__ = ("count", "total")

    def __init__(self) -> None:
        self.count = 0
        self.total = 0

    def add(self, key: str) -> None:
        self.count += 1
        self.total += row_hash(key)

    def part(self) -> str:
        return digest_part(self.count, self.total)


def input_watermarks(
    inputs: ReplayInputs,
    *,
    at: datetime,
    mode: ResearchMode,
    hindsight_links: bool = False,
    since: datetime | None = None,
) -> Watermarks:
    """The pure reference digest of what was visible at ``at``.

    Membership follows the PIT gate's subject rules (``pit.py``): an
    observation or run about a meme counts for that meme; one about a mint
    counts for every meme with a counted link to the mint; a run about
    neither counts once, under ``GLOBAL_KEY``. Knowledge time is the replay's
    own floor (``replay.obs_visibility_floor``; ``available_at`` for market
    rows; ``finished_at`` for runs). ``since`` mirrors the loader's lower
    bound (``observed_at`` for observations and market rows, ``finished_at``
    for runs). AUTHORITATIVE counts FORWARD rows only, as it admits only them.
    """
    authoritative = mode is ResearchMode.AUTHORITATIVE

    def counted(dc: DataClass) -> bool:
        return not authoritative or dc is DataClass.FORWARD

    meme_ids = sorted({m.id for m in inputs.memes})
    acc: dict[str, dict[str, _Acc]] = {m: {k: _Acc() for k in MEME_KINDS} for m in meme_ids}
    acc[GLOBAL_KEY] = {k: _Acc() for k in GLOBAL_KINDS}

    for m in inputs.memes:
        acc[m.id]["meme"].add(meme_key(m))
    for a in inputs.aliases:
        if a.meme_id in acc and a.meme_id != GLOBAL_KEY and a.added_at <= at:
            acc[a.meme_id]["alias"].add(alias_key(a))

    mints_of: dict[str, set[str]] = {m: set() for m in meme_ids}
    for link in inputs.links:
        if link.meme_id not in mints_of:
            continue
        if hindsight_links or link.linked_at <= at:
            acc[link.meme_id]["link"].add(link_key(link, at))
            mints_of[link.meme_id].add(link.mint_address)
    memes_of_mint: dict[str, list[str]] = {}
    for meme_id, mints in mints_of.items():
        for mint in mints:
            memes_of_mint.setdefault(mint, []).append(meme_id)

    seen_tokens: set[tuple[str, str]] = set()
    for t in inputs.tokens:
        for meme_id in memes_of_mint.get(t.mint_address, ()):
            key = token_key(t)
            if (meme_id, key) in seen_tokens:
                continue
            seen_tokens.add((meme_id, key))
            acc[meme_id]["token"].add(key)

    for o in inputs.observations:
        if not counted(o.data_class) or obs_visibility_floor(o, mode) > at:
            continue
        if since is not None and o.observed_at < since:
            continue
        if o.meme_id is not None:
            targets = [o.meme_id] if o.meme_id in mints_of else []
        else:
            targets = memes_of_mint.get(o.mint_address or "", [])
        if targets:
            key = observation_key(o)
            for meme_id in targets:
                acc[meme_id]["obs"].add(key)

    for p in inputs.market:
        if not counted(p.data_class) or p.available_at > at:
            continue
        if since is not None and p.observed_at < since:
            continue
        targets = memes_of_mint.get(p.mint_address, [])
        if targets:
            key = market_key(p)
            for meme_id in targets:
                acc[meme_id]["market"].add(key)

    for r in inputs.runs:
        if not counted(r.data_class) or r.finished_at > at:
            continue
        if since is not None and r.finished_at < since:
            continue
        if r.meme_id is not None:
            targets = [r.meme_id] if r.meme_id in mints_of else []
        elif r.mint_address is not None:
            targets = memes_of_mint.get(r.mint_address, [])
        else:
            targets = [GLOBAL_KEY]
        if targets:
            key = run_key(r)
            for subject in targets:
                acc[subject]["run"].add(key)

    return {s: {k: a.part() for k, a in kinds.items()} for s, kinds in acc.items()}


def empty_watermarks(meme_ids: Iterable[str]) -> Watermarks:
    """Every subject and kind present with ``0:0`` — the shape the SQL digest
    fills in, so an absent aggregate row and an empty one compare equal."""
    out: Watermarks = {m: dict.fromkeys(MEME_KINDS, digest_part(0, 0)) for m in meme_ids}
    out[GLOBAL_KEY] = dict.fromkeys(GLOBAL_KINDS, digest_part(0, 0))
    return out
