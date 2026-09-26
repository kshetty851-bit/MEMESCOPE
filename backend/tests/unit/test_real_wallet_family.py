"""The family pages' password and token, and what the real wallet offers.

(The share sizing and balance tests went with the share system, 2026-09-25.)
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.labs.graduation import live_spec
from app.real_wallet import family

D = Decimal


# --- the password -----------------------------------------------------------

def test_the_password_checks_against_a_hash_and_nothing_else():
    stored = family.hash_password("a family secret", salt=b"0123456789abcdef")
    assert "$" not in stored            # docker compose would mangle a `$`
    assert "a family secret" not in stored
    assert family.password_ok("a family secret", stored)
    assert not family.password_ok("a family secreT", stored)
    assert not family.password_ok("", stored)


@pytest.mark.parametrize("stored", ["", "   ", "nocolon", "zz:zz"])
def test_no_or_broken_password_setting_lets_nobody_in(stored):
    assert not family.password_ok("anything", stored)


def test_a_token_opens_one_member_and_only_that_one():
    token, _ = family.issue_token("JAYA")
    assert family.token_member(token) == "JAYA"
    assert family.token_member(token + "x") is None
    assert family.token_member(None) is None
    assert family.token_member("not-a-token") is None


def test_wrong_passwords_are_throttled_per_caller():
    t = family.Throttle(limit=3, window=600)
    for i in range(3):
        assert not t.blocked("a", now=i)
        t.failed("a", now=i)
    assert t.blocked("a", now=10)
    assert not t.blocked("b", now=10)          # someone else is unaffected
    assert not t.blocked("a", now=10 + 601)    # and it forgets after the window


# --- what the wallet offers -------------------------------------------------

def test_only_the_two_quiet_arms_are_offered_and_both_still_exist():
    assert live_spec.OFFERED == ("G-QUIET", "G-QUIET4", "G-Q150", "G-QMID")
    assert all(sid in live_spec.BY_ID for sid in live_spec.OFFERED)
    # Retired arms stay registered: the exit driver finds a held position's
    # rules through BY_ID.
    assert "G-B3-4M" in live_spec.BY_ID


def test_two_hundred_is_offered_once_the_ceiling_allows_it(monkeypatch):
    from app.core.config import settings
    from app.real_wallet.autotrade import ticket_choices

    monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", D("100"))
    assert D("200") not in ticket_choices("G-QUIET")
    monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", D("200"))
    choices = ticket_choices("G-QUIET")
    assert choices[0] == D("200")
    assert choices == sorted(choices, reverse=True)
    assert D("25") in choices and D("100") in choices
