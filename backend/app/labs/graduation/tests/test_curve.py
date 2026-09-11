"""PDA derivation, account decoding, and the progress arithmetic.

Pure, so these are plain asserts with no database and no network. Every number
here is pinned by something real:

* the PDA vector is a `bondingCurveKey` the live launch feed reported for a
  mint, so the derivation is checked against pump.fun's own answer;
* the account bytes are a REAL `getMultipleAccounts` response, saved verbatim;
* `793100000000000` is the constant the platform's own
  `app/services/curve/state.py` reads off mainnet.
"""

from __future__ import annotations

import base64
import json
import pathlib
import struct
from decimal import Decimal

import pytest

from app.labs.graduation import config, curve
from app.services.curve.pda import bonding_curve_address
from app.services.curve.state import CurveState

D = Decimal
FIXTURES = pathlib.Path(__file__).parent / "fixtures"
ACCOUNT = json.loads((FIXTURES / "curve_account.json").read_text())
RAW = base64.b64decode(ACCOUNT["rpc_value"]["data"][0])

#: 1,073,000,000,000,000 - pct * 793,100,000,000,000, worked out by hand. RAW
#: base units: the account counts in them, unlike the websocket that this lab
#: used to read, which sent whole tokens.
EXACT = [
    ("1073000000000000", "0.000"),    # nobody has bought
    ("914380000000000", "20.000"),
    ("755760000000000", "40.000"),
    ("517830000000000", "70.000"),    # the tracking threshold
    ("438520000000000", "80.000"),
    ("359210000000000", "90.000"),
    ("319555000000000", "95.000"),
    ("279900000000000", "100.000"),   # the curve is full
]


def state(v_token: int = 1073000000000000, v_sol: int = 30000000006,
          real_token: int = 793100000000000, real_sol: int = 6,
          supply: int = 1000000000000000, complete: bool = False) -> CurveState:
    return CurveState(
        virtual_token_reserves=v_token, virtual_sol_reserves=v_sol,
        real_token_reserves=real_token, real_sol_reserves=real_sol,
        token_total_supply=supply, complete=complete,
    )


def account_bytes(**kwargs) -> bytes:
    """Rebuild a curve account from field values, discriminator and all."""
    s = state(**kwargs)
    return (config.CURVE_DISCRIMINATOR + struct.pack(
        "<QQQQQ", s.virtual_token_reserves, s.virtual_sol_reserves,
        s.real_token_reserves, s.real_sol_reserves, s.token_total_supply)
        + bytes([1 if s.complete else 0]) + b"\x00" * 102)


# --- the PDA ------------------------------------------------------------------

def test_pda_matches_what_pump_fun_itself_reported() -> None:
    """The launch feed sends `bondingCurveKey` on 102 of 121 messages. This is
    that field, for that mint, reproduced locally from the seeds alone.

    Deriving rather than looking up is what makes polling affordable: the whole
    watch set is one `getMultipleAccounts` per hundred tokens because there is
    no address lookup to do first.
    """
    derived = bonding_curve_address(ACCOUNT["mint"], program_id=config.PUMP_PROGRAM_ID)
    assert derived == ACCOUNT["curve_address"]


def test_pda_is_deterministic() -> None:
    first = bonding_curve_address(ACCOUNT["mint"], program_id=config.PUMP_PROGRAM_ID)
    second = bonding_curve_address(ACCOUNT["mint"], program_id=config.PUMP_PROGRAM_ID)
    assert first == second


def test_a_different_mint_derives_a_different_curve() -> None:
    other = bonding_curve_address("9Wm4XeBdnSTBWfvKaq2rGa6YDkFBJKBpXcbmVkZ9pump",
                                  program_id=config.PUMP_PROGRAM_ID)
    assert other != ACCOUNT["curve_address"]


# --- decoding -----------------------------------------------------------------

def test_the_real_account_decodes_to_the_seeded_constants() -> None:
    """A live, untouched curve. Every field is at its seeded value, which is
    what pins all three constants at once."""
    assert len(RAW) == ACCOUNT["account_length"] == 151
    assert RAW[:8].hex() == "17b7f83760d8ac60"
    decoded = curve.decode(RAW)
    assert decoded is not None
    expected = ACCOUNT["decoded"]
    assert decoded.virtual_token_reserves == expected["virtual_token_reserves"]
    assert decoded.virtual_sol_reserves == expected["virtual_sol_reserves"]
    assert decoded.real_token_reserves == expected["real_token_reserves"]
    assert decoded.token_total_supply == expected["token_total_supply"]
    assert decoded.complete is False


def test_the_account_is_151_bytes_and_the_49_byte_prefix_is_what_is_read() -> None:
    """`state.ACCOUNT_SIZE` is 49 and the account is 151. That is not a bug:
    the check is a MINIMUM, the five reserves and the flag live in the prefix,
    and the 102 bytes past it are deliberately not decoded — reading a field
    this lab has never verified would be inventing data."""
    assert curve.decode(RAW[:49]) is not None
    assert curve.decode(RAW[:48]) is None


def test_a_wrong_discriminator_is_refused() -> None:
    """Deriving an address does not prove what is stored there. `parse` never
    looks at the first eight bytes, so without this check a PDA holding some
    other Anchor account would decode to five plausible integers."""
    wrong = bytes.fromhex("0000000000000000") + RAW[8:]
    assert curve.decode(wrong) is None
    assert curve.decode(None) is None
    assert curve.decode(b"") is None


