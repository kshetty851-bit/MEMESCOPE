"""PumpPortal message -> row. Pure: no clock, no socket, no session.

Only TWO message kinds are parsed here, because only two are subscribed:
`create` (discovery) and the migration event (the graduation timestamp). Both
subscriptions are free. Trades are not read from this feed at all — progress
comes from the chain, in `polling.py`.

Field names are the ones the live socket sends, counted over 121 consecutive
`create` messages:

    signature  121/121    marketCapSol  121/121    name/symbol/uri  104/121
    mint       121/121    pool          121/121    bondingCurveKey  102/121
    txType     121/121    initialBuy    121/121    vTokensInBondingCurve 31/50
    traderPublicKey 121/121 solAmount   121/121    tokensInPool          19/121

Three consequences drive this module:

* **`name` and `symbol` are optional.** A parser that required them would drop
  one launch in seven.
* **There is no timestamp and no slot in ANY message.** Every `ts` here is the
  recorder's receipt time, passed in.
* **`bondingCurveKey` is present on only 102 of 121, and is not reliable when
  it is.** Measured on 15 consecutive launches: three carried the SAME key for
  three unrelated mints, and that address is a zero-length System Program
  account rather than a curve. It is recorded and NEVER used. The address this
  lab polls is DERIVED from the mint, which is correct for every launch.

## The migration shape is not verified

PumpPortal publishes no example payload for `subscribeMigration`. The names
used here are the documented ones, and each also appears in a `create` message,
which is the same producer. `unexpected_fields()` exists so the first live run
REPORTS the difference instead of silently writing nulls: the recorder logs it
once and the health route counts it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.labs.graduation import config

_CREATE = "create"
#: PumpPortal publishes no example migration payload. These are the plausible
#: spellings; `unexpected_fields` reports whatever actually turns up.
_MIGRATION_TYPES = frozenset({"migrate", "migration", "migrated"})

#: How a launch's quote denomination is read. A USDC-denominated curve holds
#: USDC in the reserve the SOL field normally carries; the account itself
#: carries no denomination flag in the bytes this lab decodes, so this message
#: is the only place the distinction is observable. First match wins.
_QUOTE_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (config.QUOTE_USDC, ("vUsdcInBondingCurve", "vUSDCInBondingCurve",
                         "usdcAmount", "usdcInPool")),
    (config.QUOTE_SOL, ("vSolInBondingCurve", "solAmount", "solInPool")),
)

KNOWN_MIGRATION_FIELDS = frozenset({
    "signature", "mint", "txType", "pool", "traderPublicKey", "slot",
    "marketCapSol", "bondingCurveKey", "name", "symbol", "uri",
})


@dataclass(frozen=True, slots=True)
class TokenRow:
    mint: str
    name: str | None
    symbol: str | None
    creator: str | None
    launch_pool: str | None
    bonding_curve_key: str | None
    quote_currency: str
    first_seen_at: datetime


@dataclass(frozen=True, slots=True)
class MigrationRow:
    mint: str
    ts: datetime
    pool: str | None
    signature: str | None
    raw: dict


def _text(value: object, limit: int) -> str | None:
    """A non-empty string, trimmed to the column's width. The feed has sent
    names longer than the column, and a truncated name beats a rejected row."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed[:limit] or None


def quote_currency(msg: dict) -> str:
    """`SOL` or `USDC`, from whichever quote field the launch carries.

    Defaults to SOL rather than to None: every curve observed so far is
    SOL-denominated, and a null here would force every reader to handle a third
    case that has never occurred. A USDC curve is detected by its own field
    names, which is the only signal there is.
    """
    for currency, names in _QUOTE_FIELDS:
        if any(name in msg for name in names):
            return currency
    return config.QUOTE_SOL


def parse_token(msg: dict, *, received_at: datetime) -> TokenRow | None:
    """A `create` message, or None if it is not one or carries no mint."""
    if msg.get("txType") != _CREATE:
        return None
    mint = _text(msg.get("mint"), 64)
    if not mint:
        return None
    return TokenRow(
        mint=mint,
        name=_text(msg.get("name"), 128),
        symbol=_text(msg.get("symbol"), 32),
        creator=_text(msg.get("traderPublicKey"), 64),
        launch_pool=_text(msg.get("pool"), 32),
        bonding_curve_key=_text(msg.get("bondingCurveKey"), 64),
        quote_currency=quote_currency(msg),
        first_seen_at=received_at,
    )


def parse_migration(msg: dict, *, received_at: datetime) -> MigrationRow | None:
    """A migration message, or None.

    Recognised by `txType` alone. One socket carries both subscriptions, so
    there is no other way to tell which one a message arrived on — and a
    fallback that guessed from `pool == "pump-amm"` would swallow anything that
    happened to mention the graduated AMM.
    """
    if msg.get("txType") not in _MIGRATION_TYPES:
        return None
    mint = _text(msg.get("mint"), 64)
    if not mint:
        return None
    return MigrationRow(
        mint=mint,
        ts=received_at,
        pool=_text(msg.get("pool"), 16),
        signature=_text(msg.get("signature"), 96),
        raw=msg,
    )


def unexpected_fields(msg: dict) -> frozenset[str]:
    """Field names in a migration payload never seen before.

    The migration shape could not be observed, so this is how the first live
    run tells us what it really sends, instead of us finding out from a column
    full of nulls months later. `create` is not checked: its shape IS verified.
    """
    if msg.get("txType") in _MIGRATION_TYPES:
        return frozenset(msg) - KNOWN_MIGRATION_FIELDS
    return frozenset()


def is_subscription_ack(msg: dict) -> bool:
    """PumpPortal answers every subscribe with a bare `{"message": ...}`."""
    return "message" in msg and "txType" not in msg
