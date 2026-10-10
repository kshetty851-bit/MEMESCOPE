"""The crew rule: a wallet listed after a bad coin refuses later coins only."""

from datetime import UTC, datetime, timedelta

from app.labs.graduation import moneyblock as mb

T = datetime(2026, 10, 10, 2, 47, tzinfo=UTC)  # SI closed


def test_a_listed_wallet_refuses_a_later_coin_but_not_an_earlier_one():
    crew = {"BbK5": T}
    assert mb.crew_hit({"BbK5", "bot"}, T + timedelta(hours=5), crew)       # TM
    assert not mb.crew_hit({"BbK5"}, T - timedelta(minutes=5), crew)        # SI itself
    assert not mb.crew_hit({"someone else"}, T + timedelta(hours=5), crew)
    assert not mb.crew_hit(set(), T + timedelta(hours=5), crew)


def test_the_line_is_a_30_percent_loss():
    assert mb.CREW_RETURN == -0.30 and mb.CREW_MAX_COINS == 3
