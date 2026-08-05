"""Bonding curve collection: derive, fetch, parse, append.

Sits beside market enrichment rather than inside it. The two answer different
questions from different sources — DexScreener reports a pair, the chain reports
the curve — and a provider outage on one must never stop the other, which is the
same separation the scanner and enrichment already hold.

    mints ──▶ derive PDA (local, pure) ──▶ getMultipleAccounts (batched)
                                                    │
                                              parse + invariants
                                                    │
                                          token_curve_snapshots (append-only)

**Batched by construction.** `getMultipleAccounts` takes up to 100 addresses,
and deriving the address locally is what makes that possible — there is no
lookup to do first. One RPC call per hundred tokens rather than one per token
is the difference between this being affordable and not.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.repositories.curve import CurveSnapshotRepository
from app.services.curve.pda import InvalidAddressError, bonding_curve_address
from app.services.curve.state import CurveReading, parse
from app.services.rpc.base import RpcError, SolanaRPC
from app.services.rpc.registry import get_rpc

logger = get_logger(__name__)

#: `getMultipleAccounts` accepts at most 100 addresses per request.
MAX_ACCOUNTS_PER_CALL = 100


@dataclass
class CollectionOutcome:
    """What one pass did. Counts only, so it logs cleanly."""

    requested: int = 0
    addressed: int = 0
    fetched: int = 0
    parsed: int = 0
    written: int = 0
    absent: int = 0
    unparsable: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {
            "requested": self.requested,
            "addressed": self.addressed,
            "fetched": self.fetched,
            "parsed": self.parsed,
            "written": self.written,
            "absent": self.absent,
            "unparsable": self.unparsable,
            "failed": self.failed,
        }


class BondingCurveCollector:
    """Reads bonding curve accounts and appends them to the history."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        rpc: SolanaRPC | None = None,
        program_id: str | None = None,
    ) -> None:
        self._repository = CurveSnapshotRepository(session)
        self._rpc = rpc
        self._owns_client = rpc is None
        self._program_id = program_id or settings.PUMPFUN_PROGRAM_ID

    # --- Address derivation ---------------------------------------------------

    def addresses_for(self, mints: Sequence[str]) -> dict[str, str]:
        """Curve address per mint, skipping any that cannot be derived.

        A malformed mint is logged and dropped rather than failing the batch:
        one bad row must not cost the other ninety-nine tokens their reading.
        """
        derived: dict[str, str] = {}
        for mint in dict.fromkeys(mints):
            try:
                derived[mint] = bonding_curve_address(mint, program_id=self._program_id)
            except (InvalidAddressError, ValueError) as exc:
                logger.warning("curve_address_underivable", mint=mint, error=str(exc))
        return derived

    # --- Collection -----------------------------------------------------------

    async def collect(
        self, mints: Sequence[str], *, now: datetime | None = None
    ) -> CollectionOutcome:
        """Read every curve for these mints and append what parsed."""
        moment = now or datetime.now(UTC)
        outcome = CollectionOutcome(requested=len(set(mints)))
        if not mints:
            return outcome

        addresses = self.addresses_for(mints)
        outcome.addressed = len(addresses)
        if not addresses:
            return outcome

        readings = await self._fetch(addresses, outcome=outcome)
        outcome.parsed = len(readings)
        if readings:
            outcome.written = await self._repository.append(readings, captured_at=moment)

        logger.info("curve_collection_completed", **outcome.as_dict())
        return outcome

    async def _fetch(
        self, addresses: dict[str, str], *, outcome: CollectionOutcome
    ) -> list[CurveReading]:
        """Fetch and parse, in chunks the RPC will accept."""
        client = self._rpc or get_rpc()
        if self._owns_client:
            await client.start()

        readings: list[CurveReading] = []
        try:
            mints = list(addresses)
            for start in range(0, len(mints), MAX_ACCOUNTS_PER_CALL):
                chunk = mints[start : start + MAX_ACCOUNTS_PER_CALL]
                readings.extend(
                    await self._fetch_chunk(chunk, addresses, client=client, outcome=outcome)
                )
        finally:
            if self._owns_client:
                await client.close()
        return readings

    async def _fetch_chunk(
        self,
        mints: list[str],
        addresses: dict[str, str],
        *,
        client: SolanaRPC,
        outcome: CollectionOutcome,
    ) -> list[CurveReading]:
        """One RPC read.

        Takes the started client rather than building its own — constructing one
        here left it unstarted, which every stubbed test hid and the first live
        run surfaced immediately.
        """
        try:
            # The interface's own batched read, rather than a raw `call`. The
            # chunk limit and the "a short list is not an absent account" rule
            # are properties of the RPC, so they live with it.
            values = await client.get_multiple_accounts([addresses[mint] for mint in mints])
        except RpcError as exc:
            # A whole chunk lost. Contained and counted: the curve history is a
            # series, so a missed read costs one point rather than the token.
            outcome.failed += len(mints)
            outcome.errors.append(str(exc))
            logger.warning("curve_fetch_failed", tokens=len(mints), error=str(exc)[:200])
            return []

        readings: list[CurveReading] = []

        for mint, value in zip(mints, values, strict=False):
            if value is None:
                # No curve account. Normal for a token that never had one, and
                # for one whose account was closed after migrating.
                outcome.absent += 1
                continue

            outcome.fetched += 1
            state = parse(_decode(value))
            if state is None:
                outcome.unparsable += 1
                continue
            readings.append(CurveReading(mint_address=mint, state=state))

        return readings


def _decode(value: dict[str, object]) -> bytes:
    """Account data from an RPC value, or empty bytes.

    Tolerant on purpose: an encoding the node returns that we did not ask for
    is an absent reading, not an exception three frames away.
    """
    data = value.get("data")
    if isinstance(data, list) and data and isinstance(data[0], str):
        try:
            return base64.b64decode(data[0])
        except Exception:
            return b""
    return b""
