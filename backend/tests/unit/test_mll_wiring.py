"""The Lab is switched on by wiring, not by code: these tests hold the wiring.

Every pure engine can be right and the Lab still collect nothing, if a task is
not registered, a beat entry is missing, a route is not mounted or a source
that must stay off turns itself on. None of that shows up in an engine test,
and all of it is invisible in a diff, so it is asserted here.

What is deliberately NOT asserted: that a source answers. The collection
hosts (GDELT, Wikimedia, DexScreener, pump.fun) are third parties; whether
they answer is reported by ``/lifecycle-lab/health``, never by a test.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from celery.schedules import crontab
from pydantic import SecretStr

from app.core.config import Settings, settings
from app.lifecycle_lab import scheduler as lab_scheduler
from app.lifecycle_lab.adapters import (
    PumpfunRepliesAdapter,
    RedditAdapter,
    XAdapter,
    build_adapters,
)
from app.lifecycle_lab.domain import Source, SourceStatus
from app.workers.celery_app import celery_app

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)

BACKEND = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND.parent
SCHEDULER_SRC = BACKEND / "app" / "lifecycle_lab" / "scheduler.py"

#: beat entry name -> (task name, expected minute set on a ``crontab``).
#: The minute sets are the cadence: a changed cadence is a deliberate edit to
#: this table, with the reason in the beat comment.
BEAT: dict[str, tuple[str, set[int]]] = {
    "lifecycle-collect": (
        "app.lifecycle_lab.scheduler.lifecycle_collect_tick",
        {1, 16, 31, 46},  # every 15 min, off :00 (GDELT's 15-minute buckets)
    ),
    "lifecycle-detect-events": (
        "app.lifecycle_lab.scheduler.lifecycle_detect_events_tick",
        set(range(0, 60, 5)),  # the replay's 5-minute decision grid
    ),
    "lifecycle-timeliness": (
        "app.lifecycle_lab.scheduler.lifecycle_timeliness_tick",
        {4, 19, 34, 49},  # every 15 min
    ),
    "lifecycle-forward-replay": (
        "app.lifecycle_lab.scheduler.lifecycle_forward_replay_tick",
        {11, 41},  # every 30 min
    ),
    "lifecycle-autolink": (
        "app.lifecycle_lab.scheduler.lifecycle_autolink_tick",
        {23},  # hourly
    ),
    "lifecycle-experiment": (
        "app.lifecycle_lab.scheduler.lifecycle_experiment_tick",
        {7},  # hourly
    ),
}

#: On demand (admin POST /memes/{slug}/backfill); deliberately NOT on beat.
ON_DEMAND_TASKS = {"app.lifecycle_lab.scheduler.lifecycle_backfill"}

#: Routes that must be mounted. Additions are allowed; a removal is not.
REQUIRED_ROUTES: set[tuple[str, str]] = {
    ("get", "/api/v1/lifecycle-lab/overview"),
    ("get", "/api/v1/lifecycle-lab/health"),
    ("get", "/api/v1/lifecycle-lab/memes"),
    ("get", "/api/v1/lifecycle-lab/memes/{slug}"),
    ("get", "/api/v1/lifecycle-lab/quality"),
    ("get", "/api/v1/lifecycle-lab/memes/{slug}/quality"),
    ("get", "/api/v1/lifecycle-lab/research-status"),
    ("get", "/api/v1/lifecycle-lab/experiments"),
    ("get", "/api/v1/lifecycle-lab/runs/{run_id}"),
    ("post", "/api/v1/lifecycle-lab/memes"),
    ("post", "/api/v1/lifecycle-lab/memes/{slug}/aliases"),
    ("post", "/api/v1/lifecycle-lab/memes/{slug}/links"),
    ("post", "/api/v1/lifecycle-lab/memes/{slug}/backfill"),
}

FRONTEND_ROUTES = (
    "frontend/src/app/(dashboard)/lifecycle-lab/page.tsx",
    "frontend/src/app/(dashboard)/lifecycle-lab/[slug]/page.tsx",
)


def _lab_on_settings(**overrides: Any) -> Settings:
    """Real settings, Lab flag on, no credentials unless an override adds one."""
    base: dict[str, Any] = {
        "FEATURE_LIFECYCLE_LAB_ENABLED": True,
        "MLL_REDDIT_CLIENT_ID": SecretStr(""),
        "MLL_REDDIT_CLIENT_SECRET": SecretStr(""),
        "MLL_REDDIT_USER_AGENT": "",
        "MLL_X_BEARER_TOKEN": SecretStr(""),
    }
    base.update(overrides)
    return settings.model_copy(update=base)


# --------------------------------------------------------------------------
# Migrations
# --------------------------------------------------------------------------


def _script_directory() -> ScriptDirectory:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_the_lab_migration_is_an_ancestor_of_the_single_head() -> None:
    """``alembic upgrade head`` must create the Lab's tables, and there must be
    exactly one head: two heads make ``upgrade head`` refuse to run at all."""
    script = _script_directory()
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic has multiple heads: {heads}"
    lineage = {rev.revision for rev in script.walk_revisions(base="base", head=heads[0])}
    assert "0112_meme_lifecycle_lab" in lineage


# --------------------------------------------------------------------------
# Celery tasks and beat
# --------------------------------------------------------------------------


def _scheduler_task_names() -> set[str]:
    """Task names declared by ``@celery_app.task(name=...)`` in the scheduler."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(SCHEDULER_SRC.read_text())):
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call):
                for kw in deco.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        names.add(str(kw.value.value))
    return names


