"""Isolated mainnet signer service. Holds the key; proves identity; signs nothing yet.

## Why this exists

The ARMED rehearsal has to answer "is the signer mounted, and does it hold the
key we pinned?" — and it cannot answer that by loading the key itself, because
every application container is deliberately denied a signer path. The devnet
signer already solved the shape of this problem: a separate process owns the
secret, the API owns only a Unix socket, and an ID crosses between them rather
than key material. This is the same architecture for the mainnet wallet.

## What it will not do

**It refuses to sign.** `sign` is a named refusal, `mainnet_signing_not_implemented`,
not a missing branch — because there is no mainnet intent model to sign, and a
signer built for intents that do not exist is a speculative attack surface on
the one component whose compromise loses the wallet. When mainnet order
assembly exists, signing arrives with it, reviewed together.

So the whole service answers one question — `identity` — and that is enough to
turn `signer_ready` from an assumption into a measurement.

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
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.real_wallet.network import require_verified_network
from app.real_wallet.signer import FileExecutionSigner
from app.services.rpc.standard import StandardSolanaRPC

logger = get_logger(__name__)

#: The one operation this service performs.
IDENTITY = "identity"
#: Named, so a caller learns why rather than seeing a missing branch.
SIGN_REFUSAL = "mainnet_signing_not_implemented"


class MainnetSignerError(RuntimeError):
    """The isolated mainnet signer refused."""


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
        "can_sign": False,
        "sign_refusal": SIGN_REFUSAL,
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
            # Explicit, named, and logged: a refusal somebody can find.
            logger.warning("mainnet_signer_sign_refused", reason=SIGN_REFUSAL)
            raise MainnetSignerError(SIGN_REFUSAL)
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