def test_progress_from_the_decoded_account() -> None:
    """The path the poller actually takes: bytes in, percentage out."""
    assert curve.progress_of(curve.decode(RAW)) == D("0.000")
    assert curve.progress_of(curve.decode(
        account_bytes(real_token=237930000000000))) == D("70.000")
    assert curve.progress_of(curve.decode(account_bytes(real_token=0))) == D("100.000")
    assert curve.progress_of(None) is None


def test_a_completed_curve_reads_100_by_statement_not_by_luck() -> None:
    """A completed curve ZEROES every reserve. Zero real tokens would compute
    to 100% anyway, so `complete` is checked first and the row says so rather
    than arriving at the right answer by accident."""
    done = state(v_token=0, v_sol=0, real_token=0, real_sol=0, complete=True)
    assert curve.progress_of(done) == 100
    assert curve.market_cap_quote(done) is None  # no division by zero


# --- the arithmetic -----------------------------------------------------------

@pytest.mark.parametrize(("v_tokens", "expected"), EXACT)
def test_progress_at_each_level(v_tokens: str, expected: str) -> None:
    assert curve.progress_pct(D(v_tokens), pool="pump") == D(expected)


def test_the_curve_floor_is_279_9m_not_206_9m() -> None:
    """The constant the brief got wrong, asserted directly.

    206,900,000 is 1,000,000,000 - 793,100,000: the supply held back to seed
    the AMM at migration, which is never in the curve account. Using it as the
    floor reads a FULL curve as 91.57% and would make the 95% and 100%
    checkpoints unreachable — the exact band this lab exists to measure.
    """
    assert curve.curve_floor_tokens() == D("279900000000000")

    wrong_floor = D("206900000000000")
    sold = config.INITIAL_VIRTUAL_TOKEN_RESERVES - curve.curve_floor_tokens()
    misread = sold / (config.INITIAL_VIRTUAL_TOKEN_RESERVES - wrong_floor) * 100
    assert round(misread, 2) == D("91.57")
    assert curve.progress_pct(curve.curve_floor_tokens(), pool="pump") == 100


def test_this_module_agrees_with_the_platform_curve_service() -> None:
    """Two definitions of the same quantity, pinned together.

    `app/services/curve/state.py` computes progress for the platform's own
    collector. If this lab's overridable constants ever disagree with it, a
    join between `grad_curve_samples` and the platform's curve snapshots would
    be comparing two different numbers with the same name. This fails first.
    """
    for raw_real, expected in [
        ("793100000000000", "0.000"), ("237930000000000", "70.000"),
        ("79310000000000", "90.000"), ("0", "100.000"),
    ]:
        reading = state(real_token=int(raw_real))
        assert curve.progress_of(reading) == D(expected)
        assert (reading.progress * 100).quantize(D("0.001")) == D(expected)


def test_progress_is_clamped_both_ways() -> None:
    assert curve.progress_pct(D("1000"), pool="pump") == 100
    assert curve.progress_pct(D("2000000000000000"), pool="pump") == 0


def test_unmeasurable_is_none_not_zero() -> None:
    """`None` says the position is unknown; `0` says nobody has bought."""
    assert curve.progress_pct(None, pool="pump") is None
    assert curve.progress_pct(D("900000000000000"), pool="bonk") is None
    assert curve.progress_pct(D("1073000000000000"), pool="pump") == 0


def test_misconfigured_constants_refuse_rather_than_divide() -> None:
    original = config.INITIAL_REAL_TOKEN_RESERVES
    config.INITIAL_REAL_TOKEN_RESERVES = D(0)
    try:
        assert curve.progress_pct(D("517830000000000"), pool="pump") is None
        assert curve.progress_pct_from_real(D("1")) is None
    finally:
        config.INITIAL_REAL_TOKEN_RESERVES = original


def test_market_cap_comes_from_the_curve_itself() -> None:
    """`virtual_quote / virtual_token * total_supply`. On the live seeded
    account that is 27.96 SOL — roughly $5.6k, which is what a fresh pump.fun
    token is worth, so the units are right way up."""
    cap = curve.market_cap_quote(curve.decode(RAW))
    assert cap is not None
    assert D("27.9") < cap < D("28.0")


def test_quote_reserves_are_named_quote_because_they_may_be_usdc() -> None:
    v_quote, real_quote = curve.quote_reserves(curve.decode(RAW))
    assert v_quote == D("30.000000006")
    assert real_quote == D("0.000000006")
    assert curve.quote_reserves(None) == (None, None)


def test_whole_tokens_divides_the_base_units_down() -> None:
    assert curve.whole_tokens(1073000000000000) == D("1073000000")
    assert curve.whole_tokens(None) is None


def test_crossed_fires_once_per_level() -> None:
    """A token jumping 68 -> 94 between two polls owes three checkpoints, and
    one oscillating around a level owes none the second time."""
    assert curve.crossed(None, D("94"), D("70")) is True
    assert curve.crossed(None, D("94"), D("90")) is True
    assert curve.crossed(None, D("94"), D("95")) is False
    assert curve.crossed(D("94"), D("94"), D("90")) is False
    assert curve.crossed(D("69"), D("70"), D("70")) is True
    assert curve.crossed(D("94"), None, D("70")) is False
