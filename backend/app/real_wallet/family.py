"""The user wallets: who they are, and the trade sizes one may be set to.

USER 1 … USER 10 (Karthik, 2026-09-27: "remove family wallets and give list
of 10 wallets in sequence, just name it USER 1, USER 2 etc") each have a
Solana wallet of their own (`family_wallets`) that copies the strategy he
nominated at Start, on its own switch and size. The module and table keep
their "family" names; the people in them are now numbered.

Only Karthik, signed in as the admin, can see or touch these wallets. The
family password that used to open them went with the names.
"""

from __future__ import annotations

from decimal import Decimal

MEMBERS: tuple[str, ...] = tuple(f"USER{i}" for i in range(1, 11))
#: The trade sizes a user's wallet may be set to.
TICKETS_USD: tuple[Decimal, ...] = tuple(
    Decimal(t) for t in ("10", "20", "25", "50", "100", "200"))


def label(member: str) -> str:
    """"USER7" -> "USER 7", for people to read."""
    return member.replace("USER", "USER ", 1)
