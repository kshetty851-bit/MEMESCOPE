"""What the platform needs from a Solana RPC node, and nothing vendor-specific.

The scanner, curve collection and account fetching all speak this interface.
Swapping a vendor is a config change; it touches no caller. The same division
`services/market/providers` already holds between an adapter and the service
that consumes it.

## Standard, plus one declared extension

Everything on `SolanaRPC` except `get_asset` is plain Solana JSON-RPC and works
against any compliant node — a public endpoint, a self-hosted validator, or a
paid provider.

`getAsset` is **not** standard. It is the Metaplex Digital Asset Standard read,
served by indexers rather than by validators, and a node that does not index
cannot answer it at any price. So it is modelled as a *declared capability*
rather than assumed: `supports_metadata` says whether this node can answer, and
`metadata_unavailable_reason` says why not when it cannot. A caller that finds
metadata missing learns that the node does not index it, rather than that the
token has no name.

That is the same contract every other gap on this platform honours — reported,
never omitted, and never filled in with a guess.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import TracebackType
from typing import Any, ClassVar, Self


class RpcError(RuntimeError):
    """An RPC call failed after exhausting retries."""


class RpcMethodRestrictedError(RpcError):
    """The provider refused the METHOD outright (403/404/405) — a plan or
    capability gap, deterministic for this provider but possibly served by
    another. Routers fail over without retrying and without charging the
    provider's health breaker."""


class RpcExhaustedError(RpcError):
    """Transient failures used up every attempt. Eligible for provider
    failover — unlike a deterministic JSON-RPC application error, which will
    fail identically on any node."""


class RpcRateLimitError(RpcError):
    """The node returned 429. Its own class because quota exhaustion is an
    operational condition, not a bug, and the health surface reports it as one."""


@dataclass(frozen=True, slots=True)
class RpcDescription:
    """What this node is and what it can answer. Published, so it is checkable.

    Mirrors `ProviderMeta` in the Opportunity Engine: an implementation declares
    its own limits rather than leaving a caller to discover them by getting
    nothing back.
    """

    name: str
    endpoint: str
    supports_metadata: bool
    metadata_unavailable_reason: str | None = None


class SolanaRPC(ABC):
    """One Solana RPC endpoint. Async, and safe to share across tasks.

    Implementations are constructed by `registry.get_rpc`, which is the only
    place that knows concrete classes.
    """

    #: Registry key. Set by each implementation.
    name: ClassVar[str] = "solana"

    #: Whether this node can answer the DAS metadata read. False on a plain
    #: validator, which is the honest default.
    supports_metadata: ClassVar[bool] = False

    #: Why metadata cannot be read here, when it cannot. Carried so the gap is
    #: attributable at the point a caller notices it.
    metadata_unavailable_reason: ClassVar[str | None] = None

    # --- Lifecycle -----------------------------------------------------------

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    @abstractmethod
    async def start(self) -> None:
        """Open whatever the implementation needs. Idempotent."""

    @abstractmethod
    async def close(self) -> None:
        """Release what `start` opened. Only what this instance owns."""

    @abstractmethod
    def describe(self) -> RpcDescription:
        """What this node is, for the health surface and for logs."""

    # --- Calls ---------------------------------------------------------------

    @abstractmethod
    async def call(self, method: str, params: Any, *, attempts: int = 3) -> Any:
        """Issue a JSON-RPC call and return its `result`.

        Left on the interface deliberately. Every method below is built on it,
        and a caller needing a method this interface has not named should not
        have to wait for a release to make it — the escape hatch is explicit
        rather than achieved by reaching past the abstraction.
        """

    @abstractmethod
    async def get_transaction(
        self, signature: str, *, attempts: int | None = None
    ) -> dict[str, Any] | None:
        """A parsed transaction, or `None` if it never became available.

        Polls: a transaction seconds old may not have reached the node yet, and
        that is propagation rather than an error.
        """

    @abstractmethod
    async def get_multiple_accounts(
        self, addresses: list[str], *, encoding: str = "base64"
    ) -> list[dict[str, Any] | None]:
        """Raw account data for up to 100 addresses, positionally aligned.

        `None` in a slot means the account does not exist — normal for a curve
        that was never opened or has been closed, and distinct from a failed
        read, which raises.
        """

    async def get_asset(
        self, mint_address: str, *, attempts: int | None = None
    ) -> dict[str, Any] | None:
        """DAS metadata for a mint, or `None` when this node cannot answer.

        The default is `None`, which is correct for any node that does not
        index: metadata is an *extension*, and a validator that never had it is
        not failing. Callers already treat `None` as unresolved-so-far rather
        than as absent-forever — `MetadataStatus.PENDING` exists for exactly
        this, and a later resolution needs no backfill.
        """
        return None
