"""The user wallets' names, and what the real wallet offers.

(The share sizing and balance tests went with the share system, 2026-09-25.)
"""

from __future__ import annotations

from decimal import Decimal

from app.labs.graduation import live_spec
from app.real_wallet import family

D = Decimal


# --- the users ---------------------------------------------------------------

def test_ten_users_in_order_with_readable_names():
    assert tuple(f"USER{i}" for i in range(1, 11)) == family.MEMBERS
    assert family.label("USER1") == "USER 1"
    assert family.label("USER10") == "USER 10"


def test_the_users_password_checks_against_a_hash_and_nothing_else():
    stored = family.hash_password("a users secret", salt=b"0123456789abcdef")
    assert "$" not in stored            # docker compose would mangle a `$`
    assert "a users secret" not in stored
    assert family.password_ok("a users secret", stored)
    assert not family.password_ok("a users secreT", stored)
    assert not family.password_ok("anything", "")      # none set: nobody gets in
    assert not family.password_ok("anything", "zz:zz")


def test_only_user1_is_open_and_a_token_opens_the_rest():
    assert not family.locked("USER1")
    assert all(family.locked(f"USER{i}") for i in range(2, 11))
    token, _ = family.issue_token()
    assert family.token_ok(token)
    assert not family.token_ok(token + "x")
    assert not family.token_ok(None)


# --- what the wallet offers -------------------------------------------------

def test_only_the_two_quiet_arms_are_offered_and_both_still_exist():
    assert live_spec.OFFERED == ("G-QUIET", "G-QUIET4", "G-Q150")
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


def test_bands_include_the_lower_bound_and_exclude_the_upper():
    from decimal import Decimal as D

    from app.real_wallet.family import in_band

    assert in_band("any", None) and in_band("any", D("5e9"))
    assert in_band("1m-20m", D("1000000")) and not in_band("1m-20m", D("20000000"))
    assert not in_band("1m-20m", D("999999")) and not in_band("1m-20m", None)
    assert in_band("5m-100m", D("99999999")) and not in_band("5m-100m", D("100000000"))
    assert not in_band("nonsense", D("5000000"))
