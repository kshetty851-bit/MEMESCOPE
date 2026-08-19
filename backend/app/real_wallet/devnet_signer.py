"""Isolated signer process for one approved Phase 2 devnet intent.

Run this module in the dedicated ``devnet-signer`` service.  It is the only
code path that names ``PHASE2_DEVNET_SIGNER_FILE``.  The API has only a Unix
socket client and may request an intent ID, never send transaction bytes or
read the secret mount.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db.session import SessionFactory, dispose_engine
from app.real_wallet.devnet_intent import DevnetIntentState
from app.real_wallet.devnet_repository import DevnetIntentRepository
from app.real_wallet.devnet_transaction import (
    NATIVE_SOL_MINT,
    NativeTransferSpec,
    inspect_native_transfer,
    transaction_fingerprint,
)
from app.real_wallet.devnet_workflow import DevnetManualWorkflowError
from app.real_wallet.network import require_verified_devnet
from app.real_wallet.signer import (
    ExecutionSignerUnavailableError,
    ExecutionTransactionValidationError,
    FileExecutionSigner,
)
from app.services.rpc.standard import StandardSolanaRPC


class DevnetSignerError(RuntimeError):
    """The signer rejects an intent before any secret-dependent operation."""


def _signer_secret_file() -> Path:
    """Read the secret path only inside this dedicated process."""
    value = os.environ.get("PHASE2_DEVNET_SIGNER_FILE", "").strip()
    if not value:
        raise DevnetSignerError("devnet_signer_secret_file_not_configured")
    path = Path(value)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise DevnetSignerError("devnet_signer_secret_file_unavailable") from exc
    if mode & 0o077:
        raise DevnetSignerError("devnet_signer_secret_file_permissions")
    return path


async def sign_approved_intent(intent_id: uuid.UUID) -> dict[str, str]:
    """Reload, re-verify, inspect, and sign precisely one authoritative intent."""
    async with SessionFactory() as session:
        repository = DevnetIntentRepository(session)
        intent = await repository.intent_by_id(intent_id)
        if intent is None:
            raise DevnetSignerError("devnet_intent_not_found")
        if intent.state == DevnetIntentState.SIGNED and intent.transaction_signature:
            return {"intent_id": str(intent.id), "signature": intent.transaction_signature}
        if intent.state != DevnetIntentState.APPROVED:
            raise DevnetSignerError("devnet_intent_not_approved")
        now = datetime.now(UTC)
        if await repository.expire_if_needed(intent=intent, at=now):
            await session.commit()
            raise DevnetSignerError("devnet_quote_or_approval_expired")
        if intent.simulation_status != "SUCCESS" or not intent.transaction_base64:
            raise DevnetSignerError("devnet_successful_simulation_required")
        if intent.signing_status == "SIGNING":
            # A signer crash after it touched a key must never lead to a second
            # signature. Mark the ambiguous attempt terminally failed instead.
            await repository.fail(
                intent=intent,
                at=now,
                reason="signing_outcome_unknown",
                detail={"restart_recovery": True},
            )
            await session.commit()
            raise DevnetSignerError("devnet_signing_outcome_unknown")
        if not await repository.claim_signing(intent=intent, at=now):
            await session.rollback()
            refreshed = await repository.intent_by_id(intent_id)
            if (
                refreshed
                and refreshed.state == DevnetIntentState.SIGNED
                and refreshed.transaction_signature
            ):
                return {
                    "intent_id": str(refreshed.id),
                    "signature": refreshed.transaction_signature,
                }
            raise DevnetSignerError("devnet_signing_already_claimed")
        # The reservation is persisted before the secret is touched. A process
        # death after this point leaves a terminally recoverable *unknown*, not
        # an opportunity for a duplicate signature.
        await session.commit()

        try:
            spec = _spec_from_intent(intent)
            rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
            async with rpc:
                await require_verified_devnet(
                    rpc, configured_network=settings.REAL_WALLET_NETWORK
                )
            inspected = inspect_native_transfer(intent.transaction_base64, expected=spec)
            if intent.transaction_fingerprint != inspected.fingerprint:
                raise DevnetSignerError("devnet_unsigned_transaction_changed")
            signer = FileExecutionSigner.load(
                secret_file=_signer_secret_file(),
                expected_public_key=intent.wallet_public_key,
            )
            signed_transaction, signature = signer.sign_native_transaction(
                intent.transaction_base64
            )
            signed_inspection = inspect_native_transfer(signed_transaction, expected=spec)
            validation = {
                "network": "devnet",
                "network_verified": True,
                "transaction_semantics": signed_inspection.as_metadata(),
                "unsigned_transaction_fingerprint": inspected.fingerprint,
                "signed_transaction_fingerprint": transaction_fingerprint(signed_transaction),
                "signer_public_key": signer.public_key,
                "validated_at": now.isoformat(),
            }
        except (
            DevnetSignerError,
            DevnetManualWorkflowError,
            ExecutionSignerUnavailableError,
            ExecutionTransactionValidationError,
        ) as exc:
            await _record_signer_failure(session, repository, intent_id, type(exc).__name__)
            raise DevnetSignerError(type(exc).__name__) from exc
        except Exception as exc:
            await _record_signer_failure(
                session, repository, intent_id, "signer_validation_failed"
            )
            raise DevnetSignerError("signer_validation_failed") from exc

        # Reload after the commit that reserved signing: this protects against
        # a manual cancellation or expiry occurring while an isolated process
        # was performing its own network and byte-level checks.
        intent = await repository.intent_by_id(intent_id)
        if (
            intent is None
            or intent.state != DevnetIntentState.APPROVED
            or intent.signing_status != "SIGNING"
        ):
            raise DevnetSignerError("devnet_intent_changed_during_signing")
        now = datetime.now(UTC)
        if await repository.expire_if_needed(intent=intent, at=now):
            await session.commit()
            raise DevnetSignerError("devnet_quote_or_approval_expired")
        await repository.transition(
            intent=intent,
            next_state=DevnetIntentState.SIGNED,
            at=now,
            event_type="signed_by_isolated_signer",
            detail={
                "signature": signature,
                "signer_public_key": intent.wallet_public_key,
            },
            signing_status="SIGNED",
            signed_transaction_base64=signed_transaction,
            transaction_signature=signature,
            signer_validation=validation,
            signed_at=now,
        )
        await session.commit()
        return {"intent_id": str(intent.id), "signature": signature}


async def _record_signer_failure(
    session: Any, repository: DevnetIntentRepository, intent_id: uuid.UUID, reason: str
) -> None:
    intent = await repository.intent_by_id(intent_id)
    if intent is not None and intent.state == DevnetIntentState.APPROVED:
        await repository.fail(
            intent=intent,
            at=datetime.now(UTC),
            reason=reason,
            detail={"isolated_signer": True},
        )
    await session.commit()


def _spec_from_intent(intent: Any) -> NativeTransferSpec:
    """Repeat the API checks inside the signer instead of trusting its output."""
    if intent.network != "devnet" or intent.action_type != "SOL_TRANSFER":
        raise DevnetSignerError("unsupported_devnet_intent")
    if intent.input_mint != NATIVE_SOL_MINT or intent.output_mint != NATIVE_SOL_MINT:
        raise DevnetSignerError("unexpected_intent_mint")
    if not intent.destination_public_key:
        raise DevnetSignerError("intent_destination_missing")
    lamports = int(intent.input_amount_raw)
    if not 0 < lamports <= settings.PHASE2_DEVNET_MAX_TRANSFER_LAMPORTS:
        raise DevnetSignerError("intent_amount_outside_devnet_limit")
    return NativeTransferSpec(
        fee_payer=intent.wallet_public_key,
        destination=intent.destination_public_key,
        lamports=lamports,
    )


async def _handle_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        raw = await asyncio.wait_for(reader.readline(), timeout=10)
        body = json.loads(raw.decode("utf-8"))
        if not isinstance(body, dict) or not isinstance(body.get("intent_id"), str):
            raise DevnetSignerError("invalid_signer_request")
        result = await sign_approved_intent(uuid.UUID(body["intent_id"]))
        response: dict[str, Any] = {"ok": True, **result}
    except Exception as exc:
        response = {"ok": False, "error": type(exc).__name__}
    writer.write((json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8"))
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def serve(socket_path: Path) -> None:
    """Serve tiny intent-ID requests on a permission-gated Unix-domain socket."""
    await asyncio.to_thread(_prepare_socket, socket_path)
    server = await asyncio.start_unix_server(_handle_connection, path=str(socket_path))
    os.chmod(socket_path, 0o660)
    async with server:
        await server.serve_forever()


def _prepare_socket(socket_path: Path) -> None:
    """Prepare socket filesystem state outside the event loop."""
    socket_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    if socket_path.exists():
        if not socket_path.is_socket():
            raise DevnetSignerError("refusing_to_replace_non_socket")
        socket_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="MEMESCOPE isolated Phase 2 devnet signer")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--intent-id", type=uuid.UUID)
    group.add_argument("--serve", action="store_true")
    parser.add_argument("--socket", type=Path)
    args = parser.parse_args()
    try:
        if args.intent_id:
            result = asyncio.run(sign_approved_intent(args.intent_id))
            print(json.dumps(result, separators=(",", ":")))  # noqa: T201 - operator CLI result
        else:
            socket_setting = settings.PHASE2_DEVNET_SIGNER_SOCKET.strip()
            if args.socket is None and not socket_setting:
                raise DevnetSignerError("devnet_signer_socket_not_configured")
            socket_path = args.socket or Path(socket_setting)
            asyncio.run(serve(socket_path))
    finally:
        if args.serve:
            asyncio.run(dispose_engine())


if __name__ == "__main__":
    main()
