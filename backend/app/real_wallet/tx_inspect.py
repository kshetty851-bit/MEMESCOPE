"""What the bytes about to be signed actually are, and whether we authorised them.

## The gap this closes

`FileExecutionSigner.sign_jupiter_transaction` answers exactly one question:
"is this a transaction only my wallet can pay for". `order_evidence.verify`
answers "is the JSON that came with it the swap I authorised". Neither answers
"do the bytes contain only programs I approve", and that is the question that
decides whether a compromised or substituted `/order` response can drain the
wallet through a program nobody reviewed.

So it is asked here, on the decoded message, before signing.

## Why the program id must come from the static keys

A v0 message resolves account keys from two places: the static `account_keys`
array carried in the transaction, and addresses loaded from address lookup
tables whose *contents are not in the bytes*. An ALT-resolved program id is
therefore unauditable offline — the table can be read only from chain, and it
can be modified by its authority between our read and the validator's.

A real mainnet Jupiter swap was assembled and decoded to check this is not a
theoretical constraint (2026-08-22, USDC→SOL, `lite-api.jup.ag/swap/v1/swap`):
all four top-level program ids — ComputeBudget, Associated Token Account,
Jupiter v6 aggregator, SPL Token — sat in the static keys, and the lookup table
supplied only the route's *accounts*. So requiring static program ids costs
nothing on the real route and refuses the one shape we cannot audit.

`PROGRAM_FROM_LOOKUP_TABLE` is the reason code for that refusal. It is
fail-closed by construction: an index past the static keys cannot be resolved,
so it cannot be checked, so it is refused.

## What this cannot do

An allowlisted program can still be invoked with the wrong accounts, and CPI
targets are not visible here at all. That is why this is one layer of three:
semantics live in `order_evidence.py`, bytes live here, and the only proof that
survives everything is `reconciliation.py` reading the chain afterwards.

Pure: no I/O, no clock, no database.
"""

from __future__ import annotations

import hashlib
from base64 import b64decode
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from solders.transaction import VersionedTransaction

#: Programs a real swap transaction may invoke at the top level.
#:
#: Observed on a decoded mainnet Jupiter route (see module docstring). Anything
#: outside this set is refused rather than reasoned about, because "which
#: unknown program is safe" is not a judgement a signing boundary should make.
#: Overridable through `REAL_WALLET_ALLOWED_PROGRAM_IDS` so a canary operator
#: can widen it deliberately after decoding a real order — never silently.
DEFAULT_ALLOWED_PROGRAMS: frozenset[str] = frozenset(
    {
        # System — account creation and SOL wrap/unwrap.
        "11111111111111111111111111111111",
        # Compute budget — priority fee and unit limit.
        "ComputeBudget111111111111111111111111111111",
        # SPL Token and Token-2022.
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
        # Associated Token Account — ATA creation for the output mint.
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
        # Jupiter v6 aggregator — the swap itself.
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
    }
)


class TxRejection(StrEnum):
    """Why a transaction may not be signed. Persisted verbatim on the intent."""

    MALFORMED = "TX_MALFORMED"
    NOT_VERSIONED = "TX_NOT_VERSIONED"
    UNEXPECTED_SIGNER_COUNT = "TX_UNEXPECTED_SIGNER_COUNT"
    FEE_PAYER_MISMATCH = "TX_FEE_PAYER_MISMATCH"
    NO_INSTRUCTIONS = "TX_NO_INSTRUCTIONS"
    PROGRAM_NOT_ALLOWED = "TX_PROGRAM_NOT_ALLOWED"
    PROGRAM_FROM_LOOKUP_TABLE = "TX_PROGRAM_FROM_LOOKUP_TABLE"
    ALREADY_SIGNED = "TX_ALREADY_SIGNED"
    INTENT_FINGERPRINT_MISMATCH = "TX_INTENT_FINGERPRINT_MISMATCH"


