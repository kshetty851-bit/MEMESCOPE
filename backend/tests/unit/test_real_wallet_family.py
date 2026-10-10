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


def test_user1_to_7_need_the_investment_password_and_8_to_10_the_users(monkeypatch):
    from app.core.config import settings

    assert [family.scope(f"USER{i}") for i in range(1, 11)] == \
        ["investment"] * 7 + ["users"] * 3
    monkeypatch.setattr(settings, "REAL_WALLET_INVESTMENT_PASSWORD_HASH",
                        family.hash_password("seven", salt=b"a" * 16))
    monkeypatch.setattr(settings, "REAL_WALLET_USERS_PASSWORD_HASH",
                        family.hash_password("ten", salt=b"b" * 16))
    assert family.password_scope("seven") == "investment"
    assert family.password_scope("ten") == "users"
    assert family.password_scope("other") is None
    investment, _ = family.issue_token({"investment"})
    assert family.opens("USER1", investment) and family.opens("USER7", investment)
    assert not family.opens("USER8", investment)
    both, _ = family.issue_token({"investment", "users"})
    assert all(family.opens(f"USER{i}", both) for i in range(1, 11))
    assert family.token_scopes(both + "x") == frozenset()
    assert family.token_scopes(None) == frozenset()


def test_an_unset_investment_password_opens_nothing(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "REAL_WALLET_INVESTMENT_PASSWORD_HASH", "")
    monkeypatch.setattr(settings, "REAL_WALLET_USERS_PASSWORD_HASH", "")
    assert family.password_scope("") is None and family.password_scope("x") is None


def test_only_the_two_quiet_arms_are_offered_and_both_still_exist():
    assert live_spec.OFFERED == ("G-QUIET", "G-QUIET4", "G-Q150", "G-Q50")
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


def test_pool_bands_for_smart_stacking():
    from decimal import Decimal as D

    from app.real_wallet.family import ALL_BANDS, in_pool_band, is_pool_band

    assert is_pool_band("pool-under-75k")
    assert not is_pool_band("1m-20m") and not is_pool_band("any")
    assert in_pool_band("pool-under-75k", D("74999"))
    assert not in_pool_band("pool-under-75k", D("75000"))
    assert in_pool_band("pool-under-150k", D("120000"))
    assert not in_pool_band("pool-under-150k", D("150000"))
    assert not in_pool_band("pool-under-150k", None)      # unknown pool: no
    assert {"any", "1m-20m", "pool-under-75k", "pool-under-150k"} <= ALL_BANDS


def test_only_a_known_device_key_opens_jupiter():
    import hashlib

    key = "k" * 40
    allowed = f" {hashlib.sha256(key.encode()).hexdigest().upper()} , abc"
    assert family.device_ok(key, allowed)                 # case and spaces ignored
    assert not family.device_ok("x" * 40, allowed)
    assert not family.device_ok(key, "")                  # nothing configured: nobody
    assert not family.device_ok("short", allowed)
    assert not family.device_ok(None, allowed)
