"""Issue a reset link from the server, for when email cannot deliver one.

SMTP is not always configured, and an owner locked out of the only admin
account should not have to choose between editing the database by hand and
being stuck. This issues a real token through the same service the HTTP flow
uses — same expiry, same single use, same invalidation of earlier links — and
prints the URL to the operator's terminal.

**It is not a privilege escalation path**, and deliberately not an endpoint.
Running it requires a shell on the production host, which is strictly more
access than it grants: anyone who can run it can already read and write the
users table directly. Exposing the same capability over HTTP would let an
administrator take over any account from a browser, which is a different and
much worse thing.

    python -m app.services.password_reset_cli --email owner@example.com
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from app.db.session import SessionFactory, dispose_engine
from app.services.password_reset import PasswordResetService


async def _issue(email: str) -> str:
    async with SessionFactory() as session:
        issued = await PasswordResetService(session).request(
            email=email, now=datetime.now(UTC), ip="operator-cli"
        )
        await session.commit()
    if not issued.token:
        # Same refusal the HTTP flow gives, for the same reason: this prints to
        # a terminal, but the answer should not depend on the channel.
        return "No link issued. That address has no active account."
    return PasswordResetService.reset_url(issued.token)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Issue a MEMESCOPE password-reset link from the server"
    )
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    try:
        print(asyncio.run(_issue(args.email)))  # noqa: T201 - operator CLI result
    finally:
        asyncio.run(dispose_engine())


if __name__ == "__main__":
    main()
