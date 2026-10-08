"""Meme Lifecycle Lab — when a replay checkpoint may be trusted.

A checkpoint is only an optimisation if resuming from it is indistinguishable
from replaying from scratch. That holds exactly when nothing the fold could
have seen at or before ``processed_until`` has changed — the engine, the
configuration, the strategy spec, the window, the meme set, and every row
whose knowledge time is ``<= processed_until``. Each of those is a test here,
paired with its mirror image: the change that must NOT invalidate (a row or
link that became known later is precisely what resuming picks up).

The last tests close the loop: whenever ``is_valid`` says yes, the resumed
result equals the full replay; when a retroactive row arrives, it says no.
"""

from __future__ import annotations

import ast
import importlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.lifecycle_lab import checkpoint as cp
from app.lifecycle_lab.config import LabConfig
from app.lifecycle_lab.domain import (
    AliasKind,
    Arm,
    CollectionRun,
    DataClass,
    LinkMethod,
    MarketPoint,
    Meme,
    MemeAlias,
    MemeTokenLink,
    Metric,
    Observation,
    ResearchMode,
    Source,
    SourceStatus,
    ValueKind,
)
from app.lifecycle_lab.replay import (
    REPLAY_VERSION,
    ReplayInputs,
    ReplayState,
    config_hash,
    resume_replay,
)
from tests.unit.test_mll_incremental import (
    CFG,
    END,
    H0,
    START,
    assert_same,
    full,
    initial,
    world,
)

pytestmark = pytest.mark.unit

AUTH = ResearchMode.AUTHORITATIVE
EXPL = ResearchMode.EXPLORATORY
T = H0 + timedelta(hours=40)
SPEC = "spec-hash-1"
ENGINE = {"app.lifecycle_lab.replay": b"v1"}


@pytest.fixture(scope="module")
def inputs() -> ReplayInputs:
    return world(3)


def versions(cfg: LabConfig = CFG, arm: Arm = Arm.BASELINE) -> cp.CheckpointVersions:
    return cp.current_versions(engine_sources=ENGINE, cfg=cfg, arm=arm, spec_hash=SPEC)


def wm(inputs: ReplayInputs, **kw: object) -> cp.Watermarks:
    args: dict[str, object] = {"at": T, "mode": AUTH}
    args.update(kw)
    return cp.input_watermarks(inputs, **args)  # type: ignore[arg-type]


def checkpoint_of(inputs: ReplayInputs, **kw: object) -> cp.Checkpoint:
    state = _state(inputs)
    return cp.make_checkpoint(
        scope=cp.CheckpointScope(mode=AUTH, arm=Arm.BASELINE, experiment_id="exp-1"),
        versions=versions(),
        state=state,
        watermarks=wm(inputs, at=state.processed_until, **kw),
    )


def _state(inputs: ReplayInputs) -> ReplayState:
    _, state = resume_replay(
        state=initial(inputs),
        inputs=inputs,
        cfg=CFG,
        mode=AUTH,
        arm=Arm.BASELINE,
        end=T + timedelta(minutes=1),
    )
    assert state.processed_until == T
    return state


@pytest.fixture(scope="module")
def checkpoint(inputs: ReplayInputs) -> cp.Checkpoint:
    return checkpoint_of(inputs)


def verdict(checkpoint: cp.Checkpoint, inputs: ReplayInputs, **kw: object) -> tuple[bool, str]:
    return cp.is_valid(
        checkpoint,
        current_versions=versions(),
        current_watermarks=wm(inputs, at=checkpoint.processed_until, **kw),
    )


def gdelt(
    meme_id: str | None, retrieved_at: datetime, value: int = 50, **kw: object
) -> Observation:
    window_end = retrieved_at - timedelta(minutes=2)
    fields: dict[str, object] = {
        "source": Source.GDELT,
        "metric": Metric.MENTIONS,
        "value_kind": ValueKind.WINDOW_COUNT,
        "data_class": DataClass.FORWARD,
        "source_timestamp": window_end - timedelta(minutes=15),
        "observed_at": window_end,
        "retrieved_at": retrieved_at,
        "raw_value": Decimal(value),
        "meme_id": meme_id,
        "window_start": window_end - timedelta(minutes=15),
        "window_end": window_end,
        "query": "late",
    }
    fields.update(kw)
    return Observation(**fields)  # type: ignore[arg-type]


