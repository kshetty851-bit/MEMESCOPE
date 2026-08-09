"""Generate a dedicated, low-balance Solana execution wallet locally.

Run explicitly on the operator's secure machine, for example:
``python -m app.real_wallet.generate_wallet --output /secure/path/memescope.json``.
The command never contacts Solana and never sends funds.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from solders.keypair import Keypair


def generate_wallet_file(output: Path) -> str:
    """Create a non-overwritable `solana-keygen`-compatible JSON keypair file."""
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    keypair = Keypair()
    payload = json.dumps(list(bytes(keypair)), separators=(",", ":")).encode("utf-8")
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise FileExistsError(f"refusing to overwrite existing secret file: {output}") from exc
    with os.fdopen(descriptor, "wb") as secret_file:
        secret_file.write(payload)
    return str(keypair.pubkey())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a dedicated MEMESCOPE execution wallet"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="secure local JSON keypair path"
    )
    args = parser.parse_args()
    public_key = generate_wallet_file(args.output)
    print(f"PUBLIC ADDRESS: {public_key}")  # noqa: T201 - explicit operator command output
    print(  # noqa: T201
        f"SECRET MATERIAL: saved only to {args.output} (mode 0600); never share or commit it."
    )
    print("BACK UP OFFLINE NOW before funding. MEMESCOPE cannot recover this secret for you.")  # noqa: T201


if __name__ == "__main__":
    main()
