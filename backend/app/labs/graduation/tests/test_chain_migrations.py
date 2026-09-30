"""The on-chain backup for graduations (2026-09-30): pump.fun's migration
event decoded from a REAL mainnet transaction, the listener, and the recorder
keeping only the first report of a mint from either source."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from app.labs.graduation import config
from app.labs.graduation.parse import MigrationRow, chain_migration
from app.labs.graduation.sources import ChainMigrationStream
from app.labs.graduation.tests.test_parse import by_signature
from app.labs.graduation.tests.test_recorder import MINT, START, build

#: Mainnet, 2026-09-30: MigrateV2 of Gu2bpydt5bHVHtko5vvsWH5KQUT3Wxvt6hzYvKdND6ur.
SIG = "4o3x4vqtYmhqVZZS7wWV1NoePZqFpcnnKwZugso2VYq3mg7bMSxJ7Nb6JLy1FDgvqxcXe81ZbmXVBucwEMjtFY3L"
EVENT = ("Program data: velduVyU6pR5syl9Y/fz65admv7nJIovNlWDCH2Y954qauspuQDisuwzUMyokBlI9He9bDJYZL"
         "BdKpH/XoIk1hamctkkqmJdAAgBqSy8AAAF99HJEwAAAMHh5AAAAAAAMoHGAnbACdz3Aovqgja6G775Z0zt9dicAH"
         "fAL5D4BdekM71qAAAAAAdiat/7kUlZ19grEIFCFjyGZe3q4Tdy97klho7bjE4UAAAAAAAAAAAAAAAAAAAAAAAAAA"
         "AAAAAAAAAAAAAAAAA=")
LOGS = ["Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke [1]",
        "Program log: Instruction: MigrateV2",
        "Program data: not base64 at all!!",
        EVENT,
        "Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P success"]


def test_the_real_migration_event_decodes_to_its_coin_pool_and_time():
    row = chain_migration(SIG, LOGS)
    assert row is not None
    assert row.mint == "Gu2bpydt5bHVHtko5vvsWH5KQUT3Wxvt6hzYvKdND6ur"
    assert row.ts == datetime.fromtimestamp(1790784420, UTC)       # == block time
    assert (row.pool, row.signature) == (config.PUMPSWAP_VENUE, SIG)
    assert row.raw["pool_address"] == "Vptu7kbcUHWNHKSCw1Qn1MhgP9fqKmQnTAzTqETCAs5"
    assert round(row.raw["sol"], 2) == 84.99 and row.raw["source"] == "chain"


def test_a_migrate_call_that_did_nothing_is_not_a_graduation():
    assert chain_migration(SIG, LOGS[:3] + LOGS[4:]) is None
    assert chain_migration(SIG, None) is None


def _chain_row(mint: str = MINT) -> MigrationRow:
    return MigrationRow(mint=mint, ts=START, pool=config.PUMPSWAP_VENUE, signature="sigChain",
                        raw={"source": "chain"})


async def test_the_first_report_of_a_graduation_wins_from_either_source():
    recorder, *_ = build()
    recorder.handle(by_signature("sigMigrate0"), START)     # PumpPortal first
    recorder._on_migration(_chain_row())                     # the chain agrees later
    assert len(recorder._migrations) == 1
    assert recorder._migrated[MINT] == "pumpportal"

    recorder, *_ = build()
    recorder._on_migration(_chain_row())                     # the chain first
    recorder.handle(by_signature("sigMigrate0"), START)
    assert [m["raw"]["source"] for m in recorder._migrations] == ["chain"]
    assert recorder._migrated[MINT] == "chain"


async def test_a_graduation_only_the_chain_saw_is_recorded_and_sampled():
    recorder, *_ = build()
    recorder._on_migration(_chain_row("OnlyOnChain111111111111111111111111111pump"))
    assert recorder._migrations[0]["mint"] == "OnlyOnChain111111111111111111111111111pump"
    assert "OnlyOnChain111111111111111111111111111pump" in recorder.postgrad.states


class _Socket:
    def __init__(self, frames):
        self.frames, self.sent = list(frames), []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        if self.frames:
            return self.frames.pop(0)
        await asyncio.sleep(3600)


def _frame(err, logs):
    return json.dumps({"method": "logsNotification", "params": {"result": {"value": {
        "signature": SIG, "err": err, "logs": logs}}}})


async def test_the_listener_subscribes_to_the_migration_account_and_yields_graduations():
    socket = _Socket([json.dumps({"jsonrpc": "2.0", "result": 7, "id": 1}),   # subscribed
                      _frame({"InstructionError": [0, "x"]}, LOGS),          # failed tx
                      _frame(None, LOGS[:1]),                                 # no event
                      _frame(None, LOGS)])
    stream = ChainMigrationStream(url="wss://test", connect=lambda *a, **k: socket)
    got = []
    async for row in stream.migrations():
        got.append(row)
        stream.stop()
        break
    assert [r.mint for r in got] == ["Gu2bpydt5bHVHtko5vvsWH5KQUT3Wxvt6hzYvKdND6ur"]
    assert socket.sent[0]["method"] == "logsSubscribe"
    assert socket.sent[0]["params"][0] == {"mentions": [config.PUMP_MIGRATION_ACCOUNT]}