def with_obs(inputs: ReplayInputs, *rows: Observation) -> ReplayInputs:
    return replace(inputs, observations=(*inputs.observations, *rows))


# --------------------------------------------------------------------------
# Baseline
# --------------------------------------------------------------------------


def test_unchanged_inputs_are_valid(checkpoint: cp.Checkpoint, inputs: ReplayInputs) -> None:
    assert verdict(checkpoint, inputs) == (True, "valid")
    assert checkpoint.processed_until == T
    assert ReplayState.from_json(json.loads(json.dumps(checkpoint.state))) == _state(inputs)


def test_watermarks_have_every_subject_and_kind(inputs: ReplayInputs) -> None:
    """Zero is spelled out, so a kind with no rows and an absent aggregate row
    in SQL compare equal."""
    marks = wm(inputs)
    assert set(marks) == {"meme-00", "meme-01", "meme-02", cp.GLOBAL_KEY}
    assert set(cp.empty_watermarks(["meme-00"])["meme-00"]) == set(cp.MEME_KINDS)
    for subject, kinds in marks.items():
        expected = cp.GLOBAL_KINDS if subject == cp.GLOBAL_KEY else cp.MEME_KINDS
        assert set(kinds) == set(expected)
    assert marks["meme-00"]["obs"] != "0:0" and marks["meme-00"]["market"] != "0:0"


def test_the_watermark_depends_only_on_what_was_visible(inputs: ReplayInputs) -> None:
    """Dropping every row known after T leaves the watermark at T unchanged:
    it describes the information set at T, nothing later."""
    known = replace(
        inputs,
        observations=tuple(o for o in inputs.observations if o.retrieved_at <= T),
        market=tuple(p for p in inputs.market if p.available_at <= T),
        runs=tuple(r for r in inputs.runs if r.finished_at <= T),
        links=tuple(k for k in inputs.links if k.linked_at <= T),
    )
    assert wm(known) == wm(inputs)
    assert wm(inputs, at=T + timedelta(hours=1)) != wm(inputs)


# --------------------------------------------------------------------------
# Versions, configuration, window
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"replay_version": "mll-replay-v0"}, "replay_version_changed"),
        ({"engine_hash": "0" * 64}, "engine_code_changed"),
        ({"spec_hash": "spec-hash-2"}, "strategy_spec_changed"),
        ({"config_hash": "f" * 64}, "config_changed"),
    ],
)
def test_any_version_change_invalidates(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs, change: dict[str, str], reason: str
) -> None:
    current = replace(versions(), **change)
    ok, why = cp.is_valid(
        checkpoint,
        current_versions=current,
        current_watermarks=wm(inputs, at=checkpoint.processed_until),
    )
    assert (ok, why) == (False, reason)


def test_a_config_change_changes_the_config_hash() -> None:
    other = replace(CFG, decision_interval=timedelta(minutes=5))
    assert versions(other).config_hash != versions().config_hash
    assert versions(arm=Arm.CONTROL_C_ATTENTION_ONLY).config_hash != versions().config_hash
    assert versions().replay_version == REPLAY_VERSION
    assert versions().config_hash == config_hash(CFG, Arm.BASELINE)


def test_a_moved_window_start_invalidates(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs
) -> None:
    current = wm(inputs, at=checkpoint.processed_until)
    assert cp.is_valid(
        checkpoint, current_versions=versions(), current_watermarks=current, window_start=START
    ) == (True, "valid")
    assert cp.is_valid(
        checkpoint,
        current_versions=versions(),
        current_watermarks=current,
        window_start=START + timedelta(hours=1),
    ) == (False, "window_start_changed")


def test_engine_hash_tracks_names_and_bytes() -> None:
    a = cp.engine_hash({"x": b"1", "y": b"2"})
    assert a == cp.engine_hash({"y": b"2", "x": b"1"})
    assert a != cp.engine_hash({"x": b"1", "y": b"3"})
    assert a != cp.engine_hash({"x": b"1", "z": b"2"})


