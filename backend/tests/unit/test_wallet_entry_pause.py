"""The V4 entry pause: entries stop, exits cannot be reached by the switch.

The property that matters is placement: the gate is the *first* statement in
the one function every new position is born in. These tests prove it by
handing the service no session at all — if the gate ever moves behind a query
or the strategy registry, the tests fail with an attribute error instead of a
refusal.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.config import settings
from app.paper.eligibility import REFUSAL_LABELS, Refusal
from app.paper.service import PaperWalletService

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_paused_open_entries_refuses_before_touching_anything(monkeypatch):
    monkeypatch.setattr(settings, "PAPER_WALLET_ENTRIES_PAUSED", True)
    service = PaperWalletService.__new__(PaperWalletService)  # no session on purpose
    opened, candidates, truncated, refusals = await service._open_entries(None, now=NOW)
    assert (opened, candidates, truncated) == (0, 0, False)
    assert refusals == {Refusal.ENTRIES_PAUSED.value: 1}


@pytest.mark.asyncio
async def test_unpaused_open_entries_proceeds_past_the_gate(monkeypatch):
    monkeypatch.setattr(settings, "PAPER_WALLET_ENTRIES_PAUSED", False)
    service = PaperWalletService.__new__(PaperWalletService)
    # With no session and no strategy the very next statement must blow up —
    # proving the gate, and only the gate, ran while paused was False.
    with pytest.raises(AttributeError):
        await service._open_entries(None, now=NOW)


def test_pause_refusal_is_a_named_reason_with_a_label():
    assert Refusal.ENTRIES_PAUSED.value == "entries_paused"
    label = REFUSAL_LABELS[Refusal.ENTRIES_PAUSED]
    assert "paused" in label and "exits still settle" in label.lower()
