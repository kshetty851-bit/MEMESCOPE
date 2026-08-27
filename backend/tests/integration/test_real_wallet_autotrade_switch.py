"""The start/stop control, and the asymmetry that makes it trustworthy.

Stopping must be unconditional. Starting must authorise nothing. Both halves are
worth testing hard: a stop that can be refused is a stop nobody relies on, and a
start that grants permission is a browser button that can spend money.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models.real_wallet_execution import RealWalletAutotradeEvent
from app.real_wallet.autotrade import AutotradeSwitchService, UnknownStrategyError
from app.real_wallet.live_readiness import LiveSubmissionGuard, SubmissionFacts

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)


async def test_it_starts_off(db_session):
    state = await AutotradeSwitchService(db_session).state()
    assert state.enabled is False
    assert state.nominated_strategy is None


async def test_starting_records_who_why_and_which_strategy(db_session):
    svc = AutotradeSwitchService(db_session)
    state = await svc.start(actor="op@example.com", reason="V6-06 led the 30d review",
                            strategy_id="v6-06", at=NOW)
    assert state.enabled is True
    assert state.nominated_strategy == "V6-06"          # normalised
    assert state.started_by == "op@example.com"
    assert state.start_reason == "V6-06 led the 30d review"


async def test_starting_authorises_nothing(db_session):
    """The whole contract. Turning it on satisfies exactly one condition."""
    svc = AutotradeSwitchService(db_session)
    state = await svc.start(actor="op@example.com", reason="ready",
                            strategy_id="V6-06", at=NOW)
    assert state.as_dict()["authorises_execution"] is False

    # every OTHER condition still refuses
    decision = LiveSubmissionGuard().evaluate(SubmissionFacts(autotrade_switch_on=True))
    assert decision.allowed is False
    assert "AUTOTRADE_SWITCH_OFF" not in decision.reasons   # this one is satisfied
    for still_blocking in ("RELEASE_NOT_APPROVED", "EXECUTION_DISABLED",
                           "SIGNER_UNAVAILABLE", "SAFETY_NOT_APPROVED"):
        assert still_blocking in decision.reasons


async def test_the_switch_off_refuses_even_when_everything_else_passes(db_session):
    """This is what makes STOP trustworthy: it is sufficient on its own."""
    everything_else = SubmissionFacts(
        signer_ready=True, signer_matches_pinned_key=True, safety_passed=True,
        safety_fresh=True, policy_passed=True, valid_intent=True,
        not_previously_submitted=True, order_fresh=True, market_fresh=True,
        kill_switch_active=False, daily_loss_within_limit=True,
        open_position_within_limit=True, trade_size_within_limit=True,
        mainnet_verified=True, transaction_approved=True,
        not_previously_signed=True, canary_limits_satisfied=True,
        transport_release_approved=True,
        autotrade_switch_on=False,
    )
    decision = LiveSubmissionGuard().evaluate(everything_else)
    assert decision.allowed is False
    # Three of the guard's checks read settings rather than facts and are always
    # present in a test process; of everything the FACTS control, the switch is
    # the only thing left refusing — which is the property that matters.
    from_settings = {"MODE_NOT_LIVE", "EXECUTION_DISABLED", "AUTOTRADE_DISABLED"}
    assert set(decision.reasons) - from_settings == {"AUTOTRADE_SWITCH_OFF"}


async def test_stopping_is_unconditional_and_immediate(db_session):
    svc = AutotradeSwitchService(db_session)
    await svc.start(actor="op@example.com", reason="go", strategy_id="V6-06", at=NOW)
    state = await svc.stop(actor="op@example.com", reason="drawdown", at=NOW)
    assert state.enabled is False
    assert state.stop_reason == "drawdown"
    # the nomination is retained: what was running matters after it stopped
    assert state.nominated_strategy == "V6-06"


async def test_stopping_works_from_a_cold_start(db_session):
    """Stop must never depend on having been started, or on a row existing."""
    state = await AutotradeSwitchService(db_session).stop(
        actor="op@example.com", reason="precaution", at=NOW
    )
    assert state.enabled is False


async def test_a_nomination_must_name_a_real_strategy(db_session):
    with pytest.raises(UnknownStrategyError):
        await AutotradeSwitchService(db_session).start(
            actor="op@example.com", reason="typo", strategy_id="V6-99", at=NOW
        )
    assert (await AutotradeSwitchService(db_session).state()).enabled is False


async def test_every_transition_is_appended_to_history(db_session):
    svc = AutotradeSwitchService(db_session)
    await svc.start(actor="a@x.com", reason="one", strategy_id="V6-06", at=NOW)
    await svc.stop(actor="b@x.com", reason="two", at=NOW)
    await svc.start(actor="a@x.com", reason="three", strategy_id="V6-18", at=NOW)
    events = list((await db_session.execute(
        select(RealWalletAutotradeEvent)
    )).scalars())
    assert [e.action for e in events] == ["started", "stopped", "started"]
    assert [e.actor for e in events] == ["a@x.com", "b@x.com", "a@x.com"]
    assert events[-1].nominated_strategy == "V6-18"


async def test_history_survives_the_switch_being_toggled_back(db_session):
    """The row is state; the events are evidence. Evidence is never rewritten."""
    svc = AutotradeSwitchService(db_session)
    await svc.start(actor="a@x.com", reason="one", strategy_id="V6-06", at=NOW)
    await svc.stop(actor="a@x.com", reason="two", at=NOW)
    assert len(await svc.history()) == 2