def _app_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.startswith("app."):
                for alias in node.names:
                    full_name = f"{node.module}.{alias.name}"
                    try:
                        importlib.import_module(full_name)
                        out.add(full_name)
                    except ImportError:
                        out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names if a.name.startswith("app."))
    return out


def test_engine_modules_cover_everything_the_replay_reaches() -> None:
    """An engine edit must change ``engine_hash``. Walk replay.py's imports
    transitively (within app.*) and require every module be hashed."""
    seen: set[str] = set()
    todo = ["app.lifecycle_lab.replay"]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        module = importlib.import_module(name)
        assert module.__file__ is not None
        todo.extend(_app_imports(Path(module.__file__)) - seen)
    assert seen <= set(cp.ENGINE_MODULES), sorted(seen - set(cp.ENGINE_MODULES))


# --------------------------------------------------------------------------
# Meme set and identity
# --------------------------------------------------------------------------


def test_a_new_meme_invalidates(checkpoint: cp.Checkpoint, inputs: ReplayInputs) -> None:
    extra = Meme(id="meme-99", slug="meme-99", display_name="New", tracking_started_at=T)
    grown = replace(inputs, memes=(*inputs.memes, extra))
    assert verdict(checkpoint, grown) == (False, "meme_set_changed")


def test_a_dropped_meme_invalidates(checkpoint: cp.Checkpoint, inputs: ReplayInputs) -> None:
    assert verdict(checkpoint, replace(inputs, memes=inputs.memes[1:])) == (
        False,
        "meme_set_changed",
    )


def test_an_edited_meme_row_invalidates(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs
) -> None:
    memes = (replace(inputs.memes[0], tracking_started_at=H0 + timedelta(hours=1)),)
    ok, why = verdict(checkpoint, replace(inputs, memes=memes + inputs.memes[1:]))
    assert not ok and why.startswith("meme_changed:meme-00")


@pytest.mark.parametrize(("offset", "invalid"), [(-1, True), (1, False)])
def test_an_alias_counts_from_when_it_became_known(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs, offset: int, invalid: bool
) -> None:
    alias = MemeAlias("meme-01", "late", AliasKind.PHRASE, T + timedelta(minutes=offset))
    ok, why = verdict(checkpoint, replace(inputs, aliases=(*inputs.aliases, alias)))
    assert ok is not invalid
    if invalid:
        assert why == "alias_changed:meme-01:alias"


def test_a_token_identity_change_invalidates(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs
) -> None:
    """Token rows are not time-gated (discovered_tokens is mutable), and the
    creation time feeds token age — so any edit to a counted mint's row is
    retroactive."""
    tokens = tuple(
        replace(t, created_at=H0) if t.mint_address == "MINT01A" else t for t in inputs.tokens
    )
    ok, why = verdict(checkpoint, replace(inputs, tokens=tokens))
    assert (ok, why) == (False, "token_changed:meme-01:token")


# --------------------------------------------------------------------------
# Links
# --------------------------------------------------------------------------


def _link(meme: str, mint: str, at: datetime, **kw: object) -> MemeTokenLink:
    return MemeTokenLink(
        meme_id=meme,
        mint_address=mint,
        method=LinkMethod.MANUAL,
        confidence=Decimal("0.9"),
        linked_at=at,
        **kw,  # type: ignore[arg-type]
    )


def test_a_link_backdated_into_the_past_invalidates(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs
) -> None:
    grown = replace(inputs, links=(*inputs.links, _link("meme-02", "MINT00A", T)))
    ok, why = verdict(checkpoint, grown)
    assert not ok and why.startswith("link_changed:meme-02:")
    # The new link also brings the mint's market rows into the meme's set.
    assert "market" in why


def test_a_link_made_after_the_checkpoint_does_not_invalidate(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs
) -> None:
    """A link is a fact with a time: one made now changes nothing about what
    was knowable at processed_until, so resuming is still exact."""
    late = _link("meme-02", "MINT00A", T + timedelta(minutes=1))
    assert verdict(checkpoint, replace(inputs, links=(*inputs.links, late))) == (True, "valid")