def test_the_scheduler_module_is_in_the_celery_includes() -> None:
    """A worker only knows the tasks of modules in ``include``. Without this the
    beat entries fire at a worker that answers "unregistered task"."""
    assert "app.lifecycle_lab.scheduler" in celery_app.conf.include


def test_every_lab_task_is_registered_by_name() -> None:
    declared = _scheduler_task_names()
    expected = {task for task, _ in BEAT.values()} | ON_DEMAND_TASKS
    assert declared == expected, "a Lab task was added or removed without updating the wiring"
    # Importing the module (done above) is what registers them on the app.
    assert declared <= set(celery_app.tasks)


def test_every_scheduled_lab_task_has_exactly_one_beat_entry() -> None:
    schedule = celery_app.conf.beat_schedule
    lab_entries = {
        name: entry
        for name, entry in schedule.items()
        if entry["task"].startswith("app.lifecycle_lab.")
    }
    assert set(lab_entries) == set(BEAT)
    scheduled_tasks = [entry["task"] for entry in lab_entries.values()]
    assert len(scheduled_tasks) == len(set(scheduled_tasks)), "a task has two beat entries"
    assert not (set(scheduled_tasks) & ON_DEMAND_TASKS), "backfill must stay on demand"


@pytest.mark.parametrize("entry_name", sorted(BEAT))
def test_beat_cadence(entry_name: str) -> None:
    task, minutes = BEAT[entry_name]
    entry = celery_app.conf.beat_schedule[entry_name]
    assert entry["task"] == task
    schedule = entry["schedule"]
    assert isinstance(schedule, crontab)
    assert set(schedule.minute) == minutes
    # Every hour, every day: a cadence is a minute pattern, nothing narrower.
    assert set(schedule.hour) == set(range(24))
    assert set(schedule.day_of_week) == set(range(7))


# --------------------------------------------------------------------------
# The flag: inert when off
# --------------------------------------------------------------------------


class _SessionOpenedError(AssertionError):
    """A Lab task opened a database session while the Lab flag was off."""


def _forbid_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_: object, **__: object) -> None:
        raise _SessionOpenedError

    monkeypatch.setattr(lab_scheduler, "SessionFactory", _boom)
    # ``run_async`` also initialises Redis and disposes the engine; the tasks'
    # own bodies are what is under test, so run them on a plain loop.
    monkeypatch.setattr(lab_scheduler, "run_async", asyncio.run)


def test_the_flag_ships_off(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings.model_fields["FEATURE_LIFECYCLE_LAB_ENABLED"].default is False


@pytest.mark.parametrize(
    "task_name",
    sorted({task for task, _ in BEAT.values()}),
)
def test_every_beat_task_returns_before_opening_a_session_when_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch, task_name: str
) -> None:
    """Registering the beat entries must start nothing. A task that touched the
    database first would hit a Lab that is off, on every tick, forever."""
    monkeypatch.setattr(settings, "FEATURE_LIFECYCLE_LAB_ENABLED", False)
    _forbid_sessions(monkeypatch)

    result = celery_app.tasks[task_name]()

    assert result == {"skipped": "lab_disabled"}


def test_the_on_demand_backfill_is_also_inert_when_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "FEATURE_LIFECYCLE_LAB_ENABLED", False)
    _forbid_sessions(monkeypatch)

    result = celery_app.tasks["app.lifecycle_lab.scheduler.lifecycle_backfill"](
        "doge", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"
    )

    assert result == {"skipped": "lab_disabled"}


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def test_every_lifecycle_lab_route_is_mounted() -> None:
    from app.main import create_app

    mounted = {
        (method.lower(), path)
        for path, operations in create_app().openapi()["paths"].items()
        if path.startswith("/api/v1/lifecycle-lab")
        for method in operations
    }
    assert mounted >= REQUIRED_ROUTES, f"unmounted: {sorted(REQUIRED_ROUTES - mounted)}"


