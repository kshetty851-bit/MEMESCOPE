"""Seed the local database with an admin account.

    python -m scripts.seed --email admin@memescope.ai --password '...'

Refuses to run against production: seed data has no business there.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionFactory
from app.models.user import User, UserRole


async def seed(email: str, password: str, display_name: str) -> int:
    if settings.is_production:
        print("Refusing to seed a production database.", file=sys.stderr)
        return 1

    async with SessionFactory() as session:
        existing = (
            await session.execute(select(User).where(User.email == email))
        ).scalars().first()

        if existing is not None:
            print(f"User {email} already exists (id={existing.id}).")
            return 0

        session.add(
            User(
                email=email,
                hashed_password=hash_password(password),
                display_name=display_name,
                role=UserRole.ADMIN,
                is_verified=True,
            )
        )
        await session.commit()

    print(f"Created admin {email}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a MemeScope admin user.")
    parser.add_argument("--email", default="admin@memescope.local")
    parser.add_argument("--password", default="ChangeMeNow123!")
    parser.add_argument("--display-name", default="MemeScope Admin")
    args = parser.parse_args()
    return asyncio.run(seed(args.email, args.password, args.display_name))


if __name__ == "__main__":
    raise SystemExit(main())