def test_under_hindsight_every_link_counts(inputs: ReplayInputs) -> None:
    late = _link("meme-02", "MINT00A", T + timedelta(days=3))
    grown = replace(inputs, links=(*inputs.links, late))
    assert wm(grown, mode=EXPL) == wm(inputs, mode=EXPL)
    assert wm(grown, mode=EXPL, hindsight_links=True) != wm(
        inputs, mode=EXPL, hindsight_links=True
    )


@pytest.mark.parametrize(("offset", "invalid"), [(-1, True), (1, False)])
def test_an_unlink_counts_from_when_it_happened(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs, offset: int, invalid: bool
) -> None:
    links = tuple(
        replace(k, unlinked_at=T + timedelta(minutes=offset))
        if k.mint_address == "MINT02A" and k.meme_id == "meme-02"
        else k
        for k in inputs.links
    )
    ok, why = verdict(checkpoint, replace(inputs, links=links))
    assert ok is not invalid
    if invalid:
        assert why == "link_changed:meme-02:link"


# --------------------------------------------------------------------------
# Retroactive source data
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("offset", "invalid"), [(0, True), (-90, True), (1, False)])
def test_an_observation_counts_from_its_retrieved_at(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs, offset: int, invalid: bool
) -> None:
    """The late-arriving row: retrieved (stamped) at or before the checkpoint
    but inserted after it. The watermark sees it; the next run replays."""
    row = gdelt("meme-01", T + timedelta(minutes=offset))
    ok, why = verdict(checkpoint, with_obs(inputs, row))
    assert ok is not invalid
    if invalid:
        assert why == "retroactive_data_changed:meme-01:obs"


