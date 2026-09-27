"""The user wallets' profit fee: the maths, and where the signer lets it go."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from solders.keypair import Keypair

from app.core.config import settings
from app.real_wallet import mainnet_signer as ms
from app.real_wallet import user_fees, withdraw_service
from tests.unit.test_family_wallets import _transfer, keys  # noqa: F401

D = Decimal


@pytest.mark.parametrize(("profit", "hwm", "rate", "fee", "mark"), [
    ("100", "0", "0.20", "20.00", "100"),     # first month's profit
    ("150", "100", "0.20", "10.00", "150"),   # only the NEW 50 is charged
    ("80", "150", "0.20", "0", "150"),        # a losing month pays nothing, mark stays
    ("150", "150", "0.20", "0", "150"),       # winning the loss back pays nothing
    ("200", "0", "0", "0.00", "200"),         # USER 1: no fee, mark still moves
    ("-40", "0", "0.20", "0", "0"),
])
def test_the_fee_is_a_share_of_profit_above_the_high_water_mark(profit, hwm, rate, fee, mark):
    assert user_fees.fee_for(D(profit), D(hwm), D(rate)) == (D(fee), D(mark))


def test_months_step_back_across_a_year():
    assert user_fees.previous_month(date(2027, 1, 1)) == date(2026, 12, 1)
    assert user_fees.previous_month(date(2026, 10, 1)) == date(2026, 9, 1)


@pytest.fixture
def fee_address(keys, monkeypatch):  # noqa: F811
    fee = Keypair()
    monkeypatch.setattr(settings, "REAL_WALLET_FEE_ADDRESS", str(fee.pubkey()))
    return fee


async def test_a_user_wallet_may_pay_the_fee_address(keys, fee_address):  # noqa: F811
    out = await ms.sign_withdrawal(_transfer(keys.user1, str(fee_address.pubkey())),
                                   wallet=str(keys.user1.pubkey()), to_fee=True)
    assert out["destination"] == str(fee_address.pubkey())


async def test_the_fee_goes_nowhere_else(keys, fee_address):  # noqa: F811
    # Not to a stranger, and not to Karthik's withdrawal address either.
    for to in (str(Keypair().pubkey()), str(keys.karthik.pubkey())):
        with pytest.raises(ms.MainnetSignerError, match="withdrawal_rejected"):
            await ms.sign_withdrawal(_transfer(keys.user1, to),
                                     wallet=str(keys.user1.pubkey()), to_fee=True)


async def test_the_owners_wallet_never_pays_a_fee(keys, fee_address):  # noqa: F811
    with pytest.raises(ms.MainnetSignerError, match="owner_wallet_pays_no_fee"):
        await ms.sign_withdrawal(_transfer(keys.owner, str(fee_address.pubkey())), to_fee=True)
    with pytest.raises(withdraw_service.WithdrawError, match="only_a_user_wallet"):
        withdraw_service.fee_destination(str(keys.owner.pubkey()))


async def test_no_fee_address_means_no_fee(keys, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "REAL_WALLET_FEE_ADDRESS", "")
    with pytest.raises(ms.MainnetSignerError, match="not_configured"):
        await ms.sign_withdrawal(_transfer(keys.user1, str(Keypair().pubkey())),
                                 wallet=str(keys.user1.pubkey()), to_fee=True)
    with pytest.raises(withdraw_service.WithdrawError, match="fee_address_not_configured"):
        withdraw_service.fee_destination(str(keys.user1.pubkey()))


def test_every_service_and_the_signer_read_the_fee_address():
    from tests.unit.test_family_wallets import _compose

    services = _compose()["services"]
    for name in ("backend", "mainnet-signer"):
        assert "REAL_WALLET_FEE_ADDRESS" in services[name]["environment"]
