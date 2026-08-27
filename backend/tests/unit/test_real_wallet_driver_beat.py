"""The driver had no heartbeat.

Everything about the real wallet was built and correct — switch, nomination,
policy, order factory, signer — and nothing called `RealWalletDriver.tick`. The
operator could nominate a strategy, press START, and watch a switch that was on
while no intent was ever created. These tests exist so that cannot come back
silently.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from app.real_wallet import scheduler as sched
from app.workers.celery_app import celery_app

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


def test_the_driver_is_actually_scheduled():
    entry = celery_app.conf.beat_schedule["real-wallet-driver-tick"]
    assert entry["task"] == "app.real_wallet.scheduler.real_wallet_driver_tick"
    # Every minute: a Lab decision is actionable for ten, and a slower tick
    # would spend most of that shelf life asleep.
    assert entry["schedule"].minute == {m for m in range(60)}


def test_the_scheduled_task_is_registered_under_the_name_beat_calls():
    assert "app.real_wallet.scheduler.real_wallet_driver_tick" in celery_app.tasks


def test_the_task_adds_no_authority_of_its_own():
    """It may call the driver and commit. It must not reach past it to create
    intents, sign, or submit — every barrier lives downstream of `tick`."""
    tree = ast.parse(Path(sched.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_real_wallet_driver_tick")
    called = {n.func.attr for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "tick" in called
    assert not called & {"create_intent", "prepare", "sign", "submit",
                         "execute", "authorise", "sign_intent"}


def test_a_driver_failure_cannot_stop_the_beat():
    """Contained like the Lab's. Beat also carries the tasks that watch the
    kill switch's neighbours, and one wallet must not take them down."""
    tree = ast.parse(Path(sched.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_real_wallet_driver_tick")
    handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
    assert handlers, "an unhandled driver failure would raise into beat"
    assert not any(isinstance(n, ast.Raise) for h in handlers for n in ast.walk(h))


def test_two_ticks_cannot_run_at_once():
    """The intent's idempotency key stops a duplicate row, but two concurrent
    ticks would each read the open-position count before either wrote, and the
    policy would be counting a book that no longer exists."""
    src = Path(sched.__file__).read_text()
    assert "pg_try_advisory_xact_lock" in src
    assert sched.DRIVER_LOCK_KEY != sched.DRY_RUN_LOCK_KEY


async def test_the_switch_being_off_is_what_stops_it(monkeypatch):
    """The default state refuses at the first condition, so scheduling it
    changes nothing until an operator deliberately starts it."""
    from app.real_wallet.driver import RealWalletDriver

    class _Switch:
        enabled = False
        nominated_strategy = None

    class _Service:
        def __init__(self, _session): ...
        async def state(self): return _Switch()

    monkeypatch.setattr("app.real_wallet.driver.AutotradeSwitchService", _Service)
    outcome = await RealWalletDriver(object()).tick()
    assert outcome.created == 0
    assert outcome.skipped == "autotrade_switch_off"


def test_the_driver_spends_the_asset_the_wallet_actually_holds():
    """It named USDC as the input mint and set no amount at all.

    The wallet holds SOL and zero USDC, so the swap would have tried to spend a
    token that is not there — and the order factory refuses first anyway, on
    `buy_intent_missing_lamports`, because a BUY's spend is read from the ROW
    rather than recomputed at assembly.
    """
    from app.real_wallet import driver as drv

    tree = ast.parse(Path(drv.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "tick")
    src = ast.unparse(fn)
    assert "settings.EXECUTION_SOL_MINT" in src
    assert "JUPITER_USDC_MINT" not in src
    assert "actual_input_amount_raw=lamports" in src


def test_an_unpriced_entry_refuses_rather_than_guessing():
    """Every limit this wallet has is written in dollars, so an entry that
    cannot be priced is an entry nobody sized. A stale reading is not a price."""
    from app.real_wallet import driver as drv

    tree = ast.parse(Path(drv.__file__).read_text())
    tick = ast.unparse(next(n for n in ast.walk(tree)
                            if isinstance(n, ast.AsyncFunctionDef) and n.name == "tick"))
    assert "sol_price_unavailable" in tick
    assert "entry_size_rounds_to_zero_lamports" in tick


@pytest.mark.parametrize(
    ("age_seconds", "usd", "expected"),
    [
        (0, "100", "100"),        # fresh and positive -> usable
        (10_000, "100", None),    # stale -> refuses
        (-60, "100", None),       # from the future is not fresh, it is wrong
        (0, "0", None),           # a zero price is not a price
    ],
)
async def test_a_stale_or_absent_sol_price_refuses(monkeypatch, age_seconds,
                                                   usd, expected):
    """A stale reading is not a price.

    Asserted by CALLING it rather than by looking for "is_fresh" in the
    function's source, which is how this was written and which broke the moment
    the freshness rule moved into a shared helper. The property is about what
    the function returns, and source text is not evidence of that in either
    direction.
    """
    from datetime import UTC, datetime, timedelta

    from app.real_wallet import sol_price as sp

    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

    class _Source:
        async def current(self, *, now):  # noqa: ARG002
            return sp.SolUsdPrice(
                usd=Decimal(usd),
                observed_at=now - timedelta(seconds=age_seconds),
                source="test",
            )

    monkeypatch.setattr(sp, "JupiterSolUsdPriceSource", _Source)
    got = await sp.current_usd(now)
    assert got == (Decimal(expected) if expected is not None else None)


async def test_an_unreachable_price_source_refuses(monkeypatch):
    """An exception is an unpriced entry, never a guessed one."""
    from datetime import UTC, datetime

    from app.real_wallet import sol_price as sp

    class _Broken:
        async def current(self, *, now):  # noqa: ARG002
            raise RuntimeError("jupiter down")

    monkeypatch.setattr(sp, "JupiterSolUsdPriceSource", _Broken)
    assert await sp.current_usd(datetime(2026, 8, 27, tzinfo=UTC)) is None


def test_the_spend_is_stored_not_recomputed_at_assembly():
    """A price that moves between authorisation and assembly must not change
    what gets spent — which is why the lamports live on the row."""
    from app.real_wallet import production_order as po

    src = Path(po.__file__).read_text()
    assert "intent.actual_input_amount_raw" in src
    assert "buy_intent_missing_lamports" in src


def test_the_entry_is_quantised_down_to_whole_lamports():
    """`lamports_from_sol` refuses anything inexact by design — a limit that
    rounds is a limit that can be crossed by rounding — and $5 at any real SOL
    price is not a whole number of lamports. Without quantising, every driver
    tick raised and the beat recorded `{"failed": True}`.

    DOWN, not nearest: the entry must be at most the authorised size, never a
    lamport over it.
    """
    from decimal import ROUND_DOWN, Decimal

    from app.real_wallet import driver as drv
    from app.real_wallet.tx_inspect import lamports_from_sol

    src = ast.unparse(ast.parse(Path(drv.__file__).read_text()))
    assert "ROUND_DOWN" in src

    # The real arithmetic, at a real price, must not raise.
    entry, price = Decimal("5"), Decimal("96.32")
    sol = (entry / price).quantize(Decimal("1e-9"), rounding=ROUND_DOWN)
    lamports = lamports_from_sol(sol)
    assert lamports > 0
    # And never more than the authorised size.
    assert Decimal(lamports).scaleb(-9) * price <= entry