def test_a_removed_or_edited_observation_invalidates(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs
) -> None:
    visible = [
        o for o in inputs.observations if o.retrieved_at <= T and o.meme_id == "meme-00"
    ]
    target = visible[len(visible) // 2]
    removed = replace(
        inputs, observations=tuple(o for o in inputs.observations if o is not target)
    )
    assert verdict(checkpoint, removed) == (False, "retroactive_data_changed:meme-00:obs")
    edited = replace(
        inputs,
        observations=tuple(
            replace(o, raw_value=o.raw_value + 1) if o is target else o
            for o in inputs.observations
        ),
    )
    assert verdict(checkpoint, edited) == (False, "retroactive_data_changed:meme-00:obs")


def test_a_mint_observation_counts_for_every_meme_linked_to_it(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs
) -> None:
    row = gdelt(
        None,
        T - timedelta(minutes=5),
        mint_address="MINT00A",
        source=Source.PUMPFUN_REPLIES,
        metric=Metric.REPLIES_TOTAL,
        value_kind=ValueKind.CUMULATIVE,
    )
    ok, why = verdict(checkpoint, with_obs(inputs, row))
    assert (ok, why) == (False, "retroactive_data_changed:meme-00:obs")


@pytest.mark.parametrize(("offset", "invalid"), [(-1, True), (1, False)])
def test_a_market_reading_counts_from_its_available_at(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs, offset: int, invalid: bool
) -> None:
    at = T + timedelta(minutes=offset)
    point = MarketPoint(
        mint_address="MINT01A",
        observed_at=at - timedelta(seconds=30),
        available_at=at,
        data_class=DataClass.FORWARD,
        price_usd=Decimal("9"),
    )
    ok, why = verdict(checkpoint, replace(inputs, market=(*inputs.market, point)))
    assert ok is not invalid
    if invalid:
        assert why == "retroactive_data_changed:meme-01:market"


def test_an_edited_market_reading_invalidates(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs
) -> None:
    target = next(
        p for p in inputs.market if p.mint_address == "MINT02A" and p.available_at < T
    )
    market = tuple(
        replace(p, volume_1h=Decimal(1)) if p is target else p for p in inputs.market
    )
    ok, why = verdict(checkpoint, replace(inputs, market=market))
    assert (ok, why) == (False, "retroactive_data_changed:meme-02:market")


def test_a_late_collection_run_invalidates_globally_or_per_meme(
    checkpoint: cp.Checkpoint, inputs: ReplayInputs
) -> None:
    def run(**kw: object) -> CollectionRun:
        fields: dict[str, object] = {
            "id": "late-run",
            "source": Source.WIKIPEDIA,
            "status": SourceStatus.ERROR,
            "started_at": T - timedelta(minutes=3),
            "finished_at": T - timedelta(minutes=2),
            "data_class": DataClass.FORWARD,
            "reason": "http_500",
        }
        fields.update(kw)
        return CollectionRun(**fields)  # type: ignore[arg-type]

    sweep = replace(inputs, runs=(*inputs.runs, run()))
    assert verdict(checkpoint, sweep) == (
        False,
        f"retroactive_data_changed:{cp.GLOBAL_KEY}:run",
    )
    mine = replace(inputs, runs=(*inputs.runs, run(meme_id="meme-02")))
    assert verdict(checkpoint, mine) == (False, "retroactive_data_changed:meme-02:run")
    later = replace(inputs, runs=(*inputs.runs, run(finished_at=T + timedelta(minutes=1))))
    assert verdict(checkpoint, later) == (True, "valid")


def test_backfill_counts_only_where_the_mode_admits_it(inputs: ReplayInputs) -> None:
    """AUTHORITATIVE never admits BACKFILL, so a backfill load cannot disturb
    an authoritative checkpoint; EXPLORATORY counts a backfilled row from
    when it was knowable on its timeline."""
    described = T - timedelta(hours=2)
    row = gdelt(
        "meme-01",
        T + timedelta(days=30),
        data_class=DataClass.BACKFILL,
        source_timestamp=described,
        observed_at=described + timedelta(minutes=15),
        window_start=described,
        window_end=described + timedelta(minutes=15),
    )
    grown = with_obs(inputs, row)
    assert wm(grown) == wm(inputs)
    assert wm(grown, mode=EXPL) != wm(inputs, mode=EXPL)
    later = gdelt(
        "meme-01",
        T + timedelta(days=30),
        data_class=DataClass.BACKFILL,
        source_timestamp=T + timedelta(hours=1),
        observed_at=T + timedelta(hours=1),
    )
    assert wm(with_obs(inputs, later), mode=EXPL) == wm(inputs, mode=EXPL)


def test_since_mirrors_the_loaders_lower_bound(inputs: ReplayInputs) -> None:
    old = gdelt("meme-01", H0 - timedelta(days=2))
    assert wm(with_obs(inputs, old), since=H0) == wm(inputs, since=H0)
    assert wm(with_obs(inputs, old)) != wm(inputs)


# --------------------------------------------------------------------------
# Canonical keys (the SQL contract)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("10.00000000"), "10"),
        (Decimal("1E+2"), "100"),
        (Decimal("0E-8"), "0"),
        (Decimal("-1.50"), "-1.5"),
        (Decimal("1.00000000E-10"), "0.0000000001"),
        (Decimal("0.000012345678901234567890"), "0.00001234567890123456789"),
        (7, "7"),
        (None, ""),
    ],
)
def test_canonical_numbers_match_postgres_trim_scale(
    value: Decimal | int | None, text: str
) -> None:
    assert cp.canon_num(value) == text


def test_canonical_timestamps_are_epoch_microseconds() -> None:
    assert cp.canon_ts(H0 + timedelta(microseconds=7)) == str(1785542400 * 10**6 + 7)
    assert cp.canon_ts(None) == ""


def test_row_hash_is_a_60_bit_md5_prefix() -> None:
    h = cp.row_hash("abc")
    assert h == int("900150983cd24fb0d6963f7d28e17f72"[:15], 16)
    assert 0 <= h < 2**60


# --------------------------------------------------------------------------
# The contract end to end: valid ⇒ resuming is exact
# --------------------------------------------------------------------------


def _known_by(inputs: ReplayInputs, t: datetime) -> ReplayInputs:
    return replace(
        inputs,
        observations=tuple(o for o in inputs.observations if o.retrieved_at <= t),
        market=tuple(p for p in inputs.market if p.available_at <= t),
        runs=tuple(r for r in inputs.runs if r.finished_at <= t),
        links=tuple(k for k in inputs.links if k.linked_at <= t),
    )