def test_every_curation_route_is_admin_only() -> None:
    """Reads are public by design; every write must sit behind ``AdminUser``."""
    source = (BACKEND / "app" / "lifecycle_lab" / "api.py").read_text()
    tree = ast.parse(source)
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)):
        posts = any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and d.func.attr == "post"
            for d in fn.decorator_list
        )
        if posts:
            annotations = {ast.unparse(a.annotation) for a in fn.args.args if a.annotation}
            assert "AdminUser" in annotations, f"{fn.name} is a write without AdminUser"


# --------------------------------------------------------------------------
# Sources that must stay off
# --------------------------------------------------------------------------


def test_reddit_and_x_default_off() -> None:
    assert Settings.model_fields["MLL_REDDIT_ENABLED"].default is False
    assert Settings.model_fields["MLL_X_ENABLED"].default is False


def test_reddit_and_x_stay_disabled_with_the_lab_on_and_no_credentials() -> None:
    cfg = _lab_on_settings()
    assert RedditAdapter(cfg, client=None).enabled()[0] is False  # type: ignore[arg-type]
    assert XAdapter(cfg).enabled()[0] is False


def test_reddit_switch_alone_does_not_enable_it() -> None:
    """The switch without every credential is still off: no scraping fallback."""
    cfg = _lab_on_settings(MLL_REDDIT_ENABLED=True)
    assert RedditAdapter(cfg, client=None).enabled() == (False, "disabled_by_config")  # type: ignore[arg-type]
    cfg = _lab_on_settings(MLL_REDDIT_ENABLED=True, MLL_REDDIT_CLIENT_ID=SecretStr("id"))
    assert RedditAdapter(cfg, client=None).enabled()[0] is False  # type: ignore[arg-type]


def test_x_never_enables_itself_even_with_a_token() -> None:
    """There is no X implementation; a token must not make it claim to run."""
    cfg = _lab_on_settings(MLL_X_ENABLED=True, MLL_X_BEARER_TOKEN=SecretStr("t"))
    assert XAdapter(cfg).enabled() == (False, "not_implemented_no_api_plan")


def test_disabled_sources_collect_as_disabled_without_a_network_call() -> None:
    """DISABLED is a run row with a reason - never an empty AVAILABLE, never 0."""
    cfg = _lab_on_settings()

    def _no_network(*_: object, **__: object) -> None:
        raise AssertionError("a disabled source touched the network")

    client = SimpleNamespace(get=_no_network, post=_no_network, request=_no_network)
    adapters = {a.source: a for a in build_adapters(cfg, client)}  # type: ignore[arg-type]

    for source in (Source.REDDIT, Source.X):
        result = asyncio.run(adapters[source].collect([], now=_NOW))
        assert result.status is SourceStatus.DISABLED
        assert result.reason
        assert not result.observations


def test_pumpfun_replies_probe_is_disabled_without_the_social_poller() -> None:
    cfg = _lab_on_settings(FEATURE_PUMPFUN_SOCIAL_ENABLED=False)
    assert PumpfunRepliesAdapter(cfg).enabled() == (False, "pumpfun_social_disabled")


def test_all_seven_sources_are_built_whether_enabled_or_not() -> None:
    adapters = build_adapters(_lab_on_settings(), client=None)  # type: ignore[arg-type]
    assert {a.source for a in adapters} == {
        Source.PUMPFUN_REPLIES,
        Source.WIKIPEDIA,
        Source.GDELT,
        Source.DEXSCREENER,
        Source.GECKOTERMINAL,
        Source.REDDIT,
        Source.X,
    }


# --------------------------------------------------------------------------
# Settings reach every service (compose) and the frontend routes exist
# --------------------------------------------------------------------------


def test_every_lab_setting_is_in_the_compose_backend_env_anchor() -> None:
    """A switch on one service shows a Lab that reports itself off while
    another collects. Skips where the repo root is not mounted (the container)."""
    compose = REPO_ROOT / "docker-compose.yml"
    if not compose.exists():
        pytest.skip("repo root not mounted")
    text = compose.read_text()
    names = [
        n
        for n in Settings.model_fields
        if n.startswith("MLL_") or n == "FEATURE_LIFECYCLE_LAB_ENABLED"
    ]
    assert names
    missing = [n for n in names if f"  {n}: " not in text]
    assert not missing, f"missing from the x-backend-env anchor: {missing}"


def test_the_beat_and_worker_run_from_the_same_celery_app() -> None:
    compose = REPO_ROOT / "docker-compose.yml"
    if not compose.exists():
        pytest.skip("repo root not mounted")
    text = compose.read_text()
    assert "celery -A app.workers.celery_app worker --loglevel=info --concurrency=2" in text
    assert "celery -A app.workers.celery_app beat" in text


@pytest.mark.parametrize("relative", FRONTEND_ROUTES)
def test_frontend_route_files_exist(relative: str) -> None:
    if not (REPO_ROOT / "frontend").exists():
        pytest.skip("frontend not mounted")
    assert (REPO_ROOT / relative).is_file()
