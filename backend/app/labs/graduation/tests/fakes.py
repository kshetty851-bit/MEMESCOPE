"""Stand-ins for the socket, the node, the market APIs and the database."""

from __future__ import annotations

import struct
from datetime import datetime
from types import TracebackType
from typing import Any, Self

from app.labs.graduation import config
from app.services.curve.state import CurveState


def account_bytes(state: CurveState) -> bytes:
    """A curve account as the chain would serve it, discriminator and all."""
    return (config.CURVE_DISCRIMINATOR + struct.pack(
        "<QQQQQ", state.virtual_token_reserves, state.virtual_sol_reserves,
        state.real_token_reserves, state.real_sol_reserves,
        state.token_total_supply)
        + bytes([1 if state.complete else 0]) + b"\x00" * 102)


def curve_state(real_token: int = 793100000000000, *, complete: bool = False,
                real_sol: int = 6) -> CurveState:
    """A curve at a given fill. Virtual reserves follow the real ones, as the
    constant product requires."""
    return CurveState(
        virtual_token_reserves=279900000000000 + real_token,
        virtual_sol_reserves=30000000000 + real_sol,
        real_token_reserves=real_token,
        real_sol_reserves=real_sol,
        token_total_supply=1000000000000000,
        complete=complete,
    )


class FakeStream:
    """A websocket that replays a list and never connects."""

    def __init__(self, messages: list[dict] | None = None) -> None:
        self._messages = messages or []
        self.connected = True
        self.reconnects = 0
        self.messages_received = 0
        self.stopped = False

    async def messages(self):
        for message in self._messages:
            self.messages_received += 1
            yield message

    def stop(self) -> None:
        self.stopped = True


class FakeRPC:
    """A node that answers from a dict, and records what it was asked."""

    def __init__(self, readings: dict[str, CurveState | None] | None = None,
                 *, unreadable: set[str] | None = None) -> None:
        self.readings = readings or {}
        #: Mints the read simply did NOT happen for — absent from the result,
        #: which is a different claim from "no curve".
        self.unreadable = unreadable or set()
        self.fetches: list[list[str]] = []
        self.forgotten: set[str] = set()
        self.calls = 0
        self.failures = 0
        self.rate_limited = 0
        self.last_failure: str | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None,
                        exc: BaseException | None, tb: TracebackType | None) -> None:
        return None

    def address_for(self, mint: str) -> str | None:
        return f"curve-of-{mint}"

    def forget(self, mints) -> None:
        self.forgotten |= set(mints)

    async def fetch(self, mints):
        self.fetches.append(list(mints))
        self.calls += 1
        return {m: self.readings.get(m) for m in mints if m not in self.unreadable}


class FakeMarket:
    """DexScreener and GeckoTerminal, canned."""

    def __init__(self, pairs=None, candles=None) -> None:
        self.pairs = pairs or []
        self.candles = candles or []
        self.pair_calls: list[list[str]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None,
                        exc: BaseException | None, tb: TracebackType | None) -> None:
        return None

    async def dex_pairs(self, mints):
        self.pair_calls.append(list(mints))
        wanted = set(mints)
        return [p for p in self.pairs
                if (p.get("baseToken") or {}).get("address") in wanted]

    async def gecko_minute_ohlcv(self, pool, *, limit):
        return self.candles


class FakeSession:
    """Swallows statements and counts commits, so `flush()` is exercisable."""

    def __init__(self, log: list[Any]) -> None:
        self._log = log
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None,
                        exc: BaseException | None, tb: TracebackType | None) -> None:
        return None

    async def execute(self, statement: Any) -> None:
        self._log.append(statement)

    async def commit(self) -> None:
        self.commits += 1


class FakeSessionFactory:
    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.sessions: list[FakeSession] = []

    def __call__(self) -> FakeSession:
        session = FakeSession(self.statements)
        self.sessions.append(session)
        return session

    def table_names(self) -> list[str]:
        """The table each recorded statement targets, in order."""
        names = []
        for statement in self.statements:
            table = getattr(statement, "table", None)
            names.append(getattr(table, "name", type(statement).__name__))
        return names


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now
