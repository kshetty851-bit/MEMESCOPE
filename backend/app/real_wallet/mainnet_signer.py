"""Isolated mainnet signer service. Holds the key; proves identity; signs nothing yet.

## Why this exists

The ARMED rehearsal has to answer "is the signer mounted, and does it hold the
key we pinned?" — and it cannot answer that by loading the key itself, because
every application container is deliberately denied a signer path. The devnet
signer already solved the shape of this problem: a separate process owns the
secret, the API owns only a Unix socket, and an ID crosses between them rather
than key material. This is the same architecture for the mainnet wallet.

## What it does

Two operations. `identity` returns the public key it holds and whether that
matches the one production pinned — enough to turn `signer_ready` from an
assumption into a measurement. `sign` produces one signature over one intent.

**`sign` trusts nothing it is handed.** It receives an intent ID, never a
transaction: it reloads the intent from Postgres itself, re-verifies the chain,
re-checks that every top-level program is allowlisted, re-computes the intent
fingerprint, and refuses a message this wallet has signed before. A caller that
has been compromised can therefore ask for a signature over a transaction the
signer will not produce, which is the entire reason the boundary exists.

## What it refuses to start on

It verifies the chain before it will answer at all, using the stricter mainnet
check: the RPC host must be on the allowlist *before* the endpoint is trusted to
say which chain it is. Asking an unapproved host to identify itself and then
believing the answer is not verification. A signer that answers on the wrong
chain is worse than one that does not answer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.real_wallet import tx_inspect
from app.real_wallet.live_readiness import ExecutionState
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.network import require_verified_network
from app.real_wallet.signer import (
    ExecutionTransactionValidationError,
    FileExecutionSigner,
)
from app.services.rpc.standard import StandardSolanaRPC

logger = get_logger(__name__)

#: The one operation this service performs.
IDENTITY = "identity"


class MainnetSignerError(RuntimeError):
    """The isolated mainnet signer refused."""


def _allowed_programs() -> frozenset[str]:
    """Configured allowlist, or the reviewed defaults. Never "anything"."""
    configured = settings.REAL_WALLET_ALLOWED_PROGRAM_IDS
    return frozenset(configured) if configured else tx_inspect.DEFAULT_ALLOWED_PROGRAMS


def _secret_file() -> Path:
    """The key path, read only here. No application container may set this."""
    value = os.environ.get("MAINNET_SIGNER_FILE", "").strip()
    if not value:
        raise MainnetSignerError("mainnet_signer_secret_file_not_configured")
    path = Path(value)
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise MainnetSignerError("mainnet_signer_secret_file_unavailable") from exc
    # A key readable by group or other is a key that has already leaked as far
    # as this process can tell, and it refuses rather than assuming otherwise.
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise MainnetSignerError("mainnet_signer_secret_file_permissions")
    return path


async def _verified_chain() -> str:
    """Prove the configured chain before answering anything about the key."""
    if settings.REAL_WALLET_NETWORK != "mainnet":
        raise MainnetSignerError("mainnet_signer_requires_mainnet")
    rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
    async with rpc:
        status = await require_verified_network(
            rpc,
            configured_network=settings.REAL_WALLET_NETWORK,
            rpc_url=settings.REAL_WALLET_RPC_URL,
            allowed_rpc_hosts=settings.REAL_WALLET_ALLOWED_RPC_HOSTS,
        )
    return status.observed_genesis_hash or ""


async def identity() -> dict[str, Any]:
    """Who is mounted here, and does it match what production pinned?

    Returns the PUBLIC key only. The secret never leaves this process, and
    nothing here can produce a signature.
    """
    genesis = await _verified_chain()
    expected = settings.REAL_WALLET_PUBLIC_KEY.strip()
    if not expected:
        raise MainnetSignerError("mainnet_signer_pinned_key_not_configured")
    # `load` derives the public key from the secret and compares it to the
    # pinned one, raising on mismatch — the check is the whole point of asking.
    signer = FileExecutionSigner.load(
        secret_file=_secret_file(), expected_public_key=expected
    )
    return {
        "public_key": signer.public_key(),
        "matches_pinned_key": signer.public_key() == expected,
        "network": settings.REAL_WALLET_NETWORK,
        "genesis_hash": genesis,
        "can_sign": True,
    }


async def sign_intent(intent_id: uuid.UUID) -> dict[str, Any]:
    """Produce exactly one signature over one reloaded, re-verified intent.

    Nothing about the transaction is taken from the caller. It sends an ID; this
    reloads the intent from Postgres, recomputes the fingerprint from those
    authoritative fields, and hands both to `sign_jupiter_transaction`, which
    refuses unless the assembled bytes agree — so a compromised caller can ask
    for a signature and still not choose what gets signed.

    The replay guard is the database, not this process: `transaction_signature`
    carries a unique index, so the same signature cannot attach to a second
    intent even if two signers ran at once.
    """
    genesis = await _verified_chain()
    expected = settings.REAL_WALLET_PUBLIC_KEY.strip()
    if not expected:
        raise MainnetSignerError("mainnet_signer_pinned_key_not_configured")

    async with SessionFactory() as session:
        repo = LiveIntentRepository(session)
        intent = await repo.by_id(intent_id)
        if intent is None:
            raise MainnetSignerError("intent_not_found")
        # Signing is legal from exactly one state; anything else is a replay or
        # a caller that skipped a barrier.
        if intent.state != ExecutionState.ORDER_CREATED:
            raise MainnetSignerError(f"intent_not_signable:{intent.state}")
        if intent.wallet_public_key != expected:
            raise MainnetSignerError("intent_wallet_is_not_this_signer")

        evidence = intent.order_evidence or {}
        encoded = evidence.get("unsigned_transaction")
        if not encoded:
            raise MainnetSignerError("intent_has_no_unsigned_transaction")
        for field in ("input_mint", "output_mint", "jupiter_request_id"):
            if not getattr(intent, field, None):
                raise MainnetSignerError(f"intent_missing_{field}")
        raw_amount = evidence.get("input_amount_raw")
        if raw_amount is None:
            raise MainnetSignerError("intent_missing_input_amount")

        # Recomputed from the intent this process loaded, never from the caller
        # and never from the Jupiter response.
        fingerprint = tx_inspect.intent_fingerprint(
            intent_id=str(intent.id),
            side=intent.side,
            wallet_public_key=intent.wallet_public_key,
            input_mint=intent.input_mint,
            output_mint=intent.output_mint,
            input_amount_raw=int(raw_amount),
            request_id=intent.jupiter_request_id,
            max_slippage_bps=int(settings.REAL_WALLET_EXIT_MAX_SLIPPAGE_BPS),
        )
        signer = FileExecutionSigner.load(
            secret_file=_secret_file(), expected_public_key=expected
        )
        try:
            signed = signer.sign_jupiter_transaction(
                encoded,
                expected_intent_fingerprint=evidence.get("intent_fingerprint"),
                intent_fingerprint_value=fingerprint,
                allowed_programs=_allowed_programs(),
            )
        except ExecutionTransactionValidationError as exc:
            logger.warning("mainnet_signer_refused_transaction",
                           intent_id=str(intent_id), reason=str(exc))
            raise MainnetSignerError(f"transaction_rejected:{exc}") from exc

    logger.warning("mainnet_signer_signed", intent_id=str(intent_id),
                   genesis=genesis[:12], programs=list(signed.program_ids))
    return {
        "signed_transaction": signed.signed_transaction,
        "signature": signed.signature,
        "message_fingerprint": signed.message_fingerprint,
    }


async def _handle_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        raw = await asyncio.wait_for(reader.readline(), timeout=10)
        body = json.loads(raw.decode("utf-8"))
        if not isinstance(body, dict):
            raise MainnetSignerError("invalid_signer_request")
        op = body.get("op")
        if op == IDENTITY:
            response: dict[str, Any] = {"ok": True, **(await identity())}
        elif op == "sign":
            raw_id = body.get("intent_id")
            if not isinstance(raw_id, str):
                raise MainnetSignerError("invalid_signer_request")
            response = {"ok": True, **(await sign_intent(uuid.UUID(raw_id)))}
        else:
            raise MainnetSignerError("unsupported_signer_operation")
    except Exception as exc:  # noqa: BLE001 - the wire must never carry a traceback
        response = {"ok": False, "error": str(exc) or type(exc).__name__}
    writer.write((json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8"))
    await writer.drain()
    writer.close()
    await writer.wait_closed()


def _prepare_socket(socket_path: Path) -> None:
    socket_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    if socket_path.exists():
        if not socket_path.is_socket():
            raise MainnetSignerError("refusing_to_replace_non_socket")
        socket_path.unlink()


async def serve(socket_path: Path) -> None:
    await asyncio.to_thread(_prepare_socket, socket_path)
    server = await asyncio.start_unix_server(_handle_connection, path=str(socket_path))
    os.chmod(socket_path, 0o660)
    logger.info("mainnet_signer_listening", socket=str(socket_path))
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MEMESCOPE isolated mainnet signer (identity only)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--identity", action="store_true")
    group.add_argument("--serve", action="store_true")
    parser.add_argument("--socket", type=Path)
    args = parser.parse_args()
    if args.identity:
        print(json.dumps(asyncio.run(identity()), separators=(",", ":")))  # noqa: T201
        return
    configured = settings.MAINNET_SIGNER_SOCKET.strip()
    if args.socket is None and not configured:
        raise MainnetSignerError("mainnet_signer_socket_not_configured")
    asyncio.run(serve(args.socket or Path(configured)))


if __name__ == "__main__":
    main()
