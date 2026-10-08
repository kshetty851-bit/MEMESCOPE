"""Every reason code has a sentence, and no sentence advises.

The page this feeds is paper only and must read the same to someone who is not
allowed to trade. The pattern is the frontend's own banned-word test, so a word
the page would refuse cannot be shipped by the server.
"""

from __future__ import annotations

import re

import pytest

from app.labs.btc_range import bounds, service
from app.labs.btc_range.prose import REASON_TEXT, reason_text
from app.labs.btc_range.types import Reason

pytestmark = pytest.mark.unit

BANNED = re.compile(
    r"\b(buy|buying|sell|selling|hold|holding|should|consider|recommend\w*|advice|advise\w*)\b"
    r"|opportunity to",
    re.IGNORECASE,
)


@pytest.mark.parametrize("reason", list(Reason), ids=lambda r: r.value)
def test_every_reason_has_text(reason: Reason) -> None:
    text = REASON_TEXT.get(reason)
    assert text and text.strip(), f"{reason.value} has no prose"
    assert reason_text(reason) == text
    assert reason_text(reason.value) == text


def test_the_table_has_no_stray_codes() -> None:
    assert set(REASON_TEXT) == set(Reason)


@pytest.mark.parametrize("reason", list(Reason), ids=lambda r: r.value)
def test_no_reason_text_advises(reason: Reason) -> None:
    assert not BANNED.search(REASON_TEXT[reason]), REASON_TEXT[reason]


def test_the_checker_catches_what_it_claims_to() -> None:
    for word in ("buy", "Sell now", "hold", "you should", "consider", "recommended"):
        assert BANNED.search(word), word
    assert not BANNED.search("threshold of the range")


def test_an_unknown_code_is_shown_raw_not_raised() -> None:
    assert reason_text("brand_new_code") == "brand_new_code"


@pytest.mark.parametrize("name", list(bounds.BOUNDS))
def test_field_wording_does_not_advise(name: str) -> None:
    b = bounds.BOUNDS[name]
    assert not BANNED.search(b.label), b.label
    assert not BANNED.search(b.help), b.help


def test_status_wording_does_not_advise() -> None:
    assert not BANNED.search(service.LAB_OFF_REASON)
    assert not BANNED.search(service.NO_CANDLES_REASON)
