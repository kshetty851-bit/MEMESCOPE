"""The entry pause stops buying and provably cannot stop selling.

`PAPER_WALLET_ENTRIES_PAUSED` is a capital-protection kill switch. The thing
that makes it safe is structural, not a promise in a docstring: every new
position is born in `_open_entries`, and every caller of `_open_entries`
settles exits *before* it. These tests read the source so the guarantee
survives a refactor a hand-written list of call sites would not.

Modelled on `tests/integration/test_market_data_gate.py`, which proves the
same property for the feed-health gate.
"""

from __future__ import annotations

import inspect

from app.core.config import settings
from app.paper import eligibility, service as service_module
from app.paper.service import PaperWalletService

SOURCE = inspect.getsource(service_module)
SETTING = "PAPER_WALLET_ENTRIES_PAUSED"


def _body(name: str) -> str:
    """One method's source, to the start of the next method at the same depth."""
    # `def {name}(` and not `def {name}` — the latter prefix-matches, so
    # `manual_sell` silently read `manual_sell_preview` instead.
    start = SOURCE.find(f"def {name}(")
    assert start != -1, f"{name} not found in app.paper.service"
    end = SOURCE.find("\n    async def ", start + 1)
    return SOURCE[start : end if end != -1 else len(SOURCE)]


class TestTheSwitchIsInertByDefault:
    def test_default_is_off(self) -> None:
        """A capital control ships off. Turning it on is an operation."""
        assert type(settings).model_fields[SETTING].default is False

    def test_the_refusal_code_renders_a_sentence(self) -> None:
        assert (
            eligibility.ENTRIES_PAUSED_REFUSAL in eligibility.REFUSAL_LABELS
        ), "a refusal with no label renders as a bare code on the dashboard"


class TestOnlyEntriesCanSeeIt:
    def test_no_exit_path_reads_the_pause(self) -> None:
        """The switch must be unreachable from anything that closes a position."""
        for marker in (
            "_settle_exits",
            "_close_terminal",
            "_close_observed_bracket",
            "manual_sell",
            "review_observed_mints",
            "_record_audits",
        ):
            assert SETTING not in _body(marker), f"{marker} reaches the entry pause"

    def test_only_open_entries_reads_the_pause(self) -> None:
        """Exactly one method in the service consults it."""
        readers = [
            name
            for name, _ in inspect.getmembers(PaperWalletService, inspect.isfunction)
            if SETTING in _body(name)
        ]
        assert readers == ["_open_entries"], readers

    def test_open_entries_is_the_only_gateway_to_a_new_position(self) -> None:
        """If a second birthplace ever appears, the pause stops being total."""
        openers = [
            name
            for name, _ in inspect.getmembers(PaperWalletService, inspect.isfunction)
            if "_repository.open_position(" in _body(name)
        ]
        assert sorted(openers) == [
            "_open_entries",
            "_open_track_record_entries",
        ], openers
        # ...and the track-record path is only ever reached *through* the gate,
        # which is why the guard sits above that branch.
        guard = _body("_open_entries").index(SETTING)
        branch = _body("_open_entries").index("_open_track_record_entries")
        assert guard < branch, "the pause must precede the track-record branch"


class TestExitsRunFirstRegardless:
    def test_every_caller_settles_exits_before_opening(self) -> None:
        """The ordering *is* the safety argument, so it is asserted."""
        for caller in ("review", "review_observed_mints"):
            body = _body(caller)
            assert body.index("_settle_exits") < body.index(
                "_open_entries"
            ), f"{caller} opens before it settles"

    def test_manual_sell_closes_before_it_refills(self) -> None:
        body = _body("manual_sell")
        assert body.index("_repository.close(") < body.index("_open_entries")

    def test_the_scheduler_gate_is_a_different_switch(self) -> None:
        """`FEATURE_PAPER_WALLET_ENABLED` stops the whole review, exits included.

        Confusing the two is the mistake this switch exists to avoid, so the
        distinction is pinned rather than left to the reader.
        """
        scheduler = inspect.getsource(__import__("app.paper.scheduler", fromlist=["x"]))
        assert "FEATURE_PAPER_WALLET_ENABLED" in scheduler
        assert SETTING not in scheduler