def _forward_cycle(
    inputs_now: Callable[[datetime], ReplayInputs], first: datetime, second: datetime
) -> tuple[cp.Checkpoint, ReplayInputs]:
    """What the service does at ``first``: replay to now, checkpoint 30 min
    behind it. Returns the checkpoint and the inputs as of ``second``."""
    lag = timedelta(minutes=30)
    seen = inputs_now(first)
    _, state = resume_replay(
        state=initial(seen),
        inputs=seen,
        cfg=CFG,
        mode=AUTH,
        arm=Arm.BASELINE,
        end=first,
        checkpoint_at=first - lag,
    )
    assert state.processed_until is not None
    checkpoint = cp.make_checkpoint(
        scope=cp.CheckpointScope(mode=AUTH, arm=Arm.BASELINE, experiment_id="exp-1"),
        versions=versions(),
        state=state,
        watermarks=cp.input_watermarks(seen, at=state.processed_until, mode=AUTH),
    )
    return checkpoint, inputs_now(second)


def test_when_valid_the_resumed_replay_equals_the_full_replay() -> None:
    inputs = world(3)
    first, second = H0 + timedelta(hours=38, minutes=4), END
    checkpoint, later = _forward_cycle(lambda t: _known_by(inputs, t), first, second)
    ok, why = cp.is_valid(
        checkpoint,
        current_versions=versions(),
        current_watermarks=cp.input_watermarks(
            later, at=checkpoint.processed_until, mode=AUTH
        ),
    )
    assert (ok, why) == (True, "valid")
    resumed, _ = resume_replay(
        state=ReplayState.from_json(checkpoint.state),
        inputs=later,
        cfg=CFG,
        mode=AUTH,
        arm=Arm.BASELINE,
        end=second,
    )
    assert_same(full(later, end=second), resumed)


def test_a_retroactive_row_is_caught_before_it_can_make_a_resume_wrong() -> None:
    """A row stamped before the checkpoint but inserted after it: the resumed
    result would differ from a full replay — and the checkpoint is refused."""
    inputs = world(3)
    first, second = H0 + timedelta(hours=38, minutes=4), END
    late = gdelt("meme-01", H0 + timedelta(hours=33), value=400)

    def known(t: datetime) -> ReplayInputs:
        base = _known_by(inputs, t)
        return base if t < second else with_obs(base, late)

    checkpoint, later = _forward_cycle(known, first, second)
    ok, why = cp.is_valid(
        checkpoint,
        current_versions=versions(),
        current_watermarks=cp.input_watermarks(
            later, at=checkpoint.processed_until, mode=AUTH
        ),
    )
    assert (ok, why) == (False, "retroactive_data_changed:meme-01:obs")
    # And refusing was necessary: trusting it would have given another answer.
    trusted, _ = resume_replay(
        state=ReplayState.from_json(checkpoint.state),
        inputs=later,
        cfg=CFG,
        mode=AUTH,
        arm=Arm.BASELINE,
        end=second,
    )
    assert trusted.to_dict() != full(later, end=second).to_dict()


def test_make_checkpoint_refuses_inconsistent_parts(inputs: ReplayInputs) -> None:
    scope = cp.CheckpointScope(mode=AUTH, arm=Arm.BASELINE, experiment_id="exp-1")
    with pytest.raises(ValueError, match="no tick"):
        cp.make_checkpoint(
            scope=scope, versions=versions(), state=initial(inputs), watermarks={}
        )
    state = _state(inputs)
    with pytest.raises(ValueError, match="mode or arm"):
        cp.make_checkpoint(
            scope=replace(scope, arm=Arm.CONTROL_D_COMBINED),
            versions=versions(),
            state=state,
            watermarks={},
        )
    with pytest.raises(ValueError, match="configuration"):
        cp.make_checkpoint(
            scope=scope,
            versions=versions(arm=Arm.CONTROL_C_ATTENTION_ONLY),
            state=state,
            watermarks={},
        )
    assert scope.key() == f"authoritative|{Arm.BASELINE.value}|exp-1|hindsight=0"
