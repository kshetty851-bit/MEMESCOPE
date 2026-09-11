"""Message parsing, against the recorded fixture file.

Only two message kinds are parsed now, because only two are subscribed:
`create` and the migration event. Both subscriptions are free. There is no
trade parsing anywhere in this package — progress comes from the chain.

The `create` fixtures are REAL messages off the live socket. The migration ones
are marked SYNTHETIC in their own `_note`, because PumpPortal publishes no
example payload for `subscribeMigration`. `_note` is stripped on load so it
never reaches the parser.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime

from app.labs.graduation import parse

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "messages.json"


def load() -> list[dict]:
    raw = json.loads(FIXTURES.read_text())
    return [{k: v for k, v in m.items() if k != "_note"} for m in raw]


MESSAGES = load()


def by_signature(prefix: str) -> dict:
    for message in MESSAGES:
        if str(message.get("signature", "")).startswith(prefix):
            return message
    raise AssertionError(f"no fixture message with signature {prefix!r}")


# --- acks ---------------------------------------------------------------------

def test_acks_are_recognised_and_are_not_rows() -> None:
    acks = [m for m in MESSAGES if parse.is_subscription_ack(m)]
    assert len(acks) == 1
    for ack in acks:
        assert parse.parse_token(ack, received_at=NOW) is None
        assert parse.parse_migration(ack, received_at=NOW) is None


# --- creates ------------------------------------------------------------------

def test_real_create_parses_every_field() -> None:
    row = parse.parse_token(by_signature("4D7BVU"), received_at=NOW)
    assert row is not None
    assert row.mint == "Bjsxb2QErbB4rhpSRsUgtNBPPri24R3AK58tQwjvpump"
    assert row.symbol == "ILY"
    assert row.name == "There's no meme, ILY"
    assert row.creator == "jAWjap1jBXDm8wL2Qfped3j4ASa5nhKv5vmwm4gmTx4"
    assert row.launch_pool == "pump"
    assert row.bonding_curve_key == "3XWT7fTxe9xkKsGYjNZ3AVoaomUVpxw2hDyeo3Rupwfy"
    assert row.quote_currency == "SOL"
    assert row.first_seen_at == NOW  # receipt time; the feed sends no clock


def test_create_without_name_or_symbol_is_kept() -> None:
    """17 of 121 observed launches had neither. Requiring them drops one in
    seven — including every `bonk` launch in that sample."""
    row = parse.parse_token(by_signature("La32Yc"), received_at=NOW)
    assert row is not None
    assert row.name is None and row.symbol is None
    assert row.launch_pool == "bonk"
    assert row.bonding_curve_key is None  # absent from 19 of 121


def test_a_migration_is_not_a_create() -> None:
    assert parse.parse_token(by_signature("sigMigrate0"), received_at=NOW) is None


# --- the quote denomination ---------------------------------------------------

def test_a_usdc_curve_is_detected_from_its_field_names() -> None:
    """The curve ACCOUNT carries no denomination flag in the bytes this lab
    decodes, so the launch message is the only place the distinction is
    observable. Progress is unaffected — it is a function of the token side."""
    row = parse.parse_token(by_signature("sigUsdcCreate"), received_at=NOW)
    assert row is not None
    assert row.quote_currency == "USDC"


def test_denomination_defaults_to_sol_rather_than_to_none() -> None:
    """Every curve observed so far is SOL-denominated. A null here would force
    every reader to handle a third case that has never occurred."""
    assert parse.quote_currency({}) == "SOL"
    assert parse.quote_currency({"vSolInBondingCurve": 30.0}) == "SOL"
    assert parse.quote_currency({"vUsdcInBondingCurve": 12500.0}) == "USDC"


# --- migrations ---------------------------------------------------------------

def test_migration_parses_and_keeps_the_raw_message() -> None:
    """The shape is unverified, so `raw` is the appeal against a misreading."""
    row = parse.parse_migration(by_signature("sigMigrate0"), received_at=NOW)
    assert row is not None
    assert row.mint == "Bjsxb2QErbB4rhpSRsUgtNBPPri24R3AK58tQwjvpump"
    assert row.pool == "pump-amm"
    assert row.ts == NOW
    assert row.raw["txType"] == "migrate"


def test_a_message_without_a_mint_is_dropped() -> None:
    assert parse.parse_migration({"txType": "migrate"}, received_at=NOW) is None
    assert parse.parse_token({"txType": "create"}, received_at=NOW) is None


def test_every_plausible_migration_spelling_is_accepted() -> None:
    """No example payload was ever published, so all three are taken."""
    for tx in ("migrate", "migration", "migrated"):
        row = parse.parse_migration({"txType": tx, "mint": "m"}, received_at=NOW)
        assert row is not None, tx
    assert parse.parse_migration({"txType": "buy", "mint": "m"},
                                 received_at=NOW) is None


# --- shape drift --------------------------------------------------------------

def test_unknown_fields_are_reported_not_swallowed() -> None:
    """The migration shape could not be observed. This is how the first live
    run tells us what it really sends."""
    assert parse.unexpected_fields(by_signature("sigMigrateNew")) == {"blockTime"}
    assert parse.unexpected_fields(by_signature("sigMigrate0")) == frozenset()
    # A create is not checked: its shape IS verified.
    assert parse.unexpected_fields(by_signature("4D7BVU")) == frozenset()


def test_a_migration_naming_usdc_is_not_a_graduation() -> None:
    """The live feed sent exactly this on 2026-09-11. Nothing downstream could
    tell it from a real graduation: the sampler priced USDC at $1.00 for an
    hour and the paper book spent a $100 slot on it. Rejected at the parse,
    which is the one place every path runs through."""
    msg = {"txType": "migrate", "pool": "pump-amm",
           "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
           "signature": "3bcLnw55hi7qhownNGFqyTwVCJ128uXzm5dWKaAJSyix"}
    assert parse.parse_migration(msg, received_at=NOW) is None
    # And the same mint arriving as a launch is not a launch either.
    assert parse.parse_token({**msg, "txType": "create"}, received_at=NOW) is None
    # A real graduation still parses — the guard is a denylist, not a filter.
    real = {**msg, "mint": "H4TqHhLbCqmcpV8GZqtv9XJhWiWhJrc4XVksKbjApump"}
    assert parse.parse_migration(real, received_at=NOW) is not None
