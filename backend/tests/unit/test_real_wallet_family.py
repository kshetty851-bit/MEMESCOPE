"""Family shares of the real wallet: sizing, balances and the password.

The driver's only new behaviour is `family.split` and `family.scale`, so the
guarantees that matter are pinned here, where they can be checked exactly:

* nobody switched on leaves the owner's order EXACTLY as it was;
* the whole order never exceeds the cap, and shares shrink together;
* the parts of an order always add up to the order, to the cent;
* a member is only ever charged their share, never the owner's.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.labs.graduation import live_spec
from app.real_wallet import family
from app.real_wallet.family import Seat, Share, Split

D = Decimal


def seat(name: str, ticket: str, available: str = "1000", enabled: bool = True) -> Seat:
    return Seat(name, enabled, D(ticket), D(available))


def parts(order: Split) -> D:
    return order.owner + sum(order.members.values(), D(0))


# --- sizing -----------------------------------------------------------------

@pytest.mark.parametrize("own", ["5", "25", "99.00", "100", "200"])
def test_nobody_on_leaves_the_owner_order_exactly_as_it_was(own):
    for seats in ([], [seat("JAYA", "50", enabled=False)],
                  [seat("ASHA", "50", available="10")]):
        order = family.split(D(own), seats)
        assert order == Split(total=D(own), owner=D(own), members={})
    # ...and scaling a lone owner is the old `min(ticket, cash)` exactly.
    assert family.scale(family.split(D(own), []), D("12.34")).total == min(D(own), D("12.34"))


def test_members_who_are_on_and_can_pay_add_their_ticket():
    order = family.split(D("25"), [seat("JAYA", "50"), seat("ASHA", "20"),
                                   seat("APOORVA", "100", enabled=False)])
    assert order.total == D("95")
    assert order.owner == D("25")
    assert order.members == {"JAYA": D("50"), "ASHA": D("20")}


def test_a_member_without_the_money_for_a_whole_ticket_sits_out():
    order = family.split(D("25"), [seat("JAYA", "50", available="49.99"),
                                   seat("ASHA", "50", available="50")])
    assert order.members == {"ASHA": D("50")}


def test_the_whole_order_never_exceeds_the_cap_and_shares_shrink_together():
    # $200 + 3 x $200 = $800 asked for; the arm loses money above ~$400.
    order = family.split(D("200"), [seat(n, "200") for n in family.MEMBERS])
    assert order.total == family.COMBINED_CAP_USD == D("400")
    assert parts(order) == D("400")
    # Everyone had the same ticket, so everyone gets the same share.
    assert set(order.members.values()) == {D("100")}
    assert order.owner == D("100")


def test_scaling_keeps_the_parts_summing_to_the_order_to_the_cent():
    order = family.split(D("25"), [seat("JAYA", "20"), seat("ASHA", "10"),
                                   seat("APOORVA", "50")])       # $105
    for to in (D("104.99"), D("73.33"), D("56.00"), D("1.00")):
        s = family.scale(order, to)
        assert s.total == to
        assert parts(s) == to
        # A member is rounded DOWN, so never charged more than their share...
        for name, amount in s.members.items():
            assert amount <= order.members[name] * to / order.total
        # ...and the owner carries the rounding.
        assert s.owner >= D(0)


def test_scaling_up_or_to_the_same_size_changes_nothing():
    order = family.split(D("25"), [seat("JAYA", "20")])
    assert family.scale(order, order.total) == order
    assert family.scale(order, order.total + 5) == order


# --- balances ---------------------------------------------------------------

def test_a_members_balance_is_money_in_minus_out_plus_their_share_of_results():
    ledger = [("deposit", D("100")), ("deposit", D("50")), ("withdrawal", D("30"))]
    shares = [
        # $20 of a $100 order that made $5: this member's share is $1.
        Share(D("20"), D("100"), "closed", D("5")),
        # $20 of a $100 order that died, -$100: this member lost $20.
        Share(D("20"), D("100"), "closed", D("-100")),
        # $20 still in a trade.
        Share(D("20"), D("100"), "open", None),
        # An order that failed: no money moved, nothing counts.
        Share(D("20"), D("100"), "void", None),
    ]
    b = family.balance(ledger, shares)
    assert b.deposited == D("150") and b.withdrawn == D("30")
    assert b.pnl == D("1.00") + D("-20.00")
    assert b.balance == D("150") - D("30") - D("19")
    assert b.in_trades == D("20")
    assert b.available == b.balance - D("20")
    assert (b.trades, b.wins) == (2, 1)


def test_money_in_a_trade_is_not_available_for_the_next_one():
    b = family.balance([("deposit", D("50"))], [Share(D("50"), D("75"), "open", None)])
    order = family.split(D("25"), [Seat("JAYA", True, D("50"), b.available)])
    assert order.members == {}


@pytest.mark.parametrize("intent, position, want", [
    ("confirmed", "CLOSED", "closed"),
    ("confirmed", "OPEN", "open"),
    ("submitted", None, "open"),
    ("created", None, "open"),
    ("failed", None, "void"),
    ("blocked", None, "void"),
])
def test_how_an_order_stands_for_accounting(intent, position, want):
    assert family.share_state(intent, position) == want


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
