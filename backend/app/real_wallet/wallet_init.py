"""Explicit, offline initialization for a dedicated execution wallet.

This command has no RPC client, database connection, API route, or logging
integration. It writes a Solana-compatible secret file locally and prints only
the public address plus a non-secret backup manifest fingerprint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from solders.keypair import Keypair

from app.real_wallet.generate_wallet import generate_wallet_file


def _write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise FileExistsError(f"refusing to overwrite existing file: {path}") from exc
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)


def import_wallet_file(*, source: Path, output: Path) -> str:
    """Copy a valid JSON keypair once, with owner-only permissions.

    Source and output are intentionally paths rather than CLI arguments with
    key bytes. The imported value is never logged, returned, or persisted.
    """
    raw = source.read_bytes()
    try:
        values = json.loads(raw)
        if not isinstance(values, list) or not all(isinstance(value, int) for value in values):
            raise ValueError("keypair must be a JSON byte array")
        keypair = Keypair.from_bytes(bytes(values))
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError("invalid_solana_keypair_file") from exc
    _write_exclusive(output, json.dumps(list(bytes(keypair)), separators=(",", ":")).encode())
    return str(keypair.pubkey())


def write_backup_manifest(*, secret_file: Path, output: Path, public_key: str) -> None:
    """Write a non-recovery proof for the operator's offline-backup ceremony."""
    fingerprint = hashlib.sha256(secret_file.read_bytes()).hexdigest()
    payload = json.dumps(
        {
            "public_key": public_key,
            "sha256_fingerprint": fingerprint,
            "recovery_material_included": False,
            "operator_action": "Verify an encrypted offline backup separately before funding.",
        },
        indent=2,
    ).encode()
    _write_exclusive(output, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize a MEMESCOPE wallet offline")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--create", action="store_true")
    actions.add_argument("--import-from", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="new local keypair path")
    parser.add_argument(
        "--backup-manifest", type=Path, required=True, help="new non-secret backup proof path"
    )
    args = parser.parse_args()
    public_key = (
        generate_wallet_file(args.output)
        if args.create
        else import_wallet_file(source=args.import_from, output=args.output)
    )
    write_backup_manifest(
        secret_file=args.output, output=args.backup_manifest, public_key=public_key
    )
    print(f"PUBLIC ADDRESS: {public_key}")  # noqa: T201 - explicit offline operator command
    print(f"BACKUP MANIFEST: {args.backup_manifest}")  # noqa: T201
    print("No key material was printed. Verify an encrypted offline backup before funding.")  # noqa: T201


if __name__ == "__main__":
    main()
