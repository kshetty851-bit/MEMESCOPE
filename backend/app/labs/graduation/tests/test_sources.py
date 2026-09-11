"""The batched account read, and the alignment bug that corrupted it.

`getMultipleAccounts` answers positionally, so pairing results back to mints
is only sound while the window and the response line up exactly. They stopped
lining up the moment one batch failed, and nothing raised — every later mint
was paired with ANOTHER TOKEN'S account, and those rows looked perfectly
healthy because they were real curves belonging to somebody else.
"""

from __future__ import annotations

import base64
import struct

import pytest

from app.labs.graduation import config
from app.labs.graduation.sources import CurveRPC

#: Real base58 mints, so the PDA derivation is exercised rather than stubbed.
MINTS = [
    "Bjsxb2QErbB4rhpSRsUgtNBPPri24R3AK58tQwjvpump",
    "9Wm4XeBdnSTBWfvKaq2rGa6YDkFBJKBpXcbmVkZ9pump",
    "EABHq2ZXYCCBUw8LAJTgaMFYPifVm3sBcgicpt29pump",
    "AaCBdbi8DiBvWiSjTG2xkkqeshDCSifsvYqZrkpDpump",
]


def account(real_token: int) -> dict:
    """A curve account whose real-token reserve identifies it."""
    raw = (config.CURVE_DISCRIMINATOR
           + struct.pack("<QQQQQ", 279_900_000_000_000 + real_token,
                         30_000_000_000, real_token, 0,
                         1_000_000_000_000_000)
           + b"\x00" + b"\x00" * 102)
    return {"data": [base64.b64encode(raw).decode(), "base64"]}


#: mint -> the reserve that identifies its own account.
OWN = {m: (i + 1) * 1_000_000_000 for i, m in enumerate(MINTS)}


class ScriptedRPC:
    """Answers per address, and can be told to fail the first call."""

    def __init__(self, *, fail_first: bool = False, short: bool = False) -> None:
        self.fail_first = fail_first
        self.short = short
        self.calls = 0

    async def get_multiple_accounts(self, addresses):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("node said no")
        values = [account(self._reserve(a)) for a in addresses]
        return values[:-1] if self.short else values

    def _reserve(self, address: str) -> int:
        # Reverse the derivation: whichever mint derives this address owns it.
        for mint, reserve in OWN.items():
            if _rpc_for_test().address_for(mint) == address:
                return reserve
        raise AssertionError(f"unknown address {address}")


_CACHED: CurveRPC | None = None


def _rpc_for_test() -> CurveRPC:
    global _CACHED
    if _CACHED is None:
        _CACHED = CurveRPC(rpc=object())
    return _CACHED


@pytest.fixture(autouse=True)
def _small_batches():
    """Two addresses a call, so four mints span two batches."""
    original = config.MAX_ACCOUNTS_PER_CALL
    config.MAX_ACCOUNTS_PER_CALL = 2
    yield
    config.MAX_ACCOUNTS_PER_CALL = original


async def test_every_mint_gets_its_own_account() -> None:
    rpc = CurveRPC(rpc=ScriptedRPC())
    got = await rpc.fetch(MINTS)
    assert len(got) == len(MINTS)
    for mint in MINTS:
        assert got[mint] is not None
        assert got[mint].real_token_reserves == OWN[mint], mint


async def test_a_failed_batch_does_not_shift_every_later_mint() -> None:
    """The bug. The first window failed, `out` stayed empty, and the second
    window was then read from the FIRST window's position — so mints 3 and 4
    were handed the accounts belonging to mints 1 and 2. In production that
    silently gave 508 of 1391 tokens another token's progress.
    """
    rpc = CurveRPC(rpc=ScriptedRPC(fail_first=True))
    got = await rpc.fetch(MINTS)

    # The failed window is ABSENT — "no answer", not "no curve".
    assert MINTS[0] not in got
    assert MINTS[1] not in got
    # And the window that did answer is attributed correctly, not shifted.
    assert got[MINTS[2]].real_token_reserves == OWN[MINTS[2]]
    assert got[MINTS[3]].real_token_reserves == OWN[MINTS[3]]
    assert rpc.failures == 1


async def test_a_short_response_is_refused_rather_than_misaligned() -> None:
    """Positional pairing is only sound when the lengths match. A gap is
    recoverable; a wrong reading is not."""
    rpc = CurveRPC(rpc=ScriptedRPC(short=True))
    got = await rpc.fetch(MINTS)
    assert got == {}
    assert rpc.failures == 2          # both windows refused
    assert "returned" in (rpc.last_failure or "")


async def test_an_absent_account_is_none_not_missing() -> None:
    class Absent(ScriptedRPC):
        async def get_multiple_accounts(self, addresses):
            self.calls += 1
            return [None] * len(addresses)

    rpc = CurveRPC(rpc=Absent())
    got = await rpc.fetch(MINTS)
    assert set(got) == set(MINTS)
    assert all(v is None for v in got.values())