class TransactionRejectedError(RuntimeError):
    """The decoded transaction is not the one that was authorised."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__(",".join(reasons) or "transaction_rejected")
        self.reasons = reasons


@dataclass(frozen=True, slots=True)
class TransactionFacts:
    """Everything auditable from the bytes alone. No chain read, no guess."""

    fee_payer: str
    required_signatures: int
    #: Top-level program ids that resolved from the static keys.
    program_ids: tuple[str, ...]
    #: True when any instruction's program id indexed past the static keys.
    program_from_lookup_table: bool
    #: Lookup tables the message references, for the audit row.
    lookup_tables: tuple[str, ...]
    #: SHA-256 of the message bytes. Stable across signing (a signature is
    #: appended to the transaction, never mixed into the message), so it is a
    #: usable replay key: the same message signed twice is the same value.
    message_fingerprint: str
    #: Populated only when at least one signature slot is already filled.
    already_signed: bool


@dataclass(frozen=True, slots=True)
class TransactionVerdict:
    approved: bool
    reason_codes: tuple[str, ...]
    facts: TransactionFacts | None

    def require(self) -> TransactionFacts:
        if not self.approved or self.facts is None:
            raise TransactionRejectedError(self.reason_codes)
        return self.facts


def inspect(encoded_transaction: str) -> TransactionFacts:
    """Decode one base64 v0 transaction into auditable facts, or refuse."""
    try:
        raw = b64decode(encoded_transaction, validate=True)
        transaction = VersionedTransaction.from_bytes(raw)
    except Exception as exc:
        raise TransactionRejectedError((TxRejection.MALFORMED,)) from exc

    message = transaction.message
    static_keys = list(message.account_keys)
    lookups = list(getattr(message, "address_table_lookups", None) or ())

    programs: list[str] = []
    from_lookup = False
    for instruction in message.instructions:
        index = int(instruction.program_id_index)
        # Past the static keys means the id would have to be resolved from a
        # table we cannot read here. Unauditable, therefore refused.
        if index >= len(static_keys):
            from_lookup = True
            continue
        programs.append(str(static_keys[index]))

    # `signatures` is pre-sized with the required count; an all-zero entry is
    # an empty slot, so "already signed" is any non-zero one.
    already_signed = any(bytes(sig) != bytes(64) for sig in transaction.signatures)

    return TransactionFacts(
        fee_payer=str(static_keys[0]) if static_keys else "",
        required_signatures=int(message.header.num_required_signatures),
        program_ids=tuple(dict.fromkeys(programs)),
        program_from_lookup_table=from_lookup,
        lookup_tables=tuple(str(lookup.account_key) for lookup in lookups),
        message_fingerprint=hashlib.sha256(bytes(message)).hexdigest(),
        already_signed=already_signed,
    )


def verify(
    *,
    encoded_transaction: str,
    expected_fee_payer: str,
    allowed_programs: frozenset[str] | None = None,
    expected_intent_fingerprint: str | None = None,
    intent_fingerprint_value: str | None = None,
    seen_message_fingerprints: frozenset[str] = frozenset(),
) -> TransactionVerdict:
    """Decide whether these exact bytes may be signed.

    Reasons accumulate rather than short-circuiting, for the same reason they do
    in `order_evidence.verify`: a transaction that is wrong in three ways is a
    different event from one that is merely stale, and the audit row should say
    which happened.

    `seen_message_fingerprints` is the replay guard. A message this wallet has
    already signed is refused outright — not retried, not resubmitted — because
    a second signature over the same message is a second chance for the same
    transaction to land.
    """
    allowed = DEFAULT_ALLOWED_PROGRAMS if allowed_programs is None else allowed_programs
    try:
        facts = inspect(encoded_transaction)
    except TransactionRejectedError as exc:
        return TransactionVerdict(False, exc.reasons, None)

    reasons: list[str] = []
    if facts.required_signatures != 1:
        reasons.append(TxRejection.UNEXPECTED_SIGNER_COUNT)
    if not expected_fee_payer or facts.fee_payer != expected_fee_payer:
        reasons.append(TxRejection.FEE_PAYER_MISMATCH)
    if not facts.program_ids and not facts.program_from_lookup_table:
        reasons.append(TxRejection.NO_INSTRUCTIONS)
    if facts.program_from_lookup_table:
        reasons.append(TxRejection.PROGRAM_FROM_LOOKUP_TABLE)
    for program in facts.program_ids:
        if program not in allowed:
            reasons.append(f"{TxRejection.PROGRAM_NOT_ALLOWED}:{program}")
    if facts.already_signed:
        reasons.append(TxRejection.ALREADY_SIGNED)
    if facts.message_fingerprint in seen_message_fingerprints:
        reasons.append(TxRejection.ALREADY_SIGNED)
    if (
        expected_intent_fingerprint is not None
        and intent_fingerprint_value != expected_intent_fingerprint
    ):
        reasons.append(TxRejection.INTENT_FINGERPRINT_MISMATCH)

    return TransactionVerdict(
        approved=not reasons,
        reason_codes=tuple(dict.fromkeys(reasons)),
        facts=facts,
    )


def intent_fingerprint(
    *,
    intent_id: str,
    side: str,
    wallet_public_key: str,
    input_mint: str,
    output_mint: str,
    input_amount_raw: int,
    request_id: str,
    max_slippage_bps: int,
) -> str:
    """One value binding a signing request to the intent that authorised it.

    Every component is server-derived — none of it comes from the Jupiter
    response — so an attacker who can substitute an `/order` reply cannot
    reproduce the fingerprint for a different swap. The signer recomputes this
    from the authoritative intent it loads itself, and refuses when the caller's
    value disagrees; a caller therefore cannot nominate what it is signing.
    """
    parts = (
        intent_id,
        side,
        wallet_public_key,
        input_mint,
        output_mint,
        str(int(input_amount_raw)),
        request_id,
        str(int(max_slippage_bps)),
    )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def lamports_from_sol(sol: Decimal) -> int:
    """Convert a SOL figure to integer lamports, refusing anything inexact.

    Canary limits are compared in lamports rather than in floating SOL: a limit
    that rounds is a limit that can be crossed by rounding.
    """
    scaled = sol.scaleb(9)
    if scaled != scaled.to_integral_value():
        raise ValueError("sol_amount_is_not_representable_in_lamports")
    return int(scaled)
